"""Template layout transplant: carry a template's designed master/layouts verbatim.

Theme ingestion (theme_extractor) consumes *declared theming* — colors, fonts,
type scale. This module closes the gap it left: placeholder-based slides used
to resolve against Paro's generic layouts, so a cover on an ingested theme came
out plain. The transplant captures the template's slideMaster, slideLayouts,
theme part, their relationship files and referenced media VERBATIM, plus a
parsed placeholder inventory so the resolver can lay text into the template's
real placeholder geometry.

Lossless by construction: parts are copied byte-for-byte under their original
package paths, so every internal relationship stays valid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from lxml import etree

from ingestion.theme_extractor import ThemeExtractionError

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

# Placeholder types that carry chrome, not content — ignored when classifying
# a layout against Paro's DSL layout names.
CHROME_PH_TYPES = {"dt", "ftr", "sldNum"}


def extract_layout_transplant(pptx_path: str | Path) -> dict[str, Any]:
    """Extract the transplant: raw parts + placeholder inventory + DSL name map."""
    pptx_path = Path(pptx_path)
    try:
        with ZipFile(pptx_path) as package:
            return _extract(package)
    except BadZipFile as exc:
        raise ThemeExtractionError(
            f"{pptx_path.name} is not a .pptx/.potx package (not a zip archive)"
        ) from exc


def _extract(package: ZipFile) -> dict[str, Any]:
    names = set(package.namelist())

    presentation_part = _rel_target(package, "", REL_OFFICE_DOCUMENT)
    if presentation_part is None:
        raise ThemeExtractionError("package has no officeDocument relationship")
    presentation = _parse(package, presentation_part)
    master_id = presentation.find("p:sldMasterIdLst/p:sldMasterId", NS)
    if master_id is None:
        raise ThemeExtractionError(f"{presentation_part} declares no slide master")
    master_part = _resolve_rid(package, presentation_part, master_id.get(_qn("r", "id")))
    master_root = _parse(package, master_part)

    theme_part = _rel_target(package, master_part, REL_THEME)
    if theme_part is None:
        raise ThemeExtractionError(f"{master_part} has no theme relationship")

    # Layout order comes from the master's sldLayoutIdLst (template's order).
    layout_parts: list[str] = []
    for layout_id in master_root.findall("p:sldLayoutIdLst/p:sldLayoutId", NS):
        layout_parts.append(_resolve_rid(package, master_part, layout_id.get(_qn("r", "id"))))

    parts: dict[str, bytes] = {}

    def take(part: str):
        if part in names and part not in parts:
            parts[part] = package.read(part)

    for part in (master_part, theme_part, *layout_parts):
        take(part)
        rels = _rels_path(part)
        take(rels)
        # carry every relationship target that is a binary/media dependency
        for target in _all_rel_targets(package, part):
            if target.startswith("ppt/media/") or "/media/" in target:
                take(target)

    master_placeholders = _placeholders(master_root)
    layouts: list[dict[str, Any]] = []
    for layout_part in layout_parts:
        root = _parse(package, layout_part)
        c_sld = root.find("p:cSld", NS)
        layouts.append(
            {
                "part_path": layout_part,
                "name": (c_sld.get("name") if c_sld is not None else None) or layout_part,
                "type": root.get("type", ""),
                "placeholders": _placeholders(root, inherit_from=master_placeholders),
            }
        )

    return {
        "master_part": master_part,
        "theme_part": theme_part,
        "parts": parts,
        "layouts": layouts,
        "name_map": _dsl_name_map(layouts),
    }


def _placeholders(root, inherit_from: list[dict] | None = None) -> list[dict[str, Any]]:
    found = []
    for sp in root.findall(".//p:cSld/p:spTree/p:sp", NS):
        ph = sp.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if ph is None:
            continue
        entry: dict[str, Any] = {
            "idx": int(ph.get("idx", "0")),
            "type": ph.get("type", "body"),
        }
        xfrm = sp.find("p:spPr/a:xfrm", NS)
        if xfrm is not None:
            off = xfrm.find("a:off", NS)
            ext = xfrm.find("a:ext", NS)
            if off is not None and ext is not None:
                entry["off"] = {"x": int(off.get("x")), "y": int(off.get("y"))}
                entry["ext"] = {"cx": int(ext.get("cx")), "cy": int(ext.get("cy"))}
        if "off" not in entry and inherit_from is not None:
            inherited = _inherited_geometry(entry["type"], inherit_from)
            if inherited:
                entry["off"], entry["ext"] = inherited
        if "off" in entry:
            found.append(entry)
    return found


def _inherited_geometry(ph_type: str, master_placeholders: list[dict]):
    """OOXML inheritance: title/dt/ftr/sldNum inherit their own master
    placeholder; every other type falls back to the master body."""
    direct = ph_type if ph_type in {"title", "ctrTitle", "dt", "ftr", "sldNum"} else "body"
    if direct == "ctrTitle":
        direct = "title"
    for candidate in master_placeholders:
        if candidate["type"] == direct and "off" in candidate:
            return candidate["off"], candidate["ext"]
    return None


def _dsl_name_map(layouts: list[dict[str, Any]]) -> dict[str, str]:
    """Map Paro's DSL layout names onto template layouts.

    The layout's designed name is the strongest signal (template authors name
    their covers "Title Slide ..." and their section breaks "Divider ...");
    placeholder signatures are the fallback. First match in template order
    wins each DSL name."""
    name_map: dict[str, str] = {}

    def claim(dsl_name: str, layout: dict):
        name_map.setdefault(dsl_name, layout["part_path"])

    # pass 1: designed-name hints
    cover_parts: set[str] = set()
    for layout in layouts:
        name = (layout["name"] or "").lower()
        if "title slide" in name or "cover" in name:
            claim("title", layout)
            cover_parts.add(layout["part_path"])
        if "divider" in name or "section" in name:
            claim("divider", layout)
            cover_parts.add(layout["part_path"])
        if "title only" in name:
            claim("titleOnly", layout)
        if "blank" in name:
            claim("blank", layout)

    # pass 2: placeholder signatures for whatever names remain unfilled;
    # covers never stand in for content layouts.
    for layout in layouts:
        content = [p for p in layout["placeholders"] if p["type"] not in CHROME_PH_TYPES]
        types = [p["type"] for p in content]
        type_set = set(types)
        already_cover = layout["part_path"] in cover_parts
        if "ctrTitle" in type_set or {"title", "subTitle"} <= type_set:
            claim("title", layout)
        if not type_set:
            claim("blank", layout)
        if type_set == {"title"}:
            claim("titleOnly", layout)
        if "pic" in type_set and not already_cover:
            claim("picture", layout)
        if "title" in type_set and types.count("body") >= 1 and not already_cover:
            claim("titleBody", layout)
        if types.count("body") == 2 and "title" in type_set:
            claim("twoContent", layout)

    return name_map


def transplant_to_registry_layouts(transplant: dict[str, Any]) -> dict[str, dict]:
    """LayoutRegistry injection: DSL names resolve to the template's layouts."""
    by_part = {layout["part_path"]: layout for layout in transplant["layouts"]}
    registry: dict[str, dict] = {}
    for dsl_name, part_path in transplant["name_map"].items():
        layout = by_part[part_path]
        registry[dsl_name] = {
            "name": layout["name"],
            "type": layout["type"] or dsl_name,
            "part_path": part_path,
            "placeholders": [
                {"idx": p["idx"], "type": p["type"], "off": p["off"], "ext": p["ext"]}
                for p in layout["placeholders"]
            ],
        }
    return registry


# --- package traversal (parallel to theme_extractor's helpers) -------------


def _qn(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


def _parse(package: ZipFile, part: str) -> etree._Element:
    try:
        return etree.fromstring(package.read(part))
    except KeyError as exc:
        raise ThemeExtractionError(f"package is missing part {part}") from exc


def _rels_path(part: str) -> str:
    if part == "":
        return "_rels/.rels"
    folder, _, filename = part.rpartition("/")
    return f"{folder}/_rels/{filename}.rels" if folder else f"_rels/{filename}.rels"


def _resolve_target(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    base = Path(base_part).parent
    resolved = (base / target).as_posix()
    pieces: list[str] = []
    for piece in resolved.split("/"):
        if piece == "..":
            pieces.pop()
        elif piece != ".":
            pieces.append(piece)
    return "/".join(pieces)


def _iter_rels(package: ZipFile, part: str):
    rels = _rels_path(part)
    if rels not in package.namelist():
        return
    root = etree.fromstring(package.read(rels))
    yield from root.findall("rel:Relationship", NS)


def _all_rel_targets(package: ZipFile, part: str) -> list[str]:
    return [
        _resolve_target(part, rel.get("Target"))
        for rel in _iter_rels(package, part)
        if rel.get("TargetMode") != "External"
    ]


def _rel_target(package: ZipFile, part: str, rel_type: str) -> str | None:
    for rel in _iter_rels(package, part):
        if rel.get("Type") == rel_type and rel.get("TargetMode") != "External":
            return _resolve_target(part, rel.get("Target"))
    return None


def _resolve_rid(package: ZipFile, part: str, rid: str) -> str:
    for rel in _iter_rels(package, part):
        if rel.get("Id") == rid:
            return _resolve_target(part, rel.get("Target"))
    raise ThemeExtractionError(f"{part} has no relationship {rid}")
