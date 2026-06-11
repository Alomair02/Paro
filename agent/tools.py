"""In-process MCP tools the authoring agent can call."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def build_deck_text(
    deck_path: str,
    png: bool,
    theme_pptx: str | None = None,
    theme_name: str | None = None,
) -> str:
    """Run paro's build (and optional render) capturing its report as text."""
    from paro import run_build

    out = io.StringIO()
    with redirect_stdout(out):
        code = run_build(
            deck_path,
            png=png,
            theme_pptx=theme_pptx,
            theme_name=theme_name,
        )
    status = "OK" if code == 0 else "FAILED"
    return f"build {status} (exit {code})\n{out.getvalue()}"


@tool(
    "paro_build",
    "Build a Paro deck XML into .pptx, print validator/design-lint findings, and "
    "optionally render per-slide PNGs you can Read to inspect your own output. "
    "To build against an ingested template, pass theme_pptx (the template path) and "
    "theme_name (the name your deck's theme= attribute uses) on every call.",
    {"deck_path": str, "png": bool, "theme_pptx": str, "theme_name": str},
)
async def paro_build(args: dict):
    text = build_deck_text(
        str(args["deck_path"]),
        bool(args.get("png", True)),
        args.get("theme_pptx"),
        args.get("theme_name"),
    )
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "read_source",
    "Read user-supplied source material (xlsx, docx, pdf, csv, txt, md) as text; "
    "spreadsheet rows and document tables come back as pipe-delimited rows you can "
    "lift into <chart> series or <table> cells. Pass sheet to pick one xlsx sheet.",
    {"path": str, "sheet": str},
)
async def read_source_tool(args: dict):
    from agent.sources import SourceReadError, read_source

    try:
        text = read_source(str(args["path"]), args.get("sheet"))
    except SourceReadError as exc:
        text = f"read_source FAILED: {exc}"
    return {"content": [{"type": "text", "text": text}]}


def mcp_server():
    return create_sdk_mcp_server(
        name="paro", version="1.0.0", tools=[paro_build, read_source_tool]
    )
