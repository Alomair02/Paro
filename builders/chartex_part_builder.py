#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: chartex_part_builder.py
Description: 
"""
from pathlib import Path
from lxml import etree
from core.xml_builder import make_sub_element, to_xml_string, NSMAP, qn 
from builders.common import relationship_target
from builders.chart_workbook import build_chart_workbook_bytes
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry

CHARTEX_NS = "http://schemas.microsoft.com/office/drawing/2014/chartex"
CHARTEX_NSMAP = {"cx": CHARTEX_NS}

_ASSETS = Path(__file__).parent / "chartex_assets"

def load_funnel_style_xml() -> str:
    return (_ASSETS / "funnel_style.xml").read_text(encoding="utf-8")

def load_funnel_colors_xml() -> str:
    return (_ASSETS / "funnel_colors.xml").read_text(encoding="utf-8")

def cxqn(local: str) -> str:
    """Clark name in the chartex namespace"""
    return f"{{{CHARTEX_NS}}}{local}"

def _cx(parent, local, text=None, **attrs):
    el = etree.SubElement(parent, cxqn(local))
    for k, v in attrs.items():
        el.set(k, str(v))
    if text is not None:
        el.text = text
    return el

def build_funnel_part_xml(workbook_rid: str) -> str:
    root = etree.Element(cxqn("chartSpace"), nsmap={"cx": CHARTEX_NS, "r": NSMAP["r"]})

    chart_data = make_sub_element(root, cxqn("chartData"))
    ext = make_sub_element(chart_data, cxqn("externalData"))
    ext.set(qn("r", "id"), workbook_rid)
    ext.set(cxqn("autoUpdate"), "0")

    data = make_sub_element(chart_data, cxqn("data"), attrib={"id": "0"})

    cats = ["Leads", "Qualified", "Proposal", "Won"]
    str_dim = make_sub_element(data, cxqn("strDim"), attrib={"type": "cat"})
    make_sub_element(str_dim, cxqn("f"), text="Sheet1!$A$2:$A$5")
    str_lvl = make_sub_element(str_dim, cxqn("lvl"), attrib={"ptCount": str(len(cats))})
    for i, c in enumerate(cats):
        make_sub_element(str_lvl, cxqn("pt"), text=c, attrib={"idx": str(i)})
    
    vals = ["1000", "600", "300", "150"]
    num_dim = make_sub_element(data, cxqn("numDim"), attrib={"type": "val"})
    make_sub_element(num_dim, cxqn("f"), text="Sheet1!$B$2:$B$5")
    num_lvl = make_sub_element(num_dim, cxqn("lvl"),
                               attrib={"ptCount": str(len(vals)), "formatCode": "General"})
    for i, v in enumerate(vals):
        make_sub_element(num_lvl, cxqn("pt"), text=v, attrib={"idx": str(i)})

    chart = make_sub_element(root, cxqn("chart"))
    title = make_sub_element(chart, cxqn("title"), attrib={"pos": "t", "align": "ctr", "overlay": "0"})
    plot_area = make_sub_element(chart, cxqn("plotArea"))
    region = make_sub_element(plot_area, cxqn("plotAreaRegion"))
    axis = make_sub_element(plot_area, cxqn("axis"), attrib={"id": "0"})
    make_sub_element(axis, cxqn("catScaling"), attrib={"gapWidth": "0.0599999987"})
    make_sub_element(axis, cxqn("tickLabels"))
    series = make_sub_element(region, cxqn("series"),
                              attrib={"layoutId": "funnel",
                                      "uniqueId": "{00000000-0000-0000-0000-000000000001}"})
    data_labels = make_sub_element(series, cxqn("dataLabels"))
    make_sub_element(data_labels, cxqn("visibility"),
                     attrib={"seriesName": "0", "categoryName": "0", "value": "1"})
    make_sub_element(series, cxqn("dataId"), attrib={"val": "0"})

    return to_xml_string(root)

def emit_funnel(shape_data, slide_state, relationships, content_types):
    """Emit a p:graphicFrame referencing a hardcoded chartEx funnel part."""

    chartex_part_path   = slide_state.next_chartex_path()
    
    # Clean index from "ppt/charts/chartEx3.xml" -> "3" (rsplit on "chartEx", not "chart")
    chartex_index = chartex_part_path.rsplit("chartEx", 1)[-1].split(".")[0]

    workbook_path = f"xl/embeddings/Microsoft_Excel_Worksheet_chartEx{chartex_index}.xlsx"
    style_path    = f"ppt/charts/style_chartEx{chartex_index}.xml"
    colors_path   = f"ppt/charts/colors_chartEx{chartex_index}.xml"

    categories = ["Leads", "Qualified", "Proposal", "Won"]
    series_list = [{"name": "Count", "values": [1000, 600, 300, 150], "tone": None}]

    slide_state.chart_parts[workbook_path] = build_chart_workbook_bytes(categories, series_list)
    content_types.add_override(workbook_path, ContentTypeRegistry.SPREADSHEET)

    workbook_rid = relationships.add(
        chartex_part_path,
        relationship_target(chartex_part_path, workbook_path),
        RelationshipRegistry.PACKAGE,
    )


    slide_state.chart_parts[chartex_part_path] = build_funnel_part_xml(workbook_rid)
    content_types.add_override(chartex_part_path, ContentTypeRegistry.CHARTEX)

    slide_state.chart_parts[style_path] = load_funnel_style_xml()
    content_types.add_override(style_path, ContentTypeRegistry.CHART_STYLE)
    relationships.add(
        chartex_part_path,
        relationship_target(chartex_part_path, style_path),
        RelationshipRegistry.CHART_STYLE,
    )

    slide_state.chart_parts[colors_path] = load_funnel_colors_xml()
    content_types.add_override(colors_path, ContentTypeRegistry.CHART_COLOR_STYLE)
    relationships.add(
        chartex_part_path,
        relationship_target(chartex_part_path, colors_path),
        RelationshipRegistry.CHART_COLOR_STYLE,
    )

    rid = relationships.add(
        slide_state.part_path,
        relationship_target(slide_state.part_path, chartex_part_path),
        RelationshipRegistry.CHARTEX,
    )

    x = int(shape_data.get("x", 914400))
    y = int(shape_data.get("y", 914400))
    cx = int(shape_data.get("w", 6858000))
    cy = int(shape_data.get("h", 4572000))

    gf = etree.Element(qn("p", "graphicFrame"))
    nv = etree.SubElement(gf, qn("p", "nvGraphicFramePr"))
    cnv = etree.SubElement(nv, qn("p", "cNvPr"))
    cnv.set("id", str(slide_state.next_id()))
    cnv.set("name", chartex_part_path.rsplit("/", 1)[-1])
    etree.SubElement(nv, qn("p", "cNvGraphicFramePr"))
    etree.SubElement(nv, qn("p", "nvPr"))

    xfrm = etree.SubElement(gf, qn("p", "xfrm"))
    off = etree.SubElement(xfrm, qn("a", "off")); off.set("x", str(x)); off.set("y", str(y))
    ext = etree.SubElement(xfrm, qn("a", "ext")); ext.set("cx", str(cx)); ext.set("cy", str(cy))

    chartex_child_nsmap = {"cx": CHARTEX_NS, "r": NSMAP["r"]}
    graphic = etree.SubElement(gf, qn("a", "graphic"))
    gdata = etree.SubElement(graphic, qn("a", "graphicData"))
    gdata.set("uri", CHARTEX_NS)
    chart_ref = etree.SubElement(gdata, cxqn("chart"), nsmap=chartex_child_nsmap)
    chart_ref.set(qn("r", "id"), rid)
    return gf

if __name__ == "__main__":
     print(build_funnel_part_xml("rId1"))