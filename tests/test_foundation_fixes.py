import unittest
from xml.etree import ElementTree

from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import (
    CANONICAL_XML_DECLARATION,
    make_gradient_fill,
    make_solid_fill,
    make_text_body,
    qn,
    to_xml_string,
)
from utils.converter import UnitConverter


class RelationshipRegistryTests(unittest.TestCase):
    def test_package_root_rels_path(self):
        self.assertEqual(RelationshipRegistry.rels_path(RelationshipRegistry.PACKAGE_ROOT), "_rels/.rels")
        self.assertEqual(RelationshipRegistry.rels_path(""), "_rels/.rels")

    def test_slide_rels_path(self):
        self.assertEqual(
            RelationshipRegistry.rels_path("ppt/slides/slide1.xml"),
            "ppt/slides/_rels/slide1.xml.rels",
        )

    def test_internal_target_is_preserved_as_source_relative_uri(self):
        registry = RelationshipRegistry()

        registry.add(
            "ppt/slides/slide1.xml",
            "../slideLayouts/slideLayout1.xml",
            RelationshipRegistry.SLIDE_LAYOUT,
        )

        rels_xml = registry.render("ppt/slides/slide1.xml")
        self.assertIn('Target="../slideLayouts/slideLayout1.xml"', rels_xml)
        self.assertNotIn('Target="ppt/slideLayouts/slideLayout1.xml"', rels_xml)

    def test_same_relationship_added_twice_returns_same_rid(self):
        registry = RelationshipRegistry()

        first_rid = registry.add(
            "ppt/slides/slide1.xml",
            "../slideLayouts/slideLayout1.xml",
            RelationshipRegistry.SLIDE_LAYOUT,
        )
        second_rid = registry.add(
            "ppt/slides/slide1.xml",
            "../slideLayouts/slideLayout1.xml",
            RelationshipRegistry.SLIDE_LAYOUT,
        )

        self.assertEqual(first_rid, second_rid)

    def test_external_target_mode_and_url_are_preserved(self):
        registry = RelationshipRegistry()
        target = "https://example.com/page?a=1&b=2"

        registry.add(
            "ppt/slides/slide1.xml",
            target,
            RelationshipRegistry.HYPERLINK,
            target_mode="External",
        )

        rels_xml = registry.render("ppt/slides/slide1.xml")
        self.assertIn('TargetMode="External"', rels_xml)
        self.assertIn("https://example.com/page?a=1&amp;b=2", rels_xml)

        root = ElementTree.fromstring(rels_xml)
        rel = root[0]
        self.assertEqual(rel.attrib["Target"], target)
        self.assertEqual(rel.attrib["TargetMode"], "External")

    def test_duplicate_relationship_identity_includes_target_mode(self):
        registry = RelationshipRegistry()
        target = "https://example.com/page"

        external_rid = registry.add(
            "ppt/slides/slide1.xml",
            target,
            RelationshipRegistry.HYPERLINK,
            target_mode="External",
        )
        duplicate_external_rid = registry.add(
            "ppt/slides/slide1.xml",
            target,
            RelationshipRegistry.HYPERLINK,
            target_mode="External",
        )
        internal_rid = registry.add(
            "ppt/slides/slide1.xml",
            target,
            RelationshipRegistry.HYPERLINK,
        )

        self.assertEqual(external_rid, duplicate_external_rid)
        self.assertNotEqual(external_rid, internal_rid)

    def test_target_with_ampersand_renders_as_valid_xml(self):
        registry = RelationshipRegistry()
        target = "https://example.com/page?a=1&b=2"

        registry.add(
            "ppt/slides/slide1.xml",
            target,
            RelationshipRegistry.HYPERLINK,
            target_mode="External",
        )

        root = ElementTree.fromstring(registry.render("ppt/slides/slide1.xml"))
        self.assertEqual(root[0].attrib["Target"], target)


class ContentTypeRegistryTests(unittest.TestCase):
    def test_add_default_strips_leading_dot(self):
        registry = ContentTypeRegistry()

        registry.add_default(".png", "image/png")

        content_types_xml = registry.render()
        self.assertIn('Extension="png"', content_types_xml)
        self.assertNotIn('Extension=".png"', content_types_xml)


class XmlBuilderTests(unittest.TestCase):
    def test_to_xml_string_uses_canonical_xml_declaration(self):
        xml = to_xml_string(make_solid_fill("accent1"))

        self.assertEqual(xml.splitlines()[0], CANONICAL_XML_DECLARATION)

    def test_empty_text_body_gets_empty_paragraph(self):
        txbody = make_text_body([])

        paragraphs = txbody.findall(qn("a", "p"))
        self.assertEqual(len(paragraphs), 1)
        self.assertEqual(len(paragraphs[0]), 1)
        self.assertEqual(paragraphs[0][0].tag, qn("a", "pPr"))

    def test_none_text_body_gets_empty_paragraph(self):
        txbody = make_text_body(None)

        paragraphs = txbody.findall(qn("a", "p"))
        self.assertEqual(len(paragraphs), 1)

    def test_solid_fill_uses_scheme_color_for_scheme_token(self):
        fill = make_solid_fill("accent1")

        self.assertIsNotNone(fill.find(qn("a", "schemeClr")))
        self.assertIsNone(fill.find(qn("a", "srgbClr")))

    def test_solid_fill_uses_srgb_color_for_hex(self):
        fill = make_solid_fill("#ff0000")

        srgb = fill.find(qn("a", "srgbClr"))
        self.assertIsNotNone(srgb)
        self.assertEqual(srgb.get("val"), "FF0000")

    def test_luminance_transforms_must_be_ooxml_percentages(self):
        with self.assertRaisesRegex(ValueError, "lumMod"):
            make_solid_fill("accent1", {"lumMod": 100001})
        with self.assertRaisesRegex(ValueError, "lumOff"):
            make_gradient_fill("accent1", {"lumMod": 100000, "lumOff": -1}, {"lumMod": 82000})

        fill = make_gradient_fill("accent1", {"lumMod": 100000, "lumOff": 18000}, {"lumMod": 82000})
        values = [
            int(node.get("val"))
            for transform in ("lumMod", "lumOff")
            for node in fill.findall(f".//{qn('a', transform)}")
        ]
        self.assertTrue(values)
        self.assertLessEqual(max(values), 100000)


class UnitConverterTests(unittest.TestCase):
    def test_to_emu_parses_decimal_inches(self):
        self.assertEqual(UnitConverter.to_emu("1.5in"), 1371600)

    def test_to_emu_handles_negative_values(self):
        self.assertEqual(UnitConverter.to_emu("-2pt"), -25400)

    def test_to_emu_accepts_bare_number_with_explicit_unit(self):
        self.assertEqual(UnitConverter.to_emu(2, "cm"), 720000)

    def test_to_emu_rejects_unknown_unit(self):
        with self.assertRaises(ValueError):
            UnitConverter.to_emu("10furlong")

    def test_degrees_to_ooxml_angle(self):
        self.assertEqual(UnitConverter.degrees_to_ooxml_angle(90), 5400000)
        self.assertEqual(UnitConverter.degrees_to_ooxml_angle(0.5), 30000)


if __name__ == "__main__":
    unittest.main()
