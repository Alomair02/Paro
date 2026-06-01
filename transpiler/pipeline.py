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
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from transpiler.ast import DeckAst
from transpiler.parser import DSLParser
from transpiler.registries import LayoutRegistry, ShapeLibrary, ThemeRegistry
from transpiler.resolver import LayoutResolver, ResolvedDeck
from transpiler.validator import ValidationIssue, Validator


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
) -> Path:
    """Transpile an XML DSL file and return the generated PPTX path."""
    return transpile_deck(dsl_xml_path, output_path, auto_shrink_text=auto_shrink_text).pptx_path


def transpile_deck(
    dsl_xml_path: str | Path,
    output_path: str | Path | None = None,
    *,
    auto_shrink_text: bool = False,
) -> TranspileResult:
    """Run parse -> resolve -> validate -> engine -> zip."""
    dsl_xml_path = Path(dsl_xml_path)
    ast = DSLParser().parse_file(str(dsl_xml_path))
    output = Path(output_path) if output_path else dsl_xml_path.with_suffix(".pptx")

    theme_registry = ThemeRegistry(_inline_theme_map(ast))
    layout_registry = LayoutRegistry()
    shape_library = ShapeLibrary()

    resolver = LayoutResolver(theme_registry, layout_registry, shape_library)
    resolved = resolver.resolve(ast)
    validator = Validator(layout_registry, auto_shrink_text=auto_shrink_text)
    issues = validator.validate(resolved)
    validator.raise_for_errors(issues)

    graph = _build_package(resolved, output)
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
            colors[slot] = attrs[slot].lstrip("#").upper()
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


def _build_package(resolved: ResolvedDeck, output_path: Path) -> dict[str, Any]:
    content_types = ContentTypeRegistry()
    relationships = RelationshipRegistry()
    parts: dict[str, str | bytes] = {}
    media_parts: dict[str, bytes] = {}

    theme_path = package_path("theme", 1)
    parts[theme_path] = ThemeBuilder(content_types, relationships).build(
        resolved.theme,
        part_path=theme_path,
    )

    layout_builder = LayoutBuilder(content_types, relationships)
    for layout_name, layout_def in LAYOUT_DEFINITIONS.items():
        parts[layout_def["part_path"]] = layout_builder.build(layout_name)

    master_path = package_path("slideMaster", 1)
    layout_records = LayoutBuilder.default_layout_records()
    parts[master_path] = MasterBuilder(content_types, relationships).build(
        layout_records,
        theme_part_path=theme_path,
        part_path=master_path,
    )

    slide_builder = SlideBuilder(content_types, relationships, media_parts)
    slide_paths = []
    for slide in resolved.slide_data:
        slide_path = package_path("slide", slide["index"])
        parts[slide_path] = slide_builder.build(slide, part_path=slide_path)
        slide_paths.append(slide_path)

    presentation_path = package_path("presentation")
    parts[presentation_path] = PresentationBuilder(content_types, relationships).build(
        slide_paths,
        master_part_path=master_path,
        part_path=presentation_path,
    )

    parts.update(media_parts)
    output_path = ZIPAssembler(content_types, relationships).assemble(output_path, parts)
    return {
        "output_path": output_path,
        "parts": parts,
        "content_types": content_types,
        "relationships": relationships,
        "slide_paths": slide_paths,
        "layout_records": layout_records,
    }
