"""Tier 0/1 deterministic theme extraction per INGESTION_SPEC.md.

Reads what a template *declares* (theme part, slide master, presentation
properties) via rels-driven part discovery — never path guessing. Everything
on the theme surface is captured; what the engine cannot consume yet is
preserved raw and reported in the bundle's coverage block.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from lxml import etree

from builders.common import REFERENCE

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

REL_OFFICE_DOCUMENT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
REL_SLIDE_MASTER = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
)
REL_SLIDE_LAYOUT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
)
REL_THEME = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"

COLOR_SLOTS = (
    "dk1", "lt1", "dk2", "lt2",
    "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
    "hlink", "folHlink",
)

# sysClr fallbacks when a template omits lastClr.
SYS_CLR_DEFAULTS = {"windowText": "000000", "window": "FFFFFF"}

# Default clrMap: scheme-color tokens as used inside bg/fill references.
SCHEME_TOKEN_MAP = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}


class ThemeExtractionError(ValueError):
    """Raised when a template lacks a part OPC packaging requires."""


def extract_theme_bundle(pptx_path: str | Path) -> dict[str, Any]:
    """Extract a v1 theme bundle (see INGESTION_SPEC.md) from a .pptx/.potx."""
    pptx_path = Path(pptx_path)
    try:
        with ZipFile(pptx_path) as package:
            return _extract(package, pptx_path.name)
    except BadZipFile as exc:
        raise ThemeExtractionError(
            f"{pptx_path.name} is not a .pptx/.potx package (not a zip archive)"
        ) from exc


def bundle_to_registry_themes(bundle: dict[str, Any], name: str) -> dict[str, dict]:
    """Map a bundle to the ThemeRegistry injection shape, stripping provenance."""
    type_scale = {
        role: {k: v for k, v in entry.items() if k != "provenance"}
        for role, entry in bundle["theme"]["typeScale"].items()
    }
    theme: dict[str, Any] = {
        "name": name,
        "colors": dict(bundle["theme"]["colors"]),
        "fonts": dict(bundle["theme"]["fonts"]),
        "typeScale": type_scale,
    }
    return {name: theme}


# --- package traversal -----------------------------------------------------


def _extract(package: ZipFile, file_name: str) -> dict[str, Any]:
    coverage: dict[str, Any] = {"used": [], "preserved": {}, "skipped": []}

    presentation_part = _rel_target(package, "", REL_OFFICE_DOCUMENT)
    if presentation_part is None:
        raise ThemeExtractionError("package has no officeDocument relationship")
    presentation = _parse(package, presentation_part)

    master_rid = presentation.find("p:sldMasterIdLst/p:sldMasterId", NS)
    if master_rid is None:
        raise ThemeExtractionError(f"{presentation_part} declares no slide master")
    master_part = _resolve_rid(
        package, presentation_part, master_rid.get(_qn("r", "id"))
    )
    master = _parse(package, master_part)

    extra_masters = presentation.findall("p:sldMasterIdLst/p:sldMasterId", NS)[1:]
    if extra_masters:
        coverage["skipped"].append({
            "what": f"{len(extra_masters)} additional slide master(s)",
            "why": "v1 extracts the first master; variants are a deferred bundle feature",
        })

    theme_part = _rel_target(package, master_part, REL_THEME)
    if theme_part is None:
        raise ThemeExtractionError(f"{master_part} has no theme relationship")
    theme_root = _parse(package, theme_part)

    colors, color_notes = _extract_colors(theme_root, theme_part)
    fonts, font_notes = _extract_fonts(theme_root, theme_part)
    coverage["skipped"].extend(color_notes + font_notes)
    coverage["used"] += ["theme.colors", "theme.fonts"]

    slide_size = _extract_slide_size(presentation, coverage)
    background = _extract_background(master, theme_root, coverage)
    master_text_styles = _extract_master_text_styles(master)
    type_scale = _derive_type_scale(master_text_styles)
    coverage["used"] += ["theme.typeScale", "slide_size"]
    if background is not None:
        coverage["used"].append("background")

    fmt_scheme = theme_root.find("a:themeElements/a:fmtScheme", NS)
    if fmt_scheme is not None:
        coverage["preserved"]["fmtScheme"] = etree.tostring(
            fmt_scheme, encoding="unicode"
        )
    layout_count = len(_rel_targets(package, master_part, REL_SLIDE_LAYOUT))
    coverage["preserved"]["layouts"] = {
        "count": layout_count,
        "note": "layout geometry mapping is Tier 3 (agent judgment); see INGESTION_SPEC",
    }

    clr_scheme = theme_root.find("a:themeElements/a:clrScheme", NS)
    font_scheme = theme_root.find("a:themeElements/a:fontScheme", NS)
    return {
        "bundle_version": 1,
        "source": {
            "file": file_name,
            "theme_part": theme_part,
            "theme_name": theme_root.get("name", ""),
            "color_scheme_name": clr_scheme.get("name", "") if clr_scheme is not None else "",
            "font_scheme_name": font_scheme.get("name", "") if font_scheme is not None else "",
        },
        "theme": {"colors": colors, "fonts": fonts, "typeScale": type_scale},
        "slide_size": slide_size,
        "background": background,
        "master_text_styles": master_text_styles,
        "coverage": coverage,
    }


def _qn(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


def _parse(package: ZipFile, part: str) -> etree._Element:
    try:
        data = package.read(part)
    except KeyError as exc:
        raise ThemeExtractionError(f"package is missing required part: {part}") from exc
    return etree.fromstring(data)


def _rels_path(part: str) -> str:
    if not part:
        return "_rels/.rels"
    folder, _, name = part.rpartition("/")
    return f"{folder}/_rels/{name}.rels" if folder else f"_rels/{name}.rels"


def _resolve_target(base_part: str, target: str) -> str:
    base = Path(base_part).parent if base_part else Path("")
    resolved = (base / target).as_posix()
    parts: list[str] = []
    for segment in resolved.split("/"):
        if segment == "..":
            parts.pop()
        elif segment not in (".", ""):
            parts.append(segment)
    return "/".join(parts)


def _rel_targets(package: ZipFile, part: str, rel_type: str) -> list[str]:
    rels_part = _rels_path(part)
    if rels_part not in package.namelist():
        return []
    rels = etree.fromstring(package.read(rels_part))
    return [
        _resolve_target(part, rel.get("Target"))
        for rel in rels.findall("rel:Relationship", NS)
        if rel.get("Type") == rel_type and rel.get("TargetMode") != "External"
    ]


def _rel_target(package: ZipFile, part: str, rel_type: str) -> str | None:
    targets = _rel_targets(package, part, rel_type)
    return targets[0] if targets else None


def _resolve_rid(package: ZipFile, part: str, rid: str) -> str:
    rels = etree.fromstring(package.read(_rels_path(part)))
    for rel in rels.findall("rel:Relationship", NS):
        if rel.get("Id") == rid:
            return _resolve_target(part, rel.get("Target"))
    raise ThemeExtractionError(f"{part} has no relationship {rid}")


# --- theme surface ----------------------------------------------------------


def _extract_colors(theme_root, theme_part) -> tuple[dict[str, str], list[dict]]:
    scheme = theme_root.find("a:themeElements/a:clrScheme", NS)
    if scheme is None:
        raise ThemeExtractionError(f"{theme_part} has no a:clrScheme")
    colors: dict[str, str] = {}
    notes: list[dict] = []
    for slot in COLOR_SLOTS:
        el = scheme.find(f"a:{slot}", NS)
        if el is None:
            notes.append({"what": f"color slot {slot}", "why": "absent from clrScheme"})
            continue
        srgb = el.find("a:srgbClr", NS)
        sys_clr = el.find("a:sysClr", NS)
        if srgb is not None:
            colors[slot] = srgb.get("val", "").upper()
        elif sys_clr is not None:
            last = sys_clr.get("lastClr")
            if last is None:
                last = SYS_CLR_DEFAULTS.get(sys_clr.get("val", ""), "000000")
                notes.append({
                    "what": f"color slot {slot}",
                    "why": f"sysClr without lastClr; used {last} default",
                })
            colors[slot] = last.upper()
        else:
            notes.append({
                "what": f"color slot {slot}",
                "why": f"unsupported color element <{etree.QName(el[0]).localname}>"
                if len(el) else "empty color slot",
            })
    return colors, notes


def _extract_fonts(theme_root, theme_part) -> tuple[dict[str, str], list[dict]]:
    scheme = theme_root.find("a:themeElements/a:fontScheme", NS)
    if scheme is None:
        raise ThemeExtractionError(f"{theme_part} has no a:fontScheme")
    fonts: dict[str, str] = {}
    notes: list[dict] = []
    for slot, tag in (("heading", "majorFont"), ("body", "minorFont")):
        latin = scheme.find(f"a:{tag}/a:latin", NS)
        typeface = latin.get("typeface", "") if latin is not None else ""
        if typeface:
            fonts[slot] = typeface
        else:
            notes.append({
                "what": f"{slot} font ({tag})",
                "why": "empty latin typeface; engine default kept",
            })
    return fonts, notes


def _extract_slide_size(presentation, coverage) -> dict[str, Any]:
    sld_sz = presentation.find("p:sldSz", NS)
    if sld_sz is None:
        coverage["skipped"].append(
            {"what": "slide size", "why": "presentation.xml has no p:sldSz"}
        )
        return {"cx": None, "cy": None, "engine_size": None}
    cx, cy = int(sld_sz.get("cx")), int(sld_sz.get("cy"))
    engine_size = next(
        (
            name
            for name, dims in REFERENCE["slide_sizes"].items()
            if isinstance(dims, dict) and dims["cx"] == cx and dims["cy"] == cy
        ),
        None,
    )
    if engine_size is None:
        coverage["skipped"].append({
            "what": f"slide size {cx}x{cy}",
            "why": "no matching engine size; engine default applies",
        })
    return {"cx": cx, "cy": cy, "engine_size": engine_size}


# --- background -------------------------------------------------------------


def _extract_background(master, theme_root, coverage) -> dict[str, Any] | None:
    bg = master.find("p:cSld/p:bg", NS)
    if bg is None:
        return None

    bg_pr = bg.find("p:bgPr", NS)
    if bg_pr is not None:
        solid = bg_pr.find("a:solidFill", NS)
        if solid is not None:
            resolved = _fill_color(solid, ph_color=None)
            if resolved is not None:
                key = "token" if resolved[0] == "scheme" else "hex"
                return {"kind": resolved[0], key: resolved[1], "provenance": "extracted"}
        coverage["preserved"]["master_background"] = etree.tostring(bg, encoding="unicode")
        coverage["skipped"].append({
            "what": "master background (bgPr)",
            "why": "non-solid background fill; preserved raw, engine default applies",
        })
        return None

    bg_ref = bg.find("p:bgRef", NS)
    if bg_ref is None:
        return None
    idx = int(bg_ref.get("idx", "0"))
    ph = _scheme_token(bg_ref)
    fill = _format_scheme_fill(theme_root, idx)
    if fill is not None and fill.tag == _qn("a", "solidFill"):
        resolved = _fill_color(fill, ph_color=ph)
        if resolved is not None:
            key = "token" if resolved[0] == "scheme" else "hex"
            return {"kind": resolved[0], key: resolved[1], "provenance": "extracted"}
    coverage["preserved"]["master_background"] = etree.tostring(bg, encoding="unicode")
    coverage["skipped"].append({
        "what": f"master background (bgRef idx={idx})",
        "why": "non-solid format-scheme fill; preserved raw, engine default applies",
    })
    return None


def _format_scheme_fill(theme_root, idx: int):
    """bgRef/fillRef index per ECMA-376: 1-999 fillStyleLst, >=1001 bgFillStyleLst."""
    if idx >= 1001:
        styles = theme_root.findall(
            "a:themeElements/a:fmtScheme/a:bgFillStyleLst/*", NS
        )
        offset = idx - 1001
    elif idx >= 1:
        styles = theme_root.findall("a:themeElements/a:fmtScheme/a:fillStyleLst/*", NS)
        offset = idx - 1
    else:
        return None
    return styles[offset] if 0 <= offset < len(styles) else None


def _scheme_token(color_parent) -> str | None:
    scheme_clr = color_parent.find("a:schemeClr", NS)
    if scheme_clr is None:
        return None
    val = scheme_clr.get("val", "")
    return SCHEME_TOKEN_MAP.get(val, val)


def _fill_color(fill_el, ph_color: str | None) -> tuple[str, str] | None:
    """Resolve a solidFill to ('scheme', token) or ('hex', RRGGBB)."""
    srgb = fill_el.find("a:srgbClr", NS)
    if srgb is not None:
        return ("hex", srgb.get("val", "").upper())
    scheme_clr = fill_el.find("a:schemeClr", NS)
    if scheme_clr is not None:
        val = scheme_clr.get("val", "")
        if val == "phClr":
            return ("scheme", ph_color) if ph_color else None
        return ("scheme", SCHEME_TOKEN_MAP.get(val, val))
    return None


# --- master text styles -> type scale ---------------------------------------


def _extract_master_text_styles(master) -> dict[str, Any]:
    styles: dict[str, Any] = {}
    tx_styles = master.find("p:txStyles", NS)
    if tx_styles is None:
        return styles
    for style_name in ("titleStyle", "bodyStyle", "otherStyle"):
        style = tx_styles.find(f"p:{style_name}", NS)
        if style is None:
            continue
        def_rpr = style.find("a:lvl1pPr/a:defRPr", NS)
        if def_rpr is None:
            continue
        entry: dict[str, Any] = {}
        if def_rpr.get("sz"):
            entry["size"] = int(def_rpr.get("sz")) / 100.0
        if def_rpr.get("b") is not None:
            entry["bold"] = def_rpr.get("b") == "1"
        latin = def_rpr.find("a:latin", NS)
        if latin is not None and latin.get("typeface"):
            entry["font"] = latin.get("typeface")
        if entry:
            styles[style_name] = entry
    return styles


def _derive_type_scale(master_text_styles: dict[str, Any]) -> dict[str, dict]:
    """Extract title/body sizes exactly; rescale the other roles proportionally.

    Merging an extracted 20pt title into the default scale would leave the
    default 24pt heading above it — an inverted hierarchy. heading/subheading
    interpolate between body and title at the same relative position they
    occupy in the default scale; bodySmall/caption keep their default ratio to
    body; minSize keeps each role's default minSize/size ratio (spec rule).
    """
    default_scale = REFERENCE["default_theme"]["typeScale"]
    title_size = master_text_styles.get("titleStyle", {}).get("size")
    body_size = master_text_styles.get("bodyStyle", {}).get("size")
    if title_size is None or body_size is None or title_size <= body_size:
        return {}

    d_title = float(default_scale["title"]["size"])
    d_body = float(default_scale["body"]["size"])

    def _round_half(value: float) -> float:
        return round(value * 2) / 2

    scale: dict[str, dict] = {}
    for role, bundle in default_scale.items():
        d_size = float(bundle["size"])
        if role == "title":
            size, provenance = float(title_size), "extracted"
        elif role == "body":
            size, provenance = float(body_size), "extracted"
        elif d_size > d_body:  # heading/subheading: between body and title
            position = (d_size - d_body) / (d_title - d_body)
            size = _round_half(body_size + position * (title_size - body_size))
            provenance = "derived"
        else:  # bodySmall/caption: keep ratio to body
            size = _round_half(body_size * d_size / d_body)
            provenance = "derived"
        entry: dict[str, Any] = {"size": size, "provenance": provenance}
        if "minSize" in bundle:
            entry["minSize"] = _round_half(size * float(bundle["minSize"]) / d_size)
        declared_bold = None
        if role == "title":
            declared_bold = master_text_styles.get("titleStyle", {}).get("bold")
        elif role == "body":
            declared_bold = master_text_styles.get("bodyStyle", {}).get("bold")
        if declared_bold is not None:
            entry["weight"] = "bold" if declared_bold else "normal"
        scale[role] = entry
    return scale
