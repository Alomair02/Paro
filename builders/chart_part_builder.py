#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: chart_part_builder.py
Description: Emits a native OOXML chart part (charts/chartN.xml).
Stage 1: a single hardcoded column chart to prove the chart-part XML.
The c: (chart) namespace is declared locally on the chart root only,
never in the global NSMAP, so existing parts stay byte-identical.
"""

from lxml import etree
from builders.common import relationship_target
from core.relationship_reg import RelationshipRegistry
from core.content_type_reg import ContentTypeRegistry
from core.xml_builder import NSMAP, make_effect_list, make_solid_fill, make_gradient_fill, make_ln, qn, to_xml_string
from builders.chart_workbook import build_chart_workbook_bytes
from utils.converter import UnitConverter


# Chart namespace — declared locally on the chart part root, not globally.
CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"

CHART_NSMAP = {
    "c": CHART_NS,
    "a": NSMAP["a"],
    "r": NSMAP["r"],
}


def cqn(local: str) -> str:
    """Clark name in the chart namespace: cqn('barChart') -> '{...chart}barChart'."""
    return f"{{{CHART_NS}}}{local}"


def _c(parent, local, text=None, **attrs):
    """Make a c:-namespaced sub-element with optional text + attributes."""
    el = etree.SubElement(parent, cqn(local))
    for k, v in attrs.items():
        el.set(k, str(v))
    if text is not None:
        el.text = text
    return el


def _str_ref(parent, tag, ref_formula, values):
    """
    Build a c:cat or c:tx-style string reference with cached values.
    <c:{tag}><c:strRef><c:f>ref</c:f><c:strCache>...</c:strCache></c:strRef></c:{tag}>
    """
    wrapper = _c(parent, tag)
    str_ref = _c(wrapper, "strRef")
    _c(str_ref, "f", text=ref_formula)
    cache = _c(str_ref, "strCache")
    _c(cache, "ptCount", val=len(values))
    for i, v in enumerate(values):
        pt = _c(cache, "pt", idx=i)
        _c(pt, "v", text=str(v))
    return wrapper


def _num_ref(parent, tag, ref_formula, values):
    """
    Build a c:val-style numeric reference with cached values.
    """
    wrapper = _c(parent, tag)
    num_ref = _c(wrapper, "numRef")
    _c(num_ref, "f", text=ref_formula)
    cache = _c(num_ref, "numCache")
    _c(cache, "formatCode", text="General")
    _c(cache, "ptCount", val=len(values))
    for i, v in enumerate(values):
        pt = _c(cache, "pt", idx=i)
        _c(pt, "v", text=str(v))
    return wrapper

def _apply_bar_finish(sp_pr, tone, finish):
    """Fill + border + shadow for a bar/column/area series mark, per finish."""
    fill_mode = finish.get("fillMode", "solid")
    if fill_mode == "gradient":
        sp_pr.append(make_gradient_fill(tone))
    elif fill_mode == "tinted":
        sp_pr.append(make_solid_fill(tone, {"lumMod": 60000, "lumOff": 40000}))
    else:
        sp_pr.append(make_solid_fill(tone))

    border = finish.get("border")
    if border:
        color = tone if border.get("color") == "tone" else border.get("color", "dk2")
        sp_pr.append(make_ln(UnitConverter.to_emu(border.get("width", "1pt")), color))

    shadow = finish.get("shadow")
    if shadow:
        sp_pr.append(make_effect_list({
            "blurRad": UnitConverter.to_emu(shadow["blur"]),
            "dist": UnitConverter.to_emu(shadow["dist"]),
            "dir": shadow["dir"],
            "alpha": shadow["alpha"],
        }))

def build_chart_part_xml(workbook_rid: str, categories: list, series_list: list, chart_type: str = "column", style: dict | None = None, finish: dict | None = None, stacked: str = "false", legend: str | None = None) -> str:
    """
    series_list: [{"name": str, "values": [num], "tone": str|None}, ...]
    chart_type: column|bar|line|area|pie
    """
    style = style or {}
    finish = finish or {}
    palette = style.get("palette") or ["accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]
    # Fresh per chart part: dispenses 111111111, 222222222, 333333333, 444444444
    # in call order. One allocator per build_chart_part_xml call, so ids never
    # leak across charts and single-plot charts always emit the same first two.
    _next_axis_id = [0]
    def alloc_axis_id() -> str:
        _next_axis_id[0] += 1
        return str(111111111 * _next_axis_id[0])
    
    n = len(categories)
    cat_ref = f"Sheet1!$A$2:$A${n+1}"
    cat_ax_id, val_ax_id = alloc_axis_id(), alloc_axis_id()

    root = etree.Element(cqn("chartSpace"), nsmap=CHART_NSMAP)
    chart = _c(root, "chart")
    plot_area = _c(chart, "plotArea")
    _c(plot_area, "layout")

    # --- plot-type element ---
    if chart_type == "combo":
        needs_value_axis = False   # combo emits its own axes inline; skip the single-plot tail

        PLOT_ELEMENT = {"column": "barChart", "bar": "barChart",
                        "line": "lineChart", "area": "areaChart"}
        BAR_DIR = {"column": "col", "bar": "bar"}

        uses_secondary = any(s.get("axis", "primary") == "secondary" for s in series_list)
        pri_cat, pri_val = alloc_axis_id(), alloc_axis_id()
        sec_val = sec_cat = None
        if uses_secondary:
            sec_val, sec_cat = alloc_axis_id(), alloc_axis_id()

        def axis_pair(axis):
            return (sec_cat, sec_val) if axis == "secondary" else (pri_cat, pri_val)

        groups, order = {}, []
        for gidx, s in enumerate(series_list):
            bucket = s["type"] if s["type"] in ("column", "bar") else PLOT_ELEMENT[s["type"]]
            key = (bucket, s.get("axis", "primary"))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((gidx, s))

        for key in order:
            first_type = groups[key][0][1]["type"]
            element = PLOT_ELEMENT[first_type]
            plot = _c(plot_area, element)
            if element == "barChart":
                _c(plot, "barDir", val=BAR_DIR[first_type])
            if element in ("barChart", "areaChart") and stacked in ("true", "percent"):
                _c(plot, "grouping", val="percentStacked" if stacked == "percent" else "stacked")
            else:
                _c(plot, "grouping", val="clustered" if element == "barChart" else "standard")
            _c(plot, "varyColors", val="0")

            for gidx, s in groups[key]:
                ser = _c(plot, "ser")
                _c(ser, "idx", val=gidx)
                _c(ser, "order", val=gidx)
                name_col = chr(ord("B") + gidx)
                _str_ref(ser, "tx", f"Sheet1!${name_col}$1", [s["name"]])
                tone = s.get("tone") or palette[gidx % len(palette)]
                sp_pr = _c(ser, "spPr")
                if element == "lineChart":
                    ln = etree.SubElement(sp_pr, qn("a", "ln"))
                    ln.append(make_solid_fill(tone))
                else:
                    _apply_bar_finish(sp_pr, tone, finish)
                _str_ref(ser, "cat", cat_ref, categories)
                _num_ref(ser, "val", f"Sheet1!${name_col}$2:${name_col}${n+1}", s["values"])
                if element == "lineChart":
                    _c(ser, "smooth", val="0")

            if element == "barChart" and stacked in ("true", "percent"):
                _c(plot, "overlap", val="100")
            gcat, gval = axis_pair(key[1])
            _c(plot, "axId", val=gcat)
            _c(plot, "axId", val=gval)

        def emit_cat_ax(ax_id, cross, delete="0"):
            ax = _c(plot_area, "catAx")
            _c(ax, "axId", val=ax_id)
            sc = _c(ax, "scaling"); _c(sc, "orientation", val="minMax")
            _c(ax, "delete", val=delete); _c(ax, "axPos", val="b")
            _c(ax, "crossAx", val=cross)

        def emit_val_ax(ax_id, cross, pos, gridlines=False, crosses=None):
            ax = _c(plot_area, "valAx")
            _c(ax, "axId", val=ax_id)
            sc = _c(ax, "scaling"); _c(sc, "orientation", val="minMax")
            _c(ax, "delete", val="0"); _c(ax, "axPos", val=pos)
            if gridlines:
                _c(ax, "majorGridlines")
            _c(ax, "crossAx", val=cross)
            if crosses:
                _c(ax, "crosses", val=crosses)

        emit_cat_ax(pri_cat, pri_val)
        emit_val_ax(pri_val, pri_cat, "l", gridlines=(style.get("gridlines") == "major"))
        if uses_secondary:
            emit_val_ax(sec_val, sec_cat, "r", crosses="max")
            emit_cat_ax(sec_cat, sec_val, delete="1")

    elif chart_type in ("column", "bar"):
        plot = _c(plot_area, "barChart")
        _c(plot, "barDir", val="col" if chart_type == "column" else "bar")
        _c(plot, "grouping", val="clustered")
        _c(plot, "varyColors", val="0")
        needs_value_axis = True
    elif chart_type == "line":
        plot = _c(plot_area, "lineChart")
        _c(plot, "grouping", val="standard")
        _c(plot, "varyColors", val="0")
        needs_value_axis = True
    elif chart_type == "area":
        plot = _c(plot_area, "areaChart")
        _c(plot, "grouping", val="standard")
        _c(plot, "varyColors", val="0")
        needs_value_axis = True
    elif chart_type == "pie":
        plot = _c(plot_area, "pieChart")
        _c(plot, "varyColors", val="1")
        needs_value_axis = False
    elif chart_type == "scatter":
        plot = _c(plot_area, "scatterChart")
        _c(plot, "scatterStyle", val="lineMarker")
        _c(plot, "varyColors", val="0")
        needs_value_axis = False

    else:
        raise ValueError(f"Chart type not yet supported in engine: {chart_type}")


    # --- series ---
    if chart_type == "combo":
        pass
    
    elif chart_type == "scatter":
        x_ax_id, y_ax_id = alloc_axis_id(), alloc_axis_id()
        for idx, series in enumerate(series_list):
            ser = _c(plot, "ser")
            _c(ser, "idx", val=idx)
            _c(ser, "order", val=idx)
            x_col = chr(ord("A") + idx * 2)
            y_col = chr(ord("A") + idx * 2 + 1)
            _str_ref(ser, "tx", f"Sheet1!${y_col}$1", [series["name"]])
            sp_pr = _c(ser, "spPr")
            ln = etree.SubElement(sp_pr, qn("a", "ln"))
            ln.append(make_solid_fill(series.get("tone") or palette[idx % len(palette)]))
            m = len(series["xy"])
            x_ref = f"Sheet1!${x_col}$2:${x_col}${m + 1}"
            y_ref = f"Sheet1!${y_col}$2:${y_col}${m + 1}"
            _num_ref(ser, "xVal", x_ref, [p[0] for p in series["xy"]])
            _num_ref(ser, "yVal", y_ref, [p[1] for p in series["xy"]])
        _c(plot, "axId", val=x_ax_id)
        _c(plot, "axId", val=y_ax_id)
        # two value axes
        for ax_id, pos, cross in ((x_ax_id, "b", y_ax_id), (y_ax_id, "l", x_ax_id)):
            ax = _c(plot_area, "valAx")
            _c(ax, "axId", val=ax_id)
            sc = _c(ax, "scaling"); _c(sc, "orientation", val="minMax")
            _c(ax, "delete", val="0"); _c(ax, "axPos", val=pos)
            if style.get("gridlines") == "major" and pos == "l":
                _c(ax, "majorGridlines")
            _c(ax, "crossAx", val=cross)
    else:   
        for idx, series in enumerate(series_list):
            ser = _c(plot, "ser")
            _c(ser, "idx", val=idx)
            _c(ser, "order", val=idx)
            name_col = chr(ord("B") + idx)
            _str_ref(ser, "tx", f"Sheet1!${name_col}$1", [series["name"]])
            if chart_type != "pie":
                sp_pr = _c(ser, "spPr")
                tone = series.get("tone") or palette[idx % len(palette)]
                if chart_type == "line":
                    ln = etree.SubElement(sp_pr, qn("a", "ln"))
                    ln.append(make_solid_fill(tone))
                else:
                    # fill per finish.fillMode
                    fill_mode = finish.get("fillMode", "solid")
                    if fill_mode == "gradient":
                        sp_pr.append(make_gradient_fill(tone)),
                    elif fill_mode == "tinted":
                        sp_pr.append(make_solid_fill(tone, {"lumMod": 60000, "lumOff": 40000}))
                    else:
                        sp_pr.append(make_solid_fill(tone))
                    
                    # border per finish.border
                    border = finish.get("border")
                    if border:
                        color = tone if border.get("color") == "tone" else border.get("color", "dk2")
                        sp_pr.append(make_ln(
                            UnitConverter.to_emu(border.get("width", "1pt")),
                            color,
                        ))
                    
                    # shadow per finish.shadow
                    shadow = finish.get("shadow")
                    if shadow:
                        sp_pr.append(make_effect_list({
                            "blurRad": UnitConverter.to_emu(shadow["blur"]),
                            "dist": UnitConverter.to_emu(shadow["dist"]),
                            "dir": shadow["dir"],
                            "alpha": shadow["alpha"],
                        }))


            _str_ref(ser, "cat", cat_ref, categories)
            _num_ref(ser, "val", f"Sheet1!${name_col}$2:${name_col}${n+1}", series["values"])
            if chart_type == "line":
                _c(ser, "smooth", val="0")

    # --- axis ids on plot element (pie has none) ---
    if needs_value_axis:
        _c(plot, "axId", val=cat_ax_id)
        _c(plot, "axId", val=val_ax_id)

    # --- axes (skip for pie) ---
    if needs_value_axis:
        cat_ax = _c(plot_area, "catAx")
        _c(cat_ax, "axId", val=cat_ax_id)
        sc = _c(cat_ax, "scaling"); _c(sc, "orientation", val="minMax")
        _c(cat_ax, "delete", val="0"); _c(cat_ax, "axPos", val="b")
        _c(cat_ax, "crossAx", val=val_ax_id)
        val_ax = _c(plot_area, "valAx")
        if style.get("gridlines") == "major":
            _c(val_ax, "majorGridlines")
        _c(val_ax, "axId", val=val_ax_id)
        sc2 = _c(val_ax, "scaling"); _c(sc2, "orientation", val="minMax")
        _c(val_ax, "delete", val="0"); _c(val_ax, "axPos", val="l")
        _c(val_ax, "crossAx", val=cat_ax_id)

    # --- legend, plotVisOnly, externalData ---
    
    # DSL `legend` (t/b/l/r/none) overrides the style's legendPos; classic charts
    # support all four positions (chartEx only verified for t/none).
    legend_pos = legend or style.get("legendPos", "b")
    if legend_pos != "none":
        legend = _c(chart, "legend")
        _c(legend, "legendPos", val=legend_pos)
        _c(legend, "overlay", val="0")
    _c(chart, "plotVisOnly", val="1")
    ext_data = _c(root, "externalData")
    ext_data.set(qn("r", "id"), workbook_rid)
    _c(ext_data, "autoUpdate", val="0")

    return to_xml_string(root)

def emit_chart(shape_data, slide_state, relationships, content_types):
    """Emit a p:graphicFrame referencing a (hardcoded) chart part."""

    categories = shape_data["categories"]
    series_list = shape_data["series"]  # [{"name": str, "values": [num], "tone": str|None}, ...]
    chart_type = shape_data.get("chart_type", "column")
    style = shape_data.get("style", {})
    finish = shape_data.get("finish")
    stacked = shape_data.get("stacked", "false")
    legend = shape_data.get("legend")
    chart_part_path = slide_state.next_chart_path()
    chart_index = chart_part_path.rsplit("chart", 1)[-1].split(".")[0]
    workbook_path = f"xl/embeddings/Microsoft_Excel_Worksheet{chart_index}.xlsx"

    slide_state.chart_parts[workbook_path] = build_chart_workbook_bytes(categories, series_list, chart_type)
    content_types.add_override(workbook_path, ContentTypeRegistry.SPREADSHEET)
    
    workbook_rid = relationships.add(
        chart_part_path,
        relationship_target(chart_part_path, workbook_path),
        RelationshipRegistry.PACKAGE,
    )

    slide_state.chart_parts[chart_part_path] = build_chart_part_xml(workbook_rid=workbook_rid,
                                                                     categories=categories,
                                                                       series_list=series_list,
                                                                         chart_type=chart_type,
                                                                           style=style,
                                                                             finish=finish,
                                                                               stacked=stacked,
                                                                               legend=legend)
    content_types.add_override(chart_part_path, ContentTypeRegistry.CHART)

    rid = relationships.add(
        slide_state.part_path,
        relationship_target(slide_state.part_path, chart_part_path),
        RelationshipRegistry.CHART,
    )

    x = int(shape_data.get("x", 914400))
    y = int(shape_data.get("y", 914400))
    cx = int(shape_data.get("w", 6858000))
    cy = int(shape_data.get("h", 4572000))

    gf = etree.Element(qn("p", "graphicFrame"))
    nv = etree.SubElement(gf, qn("p", "nvGraphicFramePr"))
    cnv = etree.SubElement(nv, qn("p", "cNvPr"))
    cnv.set("id", str(slide_state.next_id()))
    cnv.set("name", chart_part_path.rsplit("/", 1)[-1])
    etree.SubElement(nv, qn("p", "cNvGraphicFramePr"))
    etree.SubElement(nv, qn("p", "nvPr"))

    xfrm = etree.SubElement(gf, qn("p", "xfrm"))
    off = etree.SubElement(xfrm, qn("a", "off")); off.set("x", str(x)); off.set("y", str(y))
    ext = etree.SubElement(xfrm, qn("a", "ext")); ext.set("cx", str(cx)); ext.set("cy", str(cy))

    graphic = etree.SubElement(gf, qn("a", "graphic"))
    gdata = etree.SubElement(graphic, qn("a", "graphicData"))
    gdata.set("uri", CHART_NS)
    chart_ref = etree.SubElement(gdata, cqn("chart"))
    chart_ref.set(qn("r", "id"), rid)
    return gf


if __name__ == "__main__":
    print(build_chart_part_xml(
        "rId1",
        ["EMEA", "APAC", "Americas"],
        [{"name": "2025", "values": [42, 31, 58], "tone": "accent1"}],
        "column",
    ))