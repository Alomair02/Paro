"""OOXML part builders for PPTX package parts."""

from builders.theme_builder import ThemeBuilder
from builders.master_builder import MasterBuilder
from builders.layout_builder import LayoutBuilder, LAYOUT_DEFINITIONS
from builders.presentation_builder import PresentationBuilder
from builders.slide_builder import SlideBuilder
from builders.shape_emitters import (
    SlideState,
    emit_autoshape,
    emit_image,
    emit_placeholder_text,
    emit_text_box,
)
from builders.zip_assembler import ZIPAssembler
from builders.deck_builder import build_deck

__all__ = [
    "ThemeBuilder",
    "MasterBuilder",
    "LayoutBuilder",
    "LAYOUT_DEFINITIONS",
    "PresentationBuilder",
    "SlideBuilder",
    "SlideState",
    "emit_placeholder_text",
    "emit_text_box",
    "emit_image",
    "emit_autoshape",
    "ZIPAssembler",
    "build_deck",
]
