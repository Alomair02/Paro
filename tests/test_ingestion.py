import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from ingestion import (
    ThemeExtractionError,
    bundle_to_registry_themes,
    extract_theme_bundle,
)
from transpiler import ThemeRegistry, transpile_deck

DELOITTE = Path(__file__).resolve().parent.parent / (
    "Deloitte Tech Optimisation and Delivery PPT Template.pptx"
)

# Ground truth read by hand from the template's ppt/theme/theme1.xml.
DELOITTE_COLORS = {
    "dk1": "000000",
    "lt1": "FFFFFF",
    "dk2": "53565A",
    "lt2": "D0D0CE",
    "accent1": "86BC25",
    "accent2": "046A38",
    "accent3": "62B5E5",
    "accent4": "012169",
    "accent5": "0097A9",
    "accent6": "75787B",
    "hlink": "00A3E0",
    "folHlink": "53565A",
}


@unittest.skipUnless(DELOITTE.exists(), "Deloitte template not present")
class DeloitteExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = extract_theme_bundle(DELOITTE)

    def test_extracts_every_color_slot_exactly(self):
        self.assertEqual(self.bundle["theme"]["colors"], DELOITTE_COLORS)

    def test_extracts_font_scheme(self):
        self.assertEqual(
            self.bundle["theme"]["fonts"], {"heading": "Verdana", "body": "Verdana"}
        )

    def test_picks_the_slide_masters_theme_not_notes_or_handout(self):
        # the template carries theme1 (slides), theme2/theme3 (notes/handout)
        self.assertEqual(self.bundle["source"]["theme_part"], "ppt/theme/theme1.xml")
        self.assertEqual(self.bundle["source"]["theme_name"], "Deloitte_US_Onscreen")

    def test_slide_size_matches_engine_16_9(self):
        self.assertEqual(
            self.bundle["slide_size"],
            {"cx": 12192000, "cy": 6858000, "engine_size": "16:9"},
        )

    def test_master_background_resolves_through_bgref(self):
        # master declares <p:bgRef idx="1001"><a:schemeClr val="bg1"/>:
        # bgFillStyleLst[0] is solid phClr -> bg1 -> lt1
        self.assertEqual(
            self.bundle["background"],
            {"kind": "scheme", "token": "lt1", "provenance": "extracted"},
        )

    def test_title_and_body_sizes_extracted_exactly(self):
        scale = self.bundle["theme"]["typeScale"]
        self.assertEqual(scale["title"]["size"], 20.0)
        self.assertEqual(scale["title"]["provenance"], "extracted")
        self.assertEqual(scale["body"]["size"], 12.0)
        self.assertEqual(scale["body"]["provenance"], "extracted")

    def test_derived_scale_keeps_hierarchy_coherent(self):
        scale = self.bundle["theme"]["typeScale"]
        ordered = ["title", "heading", "subheading", "body", "bodySmall", "caption"]
        sizes = [scale[r]["size"] for r in ordered]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertTrue(all(sizes[i] > sizes[i + 1] for i in range(len(sizes) - 1)))
        for role in ("heading", "subheading", "bodySmall", "caption"):
            self.assertEqual(scale[role]["provenance"], "derived")

    def test_coverage_reports_nothing_silently_dropped(self):
        coverage = self.bundle["coverage"]
        for block in ("theme.colors", "theme.fonts", "theme.typeScale", "background"):
            self.assertIn(block, coverage["used"])
        self.assertIn("fmtScheme", coverage["preserved"])
        self.assertEqual(coverage["preserved"]["layouts"]["count"], 41)

    def test_bundle_is_json_serializable(self):
        import json

        json.dumps(self.bundle)


@unittest.skipUnless(DELOITTE.exists(), "Deloitte template not present")
class DeloitteRoundTripTests(unittest.TestCase):
    """Acceptance: ingest -> registries -> generate -> emitted theme is Deloitte."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = extract_theme_bundle(DELOITTE)
        cls.themes = bundle_to_registry_themes(cls.bundle, "deloitte")

    def test_registry_payload_strips_provenance_and_merges_over_default(self):
        theme = ThemeRegistry(self.themes).get("deloitte")
        self.assertEqual(theme["colors"]["accent1"], "86BC25")
        self.assertEqual(theme["fonts"]["body"], "Verdana")
        self.assertNotIn("provenance", theme["typeScale"]["title"])
        # default-merge fills what the master doesn't declare
        self.assertEqual(theme["typeScale"]["title"]["weight"], "bold")
        self.assertIn("spaceAfter", theme["typeScale"]["title"])

    def test_generated_deck_carries_deloitte_theme(self):
        dsl = (
            '<deck theme="deloitte">'
            '<slide layout="titleBody">'
            '<text placeholder="title">Ingested</text>'
            '<text placeholder="body">Generated under the Deloitte theme.</text>'
            "</slide></deck>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "deck.xml"
            src.write_text(dsl)
            result = transpile_deck(src, themes=self.themes)
            with ZipFile(result.pptx_path) as pptx:
                theme_xml = pptx.read("ppt/theme/theme1.xml").decode("utf-8")
                slide_xml = pptx.read("ppt/slides/slide1.xml").decode("utf-8")
            self.assertIn('val="86BC25"', theme_xml)
            self.assertIn('typeface="Verdana"', theme_xml)
            # the ingested type scale flows: 20pt title -> sz="2000"
            self.assertIn('sz="2000"', slide_xml)

    def test_inline_theme_outranks_ingested_theme_of_same_name(self):
        dsl = (
            '<deck theme="deloitte">'
            '<theme name="deloitte" accent1="FF0000"/>'
            '<slide layout="blank" flow="stack"><text role="body">x</text></slide>'
            "</deck>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "deck.xml"
            src.write_text(dsl)
            result = transpile_deck(src, themes=self.themes)
            with ZipFile(result.pptx_path) as pptx:
                theme_xml = pptx.read("ppt/theme/theme1.xml").decode("utf-8")
            self.assertIn('val="FF0000"', theme_xml)
            self.assertNotIn('val="86BC25"', theme_xml)


class ExtractionErrorTests(unittest.TestCase):
    def test_non_zip_file_fails_with_clear_error(self):
        with tempfile.NamedTemporaryFile(suffix=".pptx") as f:
            f.write(b"not a zip")
            f.flush()
            with self.assertRaises(ThemeExtractionError) as ctx:
                extract_theme_bundle(f.name)
            self.assertIn("not a .pptx", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
