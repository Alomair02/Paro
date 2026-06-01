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


def make_prst_geom(prst: str = "rect") -> etree._Element:
    """
    Build an a:prstGeom element for a preset shape.
    prst is one of the 187 preset shape names: "rect", "ellipse", "roundRect", etc.
    """
    geom = etree.Element(qn("a", "prstGeom"))
    geom.set("prst", prst)
    etree.SubElement(geom, qn("a", "avLst"))  # required child, even if empty
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


def make_solid_fill(color: str) -> etree._Element:
    """
    Build an a:solidFill element.
    color is either:
      - a scheme token like "accent1", "dk1"  → a:schemeClr
      - a hex RGB string like "FF0000"         → a:srgbClr
    """
    fill = etree.Element(qn("a", "solidFill"))
    if color in _SCHEME_TOKENS:
        clr = etree.SubElement(fill, qn("a", "schemeClr"))
        clr.set("val", color)
    else:
        clr = etree.SubElement(fill, qn("a", "srgbClr"))
        clr.set("val", color.lstrip("#").upper())
    return fill


def make_no_fill() -> etree._Element:
    """Build an a:noFill element."""
    return etree.Element(qn("a", "noFill"))


# ---------------------------------------------------------------------------
# Line / stroke builder
# ---------------------------------------------------------------------------

def make_ln(width_emu: int = 0, color: str = None) -> etree._Element:
    """
    Build an a:ln element.
    width_emu = 0 → no line (a:noFill inside).
    color follows the same rules as make_solid_fill.
    """
    ln = etree.Element(qn("a", "ln"))
    if width_emu:
        ln.set("w", str(width_emu))
        ln.append(make_solid_fill(color if color else "dk1"))
    else:
        ln.append(make_no_fill())
    return ln


# ---------------------------------------------------------------------------
# Text builders
# ---------------------------------------------------------------------------

def make_run(text: str,
             bold: bool = False,
             italic: bool = False,
             size_pt: float = None,
             color: str = None,
             font: str = None) -> etree._Element:
    """
    Build an a:r element (text run).
    size_pt is in points; converted internally to hundredths of a point.
    """
    run = etree.Element(qn("a", "r"))

    rpr = etree.SubElement(run, qn("a", "rPr"))
    rpr.set("lang", "en-US")
    rpr.set("dirty", "0")

    if bold:    rpr.set("b", "1")
    if italic:  rpr.set("i", "1")
    if size_pt: rpr.set("sz", str(int(size_pt * 100)))

    if color:
        rpr.append(make_solid_fill(color))
    if font:
        latin = etree.SubElement(rpr, qn("a", "latin"))
        latin.set("typeface", font)

    t = etree.SubElement(run, qn("a", "t"))
    t.text = text

    return run


def make_paragraph(runs: list = None,
                   level: int = 0,
                   align: str = None) -> etree._Element:
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
