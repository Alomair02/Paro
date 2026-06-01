"""Layout resolution from DSL AST to engine slide dictionaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from builders.common import REFERENCE
from transpiler.ast import Box, DeckAst, Node, ResolvedBlock, ResolvedSlide
from transpiler.registries import LayoutRegistry, ShapeLibrary, ThemeRegistry
from utils.converter import UnitConverter


@dataclass
class ResolvedDeck:
    """A deck resolved into the slide dicts consumed by SlideBuilder."""

    theme: dict[str, Any]
    size: str
    slide_size: dict[str, Any]
    slides: list[ResolvedSlide]
    warnings: list[str] = field(default_factory=list)

    @property
    def slide_data(self) -> list[dict[str, Any]]:
        return [slide.slide_data for slide in self.slides]


class LayoutResolver:
    """Resolve stack/grid/free/table/timeline layout into absolute EMU shapes."""

    DEFAULT_SLIDE_PAD = "0.5in"
    DEFAULT_GAP = "0.2in"
    FONT_DRIFT_THRESHOLD_PT = 4.0

    def __init__(
        self,
        theme_registry: ThemeRegistry | None = None,
        layout_registry: LayoutRegistry | None = None,
        shape_library: ShapeLibrary | None = None,
    ):
        self.theme_registry = theme_registry or ThemeRegistry()
        self.layout_registry = layout_registry or LayoutRegistry()
        self.shape_library = shape_library or ShapeLibrary()
        self._resolved_slide: ResolvedSlide | None = None
        self._slide_box: Box | None = None
        self._layout: dict[str, Any] | None = None
        self._theme: dict[str, Any] | None = None

    def resolve(self, deck: DeckAst) -> ResolvedDeck:
        slide_size = REFERENCE["slide_sizes"].get(deck.size)
        if slide_size is None:
            raise ValueError(f"Unknown slide size: {deck.size}")

        theme = self.theme_registry.get(deck.theme)
        self._theme = theme
        slide_box = Box(0, 0, slide_size["cx"], slide_size["cy"])
        resolved_slides: list[ResolvedSlide] = []

        for slide_ast in deck.slides:
            self._slide_box = slide_box
            self._layout = self.layout_registry.get(slide_ast.layout)
            slide_data = {
                "index": slide_ast.index,
                "layout": slide_ast.layout,
                "name": f"Slide {slide_ast.index}",
                "shapes": [],
            }
            self._resolved_slide = ResolvedSlide(slide_data=slide_data)
            root_node = Node(
                slide_ast.flow,
                {
                    "pad": slide_ast.attrs.get("pad", self.DEFAULT_SLIDE_PAD),
                    "gap": slide_ast.attrs.get("gap", self.DEFAULT_GAP),
                },
                slide_ast.children,
            )
            self._resolve_container(root_node, slide_box, parent_kind="slide")
            resolved_slides.append(self._resolved_slide)

        return ResolvedDeck(theme=theme, size=deck.size, slide_size=slide_size, slides=resolved_slides)

    def _resolve_node(self, node: Node, box: Box, parent_kind: str):
        if node.kind in {"stack", "grid", "free"}:
            self._resolve_container(node, self._box_for_node(node, box), parent_kind)
        elif node.kind == "text":
            self._resolve_text(node, box, parent_kind)
        elif node.kind == "image":
            self._resolve_image(node, box, parent_kind)
        elif node.kind == "shape":
            self._resolve_shape(node, box, parent_kind)
        elif node.kind == "line":
            self._resolve_line(node, box, parent_kind)
        elif node.kind == "table":
            self._resolve_table(node, box, parent_kind)
        elif node.kind == "timeline":
            self._resolve_timeline(node, box, parent_kind)
        else:
            raise ValueError(f"Unsupported AST node: {node.kind}")

    def _resolve_container(self, node: Node, box: Box, parent_kind: str):
        if node.kind == "stack":
            self._resolve_stack(node, box, parent_kind)
        elif node.kind == "grid":
            self._resolve_grid(node, box, parent_kind)
        elif node.kind == "free":
            self._resolve_free(node, box, parent_kind)
        else:
            raise ValueError(f"Unsupported container: {node.kind}")

    def _resolve_stack(self, node: Node, box: Box, parent_kind: str):
        box = self._anchored_stack_box(node, box)
        self._emit_container_background(node, box)
        inner = box.inset(self._unit(node.attrs.get("pad", "0"), min(box.w, box.h)))
        children = node.children
        self._record_sibling_font_group(children, node.kind)
        if not children:
            return

        direction = node.attrs.get("dir", "v")
        gap = self._unit(node.attrs.get("gap", self.DEFAULT_GAP), inner.w if direction == "h" else inner.h)
        slots = self._stack_slots(children, inner, direction, gap, node.attrs.get("align", "stretch"))
        for child, child_box in zip(children, slots):
            self._resolve_node(child, child_box, node.kind)

    def _resolve_grid(self, node: Node, box: Box, parent_kind: str):
        self._emit_container_background(node, box)
        inner = box.inset(self._unit(node.attrs.get("pad", "0"), min(box.w, box.h)))
        cols = int(node.attrs.get("cols", 12))
        rows = int(node.attrs.get("rows", self._grid_auto_rows(node.children)))
        gap_default = self._unit(node.attrs.get("gap", self.DEFAULT_GAP), inner.w)
        col_gap = self._unit(node.attrs.get("colgap"), inner.w, gap_default)
        row_gap = self._unit(node.attrs.get("rowgap"), inner.h, gap_default)
        col_w = (inner.w - col_gap * (cols - 1)) / cols
        row_h = (inner.h - row_gap * (rows - 1)) / rows
        self._record_sibling_font_group(node.children, node.kind)

        next_col = 1
        next_row = 1
        for child in node.children:
            col = int(child.attrs.get("col", next_col))
            row = int(child.attrs.get("row", next_row))
            colspan = int(child.attrs.get("colspan", 1))
            rowspan = int(child.attrs.get("rowspan", 1))
            self._resolved_slide.grid_placements.append(
                {
                    "cols": cols,
                    "rows": rows,
                    "col": col,
                    "row": row,
                    "colspan": colspan,
                    "rowspan": rowspan,
                    "kind": child.kind,
                }
            )
            x = round(inner.x + (col - 1) * (col_w + col_gap))
            y = round(inner.y + (row - 1) * (row_h + row_gap))
            w = round(col_w * colspan + col_gap * (colspan - 1))
            h = round(row_h * rowspan + row_gap * (rowspan - 1))
            self._resolve_node(child, Box(x, y, w, h), node.kind)
            next_col += colspan
            if next_col > cols:
                next_col = 1
                next_row += 1

    def _resolve_free(self, node: Node, box: Box, parent_kind: str):
        box = self._box_for_node(node, box)
        self._record_sibling_font_group(node.children, node.kind)
        for child in node.children:
            if child.kind == "line":
                self._resolve_line(child, box, node.kind)
                continue
            self._resolve_node(child, box, node.kind)

    def _resolve_text(self, node: Node, box: Box, parent_kind: str):
        paragraphs = self._paragraphs_from_text_node(node)
        placeholder = node.attrs.get("placeholder")
        if placeholder:
            ph = self._resolve_placeholder(placeholder, node.attrs.get("idx"))
            shape = {
                "type": "placeholder_text",
                "idx": ph["idx"],
                "placeholder_type": ph["type"],
                "name": f"{ph['type']} Placeholder",
                "paragraphs": paragraphs,
            }
            if self._has_explicit_box(node):
                shape.update(self._box_for_node(node, box).as_shape_geometry())
            self._append_shape(shape)
            ph_box = Box(ph["off"]["x"], ph["off"]["y"], ph["ext"]["cx"], ph["ext"]["cy"])
            self._record_block("text", ph_box, parent_kind, node.attrs, content=shape)
            self._resolved_slide.placeholder_refs.append(
                {"placeholder": placeholder, "idx": node.attrs.get("idx"), "layout": self._layout["name"]}
            )
            return

        actual_box = self._box_for_node(node, box)
        shape = {
            "type": "text_box",
            "name": node.attrs.get("name", "Text"),
            **actual_box.as_shape_geometry(),
            "paragraphs": paragraphs,
        }
        shape.update(self._text_body_attrs(node))
        self._append_shape(shape)
        self._record_block("text", actual_box, parent_kind, node.attrs, content=shape)

    def _resolve_image(self, node: Node, box: Box, parent_kind: str):
        if "src" not in node.attrs:
            raise ValueError("<image> requires src")
        image_attrs = self._resolve_image_attrs(node.attrs)
        if node.attrs.get("placeholder") and not self._has_explicit_box(node):
            raise ValueError("Image placeholders are not supported by the current engine without geometry")
        actual_box = self._box_for_node(node, box)
        self._append_shape(
            {
                "type": "image",
                "name": image_attrs.get("alt", Path(image_attrs["src"]).name),
                "src": image_attrs["src"],
                **actual_box.as_shape_geometry(),
            }
        )
        self._record_block("image", actual_box, parent_kind, node.attrs)

    def _resolve_shape(self, node: Node, box: Box, parent_kind: str):
        actual_box = self._box_for_node(node, box)
        shape = {
            "type": "autoshape",
            "name": f"{node.attrs.get('geom', 'rect')} Shape",
            "preset": node.attrs.get("geom", "rect"),
            "fill": self._shape_fill(node),
            **actual_box.as_shape_geometry(),
        }
        if node.attrs.get("line") == "none":
            shape["line"] = False
        elif "line" in node.attrs or "lineWidth" in node.attrs:
            shape["line"] = {
                "color": node.attrs.get("line", "dk1"),
                "width": node.attrs.get("lineWidth", "1pt"),
            }
        if "rot" in node.attrs:
            shape["rotation"] = float(node.attrs["rot"])
        text_node = next((child for child in node.children if child.kind == "text"), None)
        if text_node:
            shape["paragraphs"] = self._paragraphs_from_text_node(text_node)
        elif "text" in node.attrs:
            shape["text"] = node.attrs["text"]
        self._append_shape(shape)
        self._record_block("shape", actual_box, parent_kind, node.attrs, content=shape if ("paragraphs" in shape or "text" in shape) else None)

    def _resolve_line(self, node: Node, box: Box, parent_kind: str):
        color = node.attrs.get("color", "dk1")
        width = self._unit(node.attrs.get("width", "1pt"), min(box.w, box.h))
        if all(key in node.attrs for key in ("x1", "y1", "x2", "y2")):
            x1 = box.x + self._unit(node.attrs["x1"], box.w)
            y1 = box.y + self._unit(node.attrs["y1"], box.h)
            x2 = box.x + self._unit(node.attrs["x2"], box.w)
            y2 = box.y + self._unit(node.attrs["y2"], box.h)
        else:
            x1, x2 = box.x, box.right
            y1 = y2 = box.y + box.h // 2

        shape = {
            "type": "line",
            "name": "Line",
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "color": color,
            "width": width,
            "dash": node.attrs.get("dash", "solid"),
            "cap": node.attrs.get("cap", "flat"),
        }
        self._append_shape(shape)
        line_box = Box(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        self._record_block("line", line_box, parent_kind, node.attrs)

    def _resolve_table(self, node: Node, box: Box, parent_kind: str):
        actual_box = self._box_for_node(node, box)
        rows = [child for child in node.children if child.kind == "row"]
        if not rows:
            return

        cols = int(node.attrs.get("cols", max(len(row.children) for row in rows)))
        col_widths = self._list_units(node.attrs.get("colWidths"), cols, actual_box.w, actual_box.w / cols)
        row_heights = self._list_units(
            node.attrs.get("rowHeights"),
            len(rows),
            actual_box.h,
            actual_box.h / len(rows),
        )
        header = self._is_true(node.attrs.get("header", "false"))
        table_rows: list[dict[str, Any]] = []
        y = actual_box.y
        for row_index, row in enumerate(rows):
            x = actual_box.x
            col_index = 0
            row_cells: list[dict[str, Any]] = []
            for cell in row.children:
                colspan = int(cell.attrs.get("colspan", 1))
                rowspan = int(cell.attrs.get("rowspan", 1))
                cell_w = round(sum(col_widths[col_index : col_index + colspan]))
                cell_h = round(row_heights[row_index])
                fill = cell.attrs.get("fill")
                color = cell.attrs.get("color")
                bold = self._is_true(cell.attrs.get("bold", "false"))
                if header and row_index == 0:
                    fill = fill or node.attrs.get("headerFill", "accent1")
                    color = color or node.attrs.get("headerColor", "lt1")
                    bold = True if "bold" not in cell.attrs else bold
                fill = fill or node.attrs.get("fill", "lt1")
                line_color = node.attrs.get("line", "dk2")
                line_width = node.attrs.get("lineWidth", "0.75pt")
                cell_box = Box(round(x), round(y), cell_w, cell_h)
                cell_data = {
                    "gridSpan": colspan,
                    "rowSpan": rowspan,
                    "fill": fill,
                    "line": {"color": line_color, "width": line_width},
                    "align": cell.attrs.get("align"),
                    "valign": cell.attrs.get("valign"),
                    "paragraphs": self._paragraphs_from_cell(cell, color=color, bold=bold),
                }
                row_cells.append(cell_data)
                self._record_block("table_cell", cell_box, "table", cell.attrs, content=cell_data)
                x += cell_w
                col_index += colspan
            table_rows.append({"h": round(row_heights[row_index]), "cells": row_cells})
            y += row_heights[row_index]
        self._append_shape(
            {
                "type": "table",
                "name": "Table",
                **actual_box.as_shape_geometry(),
                "columns": [{"w": width} for width in col_widths],
                "rows": table_rows,
                "header": header,
                "headerFill": node.attrs.get("headerFill", "accent1"),
                "headerColor": node.attrs.get("headerColor", "lt1"),
                "fill": node.attrs.get("fill", "lt1"),
                "line": {"color": node.attrs.get("line", "dk2"), "width": node.attrs.get("lineWidth", "0.75pt")},
            }
        )
        self._record_block("table", actual_box, parent_kind, node.attrs)

    def _resolve_timeline(self, node: Node, box: Box, parent_kind: str):
        actual_box = self._box_for_node(node, box)
        periods = int(node.attrs["periods"])
        tasks = [child for child in node.children if child.kind == "task"]
        milestones = [child for child in node.children if child.kind == "milestone"]
        labels = self._timeline_labels(node, periods)
        label_w = min(self._unit("1.8in", actual_box.w), round(actual_box.w * 0.25))
        header_h = min(self._unit("0.36in", actual_box.h), round(actual_box.h * 0.18))
        period_w = (actual_box.w - label_w) / periods
        row_count = max(1, len(tasks))
        row_h = (actual_box.h - header_h) / row_count

        for index, label in enumerate(labels):
            label_box = Box(round(actual_box.x + label_w + index * period_w), actual_box.y, round(period_w), header_h)
            label_shape = {
                "type": "text_box",
                "name": "Timeline Period",
                **label_box.as_shape_geometry(),
                "paragraphs": [{"text": label, "align": "ctr"}],
            }
            self._append_shape(label_shape)
            self._record_block("text", label_box, "timeline", node.attrs, content=label_shape)
            self._resolve_line(
                Node(
                    "line",
                    {
                        "color": "lt2",
                        "width": "0.5pt",
                        "x1": str(label_w + index * period_w) + "emu",
                        "y1": "0emu",
                        "x2": str(label_w + index * period_w) + "emu",
                        "y2": str(actual_box.h) + "emu",
                    },
                ),
                actual_box,
                "timeline",
            )

        for row_index, task in enumerate(tasks):
            y = round(actual_box.y + header_h + row_index * row_h)
            label_box = Box(actual_box.x, y, label_w, round(row_h))
            task_label_shape = {
                "type": "text_box",
                "name": "Timeline Task Label",
                **label_box.as_shape_geometry(),
                "paragraphs": [{"text": task.attrs["label"]}],
            }
            self._append_shape(task_label_shape)
            self._record_block("text", label_box, "timeline", task.attrs, content=task_label_shape)
            start = int(task.attrs["start"])
            span = int(task.attrs.get("span", 1))
            bar_box = Box(
                round(actual_box.x + label_w + (start - 1) * period_w),
                y + round(row_h * 0.25),
                round(span * period_w),
                max(round(row_h * 0.5), self._unit("0.14in", actual_box.h)),
            )
            self._append_shape(
                {
                    "type": "autoshape",
                    "name": f"Timeline Task {task.attrs['label']}",
                    "preset": "roundRect",
                    "fill": task.attrs.get("fill", "accent1"),
                    "line": False,
                    **bar_box.as_shape_geometry(),
                }
            )
            self._record_block("timeline_task", bar_box, "timeline", task.attrs)

        marker_size = self._unit("0.14in", actual_box.w)
        for milestone in milestones:
            at = int(milestone.attrs["at"])
            x = round(actual_box.x + label_w + (at - 0.5) * period_w - marker_size / 2)
            y = actual_box.y + header_h // 2
            marker_box = Box(x, y, marker_size, marker_size)
            self._append_shape(
                {
                    "type": "autoshape",
                    "name": f"Timeline Milestone {milestone.attrs['label']}",
                    "preset": "diamond",
                    "fill": "accent3",
                    "line": False,
                    **marker_box.as_shape_geometry(),
                }
            )
            text_box = Box(x - marker_size * 2, y + marker_size, marker_size * 5, self._unit("0.25in", actual_box.h))
            milestone_label_shape = {
                "type": "text_box",
                "name": "Timeline Milestone Label",
                **text_box.as_shape_geometry(),
                "paragraphs": [{"text": milestone.attrs["label"], "align": "ctr"}],
            }
            self._append_shape(milestone_label_shape)
            self._record_block("text", text_box, "timeline", milestone.attrs, content=milestone_label_shape)
        self._record_block("timeline", actual_box, parent_kind, node.attrs)

    def _stack_slots(self, children: list[Node], box: Box, direction: str, gap: int, align: str) -> list[Box]:
        main_attr = "w" if direction == "h" else "h"
        cross_attr = "h" if direction == "h" else "w"
        main_len = box.w if direction == "h" else box.h
        cross_len = box.h if direction == "h" else box.w
        explicit_main = [
            self._unit(child.attrs[main_attr], main_len) if main_attr in child.attrs else None
            for child in children
        ]
        remaining = main_len - gap * (len(children) - 1) - sum(size or 0 for size in explicit_main)
        auto_count = sum(1 for size in explicit_main if size is None)
        auto_main = max(0, remaining // auto_count) if auto_count else 0
        slots: list[Box] = []
        cursor = box.x if direction == "h" else box.y
        for child, explicit in zip(children, explicit_main):
            main_size = explicit if explicit is not None else auto_main
            cross_size = (
                self._unit(child.attrs[cross_attr], cross_len)
                if cross_attr in child.attrs and align != "stretch"
                else cross_len
            )
            cross_pos = box.y if direction == "h" else box.x
            if align == "ctr":
                cross_pos += round((cross_len - cross_size) / 2)
            elif align == "end":
                cross_pos += round(cross_len - cross_size)
            if direction == "h":
                slots.append(Box(round(cursor), round(cross_pos), round(main_size), round(cross_size)))
            else:
                slots.append(Box(round(cross_pos), round(cursor), round(cross_size), round(main_size)))
            cursor += main_size + gap
        return slots

    def _anchored_stack_box(self, node: Node, parent: Box) -> Box:
        anchor = node.attrs.get("anchor", "none")
        if anchor == "none":
            return self._box_for_node(node, parent)

        direction = node.attrs.get("dir", "v")
        width = self._unit(node.attrs.get("w"), parent.w, parent.w if direction == "h" or anchor in {"top", "bottom", "fill"} else parent.w)
        height = self._unit(node.attrs.get("h"), parent.h, parent.h if direction == "v" or anchor in {"left", "right", "fill"} else parent.h)

        if anchor == "bottom":
            return Box(0, self._slide_box.h - height, self._slide_box.w, height)
        if anchor == "top":
            return Box(0, 0, self._slide_box.w, height)
        if anchor == "left":
            return Box(0, 0, width, self._slide_box.h)
        if anchor == "right":
            return Box(self._slide_box.w - width, 0, width, self._slide_box.h)
        if anchor == "fill":
            return Box(0, 0, self._slide_box.w, self._slide_box.h)
        return self._box_for_node(node, parent)

    def _box_for_node(self, node: Node, parent: Box) -> Box:
        x = parent.x + self._unit(node.attrs.get("x"), parent.w, 0)
        y = parent.y + self._unit(node.attrs.get("y"), parent.h, 0)
        w = self._unit(node.attrs.get("w"), parent.w, parent.w)
        h = self._unit(node.attrs.get("h"), parent.h, parent.h)
        return Box(x, y, w, h)

    def _emit_container_background(self, node: Node, box: Box):
        has_fill = node.attrs.get("fill") not in (None, "none")
        has_line = node.attrs.get("line") not in (None, "none")
        if not has_fill and not has_line:
            return
        shape = {
            "type": "autoshape",
            "name": f"{node.kind} Background",
            "preset": "roundRect" if self._unit(node.attrs.get("radius"), min(box.w, box.h), 0) else "rect",
            "fill": node.attrs.get("fill", "lt1") if has_fill else "lt1",
            **box.as_shape_geometry(),
        }
        shape["line"] = (
            {"color": node.attrs.get("line", "dk2"), "width": node.attrs.get("lineWidth", "1pt")}
            if has_line
            else False
        )
        self._append_shape(shape)
        self._record_block(f"{node.kind}_background", box, node.kind, node.attrs)

    def _paragraphs_from_text_node(self, node: Node) -> list[dict[str, Any]]:
        paragraphs = [child for child in node.children if child.kind == "p"]
        if not paragraphs:
            return [self._paragraph_from_node(Node("p", {}, [], node.text or ""), node)]
        return [self._paragraph_from_node(paragraph, node) for paragraph in paragraphs]

    def _paragraphs_from_cell(self, node: Node, color: str | None = None, bold: bool = False) -> list[dict[str, Any]]:
        paragraph_nodes = [child for child in node.children if child.kind == "p"]
        text_parent = Node("text", {"align": node.attrs.get("align", "")}, paragraph_nodes, node.text)
        paragraphs = self._paragraphs_from_text_node(text_parent)
        for paragraph in paragraphs:
            for run in paragraph.get("runs", []):
                if color and "color" not in run:
                    run["color"] = color
                if bold:
                    run["bold"] = True
        return paragraphs

    def _paragraph_from_node(self, paragraph: Node, text_parent: Node) -> dict[str, Any]:
        inherited_list = text_parent.attrs.get("list")
        level = int(paragraph.attrs.get("level", 0))
        role = paragraph.attrs.get("role", text_parent.attrs.get("role", "body"))
        role_bundle = self._type_scale(role)
        runs = self._runs_from_paragraph(
            paragraph,
            text_parent,
            role_bundle,
            self._should_emit_role_size(role_bundle, text_parent, level),
        )
        paragraph_data = {
            "text": paragraph.text,
            "runs": runs,
            "level": level,
            "align": paragraph.attrs.get("align", text_parent.attrs.get("align")),
            "bullet": paragraph.attrs.get("bullet", inherited_list),
            "role": role,
        }
        self._apply_paragraph_spacing(paragraph_data, text_parent, role_bundle)
        return paragraph_data

    def _runs_from_paragraph(
        self,
        paragraph: Node,
        text_parent: Node,
        role_bundle: dict[str, Any],
        emit_role_size: bool,
    ) -> list[dict[str, Any]]:
        run_nodes = [child for child in paragraph.children if child.kind == "run"]
        if not run_nodes:
            run_nodes = [Node("run", {}, [], paragraph.text)]
        elif paragraph.text:
            run_nodes = [Node("run", {}, [], paragraph.text)] + run_nodes
        runs: list[dict[str, Any]] = []
        for run_node in run_nodes:
            run: dict[str, Any] = {"text": run_node.text}

            bold = self._bool_attr_from_hierarchy("bold", run_node, paragraph, text_parent)
            if bold is None:
                bold = role_bundle.get("weight") == "bold"
            if bold:
                run["bold"] = True

            for attr in ("italic", "underline"):
                if self._bool_attr_from_hierarchy(attr, run_node, paragraph, text_parent):
                    run[attr] = True

            for attr in ("color", "font"):
                value = run_node.attrs.get(attr, text_parent.attrs.get(attr))
                if value:
                    run[attr] = value

            if run_node.attrs.get("link"):
                run["link"] = run_node.attrs["link"]

            size = run_node.attrs.get("size", text_parent.attrs.get("size"))
            if size:
                run["size_pt"] = self._points(size)
            elif emit_role_size and "size" in role_bundle:
                run["size_pt"] = self._scale_size_points(role_bundle["size"])

            runs.append(run)
        return runs

    def _apply_paragraph_spacing(
        self,
        paragraph_data: dict[str, Any],
        text_parent: Node,
        role_bundle: dict[str, Any],
    ):
        for attr in ("lineSpacing", "spaceBefore", "spaceAfter"):
            value = text_parent.attrs.get(attr, role_bundle.get(attr))
            if value is not None:
                paragraph_data[attr] = value

    def _type_scale(self, role: str) -> dict[str, Any]:
        scale = (self._theme or REFERENCE["default_theme"]).get(
            "typeScale",
            REFERENCE["default_theme"]["typeScale"],
        )
        try:
            return scale[role]
        except KeyError as exc:
            raise ValueError(f"Unknown type role: {role}") from exc

    def _should_emit_role_size(
        self,
        role_bundle: dict[str, Any],
        text_parent: Node,
        level: int,
    ) -> bool:
        if "size" in text_parent.attrs or "size" not in role_bundle:
            return False
        inherited_size = self._placeholder_inherited_size_points(
            text_parent.attrs.get("placeholder"),
            level,
        )
        if inherited_size is None:
            return True
        return abs(self._scale_size_points(role_bundle["size"]) - inherited_size) > 0.001

    def _placeholder_inherited_size_points(self, placeholder: str | None, level: int) -> float | None:
        if not placeholder:
            return None
        normalized = self._normalize_placeholder(placeholder)
        master_styles = REFERENCE["master_text_styles"]
        style = master_styles["placeholder_style"].get(normalized)
        if style == "title":
            return float(master_styles["title"]["size"])
        if style == "other":
            return float(master_styles["other"]["size"])
        if style == "body":
            level_sizes = master_styles["body_level_sizes"]
            return float(level_sizes[min(max(level, 0), len(level_sizes) - 1)])
        return None

    def _scale_size_points(self, value: str | int | float) -> float:
        if isinstance(value, str):
            return self._points(value if not value.replace(".", "", 1).isdigit() else f"{value}pt")
        return float(value)

    def _bool_attr_from_hierarchy(self, attr: str, run: Node, paragraph: Node, text_parent: Node) -> bool | None:
        for attrs in (run.attrs, paragraph.attrs, text_parent.attrs):
            if attr in attrs:
                return self._is_true(attrs[attr])
        return None

    def _text_body_attrs(self, node: Node) -> dict[str, str]:
        attrs = {}
        if "wrap" in node.attrs:
            attrs["wrap"] = node.attrs["wrap"]
        if "anchor" in node.attrs:
            attrs["anchor"] = node.attrs["anchor"]
        return attrs

    def _resolve_placeholder(self, placeholder: str, idx: str | None) -> dict[str, Any]:
        normalized = self._normalize_placeholder(placeholder)
        candidates = [
            ph
            for ph in self._layout["placeholders"]
            if ph["type"] == normalized or (normalized == "title" and ph["type"] == "ctrTitle")
        ]
        if idx is not None:
            for ph in self._layout["placeholders"]:
                if str(ph["idx"]) == str(idx):
                    return ph
        if not candidates:
            return {"idx": idx or 0, "type": normalized, "off": {"x": 0, "y": 0}, "ext": {"cx": 0, "cy": 0}}
        if len(candidates) > 1:
            raise ValueError(f"Placeholder '{placeholder}' is ambiguous; add idx")
        return candidates[0]

    def _normalize_placeholder(self, placeholder: str) -> str:
        aliases = {
            "subtitle": "subTitle",
            "subTitle": "subTitle",
            "ctrtitle": "ctrTitle",
            "ctrTitle": "ctrTitle",
        }
        return aliases.get(placeholder, aliases.get(placeholder.lower(), placeholder))

    def _record_sibling_font_group(self, children: list[Node], parent_kind: str):
        group = []
        for child in children:
            if child.kind == "text" and "size" in child.attrs:
                group.append(
                    {
                        "kind": "text",
                        "parent_kind": parent_kind,
                        "size_pt": self._points(child.attrs["size"]),
                        "text": child.text,
                    }
                )
        if len(group) > 1:
            self._resolved_slide.sibling_font_groups.append(group)

    def _record_block(
        self,
        kind: str,
        box: Box,
        parent_kind: str,
        attrs: dict[str, Any],
        content: dict[str, Any] | None = None,
    ):
        self._resolved_slide.blocks.append(
            ResolvedBlock(kind=kind, box=box, parent_kind=parent_kind, attrs=dict(attrs), content=content)
        )

    def _append_shape(self, shape: dict[str, Any]):
        self._resolved_slide.slide_data["shapes"].append(shape)

    def _grid_auto_rows(self, children: list[Node]) -> int:
        highest = 1
        for child in children:
            row = int(child.attrs.get("row", highest))
            rowspan = int(child.attrs.get("rowspan", 1))
            highest = max(highest, row + rowspan - 1)
        return highest

    def _timeline_labels(self, node: Node, periods: int) -> list[str]:
        if "labels" not in node.attrs:
            return [f"Week {index}" for index in range(1, periods + 1)]
        labels = [label.strip() for label in node.attrs["labels"].split(",")]
        return (labels + [f"Week {index}" for index in range(len(labels) + 1, periods + 1)])[:periods]

    def _list_units(self, value: str | None, count: int, parent: int, default: float) -> list[int]:
        if not value:
            return [round(default) for _ in range(count)]
        items = [item.strip() for item in value.split(",")]
        values = [self._unit(item, parent) for item in items]
        while len(values) < count:
            values.append(round(default))
        return values[:count]

    def _shape_fill(self, node: Node) -> str:
        fill = node.attrs.get("fill")
        if fill in (None, "none"):
            return "none"
        return fill

    def _resolve_image_attrs(self, attrs: dict[str, str]) -> dict[str, str]:
        src = attrs["src"]
        if self._is_named_asset_ref(src):
            name = src.removeprefix("asset:")
            asset = self.shape_library.get(name)
            merged = dict(asset)
            merged.update({key: value for key, value in attrs.items() if key != "src"})
            if "src" not in merged:
                raise ValueError(f"Named asset '{name}' does not define src")
            return merged
        return dict(attrs)

    def _is_named_asset_ref(self, src: str) -> bool:
        if src.startswith("asset:"):
            return True
        return "/" not in src and "\\" not in src and "." not in Path(src).name

    def _has_explicit_box(self, node: Node) -> bool:
        return all(key in node.attrs for key in ("x", "y", "w", "h"))

    def _unit(self, value: Any, parent_length: int, default: int | float | None = None) -> int:
        if value is None:
            if default is None:
                raise ValueError("Missing unit value")
            return round(default)
        if isinstance(value, (int, float)):
            return round(value)
        text = str(value).strip()
        if text in {"0", "+0", "-0", "0.0", "+0.0", "-0.0"}:
            return 0
        if text.endswith("%"):
            return round(parent_length * float(text[:-1]) / 100)
        return UnitConverter.to_emu(text)

    def _points(self, value: str | int | float) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        return UnitConverter.to_emu(value) / UnitConverter.CONVERSION_FACTORS["pt"]

    def _is_true(self, value: str | bool | None) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").lower() in {"1", "true", "yes"}
