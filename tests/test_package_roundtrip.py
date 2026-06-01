import tempfile
import unittest
from pathlib import Path

from builders.common import REFERENCE
from core.relationship_reg import RelationshipRegistry
from tests.pptx_test_utils import build_core_parts, parse_xml, write_pptx_package


def package_xml_payloads(graph: dict) -> dict[str, str]:
    relationships = graph["relationships"]
    payloads = {
        "[Content_Types].xml": graph["content_types"].render(),
    }

    for source_part_path in relationships.registry:
        rels_xml = relationships.render(source_part_path)
        if rels_xml:
            payloads[RelationshipRegistry.rels_path(source_part_path)] = rels_xml

    payloads.update(graph["parts"])
    return payloads


class PackageRoundTripTests(unittest.TestCase):
    def test_core_package_xml_is_well_formed_and_opens_with_python_pptx(self):
        try:
            from pptx import Presentation as PptxPresentation
        except ImportError as exc:
            self.fail(
                "python-pptx is required for package round-trip tests; "
                "install requirements-dev.txt"
            )

        graph = build_core_parts(synthetic_slide_count=0)

        for package_path, xml in package_xml_payloads(graph).items():
            with self.subTest(xml=package_path):
                parse_xml(xml)

        with tempfile.TemporaryDirectory() as tmpdir:
            pptx_path = Path(tmpdir) / "core-package.pptx"
            write_pptx_package(pptx_path, graph)

            presentation = PptxPresentation(str(pptx_path))
            self.assertEqual(len(presentation.slides), 0)
            self.assertEqual(
                int(presentation.slide_width),
                REFERENCE["slide_sizes"]["16:9"]["cx"],
            )
            self.assertEqual(
                int(presentation.slide_height),
                REFERENCE["slide_sizes"]["16:9"]["cy"],
            )


if __name__ == "__main__":
    unittest.main()
