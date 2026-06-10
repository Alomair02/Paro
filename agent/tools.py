"""In-process MCP tools the authoring agent can call."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def build_deck_text(deck_path: str, png: bool, theme_pptx: str | None = None) -> str:
    """Run paro's build (and optional render) capturing its report as text."""
    from paro import run_build

    out = io.StringIO()
    with redirect_stdout(out):
        code = run_build(
            deck_path,
            png=png,
            theme_pptx=theme_pptx,
        )
    status = "OK" if code == 0 else "FAILED"
    return f"build {status} (exit {code})\n{out.getvalue()}"


@tool(
    "paro_build",
    "Build a Paro deck XML into .pptx, print validator/design-lint findings, and "
    "optionally render per-slide PNGs you can Read to inspect your own output.",
    {"deck_path": str, "png": bool},
)
async def paro_build(args: dict):
    text = build_deck_text(
        str(args["deck_path"]),
        bool(args.get("png", True)),
        args.get("theme_pptx"),
    )
    return {"content": [{"type": "text", "text": text}]}


def mcp_server():
    return create_sdk_mcp_server(name="paro", version="1.0.0", tools=[paro_build])
