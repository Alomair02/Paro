#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: content_type_reg.py
Author: Abdulaziz Alomair
Date: 2026-06-01 (YYYY-MM-DD)
Version: 1.0
Description: A manifest of content types. This is a dictionary keyed by part path. Each entry is the content type string for that part. When you add a part, you call add() and get back the content type string to write into your [Content_Types].xml file.
"""


class ContentTypeRegistry:

    # Content type strings - exact, case-sensitive
    PRESENTATION  = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
    SLIDE         = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
    SLIDE_LAYOUT  = "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
    SLIDE_MASTER  = "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"
    THEME         = "application/vnd.openxmlformats-officedocument.theme+xml"
    PRES_PROPS    = "application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"
    VIEW_PROPS    = "application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"
    TABLE_STYLES  = "application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"
    CORE_PROPS    = "application/vnd.openxmlformats-package.core-properties+xml"
    APP_PROPS     = "application/vnd.openxmlformats-officedocument.extended-properties+xml"
    CHART         = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
    SPREADSHEET   = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(self):
        # Defaults cover all files of a given extension, e.g. "xml" → "application/xml"
        # Pre-populated with extensions that are always present
        self._defaults = {
            "rels": "application/vnd.openxmlformats-package.relationships+xml",
            "xml":  "application/xml",
        }

        # Overrides cover a specific part by its full package path.
        # Ordered dict so render output is deterministic.
        self.overrides = {}

    @staticmethod
    def _normalize_path(path):
        """
        Normalize the part path to ensure consistent registry keys.
        """
        return path.replace("\\", "/").lstrip("/")

    def add_default(self, extension: str, mime_type: str):
        """
        Add a default content type for a given file extension.
        """
        extension = extension.lstrip(".")
        self._defaults[extension] = mime_type

    def add_override(self, part_path: str, content_type: str):
        """
        Add an override content type for a specific part path.
        """
        normalized_path = self._normalize_path(part_path)
        self.overrides[normalized_path] = content_type

    def render(self) -> str:
        """
        Render the [Content_Types].xml content as a string.
        """
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        ]

        for ext, mime in self._defaults.items():
            lines.append(f'    <Default Extension="{ext}" ContentType="{mime}"/>')

        for part_path, content_type in self.overrides.items():
            lines.append(f'    <Override PartName="/{part_path}" ContentType="{content_type}"/>')

        lines.append('</Types>')
        return "\n".join(lines)
    
if __name__ == "__main__":
    # Example usage
    registry = ContentTypeRegistry()
    registry.add_default("jpg", "image/jpeg")
    registry.add_override("ppt/slides/slide1.xml", ContentTypeRegistry.SLIDE)
    print(registry.render())
