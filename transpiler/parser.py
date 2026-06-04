"""Parser for the XML slide DSL."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from builders.common import REFERENCE
from transpiler.ast import DeckAst, Node, SlideAst, ThemeAst


class DSLParseError(ValueError):
    """Raised when DSL XML violates the schema surface."""


THEME_COLOR_ATTRS = set(REFERENCE["color_scheme_slots"]["order"])
THEME_ATTRS = {"name", "heading", "body"} | THEME_COLOR_ATTRS
GRID_PLACEMENT_ATTRS = {"col", "row", "colspan", "rowspan"}
GEOMETRY_ATTRS = {"x", "y", "w", "h", "rot"}
TYPE_SCALE_ROLES = set(REFERENCE["default_theme"]["typeScale"])

ALLOWED_ATTRS = {
    "deck": {"theme", "size", "font", "background"},
    "theme": THEME_ATTRS,
    "defs": set(),
    "def": {"name", "auto"},
    "use": {"ref"},
    "slide": {"layout", "flow", "pad", "gap", "background"},
    "stack": {
        "dir",
        "gap",
        "align",
        "justify",
        "pad",
        "w",
        "h",
        "anchor",
        "fill",
        "line",
        "lineWidth",
        "radius",
    }
    | GRID_PLACEMENT_ATTRS
    | GEOMETRY_ATTRS,
    "grid": {
        "cols",
        "rows",
        "gap",
        "colgap",
        "rowgap",
        "pad",
        "fill",
        "line",
        "lineWidth",
        "radius",
    }
    | GRID_PLACEMENT_ATTRS
    | GEOMETRY_ATTRS,
    "free": GEOMETRY_ATTRS | GRID_PLACEMENT_ATTRS,
    "text": {
        "placeholder",
        "idx",
        "font",
        "size",
        "color",
        "align",
        "bold",
        "italic",
        "underline",
        "anchor",
        "wrap",
        "lineSpacing",
        "spaceBefore",
        "spaceAfter",
        "list",
        "role",
    }
    | GRID_PLACEMENT_ATTRS
    | GEOMETRY_ATTRS,
    "p": {"level", "align", "bullet", "bold", "italic", "role"},
    "run": {"bold", "italic", "underline", "size", "color", "font", "link"},
    "image": {"src", "placeholder", "idx", "fit", "alt"} | GRID_PLACEMENT_ATTRS | GEOMETRY_ATTRS,
    "shape": {
        "geom",
        "fill",
        "line",
        "lineWidth",
        "radius",
        "text",
    }
    | GRID_PLACEMENT_ATTRS
    | GEOMETRY_ATTRS,
    "line": {"color", "width", "dash", "x1", "y1", "x2", "y2", "cap"}
    | GRID_PLACEMENT_ATTRS
    | GEOMETRY_ATTRS,
    "table": {
        "cols",
        "colWidths",
        "rowHeights",
        "header",
        "headerFill",
        "headerColor",
        "fill",
        "line",
        "lineWidth",
    }
    | GRID_PLACEMENT_ATTRS
    | GEOMETRY_ATTRS,
    "row": set(),
    "cell": {"colspan", "rowspan", "align", "valign", "fill", "color", "bold", "italic"},
    "timeline": {"style", "periods", "unit", "labels", "finish", "borderWidth", "shadow"}
    | GRID_PLACEMENT_ATTRS
    | GEOMETRY_ATTRS,
    "group": {"label"},
    "task": {"label", "start", "span", "tone"},
    "milestone": {"label", "at"},
    "chart": {"type", "title", "style", "finish", "legend", "stacked"}
    | GRID_PLACEMENT_ATTRS
    | GEOMETRY_ATTRS,
    "categories": set(),
    "series": {"name", "tone", "type","axis"},
    "point": {"cat", "value", "x", "y", "subtotal"},
    "node": {"label", "value"},
}

REQUIRED_ATTRS = {
    "theme": {"name"},
    "def": {"name"},
    "use": {"ref"},
    "free": {"x", "y", "w", "h"},
    "image": {"src"},
    "timeline": {"periods"},
    "group": {"label"},
    "task": {"label", "start"},
    "milestone": {"label", "at"},
    "chart": {"type"},
    "series": {"name"},
}

ALLOWED_CHILDREN = {
    "deck": {"theme", "defs", "slide"},
    "defs": {"def"},
    "def": {
        "stack",
        "grid",
        "free",
        "text",
        "image",
        "shape",
        "line",
        "table",
        "timeline",
        "chart",
        "use",
    },
    "slide": {
        "stack",
        "grid",
        "free",
        "text",
        "image",
        "shape",
        "line",
        "table",
        "timeline",
        "chart",
        "use",
    },
    "stack": {"stack", "grid", "free", "text", "image", "shape", "line", "table", "timeline", "chart", "use"},
    "grid": {"stack", "grid", "free", "text", "image", "shape", "line", "table", "timeline", "chart", "use"},
    "free": {"stack", "grid", "free", "text", "image", "shape", "line", "table", "timeline", "chart", "use"},
    "text": {"p"},
    "p": {"run"},
    "shape": {"text"},
    "table": {"row"},
    "row": {"cell"},
    "cell": {"p"},
    "timeline": {"group", "task", "milestone"},
    "chart": {"categories", "series", "node"},
    "series": {"point"},
    "group": {"task"},
    "node": {"node"},
}


class DSLParser:
    """Parse XML DSL into a plain AST and expand defs/use."""

    def parse_file(self, path: str) -> DeckAst:
        return self.parse(Path(path).read_text(encoding="utf-8"))

    def parse(self, xml_text: str) -> DeckAst:
        try:
            root = etree.fromstring(xml_text.encode("utf-8"))
        except etree.XMLSyntaxError as exc:
            raise DSLParseError(str(exc)) from exc

        self._validate_element_surface(root)
        if self._local_name(root) != "deck":
            raise DSLParseError("Root element must be <deck>")

        defs = self._parse_defs(root)
        inline_theme = self._parse_theme(root)
        slides: list[SlideAst] = []
        for index, slide_el in enumerate(self._children_named(root, "slide"), start=1):
            slide_attrs = dict(slide_el.attrib)
            children = self._expand_children(slide_el, defs)
            auto_children = [
                child.clone()
                for def_el in self._children_named(self._first_child_named(root, "defs"), "def")
                if self._is_true(def_el.get("auto", "false"))
                for child in self._nodes_from_children(def_el, defs)
            ]
            children.extend(auto_children)
            slides.append(
                SlideAst(
                    index=index,
                    layout=slide_attrs.get("layout", "blank"),
                    flow=slide_attrs.get("flow", "stack"),
                    attrs=slide_attrs,
                    children=children,
                )
            )

        if not slides:
            raise DSLParseError("<deck> requires at least one <slide>")

        deck_theme = root.get("theme", "default")
        if inline_theme and root.get("theme") is None:
            deck_theme = inline_theme.name

        return DeckAst(
            theme=deck_theme,
            size=root.get("size", "16:9"),
            font=root.get("font"),
            background=root.get("background"),
            inline_theme=inline_theme,
            slides=slides,
            defs=defs,
        )

    def _validate_element_surface(self, element: etree._Element, parent: str | None = None):
        kind = self._local_name(element)
        if kind not in ALLOWED_ATTRS:
            raise DSLParseError(f"Unknown element <{kind}>")

        if parent:
            allowed = ALLOWED_CHILDREN.get(parent, set())
            if kind not in allowed:
                raise DSLParseError(f"<{kind}> is not allowed inside <{parent}>")

        allowed_attrs = ALLOWED_ATTRS[kind]
        for attr in element.attrib:
            if attr not in allowed_attrs:
                raise DSLParseError(f"Unknown attribute '{attr}' on <{kind}>")

        for required in REQUIRED_ATTRS.get(kind, set()):
            if required not in element.attrib:
                raise DSLParseError(f"<{kind}> requires {required}")

        if "role" in element.attrib and element.attrib["role"] not in TYPE_SCALE_ROLES:
            raise DSLParseError(f"Unknown type role: {element.attrib['role']}")

        for child in element:
            self._validate_element_surface(child, kind)

    def _parse_defs(self, root: etree._Element) -> dict[str, list[Node]]:
        defs_el = self._first_child_named(root, "defs")
        if defs_el is None:
            return {}

        defs: dict[str, list[Node]] = {}
        for def_el in self._children_named(defs_el, "def"):
            name = def_el.get("name")
            if not name:
                raise DSLParseError("<def> requires name")
            if name in defs:
                raise DSLParseError(f"Duplicate <def> name: {name}")
            defs[name] = self._nodes_from_children(def_el, defs)
        return defs

    def _parse_theme(self, root: etree._Element) -> ThemeAst | None:
        theme_el = self._first_child_named(root, "theme")
        if theme_el is None:
            return None
        attrs = dict(theme_el.attrib)
        name = attrs.get("name")
        if not name:
            raise DSLParseError("<theme> requires name")
        return ThemeAst(name=name, attrs=attrs)

    def _expand_children(self, parent: etree._Element, defs: dict[str, list[Node]]) -> list[Node]:
        return self._nodes_from_children(parent, defs)

    def _nodes_from_children(self, parent: etree._Element | None, defs: dict[str, list[Node]]) -> list[Node]:
        if parent is None:
            return []

        nodes: list[Node] = []
        for child in parent:
            kind = self._local_name(child)
            if kind == "use":
                ref = child.get("ref")
                if not ref:
                    raise DSLParseError("<use> requires ref")
                if ref not in defs:
                    raise DSLParseError(f"Unknown <use> ref: {ref}")
                nodes.extend(def_node.clone() for def_node in defs[ref])
                continue

            if kind in {"theme", "defs"}:
                continue
            nodes.append(self._node_from_element(child, defs))
        return nodes

    def _node_from_element(self, element: etree._Element, defs: dict[str, list[Node]]) -> Node:
        kind = self._local_name(element)
        text = self._direct_text(element)
        children: list[Node] = []
        for child in element:
            child_kind = self._local_name(child)
            if child_kind == "use":
                ref = child.get("ref")
                if ref not in defs:
                    raise DSLParseError(f"Unknown <use> ref: {ref}")
                children.extend(def_node.clone() for def_node in defs[ref])
            else:
                node = self._node_from_element(child, defs)
                if child.tail and child.tail.strip():
                    if node.kind == "run":
                        children.append(node)
                        children.append(Node("run", {}, [], child.tail.strip()))
                        continue
                children.append(node)
        return Node(kind, dict(element.attrib), children, text)

    def _direct_text(self, element: etree._Element) -> str:
        pieces: list[str] = []
        if element.text and element.text.strip():
            pieces.append(element.text.strip())
        if self._local_name(element) not in {"p", "cell"}:
            for child in element:
                if child.tail and child.tail.strip():
                    pieces.append(child.tail.strip())
        return " ".join(pieces)

    def _children_named(self, parent: etree._Element | None, name: str) -> list[etree._Element]:
        if parent is None:
            return []
        return [child for child in parent if self._local_name(child) == name]

    def _first_child_named(self, parent: etree._Element | None, name: str) -> etree._Element | None:
        children = self._children_named(parent, name)
        return children[0] if children else None

    def _local_name(self, element: etree._Element) -> str:
        return etree.QName(element).localname

    def _is_true(self, value: str) -> bool:
        return value.lower() in {"1", "true", "yes"}
