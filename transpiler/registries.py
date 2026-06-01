"""Thin registry seams for design-system data."""

from __future__ import annotations

from copy import deepcopy

from builders.common import REFERENCE
from builders.layout_builder import LAYOUT_DEFINITIONS


class ThemeRegistry:
    """Resolve theme names through a small, replaceable registry seam."""

    def __init__(self, themes: dict[str, dict] | None = None):
        base = deepcopy(REFERENCE["default_theme"])
        default = deepcopy(base)
        default["name"] = "default"
        self._themes = {
            "default": default,
            "paro": deepcopy(base),
            "Paro": deepcopy(base),
        }
        if themes:
            for name, theme in themes.items():
                self._themes[name] = self._with_default_theme_data(theme, name)

    def get(self, name: str) -> dict:
        try:
            return deepcopy(self._themes[name])
        except KeyError as exc:
            raise KeyError(f"Unknown theme: {name}") from exc

    def _with_default_theme_data(self, theme: dict, name: str) -> dict:
        merged = deepcopy(REFERENCE["default_theme"])
        merged.update(deepcopy(theme))
        merged["name"] = theme.get("name", name)
        merged["colors"] = {**REFERENCE["default_theme"]["colors"], **theme.get("colors", {})}
        merged["fonts"] = {**REFERENCE["default_theme"]["fonts"], **theme.get("fonts", {})}
        merged["typeScale"] = deepcopy(REFERENCE["default_theme"]["typeScale"])
        for role, bundle in theme.get("typeScale", {}).items():
            merged["typeScale"][role] = {
                **merged["typeScale"].get(role, {}),
                **deepcopy(bundle),
            }
        return merged


class LayoutRegistry:
    """Resolve layout names through the engine's existing layout table."""

    def __init__(self, layouts: dict | None = None):
        self._layouts = layouts or LAYOUT_DEFINITIONS

    def get(self, name: str) -> dict:
        try:
            return deepcopy(self._layouts[name])
        except KeyError as exc:
            raise KeyError(f"Unknown layout: {name}") from exc


class ShapeLibrary:
    """Resolve named reusable assets through a replaceable seam."""

    def __init__(self, assets: dict[str, dict] | None = None):
        self._assets = deepcopy(assets or {})

    def get(self, name: str) -> dict:
        try:
            return deepcopy(self._assets[name])
        except KeyError as exc:
            raise KeyError(f"Unknown named asset: {name}") from exc


class TimelineStyleRegistry:
    """Resolve timeline styles through the same thin design-system seam."""

    DEFAULT_STYLE = "gantt-grid"

    def __init__(self, styles: dict[str, dict] | None = None, finishes: dict[str, dict] | None = None):
        self._styles = deepcopy(TIMELINE_STYLES)
        self._finishes = deepcopy(TIMELINE_FINISHES)
        if styles:
            for name, style in styles.items():
                self._styles[name] = deepcopy(style)
        if finishes:
            for name, finish in finishes.items():
                self._finishes[name] = deepcopy(finish)

    def get(self, name: str | None = None) -> dict:
        style_name = name or self.DEFAULT_STYLE
        try:
            return deepcopy(self._styles[style_name])
        except KeyError as exc:
            raise KeyError(f"Unknown timeline style: {style_name}") from exc

    def get_finish(self, name: str | None = None) -> dict:
        finish_name = name or "flat"
        try:
            return deepcopy(self._finishes[finish_name])
        except KeyError as exc:
            raise KeyError(f"Unknown timeline finish: {finish_name}") from exc


TIMELINE_FINISHES = {
    "flat": {
        "fill": {"type": "solid"},
        "border": {"enabled": False},
        "shadow": None,
        "cornerRadius": "2pt",
    },
    "soft-shadow": {
        "fill": {"type": "solid"},
        "border": {"enabled": False},
        "shadow": {"blur": "2.5pt", "dist": "1pt", "dir": 2700000, "alpha": 14000},
        "cornerRadius": "3pt",
    },
    "elevated": {
        "fill": {"type": "solid"},
        "border": {"enabled": True, "color": "tone", "width": "0.75pt"},
        "shadow": {"blur": "4pt", "dist": "1.5pt", "dir": 2700000, "alpha": 18000},
        "cornerRadius": "3pt",
    },
    "outlined": {
        "fill": {"type": "solid", "transforms": {"lumMod": 35000, "lumOff": 65000}},
        "border": {"enabled": True, "color": "tone", "width": "1pt"},
        "shadow": None,
        "cornerRadius": "2pt",
    },
    "accent-gradient": {
        "fill": {
            "type": "gradient",
            "startTransforms": {"lumMod": 100000, "lumOff": 18000},
            "endTransforms": {"lumMod": 82000},
            "angle": 5400000,
        },
        "border": {"enabled": False},
        "shadow": {"blur": "3pt", "dist": "1pt", "dir": 2700000, "alpha": 12000},
        "cornerRadius": "8pt",
    },
}


TIMELINE_STYLES = {
    "gantt-grid": {
        "mechanism": "bars-in-columns",
        "gutterRatio": 0.22,
        "gutterMin": "1.2in",
        "headerHeight": "0.32in",
        "showGrid": True,
        "gridColor": "dk2",
        "gridWidth": "0.5pt",
        "rowHeight": "0.5in",
        "rowHeightMin": "0.46in",
        "barHeightRatio": 0.55,
        "barRadius": "2pt",
        "barInset": "0.04in",
        "labelPlacement": "gutter",
        "labelOverflow": "truncate",
        "renderGroups": False,
        "groupHeaderStyle": "none",
        "milestoneMarker": "diamond",
        "milestoneLabelPlacement": "below",
        "milestoneLabelOverflow": "extend",
        "defaultTones": ["accent1", "accent2", "accent3"],
        "paletteMode": "cycle",
        "finish": "flat",
    },
    "gantt-minimal": {
        "mechanism": "bars-in-columns",
        "gutterRatio": 0.22,
        "gutterMin": "1.2in",
        "headerHeight": "0.28in",
        "showGrid": False,
        "gridColor": "dk2",
        "gridWidth": "0.5pt",
        "rowHeight": "0.48in",
        "rowHeightMin": "0.44in",
        "barHeightRatio": 0.55,
        "barRadius": "3pt",
        "barInset": "0.04in",
        "labelPlacement": "gutter",
        "labelOverflow": "truncate",
        "renderGroups": False,
        "groupHeaderStyle": "none",
        "milestoneMarker": "diamond",
        "milestoneLabelPlacement": "below",
        "milestoneLabelOverflow": "stagger",
        "defaultTones": ["accent1", "accent2", "accent3"],
        "paletteMode": "cycle",
        "finish": "soft-shadow",
    },
    "roadmap": {
        "mechanism": "bars-in-columns",
        "gutterRatio": 0,
        "gutterMin": "0",
        "headerHeight": "0.32in",
        "showGrid": False,
        "gridColor": "dk2",
        "gridWidth": "0.5pt",
        "rowHeight": "0.56in",
        "rowHeightMin": "0.5in",
        "barHeightRatio": 0.64,
        "barRadius": "8pt",
        "barInset": "0.06in",
        "labelPlacement": "on-bar",
        "labelOverflow": "truncate",
        "renderGroups": False,
        "groupHeaderStyle": "none",
        "milestoneMarker": "flag",
        "milestoneLabelPlacement": "above",
        "milestoneLabelOverflow": "extend",
        "defaultTones": ["accent1", "accent2", "accent3", "accent4"],
        "paletteMode": "cycle",
        "finish": "accent-gradient",
    },
    "swimlane": {
        "mechanism": "bars-in-columns",
        "gutterRatio": 0.22,
        "gutterMin": "1.2in",
        "headerHeight": "0.32in",
        "showGrid": True,
        "gridColor": "dk2",
        "gridWidth": "0.5pt",
        "rowHeight": "0.46in",
        "rowHeightMin": "0.42in",
        "barHeightRatio": 0.55,
        "barRadius": "2pt",
        "barInset": "0.04in",
        "labelPlacement": "gutter",
        "labelOverflow": "truncate",
        "renderGroups": True,
        "groupHeaderStyle": "band",
        "milestoneMarker": "diamond",
        "milestoneLabelPlacement": "below",
        "milestoneLabelOverflow": "stagger",
        "defaultTones": ["accent1", "accent2", "accent3"],
        "paletteMode": "by-group",
        "finish": "elevated",
    },
}
