"""End-to-end deck orchestration helpers."""

from copy import deepcopy
from pathlib import Path

from builders.common import REFERENCE, package_path
from builders.layout_builder import LAYOUT_DEFINITIONS, LayoutBuilder
from builders.master_builder import MasterBuilder
from builders.presentation_builder import PresentationBuilder
from builders.slide_builder import SlideBuilder
from builders.theme_builder import ThemeBuilder
from builders.zip_assembler import ZIPAssembler
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry


SAMPLE_THEME = deepcopy(REFERENCE["default_theme"])

# Media extensions a transplanted template may carry.
MEDIA_MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "svg": "image/svg+xml",
    "emf": "image/x-emf",
    "wmf": "image/x-wmf",
}


def _register_transplant_part(part_path: str, content_types: ContentTypeRegistry):
    if part_path.endswith(".rels"):
        return  # covered by the package-wide rels default
    if "/slideLayouts/" in part_path and part_path.endswith(".xml"):
        content_types.add_override(part_path, ContentTypeRegistry.SLIDE_LAYOUT)
    elif "/slideMasters/" in part_path and part_path.endswith(".xml"):
        content_types.add_override(part_path, ContentTypeRegistry.SLIDE_MASTER)
    elif "/theme/" in part_path and part_path.endswith(".xml"):
        content_types.add_override(part_path, ContentTypeRegistry.THEME)
    else:
        extension = part_path.rsplit(".", 1)[-1].lower()
        if extension in MEDIA_MIME_TYPES:
            content_types.add_default(extension, MEDIA_MIME_TYPES[extension])


def assemble_package(
    theme: dict,
    slide_data: list[dict],
    output_path,
    transplant: dict | None = None,
) -> dict:
    """Shared package-building sequence: theme -> layouts -> master ->
    slides -> presentation -> assemble. The single place part-wiring lives.

    transplant: an ingestion.layout_extractor transplant — the template's
    theme/master/layouts/media are carried verbatim under their original
    part paths (so their internal rels stay valid) instead of generating
    Paro's own. Slides then reference the template's layouts directly via
    slide_data["layout_part_path"]."""
    content_types = ContentTypeRegistry()
    relationships = RelationshipRegistry()
    parts: dict[str, str | bytes] = {}
    media_parts: dict[str, bytes] = {}
    media_sources: dict[str, str] = {}
    chart_parts: dict[str, str | bytes] = {}

    if transplant:
        master_path = transplant["master_part"]
        layout_records = None
        for part_path, payload in transplant["parts"].items():
            parts[part_path] = payload
            _register_transplant_part(part_path, content_types)
    else:
        theme_path = package_path("theme", 1)
        parts[theme_path] = ThemeBuilder(content_types, relationships).build(
            theme, part_path=theme_path
        )

        layout_builder = LayoutBuilder(content_types, relationships)
        for layout_name, layout_def in LAYOUT_DEFINITIONS.items():
            parts[layout_def["part_path"]] = layout_builder.build(layout_name)

        master_path = package_path("slideMaster", 1)
        layout_records = LayoutBuilder.default_layout_records()
        parts[master_path] = MasterBuilder(content_types, relationships).build(
            layout_records, theme_part_path=theme_path, part_path=master_path
        )

    slide_builder = SlideBuilder(
        content_types, relationships, media_parts, media_sources, chart_parts
    )
    slide_paths = []
    for slide in slide_data:
        slide_path = package_path("slide", slide["index"])
        parts[slide_path] = slide_builder.build(slide, part_path=slide_path)
        slide_paths.append(slide_path)

    presentation_path = package_path("presentation")
    parts[presentation_path] = PresentationBuilder(content_types, relationships).build(
        slide_paths, master_part_path=master_path, part_path=presentation_path
    )

    parts.update(media_parts)
    parts.update(chart_parts)
    output_path = ZIPAssembler(content_types, relationships).assemble(output_path, parts)
    return {
        "output_path": output_path,
        "parts": parts,
        "content_types": content_types,
        "relationships": relationships,
        "slide_paths": slide_paths,
        "layout_records": layout_records,
    }

def build_deck(output_path: str | Path = "tests/fixtures/sample_deck.pptx") -> dict:
    """Build a complete two-slide sample deck and write it to output_path."""
    return assemble_package(SAMPLE_THEME, _sample_slides(), output_path)

def _sample_slides() -> list[dict]:
    return [
        {
            "index": 1,
            "layout": "title",
            "name": "Title",
            "shapes": [
                {
                    "type": "placeholder_text",
                    "idx": 0,
                    "placeholder_type": "ctrTitle",
                    "name": "Title Placeholder",
                    "text": "Quarterly Update",
                },
                {
                    "type": "placeholder_text",
                    "idx": 1,
                    "placeholder_type": "subTitle",
                    "name": "Subtitle Placeholder",
                    "text": "Generated by Paro",
                },
            ],
        },
        {
            "index": 2,
            "layout": "titleBody",
            "name": "Content",
            "shapes": [
                {
                    "type": "placeholder_text",
                    "idx": 0,
                    "placeholder_type": "title",
                    "name": "Content Title Placeholder",
                    "text": "Slide Layer",
                },
                {
                    "type": "text_box",
                    "name": "Body Text Box",
                    "x": "1.1in",
                    "y": "2.05in",
                    "w": "5.15in",
                    "h": "1.05in",
                    "text": "A freeform text box emitted directly on the slide.",
                },
                {
                    "type": "autoshape",
                    "name": "Accent Rectangle",
                    "x": "7.1in",
                    "y": "2.1in",
                    "w": "3.4in",
                    "h": "1.2in",
                    "fill": "accent1",
                    "line": False,
                },
            ],
        },
    ]
