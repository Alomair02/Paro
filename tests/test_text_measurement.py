import tempfile
import unittest
from pathlib import Path

from pptx import Presentation as PptxPresentation

from builders.common import REFERENCE
from transpiler import DSLParser, LayoutRegistry, LayoutResolver, ThemeRegistry, Validator, transpile_deck
from transpiler.text_metrics import TextMeasurer, resolve_font
from utils.converter import UnitConverter


def parse_resolve(xml: str):
    ast = DSLParser().parse(xml)
    return LayoutResolver(ThemeRegistry(), LayoutRegistry()).resolve(ast)


class TextMetricsTests(unittest.TestCase):
    def test_metrics_measure_known_liberation_sans_widths_and_wraps(self):
        measurer = TextMeasurer()
        wide_box = UnitConverter.to_emu("10in")

        hello = measurer.measure("Hello", "Liberation Sans", 12, wide_box)
        wide = measurer.measure("WW", "Liberation Sans", 12, wide_box)
        narrow = measurer.measure("ii", "Liberation Sans", 12, wide_box)
        wrapped = measurer.measure("one two three four five", "Liberation Sans", 12, UnitConverter.to_emu("0.8in"))

        self.assertFalse(hello.approximation_used)
        self.assertEqual(hello.wrapped_lines, 1)
        self.assertGreater(hello.rendered_width_emu, 300000)
        self.assertLess(hello.rendered_width_emu, 400000)
        self.assertGreater(wide.rendered_width_emu, narrow.rendered_width_emu)
        self.assertGreater(wrapped.wrapped_lines, 1)
        self.assertGreater(wrapped.rendered_height_emu, hello.rendered_height_emu)

    def test_missing_requested_font_uses_documented_fallback(self):
        result = TextMeasurer().measure("Fallback", "Definitely Missing Font", 12, UnitConverter.to_emu("4in"))

        self.assertTrue(result.approximation_used)
        self.assertEqual(result.font_family_used, "Liberation Sans")
      
    def test_aptos_resolves_to_exact_weight_and_subfamily(self):
    # Regression: substring matching grabbed 'Aptos-Black.ttf' for a plain
    # 'Aptos' request. Assert the EXACT file per family/weight/italic — a
    # correct approximation_used flag did NOT catch this (it was False while
    # pointing at Black).
      cases = [
          ("Aptos",         False, False, "Aptos.ttf"),
          ("Aptos",         True,  False, "Aptos-Bold.ttf"),
          ("Aptos",         False, True,  "Aptos-Italic.ttf"),
          ("Aptos",         True,  True,  "Aptos-Bold-Italic.ttf"),
          ("Aptos Display", False, False, "Aptos-Display.ttf"),
          ("Aptos Display", True,  False, "Aptos-Display-Bold.ttf"),
      ]
      for family, bold, italic, expected in cases:
          with self.subTest(family=family, bold=bold, italic=italic):
              r = resolve_font(family, bold=bold, italic=italic)
              self.assertIsNotNone(r.path, f"{family} did not resolve")
              self.assertEqual(r.path.name, expected)
              self.assertFalse(r.approximation_used)

      # The specific regression, named explicitly.
      self.assertNotEqual(resolve_font("Aptos").path.name, "Aptos-Black.ttf")


class TextOverflowValidatorTests(unittest.TestCase):
    def test_default_theme_defines_role_shrink_floors(self):
        for role, bundle in REFERENCE["default_theme"]["typeScale"].items():
            self.assertIn("minSize", bundle)
            self.assertLessEqual(bundle["minSize"], bundle["size"])

    def test_validator_warns_only_for_text_that_exceeds_its_box(self):
        fitting = parse_resolve(
            """
            <deck>
              <slide layout="blank" flow="free">
                <text x="0.5in" y="0.5in" w="5in" h="1in" role="body">Short text</text>
              </slide>
            </deck>
            """
        )
        overflowing = parse_resolve(
            """
            <deck>
              <slide layout="blank" flow="free">
                <text x="0.5in" y="0.5in" w="1in" h="0.22in" role="body">
                  This deliberately long text cannot fit in the small resolved box.
                </text>
              </slide>
            </deck>
            """
        )

        validator = Validator()
        self.assertNotIn("text_overflow", {issue.code for issue in validator.validate(fitting)})
        warnings = [issue for issue in validator.validate(overflowing) if issue.code == "text_overflow"]

        self.assertEqual(len(warnings), 1)
        self.assertEqual(overflowing.slide_data[0]["shapes"][0]["paragraphs"][0]["runs"][0]["size_pt"], 17)
        details = warnings[0].details
        self.assertEqual(details["slide_index"], 1)
        self.assertEqual(details["role"], "body")
        self.assertEqual(
            details["overflow_h_emu"],
            max(0, details["measured_height_emu"] - details["box"]["h"]),
        )
        self.assertGreater(details["overflow_w_emu"] + details["overflow_h_emu"], 0)

    def test_auto_shrink_reduces_within_role_range_and_keeps_role(self):
        text = "Shrink me"
        width = UnitConverter.to_emu("6in")
        role = REFERENCE["default_theme"]["typeScale"]["body"]
        measurer = TextMeasurer()
        height_at_role = measurer.measure(
            text,
            "Aptos",
            role["size"],
            width,
            line_spacing=role["lineSpacing"],
        ).rendered_height_emu + UnitConverter.to_emu(role["spaceAfter"])
        height_at_floor = measurer.measure(
            text,
            "Aptos",
            role["minSize"],
            width,
            line_spacing=role["lineSpacing"],
        ).rendered_height_emu + UnitConverter.to_emu(role["spaceAfter"])
        box_height = round((height_at_role + height_at_floor) / 2)
        deck = parse_resolve(
            f"""
            <deck>
              <slide layout="blank" flow="free">
                <text x="0.5in" y="0.5in" w="6in" h="{box_height}emu" role="body">{text}</text>
              </slide>
            </deck>
            """
        )

        issues = Validator(auto_shrink_text=True).validate(deck)
        warning = next(issue for issue in issues if issue.code == "text_overflow")
        paragraph = deck.slide_data[0]["shapes"][0]["paragraphs"][0]
        final_size = paragraph["runs"][0]["size_pt"]

        self.assertEqual(paragraph["role"], "body")
        self.assertLess(final_size, role["size"])
        self.assertGreaterEqual(final_size, role["minSize"])
        self.assertTrue(warning.details["shrink_applied"])
        self.assertFalse(warning.details["shrink_floored"])
        self.assertEqual(warning.details["final_overflow_h_emu"], 0)

    def test_auto_shrink_stops_at_floor_and_still_warns(self):
        role = REFERENCE["default_theme"]["typeScale"]["body"]
        deck = parse_resolve(
            """
            <deck>
              <slide layout="blank" flow="free">
                <text x="0.5in" y="0.5in" w="5in" h="0.04in" role="body">Still too tall</text>
              </slide>
            </deck>
            """
        )

        issues = Validator(auto_shrink_text=True).validate(deck)
        warning = next(issue for issue in issues if issue.code == "text_overflow")
        paragraph = deck.slide_data[0]["shapes"][0]["paragraphs"][0]

        self.assertEqual(paragraph["runs"][0]["size_pt"], role["minSize"])
        self.assertEqual(paragraph["role"], "body")
        self.assertTrue(warning.details["shrink_floored"])
        self.assertGreater(warning.details["final_overflow_h_emu"], 0)


class TextMeasurementIntegrationTests(unittest.TestCase):
    def test_transpile_reports_overflow_only_on_overflowing_slide(self):
        dsl = """
        <deck>
          <slide layout="blank" flow="free">
            <text x="0.7in" y="0.7in" w="6in" h="1in" role="body">This slide fits comfortably.</text>
          </slide>
          <slide layout="blank" flow="free">
            <text x="0.7in" y="0.7in" w="1in" h="0.22in" role="body">
              This slide is intentionally too dense for its resolved text box and should warn.
            </text>
          </slide>
        </deck>
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "measurement.xml"
            output = Path(tmpdir) / "measurement.pptx"
            source.write_text(dsl, encoding="utf-8")

            result = transpile_deck(source, output)
            presentation = PptxPresentation(str(result.pptx_path))

        warnings = [issue for issue in result.validation_issues if issue.code == "text_overflow"]
        self.assertEqual(len(presentation.slides), 2)
        self.assertEqual([warning.details["slide_index"] for warning in warnings], [2])
      
    def test_unsupported_theme_font_warns(self):
      from transpiler.pipeline import _inline_theme_map
      xml = ('<deck><theme name="brand" heading="Acme Sans" body="Acme Sans"/>'
            '<slide layout="blank" flow="free">'
            '<text x="0.5in" y="0.5in" w="6in" h="2in" role="body">Hi</text>'
            '</slide></deck>')
      ast = DSLParser().parse(xml)
      deck = LayoutResolver(ThemeRegistry(_inline_theme_map(ast)), LayoutRegistry()).resolve(ast)
      codes = [i.code for i in Validator().validate(deck) if i.code == "font_unsupported"]
      self.assertGreaterEqual(len(codes), 1)

    def test_supported_font_does_not_warn(self):
        xml = ('<deck><slide layout="blank" flow="free">'
              '<text x="0.5in" y="0.5in" w="6in" h="2in" role="body" font="Aptos">Hi</text>'
              '</slide></deck>')
        ast = DSLParser().parse(xml)
        deck = LayoutResolver(ThemeRegistry(), LayoutRegistry()).resolve(ast)
        codes = [i.code for i in Validator().validate(deck) if i.code == "font_unsupported"]
        self.assertEqual(codes, [])


if __name__ == "__main__":
    unittest.main()
