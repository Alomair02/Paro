"""Template ingestion: turn a user-supplied .pptx/.potx into a theme bundle."""

from ingestion.theme_extractor import (
    ThemeExtractionError,
    bundle_to_registry_themes,
    extract_theme_bundle,
)

__all__ = [
    "ThemeExtractionError",
    "bundle_to_registry_themes",
    "extract_theme_bundle",
]
