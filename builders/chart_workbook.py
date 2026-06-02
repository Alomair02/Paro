#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: chart_workbook.py
Description: Builds the embedded .xlsx workbook that backs a chart, so the
chart is editable in PowerPoint. The workbook values MUST match the chart's
cached values (the cache-equals-workbook invariant).
"""

import io

from openpyxl import Workbook


def build_chart_workbook_bytes(categories, series_list, chart_type="column") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    if chart_type == "scatter":
        # Per series: two columns (x, y). Series 0 -> A,B ; series 1 -> C,D ; ...
        for s_idx, series in enumerate(series_list):
            x_col = chr(ord("A") + s_idx * 2)
            y_col = chr(ord("A") + s_idx * 2 + 1)
            ws[f"{x_col}1"] = f"{series['name']} X"
            ws[f"{y_col}1"] = series["name"]
            for r_idx, (xv, yv) in enumerate(series["xy"], start=2):
                ws[f"{x_col}{r_idx}"] = xv
                ws[f"{y_col}{r_idx}"] = yv
    else:
        for i, cat in enumerate(categories, start=2):
            ws[f"A{i}"] = cat
        for s_idx, series in enumerate(series_list):
            col = chr(ord("B") + s_idx)
            ws[f"{col}1"] = series["name"]
            for r_idx, val in enumerate(series["values"], start=2):
                ws[f"{col}{r_idx}"] = val

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()