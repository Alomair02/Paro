"""Shared helpers for OOXML part builders."""

import json
import posixpath
from pathlib import Path

from lxml import etree

from core.relationship_reg import RelationshipRegistry
from core.xml_builder import (
    NSMAP,
    make_ln,
    make_no_fill,
    make_prst_geom,
    make_text_body,
    make_xfrm,
    qn,
)


REFERENCE = json.loads(
    (Path(__file__).resolve().parent.parent / "ENGINE_REFERENCE.json").read_text(
        encoding="utf-8"
    )
)


def package_path(template_key: str, n: int | None = None) -> str:
    """Return a canonical package path from ENGINE_REFERENCE.json."""
    path = REFERENCE["package_layout"][template_key]
    if n is not None:
        path = path.replace("{N}", str(n))
    return path


def normalize_package_path(path: str) -> str:
    """Normalize a package part path without making relationship targets absolute."""
    if path == RelationshipRegistry.PACKAGE_ROOT:
        return RelationshipRegistry.PACKAGE_ROOT
    return posixpath.normpath(path.replace("\\", "/")).lstrip("/")


def relationship_target(source_part_path: str, target_part_path: str) -> str:
    """Return target_part_path as a source-relative OPC relationship target."""
    source = normalize_package_path(source_part_path)
    target = normalize_package_path(target_part_path)
    if source == RelationshipRegistry.PACKAGE_ROOT:
        return target

    source_dir = posixpath.dirname(source) or "."
    return posixpath.relpath(target, start=source_dir).replace("\\", "/")


def clean_hex(value: str) -> str:
    """Normalize a theme RGB value for OOXML attributes."""
    return str(value).lstrip("#").upper()


def make_root(prefix: str, local: str) -> etree._Element:
    """Create a part root with all supported namespaces declared once."""
    return etree.Element(qn(prefix, local), nsmap=NSMAP)


def make_sp_tree() -> etree._Element:
    """Build the required p:spTree group shape scaffold."""
    sp_tree = etree.Element(qn("p", "spTree"))

    nv_grp_sp_pr = etree.SubElement(sp_tree, qn("p", "nvGrpSpPr"))
    c_nv_pr = etree.SubElement(nv_grp_sp_pr, qn("p", "cNvPr"))
    c_nv_pr.set("id", str(REFERENCE["constraints"]["shape_id_group_tree"]))
    c_nv_pr.set("name", "")
    etree.SubElement(nv_grp_sp_pr, qn("p", "cNvGrpSpPr"))
    etree.SubElement(nv_grp_sp_pr, qn("p", "nvPr"))

    grp_sp_pr = etree.SubElement(sp_tree, qn("p", "grpSpPr"))
    xfrm = etree.SubElement(grp_sp_pr, qn("a", "xfrm"))
    off = etree.SubElement(xfrm, qn("a", "off"))
    off.set("x", "0")
    off.set("y", "0")
    ext = etree.SubElement(xfrm, qn("a", "ext"))
    ext.set("cx", "0")
    ext.set("cy", "0")
    ch_off = etree.SubElement(xfrm, qn("a", "chOff"))
    ch_off.set("x", "0")
    ch_off.set("y", "0")
    ch_ext = etree.SubElement(xfrm, qn("a", "chExt"))
    ch_ext.set("cx", "0")
    ch_ext.set("cy", "0")

    return sp_tree


def make_placeholder_shape(
    placeholder: dict,
    shape_id: int,
    name_prefix: str = "Placeholder",
) -> etree._Element:
    """Build a placeholder p:sp with geometry and an empty text body."""
    ph_type = placeholder["type"]
    idx = str(placeholder["idx"])

    sp = etree.Element(qn("p", "sp"))

    nv_sp_pr = etree.SubElement(sp, qn("p", "nvSpPr"))
    c_nv_pr = etree.SubElement(nv_sp_pr, qn("p", "cNvPr"))
    c_nv_pr.set("id", str(shape_id))
    c_nv_pr.set("name", f"{name_prefix} {idx}")

    c_nv_sp_pr = etree.SubElement(nv_sp_pr, qn("p", "cNvSpPr"))
    sp_locks = etree.SubElement(c_nv_sp_pr, qn("a", "spLocks"))
    sp_locks.set("noGrp", "1")

    nv_pr = etree.SubElement(nv_sp_pr, qn("p", "nvPr"))
    ph = etree.SubElement(nv_pr, qn("p", "ph"))
    ph.set("type", ph_type)
    ph.set("idx", idx)

    sp_pr = etree.SubElement(sp, qn("p", "spPr"))
    sp_pr.append(
        make_xfrm(
            placeholder["off"]["x"],
            placeholder["off"]["y"],
            placeholder["ext"]["cx"],
            placeholder["ext"]["cy"],
        )
    )
    sp_pr.append(make_prst_geom("rect"))
    sp_pr.append(make_no_fill())
    sp_pr.append(make_ln(0))

    sp.append(make_text_body([]))
    return sp
