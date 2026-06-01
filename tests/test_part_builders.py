import unittest

from lxml import etree

from builders import (
    LAYOUT_DEFINITIONS,
    LayoutBuilder,
    MasterBuilder,
    PresentationBuilder,
    ThemeBuilder,
)
from builders.common import REFERENCE
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import NSMAP, qn


REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
CT_NS = {"ct": "http://schemas.openxmlformats.org/package/2006/content-types"}


def parse_xml(xml_string: str) -> etree._Element:
    return etree.fromstring(xml_string.encode("utf-8"))


def parse_relationships(registry: RelationshipRegistry, part_path: str):
    return parse_xml(registry.render(part_path)).findall("rel:Relationship", REL_NS)


def parse_content_types(registry: ContentTypeRegistry) -> etree._Element:
    return parse_xml(registry.render())


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


class ThemeBuilderTests(unittest.TestCase):
    def test_theme_tree_order_colors_fonts_and_content_type(self):
        content_types = ContentTypeRegistry()
        relationships = RelationshipRegistry()

        xml = ThemeBuilder(content_types, relationships).build(sample_theme())
        root = parse_xml(xml)

        self.assertEqual(root.tag, qn("a", "theme"))
        self.assertEqual(root.nsmap["a"], NSMAP["a"])
        self.assertEqual(root.get("name"), "Paro")

        theme_elements = root.find("a:themeElements", NSMAP)
        self.assertIsNotNone(theme_elements)
        self.assertEqual(
            [child.tag for child in theme_elements],
            [qn("a", "clrScheme"), qn("a", "fontScheme"), qn("a", "fmtScheme")],
        )

        clr_scheme = theme_elements.find("a:clrScheme", NSMAP)
        color_slots = [child.tag.rsplit("}", 1)[1] for child in clr_scheme]
        self.assertEqual(color_slots, REFERENCE["color_scheme_slots"]["order"])

        self.assertIsNotNone(clr_scheme.find("a:dk1/a:sysClr", NSMAP))
        self.assertIsNotNone(clr_scheme.find("a:lt1/a:sysClr", NSMAP))
        self.assertIsNotNone(clr_scheme.find("a:accent1/a:srgbClr", NSMAP))
        self.assertEqual(
            clr_scheme.find("a:dk1/a:sysClr", NSMAP).get("val"),
            "windowText",
        )
        self.assertEqual(
            clr_scheme.find("a:lt1/a:sysClr", NSMAP).get("val"),
            "window",
        )

        major_font = theme_elements.find("a:fontScheme/a:majorFont", NSMAP)
        minor_font = theme_elements.find("a:fontScheme/a:minorFont", NSMAP)
        self.assertEqual(
            [child.tag for child in major_font],
            [qn("a", "latin"), qn("a", "ea"), qn("a", "cs")],
        )
        self.assertEqual(
            [child.tag for child in minor_font],
            [qn("a", "latin"), qn("a", "ea"), qn("a", "cs")],
        )

        fmt_scheme = theme_elements.find("a:fmtScheme", NSMAP)
        fmt_children = [child.tag.rsplit("}", 1)[1] for child in fmt_scheme]
        self.assertEqual(
            fmt_children,
            ["fillStyleLst", "lnStyleLst", "effectStyleLst", "bgFillStyleLst"],
        )
        for child in fmt_scheme:
            self.assertGreater(len(child), 0)

        ct_root = parse_content_types(content_types)
        theme_override = ct_root.find(
            'ct:Override[@PartName="/ppt/theme/theme1.xml"]',
            CT_NS,
        )
        self.assertIsNotNone(theme_override)
        self.assertEqual(
            theme_override.get("ContentType"),
            ContentTypeRegistry.THEME,
        )

    def test_second_theme_custom_part_path_is_valid_and_registered(self):
        content_types = ContentTypeRegistry()
        relationships = RelationshipRegistry()
        builder = ThemeBuilder(content_types, relationships)

        builder.build(sample_theme())

        theme = sample_theme()
        theme["name"] = "Paro Alt"
        theme["colors"]["accent1"] = "#AA00CC"

        xml = builder.build(
            theme,
            part_path="ppt/theme/theme2.xml",
        )
        root = parse_xml(xml)

        self.assertEqual(root.tag, qn("a", "theme"))
        self.assertEqual(root.get("name"), "Paro Alt")
        self.assertEqual(
            root.find("a:themeElements/a:clrScheme/a:accent1/a:srgbClr", NSMAP).get(
                "val"
            ),
            "AA00CC",
        )

        ct_root = parse_content_types(content_types)
        self.assertIsNotNone(
            ct_root.find('ct:Override[@PartName="/ppt/theme/theme1.xml"]', CT_NS)
        )
        self.assertIsNotNone(
            ct_root.find('ct:Override[@PartName="/ppt/theme/theme2.xml"]', CT_NS)
        )


class LayoutBuilderTests(unittest.TestCase):
    def test_default_layouts_emit_placeholders_and_master_relationships(self):
        for layout_name, layout_def in LAYOUT_DEFINITIONS.items():
            with self.subTest(layout=layout_name):
                content_types = ContentTypeRegistry()
                relationships = RelationshipRegistry()

                xml = LayoutBuilder(content_types, relationships).build(layout_name)
                root = parse_xml(xml)

                self.assertEqual(root.tag, qn("p", "sldLayout"))
                self.assertEqual(root.nsmap["p"], NSMAP["p"])
                self.assertEqual(root.get("type"), layout_def["type"])

                sp_tree = root.find("p:cSld/p:spTree", NSMAP)
                placeholders = sp_tree.findall("p:sp", NSMAP)
                self.assertEqual(len(placeholders), len(layout_def["placeholders"]))

                for shape, expected in zip(placeholders, layout_def["placeholders"]):
                    ph = shape.find("p:nvSpPr/p:nvPr/p:ph", NSMAP)
                    self.assertEqual(ph.get("type"), expected["type"])
                    self.assertEqual(ph.get("idx"), str(expected["idx"]))

                    off = shape.find("p:spPr/a:xfrm/a:off", NSMAP)
                    ext = shape.find("p:spPr/a:xfrm/a:ext", NSMAP)
                    self.assertEqual(off.get("x"), str(expected["off"]["x"]))
                    self.assertEqual(off.get("y"), str(expected["off"]["y"]))
                    self.assertEqual(ext.get("cx"), str(expected["ext"]["cx"]))
                    self.assertEqual(ext.get("cy"), str(expected["ext"]["cy"]))

                self.assertIsNotNone(root.find("p:clrMapOvr/a:masterClrMapping", NSMAP))

                rels = parse_relationships(relationships, layout_def["part_path"])
                self.assertEqual(len(rels), 1)
                self.assertEqual(
                    rels[0].get("Type"),
                    RelationshipRegistry.SLIDE_MASTER,
                )
                self.assertEqual(
                    rels[0].get("Target"),
                    "../slideMasters/slideMaster1.xml",
                )

                ct_root = parse_content_types(content_types)
                override = ct_root.find(
                    f'ct:Override[@PartName="/{layout_def["part_path"]}"]',
                    CT_NS,
                )
                self.assertIsNotNone(override)
                self.assertEqual(
                    override.get("ContentType"),
                    ContentTypeRegistry.SLIDE_LAYOUT,
                )


class MasterBuilderTests(unittest.TestCase):
    def test_master_required_children_text_styles_and_relationships(self):
        content_types = ContentTypeRegistry()
        relationships = RelationshipRegistry()
        layouts = LayoutBuilder.default_layout_records()

        xml = MasterBuilder(content_types, relationships).build(layouts)
        root = parse_xml(xml)

        self.assertEqual(root.tag, qn("p", "sldMaster"))
        self.assertEqual(root.nsmap["p"], NSMAP["p"])
        self.assertEqual(
            [child.tag for child in root],
            [
                qn("p", "cSld"),
                qn("p", "clrMap"),
                qn("p", "sldLayoutIdLst"),
                qn("p", "txStyles"),
            ],
        )

        sp_tree = root.find("p:cSld/p:spTree", NSMAP)
        self.assertEqual(len(sp_tree.findall("p:sp", NSMAP)), 2)

        clr_map = root.find("p:clrMap", NSMAP)
        self.assertEqual(len(clr_map.attrib), 12)
        for key, value in REFERENCE["color_map_default"].items():
            if key != "_note":
                self.assertEqual(clr_map.get(key), value)

        layout_ids = root.findall("p:sldLayoutIdLst/p:sldLayoutId", NSMAP)
        self.assertEqual(len(layout_ids), len(layouts))
        for layout_id in layout_ids:
            self.assertIsNotNone(layout_id.get(qn("r", "id")))

        body_levels = root.findall("p:txStyles/p:bodyStyle/*", NSMAP)
        self.assertEqual(
            [level.tag for level in body_levels],
            [qn("a", f"lvl{i}pPr") for i in range(1, 10)],
        )
        self.assertIsNotNone(root.find("p:txStyles/p:titleStyle/a:lvl1pPr", NSMAP))
        self.assertIsNotNone(root.find("p:txStyles/p:otherStyle/a:lvl1pPr", NSMAP))

        rels = parse_relationships(relationships, "ppt/slideMasters/slideMaster1.xml")
        targets_by_type = {}
        for rel in rels:
            targets_by_type.setdefault(rel.get("Type"), []).append(rel.get("Target"))

        self.assertEqual(
            targets_by_type[RelationshipRegistry.SLIDE_LAYOUT],
            [
                "../slideLayouts/slideLayout1.xml",
                "../slideLayouts/slideLayout2.xml",
                "../slideLayouts/slideLayout3.xml",
            ],
        )
        self.assertEqual(
            targets_by_type[RelationshipRegistry.THEME],
            ["../theme/theme1.xml"],
        )

        ct_root = parse_content_types(content_types)
        override = ct_root.find(
            'ct:Override[@PartName="/ppt/slideMasters/slideMaster1.xml"]',
            CT_NS,
        )
        self.assertIsNotNone(override)
        self.assertEqual(override.get("ContentType"), ContentTypeRegistry.SLIDE_MASTER)


class PresentationBuilderTests(unittest.TestCase):
    def test_presentation_lists_master_slides_size_and_relationships(self):
        content_types = ContentTypeRegistry()
        relationships = RelationshipRegistry()
        slides = ["ppt/slides/slide1.xml", "ppt/slides/slide2.xml"]

        xml = PresentationBuilder(content_types, relationships).build(slides)
        root = parse_xml(xml)

        self.assertEqual(root.tag, qn("p", "presentation"))
        self.assertEqual(root.nsmap["p"], NSMAP["p"])
        self.assertEqual(
            [child.tag for child in root],
            [
                qn("p", "sldMasterIdLst"),
                qn("p", "sldIdLst"),
                qn("p", "sldSz"),
                qn("p", "notesSz"),
            ],
        )

        master_id = root.find("p:sldMasterIdLst/p:sldMasterId", NSMAP)
        self.assertEqual(master_id.get("id"), "2147483648")
        self.assertIsNotNone(master_id.get(qn("r", "id")))

        slide_ids = root.findall("p:sldIdLst/p:sldId", NSMAP)
        self.assertEqual([sid.get("id") for sid in slide_ids], ["256", "257"])
        self.assertEqual(len({sid.get("id") for sid in slide_ids}), len(slide_ids))
        for slide_id in slide_ids:
            self.assertIsNotNone(slide_id.get(qn("r", "id")))

        slide_size = root.find("p:sldSz", NSMAP)
        self.assertEqual(slide_size.get("cx"), "12192000")
        self.assertEqual(slide_size.get("cy"), "6858000")
        self.assertEqual(slide_size.get("type"), "screen16x9")

        notes_size = root.find("p:notesSz", NSMAP)
        self.assertEqual(notes_size.get("cx"), "6858000")
        self.assertEqual(notes_size.get("cy"), "9144000")

        package_rels = parse_relationships(
            relationships,
            RelationshipRegistry.PACKAGE_ROOT,
        )
        self.assertEqual(len(package_rels), 1)
        self.assertEqual(package_rels[0].get("Type"), RelationshipRegistry.OFFICE_DOC)
        self.assertEqual(package_rels[0].get("Target"), "ppt/presentation.xml")

        presentation_rels = parse_relationships(relationships, "ppt/presentation.xml")
        targets_by_type = {}
        for rel in presentation_rels:
            targets_by_type.setdefault(rel.get("Type"), []).append(rel.get("Target"))

        self.assertEqual(
            targets_by_type[RelationshipRegistry.SLIDE_MASTER],
            ["slideMasters/slideMaster1.xml"],
        )
        self.assertEqual(
            targets_by_type[RelationshipRegistry.SLIDE],
            ["slides/slide1.xml", "slides/slide2.xml"],
        )

        ct_root = parse_content_types(content_types)
        override = ct_root.find(
            'ct:Override[@PartName="/ppt/presentation.xml"]',
            CT_NS,
        )
        self.assertIsNotNone(override)
        self.assertEqual(override.get("ContentType"), ContentTypeRegistry.PRESENTATION)


if __name__ == "__main__":
    unittest.main()
