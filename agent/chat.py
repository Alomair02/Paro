"""Interactive dev chat with the Paro authoring agent.

    .venv/bin/python -m agent.chat [--theme template.pptx] [--out-dir out/chat]

Talk to the agent like a user: give a brief, watch it write/build/look/fix,
then iterate conversationally ("make the title shorter", "add a divider",
"rebuild"). The session keeps full context between turns.

Commands:  /quit  exit   ·   /new  fresh session (context cleared)
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from agent.prompt import PROJECT_ROOT  # noqa: F401  (keeps cwd semantics with runner)
from agent.runner import make_options


def _session_preamble(theme: str | None, out_dir: str) -> str:
    lines = [
        "This is an interactive working session: the user will give briefs and",
        f"follow-up revisions. Write decks under {out_dir}/ (pick clear file names),",
        "and when revising, Edit the existing deck file rather than starting over.",
    ]
    if theme:
        lines.append(
            f'Theme template for this whole session: "{theme}" — on EVERY paro_build'
            f' call pass theme_pptx="{theme}" and theme_name="ingested", set deck'
            ' theme="ingested", use theme tokens, and prefer placeholder covers and'
            " layout=\"divider\" so the template's designed layouts carry the deck."
        )
    return "\n".join(lines)


async def _drain(client: ClaudeSDKClient):
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"\n{block.text}")
                elif isinstance(block, ToolUseBlock):
                    target = block.input.get("file_path") or block.input.get("deck_path") or ""
                    print(f"  · {block.name} {target}")
        elif isinstance(message, ResultMessage):
            cost = f"  (${message.total_cost_usd:.4f})" if message.total_cost_usd else ""
            print(f"\n--- turn done{cost} ---")


async def chat(theme: str | None, out_dir: str, max_turns: int, profile_dir: str | None) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    options = make_options(max_turns, profile_dir)
    options.system_prompt += "\n\n# Session\n" + _session_preamble(theme, out_dir)

    print(__doc__)
    if profile_dir:
        print(f"[profile: {profile_dir}]")
    if theme:
        print(f"[session theme: {theme}]")

    client = ClaudeSDKClient(options)
    await client.connect()
    try:
        while True:
            try:
                user = input("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user:
                continue
            if user == "/quit":
                break
            if user == "/new":
                await client.disconnect()
                client = ClaudeSDKClient(options)
                await client.connect()
                print("[fresh session]")
                continue
            await client.query(user)
            await _drain(client)
    finally:
        await client.disconnect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.chat", description=__doc__)
    parser.add_argument("--theme", help="template .pptx for the whole session")
    parser.add_argument("--out-dir", default="out/chat", help="where the agent writes decks")
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument("--profile", help="design profile directory (see agent.profile)")
    args = parser.parse_args(argv)
    asyncio.run(chat(args.theme, args.out_dir, args.max_turns, args.profile))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
