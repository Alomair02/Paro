"""Plain AST structures for the slide DSL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    """A parsed DSL element."""

    kind: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    text: str = ""

    def clone(self) -> "Node":
        return Node(
            self.kind,
            dict(self.attrs),
            [child.clone() for child in self.children],
            self.text,
        )


@dataclass
class ThemeAst:
    """Inline deck theme definition."""

    name: str
    attrs: dict[str, str]


@dataclass
class SlideAst:
    """One parsed slide."""

    index: int
    layout: str
    flow: str
    attrs: dict[str, str]
    children: list[Node]


@dataclass
class DeckAst:
    """Parsed deck root."""

    theme: str
    size: str
    font: str | None
    inline_theme: ThemeAst | None
    slides: list[SlideAst]
    defs: dict[str, list[Node]]


@dataclass(frozen=True)
class Box:
    """Absolute EMU rectangle."""

    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def inset(self, amount: int) -> "Box":
        amount = max(0, min(amount, self.w // 2, self.h // 2))
        return Box(self.x + amount, self.y + amount, self.w - 2 * amount, self.h - 2 * amount)

    def as_shape_geometry(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass
class ResolvedBlock:
    """Resolved block metadata used by validation."""

    kind: str
    box: Box
    parent_kind: str
    attrs: dict[str, Any] = field(default_factory=dict)
    content: dict[str, Any] | None = None


@dataclass
class ResolvedSlide:
    """Resolved slide plus validator metadata."""

    slide_data: dict[str, Any]
    blocks: list[ResolvedBlock] = field(default_factory=list)
    grid_placements: list[dict[str, Any]] = field(default_factory=list)
    placeholder_refs: list[dict[str, Any]] = field(default_factory=list)
    sibling_font_groups: list[list[dict[str, Any]]] = field(default_factory=list)

