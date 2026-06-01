"""XML DSL transpiler for the PPTX engine."""

from transpiler.parser import DSLParser, DSLParseError
from transpiler.pipeline import TranspileResult, transpile, transpile_deck
from transpiler.registries import LayoutRegistry, ShapeLibrary, ThemeRegistry, TimelineStyleRegistry
from transpiler.resolver import LayoutResolver, ResolvedDeck
from transpiler.text_metrics import TextMeasurement, TextMeasurer
from transpiler.validator import ValidationIssue, Validator

__all__ = [
    "DSLParser",
    "DSLParseError",
    "LayoutRegistry",
    "ShapeLibrary",
    "ThemeRegistry",
    "TimelineStyleRegistry",
    "LayoutResolver",
    "ResolvedDeck",
    "TextMeasurement",
    "TextMeasurer",
    "ValidationIssue",
    "Validator",
    "TranspileResult",
    "transpile",
    "transpile_deck",
]
