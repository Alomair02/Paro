"""Shape emitters for slide parts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from builders.common import REFERENCE, relationship_target
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import (
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


IMAGE_CONTENT_TYPES = {
    ext: mime
    for ext, mime in REFERENCE["content_types"]["defaults"].items()
    if mime.startswith("image/")
}


@dataclass
class SlideState:
    """Mutable per-slide state shared by shape emitters."""

    part_path: str
    media_parts: dict[str, bytes] = field(default_factory=dict)
    _last_shape_id: int = field(
        default_factory=lambda: REFERENCE["constraints"]["shape_id_group_tree"]
    )
    _next_media_index: int = 1

    def __post_init__(self):
        self._next_media_index = self._infer_next_media_index()

    def next_id(self) -> int:
        """Return the next unique shape ID for this slide."""
        self._last_shape_id += 1
        return self._last_shape_id

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


def emit_placeholder_text(shape_data: dict, slide_state: SlideState) -> etree._Element:
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

    sp.append(_text_body_from_shape(shape_data))
    return sp


def emit_text_box(shape_data: dict, slide_state: SlideState) -> etree._Element:
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

    sp.append(_text_body_from_shape(shape_data))
    return sp


def emit_image(
    shape_data: dict,
    slide_state: SlideState,
    rel_registry: RelationshipRegistry,
    ct_registry: ContentTypeRegistry,
) -> etree._Element:
    """Emit a picture shape and register its slide relationship and media part."""
    shape_id = slide_state.next_id()
    source_path = Path(shape_data.get("src", shape_data.get("path", "")))
    if not source_path:
        raise ValueError("Image shape requires a src or path")

    extension = source_path.suffix.lower().lstrip(".")
    if extension not in IMAGE_CONTENT_TYPES:
        raise ValueError(f"Unsupported image extension: {extension}")

    media_part_path = slide_state.next_media_path(extension)
    slide_state.media_parts[media_part_path] = source_path.read_bytes()
    ct_registry.add_default(extension, IMAGE_CONTENT_TYPES[extension])

    rid = rel_registry.add(
        slide_state.part_path,
        relationship_target(slide_state.part_path, media_part_path),
        RelationshipRegistry.IMAGE,
    )

    pic = etree.Element(qn("p", "pic"))
    nv_pic_pr = etree.SubElement(pic, qn("p", "nvPicPr"))
    _append_c_nv_pr(
        nv_pic_pr,
        shape_id,
        shape_data.get("name", f"Picture {shape_id}"),
        descr=str(source_path.name),
    )
    c_nv_pic_pr = etree.SubElement(nv_pic_pr, qn("p", "cNvPicPr"))
    etree.SubElement(c_nv_pic_pr, qn("a", "picLocks"), noChangeAspect="1")
    etree.SubElement(nv_pic_pr, qn("p", "nvPr"))

    blip_fill = etree.SubElement(pic, qn("p", "blipFill"))
    blip = etree.SubElement(blip_fill, qn("a", "blip"))
    blip.set(qn("r", "embed"), rid)
    stretch = etree.SubElement(blip_fill, qn("a", "stretch"))
    etree.SubElement(stretch, qn("a", "fillRect"))

    sp_pr = etree.SubElement(pic, qn("p", "spPr"))
    sp_pr.append(_xfrm_from_shape(shape_data))
    sp_pr.append(make_prst_geom("rect"))
    return pic


def emit_autoshape(shape_data: dict, slide_state: SlideState) -> etree._Element:
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
    sp_pr.append(make_prst_geom(shape_data.get("preset", "rect")))
    sp_pr.append(make_solid_fill(shape_data.get("fill", "accent1")))
    if "line" in shape_data:
        sp_pr.append(_line_from_shape(shape_data["line"]))

    if _has_text(shape_data):
        sp.append(_text_body_from_shape(shape_data))
    return sp


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


def _text_body_from_shape(shape_data: dict) -> etree._Element:
    return make_text_body(
        _paragraphs_from_shape(shape_data),
        wrap=shape_data.get("wrap", "square"),
        anchor=shape_data.get("anchor", "t"),
    )


def _paragraphs_from_shape(shape_data: dict) -> list[etree._Element]:
    if "paragraphs" in shape_data:
        return [_paragraph_from_data(paragraph) for paragraph in shape_data["paragraphs"]]

    if "text" not in shape_data:
        return []

    text = shape_data["text"]
    if isinstance(text, list):
        return [_paragraph_from_data(item) for item in text]
    return [_paragraph_from_data({"text": text})]


def _paragraph_from_data(paragraph_data) -> etree._Element:
    if isinstance(paragraph_data, str):
        paragraph_data = {"text": paragraph_data}

    runs_data = paragraph_data.get("runs")
    if runs_data is None:
        runs_data = [{"text": paragraph_data.get("text", "")}]

    runs = []
    for run_data in runs_data:
        if isinstance(run_data, str):
            run_data = {"text": run_data}
        runs.append(
            make_run(
                str(run_data.get("text", "")),
                bold=run_data.get("bold", False),
                italic=run_data.get("italic", False),
                size_pt=run_data.get("size_pt"),
                color=run_data.get("color"),
                font=run_data.get("font"),
            )
        )

    return make_paragraph(
        runs,
        level=paragraph_data.get("level", 0),
        align=paragraph_data.get("align"),
    )


def _has_text(shape_data: dict) -> bool:
    return "text" in shape_data or "paragraphs" in shape_data


def _xfrm_from_shape(shape_data: dict) -> etree._Element:
    x, y, cx, cy = _geometry_from_shape(shape_data)
    return make_xfrm(x, y, cx, cy, _rotation_from_shape(shape_data))


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


def _line_from_shape(line_data) -> etree._Element:
    if line_data is False or line_data is None:
        return make_ln(0)

    if not isinstance(line_data, dict):
        raise ValueError("line must be a dict, False, or None")

    width = line_data.get("width", 0)
    return make_ln(_to_emu(width), line_data.get("color"))


def _rotation_from_shape(shape_data: dict) -> int:
    if "rotation" not in shape_data:
        return 0
    return UnitConverter.degrees_to_ooxml_angle(shape_data["rotation"])


def _to_emu(value) -> int:
    if isinstance(value, str):
        return UnitConverter.to_emu(value)
    return int(value)
