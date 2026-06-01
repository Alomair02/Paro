import zipfile
from pathlib import Path

from lxml import etree

from builders import (
    LAYOUT_DEFINITIONS,
    LayoutBuilder,
    MasterBuilder,
    PresentationBuilder,
    ThemeBuilder,
)
from builders.common import make_root, make_sp_tree, package_path, relationship_target
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import qn, to_xml_string


REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
CT_NS = {"ct": "http://schemas.openxmlformats.org/package/2006/content-types"}


def parse_xml(xml_string: str) -> etree._Element:
    return etree.fromstring(xml_string.encode("utf-8"))


def canonical_xml(xml_string: str) -> str:
    root = parse_xml(xml_string)
    return etree.tostring(
        root,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    ).decode("UTF-8")


def sample_theme() -> dict:
    return {
        "name": "Paro",
        "colors": {
            "dk1": "000000",
            "lt1": "FFFFFF",
            "dk2": "1F2937",
            "lt2": "F8FAFC",
            "accent1": "2563EB",
            "accent2": "16A34A",
            "accent3": "DC2626",
            "accent4": "9333EA",
            "accent5": "EA580C",
            "accent6": "0891B2",
            "hlink": "0000FF",
            "folHlink": "800080",
        },
        "fonts": {
            "heading": "Aptos Display",
            "body": "Aptos",
        },
    }


def make_minimal_slide_xml() -> str:
    root = make_root("p", "sld")

    c_sld = etree.SubElement(root, qn("p", "cSld"))
    c_sld.append(make_sp_tree())

    clr_map_ovr = etree.SubElement(root, qn("p", "clrMapOvr"))
    etree.SubElement(clr_map_ovr, qn("a", "masterClrMapping"))

    return to_xml_string(root)


def build_core_parts(synthetic_slide_count: int = 0) -> dict:
    content_types = ContentTypeRegistry()
    relationships = RelationshipRegistry()
    parts = {}

    theme_path = package_path("theme", 1)
    parts[theme_path] = ThemeBuilder(content_types, relationships).build(
        sample_theme(),
        part_path=theme_path,
    )

    layout_builder = LayoutBuilder(content_types, relationships)
    for layout_name, layout_def in LAYOUT_DEFINITIONS.items():
        parts[layout_def["part_path"]] = layout_builder.build(layout_name)

    master_path = package_path("slideMaster", 1)
    layout_records = LayoutBuilder.default_layout_records()
    parts[master_path] = MasterBuilder(content_types, relationships).build(
        layout_records,
        part_path=master_path,
        theme_part_path=theme_path,
    )

    slide_paths = []
    default_layout_path = LAYOUT_DEFINITIONS["titleBody"]["part_path"]
    for index in range(1, synthetic_slide_count + 1):
        slide_path = package_path("slide", index)
        parts[slide_path] = make_minimal_slide_xml()
        content_types.add_override(slide_path, ContentTypeRegistry.SLIDE)
        relationships.add(
            slide_path,
            relationship_target(slide_path, default_layout_path),
            RelationshipRegistry.SLIDE_LAYOUT,
        )
        slide_paths.append(slide_path)

    presentation_path = package_path("presentation")
    parts[presentation_path] = PresentationBuilder(content_types, relationships).build(
        slide_paths,
        part_path=presentation_path,
        master_part_path=master_path,
    )

    return {
        "parts": parts,
        "content_types": content_types,
        "relationships": relationships,
        "slide_paths": slide_paths,
        "layout_records": layout_records,
    }


def relationship_entries(
    relationships: RelationshipRegistry,
    part_path: str,
) -> list[etree._Element]:
    rels_xml = relationships.render(part_path)
    if not rels_xml:
        return []
    return parse_xml(rels_xml).findall("rel:Relationship", REL_NS)


def write_pptx_package(package_path: Path, graph: dict):
    parts = graph["parts"]
    content_types = graph["content_types"]
    relationships = graph["relationships"]

    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as pptx:
        pptx.writestr("[Content_Types].xml", content_types.render())

        for source_part_path in relationships.registry:
            rels_xml = relationships.render(source_part_path)
            if rels_xml:
                pptx.writestr(RelationshipRegistry.rels_path(source_part_path), rels_xml)

        for part_path, xml in parts.items():
            pptx.writestr(part_path, xml)
