"""Font-backed text measurement for resolved DSL text blocks."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from builders.common import REFERENCE


EMU_PER_PIXEL = REFERENCE["units"]["emu_per"]["pixel_96dpi"]
POINTS_TO_PIXELS = 96 / 72

FONT_DIRS = (
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".local/share/fonts",
)

FAMILY_ALIASES = {
    "aptos": "Liberation Sans",
    "aptosdisplay": "Liberation Sans",
    "arial": "Liberation Sans",
    "calibri": "Liberation Sans",
    "helvetica": "Liberation Sans",
}

_WEIGHT_TOKENS = {
    "thin", "extralight", "ultralight", "light", "regular", "normal",
    "medium", "semibold", "demibold", "bold", "extrabold", "ultrabold", "black", "heavy",
}
_STYLE_TOKENS = {"italic", "oblique"}
_DEFAULT_WEIGHT = "regular"

@dataclass(frozen=True)
class TextMeasurement:
    """Rendered dimensions for text wrapped to a box width."""

    rendered_width_emu: int
    wrapped_lines: int
    rendered_height_emu: int
    font_family: str
    font_family_used: str
    font_path: str | None
    approximation_used: bool


class TextMeasurer:
    """Measure text using Pillow FreeType metrics with documented fallback."""

    fallback_family = "Liberation Sans"

    def measure(
        self,
        text: str,
        font_family: str,
        size_pt: float,
        box_width_emu: int,
        *,
        bold: bool = False,
        italic: bool = False,
        line_spacing: float = 1.0,
    ) -> TextMeasurement:
        resolved = resolve_font(font_family, bold=bold, italic=italic)
        font = self._load_font(resolved.path, size_pt)
        box_width_px = max(0, box_width_emu / EMU_PER_PIXEL)
        lines = self._wrap_lines(text, font, box_width_px)
        widths = [self._text_width_px(line, font) for line in lines]
        line_height = self._line_height_px(font)

        return TextMeasurement(
            rendered_width_emu=round((max(widths) if widths else 0) * EMU_PER_PIXEL),
            wrapped_lines=max(1, len(lines)),
            rendered_height_emu=round(max(1, len(lines)) * line_height * line_spacing * EMU_PER_PIXEL),
            font_family=font_family,
            font_family_used=resolved.family,
            font_path=str(resolved.path) if resolved.path else None,
            approximation_used=resolved.approximation_used,
        )

    def _load_font(self, path: Path | None, size_pt: float):
        size_px = max(1, round(float(size_pt) * POINTS_TO_PIXELS))
        if path:
            return ImageFont.truetype(str(path), size_px)
        try:
            return ImageFont.load_default(size_px)
        except TypeError:
            return ImageFont.load_default()

    def _wrap_lines(self, text: str, font, box_width_px: float) -> list[str]:
        if text == "":
            return [""]
        wrapped: list[str] = []
        for source_line in str(text).splitlines() or [""]:
            words = source_line.split()
            if not words:
                wrapped.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if box_width_px <= 0 or self._text_width_px(candidate, font) <= box_width_px:
                    current = candidate
                else:
                    wrapped.append(current)
                    current = word
            wrapped.append(current)
        return wrapped

    def _text_width_px(self, text: str, font) -> float:
        if hasattr(font, "getlength"):
            return float(font.getlength(text))
        bbox = font.getbbox(text)
        return float(bbox[2] - bbox[0])

    def _line_height_px(self, font) -> int:
        if hasattr(font, "getmetrics"):
            ascent, descent = font.getmetrics()
            return ascent + descent
        bbox = font.getbbox("Ag")
        return bbox[3] - bbox[1]


@dataclass(frozen=True)
class ResolvedFont:
    family: str
    path: Path | None
    approximation_used: bool


def resolve_font(font_family: str, *, bold: bool = False, italic: bool = False) -> ResolvedFont:
    """Resolve a requested family to an installed font, falling back predictably."""
    requested = font_family or TextMeasurer.fallback_family
    normalized_requested = _normalize(requested)
    lookup_names = [requested]
    alias = FAMILY_ALIASES.get(normalized_requested)
    if alias:
        lookup_names.append(alias)
    lookup_names.append(TextMeasurer.fallback_family)

    for family in lookup_names:
        path = _find_font_path(family, bold=bold, italic=italic)
        if path:
            return ResolvedFont(
                family=family,
                path=path,
                approximation_used=_normalize(family) != normalized_requested,
            )

    return ResolvedFont(
        family="Pillow default",
        path=None,
        approximation_used=True,
    )

def _decompose_stem(stem: str) -> tuple[str, str, bool]:
    """Split a font file stem into (normalized_family, weight, italic).

    'Aptos'                 -> ('aptos',        'regular', False)
    'Aptos-Black'           -> ('aptos',        'black',   False)
    'Aptos-Bold-Italic'     -> ('aptos',        'bold',    True)
    'Aptos-Display'         -> ('aptosdisplay', 'regular', False)
    'Aptos-Display-Bold'    -> ('aptosdisplay', 'bold',    False)
    'Aptos-Serif-Italic'    -> ('aptosserif',   'regular', True)
    """
    parts = stem.replace("_", "-").replace(" ", "-").split("-")
    family_parts: list[str] = []
    weight = _DEFAULT_WEIGHT
    italic = False
    for part in parts:
        low = part.lower()
        if low in _STYLE_TOKENS:
            italic = True
        elif low in _WEIGHT_TOKENS:
            weight = low
        else:
            family_parts.append(part)
    return _normalize("".join(family_parts)), weight, italic

def _find_font_path(font_family: str, *, bold: bool, italic: bool) -> Path | None:
    requested_family = _normalize(font_family)
    requested_weight = "bold" if bold else _DEFAULT_WEIGHT

    matches = []
    for path in _font_catalog():
        fam, weight, is_italic = _decompose_stem(path.stem)
        if fam == requested_family and weight == requested_weight and is_italic == italic:
            matches.append(path)

    if not matches:
        return None
    # After exact family+weight+italic matching there should be exactly one match;
    # sort is a deterministic tiebreak only (defensive against duplicate installs).
    return sorted(matches, key=lambda p: str(p))[0]


@lru_cache(maxsize=1)
def _font_catalog() -> tuple[Path, ...]:
    paths: list[Path] = []
    for font_dir in FONT_DIRS:
        if not font_dir.exists():
            continue
        for suffix in ("*.ttf", "*.otf"):
            paths.extend(font_dir.rglob(suffix))
    return tuple(sorted(paths, key=lambda path: str(path)))


def _normalize(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())
