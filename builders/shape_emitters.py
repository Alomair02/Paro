"""Shape emitters for slide parts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from builders.common import REFERENCE, relationship_target
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import (
    append_color,
    make_effect_list,
    make_gradient_fill,
    make_ln,
    make_no_fill,
    make_paragraph,
    make_prst_geom,
    make_run,
    make_solid_fill,
    make_text_body,
    make_xfrm,
    qn,
)
from utils.converter import UnitConverter


TABLE_GRAPHIC_URI = "http://schemas.openxmlformats.org/drawingml/2006/table"

IMAGE_CONTENT_TYPES = {
    ext: mime
    for ext, mime in REFERENCE["content_types"]["defaults"].items()
    if mime.startswith("image/")
}

_DASH_MAP = {
    "solid": "solid",
    "dot": "dot",
    "dash": "dash",
    "dashDot": "dashDot",
}

_CAP_MAP = {
    "flat": "flat",
    "round": "rnd",
    "square": "sq",
}


@dataclass
class SlideState:
    """Mutable per-slide state shared by shape emitters."""

    part_path: str
    media_parts: dict[str, bytes] = field(default_factory=dict)
    media_sources: dict[str, str] = field(default_factory=dict)
    chart_parts: dict[str, str] = field(default_factory=dict)
    _last_shape_id: int = field(
        default_factory=lambda: REFERENCE["constraints"]["shape_id_group_tree"]
    )
    _next_media_index: int = 1
    _next_chart_index: int = 1
    _next_chartex_index: int = 1

    def __post_init__(self):
        self._next_media_index   = self._infer_next_media_index()
        self._next_chart_index   = self._infer_next_chart_index()
        self._next_chartex_index = self._infer_next_chartex_index()

    def next_id(self) -> int:
        """Return the next unique shape ID for this slide."""
        self._last_shape_id += 1
        return self._last_shape_id
    
    def next_chart_index(self) -> int:
        """Return the next unique chart index for this presentation."""
        chart_index = self._next_chart_index
        self._next_chart_index += 1
        return chart_index
    
    def next_chartex_index(self) -> int:
        """Return the next unique chartEx index for this presentation."""
        chartex_index = self._next_chartex_index
        self._next_chartex_index += 1
        return chartex_index
    
    def next_chart_path(self) -> str:
        """Allocate the next available ppt/charts/chartN.xml package path."""
        chart_index = self.next_chart_index()
        chart_path = f"ppt/charts/chart{chart_index}.xml"
        while chart_path in self.chart_parts:
            chart_index = self.next_chart_index()
            chart_path = f"ppt/charts/chart{chart_index}.xml"
        return chart_path
    
    def next_chartex_path(self) -> str:
        """Allocate the next available ppt/charts/chartExN.xml package path."""
        chartex_index = self.next_chartex_index()
        chartex_path = f"ppt/charts/chartEx{chartex_index}.xml"
        while chartex_path in self.chart_parts:
            chartex_index = self.next_chartex_index()
            chartex_path = f"ppt/charts/chartEx{chartex_index}.xml"
        return chartex_path
    
    def _infer_next_chart_index(self) -> int:
        prefix = "ppt/charts/chart"
        highest = 0
        for chart_path in self.chart_parts:
            if not chart_path.startswith(prefix):
                continue
            stem = Path(chart_path).stem
            try:
                highest = max(highest, int(stem.removeprefix("chart")))
            except ValueError:
                continue
        return highest + 1
    
    def _infer_next_chartex_index(self) -> int:
        prefix = "ppt/charts/chartEx"
        highest = 0
        for chartex_path in self.chart_parts:
            if not chartex_path.startswith(prefix):
                continue
            stem = Path(chartex_path).stem
            try:
                highest = max(highest, int(stem.removeprefix("chartEx")))
            except ValueError:
                continue
        return highest + 1

    def next_media_path(self, extension: str) -> str:
        """Allocate the next available ppt/media/imageN.ext package path."""
        extension = extension.lower().lstrip(".")
        template = REFERENCE["package_layout"]["media"]

        while True:
            media_path = template.replace("{N}", str(self._next_media_index)).replace(
                "{ext}", extension
            )
            self._next_media_index += 1
            if media_path not in self.media_parts:
                return media_path

    def _infer_next_media_index(self) -> int:
        prefix = "ppt/media/image"
        highest = 0
        for media_path in self.media_parts:
            if not media_path.startswith(prefix):
                continue
            stem = Path(media_path).stem
            try:
                highest = max(highest, int(stem.removeprefix("image")))
            except ValueError:
                continue
        return highest + 1


def emit_placeholder_text(
    shape_data: dict,
    slide_state: SlideState,
    rel_registry: RelationshipRegistry | None = None,
) -> etree._Element:
    """Emit a placeholder shape, preserving layout inheritance by default."""
    shape_id = slide_state.next_id()
    idx = str(shape_data["idx"])
    ph_type = shape_data.get("placeholder_type", shape_data.get("ph_type", "body"))

    sp = etree.Element(qn("p", "sp"))
    nv_sp_pr = etree.SubElement(sp, qn("p", "nvSpPr"))
    _append_c_nv_pr(
        nv_sp_pr,
        shape_id,
        shape_data.get("name", f"Placeholder {idx}"),
    )
    c_nv_sp_pr = etree.SubElement(nv_sp_pr, qn("p", "cNvSpPr"))
    etree.SubElement(c_nv_sp_pr, qn("a", "spLocks"), noGrp="1")

    nv_pr = etree.SubElement(nv_sp_pr, qn("p", "nvPr"))
    ph = etree.SubElement(nv_pr, qn("p", "ph"))
    ph.set("idx", idx)
    if ph_type:
        ph.set("type", ph_type)

    sp_pr = etree.SubElement(sp, qn("p", "spPr"))
    if _has_any_geometry(shape_data):
        x, y, cx, cy = _geometry_from_shape(shape_data)
        sp_pr.append(make_xfrm(x, y, cx, cy, _rotation_from_shape(shape_data)))

    sp.append(_text_body_from_shape(shape_data, slide_state, rel_registry))
    return sp


def emit_text_box(
    shape_data: dict,
    slide_state: SlideState,
    rel_registry: RelationshipRegistry | None = None,
) -> etree._Element:
    """Emit a fully self-contained text box shape."""
    shape_id = slide_state.next_id()

    sp = etree.Element(qn("p", "sp"))
    nv_sp_pr = etree.SubElement(sp, qn("p", "nvSpPr"))
    _append_c_nv_pr(
        nv_sp_pr,
        shape_id,
        shape_data.get("name", f"TextBox {shape_id}"),
    )
    c_nv_sp_pr = etree.SubElement(nv_sp_pr, qn("p", "cNvSpPr"))
    c_nv_sp_pr.set("txBox", "1")
    etree.SubElement(nv_sp_pr, qn("p", "nvPr"))

    sp_pr = etree.SubElement(sp, qn("p", "spPr"))
    sp_pr.append(_xfrm_from_shape(shape_data))
    sp_pr.append(make_prst_geom("rect"))
    sp_pr.append(make_no_fill())
    sp_pr.append(make_ln(0))

    sp.append(_text_body_from_shape(shape_data, slide_state, rel_registry))
    return sp


def emit_image(
    shape_data: dict,
    slide_state: SlideState,
    rel_registry: RelationshipRegistry,
    ct_registry: ContentTypeRegistry,
) -> etree._Element:
    """Emit a picture shape and register its slide relationship and media part."""
    shape_id = slide_state.next_id()
    source_path = _image_source_path(shape_data)
    rid = _register_image_part(source_path, slide_state, rel_registry, ct_registry)
    ph_type = shape_data.get("placeholder_type", shape_data.get("ph_type"))

    pic = etree.Element(qn("p", "pic"))
    nv_pic_pr = etree.SubElement(pic, qn("p", "nvPicPr"))
    _append_c_nv_pr(
        nv_pic_pr,
        shape_id,
        shape_data.get("name", f"Picture {shape_id}"),
        descr=str(shape_data.get("alt", source_path.name)),
    )
    c_nv_pic_pr = etree.SubElement(nv_pic_pr, qn("p", "cNvPicPr"))
    etree.SubElement(c_nv_pic_pr, qn("a", "picLocks"), noChangeAspect="1")
    nv_pr = etree.SubElement(nv_pic_pr, qn("p", "nvPr"))
    if ph_type:
        ph = etree.SubElement(nv_pr, qn("p", "ph"))
        ph.set("idx", str(shape_data["idx"]))
        ph.set("type", ph_type)

    blip_fill = etree.SubElement(pic, qn("p", "blipFill"))
    blip = etree.SubElement(blip_fill, qn("a", "blip"))
    blip.set(qn("r", "embed"), rid)
    _append_blip_effects(blip, shape_data)
    _append_image_crop(blip_fill, shape_data.get("crop"))
    stretch = etree.SubElement(blip_fill, qn("a", "stretch"))
    etree.SubElement(stretch, qn("a", "fillRect"))

    sp_pr = etree.SubElement(pic, qn("p", "spPr"))
    if _has_any_geometry(shape_data):
        sp_pr.append(_xfrm_from_shape(shape_data))
        sp_pr.append(make_prst_geom("rect"))
    elif not ph_type:
        raise ValueError("Image geometry requires x, y, w/width, and h/height unless it fills a placeholder")
    return pic


def emit_slide_background(
    background_data: dict,
    slide_state: SlideState,
    rel_registry: RelationshipRegistry,
    ct_registry: ContentTypeRegistry,
) -> etree._Element:
    """Emit a slide p:bg element from resolved solid or image background data."""
    bg = etree.Element(qn("p", "bg"))
    bg_pr = etree.SubElement(bg, qn("p", "bgPr"))
    kind = background_data.get("kind", "solid")

    if kind == "solid":
        bg_pr.append(make_solid_fill(background_data["color"]))
        return bg

    if kind == "image":
        source_path = _image_source_path(background_data)
        rid = _register_image_part(source_path, slide_state, rel_registry, ct_registry)
        blip_fill = etree.SubElement(bg_pr, qn("a", "blipFill"))
        blip = etree.SubElement(blip_fill, qn("a", "blip"))
        blip.set(qn("r", "embed"), rid)
        stretch = etree.SubElement(blip_fill, qn("a", "stretch"))
        etree.SubElement(stretch, qn("a", "fillRect"))
        return bg

    raise ValueError(f"Unsupported slide background kind: {kind}")


def emit_autoshape(
    shape_data: dict,
    slide_state: SlideState,
    rel_registry: RelationshipRegistry | None = None,
) -> etree._Element:
    """Emit a self-contained preset geometry shape."""
    shape_id = slide_state.next_id()

    sp = etree.Element(qn("p", "sp"))
    nv_sp_pr = etree.SubElement(sp, qn("p", "nvSpPr"))
    _append_c_nv_pr(
        nv_sp_pr,
        shape_id,
        shape_data.get("name", f"Shape {shape_id}"),
    )
    etree.SubElement(nv_sp_pr, qn("p", "cNvSpPr"))
    etree.SubElement(nv_sp_pr, qn("p", "nvPr"))

    sp_pr = etree.SubElement(sp, qn("p", "spPr"))
    sp_pr.append(_xfrm_from_shape(shape_data))
    sp_pr.append(_prst_geom_from_shape(shape_data))
    sp_pr.append(_fill_from_shape(shape_data))
    if "line" in shape_data:
        sp_pr.append(_line_from_shape(shape_data["line"]))
    if shape_data.get("effects"):
        sp_pr.append(_effects_from_shape(shape_data["effects"]))

    if _has_text(shape_data):
        sp.append(_text_body_from_shape(shape_data, slide_state, rel_registry))
    return sp


def emit_line(shape_data: dict, slide_state: SlideState) -> etree._Element:
    """Emit a native connector line."""
    shape_id = slide_state.next_id()
    x1, y1, x2, y2 = _line_points_from_shape(shape_data)

    cxn_sp = etree.Element(qn("p", "cxnSp"))
    nv_cxn_sp_pr = etree.SubElement(cxn_sp, qn("p", "nvCxnSpPr"))
    _append_c_nv_pr(
        nv_cxn_sp_pr,
        shape_id,
        shape_data.get("name", f"Line {shape_id}"),
    )
    etree.SubElement(nv_cxn_sp_pr, qn("p", "cNvCxnSpPr"))
    etree.SubElement(nv_cxn_sp_pr, qn("p", "nvPr"))

    sp_pr = etree.SubElement(cxn_sp, qn("p", "spPr"))
    xfrm = make_xfrm(
        min(x1, x2),
        min(y1, y2),
        max(1, abs(x2 - x1)),
        max(1, abs(y2 - y1)),
    )
    if x2 < x1:
        xfrm.set("flipH", "1")
    if y2 < y1:
        xfrm.set("flipV", "1")
    sp_pr.append(xfrm)
    sp_pr.append(make_prst_geom("line"))
    sp_pr.append(
        make_ln(
            _to_emu(shape_data.get("width", "1pt")),
            shape_data.get("color", "dk1"),
            dash=_dash_value(shape_data.get("dash", "solid")),
            cap=_cap_value(shape_data.get("cap", "flat")),
            head=shape_data.get("head"),
            tail=shape_data.get("tail"),
        )
    )
    return cxn_sp


def emit_table(
    shape_data: dict,
    slide_state: SlideState,
    rel_registry: RelationshipRegistry | None = None,
) -> etree._Element:
    """Emit a native DrawingML table inside a presentation graphic frame."""
    shape_id = slide_state.next_id()

    graphic_frame = etree.Element(qn("p", "graphicFrame"))
    nv_graphic_frame_pr = etree.SubElement(graphic_frame, qn("p", "nvGraphicFramePr"))
    _append_c_nv_pr(
        nv_graphic_frame_pr,
        shape_id,
        shape_data.get("name", f"Table {shape_id}"),
    )
    etree.SubElement(nv_graphic_frame_pr, qn("p", "cNvGraphicFramePr"))
    etree.SubElement(nv_graphic_frame_pr, qn("p", "nvPr"))

    _append_graphic_frame_xfrm(graphic_frame, shape_data)

    graphic = etree.SubElement(graphic_frame, qn("a", "graphic"))
    graphic_data = etree.SubElement(graphic, qn("a", "graphicData"))
    graphic_data.set("uri", TABLE_GRAPHIC_URI)

    table = etree.SubElement(graphic_data, qn("a", "tbl"))
    table_pr = etree.SubElement(table, qn("a", "tblPr"))
    if shape_data.get("header"):
        table_pr.set("firstRow", "1")
    table_grid = etree.SubElement(table, qn("a", "tblGrid"))
    for width in _table_column_widths(shape_data):
        grid_col = etree.SubElement(table_grid, qn("a", "gridCol"))
        grid_col.set("w", str(_to_emu(width)))

    for row_index, row_data in enumerate(shape_data.get("rows", [])):
        tr = etree.SubElement(table, qn("a", "tr"))
        tr.set("h", str(_to_emu(row_data.get("h", row_data.get("height", 0)))))
        for cell_data in row_data.get("cells", []):
            _append_table_cell(
                tr,
                shape_data,
                cell_data,
                row_index,
                slide_state,
                rel_registry,
            )

    return graphic_frame


def _append_c_nv_pr(
    parent: etree._Element,
    shape_id: int,
    name: str,
    descr: str | None = None,
) -> etree._Element:
    c_nv_pr = etree.SubElement(parent, qn("p", "cNvPr"))
    c_nv_pr.set("id", str(shape_id))
    c_nv_pr.set("name", name)
    if descr is not None:
        c_nv_pr.set("descr", descr)
    return c_nv_pr


def _text_body_from_shape(
    shape_data: dict,
    slide_state: SlideState | None = None,
    rel_registry: RelationshipRegistry | None = None,
) -> etree._Element:
    return make_text_body(
        _paragraphs_from_shape(shape_data, slide_state, rel_registry),
        wrap=shape_data.get("wrap", "square"),
        anchor=shape_data.get("anchor", "t"),
    )


def _paragraphs_from_shape(
    shape_data: dict,
    slide_state: SlideState | None = None,
    rel_registry: RelationshipRegistry | None = None,
) -> list[etree._Element]:
    if "paragraphs" in shape_data:
        return [
            _paragraph_from_data(paragraph, slide_state, rel_registry)
            for paragraph in shape_data["paragraphs"]
        ]

    if "text" not in shape_data:
        return []

    text = shape_data["text"]
    if isinstance(text, list):
        return [
            _paragraph_from_data(item, slide_state, rel_registry)
            for item in text
        ]
    return [_paragraph_from_data({"text": text}, slide_state, rel_registry)]


def _paragraph_from_data(
    paragraph_data,
    slide_state: SlideState | None = None,
    rel_registry: RelationshipRegistry | None = None,
    default_run_props: dict | None = None,
) -> etree._Element:
    if isinstance(paragraph_data, str):
        paragraph_data = {"text": paragraph_data}
    default_run_props = default_run_props or {}

    runs_data = paragraph_data.get("runs")
    if runs_data is None:
        runs_data = [{"text": paragraph_data.get("text", "")}]

    runs = []
    for run_data in runs_data:
        if isinstance(run_data, str):
            run_data = {"text": run_data}
        hyperlink_rid = _hyperlink_rid(run_data, slide_state, rel_registry)
        runs.append(
            make_run(
                str(run_data.get("text", "")),
                bold=run_data.get("bold", default_run_props.get("bold", False)),
                italic=run_data.get("italic", default_run_props.get("italic", False)),
                underline=run_data.get("underline", default_run_props.get("underline", False)),
                size_pt=run_data.get("size_pt"),
                color=run_data.get("color", default_run_props.get("color")),
                font=run_data.get("font"),
                hyperlink_rid=hyperlink_rid,
            )
        )

    level = int(paragraph_data.get("level", 0))
    bullet = paragraph_data.get("bullet")
    bullet_attrs = _bullet_attrs(level, bullet)
    return make_paragraph(
        runs,
        level=level,
        align=paragraph_data.get("align"),
        line_spacing=_line_spacing(paragraph_data.get("lineSpacing")),
        space_before=_spacing_points(paragraph_data.get("spaceBefore")),
        space_after=_spacing_points(paragraph_data.get("spaceAfter")),
        **bullet_attrs,
    )


def _hyperlink_rid(
    run_data: dict,
    slide_state: SlideState | None,
    rel_registry: RelationshipRegistry | None,
) -> str | None:
    link = run_data.get("link")
    if not link:
        return None
    if slide_state is None or rel_registry is None:
        raise ValueError("Hyperlink runs require a slide state and relationship registry")
    return rel_registry.add(
        slide_state.part_path,
        link,
        RelationshipRegistry.HYPERLINK,
        target_mode="External",
    )


def _bullet_attrs(level: int, bullet: str | None) -> dict:
    if bullet is None:
        return {}
    if bullet not in {"none", "bullet", "number", "dash", "check"}:
        raise ValueError(f"Unsupported paragraph bullet type: {bullet}")

    indents = REFERENCE["text_defaults"]["level_indents"]
    indent = indents[min(max(level, 0), len(indents) - 1)]
    attrs = {
        "bullet": bullet,
        "mar_l": indent["marL"],
        "indent": indent["indent"],
    }
    if bullet == "number":
        attrs["number_type"] = REFERENCE["text_defaults"]["numbering_type"]
    elif bullet != "none":
        attrs["bullet_char"] = REFERENCE["text_defaults"]["list_markers"][bullet]
    return attrs


def _has_text(shape_data: dict) -> bool:
    return "text" in shape_data or "paragraphs" in shape_data


def _xfrm_from_shape(shape_data: dict) -> etree._Element:
    x, y, cx, cy = _geometry_from_shape(shape_data)
    return make_xfrm(
        x,
        y,
        cx,
        cy,
        _rotation_from_shape(shape_data),
        flip_h=bool(shape_data.get("flipH")),
        flip_v=bool(shape_data.get("flipV")),
    )


def _prst_geom_from_shape(shape_data: dict) -> etree._Element:
    preset = shape_data.get("preset", "rect")
    adjustments = {}
    if preset == "roundRect" and shape_data.get("radius") not in (None, "", 0, "0"):
        _, _, width, height = _geometry_from_shape(shape_data)
        radius = _to_emu(shape_data["radius"])
        shortest = max(1, min(width, height))
        adjustments["adj"] = max(0, min(50000, round(radius / shortest * 100000)))
    # Explicit adj guides are the author's exact intent; they win over radius.
    adjustments.update(shape_data.get("adjustments") or {})
    return make_prst_geom(preset, adjustments)


def _fill_from_shape(shape_data: dict) -> etree._Element:
    fill_style = shape_data.get("fill_style")
    if fill_style:
        kind = fill_style.get("type", "solid")
        color = fill_style.get("color", shape_data.get("fill", "accent1"))
        if kind == "none":
            return make_no_fill()
        if kind == "gradient":
            return make_gradient_fill(
                color,
                fill_style.get("startTransforms"),
                fill_style.get("endTransforms"),
                int(fill_style.get("angle", 5400000)),
            )
        return make_solid_fill(color, fill_style.get("transforms"))

    if shape_data.get("fill") == "none":
        return make_no_fill()
    return make_solid_fill(shape_data.get("fill", "accent1"))


def _geometry_from_shape(shape_data: dict) -> tuple[int, int, int, int]:
    x = shape_data.get("x")
    y = shape_data.get("y")
    width = shape_data.get("w", shape_data.get("width"))
    height = shape_data.get("h", shape_data.get("height"))

    if None in (x, y, width, height):
        raise ValueError("Shape geometry requires x, y, w/width, and h/height")

    return (
        _to_emu(x),
        _to_emu(y),
        _to_emu(width),
        _to_emu(height),
    )


def _has_any_geometry(shape_data: dict) -> bool:
    keys = {"x", "y", "w", "width", "h", "height"}
    present = keys.intersection(shape_data)
    if not present:
        return False

    has_width = "w" in shape_data or "width" in shape_data
    has_height = "h" in shape_data or "height" in shape_data
    if not ("x" in shape_data and "y" in shape_data and has_width and has_height):
        raise ValueError("Placeholder geometry overrides require x, y, w/width, and h/height")
    return True


def _append_graphic_frame_xfrm(parent: etree._Element, shape_data: dict):
    x, y, cx, cy = _geometry_from_shape(shape_data)
    xfrm = etree.SubElement(parent, qn("p", "xfrm"))
    off = etree.SubElement(xfrm, qn("a", "off"))
    off.set("x", str(x))
    off.set("y", str(y))
    ext = etree.SubElement(xfrm, qn("a", "ext"))
    ext.set("cx", str(cx))
    ext.set("cy", str(cy))


def _append_table_cell(
    row_el: etree._Element,
    table_data: dict,
    cell_data: dict,
    row_index: int,
    slide_state: SlideState | None,
    rel_registry: RelationshipRegistry | None,
):
    cell = _table_cell_defaults(table_data, cell_data, row_index)
    tc = etree.SubElement(row_el, qn("a", "tc"))
    if int(cell.get("gridSpan", cell.get("colspan", 1))) > 1:
        tc.set("gridSpan", str(int(cell.get("gridSpan", cell.get("colspan", 1)))))
    if int(cell.get("rowSpan", cell.get("rowspan", 1))) > 1:
        tc.set("rowSpan", str(int(cell.get("rowSpan", cell.get("rowspan", 1)))))

    tx_body = etree.SubElement(tc, qn("a", "txBody"))
    body_pr = etree.SubElement(tx_body, qn("a", "bodyPr"))
    body_pr.set("wrap", "square")
    if cell.get("valign"):
        body_pr.set("anchor", cell["valign"])
    etree.SubElement(tx_body, qn("a", "lstStyle"))

    default_run_props = {
        "bold": cell.get("bold", False),
        "italic": cell.get("italic", False),
        "color": cell.get("color"),
    }
    for paragraph in _paragraph_data_from_cell(cell):
        tx_body.append(
            _paragraph_from_data(
                paragraph,
                slide_state,
                rel_registry,
                default_run_props=default_run_props,
            )
        )

    tc_pr = etree.SubElement(tc, qn("a", "tcPr"))
    if cell.get("valign"):
        tc_pr.set("anchor", cell["valign"])
    _append_table_fill(tc_pr, cell.get("fill"))
    _append_table_borders(tc_pr, cell.get("line"))


def _table_cell_defaults(table_data: dict, cell_data: dict, row_index: int) -> dict:
    cell = dict(cell_data)
    if table_data.get("header") and row_index == 0:
        cell.setdefault("fill", table_data.get("headerFill", "accent1"))
        cell.setdefault("color", table_data.get("headerColor", "lt1"))
        cell.setdefault("bold", True)
    cell.setdefault("fill", table_data.get("fill", "lt1"))
    cell.setdefault("line", table_data.get("line", {"color": "dk2", "width": table_data.get("lineWidth", "0.75pt")}))
    if cell["line"] == "none":
        cell["line"] = False
    if isinstance(cell["line"], str):
        cell["line"] = {"color": cell["line"], "width": table_data.get("lineWidth", "0.75pt")}
    return cell


def _paragraph_data_from_cell(cell_data: dict) -> list:
    if "paragraphs" in cell_data:
        paragraphs = cell_data["paragraphs"]
    elif "text" in cell_data:
        paragraphs = [{"text": cell_data["text"], "align": cell_data.get("align")}]
    else:
        paragraphs = [{"text": "", "align": cell_data.get("align")}]

    normalized = []
    for paragraph in paragraphs:
        if isinstance(paragraph, str):
            paragraph = {"text": paragraph}
        paragraph = dict(paragraph)
        if cell_data.get("align") and "align" not in paragraph:
            paragraph["align"] = cell_data["align"]
        normalized.append(paragraph)
    return normalized


def _append_table_fill(tc_pr: etree._Element, fill):
    if fill in (None, "none", False):
        tc_pr.append(make_no_fill())
        return
    tc_pr.append(make_solid_fill(fill))


def _append_table_borders(tc_pr: etree._Element, line_data):
    for tag in ("lnL", "lnR", "lnT", "lnB"):
        ln = etree.SubElement(tc_pr, qn("a", tag))
        if line_data in (None, False, "none"):
            ln.append(make_no_fill())
            continue
        if isinstance(line_data, str):
            line_data = {"color": line_data, "width": "0.75pt"}
        width = _to_emu(line_data.get("width", "0.75pt"))
        if width:
            ln.set("w", str(width))
            ln.append(make_solid_fill(line_data.get("color", "dk2")))
        else:
            ln.append(make_no_fill())


def _table_column_widths(shape_data: dict) -> list:
    columns = shape_data.get("columns")
    if columns:
        return [column.get("w", column.get("width")) if isinstance(column, dict) else column for column in columns]

    col_count = int(shape_data.get("cols", 1))
    _, _, width, _ = _geometry_from_shape(shape_data)
    return [round(width / col_count) for _ in range(col_count)]


def _line_points_from_shape(shape_data: dict) -> tuple[int, int, int, int]:
    if all(key in shape_data for key in ("x1", "y1", "x2", "y2")):
        return (
            _to_emu(shape_data["x1"]),
            _to_emu(shape_data["y1"]),
            _to_emu(shape_data["x2"]),
            _to_emu(shape_data["y2"]),
        )

    x, y, width, height = _geometry_from_shape(shape_data)
    return x, y + height // 2, x + width, y + height // 2


def _dash_value(value: str) -> str:
    if value not in _DASH_MAP:
        raise ValueError(f"Unsupported line dash style: {value}")
    return _DASH_MAP[value]


def _cap_value(value: str) -> str:
    if value not in _CAP_MAP:
        raise ValueError(f"Unsupported line cap style: {value}")
    return _CAP_MAP[value]


def _image_source_path(shape_data: dict) -> Path:
    source = shape_data.get("src", shape_data.get("path"))
    if not source:
        raise ValueError("Image shape requires a src or path")
    return Path(source)


def _register_image_part(
    source_path: Path,
    slide_state: SlideState,
    rel_registry: RelationshipRegistry,
    ct_registry: ContentTypeRegistry,
) -> str:
    extension = source_path.suffix.lower().lstrip(".")
    if extension not in IMAGE_CONTENT_TYPES:
        raise ValueError(f"Unsupported image extension: {extension}")

    source_key = str(source_path.expanduser().resolve(strict=False))
    media_part_path = slide_state.media_sources.get(source_key)
    if media_part_path is None:
        media_part_path = slide_state.next_media_path(extension)
        slide_state.media_parts[media_part_path] = source_path.read_bytes()
        slide_state.media_sources[source_key] = media_part_path
    ct_registry.add_default(extension, IMAGE_CONTENT_TYPES[extension])

    return rel_registry.add(
        slide_state.part_path,
        relationship_target(slide_state.part_path, media_part_path),
        RelationshipRegistry.IMAGE,
    )


def _append_blip_effects(blip: etree._Element, shape_data: dict) -> None:
    """Color treatments on the picture data: alphaModFix, grayscl, duotone."""
    if shape_data.get("alpha") is not None:
        etree.SubElement(blip, qn("a", "alphaModFix")).set("amt", str(int(shape_data["alpha"])))
    if shape_data.get("grayscale"):
        etree.SubElement(blip, qn("a", "grayscl"))
    duotone = shape_data.get("duotone")
    if duotone:
        duo = etree.SubElement(blip, qn("a", "duotone"))
        for color in duotone:
            append_color(duo, color)


def _append_image_crop(blip_fill: etree._Element, crop: dict | None):
    if not crop:
        return
    attrs = {
        key: str(int(value))
        for key, value in crop.items()
        if key in {"l", "t", "r", "b"} and int(value)
    }
    if attrs:
        etree.SubElement(blip_fill, qn("a", "srcRect"), **attrs)


def _line_from_shape(line_data) -> etree._Element:
    if line_data is False or line_data is None:
        return make_ln(0)

    if not isinstance(line_data, dict):
        raise ValueError("line must be a dict, False, or None")

    width = line_data.get("width", 0)
    return make_ln(
        _to_emu(width),
        line_data.get("color"),
        dash=_dash_value(line_data.get("dash", "solid")),
        cap=_cap_value(line_data.get("cap", "flat")),
        color_transforms=line_data.get("colorTransforms"),
    )


def _effects_from_shape(effects_data: dict) -> etree._Element:
    shadow = effects_data.get("shadow")
    if shadow:
        shadow = {
            **shadow,
            "blurRad": _to_emu(shadow.get("blur", shadow.get("blurRad", 0))),
            "dist": _to_emu(shadow.get("dist", 0)),
        }
    return make_effect_list(shadow)


def _rotation_from_shape(shape_data: dict) -> int:
    if "rotation" not in shape_data:
        return 0
    return UnitConverter.degrees_to_ooxml_angle(shape_data["rotation"])


def _line_spacing(value) -> dict | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return {"type": "pct", "val": int(float(value) * 100000)}

    text = str(value).strip()
    if text.endswith("%"):
        return {"type": "pct", "val": int(float(text[:-1]) * 1000)}
    try:
        return {"type": "pct", "val": int(float(text) * 100000)}
    except ValueError:
        return {"type": "pts", "val": _spacing_points(text)}


def _spacing_points(value) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(float(value) * REFERENCE["units"]["font_size_factor"])
    return int(
        UnitConverter.to_emu(value)
        / UnitConverter.CONVERSION_FACTORS["pt"]
        * REFERENCE["units"]["font_size_factor"]
    )


def _to_emu(value) -> int:
    if isinstance(value, str):
        return UnitConverter.to_emu(value)
    return int(value)
