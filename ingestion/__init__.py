"""Template ingestion: turn a user-supplied .pptx/.potx into a theme bundle."""

from ingestion.layout_extractor import (
    extract_layout_transplant,
    transplant_to_registry_layouts,
)
from ingestion.theme_extractor import (
    ThemeExtractionError,
    bundle_to_registry_themes,
    extract_theme_bundle,
)

__all__ = [
    "ThemeExtractionError",
    "bundle_to_registry_themes",
    "extract_layout_transplant",
    "extract_theme_bundle",
    "transplant_to_registry_layouts",
]
