import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from builders.slide_builder import SlideBuilder
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from builders.common import REFERENCE
from transpiler import DSLParser, LayoutRegistry, LayoutResolver, ShapeLibrary, ThemeRegistry, Validator, transpile_deck
from transpiler.validator import TranspileValidationError
from utils.converter import UnitConverter


def parse_resolve(xml: str):
    ast = DSLParser().parse(xml)
    registry = ThemeRegistry(
        {
            ast.inline_theme.name: {
                "name": ast.inline_theme.name,
                "colors": ThemeRegistry().get("default")["colors"],
                "fonts": ThemeRegistry().get("default")["fonts"],
            }
        }
        if ast.inline_theme
        else None
    )
    return LayoutResolver(registry, LayoutRegistry()).resolve(ast)


def shape_by_name(slide_data: dict, name: str):
    return next(shape for shape in slide_data["shapes"] if shape.get("name") == name)


class TranspilerRegistryTests(unittest.TestCase):
    def test_theme_and_layout_registries_resolve_through_get(self):
        theme = ThemeRegistry().get("default")
        layout = LayoutRegistry().get("titleBody")

        self.assertEqual(theme["name"], "default")
        self.assertEqual(set(theme["typeScale"]), set(REFERENCE["default_theme"]["typeScale"]))
        self.assertEqual(layout["part_path"], "ppt/slideLayouts/slideLayout2.xml")

        with self.assertRaises(KeyError):
            ThemeRegistry().get("missing")
        with self.assertRaises(KeyError):
            LayoutRegistry().get("missing")

    def test_theme_registry_type_scale_can_be_overridden_per_role(self):
        custom = ThemeRegistry().get("default")
        custom["typeScale"]["body"] = {
            "size": 19,
            "weight": "bold",
            "spaceAfter": "8pt",
            "lineSpacing": 1.2,
        }

        theme = ThemeRegistry({"custom": custom}).get("custom")

        self.assertEqual(theme["typeScale"]["body"]["size"], 19)
        self.assertEqual(theme["typeScale"]["body"]["weight"], "bold")
        for role in ("title", "heading", "subheading", "body", "bodySmall", "caption"):
            self.assertIn("size", theme["typeScale"][role])


class DSLParserTests(unittest.TestCase):
    def test_parser_round_trips_supported_elements_and_expands_defs(self):
        xml = """
        <deck theme="default" size="16:9" font="Aptos">
          <theme name="custom" accent1="#0057B8" heading="Arial" body="Arial"/>
          <defs>
            <def name="badge"><shape fill="accent1"><text>Badge</text></shape></def>
            <def name="footer" auto="true"><text size="8pt">Footer</text></def>
          </defs>
          <slide layout="blank" flow="free">
            <use ref="badge"/>
            <stack x="0in" y="0in" w="3in" h="1in"><text role="heading"><p role="caption"><run bold="true">Run</run> tail</p></text></stack>
            <grid x="0in" y="1in" w="3in" h="1in" cols="2"><shape col="2" fill="accent2"/></grid>
            <free x="0in" y="2in" w="4in" h="2in">
              <line x1="0%" y1="0%" x2="100%" y2="0%" color="dk1"/>
              <image src="logo.png" x="0in" y="0.1in" w="0.5in" h="0.5in"/>
              <table cols="2"><row><cell bold="true">A</cell><cell>B</cell></row></table>
              <timeline periods="2"><task label="Build" start="1"/><milestone label="Go" at="2"/></timeline>
            </free>
          </slide>
        </deck>
        """

        deck = DSLParser().parse(xml)

        self.assertEqual(deck.theme, "default")
        self.assertEqual(deck.inline_theme.name, "custom")
        self.assertEqual(deck.slides[0].layout, "blank")
        kinds = [child.kind for child in deck.slides[0].children]
        self.assertEqual(kinds[0], "shape")
        self.assertEqual(kinds[-1], "text")
        nested = []

        def walk(node):
            nested.append(node.kind)
            for child in node.children:
                walk(child)

        for child in deck.slides[0].children:
            walk(child)
        for expected in ("stack", "grid", "free", "line", "image", "table", "row", "cell", "timeline", "task", "milestone", "run"):
            self.assertIn(expected, nested)
        stack = next(child for child in deck.slides[0].children if child.kind == "stack")
        self.assertEqual(stack.children[0].attrs["role"], "heading")
        self.assertEqual(stack.children[0].children[0].attrs["role"], "caption")

    def test_unknown_element_or_attribute_is_rejected(self):
        with self.assertRaisesRegex(Exception, "Unknown element"):
            DSLParser().parse("<deck><slide><bogus/></slide></deck>")
        with self.assertRaisesRegex(Exception, "Unknown attribute"):
            DSLParser().parse('<deck madeup="1"><slide/></deck>')
        with self.assertRaisesRegex(Exception, "Unknown type role"):
            DSLParser().parse('<deck><slide><text role="tiny">Bad</text></slide></deck>')


class LayoutResolverTests(unittest.TestCase):
    def test_role_resolution_uses_theme_type_scale_and_paragraph_override(self):
        custom = ThemeRegistry().get("default")
        custom["typeScale"]["heading"] = {
            "size": 23,
            "weight": "bold",
            "spaceAfter": "7pt",
            "lineSpacing": 1.2,
        }
        custom["typeScale"]["caption"] = {
            "size": 12,
            "weight": "normal",
            "spaceAfter": "2pt",
            "lineSpacing": 1.05,
        }
        ast = DSLParser().parse(
            """
            <deck theme="custom">
              <slide layout="blank" flow="free">
                <text x="1in" y="1in" w="4in" h="1.5in" role="heading">
                  <p>Heading</p>
                  <p role="caption">Caption</p>
                </text>
              </slide>
            </deck>
            """
        )

        deck = LayoutResolver(ThemeRegistry({"custom": custom}), LayoutRegistry()).resolve(ast)

        paragraphs = deck.slide_data[0]["shapes"][0]["paragraphs"]
        self.assertEqual(paragraphs[0]["runs"][0]["size_pt"], 23)
        self.assertTrue(paragraphs[0]["runs"][0]["bold"])
        self.assertEqual(paragraphs[0]["spaceAfter"], "7pt")
        self.assertEqual(paragraphs[0]["lineSpacing"], 1.2)
        self.assertEqual(paragraphs[1]["runs"][0]["size_pt"], 12)
        self.assertNotIn("bold", paragraphs[1]["runs"][0])

    def test_role_size_omits_when_placeholder_master_already_matches(self):
        custom = ThemeRegistry().get("default")
        custom["typeScale"]["title"]["size"] = REFERENCE["master_text_styles"]["title"]["size"]
        ast = DSLParser().parse(
            """
            <deck theme="custom">
              <slide layout="title">
                <text placeholder="title" role="title">Inherited title size</text>
              </slide>
            </deck>
            """
        )

        deck = LayoutResolver(ThemeRegistry({"custom": custom}), LayoutRegistry()).resolve(ast)

        run = deck.slide_data[0]["shapes"][0]["paragraphs"][0]["runs"][0]
        self.assertNotIn("size_pt", run)

    def test_stack_edge_anchor_computes_full_bleed_thirds(self):
        deck = parse_resolve(
            """
            <deck>
              <slide layout="blank" flow="free">
                <stack dir="h" anchor="bottom" gap="0" h="0.3in">
                  <shape fill="#E53935"/>
                  <shape fill="#FB8C00"/>
                  <shape fill="#43A047"/>
                </stack>
              </slide>
            </deck>
            """
        )

        shapes = deck.slide_data[0]["shapes"]
        slide_w = REFERENCE["slide_sizes"]["16:9"]["cx"]
        expected_h = UnitConverter.to_emu("0.3in")
        self.assertEqual([shape["x"] for shape in shapes], [0, round(slide_w / 3), round(slide_w * 2 / 3)])
        self.assertEqual(shapes[0]["y"], REFERENCE["slide_sizes"]["16:9"]["cy"] - expected_h)
        self.assertEqual(shapes[0]["w"], round(slide_w / 3))

    def test_grid_resolver_computes_cell_boxes(self):
        deck = parse_resolve(
            """
            <deck>
              <slide layout="blank" flow="free">
                <grid x="1in" y="1in" w="4in" h="2in" cols="2" rows="1" gap="0in">
                  <shape col="2" fill="accent1"/>
                </grid>
              </slide>
            </deck>
            """
        )

        shape = deck.slide_data[0]["shapes"][0]
        self.assertEqual(shape["x"], UnitConverter.to_emu("3in"))
        self.assertEqual(shape["y"], UnitConverter.to_emu("1in"))
        self.assertEqual(shape["w"], UnitConverter.to_emu("2in"))
        self.assertEqual(shape["h"], UnitConverter.to_emu("2in"))

    def test_table_resolver_emits_native_table_shape_data(self):
        deck = parse_resolve(
            """
            <deck>
              <slide layout="blank" flow="free">
                <table x="1in" y="1in" w="4in" h="1in" cols="2" header="true" colWidths="50%,50%">
                  <row><cell>A</cell><cell>B</cell></row>
                </table>
              </slide>
            </deck>
            """
        )

        shapes = deck.slide_data[0]["shapes"]
        self.assertEqual([shape["type"] for shape in shapes], ["table"])
        self.assertEqual(shapes[0]["columns"][0]["w"], UnitConverter.to_emu("2in"))
        self.assertEqual(shapes[0]["rows"][0]["cells"][0]["fill"], "accent1")

    def test_timeline_resolver_aligns_start_and_span_to_period_tracks(self):
        deck = parse_resolve(
            """
            <deck>
              <slide layout="blank" flow="free">
                <timeline x="1in" y="1in" w="4in" h="2in" periods="4">
                  <task label="Build" start="2" span="2" fill="accent2"/>
                </timeline>
              </slide>
            </deck>
            """
        )

        bar = shape_by_name(deck.slide_data[0], "Timeline Task Build")
        self.assertEqual(bar["x"], UnitConverter.to_emu("2.75in"))
        self.assertEqual(bar["w"], UnitConverter.to_emu("1.5in"))

        timeline_text_shapes = [
            shape
            for shape in deck.slide_data[0]["shapes"]
            if shape.get("name") in {"Timeline Period", "Timeline Task Label"}
        ]
        self.assertTrue(timeline_text_shapes)
        for shape in timeline_text_shapes:
            for paragraph in shape["paragraphs"]:
                for run in paragraph.get("runs", []):
                    self.assertNotIn("size_pt", run)

    def test_alignment_round_trips_into_slide_xml(self):
        deck = parse_resolve(
            """
            <deck>
              <slide layout="blank" flow="free">
                <text x="0.5in" y="0.5in" w="2in" h="0.4in" align="l">Left</text>
                <text x="0.5in" y="1.0in" w="2in" h="0.4in" align="ctr">Center</text>
                <text x="0.5in" y="1.5in" w="2in" h="0.4in" align="r">Right</text>
                <text x="0.5in" y="2.0in" w="2in" h="0.4in" align="just">Justified</text>
              </slide>
            </deck>
            """
        )
        slide_xml = SlideBuilder(
            ContentTypeRegistry(),
            RelationshipRegistry(),
            {},
        ).build(deck.slide_data[0], part_path="ppt/slides/slide1.xml")

        for align in ("l", "ctr", "r", "just"):
            self.assertIn(f'algn="{align}"', slide_xml)

    def test_named_image_assets_resolve_through_shape_library(self):
        ast = DSLParser().parse(
            """
            <deck>
              <slide layout="blank" flow="free">
                <image src="brand_logo" x="1in" y="1in" w="1in" h="1in"/>
              </slide>
            </deck>
            """
        )
        deck = LayoutResolver(
            ThemeRegistry(),
            LayoutRegistry(),
            ShapeLibrary({"brand_logo": {"src": "assets/logo.png", "alt": "Brand Logo"}}),
        ).resolve(ast)

        image = deck.slide_data[0]["shapes"][0]
        self.assertEqual(image["src"], "assets/logo.png")
        self.assertEqual(image["name"], "Brand Logo")


class TranspilerValidatorTests(unittest.TestCase):
    def test_validator_reports_bounds_grid_placeholder_overlap_and_font_drift(self):
        bounds = parse_resolve(
            '<deck><slide layout="blank" flow="free"><text x="13in" y="0in" w="1in" h="1in">Too far</text></slide></deck>'
        )
        grid = parse_resolve(
            '<deck><slide layout="blank" flow="free"><grid x="0in" y="0in" w="2in" h="1in" cols="2" rows="1"><shape col="3" fill="accent1"/></grid></slide></deck>'
        )
        placeholder = parse_resolve(
            '<deck><slide layout="title" flow="stack"><text placeholder="body">Missing</text></slide></deck>'
        )
        overlap = parse_resolve(
            """
            <deck><slide layout="blank" flow="free">
              <shape x="1in" y="1in" w="2in" h="1in" fill="accent1"/>
              <shape x="1.5in" y="1in" w="2in" h="1in" fill="accent2"/>
            </slide></deck>
            """
        )
        drift = parse_resolve(
            """
            <deck><slide layout="blank" flow="stack">
              <text size="10pt">Small</text>
              <text size="18pt">Large</text>
            </slide></deck>
            """
        )

        validator = Validator()
        self.assertIn("bounds", {issue.code for issue in validator.validate(bounds)})
        self.assertIn("grid_bounds", {issue.code for issue in validator.validate(grid)})
        self.assertIn("placeholder", {issue.code for issue in validator.validate(placeholder)})
        self.assertIn("free_overlap", {issue.code for issue in validator.validate(overlap)})
        self.assertIn("font_drift", {issue.code for issue in validator.validate(drift)})
        with self.assertRaises(TranspileValidationError):
            validator.raise_for_errors(validator.validate(bounds))


class TranspilerIntegrationTests(unittest.TestCase):
    def test_pressure_test_deck_transpiles_and_opens_with_python_pptx(self):
        try:
            from pptx import Presentation as PptxPresentation
        except ImportError:
            self.fail("python-pptx is required for transpiler integration tests")

        dsl = """
        <deck theme="pressure" size="16:9">
          <theme name="pressure"
                 dk1="#111827" lt1="#FFFFFF" dk2="#374151" lt2="#F3F4F6"
                 accent1="#2563EB" accent2="#F97316" accent3="#16A34A"
                 accent4="#7C3AED" accent5="#0E7490" accent6="#DC2626"
                 hlink="#1D4ED8" folHlink="#6D28D9"
                 heading="Aptos Display" body="Aptos"/>
          <slide layout="titleBody" flow="free">
            <text placeholder="title">Styled panel grid</text>
            <grid x="0.7in" y="1.65in" w="11.95in" h="4.6in" cols="3" rows="1" gap="0.25in">
              <stack col="1" fill="lt2" line="accent1" radius="6pt" pad="0.18in" gap="0.08in">
                <text size="14pt" bold="true" color="accent1">Our understanding</text>
                <text size="10pt" list="bullet"><p>Speed matters</p><p><run underline="true" link="https://example.com">Accessibility matters</run></p></text>
              </stack>
              <stack col="2" fill="lt2" line="accent2" radius="6pt" pad="0.18in">
                <text size="14pt" bold="true" color="accent2">Risks</text>
                <text size="10pt" list="bullet"><p>Security dependency</p><p>Data readiness</p></text>
              </stack>
              <stack col="3" fill="lt2" line="accent3" radius="6pt" pad="0.18in">
                <text size="14pt" bold="true" color="accent3">Plan</text>
                <text size="10pt" list="number"><p>Discover</p><p>Build</p><p>Launch</p></text>
              </stack>
            </grid>
          </slide>
          <slide layout="titleBody" flow="free">
            <text placeholder="title">Fee table</text>
            <table x="0.85in" y="1.65in" w="11.65in" h="3.2in" cols="4" header="true" colWidths="40%,20%,20%,20%" line="dk2">
              <row><cell>Position</cell><cell align="r">Daily rate</cell><cell align="r">Days</cell><cell align="r">Total</cell></row>
              <row><cell>Partner</cell><cell align="r">1000</cell><cell align="r">10</cell><cell align="r">10000</cell></row>
              <row><cell>Senior Consultant</cell><cell align="r">2000</cell><cell align="r">20</cell><cell align="r">40000</cell></row>
            </table>
          </slide>
          <slide layout="blank" flow="free">
            <text x="0.7in" y="0.65in" w="8in" h="0.6in" size="24pt" bold="true">Edge-anchored classification bar</text>
            <shape x="0.7in" y="1.4in" w="2.6in" h="0.45in" fill="none" line="accent1" text="Outline only"/>
            <stack dir="h" anchor="bottom" align="stretch" gap="0" h="0.42in">
              <shape fill="#E53935" text="HIGH RISK CONFIDENTIAL"/>
              <shape fill="#FB8C00" text="CONFIDENTIAL"/>
              <shape fill="#43A047" text="PUBLIC"/>
            </stack>
          </slide>
          <slide layout="blank" flow="free">
            <timeline x="0.7in" y="0.8in" w="11.9in" h="5.2in" periods="5" labels="W1,W2,W3,W4,W5">
              <task label="Discover" start="1" span="2" fill="accent2"/>
              <task label="Build" start="2" span="3" fill="accent1"/>
              <task label="Launch" start="5" span="1" fill="accent3"/>
              <milestone label="Kickoff" at="1"/>
              <milestone label="Go-live" at="5"/>
            </timeline>
          </slide>
        </deck>
        """

        output_path = Path("tests/fixtures/transpiled_deck.pptx")
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
            handle.write(dsl)
            source_path = Path(handle.name)
        try:
            result = transpile_deck(source_path, output_path)
        finally:
            source_path.unlink(missing_ok=True)

        presentation = PptxPresentation(str(result.pptx_path))
        self.assertEqual(len(presentation.slides), 4)
        self.assertTrue(all(len(slide.shapes) > 0 for slide in presentation.slides))
        self.assertTrue(output_path.exists())
        self.assertFalse([issue for issue in result.validation_issues if issue.severity == "error"])

        with ZipFile(output_path) as pptx:
            slide_xml = "\n".join(
                pptx.read(name).decode("utf-8")
                for name in pptx.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
        self.assertIn("<a:buChar", slide_xml)
        self.assertIn("<a:buAutoNum", slide_xml)
        self.assertIn("<a:tbl>", slide_xml)
        self.assertIn("<a:noFill", slide_xml)
        self.assertIn('u="sng"', slide_xml)
        self.assertIn("<p:cxnSp>", slide_xml)


if __name__ == "__main__":
    unittest.main()
