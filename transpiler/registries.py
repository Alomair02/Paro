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
