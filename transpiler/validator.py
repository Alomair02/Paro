"""Validation over resolved DSL layout."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from transpiler.ast import Box
from transpiler.registries import LayoutRegistry
from transpiler.resolver import ResolvedDeck
from transpiler.text_metrics import TextMeasurer
from utils.converter import UnitConverter


@dataclass(frozen=True)
class ValidationIssue:
    """One validation diagnostic."""

    severity: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class TranspileValidationError(ValueError):
    """Raised when resolved layout has blocking validation errors."""

    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("\n".join(issue.message for issue in issues))


class Validator:
    """Apply structural errors and heuristic warnings from SCHEMA_SPEC.md."""

    FONT_DRIFT_THRESHOLD_PT = 4.0

    def __init__(
        self,
        layout_registry: LayoutRegistry | None = None,
        *,
        measure_text: bool = True,
        auto_shrink_text: bool = False,
        measurer: TextMeasurer | None = None,
        shrink_step_pt: float = 0.5,
    ):
        self.layout_registry = layout_registry or LayoutRegistry()
        self.measure_text = measure_text
        self.auto_shrink_text = auto_shrink_text
        self.measurer = measurer or TextMeasurer()
        self.shrink_step_pt = shrink_step_pt

    def validate(self, deck: ResolvedDeck) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        slide_bounds = Box(0, 0, deck.slide_size["cx"], deck.slide_size["cy"])

        for slide in deck.slides:
            for block in slide.blocks:
                if not self._inside(block.box, slide_bounds):
                    issues.append(
                        ValidationIssue(
                            "error",
                            "bounds",
                            f"{block.kind} extends past slide bounds: {block.box}",
                        )
                    )

            for placement in slide.grid_placements:
                if (
                    placement["col"] < 1
                    or placement["row"] < 1
                    or placement["col"] + placement["colspan"] - 1 > placement["cols"]
                    or placement["row"] + placement["rowspan"] - 1 > placement["rows"]
                ):
                    issues.append(
                        ValidationIssue(
                            "error",
                            "grid_bounds",
                            f"Grid child {placement['kind']} is outside declared grid",
                        )
                    )

            for ref in slide.placeholder_refs:
                layout_name = slide.slide_data["layout"]
                if not self._placeholder_exists(layout_name, ref["placeholder"], ref.get("idx")):
                    issues.append(
                        ValidationIssue(
                            "error",
                            "placeholder",
                            f"Layout '{layout_name}' does not define placeholder '{ref['placeholder']}'",
                        )
                    )

            for block in slide.blocks:
                if block.kind == "image":
                    self._validate_image_source(block, issues)

            free_blocks = [block for block in slide.blocks if block.parent_kind == "free"]
            for i, left in enumerate(free_blocks):
                for right in free_blocks[i + 1 :]:
                    if self._overlaps(left.box, right.box):
                        issues.append(
                            ValidationIssue(
                                "warning",
                                "free_overlap",
                                f"Free-positioned {left.kind} overlaps {right.kind}",
                            )
                        )

            for group in slide.sibling_font_groups:
                sizes = [entry["size_pt"] for entry in group]
                if sizes and max(sizes) - min(sizes) > self.FONT_DRIFT_THRESHOLD_PT:
                    issues.append(
                        ValidationIssue(
                            "warning",
                            "font_drift",
                            "Sibling text blocks differ in font size beyond threshold",
                        )
                    )

            if self.measure_text:
                for block in slide.blocks:
                    self._validate_text_fit(deck, slide.slide_data["index"], block, issues)

        return issues

    def raise_for_errors(self, issues: list[ValidationIssue]):
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            raise TranspileValidationError(errors)

    def _placeholder_exists(self, layout_name: str, placeholder: str, idx: str | None) -> bool:
        layout = self.layout_registry.get(layout_name)
        normalized = self._normalize_placeholder(placeholder)
        for ph in layout["placeholders"]:
            type_matches = ph["type"] == normalized or (normalized == "title" and ph["type"] == "ctrTitle")
            idx_matches = idx is None or str(ph["idx"]) == str(idx)
            if type_matches and idx_matches:
                return True
        return False

    def _normalize_placeholder(self, placeholder: str) -> str:
        aliases = {"subtitle": "subTitle", "ctrtitle": "ctrTitle"}
        return aliases.get(placeholder, aliases.get(placeholder.lower(), placeholder))

    def _inside(self, box: Box, bounds: Box) -> bool:
        return box.x >= bounds.x and box.y >= bounds.y and box.right <= bounds.right and box.bottom <= bounds.bottom

    def _validate_image_source(self, block, issues: list[ValidationIssue]):
        src = (block.content or {}).get("src") or block.attrs.get("src")
        if not src:
            return
        if not Path(src).exists():
            issues.append(
                ValidationIssue(
                    "error",
                    "missing_image",
                    f"Image source does not exist: {src}",
                    {"src": src},
                )
            )

    def _overlaps(self, left: Box, right: Box) -> bool:
        return not (
            left.right <= right.x
            or right.right <= left.x
            or left.bottom <= right.y
            or right.bottom <= left.y
        )

    def _validate_text_fit(
        self,
        deck: ResolvedDeck,
        slide_index: int,
        block,
        issues: list[ValidationIssue],
    ):
        if not self._is_text_block(block):
            return

        initial = self._measure_block(deck, block)
        if initial is None or self._fits(initial):
            return

        final = initial
        shrink = {"applied": False, "floored": False}
        if self.auto_shrink_text:
            shrink = self._auto_shrink(deck, block)
            final = self._measure_block(deck, block) or initial

        details = {
            "slide_index": slide_index,
            "block_kind": block.kind,
            "parent_kind": block.parent_kind,
            "shape_name": (block.content or {}).get("name"),
            "text": initial["text_preview"],
            "role": initial["role"],
            "font_size_pt": initial["font_size_pt"],
            "box": {
                "x": block.box.x,
                "y": block.box.y,
                "w": block.box.w,
                "h": block.box.h,
            },
            "measured_width_emu": initial["measured_width_emu"],
            "measured_height_emu": initial["measured_height_emu"],
            "overflow_w_emu": initial["overflow_w_emu"],
            "overflow_h_emu": initial["overflow_h_emu"],
            "wrapped_lines": initial["wrapped_lines"],
            "approximation_used": initial["approximation_used"],
            "font_family": initial["font_family"],
            "font_family_used": initial["font_family_used"],
            "shrink_applied": shrink["applied"],
            "shrink_floored": shrink["floored"],
            "final_font_size_pt": final["font_size_pt"],
            "final_overflow_w_emu": final["overflow_w_emu"],
            "final_overflow_h_emu": final["overflow_h_emu"],
        }
        message = (
            f"Text overflow on slide {slide_index}"
            f" ({details['shape_name'] or block.kind}): "
            f"width +{initial['overflow_w_emu']} EMU, "
            f"height +{initial['overflow_h_emu']} EMU at {initial['font_size_pt']:.2f}pt"
        )
        issues.append(ValidationIssue("warning", "text_overflow", message, details))

    def _is_text_block(self, block) -> bool:
        content = block.content
        if not isinstance(content, dict):
            return False
        return "paragraphs" in content or "text" in content

    def _measure_block(self, deck: ResolvedDeck, block) -> dict[str, Any] | None:
        paragraphs = self._paragraphs_from_content(block.content, ensure=False)
        if not paragraphs:
            return None

        total_height = 0
        max_width = 0
        max_width_overflow = 0
        wrapped_lines = 0
        approximation_used = False
        font_families = []
        font_families_used = []
        max_size = 0.0
        roles = []
        preview_parts = []

        for paragraph in paragraphs:
            text = self._paragraph_text(paragraph)
            role = paragraph.get("role") or (block.content or {}).get("role") or block.attrs.get("role") or "body"
            role_bundle = self._role_bundle(deck, role)
            size_pt = self._paragraph_size_points(paragraph, block, role_bundle)
            font_family = self._paragraph_font_family(deck, paragraph, role)
            bold = self._paragraph_bold(paragraph, role_bundle)
            line_spacing = self._line_spacing_multiplier(
                paragraph.get("lineSpacing", role_bundle.get("lineSpacing", 1.0)),
                size_pt,
            )
            available_width = self._available_text_width(block.box.w, paragraph)
            measurement = self.measurer.measure(
                text,
                font_family,
                size_pt,
                available_width,
                bold=bold,
                line_spacing=line_spacing,
            )
            max_width = max(max_width, measurement.rendered_width_emu)
            max_width_overflow = max(
                max_width_overflow,
                measurement.rendered_width_emu - available_width,
            )
            total_height += measurement.rendered_height_emu
            total_height += self._spacing_emu(paragraph.get("spaceBefore"))
            total_height += self._spacing_emu(paragraph.get("spaceAfter"))
            wrapped_lines += measurement.wrapped_lines
            approximation_used = approximation_used or measurement.approximation_used
            font_families.append(measurement.font_family)
            font_families_used.append(measurement.font_family_used)
            max_size = max(max_size, size_pt)
            roles.append(role)
            if text:
                preview_parts.append(text)

        return {
            "measured_width_emu": max_width,
            "measured_height_emu": total_height,
            "overflow_w_emu": max(0, round(max_width_overflow)),
            "overflow_h_emu": max(0, round(total_height - block.box.h)),
            "wrapped_lines": wrapped_lines,
            "approximation_used": approximation_used,
            "font_family": font_families[0] if font_families else "",
            "font_family_used": font_families_used[0] if font_families_used else "",
            "font_size_pt": max_size,
            "role": roles[0] if roles else "body",
            "text_preview": " ".join(preview_parts)[:120],
        }

    def _fits(self, measurement: dict[str, Any]) -> bool:
        return measurement["overflow_w_emu"] <= 0 and measurement["overflow_h_emu"] <= 0

    def _auto_shrink(self, deck: ResolvedDeck, block) -> dict[str, bool]:
        applied = False
        floored = False
        self._paragraphs_from_content(block.content, ensure=True)

        while True:
            current = self._measure_block(deck, block)
            if current is None or self._fits(current):
                return {"applied": applied, "floored": floored}

            changed = False
            for paragraph in self._paragraphs_from_content(block.content, ensure=True):
                role = paragraph.get("role") or (block.content or {}).get("role") or block.attrs.get("role") or "body"
                role_bundle = self._role_bundle(deck, role)
                floor = self._role_min_size_points(role_bundle)
                for run in self._runs_from_paragraph(paragraph, ensure=True):
                    size = self._run_size_points(run, paragraph, block, role_bundle)
                    if size > floor:
                        run["size_pt"] = max(floor, round(size - self.shrink_step_pt, 2))
                        changed = True
                        applied = True

            if not changed:
                floored = not self._fits(current)
                return {"applied": applied, "floored": floored}

    def _paragraphs_from_content(self, content: dict[str, Any] | None, *, ensure: bool) -> list[dict[str, Any]]:
        if not isinstance(content, dict):
            return []
        paragraphs = content.get("paragraphs")
        if paragraphs is not None:
            return [self._normalize_paragraph(paragraph) for paragraph in paragraphs]
        if "text" not in content:
            return []

        paragraph = {
            "text": str(content.get("text", "")),
            "runs": [{"text": str(content.get("text", ""))}],
            "role": content.get("role", "body"),
        }
        if ensure:
            content["paragraphs"] = [paragraph]
        return [paragraph]

    def _normalize_paragraph(self, paragraph) -> dict[str, Any]:
        if isinstance(paragraph, str):
            return {"text": paragraph, "runs": [{"text": paragraph}]}
        return paragraph

    def _runs_from_paragraph(self, paragraph: dict[str, Any], *, ensure: bool) -> list[dict[str, Any]]:
        runs = paragraph.get("runs")
        if runs is not None:
            return [self._normalize_run(run) for run in runs]

        text = str(paragraph.get("text", ""))
        runs = [{"text": text}]
        if ensure:
            paragraph["runs"] = runs
        return runs

    def _normalize_run(self, run) -> dict[str, Any]:
        if isinstance(run, str):
            return {"text": run}
        return run

    def _paragraph_text(self, paragraph: dict[str, Any]) -> str:
        runs = self._runs_from_paragraph(paragraph, ensure=False)
        if runs:
            return "".join(str(run.get("text", "")) for run in runs)
        return str(paragraph.get("text", ""))

    def _paragraph_size_points(
        self,
        paragraph: dict[str, Any],
        block,
        role_bundle: dict[str, Any],
    ) -> float:
        runs = self._runs_from_paragraph(paragraph, ensure=False)
        if runs:
            return max(self._run_size_points(run, paragraph, block, role_bundle) for run in runs)
        return self._fallback_size_points(paragraph, block, role_bundle)

    def _run_size_points(
        self,
        run: dict[str, Any],
        paragraph: dict[str, Any],
        block,
        role_bundle: dict[str, Any],
    ) -> float:
        if run.get("size_pt") is not None:
            return float(run["size_pt"])
        return self._fallback_size_points(paragraph, block, role_bundle)

    def _fallback_size_points(
        self,
        paragraph: dict[str, Any],
        block,
        role_bundle: dict[str, Any],
    ) -> float:
        inherited = self._placeholder_inherited_size_points(block, int(paragraph.get("level", 0)))
        if inherited is not None and "size" not in role_bundle:
            return inherited
        if inherited is not None and not self._content_has_emitted_size(block.content):
            return inherited
        return self._points(role_bundle.get("size", 17))

    def _content_has_emitted_size(self, content: dict[str, Any] | None) -> bool:
        for paragraph in self._paragraphs_from_content(content, ensure=False):
            for run in self._runs_from_paragraph(paragraph, ensure=False):
                if run.get("size_pt") is not None:
                    return True
        return False

    def _placeholder_inherited_size_points(self, block, level: int) -> float | None:
        content = block.content or {}
        placeholder = content.get("placeholder_type") or content.get("ph_type") or block.attrs.get("placeholder")
        if not placeholder:
            return None
        normalized = self._normalize_placeholder(placeholder)
        from builders.common import REFERENCE

        master_styles = REFERENCE["master_text_styles"]
        style = master_styles["placeholder_style"].get(normalized)
        if style == "title":
            return float(master_styles["title"]["size"])
        if style == "other":
            return float(master_styles["other"]["size"])
        if style == "body":
            level_sizes = master_styles["body_level_sizes"]
            return float(level_sizes[min(max(level, 0), len(level_sizes) - 1)])
        return None

    def _paragraph_font_family(self, deck: ResolvedDeck, paragraph: dict[str, Any], role: str) -> str:
        for run in self._runs_from_paragraph(paragraph, ensure=False):
            if run.get("font"):
                return run["font"]
        fonts = deck.theme.get("fonts", {})
        if role in {"title", "heading", "subheading"}:
            return fonts.get("heading", "Liberation Sans")
        return fonts.get("body", "Liberation Sans")

    def _paragraph_bold(self, paragraph: dict[str, Any], role_bundle: dict[str, Any]) -> bool:
        for run in self._runs_from_paragraph(paragraph, ensure=False):
            if run.get("bold"):
                return True
        return role_bundle.get("weight") == "bold"

    def _role_bundle(self, deck: ResolvedDeck, role: str) -> dict[str, Any]:
        return deck.theme.get("typeScale", {}).get(role, deck.theme.get("typeScale", {}).get("body", {}))

    def _role_min_size_points(self, role_bundle: dict[str, Any]) -> float:
        if "minSize" in role_bundle:
            return self._points(role_bundle["minSize"])
        size = self._points(role_bundle.get("size", 17))
        return round(size * 0.88, 2)

    def _available_text_width(self, box_width: int, paragraph: dict[str, Any]) -> int:
        bullet = paragraph.get("bullet")
        if bullet in (None, "none"):
            return box_width
        level = int(paragraph.get("level", 0))
        from builders.common import REFERENCE

        indents = REFERENCE["text_defaults"]["level_indents"]
        mar_l = indents[min(max(level, 0), len(indents) - 1)]["marL"]
        return max(1, box_width - mar_l)

    def _line_spacing_multiplier(self, value: Any, size_pt: float) -> float:
        if value in (None, ""):
            return 1.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if text.endswith("%"):
            return float(text[:-1]) / 100
        try:
            return float(text)
        except ValueError:
            spacing_pt = self._points(text)
            return spacing_pt / size_pt if size_pt else 1.0

    def _spacing_emu(self, value: Any) -> int:
        if value in (None, ""):
            return 0
        if isinstance(value, (int, float)):
            return UnitConverter.to_emu(f"{value}pt")
        text = str(value).strip()
        try:
            float(text)
        except ValueError:
            return UnitConverter.to_emu(text)
        return UnitConverter.to_emu(f"{text}pt")

    def _points(self, value: str | int | float) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        try:
            return float(text)
        except ValueError:
            return UnitConverter.to_emu(text) / UnitConverter.CONVERSION_FACTORS["pt"]
