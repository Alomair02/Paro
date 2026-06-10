"""End-to-end DSL transpilation into a PPTX package."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from builders.common import REFERENCE, package_path
from builders.layout_builder import LAYOUT_DEFINITIONS, LayoutBuilder
from builders.master_builder import MasterBuilder
from builders.presentation_builder import PresentationBuilder
from builders.slide_builder import SlideBuilder
from builders.theme_builder import ThemeBuilder
from builders.zip_assembler import ZIPAssembler
from builders.deck_builder import assemble_package
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from transpiler.ast import DeckAst
from transpiler.parser import DSLParser, DSLParseError
from transpiler.registries import LayoutRegistry, ShapeLibrary, ThemeRegistry
from transpiler.resolver import LayoutResolver, ResolvedDeck
from transpiler.validator import ValidationIssue, Validator
import re
_HEX_RE = re.compile(r'^[0-9A-Fa-f]{6}$')

@dataclass
class TranspileResult:
    """Result of one end-to-end transpilation."""

    pptx_path: Path
    resolved_deck: ResolvedDeck
    validation_issues: list[ValidationIssue]
    parts: dict[str, str | bytes]


def transpile(
    dsl_xml_path: str | Path,
    output_path: str | Path | None = None,
    *,
    auto_shrink_text: bool = False,
    themes: dict[str, dict] | None = None,
) -> Path:
    """Transpile an XML DSL file and return the generated PPTX path."""
    return transpile_deck(
        dsl_xml_path, output_path, auto_shrink_text=auto_shrink_text, themes=themes
    ).pptx_path


def transpile_deck(
    dsl_xml_path: str | Path,
    output_path: str | Path | None = None,
    *,
    auto_shrink_text: bool = False,
    themes: dict[str, dict] | None = None,
    layout_transplant: dict | None = None,
) -> TranspileResult:
    """Run parse -> resolve -> validate -> engine -> zip.

    themes: extra registry themes (e.g. an ingested template bundle via
    ingestion.bundle_to_registry_themes). An inline <theme> with the same
    name wins — an author's explicit override outranks ingestion.

    layout_transplant: an ingestion.layout_extractor transplant — the
    template's master/layouts/theme travel verbatim into the package, DSL
    layout names resolve to the template's designed layouts, and
    placeholders take the template's real geometry.
    """
    dsl_xml_path = Path(dsl_xml_path)
    ast = DSLParser().parse_file(str(dsl_xml_path))
    output = Path(output_path) if output_path else dsl_xml_path.with_suffix(".pptx")

    theme_registry = ThemeRegistry({**(themes or {}), **_inline_theme_map(ast)})
    if layout_transplant:
        from ingestion.layout_extractor import transplant_to_registry_layouts

        layout_registry = LayoutRegistry(transplant_to_registry_layouts(layout_transplant))
    else:
        layout_registry = LayoutRegistry()
    shape_library = ShapeLibrary()

    resolver = LayoutResolver(theme_registry, layout_registry, shape_library)
    resolved = resolver.resolve(ast)
    validator = Validator(layout_registry, auto_shrink_text=auto_shrink_text)
    issues = validator.validate(resolved)
    validator.raise_for_errors(issues)

    if layout_transplant:
        name_map = layout_transplant["name_map"]
        fallback = name_map.get("blank") or layout_transplant["layouts"][0]["part_path"]
        for slide in resolved.slide_data:
            slide["layout_part_path"] = name_map.get(slide["layout"], fallback)

    graph = _build_package(resolved, output, layout_transplant)
    return TranspileResult(
        pptx_path=graph["output_path"],
        resolved_deck=resolved,
        validation_issues=issues,
        parts=graph["parts"],
    )


def _inline_theme_map(ast: DeckAst) -> dict[str, dict[str, Any]]:
    if ast.inline_theme is None:
        return {}

    base = ThemeRegistry().get("default")
    colors = dict(base["colors"])
    fonts = dict(base["fonts"])
    type_scale = dict(base["typeScale"])
    attrs = ast.inline_theme.attrs
    for slot in REFERENCE["color_scheme_slots"]["order"]:
        if slot in attrs:
            raw = attrs[slot].lstrip("#").upper()
            if not _HEX_RE.match(raw):
                raise DSLParseError(
                    f"theme {slot}='{attrs[slot]}' is not a 6-digit hex color "
                    f"(e.g. '2563EB' or '#2563EB')"
                )
            colors[slot] = raw
    if "heading" in attrs:
        fonts["heading"] = attrs["heading"]
    if "body" in attrs:
        fonts["body"] = attrs["body"]

    return {
        ast.inline_theme.name: {
            "name": ast.inline_theme.name,
            "colors": colors,
            "fonts": fonts,
            "typeScale": type_scale,
        }
    }


def _build_package(
    resolved: ResolvedDeck,
    output_path: Path,
    transplant: dict | None = None,
) -> dict[str, Any]:
    return assemble_package(
        theme=resolved.theme,
        slide_data=resolved.slide_data,
        output_path=output_path,
        transplant=transplant,
    )