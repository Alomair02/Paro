"""Run the Paro authoring agent on a brief.

    .venv/bin/python -m agent "A 3-slide overview of ACME Corp Q2 results" \
        [--out samples/acme.xml] [--theme template.pptx] [--max-turns 30]

The agent writes the deck XML, builds it through paro_build, reads its own PNG
renders, and iterates (max three builds per the protocol).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from agent.prompt import PROJECT_ROOT, build_system_prompt
from agent.tools import mcp_server


def make_options(max_turns: int = 40) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=build_system_prompt(),
        cwd=str(PROJECT_ROOT),
        mcp_servers={"paro": mcp_server()},
        allowed_tools=[
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "mcp__paro__paro_build",
        ],
        permission_mode="acceptEdits",
        max_turns=max_turns,
    )


def make_prompt(brief: str, out_path: str, theme_pptx: str | None) -> str:
    parts = [
        f"Brief: {brief}",
        f"Write the deck to: {out_path}",
    ]
    if theme_pptx:
        parts.append(
            f"Theme template: {theme_pptx} — on EVERY paro_build call pass"
            f' theme_pptx="{theme_pptx}" and theme_name="ingested", and set the deck'
            f' root to theme="ingested". Use theme tokens (dk1/accent1/...) so the'
            f" template's identity carries; do not hard-code its hex values."
        )
    return "\n".join(parts)


async def run(brief: str, out_path: str, theme_pptx: str | None, max_turns: int) -> int:
    # NB: don't return from inside the async for — closing the SDK's message
    # generator mid-iteration raises "aclose(): asynchronous generator is
    # already running" on teardown. Drain it, then return.
    exit_code = 0
    async for message in query(
        prompt=make_prompt(brief, out_path, theme_pptx),
        options=make_options(max_turns),
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                elif isinstance(block, ToolUseBlock):
                    target = block.input.get("file_path") or block.input.get("deck_path") or ""
                    print(f"  -> {block.name} {target}")
        elif isinstance(message, ResultMessage):
            cost = f", ${message.total_cost_usd:.4f}" if message.total_cost_usd else ""
            print(f"[done: {message.num_turns} turns{cost}]")
            exit_code = 1 if message.is_error else 0
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent", description=__doc__)
    parser.add_argument("brief", help="what the deck should be")
    parser.add_argument("--out", default="out/agent_deck.xml", help="deck XML path the agent writes")
    parser.add_argument("--theme", help="ingest theme from this .pptx/.potx template")
    parser.add_argument("--max-turns", type=int, default=40)
    args = parser.parse_args(argv)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    return asyncio.run(run(args.brief, args.out, args.theme, args.max_turns))
