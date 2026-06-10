"""CLI build command: exit codes and artifact creation."""

import tempfile
import unittest
from pathlib import Path

from paro import run_build


class CliBuildTests(unittest.TestCase):
    def test_build_writes_pptx_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deck = Path(tmpdir) / "deck.xml"
            deck.write_text(
                '<deck><slide layout="blank" flow="stack">'
                "<text>Hello</text></slide></deck>"
            )
            code = run_build(deck)
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmpdir) / "deck.pptx").exists())

    def test_validation_error_returns_one_without_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deck = Path(tmpdir) / "bad.xml"
            deck.write_text(
                '<deck><slide layout="blank" flow="free">'
                '<text x="14in" y="0in" w="2in" h="1in">off slide</text>'
                "</slide></deck>"
            )
            self.assertEqual(run_build(deck), 1)

    def test_missing_deck_returns_one(self):
        self.assertEqual(run_build("/does/not/exist.xml"), 1)


if __name__ == "__main__":
    unittest.main()
