import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from builders.common import REFERENCE
from builders.deck_builder import build_deck
from builders.shape_emitters import (
    SlideState,
    emit_autoshape,
    emit_image,
    emit_placeholder_text,
    emit_text_box,
)
from builders.slide_builder import SlideBuilder
from builders.zip_assembler import ZIPAssembler
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import NSMAP, qn
from tests.pptx_test_utils import CT_NS, REL_NS, build_core_parts, parse_xml


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00"
    b"\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def rels_for(registry: RelationshipRegistry, part_path: str):
    return parse_xml(registry.render(part_path)).findall("rel:Relationship", REL_NS)


def c_nv_pr_ids(root: etree._Element) -> list[str]:
    return [
        c_nv_pr.get("id")
        for c_nv_pr in root.findall(".//p:cNvPr", NSMAP)
        if c_nv_pr.get("id")
    ]


def z_order_names(root: etree._Element) -> list[str]:
    sp_tree = root.find("p:cSld/p:spTree", NSMAP)
    names = []
    for child in list(sp_tree)[2:]:
        c_nv_pr = child.find("p:nvSpPr/p:cNvPr", NSMAP)
        if c_nv_pr is None:
            c_nv_pr = child.find("p:nvPicPr/p:cNvPr", NSMAP)
        names.append(c_nv_pr.get("name"))
    return names


class ShapeEmitterTests(unittest.TestCase):
    def test_placeholder_without_geometry_omits_xfrm(self):
        state = SlideState("ppt/slides/slide1.xml")

        shape = emit_placeholder_text(
            {
                "idx": 0,
                "placeholder_type": "ctrTitle",
                "name": "Title Placeholder",
                "text": "Inherited Title",
            },
            state,
        )

        self.assertEqual(shape.tag, qn("p", "sp"))
        self.assertEqual(shape.find("p:nvSpPr/p:cNvPr", NSMAP).get("id"), "2")
        ph = shape.find("p:nvSpPr/p:nvPr/p:ph", NSMAP)
        self.assertEqual(ph.get("idx"), "0")
        self.assertEqual(ph.get("type"), "ctrTitle")
        self.assertIsNone(shape.find("p:spPr/a:xfrm", NSMAP))
        self.assertEqual(shape.find(".//a:t", NSMAP).text, "Inherited Title")

    def test_placeholder_with_explicit_geometry_emits_xfrm_only_then(self):
        state = SlideState("ppt/slides/slide1.xml")

        shape = emit_placeholder_text(
            {
                "idx": 1,
                "placeholder_type": "subTitle",
                "x": "1in",
                "y": "0.5in",
                "w": "4in",
                "h": "1in",
                "text": "Subtitle",
            },
            state,
        )

        off = shape.find("p:spPr/a:xfrm/a:off", NSMAP)
        ext = shape.find("p:spPr/a:xfrm/a:ext", NSMAP)
        self.assertEqual(off.get("x"), "914400")
        self.assertEqual(off.get("y"), "457200")
        self.assertEqual(ext.get("cx"), "3657600")
        self.assertEqual(ext.get("cy"), "914400")

    def test_text_box_is_self_contained_and_assigns_id(self):
        state = SlideState("ppt/slides/slide1.xml")

        shape = emit_text_box(
            {
                "name": "Body Text Box",
                "x": "1in",
                "y": "2in",
                "w": "3in",
                "h": "1in",
                "text": "Box",
            },
            state,
        )

        self.assertEqual(shape.tag, qn("p", "sp"))
        self.assertEqual(shape.find("p:nvSpPr/p:cNvPr", NSMAP).get("id"), "2")
        self.assertEqual(shape.find("p:nvSpPr/p:cNvSpPr", NSMAP).get("txBox"), "1")
        self.assertIsNotNone(shape.find("p:spPr/a:xfrm", NSMAP))
        self.assertEqual(shape.find("p:spPr/a:prstGeom", NSMAP).get("prst"), "rect")
        self.assertIsNotNone(shape.find("p:spPr/a:noFill", NSMAP))
        self.assertIsNotNone(shape.find("p:spPr/a:ln/a:noFill", NSMAP))

    def test_autoshape_uses_preset_fill_line_and_optional_text(self):
        state = SlideState("ppt/slides/slide1.xml")

        shape = emit_autoshape(
            {
                "name": "Accent Rectangle",
                "x": "1in",
                "y": "1in",
                "w": "2in",
                "h": "1in",
                "preset": "roundRect",
                "fill": "accent1",
                "line": False,
                "text": "Accent",
            },
            state,
        )

        self.assertEqual(shape.find("p:spPr/a:prstGeom", NSMAP).get("prst"), "roundRect")
        self.assertEqual(
            shape.find("p:spPr/a:solidFill/a:schemeClr", NSMAP).get("val"),
            "accent1",
        )
        self.assertIsNotNone(shape.find("p:spPr/a:ln/a:noFill", NSMAP))
        self.assertEqual(shape.find(".//a:t", NSMAP).text, "Accent")

    def test_image_registers_media_relationship_and_content_type(self):
        content_types = ContentTypeRegistry()
        relationships = RelationshipRegistry()

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "logo.png"
            source.write_bytes(PNG_BYTES)
            state = SlideState("ppt/slides/slide1.xml")

            pic = emit_image(
                {
                    "name": "Logo",
                    "src": str(source),
                    "x": "1in",
                    "y": "1in",
                    "w": "1in",
                    "h": "1in",
                },
                state,
                relationships,
                content_types,
            )

        self.assertEqual(pic.tag, qn("p", "pic"))
        self.assertEqual(pic.find("p:nvPicPr/p:cNvPr", NSMAP).get("id"), "2")
        self.assertEqual(
            pic.find("p:blipFill/a:blip", NSMAP).get(qn("r", "embed")),
            "rId1",
        )
        self.assertEqual(state.media_parts["ppt/media/image1.png"], PNG_BYTES)
        self.assertEqual(content_types._defaults["png"], "image/png")

        rel = rels_for(relationships, "ppt/slides/slide1.xml")[0]
        self.assertEqual(rel.get("Type"), RelationshipRegistry.IMAGE)
        self.assertEqual(rel.get("Target"), "../media/image1.png")


class SlideBuilderTests(unittest.TestCase):
    def test_slide_builder_emits_required_tree_relationships_ids_and_z_order(self):
        content_types = ContentTypeRegistry()
        relationships = RelationshipRegistry()
        slide_data = {
            "index": 1,
            "layout": "titleBody",
            "name": "Content",
            "shapes": [
                {
                    "type": "placeholder_text",
                    "idx": 0,
                    "placeholder_type": "title",
                    "name": "Title Placeholder",
                    "text": "Title",
                },
                {
                    "type": "text_box",
                    "name": "Body Text Box",
                    "x": "1in",
                    "y": "2in",
                    "w": "3in",
                    "h": "1in",
                    "text": "Body",
                },
                {
                    "type": "autoshape",
                    "name": "Accent Rectangle",
                    "x": "5in",
                    "y": "2in",
                    "w": "2in",
                    "h": "1in",
                    "fill": "accent1",
                    "line": False,
                },
            ],
        }

        xml = SlideBuilder(content_types, relationships).build(slide_data)
        root = parse_xml(xml)

        self.assertEqual(root.tag, qn("p", "sld"))
        self.assertEqual([child.tag for child in root], [qn("p", "cSld"), qn("p", "clrMapOvr")])
        self.assertIsNotNone(root.find("p:clrMapOvr/a:masterClrMapping", NSMAP))
        self.assertEqual(root.find("p:cSld/p:spTree/p:nvGrpSpPr/p:cNvPr", NSMAP).get("id"), "1")

        ids = c_nv_pr_ids(root)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, ["1", "2", "3", "4"])
        self.assertEqual(
            z_order_names(root),
            ["Title Placeholder", "Body Text Box", "Accent Rectangle"],
        )
        placeholder = root.xpath(
            "p:cSld/p:spTree/p:sp[p:nvSpPr/p:nvPr/p:ph]",
            namespaces=NSMAP,
        )[0]
        self.assertIsNone(placeholder.find("p:spPr/a:xfrm", NSMAP))

        rel = rels_for(relationships, "ppt/slides/slide1.xml")[0]
        self.assertEqual(rel.get("Type"), RelationshipRegistry.SLIDE_LAYOUT)
        self.assertEqual(rel.get("Target"), "../slideLayouts/slideLayout2.xml")
        self.assertEqual(
            content_types.overrides["ppt/slides/slide1.xml"],
            ContentTypeRegistry.SLIDE,
        )


class ZIPAssemblerTests(unittest.TestCase):
    def test_assembler_writes_rels_shell_parts_and_content_types_last(self):
        graph = build_core_parts(synthetic_slide_count=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "assembled.pptx"
            ZIPAssembler(
                graph["content_types"],
                graph["relationships"],
            ).assemble(output_path, graph["parts"])

            with ZipFile(output_path) as pptx:
                names = pptx.namelist()
                self.assertEqual(names[-1], "[Content_Types].xml")
                self.assertIn("_rels/.rels", names)
                self.assertIn("ppt/presProps.xml", names)
                self.assertIn("ppt/viewProps.xml", names)
                self.assertIn("ppt/tableStyles.xml", names)
                self.assertFalse(any(name.endswith("/") for name in names))

                content_types = parse_xml(pptx.read("[Content_Types].xml").decode("utf-8"))
                for part_name in (
                    "/ppt/presProps.xml",
                    "/ppt/viewProps.xml",
                    "/ppt/tableStyles.xml",
                ):
                    self.assertIsNotNone(
                        content_types.find(f'ct:Override[@PartName="{part_name}"]', CT_NS)
                    )

                package_rels = parse_xml(pptx.read("_rels/.rels").decode("utf-8"))
                office_rels = package_rels.findall("rel:Relationship", REL_NS)
                self.assertEqual(office_rels[0].get("Target"), "ppt/presentation.xml")

                presentation_rels = parse_xml(
                    pptx.read("ppt/_rels/presentation.xml.rels").decode("utf-8")
                )
                rel_types = {
                    rel.get("Type")
                    for rel in presentation_rels.findall("rel:Relationship", REL_NS)
                }
                self.assertIn(RelationshipRegistry.PRES_PROPS, rel_types)
                self.assertIn(RelationshipRegistry.VIEW_PROPS, rel_types)
                self.assertIn(RelationshipRegistry.TABLE_STYLES, rel_types)


class EndToEndDeckTests(unittest.TestCase):
    def test_sample_deck_opens_and_preserves_placeholder_inheritance(self):
        try:
            from pptx import Presentation as PptxPresentation
        except ImportError:
            self.fail("python-pptx is required for slide-layer integration tests")

        with tempfile.TemporaryDirectory() as tmpdir:
            graph = build_deck(Path(tmpdir) / "sample_deck.pptx")

            presentation = PptxPresentation(str(graph["output_path"]))
            self.assertEqual(len(presentation.slides), 2)
            self.assertEqual(
                int(presentation.slide_width),
                REFERENCE["slide_sizes"]["16:9"]["cx"],
            )
            self.assertEqual(
                int(presentation.slide_height),
                REFERENCE["slide_sizes"]["16:9"]["cy"],
            )

            title_slide = presentation.slides[0]
            self.assertEqual(title_slide.shapes.title.text, "Quarterly Update")
            placeholder_texts = [shape.text for shape in title_slide.placeholders]
            self.assertIn("Generated by Paro", placeholder_texts)

            content_slide = presentation.slides[1]
            names = [shape.name for shape in content_slide.shapes]
            self.assertIn("Body Text Box", names)
            self.assertIn("Accent Rectangle", names)
            non_placeholder_names = [
                shape.name
                for shape in content_slide.shapes
                if not getattr(shape, "is_placeholder", False)
            ]
            self.assertIn("Body Text Box", non_placeholder_names)
            self.assertIn("Accent Rectangle", non_placeholder_names)

            title_root = parse_xml(graph["parts"]["ppt/slides/slide1.xml"])
            placeholders = title_root.findall("p:cSld/p:spTree/p:sp", NSMAP)
            for placeholder in placeholders:
                self.assertIsNotNone(placeholder.find("p:nvSpPr/p:nvPr/p:ph", NSMAP))
                self.assertIsNone(placeholder.find("p:spPr/a:xfrm", NSMAP))

            expected_orders = {
                "ppt/slides/slide1.xml": ["Title Placeholder", "Subtitle Placeholder"],
                "ppt/slides/slide2.xml": [
                    "Content Title Placeholder",
                    "Body Text Box",
                    "Accent Rectangle",
                ],
            }
            for slide_path, expected_order in expected_orders.items():
                with self.subTest(slide=slide_path):
                    root = parse_xml(graph["parts"][slide_path])
                    ids = c_nv_pr_ids(root)
                    self.assertEqual(len(ids), len(set(ids)))
                    self.assertEqual(z_order_names(root), expected_order)


if __name__ == "__main__":
    unittest.main()
