"""Layout resolution from DSL AST to engine slide dictionaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from builders.common import REFERENCE
from transpiler.ast import Box, DeckAst, Node, ResolvedBlock, ResolvedSlide
from transpiler.registries import LayoutRegistry, ShapeLibrary, ThemeRegistry, TimelineStyleRegistry, ChartStyleRegistry
from transpiler.text_metrics import TextMeasurer
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

    # Default type-scale role for text bound to a layout placeholder. Without
    # this, placeholder text fell back to the "body" role and a title
    # placeholder was emitted at body size — the flat-deck footgun.
    PLACEHOLDER_DEFAULT_ROLES = {
        "title": "title",
        "ctrTitle": "title",
        "subTitle": "subheading",
        "body": "body",
    }

    # Valid a:headEnd/a:tailEnd marker types for <line head=/tail=>.
    LINE_END_TYPES = frozenset({"none", "triangle", "stealth", "diamond", "oval", "arrow"})

    # <run field=> DSL names -> a:fld type values.
    RUN_FIELD_TYPES = {"slidenum": "slidenum", "slideNumber": "slidenum"}

    def __init__(
        self,
        theme_registry: ThemeRegistry | None = None,
        layout_registry: LayoutRegistry | None = None,
        shape_library: ShapeLibrary | None = None,
        timeline_style_registry: TimelineStyleRegistry | None = None,
        chart_style_registry: ChartStyleRegistry | None = None,
    ):
        self.theme_registry = theme_registry or ThemeRegistry()
        self.layout_registry = layout_registry or LayoutRegistry()
        self.shape_library = shape_library or ShapeLibrary()
        self.timeline_style_registry = timeline_style_registry or TimelineStyleRegistry()
        self.chart_style_registry = chart_style_registry or ChartStyleRegistry()
        self.text_measurer = TextMeasurer()
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
            background = slide_ast.attrs.get("background", deck.background)
            if background:
                slide_data["background"] = self._resolve_background(background)
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
        elif node.kind == "chart":
            self._resolve_chart(node, box, parent_kind)
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
        slots = self._stack_slots(
            children,
            inner,
            direction,
            gap,
            node.attrs.get("align", "stretch"),
            node.attrs.get("justify", "start"),
        )
        for child, child_box in zip(children, slots):
            self._resolve_node(child, child_box, node.kind)

    def _resolve_grid(self, node: Node, box: Box, parent_kind: str):
        self._emit_container_background(node, box)
        inner = box.inset(self._unit(node.attrs.get("pad", "0"), min(box.w, box.h)))
        cols = int(node.attrs.get("cols", 12))
        rows = int(node.attrs.get("rows", self._grid_auto_rows(node.children, cols)))
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
        # box was already resolved by _resolve_node at dispatch (as for
        # stack/grid). Re-applying _box_for_node here double-applied the
        # container's own offset to every child (probe finding #3).
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
        fit = image_attrs.get("fit", "contain")
        if fit not in {"contain", "cover", "stretch"}:
            raise ValueError(f"Unsupported image fit mode: {fit}")

        placeholder = node.attrs.get("placeholder")
        shape = {
            "type": "image",
            "name": image_attrs.get("alt", Path(image_attrs["src"]).name),
            "src": image_attrs["src"],
            "fit": fit,
        }
        if self._is_true(image_attrs.get("grayscale", "false")):
            shape["grayscale"] = True
        if "duotone" in image_attrs:
            tokens = str(image_attrs["duotone"]).replace(",", " ").split()
            if len(tokens) == 1:
                tokens.append("FFFFFF")  # one color = wash over white highlights
            if len(tokens) != 2:
                raise ValueError("Image duotone takes one or two colors: 'dark [light]'")
            shape["duotone"] = tokens
        if "alpha" in image_attrs:
            shape["alpha"] = self._percent_thousandths(image_attrs["alpha"])

        if placeholder:
            ph = self._resolve_placeholder(placeholder, node.attrs.get("idx"))
            shape["idx"] = ph["idx"]
            shape["placeholder_type"] = ph["type"]
            ph_box = Box(ph["off"]["x"], ph["off"]["y"], ph["ext"]["cx"], ph["ext"]["cy"])
            self._resolved_slide.placeholder_refs.append(
                {"placeholder": placeholder, "idx": node.attrs.get("idx"), "layout": self._layout["name"]}
            )
            if not self._has_explicit_box(node):
                _, crop = self._fit_image_box(image_attrs["src"], ph_box, fit)
                if crop:
                    shape["crop"] = crop
                self._append_shape(shape)
                self._record_block("image", ph_box, parent_kind, node.attrs, content=shape)
                return

        actual_box = self._box_for_node(node, box)
        fitted_box, crop = self._fit_image_box(image_attrs["src"], actual_box, fit)
        shape.update(fitted_box.as_shape_geometry())
        if crop:
            shape["crop"] = crop
        self._append_shape(shape)
        self._record_block("image", fitted_box, parent_kind, node.attrs, content=shape)

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
        if self._is_true(node.attrs.get("flipH", "false")):
            shape["flipH"] = True
        if self._is_true(node.attrs.get("flipV", "false")):
            shape["flipV"] = True
        if "adj" in node.attrs:
            shape["adjustments"] = self._parse_adjustments(node.attrs["adj"])
        if "alpha" in node.attrs:
            if shape["fill"] == "none":
                raise ValueError("Shape alpha requires a fill")
            shape["fill_style"] = {
                "type": "solid",
                "color": shape["fill"],
                "transforms": {"alpha": self._percent_thousandths(node.attrs["alpha"])},
            }
        if self._is_true(node.attrs.get("shadow", "false")):
            shape["effects"] = {
                "shadow": {"blur": "2.5pt", "dist": "1pt", "dir": 2700000, "alpha": 14000}
            }
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
        for end in ("head", "tail"):
            if end in node.attrs:
                kind = node.attrs[end]
                if kind not in self.LINE_END_TYPES:
                    raise ValueError(
                        f"Unknown line {end} marker {kind!r}; expected one of {sorted(self.LINE_END_TYPES)}"
                    )
                shape[end] = kind
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
        if periods < 1:
            raise ValueError("<timeline> periods must be at least 1")

        style = self.timeline_style_registry.get(node.attrs.get("style"))
        if style.get("mechanism") != "bars-in-columns":
            raise ValueError(f"Unsupported timeline mechanism: {style.get('mechanism')}")

        style = self._timeline_style_with_finish(node, style)
        self._resolve_timeline_bars_in_columns(node, actual_box, periods, style)
        self._record_block("timeline", actual_box, parent_kind, node.attrs)

    def _resolve_chart(self, node: Node, box: Box, parent_kind: str):
        actual_box = self._box_for_node(node, box)

        chart_type = node.attrs["type"]
        CLASSIC = {"bar", "column", "line", "pie", "area", "scatter", "combo", "radar"}
        CHARTEX = {"funnel", "waterfall", "histogram", "boxWhisker", "pareto", "treemap", "sunburst"}
        if chart_type not in CLASSIC | CHARTEX:
            raise ValueError(f"Unsupported chart type: {chart_type}")
        
        if chart_type in ("treemap", "sunburst"):
            records = []
            def walk(nd, ancestry):
                kids = [c for c in nd.children if c.kind == "node"]
                label = nd.attrs["label"]
                if not kids:                                   # leaf: has value, no child nodes
                    records.append({
                        "path": ancestry + [label],
                        "value": self._chart_number(nd.attrs["value"]),
                    })
                else:
                    for k in kids:
                        walk(k, ancestry + [label])
            for top in [c for c in node.children if c.kind == "node"]:
                walk(top, [])
            if not records:
                raise ValueError(f"<chart type='{chart_type}'> requires nested <node> children")
            depths = {len(r["path"]) for r in records}
            if len(depths) != 1:
                raise ValueError(f"{chart_type} requires uniform leaf depth; got {sorted(depths)}")

            style = self.chart_style_registry.get(node.attrs.get("style"))
            finish = self.chart_style_registry.get_finish(node.attrs.get("finish", style.get("finish")))
            shape = {
                "type": chart_type,
                "name": node.attrs.get("title", "Chart"),
                "chart_type": chart_type,
                "title": node.attrs.get("title"),
                "categories": [],
                "series": [{"name": node.attrs.get("seriesName", "Size"), "points": records}],
                "legend": node.attrs.get("legend"),
                "style": style,
                "finish": finish,
                **actual_box.as_shape_geometry(),
            }
            self._append_shape(shape)
            self._record_block("chart", actual_box, parent_kind, node.attrs, content=shape)
            return
        # categories: a comma string in the <categories> child's text
        cat_node = next((c for c in node.children if c.kind == "categories"), None)
        categories = (
            [c.strip() for c in cat_node.text.split(",")] if cat_node and cat_node.text else []
        )

        # series: one or more <series> with <point> children (or cat/value attrs on points)
        series_nodes = [c for c in node.children if c.kind == "series"]
        if not series_nodes:
            raise ValueError("<chart> requires at least one <series> child")
        
        series = []
        for s in series_nodes:
            points = [p for p in s.children if p.kind == "point"]
            if chart_type == "scatter":
                xy = [
                    (self._chart_number(p.attrs["x"]), self._chart_number(p.attrs["y"]))
                    for p in points
                ]
                series.append({
                    "name": s.attrs["name"],
                    "tone": s.attrs.get("tone"),
                    "xy": xy,
                })
            else:
                values = [self._chart_number(p.attrs["value"]) for p in points]
                if not categories and all("cat" in p.attrs for p in points):
                    categories = [p.attrs["cat"] for p in points]
                
                # --- #8: guard parallel cat/value arrays ---
                # histogram has no categories (raw values, PP auto-bins) — exempt.
                # treemap/sunburst returned earlier. scatter handled above.
                if categories and chart_type != "histogram" and len(values) != len(categories):
                    raise ValueError(
                        f"<chart type='{chart_type}'> series '{s.attrs['name']}': "
                        f"{len(categories)} categories but {len(values)} values "
                        f"(each series must have one value per category)"
                    )
                
                series.append({
                    "name": s.attrs["name"],
                    "tone": s.attrs.get("tone"),
                    "type": s.attrs.get("type"),
                    "axis": s.attrs.get("axis", "primary"),
                    "values": values,
                })
                
        # --- #8b: category types with no categories at all ---
        # #8 catches count mismatch but only when categories exist; a series of
        # bare <point value=.../> with no <categories> slipped through and PP
        # plotted unlabeled bars. histogram is exempt (raw values, PP bins).
        if chart_type not in ("scatter", "histogram") and not categories:
            raise ValueError(
                f"<chart type='{chart_type}'> has no categories: "
                "add a <categories> child or a cat= attribute on every <point>"
            )

        # subtotal indices (waterfall): collected from the first series' points.
        # Empty for every other type — the spec map decides who uses it.
        first_points = [p for p in series_nodes[0].children if p.kind == "point"]
        subtotals = [
            i for i, p in enumerate(first_points)
            if p.attrs.get("subtotal") == "true"
        ]
        
        style = self.chart_style_registry.get(node.attrs.get("style"))
        finish = self.chart_style_registry.get_finish(node.attrs.get("finish", style.get("finish",)))

        data_labels = node.attrs.get("dataLabels")
        if data_labels is not None and data_labels not in {"none", "value", "percent", "category"}:
            raise ValueError(
                f"<chart> dataLabels='{data_labels}' is invalid "
                "(expected one of: none, value, percent, category)"
            )

        shape = {
            "type": chart_type if chart_type in CHARTEX else "chart",
            "name": node.attrs.get("title", "Chart"),
            "chart_type": chart_type,
            "title": node.attrs.get("title"),
            "categories": categories,
            "series": series,
            "subtotals": subtotals,
            "stacked": node.attrs.get("stacked", "false").lower(),
            "legend": node.attrs.get("legend"),
            "data_labels": data_labels,
            "style": style,
            "finish": finish,
            **actual_box.as_shape_geometry(),
        }
        self._append_shape(shape)
        self._record_block("chart", actual_box, parent_kind, node.attrs, content=shape)
    
    def _chart_number(self, value: str) -> float:
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"Invalid chart point value: {value}")

    def _timeline_style_with_finish(self, node: Node, style: dict[str, Any]) -> dict[str, Any]:
        style = dict(style)
        finish_name = node.attrs.get("finish", style.get("finish", "flat"))
        style["_finishName"] = finish_name
        style["_finish"] = self.timeline_style_registry.get_finish(finish_name)
        if node.attrs.get("borderWidth"):
            style["_borderWidth"] = node.attrs["borderWidth"]
        if "shadow" in node.attrs:
            style["_shadow"] = self._is_true(node.attrs["shadow"])
        return style

    def _resolve_timeline_bars_in_columns(
        self,
        node: Node,
        actual_box: Box,
        periods: int,
        style: dict[str, Any],
    ):
        labels = self._timeline_labels(node, periods)
        rows = self._timeline_rows(node, style)
        milestones = [child for child in node.children if child.kind == "milestone"]

        gutter = self._timeline_gutter(actual_box, style)
        header_h = min(self._unit(style.get("headerHeight", "0"), actual_box.h, 0), actual_box.h)
        plot_x = actual_box.x + gutter
        plot_y = actual_box.y + header_h
        plot_w = max(1, actual_box.w - gutter)
        plot_h = max(0, actual_box.h - header_h)
        period_w = plot_w / periods
        column_edges = [round(plot_x + index * period_w) for index in range(periods + 1)]
        row_h = self._timeline_row_height(style, plot_h, max(1, len(rows)))
        task_band_h = min(plot_h, row_h * len(rows))
        milestone_track_h = self._timeline_milestone_track_height(row_h, style) if milestones else 0
        active_plot_h = min(plot_h, task_band_h + milestone_track_h)

        self._emit_timeline_header(actual_box, header_h, column_edges, labels)
        if style.get("showGrid"):
            self._emit_timeline_grid(actual_box, plot_y, active_plot_h or plot_h, column_edges, style)

        task_index = 0
        for row_index, row in enumerate(rows):
            row_box = Box(actual_box.x, round(plot_y + row_index * row_h), actual_box.w, round(row_h))
            if row["kind"] == "group":
                self._emit_timeline_group_header(row["label"], row_box, style)
                continue
            if row["kind"] != "task":
                continue

            task = row["task"]
            task_color = self._timeline_task_tone(task, row, task_index, style)
            if style.get("labelPlacement") == "gutter" and gutter > 0:
                label_box = Box(actual_box.x, row_box.y, gutter, row_box.h)
                label_shape = self._timeline_text_shape(
                    "Timeline Task Label",
                    label_box,
                    task.attrs["label"],
                    role="bodySmall",
                    align="l",
                    overflow=style.get("labelOverflow", "truncate"),
                )
                self._append_shape(label_shape)
                self._record_block("text", label_box, "timeline", task.attrs, content=label_shape)

            bar_box = self._timeline_task_bar_box(task, row_box, column_edges, style)
            bar_shape = self._timeline_task_bar_shape(task, bar_box, task_color, style)
            self._append_shape(bar_shape)
            self._record_block("timeline_task", bar_box, "timeline", task.attrs)

            if style.get("labelPlacement") == "on-bar":
                label_shape = self._timeline_text_shape(
                    "Timeline Task Label",
                    bar_box,
                    task.attrs["label"],
                    role="bodySmall",
                    align="ctr",
                    overflow=style.get("labelOverflow", "truncate"),
                    color="lt1",
                )
                self._append_shape(label_shape)
                self._record_block("text", bar_box, "timeline", task.attrs, content=label_shape)
            task_index += 1

        self._emit_timeline_milestones(
            actual_box,
            plot_y,
            plot_h,
            row_h,
            task_band_h,
            column_edges,
            milestones,
            style,
        )

    def _timeline_gutter(self, box: Box, style: dict[str, Any]) -> int:
        gutter = max(
            round(box.w * float(style.get("gutterRatio", 0))),
            self._unit(style.get("gutterMin", "0"), box.w, 0),
        )
        return min(gutter, max(0, box.w - 1))

    def _timeline_row_height(self, style: dict[str, Any], plot_h: int, row_count: int) -> int:
        minimum = self._unit(style.get("rowHeightMin", "0"), plot_h, 0)
        row_height = style.get("rowHeight", "auto")
        if row_height == "auto":
            return max(minimum, round(plot_h / max(1, row_count)))
        return max(minimum, self._unit(row_height, plot_h, minimum))

    def _timeline_milestone_track_height(self, row_h: int, style: dict[str, Any]) -> int:
        marker_size = self._timeline_milestone_marker_size(row_h, style)
        label_h = self._timeline_label_height("caption")
        gap = self._unit("0.06in", row_h, 0)
        placement = style.get("milestoneLabelPlacement", "below")
        if placement == "inline":
            return max(marker_size, label_h) + 2 * gap
        return marker_size + label_h + 3 * gap

    def _timeline_rows(self, node: Node, style: dict[str, Any]) -> list[dict[str, Any]]:
        has_groups = any(child.kind == "group" for child in node.children)
        render_groups = bool(style.get("renderGroups")) and has_groups
        rows: list[dict[str, Any]] = []
        group_index = 0

        for child in node.children:
            if child.kind == "group":
                if render_groups:
                    rows.append({"kind": "group", "label": child.attrs["label"], "group_index": group_index})
                for task in child.children:
                    rows.append(
                        {
                            "kind": "task",
                            "task": task,
                            "group_label": child.attrs["label"],
                            "group_index": group_index,
                        }
                    )
                group_index += 1
            elif child.kind == "task":
                rows.append({"kind": "task", "task": child, "group_label": None, "group_index": None})

        return rows or [{"kind": "empty"}]

    def _emit_timeline_header(
        self,
        box: Box,
        header_h: int,
        column_edges: list[int],
        labels: list[str],
    ):
        if header_h <= 0:
            return
        for index, label in enumerate(labels):
            label_box = Box(
                column_edges[index],
                box.y,
                max(1, column_edges[index + 1] - column_edges[index]),
                header_h,
            )
            label_shape = self._timeline_text_shape(
                "Timeline Period",
                label_box,
                label,
                role="caption",
                align="ctr",
                overflow="truncate",
            )
            self._append_shape(label_shape)
            self._record_block("text", label_box, "timeline", {}, content=label_shape)

    def _emit_timeline_grid(
        self,
        box: Box,
        plot_y: int,
        plot_h: int,
        column_edges: list[int],
        style: dict[str, Any],
    ):
        for x in column_edges:
            line_shape = {
                "type": "line",
                "name": "Timeline Gridline",
                "x1": x,
                "y1": plot_y,
                "x2": x,
                "y2": plot_y + plot_h,
                "color": style.get("gridColor", "dk2"),
                "width": self._unit(style.get("gridWidth", "0.5pt"), box.w, 0),
            }
            self._append_shape(line_shape)
            self._record_block("line", Box(x, plot_y, 0, plot_h), "timeline", {})

    def _emit_timeline_group_header(self, label: str, row_box: Box, style: dict[str, Any]):
        if style.get("groupHeaderStyle") == "band":
            band = {
                "type": "autoshape",
                "name": f"Timeline Group {label}",
                "preset": "rect",
                "fill": "lt2",
                "line": False,
                **row_box.as_shape_geometry(),
            }
            self._append_shape(band)
            self._record_block("timeline_group", row_box, "timeline", {"label": label})

        if style.get("groupHeaderStyle") in {"band", "label"}:
            label_shape = self._timeline_text_shape(
                "Timeline Group Label",
                row_box,
                label,
                role="bodySmall",
                align="l",
                overflow="truncate",
                bold=True,
            )
            self._append_shape(label_shape)
            self._record_block("text", row_box, "timeline", {"label": label}, content=label_shape)

    def _timeline_task_bar_box(
        self,
        task: Node,
        row_box: Box,
        column_edges: list[int],
        style: dict[str, Any],
    ) -> Box:
        start = int(task.attrs["start"])
        span = int(task.attrs.get("span", 1))
        start = max(1, min(start, len(column_edges) - 1))
        end = max(start, min(start + max(1, span) - 1, len(column_edges) - 1))
        left = column_edges[start - 1]
        right = column_edges[end]
        inset = min(
            self._unit(style.get("barInset", "0"), row_box.w, 0),
            max(0, (right - left) // 2),
        )
        bar_h = max(1, round(row_box.h * float(style.get("barHeightRatio", 0.55))))
        y = row_box.y + round((row_box.h - bar_h) / 2)
        return Box(left + inset, y, max(1, right - left - 2 * inset), bar_h)

    def _timeline_task_bar_shape(
        self,
        task: Node,
        bar_box: Box,
        task_color: str,
        style: dict[str, Any],
    ) -> dict[str, Any]:
        radius = self._timeline_finish_radius(style)
        shape = {
            "type": "autoshape",
            "name": f"Timeline Task {task.attrs['label']}",
            "preset": "roundRect" if self._unit(radius, min(bar_box.w, bar_box.h), 0) else "rect",
            "radius": radius,
            "fill": task_color,
            "fill_style": self._timeline_finish_fill_style(style, task_color),
            "line": self._timeline_finish_line(style, task_color),
            **bar_box.as_shape_geometry(),
        }
        effects = self._timeline_finish_effects(style)
        if effects:
            shape["effects"] = effects
        return shape

    def _timeline_finish_radius(self, style: dict[str, Any]) -> str:
        finish = style.get("_finish", {})
        return finish.get("cornerRadius", style.get("barRadius", "0"))

    def _timeline_finish_fill_style(self, style: dict[str, Any], task_color: str) -> dict[str, Any]:
        fill = dict(style.get("_finish", {}).get("fill", {"type": "solid"}))
        fill["color"] = task_color
        return fill

    def _timeline_finish_line(self, style: dict[str, Any], task_color: str):
        finish = style.get("_finish", {})
        border = dict(finish.get("border") or {})
        width_override = style.get("_borderWidth")
        enabled = bool(border.get("enabled")) or bool(width_override)
        if not enabled:
            return False

        color = border.get("color", "dk2")
        if color == "tone":
            color = task_color
        return {
            "color": color,
            "width": width_override or border.get("width", "0.75pt"),
            "colorTransforms": border.get("colorTransforms"),
        }

    def _timeline_finish_effects(self, style: dict[str, Any]) -> dict[str, Any] | None:
        finish = style.get("_finish", {})
        shadow = finish.get("shadow")
        if style.get("_shadow") is False:
            return None
        if style.get("_shadow") is True and not shadow:
            shadow = {"blur": "2.5pt", "dist": "1pt", "dir": 2700000, "alpha": 14000}
        if not shadow:
            return None
        return {"shadow": shadow}

    def _timeline_task_tone(
        self,
        task: Node,
        row: dict[str, Any],
        task_index: int,
        style: dict[str, Any],
    ) -> str:
        if task.attrs.get("tone"):
            return task.attrs["tone"]

        tones = style.get("defaultTones") or ["accent1"]
        mode = style.get("paletteMode", "cycle")
        if mode == "uniform":
            return tones[0]
        if mode == "by-group" and row.get("group_index") is not None:
            return tones[int(row["group_index"]) % len(tones)]
        return tones[task_index % len(tones)]

    def _emit_timeline_milestones(
        self,
        box: Box,
        plot_y: int,
        plot_h: int,
        row_h: int,
        task_band_h: int,
        column_edges: list[int],
        milestones: list[Node],
        style: dict[str, Any],
    ):
        if not milestones:
            return
        marker_size = self._timeline_milestone_marker_size(row_h, style)
        gap = self._unit("0.06in", box.h, 0)
        label_h = self._timeline_label_height("caption")
        placement = style.get("milestoneLabelPlacement", "below")
        milestone_y = plot_y + task_band_h + gap
        if placement == "above":
            marker_y = milestone_y + label_h + gap
        else:
            marker_y = milestone_y
        max_marker_y = plot_y + plot_h - marker_size
        if placement in {"above", "below"}:
            max_marker_y -= label_h + gap
        marker_y = max(plot_y, min(round(marker_y), max_marker_y))
        label_boxes: list[Box] = []

        for milestone in milestones:
            at = int(milestone.attrs["at"])
            at = max(1, min(at, len(column_edges) - 1))
            marker_center_x = round((column_edges[at - 1] + column_edges[at]) / 2)
            marker_box = Box(
                round(marker_center_x - marker_size / 2),
                marker_y,
                marker_size,
                marker_size,
            )
            marker_shape = {
                "type": "autoshape",
                "name": f"Timeline Milestone {milestone.attrs['label']}",
                "preset": self._milestone_preset(style.get("milestoneMarker", "diamond")),
                "fill": "accent3",
                "line": False,
                **marker_box.as_shape_geometry(),
            }
            self._append_shape(marker_shape)
            self._record_block("timeline_milestone", marker_box, "timeline", milestone.attrs)

            text_box = self._milestone_label_box(
                milestone.attrs["label"],
                marker_box,
                box,
                max(1, column_edges[at] - column_edges[at - 1]),
                style,
                label_boxes,
            )
            label_boxes.append(text_box)
            milestone_label_shape = self._timeline_text_shape(
                "Timeline Milestone Label",
                text_box,
                milestone.attrs["label"],
                role="caption",
                align="ctr",
                overflow=style.get("milestoneLabelOverflow", "extend"),
            )
            self._append_shape(milestone_label_shape)
            self._record_block("text", text_box, "timeline", milestone.attrs, content=milestone_label_shape)

    def _timeline_milestone_marker_size(self, row_h: int, style: dict[str, Any]) -> int:
        return max(
            1,
            min(
                round(row_h * float(style.get("barHeightRatio", 0.55))),
                self._unit("0.18in", self._slide_box.w if self._slide_box else row_h),
            ),
        )

    def _milestone_preset(self, marker: str) -> str:
        return {
            "diamond": "diamond",
            "circle": "ellipse",
            "triangle": "triangle",
            "flag": "flag",
        }.get(marker, "diamond")

    def _milestone_label_box(
        self,
        label: str,
        marker_box: Box,
        timeline_box: Box,
        period_w: int,
        style: dict[str, Any],
        existing: list[Box],
    ) -> Box:
        placement = style.get("milestoneLabelPlacement", "below")
        overflow = style.get("milestoneLabelOverflow", "extend")
        label_h = self._timeline_label_height("caption")
        gap = self._unit("0.04in", timeline_box.h, 0)
        marker_center_x = marker_box.x + marker_box.w / 2

        if overflow == "extend":
            size = self._timeline_role_size("caption")
            measured_w = self._text_width_emu(label, "caption", size)
            label_w = min(timeline_box.w, max(period_w, measured_w + 2 * gap))
        else:
            label_w = period_w

        x = round(marker_center_x - label_w / 2)
        x = max(timeline_box.x, min(x, timeline_box.right - label_w))
        if placement == "above":
            y = marker_box.y - label_h - gap
        elif placement == "inline":
            y = marker_box.y + round((marker_box.h - label_h) / 2)
            x = min(timeline_box.right - label_w, marker_box.right + gap)
        else:
            y = marker_box.bottom + gap

        box = Box(round(x), round(y), round(label_w), label_h)
        if overflow == "stagger":
            box = self._stagger_milestone_label(box, timeline_box, existing, placement, gap)
        return box

    def _stagger_milestone_label(
        self,
        box: Box,
        timeline_box: Box,
        existing: list[Box],
        placement: str,
        gap: int,
    ) -> Box:
        candidate = box
        direction = -1 if placement == "above" else 1
        while any(self._boxes_overlap(candidate, other) for other in existing):
            candidate = Box(candidate.x, candidate.y + direction * (candidate.h + gap), candidate.w, candidate.h)
            if candidate.y < timeline_box.y:
                candidate = Box(candidate.x, timeline_box.y, candidate.w, candidate.h)
                break
            if candidate.bottom > timeline_box.bottom:
                candidate = Box(candidate.x, timeline_box.bottom - candidate.h, candidate.w, candidate.h)
                break
        return candidate

    def _boxes_overlap(self, left: Box, right: Box) -> bool:
        return not (
            left.right <= right.x
            or right.right <= left.x
            or left.bottom <= right.y
            or right.bottom <= left.y
        )

    def _timeline_text_shape(
        self,
        name: str,
        box: Box,
        text: str,
        *,
        role: str,
        align: str,
        overflow: str,
        bold: bool = False,
        color: str | None = None,
    ) -> dict[str, Any]:
        fitted_text, size_pt = self._fit_timeline_label(
            text,
            box.w,
            role,
            overflow if overflow in {"truncate", "shrink"} else "truncate",
            bold=bold,
        )
        run = {"text": fitted_text, "size_pt": size_pt}
        if bold:
            run["bold"] = True
        if color:
            run["color"] = color
        paragraph = {
            "text": fitted_text,
            "runs": [run],
            "align": align,
            "role": role,
        }
        return {
            "type": "text_box",
            "name": name,
            **box.as_shape_geometry(),
            "paragraphs": [paragraph],
            "wrap": "none",
            "anchor": "ctr",
        }

    def _fit_timeline_label(
        self,
        text: str,
        width: int,
        role: str,
        overflow: str,
        *,
        bold: bool = False,
    ) -> tuple[str, float]:
        size = self._timeline_role_size(role)
        floor = self._timeline_role_min_size(role)
        if self._timeline_label_fits(text, role, size, width, bold=bold):
            return text, size

        if overflow == "shrink":
            while size - 0.5 >= floor:
                size = round(size - 0.5, 2)
                if self._timeline_label_fits(text, role, size, width, bold=bold):
                    return text, size
            size = floor

        return self._truncate_timeline_label(text, role, size, width, bold=bold), size

    def _truncate_timeline_label(
        self,
        text: str,
        role: str,
        size: float,
        width: int,
        *,
        bold: bool = False,
    ) -> str:
        ellipsis = "..."
        if width <= 0:
            return ""
        if self._timeline_label_fits(ellipsis, role, size, width, bold=bold):
            suffix = ellipsis
        else:
            suffix = ""

        candidate = text
        while candidate:
            truncated = f"{candidate}{suffix}"
            if self._timeline_label_fits(truncated, role, size, width, bold=bold):
                return truncated
            candidate = candidate[:-1].rstrip()
        return suffix if suffix else ""

    def _timeline_label_fits(
        self,
        text: str,
        role: str,
        size: float,
        width: int,
        *,
        bold: bool = False,
    ) -> bool:
        measurement = self.text_measurer.measure(
            text,
            self._timeline_font_family(role),
            size,
            max(1, width),
            bold=bold,
        )
        return measurement.wrapped_lines <= 1 and measurement.rendered_width_emu <= max(1, width)

    def _text_width_emu(self, text: str, role: str, size: float, *, bold: bool = False) -> int:
        measurement = self.text_measurer.measure(
            text,
            self._timeline_font_family(role),
            size,
            self._slide_box.w if self._slide_box else REFERENCE["slide_sizes"]["16:9"]["cx"],
            bold=bold,
        )
        return measurement.rendered_width_emu

    def _timeline_label_height(self, role: str) -> int:
        size = self._timeline_role_size(role)
        line_spacing = self._type_scale(role).get("lineSpacing", 1.0)
        measurement = self.text_measurer.measure(
            "Ag",
            self._timeline_font_family(role),
            size,
            self._slide_box.w if self._slide_box else REFERENCE["slide_sizes"]["16:9"]["cx"],
            line_spacing=float(line_spacing),
        )
        return measurement.rendered_height_emu

    def _timeline_role_size(self, role: str) -> float:
        return self._scale_size_points(self._type_scale(role).get("size", 17))

    def _timeline_role_min_size(self, role: str) -> float:
        bundle = self._type_scale(role)
        return self._scale_size_points(bundle.get("minSize", self._timeline_role_size(role)))

    def _timeline_font_family(self, role: str) -> str:
        fonts = (self._theme or REFERENCE["default_theme"]).get("fonts", {})
        if role in {"title", "heading", "subheading"}:
            return fonts.get("heading", "Liberation Sans")
        return fonts.get("body", "Liberation Sans")

    def _stack_slots(self, children: list[Node], box: Box, direction: str, gap: int, align: str, justify: str = "start") -> list[Box]:
        main_attr = "w" if direction == "h" else "h"
        cross_attr = "h" if direction == "h" else "w"
        main_len = box.w if direction == "h" else box.h
        cross_len = box.h if direction == "h" else box.w
        explicit_main = [
            self._unit(child.attrs[main_attr], main_len) if main_attr in child.attrs else None
            for child in children
        ]
        gaps_total = gap * (len(children) - 1)

        if direction == "v":
            main_sizes = self._vertical_stack_sizes(
                children, explicit_main, cross_len, main_len - gaps_total
            )
        else:
            remaining = main_len - gaps_total - sum(size or 0 for size in explicit_main)
            auto_count = sum(1 for size in explicit_main if size is None)
            auto_main = max(0, remaining // auto_count) if auto_count else 0
            main_sizes = [
                explicit if explicit is not None else auto_main
                for explicit in explicit_main
            ]

        leftover = max(0, main_len - gaps_total - sum(main_sizes))
        extra_gap = 0
        cursor = box.x if direction == "h" else box.y
        if justify == "ctr":
            cursor += leftover // 2
        elif justify == "end":
            cursor += leftover
        elif justify == "between" and len(children) > 1:
            extra_gap = leftover // (len(children) - 1)

        slots: list[Box] = []
        for child, main_size in zip(children, main_sizes):
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
            cursor += main_size + gap + extra_gap
        return slots

    # Kinds that flex to absorb leftover vertical stack space. Text and rules
    # are content-sized; containers and media fill what remains.
    STACK_FLEX_KINDS = frozenset(
        {"stack", "grid", "free", "chart", "table", "timeline", "image", "shape", "use"}
    )

    # PowerPoint's default vertical text-box insets (tIns + bIns, 45720 each).
    TEXT_BOX_VERTICAL_INSETS_EMU = 91440

    def _vertical_stack_sizes(
        self,
        children: list[Node],
        explicit_main: list[int | None],
        width: int,
        available: int,
    ) -> list[int]:
        """Content-aware vertical slotting. The old model split leftover space
        EQUALLY across all auto children, so a one-line header got the same
        slot as a paragraph or a hairline rule — and overflowed onto its
        neighbour on dense slides. Text now takes its measured height, rules
        take their stroke, and only container kinds flex."""
        sized: list[tuple[str, int | None]] = []
        for child, explicit in zip(children, explicit_main):
            if explicit is not None:
                sized.append(("fixed", explicit))
            elif child.kind == "text":
                sized.append(("intrinsic", self._intrinsic_text_height(child, width)))
            elif child.kind == "line":
                stroke = self._unit(child.attrs.get("width", "1pt"), width)
                sized.append(("intrinsic", max(stroke, 1)))
            else:
                sized.append(("flex", None))

        fixed_total = sum(size for _, size in sized if size is not None)
        flex_count = sum(1 for kind, _ in sized if kind == "flex")
        remaining = available - fixed_total
        if flex_count:
            flex_size = max(0, remaining // flex_count)
        else:
            flex_size = 0
            if remaining < 0:
                # No flexible child to squeeze: compress measured (not
                # explicit) slots proportionally so siblings never overlap;
                # the validator's text_overflow warning reports the squeeze.
                intrinsic_total = sum(size for kind, size in sized if kind == "intrinsic")
                if intrinsic_total > 0:
                    factor = max(0.0, (intrinsic_total + remaining) / intrinsic_total)
                    sized = [
                        (kind, round(size * factor) if kind == "intrinsic" else size)
                        for kind, size in sized
                    ]
        return [flex_size if kind == "flex" else size for kind, size in sized]

    def _intrinsic_text_height(self, node: Node, width: int) -> int:
        """Measured height of a <text> block at its resolved size and font."""
        paragraphs = [c for c in node.children if c.kind == "p"]
        if not paragraphs:
            paragraphs = [Node("p", {}, [], node.text or "")]
        total = 0
        for para in paragraphs:
            role = para.attrs.get("role", node.attrs.get("role"))
            if role is None:
                role = self._default_role_for_placeholder(node.attrs.get("placeholder"))
            bundle = self._type_scale(role)
            if "size" in node.attrs:
                size = self._points(node.attrs["size"])
            else:
                size = self._scale_size_points(bundle.get("size", 17))
            bold = self._bool_attr_from_hierarchy("bold", para, para, node)
            if bold is None:
                bold = bundle.get("weight") == "bold"
            line_spacing = node.attrs.get("lineSpacing", bundle.get("lineSpacing", 1.0))
            font = node.attrs.get("font") or self._timeline_font_family(role)
            text = para.text or "".join(run.text or "" for run in para.children) or "Ag"
            measurement = self.text_measurer.measure(
                text,
                font,
                size,
                max(1, width),
                bold=bool(bold),
                line_spacing=float(line_spacing),
            )
            total += measurement.rendered_height_emu
            for attr in ("spaceBefore", "spaceAfter"):
                value = node.attrs.get(attr, bundle.get(attr))
                if value:
                    total += self._unit(value, width)
        return total + self.TEXT_BOX_VERTICAL_INSETS_EMU

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
        role = paragraph.attrs.get("role", text_parent.attrs.get("role"))
        if role is None:
            role = self._default_role_for_placeholder(text_parent.attrs.get("placeholder"))
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

            if run_node.attrs.get("field"):
                field = run_node.attrs["field"]
                if field not in self.RUN_FIELD_TYPES:
                    raise ValueError(
                        f"Unknown run field {field!r}; expected one of {sorted(self.RUN_FIELD_TYPES)}"
                    )
                run["field"] = self.RUN_FIELD_TYPES[field]
                # The literal is just a placeholder; PowerPoint re-renders it.
                run["text"] = run_node.text or "1"

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

    def _default_role_for_placeholder(self, placeholder: str | None) -> str:
        if not placeholder:
            return "body"
        normalized = self._normalize_placeholder(placeholder)
        return self.PLACEHOLDER_DEFAULT_ROLES.get(normalized, "body")

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

    def _grid_auto_rows(self, children: list[Node], cols: int) -> int:
        """Simulate the placement loop's auto-flow exactly. The old version
        only looked at explicit row= attrs, so an auto-flowing grid (e.g. 4
        children in 2 columns) computed rows=1 while placement wrapped to
        row 2 — and the grid_bounds validator rejected the resolver's own
        layout."""
        highest = 1
        next_col = 1
        next_row = 1
        for child in children:
            row = int(child.attrs.get("row", next_row))
            colspan = int(child.attrs.get("colspan", 1))
            rowspan = int(child.attrs.get("rowspan", 1))
            highest = max(highest, row + rowspan - 1)
            next_col += colspan
            if next_col > cols:
                next_col = 1
                next_row += 1
        return highest

    def _timeline_labels(self, node: Node, periods: int) -> list[str]:
        if "labels" not in node.attrs:
            unit = node.attrs.get("unit", "week")
            prefixes = {
                "day": "Day",
                "week": "Week",
                "month": "Month",
                "quarter": "Q",
            }
            if unit not in prefixes:
                raise ValueError(f"Unsupported timeline unit: {unit}")
            prefix = prefixes[unit]
            if unit == "quarter":
                return [f"{prefix}{index}" for index in range(1, periods + 1)]
            return [f"{prefix} {index}" for index in range(1, periods + 1)]
        labels = [label.strip() for label in node.attrs["labels"].split(",")]
        fallback = Node("timeline", {"unit": node.attrs.get("unit", "week")})
        generated = self._timeline_labels(fallback, periods)
        return (labels + generated[len(labels) :])[:periods]

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

    def _parse_adjustments(self, raw: str) -> dict[str, int]:
        """Parse adj="40%" or adj="adj1:40%, adj2:25000" into a guide dict."""
        adjustments: dict[str, int] = {}
        for token in raw.replace(",", " ").split():
            if ":" in token:
                name, value = token.split(":", 1)
            else:
                name, value = "adj", token
            adjustments[name.strip()] = self._percent_thousandths(value)
        if not adjustments:
            raise ValueError(f"Empty adj value: {raw!r}")
        return adjustments

    def _percent_thousandths(self, raw: str) -> int:
        """"40%" -> 40000; bare numbers pass through as raw OOXML units."""
        raw = str(raw).strip()
        if raw.endswith("%"):
            return round(float(raw[:-1]) * 1000)
        return int(raw)

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

    def _fit_image_box(self, src: str, box: Box, fit: str) -> tuple[Box, dict[str, int] | None]:
        if fit == "stretch":
            return box, None

        size = self._image_pixel_size(src)
        if size is None:
            return box, None

        image_w, image_h = size
        if image_w <= 0 or image_h <= 0 or box.w <= 0 or box.h <= 0:
            return box, None

        image_aspect = image_w / image_h
        box_aspect = box.w / box.h
        if fit == "contain":
            if image_aspect > box_aspect:
                fitted_w = box.w
                fitted_h = round(box.w / image_aspect)
            else:
                fitted_h = box.h
                fitted_w = round(box.h * image_aspect)
            return (
                Box(
                    round(box.x + (box.w - fitted_w) / 2),
                    round(box.y + (box.h - fitted_h) / 2),
                    fitted_w,
                    fitted_h,
                ),
                None,
            )

        crop = {"l": 0, "t": 0, "r": 0, "b": 0}
        if image_aspect > box_aspect:
            crop_each = round((1 - box_aspect / image_aspect) / 2 * 100000)
            crop["l"] = crop["r"] = crop_each
        else:
            crop_each = round((1 - image_aspect / box_aspect) / 2 * 100000)
            crop["t"] = crop["b"] = crop_each
        return box, crop

    def _image_pixel_size(self, src: str) -> tuple[int, int] | None:
        path = Path(src)
        if not path.exists():
            return None
        with Image.open(path) as image:
            return image.size

    def _resolve_background(self, value: str) -> dict[str, str]:
        background = value.strip()
        if not background:
            raise ValueError("background cannot be empty")
        if background.startswith("image:"):
            src = background.removeprefix("image:").strip()
            if not src:
                raise ValueError("image background requires a source path")
            return {
                "kind": "image",
                "src": self._resolve_image_attrs({"src": src})["src"],
            }

        if background.startswith("#") or self._is_hex_color(background):
            return {"kind": "solid", "color": background}

        theme_colors = (self._theme or REFERENCE["default_theme"]).get("colors", {})
        if background in theme_colors or background in REFERENCE["color_map_default"]:
            return {"kind": "solid", "color": background}
        raise ValueError(f"Unknown background color token: {background}")

    def _is_named_asset_ref(self, src: str) -> bool:
        if src.startswith("asset:"):
            return True
        return "/" not in src and "\\" not in src and "." not in Path(src).name

    def _is_hex_color(self, value: str) -> bool:
        text = value.strip().lstrip("#")
        return len(text) == 6 and all(char in "0123456789abcdefABCDEF" for char in text)

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
