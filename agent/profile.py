"""Design Profile: the persistent layer above briefs and decks.

A profile is what makes a student and an investment banker get different decks
from the same system: audience, formality, complexity dials, theme source
(corporate template vs house style), attached assets, exemplar decks, and the
durable preferences the agent accumulates from conversation ("we always use
waterfalls for P&L"). It outlives any single session.

    profiles/<name>/profile.json     the artifact (this module's schema)
    profiles/<name>/assets/          user-attached icons/photos/logos
    profiles/<name>/exemplars/       decks the user liked

Create one:   .venv/bin/python -m agent.profile init profiles/acme
Use one:      .venv/bin/python -m agent.chat --profile profiles/acme
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

PROFILE_VERSION = 1

DEFAULT_PROFILE: dict[str, Any] = {
    "profile_version": PROFILE_VERSION,
    "name": "default",
    "audience": "general business",
    "formality": "corporate",  # corporate | academic | casual
    "language": "en",
    "chart_complexity": "standard",  # minimal | standard | rich
    "diagram_density": "standard",  # airy | standard | dense
    "theme": {
        "source": "house",  # house | template
        "house_style": "default",
        "template_pptx": None,
        "theme_name": "ingested",
    },
    "assets": {},  # name -> {"src": path, "alt": description}
    "exemplars": [],  # deck XML paths the agent should study
    "notes": [],  # durable preferences, appended over time
}

_ENUMS = {
    "formality": {"corporate", "academic", "casual"},
    "chart_complexity": {"minimal", "standard", "rich"},
    "diagram_density": {"airy", "standard", "dense"},
}


class ProfileError(ValueError):
    """Raised when a profile file is unusable."""


def profile_path(profile_dir: str | Path) -> Path:
    return Path(profile_dir) / "profile.json"


def load_profile(profile_dir: str | Path) -> dict[str, Any]:
    """Load a profile, merging over defaults; absent file -> pure defaults."""
    path = profile_path(profile_dir)
    merged = deepcopy(DEFAULT_PROFILE)
    if not path.exists():
        return merged
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(
            f"{path} is not valid JSON ({exc}). Fix it or delete it to start fresh."
        ) from exc
    if not isinstance(data, dict):
        raise ProfileError(f"{path} must contain a JSON object")
    for key, value in data.items():
        if key == "theme" and isinstance(value, dict):
            merged["theme"].update(value)
        else:
            merged[key] = value
    for key, allowed in _ENUMS.items():
        if merged[key] not in allowed:
            raise ProfileError(
                f"{path}: {key}={merged[key]!r} not in {sorted(allowed)}"
            )
    return merged


def init_profile(profile_dir: str | Path) -> Path:
    """Write a starter profile (and its directories) for the user to edit."""
    directory = Path(profile_dir)
    (directory / "assets").mkdir(parents=True, exist_ok=True)
    (directory / "exemplars").mkdir(parents=True, exist_ok=True)
    path = profile_path(directory)
    if not path.exists():
        starter = deepcopy(DEFAULT_PROFILE)
        starter["name"] = directory.name
        path.write_text(json.dumps(starter, indent=2) + "\n", encoding="utf-8")
    return path


def profile_prompt(profile: dict[str, Any], profile_dir: str | Path | None) -> str:
    """The system-prompt section a loaded profile contributes."""
    lines = [
        "# Design profile (persistent — outranks generic doctrine where they conflict)",
        f"Audience: {profile['audience']}. Formality: {profile['formality']}."
        f" Language: {profile['language']}.",
        f"Chart complexity: {profile['chart_complexity']}"
        f" (minimal = one message per chart, no embellishment;"
        f" rich = layered series, callouts, annotations).",
        f"Diagram density: {profile['diagram_density']}"
        f" (airy = generous whitespace, fewer elements per slide;"
        f" dense = dashboard-grade packing, smaller type).",
    ]
    theme = profile["theme"]
    if theme.get("source") == "template" and theme.get("template_pptx"):
        lines.append(
            f'Theme: corporate template "{theme["template_pptx"]}" — on EVERY paro_build'
            f' call pass theme_pptx="{theme["template_pptx"]}" and'
            f' theme_name="{theme.get("theme_name", "ingested")}", set deck'
            f' theme="{theme.get("theme_name", "ingested")}", use theme tokens, and'
            " prefer placeholder covers and layout=\"divider\"."
        )
    else:
        lines.append(
            f"Theme: house style '{theme.get('house_style', 'default')}' — no template;"
            " use theme tokens against the registered theme of that name (or the"
            " engine default), and compose covers explicitly."
        )
    if profile["assets"]:
        lines.append("Attached assets (use these before stock choices):")
        for name, asset in profile["assets"].items():
            lines.append(f"  - {name}: {asset.get('src')} — {asset.get('alt', '')}")
    if profile["exemplars"]:
        lines.append(
            "Exemplar decks the user likes (Read them before your first slide): "
            + ", ".join(profile["exemplars"])
        )
    if profile["notes"]:
        lines.append("Durable preferences accumulated from past sessions (binding):")
        lines.extend(f"  - {note}" for note in profile["notes"])
    if profile_dir is not None:
        lines.append(
            f"When the user states a durable preference ('always…', 'never…', 'from now"
            f" on…'), record it: Edit {profile_path(profile_dir)} and append a short"
            f" sentence to its \"notes\" array. Do not rewrite other fields uninvited."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="agent.profile", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a starter profile directory")
    init.add_argument("directory")
    show = sub.add_parser("show", help="print the resolved profile and its prompt")
    show.add_argument("directory")
    args = parser.parse_args(argv)

    if args.command == "init":
        path = init_profile(args.directory)
        print(f"profile ready: {path}")
    elif args.command == "show":
        profile = load_profile(args.directory)
        print(json.dumps(profile, indent=2))
        print("\n--- prompt section ---\n")
        print(profile_prompt(profile, args.directory))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
