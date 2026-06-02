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


def build_chart_workbook_bytes(categories: list, series_list: list) -> bytes:
    """
    Build a minimal .xlsx matching the chart's data layout:
        A1 (blank)      B1 = series_name
        A2..An = cats   B2..Bn = values
    Returns the .xlsx file as bytes.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    for i, cat in enumerate(categories, start=2):
        ws[f"A{i}"] = cat

    for s_idx, series in enumerate(series_list):
        col = chr(ord("B") + s_idx)  # B, C, D...
        ws[f"{col}1"] = series["name"]
        for i, val in enumerate(series["values"], start=2):
            ws[f"{col}{i}"] = val

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()