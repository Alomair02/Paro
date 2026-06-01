import unittest
from pathlib import Path

from builders import LAYOUT_DEFINITIONS
from builders.common import package_path
from tests.pptx_test_utils import build_core_parts, canonical_xml


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"


def golden_outputs() -> dict[str, str]:
    graph = build_core_parts(synthetic_slide_count=0)
    parts = graph["parts"]

    outputs = {
        "theme1.xml": parts[package_path("theme", 1)],
        "slideMaster1.xml": parts[package_path("slideMaster", 1)],
        "presentation.xml": parts[package_path("presentation")],
    }

    for layout_name, layout_def in LAYOUT_DEFINITIONS.items():
        outputs[f"{layout_name}.slideLayout.xml"] = parts[layout_def["part_path"]]

    return outputs


class GoldenOutputTests(unittest.TestCase):
    def test_builder_outputs_match_golden_fixtures(self):
        for fixture_name, actual_xml in golden_outputs().items():
            with self.subTest(fixture=fixture_name):
                fixture_path = FIXTURE_DIR / fixture_name
                expected_xml = fixture_path.read_text(encoding="utf-8")

                self.assertMultiLineEqual(
                    canonical_xml(expected_xml),
                    canonical_xml(actual_xml),
                )


if __name__ == "__main__":
    unittest.main()
