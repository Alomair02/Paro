#!/usr/bin/env python3
"""Paro CLI — build a deck and see it.

    python paro.py build deck.xml                      deck.pptx + lint/warnings
    python paro.py build deck.xml --png                + per-slide PNGs (soffice + pdftoppm)
    python paro.py build deck.xml --theme corp.pptx    theme ingested from a real template

This is the agent's render loop: one command from DSL to pixels, with the
validator's findings on stdout. Exit code 0 = built (warnings allowed),
1 = errors (validation, parse, or missing input).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _print_issues(issues) -> None:
    for issue in issues:
        print(f"  [{issue.severity}] {issue.code}: {issue.message}")


def run_build(
    deck_path: str | Path,
    output_path: str | Path | None = None,
    *,
    png: bool = False,
    png_dir: str | Path | None = None,
    dpi: int = 100,
    theme_pptx: str | Path | None = None,
    theme_name: str | None = None,
) -> int:
    from transpiler.parser import DSLParseError
    from transpiler.pipeline import transpile_deck
    from transpiler.validator import TranspileValidationError

    deck_path = Path(deck_path)
    if not deck_path.exists():
        print(f"error: no such deck: {deck_path}")
        return 1
    output_path = Path(output_path) if output_path else deck_path.with_suffix(".pptx")

    themes = None
    if theme_pptx:
        from ingestion import bundle_to_registry_themes, extract_theme_bundle

        bundle = extract_theme_bundle(theme_pptx)
        name = theme_name or Path(theme_pptx).stem
        themes = bundle_to_registry_themes(bundle, name)
        skipped = bundle.get("coverage", {}).get("skipped", [])
        print(f"theme '{name}' ingested from {Path(theme_pptx).name}"
              + (f" ({len(skipped)} blocks skipped — see bundle coverage)" if skipped else ""))

    try:
        result = transpile_deck(deck_path, output_path, themes=themes)
    except TranspileValidationError as exc:
        print(f"BUILD FAILED — validation errors in {deck_path.name}:")
        _print_issues(exc.issues)
        return 1
    except (DSLParseError, ValueError, KeyError) as exc:
        print(f"BUILD FAILED — {deck_path.name}: {exc}")
        return 1

    slides = len(result.resolved_deck.slides)
    print(f"built {output_path} ({slides} slide{'s' if slides != 1 else ''})")
    warnings = [i for i in result.validation_issues if i.severity == "warning"]
    if warnings:
        print(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}:")
        _print_issues(warnings)

    if png:
        pages = render_png(output_path, Path(png_dir) if png_dir else output_path.parent, dpi)
        for page in pages:
            print(f"  rendered {page}")
    return 0


def render_png(pptx_path: Path, out_dir: Path, dpi: int = 100) -> list[Path]:
    """LibreOffice -> PDF -> PNG per slide. Returns the page image paths."""
    soffice = shutil.which("soffice")
    pdftoppm = shutil.which("pdftoppm")
    if not soffice or not pdftoppm:
        missing = [name for name, found in (("soffice", soffice), ("pdftoppm", pdftoppm)) if not found]
        print(f"  (skipping --png: {', '.join(missing)} not on PATH)")
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", str(pptx_path), "--outdir", tmp],
            check=True,
            capture_output=True,
        )
        pdf = Path(tmp) / (pptx_path.stem + ".pdf")
        if not pdf.exists():
            print("  (LibreOffice produced no PDF — is another soffice instance running?)")
            return []
        subprocess.run(
            [pdftoppm, "-png", "-r", str(dpi), str(pdf), str(out_dir / pptx_path.stem)],
            check=True,
            capture_output=True,
        )
    return sorted(out_dir.glob(f"{pptx_path.stem}-*.png"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paro", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="transpile a DSL deck to .pptx (optionally render PNGs)")
    build.add_argument("deck", help="path to the deck XML")
    build.add_argument("-o", "--output", help="output .pptx path (default: beside the XML)")
    build.add_argument("--png", action="store_true", help="render per-slide PNGs via LibreOffice")
    build.add_argument("--png-dir", help="directory for PNGs (default: beside the .pptx)")
    build.add_argument("--dpi", type=int, default=100, help="PNG resolution (default 100)")
    build.add_argument("--theme", help="ingest theme from this .pptx/.potx template")
    build.add_argument("--theme-name", help="registry name for the ingested theme (default: file stem)")

    args = parser.parse_args(argv)
    return run_build(
        args.deck,
        args.output,
        png=args.png,
        png_dir=args.png_dir,
        dpi=args.dpi,
        theme_pptx=args.theme,
        theme_name=args.theme_name,
    )


if __name__ == "__main__":
    sys.exit(main())
