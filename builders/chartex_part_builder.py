#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: chartex_part_builder.py
Description: 
"""
from pathlib import Path
from lxml import etree
from core.xml_builder import make_sub_element, to_xml_string, NSMAP, qn, make_paragraph, make_run 
from builders.common import relationship_target
from builders.chart_workbook import build_chart_workbook_bytes, build_treemap_workbook_bytes
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry

CHARTEX_NS = "http://schemas.microsoft.com/office/drawing/2014/chartex"
CHARTEX_NSMAP = {"cx": CHARTEX_NS}

_ASSETS = Path(__file__).parent / "chartex_assets"

def load_chartex_style_xml(style_name: str) -> str:
    return (_ASSETS / f"{style_name}_style.xml").read_text(encoding="utf-8")

def load_chartex_colors_xml() -> str:
    return (_ASSETS / "chartex_colors.xml").read_text(encoding="utf-8")


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

def _waterfall_layout_pr(subtotal_indices):
    lp = etree.Element(cxqn("layoutPr"))
    subs = make_sub_element(lp, cxqn("subtotals"))
    for i in subtotal_indices:
        make_sub_element(subs, cxqn("idx"), attrib={"val": str(i)})
    return lp

def _binning_layout_pr(interval_closed="r"):
    lp = etree.Element(cxqn("layoutPr"))
    make_sub_element(lp, cxqn("binning"), attrib={"intervalClosed": interval_closed})
    return lp

def _series_guid(s_idx):
    return f"{{00000000-0000-0000-0000-{s_idx + 1:012d}}}"

def _boxwhisker_layout_pr():
    lp = etree.Element(cxqn("layoutPr"))
    make_sub_element(lp, cxqn("visibility"),
                     attrib={"meanLine": "0", "meanMarker": "1",
                             "nonoutliers": "0", "outliers": "1"})
    make_sub_element(lp, cxqn("statistics"), attrib={"quartileMethod": "exclusive"})
    return lp

def _two_axes(cat_gap="0.5"):
    cat = etree.Element(cxqn("axis"), attrib={"id": "0"})
    make_sub_element(cat, cxqn("catScaling"), attrib={"gapWidth": cat_gap})
    make_sub_element(cat, cxqn("tickLabels"))
    val = etree.Element(cxqn("axis"), attrib={"id": "1"})
    make_sub_element(val, cxqn("valScaling"))
    make_sub_element(val, cxqn("majorGridlines"))
    make_sub_element(val, cxqn("tickLabels"))
    return [cat, val]

def build_chartex_part_xml(workbook_rid: str, categories: list, series_list: list,
                           layout_id: str, data_labels: dict, data_labels_pos: str = None,
                           title: str = None, layout_pr=None, axes=None, legend=None) -> str:
    
    n = len(series_list[0]["values"]) if not categories else len(categories)

    root = etree.Element(cxqn("chartSpace"),
                         nsmap={"cx": CHARTEX_NS, "r": NSMAP["r"], "a": NSMAP["a"]})
    chart_data = make_sub_element(root, cxqn("chartData"))
    ext = make_sub_element(chart_data, cxqn("externalData"))
    ext.set(qn("r", "id"), workbook_rid)
    ext.set(cxqn("autoUpdate"), "0")

    for s_idx, series in enumerate(series_list):
        data = make_sub_element(chart_data, cxqn("data"), attrib={"id": str(s_idx)})

        if categories:
            cat_ref = f"Sheet1!$A$2:$A${n+1}"
            val_col = chr(ord("B") + s_idx)     # B, C, D, one col per series
            val_ref = f"Sheet1!${val_col}$2:${val_col}${n+1}"
            str_dim = make_sub_element(data, cxqn("strDim"), attrib={"type": "cat"})
            make_sub_element(str_dim, cxqn("f"), text=cat_ref)
            str_lvl = make_sub_element(str_dim, cxqn("lvl"), attrib={"ptCount": str(n)})
            for i, c in enumerate(categories):
                make_sub_element(str_lvl, cxqn("pt"), text=str(c), attrib={"idx": str(i)})
        else:
            val_ref = f"Sheet1!$A$2:$A${n+1}"   # no category column → values in A
        

        num_dim = make_sub_element(data, cxqn("numDim"), attrib={"type": "val"})
        make_sub_element(num_dim, cxqn("f"), text=val_ref)
        num_lvl = make_sub_element(num_dim, cxqn("lvl"),
                                attrib={"ptCount": str(n), "formatCode": "General"})
        
        for i, v in enumerate(series["values"]):
            make_sub_element(num_lvl, cxqn("pt"), text=str(v), attrib={"idx": str(i)})

    chart = make_sub_element(root, cxqn("chart"))

    title_el = make_sub_element(chart, cxqn("title"),
                                attrib={"pos": "t", "align": "ctr", "overlay": "0"})
    if title:
        tx = make_sub_element(title_el, cxqn("tx"))
        rich = make_sub_element(tx, cxqn("rich"))
        make_sub_element(rich, qn("a", "bodyPr"))      # minimal — add attrs only if repair
        make_sub_element(rich, qn("a", "lstStyle"))
        rich.append(make_paragraph([make_run(str(title))]))

    plot_area = make_sub_element(chart, cxqn("plotArea"))
    region = make_sub_element(plot_area, cxqn("plotAreaRegion"))

    for s_idx, series in enumerate(series_list):
        ser = make_sub_element(region, cxqn("series"),
                               attrib={"layoutId": layout_id,
                                       "uniqueId": _series_guid(s_idx)})
        if data_labels is not None:
            dl = make_sub_element(ser, cxqn("dataLabels"))
            if data_labels_pos:
                dl.set("pos", data_labels_pos)
            make_sub_element(dl, cxqn("visibility"), attrib=data_labels)
        make_sub_element(ser, cxqn("dataId"), attrib={"val": str(s_idx)})
        
        if layout_pr is not None:
            el = layout_pr(s_idx)
            if el is not None:
                ser.append(el)

    if axes is None:
        axis = make_sub_element(plot_area, cxqn("axis"), attrib={"id": "0"})
        make_sub_element(axis, cxqn("catScaling"), attrib={"gapWidth": "0.0599999987"})
        make_sub_element(axis, cxqn("tickLabels"))
    else:
        for ax in axes:
            plot_area.append(ax)  

    if legend is not None:
        make_sub_element(chart, cxqn("legend"), attrib=legend)

    return to_xml_string(root)

def build_pareto_part_xml(workbook_rid, categories, series_list, title=None):
    n = len(categories)
    root = etree.Element(cxqn("chartSpace"),
                         nsmap={"cx": CHARTEX_NS, "r": NSMAP["r"], "a": NSMAP["a"]})
    chart_data = make_sub_element(root, cxqn("chartData"))
    ext = make_sub_element(chart_data, cxqn("externalData"))
    ext.set(qn("r", "id"), workbook_rid)
    ext.set(cxqn("autoUpdate"), "0")

    # ONE data block: raw observations (categories repeat), values in B
    data = make_sub_element(chart_data, cxqn("data"), attrib={"id": "0"})
    str_dim = make_sub_element(data, cxqn("strDim"), attrib={"type": "cat"})
    make_sub_element(str_dim, cxqn("f"), text=f"Sheet1!$A$2:$A${n+1}")
    str_lvl = make_sub_element(str_dim, cxqn("lvl"), attrib={"ptCount": str(n)})
    for i, c in enumerate(categories):
        make_sub_element(str_lvl, cxqn("pt"), text=str(c), attrib={"idx": str(i)})
    num_dim = make_sub_element(data, cxqn("numDim"), attrib={"type": "val"})
    make_sub_element(num_dim, cxqn("f"), text=f"Sheet1!$B$2:$B${n+1}")
    num_lvl = make_sub_element(num_dim, cxqn("lvl"), attrib={"ptCount": str(n), "formatCode": "General"})
    for i, v in enumerate(series_list[0]["values"]):
        make_sub_element(num_lvl, cxqn("pt"), text=str(v), attrib={"idx": str(i)})

    chart = make_sub_element(root, cxqn("chart"))
    # title (shared structure)
    title_el = make_sub_element(chart, cxqn("title"), attrib={"pos":"t","align":"ctr","overlay":"0"})
    if title:
        tx = make_sub_element(title_el, cxqn("tx"))
        rich = make_sub_element(tx, cxqn("rich"))
        make_sub_element(rich, qn("a","bodyPr"))
        make_sub_element(rich, qn("a","lstStyle"))
        rich.append(make_paragraph([make_run(str(title))]))

    plot_area = make_sub_element(chart, cxqn("plotArea"))
    region = make_sub_element(plot_area, cxqn("plotAreaRegion"))

    # series 0: clusteredColumn (the bars) — has data, aggregation, axisId=1
    col = make_sub_element(region, cxqn("series"),
                           attrib={"layoutId":"clusteredColumn", "uniqueId":_series_guid(0)})
    ctx = make_sub_element(col, cxqn("tx"))
    ctxd = make_sub_element(ctx, cxqn("txData"))
    make_sub_element(ctxd, cxqn("f"), text="Sheet1!$B$1")
    make_sub_element(ctxd, cxqn("v"), text=series_list[0]["name"])
    make_sub_element(col, cxqn("dataId"), attrib={"val":"0"})
    clp = make_sub_element(col, cxqn("layoutPr"))
    make_sub_element(clp, cxqn("aggregation"))
    make_sub_element(col, cxqn("axisId"), attrib={"val":"1"})

    # series 1: paretoLine (the cumulative line) — DERIVED, no data, ownerIdx=0, axisId=2
    line = make_sub_element(region, cxqn("series"),
                            attrib={"layoutId":"paretoLine", "ownerIdx":"0", "uniqueId":_series_guid(1)})
    make_sub_element(line, cxqn("axisId"), attrib={"val":"2"})

    # THREE axes: cat(0), val count(1), val percentage(2)
    ax0 = make_sub_element(plot_area, cxqn("axis"), attrib={"id":"0"})
    make_sub_element(ax0, cxqn("catScaling"), attrib={"gapWidth":"0"})
    make_sub_element(ax0, cxqn("tickLabels"))
    ax1 = make_sub_element(plot_area, cxqn("axis"), attrib={"id":"1"})
    make_sub_element(ax1, cxqn("valScaling"))
    make_sub_element(ax1, cxqn("majorGridlines"))
    make_sub_element(ax1, cxqn("tickLabels"))
    ax2 = make_sub_element(plot_area, cxqn("axis"), attrib={"id":"2"})
    vs2 = make_sub_element(ax2, cxqn("valScaling"), attrib={"max":"1","min":"0"})
    make_sub_element(ax2, cxqn("units"), attrib={"unit":"percentage"})
    make_sub_element(ax2, cxqn("tickLabels"))

    return to_xml_string(root)

def build_hierarchical_part_xml(workbook_rid, categories, series_list, title=None, *,
                                layout_id, data_labels_pos, parent_label_layout, legend):
    series = series_list[0]
    records = series["points"]
    series_name = series.get("name", "Size")
    n = len(records)
    depth = len(records[0]["path"])
    last_label_col = chr(ord("A") + depth - 1)
    size_col       = chr(ord("A") + depth)

    root = etree.Element(cxqn("chartSpace"),
                         nsmap={"cx": CHARTEX_NS, "r": NSMAP["r"], "a": NSMAP["a"]})
    chart_data = make_sub_element(root, cxqn("chartData"))
    ext = make_sub_element(chart_data, cxqn("externalData"))
    ext.set(qn("r", "id"), workbook_rid)
    ext.set(cxqn("autoUpdate"), "0")

    data = make_sub_element(chart_data, cxqn("data"), attrib={"id": "0"})
    str_dim = make_sub_element(data, cxqn("strDim"), attrib={"type": "cat"})
    make_sub_element(str_dim, cxqn("f"), text=f"Sheet1!$A$2:${last_label_col}${n+1}")
    for j in range(depth):
        lvl = make_sub_element(str_dim, cxqn("lvl"), attrib={"ptCount": str(n)})
        for i, rec in enumerate(records):
            label = rec["path"][depth - 1 - j]
            make_sub_element(lvl, cxqn("pt"), text=str(label), attrib={"idx": str(i)})

    num_dim = make_sub_element(data, cxqn("numDim"), attrib={"type": "size"})
    make_sub_element(num_dim, cxqn("f"), text=f"Sheet1!${size_col}$2:${size_col}${n+1}")
    num_lvl = make_sub_element(num_dim, cxqn("lvl"),
                               attrib={"ptCount": str(n), "formatCode": "General"})
    for i, rec in enumerate(records):
        make_sub_element(num_lvl, cxqn("pt"), text=str(rec["value"]), attrib={"idx": str(i)})

    chart = make_sub_element(root, cxqn("chart"))
    title_el = make_sub_element(chart, cxqn("title"), attrib={"pos": "t", "align": "ctr", "overlay": "0"})
    if title:
        tx = make_sub_element(title_el, cxqn("tx"))
        rich = make_sub_element(tx, cxqn("rich"))
        make_sub_element(rich, qn("a", "bodyPr"))
        make_sub_element(rich, qn("a", "lstStyle"))
        rich.append(make_paragraph([make_run(str(title))]))

    plot_area = make_sub_element(chart, cxqn("plotArea"))
    region = make_sub_element(plot_area, cxqn("plotAreaRegion"))
    ser = make_sub_element(region, cxqn("series"),
                           attrib={"layoutId": layout_id, "uniqueId": _series_guid(0)})
    stx = make_sub_element(ser, cxqn("tx"))
    stxd = make_sub_element(stx, cxqn("txData"))
    make_sub_element(stxd, cxqn("f"), text=f"Sheet1!${size_col}$1")
    make_sub_element(stxd, cxqn("v"), text=series_name)
    dl = make_sub_element(ser, cxqn("dataLabels"), attrib={"pos": data_labels_pos})
    make_sub_element(dl, cxqn("visibility"),
                     attrib={"seriesName": "0", "categoryName": "1", "value": "0"})
    make_sub_element(ser, cxqn("dataId"), attrib={"val": "0"})
    if parent_label_layout is not None:
        lp = make_sub_element(ser, cxqn("layoutPr"))
        make_sub_element(lp, cxqn("parentLabelLayout"), attrib={"val": parent_label_layout})
    if legend is not None:
        make_sub_element(chart, cxqn("legend"), attrib=legend)

    return to_xml_string(root)


def build_treemap_part_xml(workbook_rid, categories, series_list, title=None):
    return build_hierarchical_part_xml(
        workbook_rid, categories, series_list, title=title,
        layout_id="treemap",
        data_labels_pos="inEnd",
        parent_label_layout="overlapping",
        legend={"pos": "t", "align": "ctr", "overlay": "0"},
    )


def build_sunburst_part_xml(workbook_rid, categories, series_list, title=None):
    return build_hierarchical_part_xml(
        workbook_rid, categories, series_list, title=title,
        layout_id="sunburst",
        data_labels_pos="ctr",
        parent_label_layout=None,    # sunburst has no layoutPr
        legend=None,                 # sunburst has no legend
    )

def emit_chartex(shape_data, slide_state, relationships, content_types):
    """Emit a p:graphicFrame referencing a data-driven chartEx part"""
    spec = CHARTEX_TYPES[shape_data["type"]]

    chartex_part_path = slide_state.next_chartex_path()

    # Clean index from "ppt/charts/chartEx3.xml" -> "3" (rsplit on "chartEx", not "chart")
    chartex_index = chartex_part_path.rsplit("chartEx", 1)[-1].split(".")[0]

    workbook_path = f"xl/embeddings/Microsoft_Excel_Worksheet_chartEx{chartex_index}.xlsx"
    style_path    = f"ppt/charts/style_chartEx{chartex_index}.xml"
    colors_path   = f"ppt/charts/colors_chartEx{chartex_index}.xml"

    categories  = shape_data["categories"]
    series_list = shape_data["series"]
    title       = shape_data.get("title")

    # --- workbook: special case for treemaps
    if "workbook" in spec:
        slide_state.chart_parts[workbook_path] = spec["workbook"](categories, series_list)
    else:
        slide_state.chart_parts[workbook_path] = build_chart_workbook_bytes(categories, series_list)
    content_types.add_override(workbook_path, ContentTypeRegistry.SPREADSHEET)

    workbook_rid = relationships.add(
        chartex_part_path,
        relationship_target(chartex_part_path, workbook_path),
        RelationshipRegistry.PACKAGE,
    )

    # --- part body: dedicated builder (pareto) vs generic spec-driven builder ---
    if "build" in spec:
        part_xml = spec["build"](workbook_rid, categories, series_list, title=title)
    else:
        dsl_legend = shape_data.get("legend")     # "t" / "none" / None (unspecified)
        if dsl_legend == "none":
            legend = None
        elif dsl_legend == "t":
            legend = {"pos": "t", "align": "ctr", "overlay": "0"}
        else:                                      # unspecified → type default from spec
            legend = spec.get("legend")

        part_xml = build_chartex_part_xml(
            workbook_rid=workbook_rid,
            categories=categories,
            series_list=series_list,
            layout_id=spec["layout_id"],
            data_labels=spec["data_labels"],
            data_labels_pos=spec.get("data_labels_pos"),
            title=title,
            layout_pr=spec["layout_pr"](shape_data),
            axes=spec["axes"](shape_data),
            legend=legend,
        )

    slide_state.chart_parts[chartex_part_path] = part_xml
    content_types.add_override(chartex_part_path, ContentTypeRegistry.CHARTEX)

    # --- style + colors parts (shared) ---
    slide_state.chart_parts[style_path] = load_chartex_style_xml(spec["style"])
    content_types.add_override(style_path, ContentTypeRegistry.CHART_STYLE)
    relationships.add(
        chartex_part_path,
        relationship_target(chartex_part_path, style_path),
        RelationshipRegistry.CHART_STYLE,
    )

    slide_state.chart_parts[colors_path] = load_chartex_colors_xml()
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

    # --- graphicFrame on the slide ---
    x  = int(shape_data.get("x", 914400))
    y  = int(shape_data.get("y", 914400))
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

CHARTEX_TYPES = {
    "funnel": {
        "layout_id": "funnel",
        "style":     "funnel",
        "axes":      lambda sd: None,            # None → builder's default single catScaling axis
        "layout_pr": lambda sd: (lambda i: None),            # funnel series has no layoutPr
        "data_labels": {"seriesName":"0","categoryName":"0","value":"1"},
        "legend": None,
        
    },
    "waterfall": {
        "layout_id": "waterfall",
        "style":     "waterfall",
        "axes":      lambda sd: _two_axes("0.5"),
        "layout_pr": lambda sd: (lambda i: _waterfall_layout_pr(sd.get("subtotals", []))),
        "data_labels": {"seriesName":"0","categoryName":"0","value":"1"},
        "data_labels_pos": "outEnd",
        "legend": {"pos":"t","align":"ctr","overlay":"0"},
    },
    "histogram": {
        "layout_id": "clusteredColumn",
        "style":     "histogram",
        "axes":      lambda sd: _two_axes("0"),
        "layout_pr": lambda sd: (lambda i: _binning_layout_pr("r")),
        "data_labels": None,
        "legend": None,
    },
    "boxWhisker": {
        "layout_id": "boxWhisker",
        "style":     "boxwhisker",
        "axes":      lambda sd: _two_axes("1"),
        "layout_pr": lambda sd: (lambda i: _boxwhisker_layout_pr()),
        "data_labels": {"seriesName":"0","categoryName":"0","value":"0"},
        "legend": None,
    },
    "pareto": {
        "style": "histogram",          # shares histogram's style (verified md5)
        "build": build_pareto_part_xml,
    },
    "treemap": {
        "style": "treemap",
        "build": build_treemap_part_xml,
        "workbook": build_treemap_workbook_bytes,
    },
    "sunburst": {
        "style": "sunburst",
        "build": build_sunburst_part_xml,
        "workbook": build_treemap_workbook_bytes,   # same hierarchical workbook
    },
}

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "waterfall":
        cats = [f"Category {i+1}" for i in range(8)]
        series_list = [{"name": "Series1", "values": [100, 20, 50, -40, 130, -60, 70, 140]}]
        print(build_chartex_part_xml(
            "rId1", cats, series_list,
            layout_id="waterfall",
            data_labels={"seriesName":"0","categoryName":"0","value":"1"},
            data_labels_pos="outEnd",
            title="This is my waterfall",
            layout_pr=lambda i: _waterfall_layout_pr([0, 4, 7]),
            axes=_two_axes("0.5"),
        ))

    elif len(sys.argv) > 1 and sys.argv[1] == "histogram":
        vals = [1, 3, 3, 5, 6, 6, 7, 8, 9, 9, 10, 10, 11, 12, 13, 14, 15, 16, 17, 19, 22, 24]
        series_list = [{"name": "Series1", "values": vals}]
        print(build_chartex_part_xml(
            "rId1", [], series_list,
            layout_id="clusteredColumn",
            data_labels=None,
            title="This is my histogram",
            layout_pr=lambda i: _binning_layout_pr("r"),
            axes=_two_axes("0"),
        ))

    elif len(sys.argv) > 1 and sys.argv[1] == "boxwhisker":
        cats = ["Category 1"]*11 + ["Category 2"]*11
        series_list = [
            {"name": "Series1", "values": [-7,-10,-28,47,11,-24,-24,36,10,-78,47,-24,-17,-12,-11,17,14,46,-18,19,-26,-20]},
            {"name": "Series2", "values": [-3,1,-6,10,34,128,22,-12,-28,6,31,3,12,-12,-13,6,15,41,16,10,23,16]},
        ]
        print(build_chartex_part_xml(
            "rId1", cats, series_list,
            layout_id="boxWhisker",
            data_labels={"seriesName":"0","categoryName":"0","value":"0"},
            title="Boxes and whiskers",
            layout_pr=lambda i: _boxwhisker_layout_pr(),
            axes=_two_axes("1"),
        ))

    elif len(sys.argv) > 1 and sys.argv[1] == "pareto":
        import random
        random.seed(0)
        cats = [f"Category {random.randint(1,4)}" for _ in range(50)]
        series_list = [{"name": "Series1", "values": [1]*50}]
        print(build_pareto_part_xml(
            "rId1", cats, series_list,
            title="This is my pareto",
        ))

    elif len(sys.argv) > 1 and sys.argv[1] == "treemap":
        stems_for = ["Stem 1"]*3 + ["Stem 2"]*4 + ["Stem 3"]*2 + ["Stem 4"]*2 + ["Stem 5"]*2 + ["Stem 6"]*3
        branches_for = ["Branch 1"]*7 + ["Branch 2"]*4 + ["Branch 3"]*5
        sizes = [22,12,18,87,88,17,9,25,23,24,89,16,19,86,10,11]
        records = [{"path": [branches_for[i], stems_for[i], f"Leaf {i+1}"], "value": sizes[i]}
                   for i in range(16)]
        series_list = [{"name": "Series1", "points": records}]
        print(build_treemap_part_xml("rId1", [], series_list, title="This is my treemap"))
    
    elif len(sys.argv) > 1 and sys.argv[1] == "sunburst":
        stems_for = ["Stem 1"]*3 + ["Stem 2"]*4 + ["Stem 3"]*2 + ["Stem 4"]*2 + ["Stem 5"]*2 + ["Stem 6"]*3
        branches_for = ["Branch 1"]*7 + ["Branch 2"]*4 + ["Branch 3"]*5
        sizes = [22,12,18,87,88,17,9,25,23,24,89,16,19,86,10,11]
        records = [{"path": [branches_for[i], stems_for[i], f"Leaf {i+1}"], "value": sizes[i]}
                   for i in range(16)]
        series_list = [{"name": "Series1", "points": records}]
        print(build_sunburst_part_xml("rId1", [], series_list, title="This is my sunburst"))

    else:
        # funnel (regression anchor)
        print(build_chartex_part_xml(
            "rId1",
            ["Leads", "Qualified", "Proposal", "Won"],
            [{"name": "Count", "values": [1000, 600, 300, 150]}],
            layout_id="funnel",
            title="Funnel",
            data_labels={"seriesName":"0","categoryName":"0","value":"1"},
        ))