#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: xml_builder.py
Author: Abdulaziz Alomair
Date: 2026-06-01 (YYYY-MM-DD)
Version: 1.0
Description: Generic XML utilities and OOXML-specific builders.
Pure functions — no side effects, no state.
"""

import uuid

from lxml import etree

CANONICAL_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


# ---------------------------------------------------------------------------
# Namespace map — every OOXML builder uses these
# ---------------------------------------------------------------------------

NSMAP = {
    "a":  "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p":  "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r":  "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}


# ---------------------------------------------------------------------------
# Generic XML utilities
# ---------------------------------------------------------------------------

def qn(prefix: str, local: str) -> str:
    """
    Return a Clark-notation qualified name.
    qn("a", "xfrm") → "{http://...drawingml...}xfrm"
    """
    return f"{{{NSMAP[prefix]}}}{local}"


def make_element(tag: str, text: str = None, attrib: dict = None) -> etree._Element:
    """Create a bare XML element with optional text and attributes."""
    el = etree.Element(tag, attrib=attrib or {})
    if text is not None:
        el.text = text
    return el


def make_sub_element(parent: etree._Element, tag: str,
                     text: str = None, attrib: dict = None) -> etree._Element:
    """Create a sub-element under parent with optional text and attributes."""
    el = etree.SubElement(parent, tag, attrib=attrib or {})
    if text is not None:
        el.text = text
    return el


def to_xml_string(element: etree._Element,
                  pretty_print: bool = True,
                  xml_declaration: bool = True,
                  encoding: str = "UTF-8") -> str:
    """Serialize an lxml element to a UTF-8 XML string."""
    xml = etree.tostring(
        element,
        pretty_print=pretty_print,
        xml_declaration=False,
        encoding=encoding,
    ).decode(encoding)

    if not xml_declaration:
        return xml

    return f"{CANONICAL_XML_DECLARATION}\n{xml}"


def parse_xml_string(xml_string: str) -> etree._Element:
    """Parse an XML string and return the root element."""
    return etree.fromstring(xml_string.encode("utf-8"))


# ---------------------------------------------------------------------------
# Geometry builders
# ---------------------------------------------------------------------------

def make_xfrm(x: int, y: int, cx: int, cy: int,
              rot: int = 0,
              flip_h: bool = False,
              flip_v: bool = False) -> etree._Element:
    """
    Build an a:xfrm element for position, size, rotation, and flip.
    All positional values in EMU.
    rot is in 60,000ths of a degree (5400000 = 90°).
    """
    xfrm = etree.Element(qn("a", "xfrm"))
    if rot:    xfrm.set("rot",   str(rot))
    if flip_h: xfrm.set("flipH", "1")
    if flip_v: xfrm.set("flipV", "1")

    off = etree.SubElement(xfrm, qn("a", "off"))
    off.set("x", str(x))
    off.set("y", str(y))

    ext = etree.SubElement(xfrm, qn("a", "ext"))
    ext.set("cx", str(cx))
    ext.set("cy", str(cy))

    return xfrm


def make_prst_geom(prst: str = "rect", adjustments: dict[str, int] = None) -> etree._Element:
    """
    Build an a:prstGeom element for a preset shape.
    prst is one of the 187 preset shape names: "rect", "ellipse", "roundRect", etc.
    """
    geom = etree.Element(qn("a", "prstGeom"))
    geom.set("prst", prst)
    av_lst = etree.SubElement(geom, qn("a", "avLst"))  # required child, even if empty
    for name, value in (adjustments or {}).items():
        gd = etree.SubElement(av_lst, qn("a", "gd"))
        gd.set("name", name)
        gd.set("fmla", f"val {int(value)}")
    return geom


# ---------------------------------------------------------------------------
# Fill builders
# ---------------------------------------------------------------------------

_SCHEME_TOKENS = {
    "dk1", "lt1", "dk2", "lt2",
    "accent1", "accent2", "accent3",
    "accent4", "accent5", "accent6",
    "hlink", "folHlink", "bg1", "bg2",
    "tx1", "tx2", "phClr",
}

_PERCENT_COLOR_TRANSFORMS = {"lumMod", "lumOff", "alpha"}


def make_solid_fill(color: str, transforms: dict[str, int] = None) -> etree._Element:
    """
    Build an a:solidFill element.
    color is either:
      - a scheme token like "accent1", "dk1"  → a:schemeClr
      - a hex RGB string like "FF0000"         → a:srgbClr
    """
    fill = etree.Element(qn("a", "solidFill"))
    _append_color(fill, color, transforms)
    return fill


def make_gradient_fill(
    color: str,
    start_transforms: dict[str, int] = None,
    end_transforms: dict[str, int] = None,
    angle: int = 5400000,
) -> etree._Element:
    """Build a subtle two-stop a:gradFill using one base color ramp."""
    fill = etree.Element(qn("a", "gradFill"))
    fill.set("rotWithShape", "1")
    gs_lst = etree.SubElement(fill, qn("a", "gsLst"))
    first = etree.SubElement(gs_lst, qn("a", "gs"))
    first.set("pos", "0")
    _append_color(first, color, start_transforms or {"lumMod": 100000, "lumOff": 12000})
    second = etree.SubElement(gs_lst, qn("a", "gs"))
    second.set("pos", "100000")
    _append_color(second, color, end_transforms or {"lumMod": 88000})
    lin = etree.SubElement(fill, qn("a", "lin"))
    lin.set("ang", str(angle))
    lin.set("scaled", "1")
    return fill


def make_effect_list(shadow: dict = None) -> etree._Element:
    """Build an a:effectLst with an optional outer shadow."""
    effect_lst = etree.Element(qn("a", "effectLst"))
    if shadow:
        outer = etree.SubElement(effect_lst, qn("a", "outerShdw"))
        outer.set("blurRad", str(int(shadow.get("blurRad", 0))))
        outer.set("dist", str(int(shadow.get("dist", 0))))
        outer.set("dir", str(int(shadow.get("dir", 2700000))))
        outer.set("algn", shadow.get("algn", "ctr"))
        outer.set("rotWithShape", "0")
        _append_color(
            outer,
            shadow.get("color", "000000"),
            {"alpha": int(shadow.get("alpha", 18000))},
        )
    return effect_lst


def append_color(parent: etree._Element, color: str, transforms: dict[str, int] = None) -> etree._Element:
    """Append a schemeClr/srgbClr child to parent (public seam for bare color slots
    like a:duotone children, where no fill wrapper element is wanted)."""
    return _append_color(parent, color, transforms)


def _append_color(parent: etree._Element, color: str, transforms: dict[str, int] = None) -> etree._Element:
    if color in _SCHEME_TOKENS:
        clr = etree.SubElement(parent, qn("a", "schemeClr"))
        clr.set("val", color)
    else:
        clr = etree.SubElement(parent, qn("a", "srgbClr"))
        clr.set("val", color.lstrip("#").upper())

    for name, value in (transforms or {}).items():
        value = int(value)
        _validate_color_transform(name, value)
        child = etree.SubElement(clr, qn("a", name))
        child.set("val", str(value))
    return clr


def _validate_color_transform(name: str, value: int):
    if name in _PERCENT_COLOR_TRANSFORMS and not 0 <= value <= 100000:
        raise ValueError(f"{name} must be between 0 and 100000, got {value}")


def make_no_fill() -> etree._Element:
    """Build an a:noFill element."""
    return etree.Element(qn("a", "noFill"))


# ---------------------------------------------------------------------------
# Line / stroke builder
# ---------------------------------------------------------------------------

def make_ln(
    width_emu: int = 0,
    color: str = None,
    dash: str = None,
    cap: str = None,
    color_transforms: dict[str, int] = None,
    head: str = None,
    tail: str = None,
) -> etree._Element:
    """
    Build an a:ln element.
    width_emu = 0 → no line (a:noFill inside).
    color follows the same rules as make_solid_fill.
    head/tail are line-end marker types (triangle, stealth, diamond, oval, arrow).
    """
    ln = etree.Element(qn("a", "ln"))
    if cap:
        ln.set("cap", cap)
    if width_emu:
        ln.set("w", str(width_emu))
        ln.append(make_solid_fill(color if color else "dk1", color_transforms))
        if dash and dash != "solid":
            prst_dash = etree.SubElement(ln, qn("a", "prstDash"))
            prst_dash.set("val", dash)
        for tag, kind in (("headEnd", head), ("tailEnd", tail)):
            if kind and kind != "none":
                end = etree.SubElement(ln, qn("a", tag))
                end.set("type", kind)
                end.set("w", "med")
                end.set("len", "med")
    else:
        ln.append(make_no_fill())
    return ln


# ---------------------------------------------------------------------------
# Text builders
# ---------------------------------------------------------------------------

def make_run(text: str,
             bold: bool = False,
             italic: bool = False,
             underline: bool = False,
             size_pt: float = None,
             color: str = None,
             font: str = None,
             hyperlink_rid: str = None,
             field: str = None) -> etree._Element:
    """
    Build an a:r element (text run).
    size_pt is in points; converted internally to hundredths of a point.
    field turns the run into an a:fld of that type (e.g. "slidenum"); the
    text becomes the placeholder literal PowerPoint replaces on render.
    """
    if field:
        run = etree.Element(qn("a", "fld"))
        run.set("id", "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"paro-field-{field}")).upper() + "}")
        run.set("type", field)
    else:
        run = etree.Element(qn("a", "r"))

    rpr = etree.SubElement(run, qn("a", "rPr"))
    rpr.set("lang", "en-US")
    rpr.set("dirty", "0")

    if bold:      rpr.set("b", "1")
    if italic:    rpr.set("i", "1")
    if underline: rpr.set("u", "sng")
    if size_pt:   rpr.set("sz", str(int(size_pt * 100)))

    if color:
        rpr.append(make_solid_fill(color))
    if font:
        latin = etree.SubElement(rpr, qn("a", "latin"))
        latin.set("typeface", font)
    if hyperlink_rid:
        hlink = etree.SubElement(rpr, qn("a", "hlinkClick"))
        hlink.set(qn("r", "id"), hyperlink_rid)

    t = etree.SubElement(run, qn("a", "t"))
    t.text = text

    return run


def make_paragraph(runs: list = None,
                   level: int = 0,
                   align: str = None,
                   bullet: str = None,
                   bullet_char: str = None,
                   number_type: str = "arabicPeriod",
                   mar_l: int = None,
                   indent: int = None,
                   line_spacing: dict = None,
                   space_before: int = None,
                   space_after: int = None) -> etree._Element:
    """
    Build an a:p element (paragraph) containing the given runs.
    level: bullet indent level 0–8.
    align: "l", "ctr", "r", "just", or None to inherit.
    runs: list of a:r elements. Pass [] or None for an empty paragraph.
    """
    para = etree.Element(qn("a", "p"))

    ppr = etree.SubElement(para, qn("a", "pPr"))
    if level: ppr.set("lvl", str(level))
    if align: ppr.set("algn", align)
    if mar_l is not None: ppr.set("marL", str(mar_l))
    if indent is not None: ppr.set("indent", str(indent))

    if line_spacing:
        ln_spc = etree.SubElement(ppr, qn("a", "lnSpc"))
        tag = "spcPct" if line_spacing["type"] == "pct" else "spcPts"
        spc = etree.SubElement(ln_spc, qn("a", tag))
        spc.set("val", str(line_spacing["val"]))
    if space_before is not None:
        spc_bef = etree.SubElement(ppr, qn("a", "spcBef"))
        spc = etree.SubElement(spc_bef, qn("a", "spcPts"))
        spc.set("val", str(space_before))
    if space_after is not None:
        spc_aft = etree.SubElement(ppr, qn("a", "spcAft"))
        spc = etree.SubElement(spc_aft, qn("a", "spcPts"))
        spc.set("val", str(space_after))

    if bullet == "none":
        etree.SubElement(ppr, qn("a", "buNone"))
    elif bullet == "number":
        bu_auto_num = etree.SubElement(ppr, qn("a", "buAutoNum"))
        bu_auto_num.set("type", number_type)
    elif bullet in {"bullet", "dash", "check"}:
        bu_char = etree.SubElement(ppr, qn("a", "buChar"))
        bu_char.set("char", bullet_char or "")

    for run in (runs or []):
        para.append(run)

    return para


def make_text_body(paragraphs: list,
                   wrap: str = "square",
                   anchor: str = "t") -> etree._Element:
    """
    Build a p:txBody element containing the given paragraphs.
    wrap:   "square" or "none"
    anchor: "t" (top), "ctr" (middle), "b" (bottom)
    """
    txbody = etree.Element(qn("p", "txBody"))

    bodypr = etree.SubElement(txbody, qn("a", "bodyPr"))
    bodypr.set("wrap", wrap)
    bodypr.set("anchor", anchor)

    etree.SubElement(txbody, qn("a", "lstStyle"))  # required, even if empty

    for para in (paragraphs or [make_paragraph()]):
        txbody.append(para)

    return txbody


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    spPr = etree.Element(qn("p", "spPr"))
    spPr.append(make_xfrm(914400, 914400, 4572000, 1143000))
    spPr.append(make_prst_geom("rect"))
    spPr.append(make_solid_fill("accent1"))
    spPr.append(make_ln(12700, "dk1"))

    body = make_text_body([
        make_paragraph([make_run("Hello", bold=True, size_pt=24, color="lt1")], align="ctr"),
        make_paragraph([make_run("World", italic=True, size_pt=18)], level=1),
        make_paragraph([]),
    ])

    print(to_xml_string(spPr))
    print(to_xml_string(body))
