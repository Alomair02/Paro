import posixpath
import unittest

from builders import LAYOUT_DEFINITIONS
from builders.common import package_path
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import qn
from tests.pptx_test_utils import (
    CT_NS,
    REL_NS,
    build_core_parts,
    parse_xml,
    relationship_entries,
)


def resolve_target(source_part_path: str, target: str) -> str:
    if source_part_path == RelationshipRegistry.PACKAGE_ROOT:
        return posixpath.normpath(target)
    return posixpath.normpath(
        posixpath.join(posixpath.dirname(source_part_path), target)
    )


def referenced_rids(root):
    rid_attr = qn("r", "id")
    return [element.get(rid_attr) for element in root.iter() if element.get(rid_attr)]


class CrossComponentInvariantTests(unittest.TestCase):
    def setUp(self):
        self.graph = build_core_parts(synthetic_slide_count=2)
        self.parts = self.graph["parts"]
        self.content_types = self.graph["content_types"]
        self.relationships = self.graph["relationships"]

    def test_all_referenced_rids_have_matching_relationships(self):
        for part_path, xml in self.parts.items():
            with self.subTest(part=part_path):
                rid_refs = referenced_rids(parse_xml(xml))
                rel_ids = {
                    rel.get("Id")
                    for rel in relationship_entries(self.relationships, part_path)
                }

                for rid in rid_refs:
                    self.assertIn(rid, rel_ids)

    def test_relationship_targets_are_source_relative_and_resolve(self):
        for source_part_path in self.relationships.registry:
            for rel in relationship_entries(self.relationships, source_part_path):
                with self.subTest(source=source_part_path, rid=rel.get("Id")):
                    target = rel.get("Target")
                    self.assertFalse(target.startswith("/"))

                    if rel.get("TargetMode") == "External":
                        continue

                    if source_part_path != RelationshipRegistry.PACKAGE_ROOT:
                        self.assertFalse(target.startswith("ppt/"))

                    resolved = resolve_target(source_part_path, target)
                    self.assertIn(resolved, self.parts)

    def test_no_duplicate_rids_within_single_rels_part(self):
        for source_part_path in self.relationships.registry:
            with self.subTest(source=source_part_path):
                rel_ids = [
                    rel.get("Id")
                    for rel in relationship_entries(self.relationships, source_part_path)
                ]
                self.assertEqual(len(rel_ids), len(set(rel_ids)))

    def test_every_created_part_has_content_type_override(self):
        for part_path in self.parts:
            with self.subTest(part=part_path):
                self.assertIn(part_path, self.content_types.overrides)

    def test_content_type_manifest_has_no_duplicate_overrides(self):
        content_types_root = parse_xml(self.content_types.render())
        override_part_names = [
            override.get("PartName")
            for override in content_types_root.findall("ct:Override", CT_NS)
        ]

        self.assertEqual(len(override_part_names), len(set(override_part_names)))

    def test_slide_ids_are_unique_across_deck(self):
        presentation_root = parse_xml(self.parts[package_path("presentation")])
        slide_ids = [
            slide_id.get("id")
            for slide_id in presentation_root.findall("p:sldIdLst/p:sldId", {
                "p": "http://schemas.openxmlformats.org/presentationml/2006/main"
            })
        ]

        self.assertEqual(len(slide_ids), len(set(slide_ids)))
        for slide_id in slide_ids:
            self.assertGreaterEqual(int(slide_id), 256)

    def test_layout_to_master_and_slide_to_layout_chains_resolve(self):
        master_path = package_path("slideMaster", 1)
        layout_paths = {
            layout_def["part_path"] for layout_def in LAYOUT_DEFINITIONS.values()
        }

        for layout_path in layout_paths:
            with self.subTest(layout=layout_path):
                layout_rels = relationship_entries(self.relationships, layout_path)
                master_rels = [
                    rel
                    for rel in layout_rels
                    if rel.get("Type") == RelationshipRegistry.SLIDE_MASTER
                ]
                self.assertEqual(len(master_rels), 1)
                self.assertEqual(
                    resolve_target(layout_path, master_rels[0].get("Target")),
                    master_path,
                )

        for slide_path in self.graph["slide_paths"]:
            with self.subTest(slide=slide_path):
                slide_rels = relationship_entries(self.relationships, slide_path)
                layout_rels = [
                    rel
                    for rel in slide_rels
                    if rel.get("Type") == RelationshipRegistry.SLIDE_LAYOUT
                ]
                self.assertEqual(len(layout_rels), 1)
                self.assertIn(
                    resolve_target(slide_path, layout_rels[0].get("Target")),
                    layout_paths,
                )

    def test_relationship_renders_parse_with_package_namespace(self):
        for source_part_path in self.relationships.registry:
            with self.subTest(source=source_part_path):
                rels_root = parse_xml(self.relationships.render(source_part_path))
                self.assertEqual(
                    rels_root.nsmap[None],
                    "http://schemas.openxmlformats.org/package/2006/relationships",
                )
                self.assertEqual(
                    len(rels_root.findall("rel:Relationship", REL_NS)),
                    len(self.relationships.registry[source_part_path]),
                )

    def test_synthetic_slide_parts_use_slide_content_type(self):
        for slide_path in self.graph["slide_paths"]:
            with self.subTest(slide=slide_path):
                self.assertEqual(
                    self.content_types.overrides[slide_path],
                    ContentTypeRegistry.SLIDE,
                )


if __name__ == "__main__":
    unittest.main()
