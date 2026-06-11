"""Agent layer plumbing — no API calls, no network."""

import tempfile
import unittest
from pathlib import Path

try:
    import claude_agent_sdk  # noqa: F401

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False


@unittest.skipUnless(HAVE_SDK, "claude-agent-sdk not installed")
class AgentPlumbingTests(unittest.TestCase):
    def test_system_prompt_carries_protocol_and_doctrine(self):
        from agent.prompt import build_system_prompt

        prompt = build_system_prompt()
        self.assertIn("paro_build", prompt)
        self.assertIn("at most three builds", prompt)
        # the doctrine actually made it in
        self.assertIn("Spacing rhythm", prompt)
        self.assertIn("Diagrams: composites before shapes", prompt)

    def test_build_tool_reports_lint_text(self):
        from agent.tools import build_deck_text

        with tempfile.TemporaryDirectory() as tmpdir:
            deck = Path(tmpdir) / "deck.xml"
            deck.write_text(
                '<deck><slide layout="blank" flow="free">'
                '<text x="1in" y="1in" w="3in" h="0.4in" size="6pt">tiny</text>'
                "</slide></deck>"
            )
            report = build_deck_text(str(deck), png=False)
        self.assertIn("build OK", report)
        self.assertIn("lint_tiny_text", report)

    def test_build_tool_surfaces_errors(self):
        from agent.tools import build_deck_text

        with tempfile.TemporaryDirectory() as tmpdir:
            deck = Path(tmpdir) / "bad.xml"
            deck.write_text(
                '<deck><slide layout="blank" flow="free">'
                '<text x="14in" y="0in" w="2in" h="1in">off slide</text>'
                "</slide></deck>"
            )
            report = build_deck_text(str(deck), png=False)
        self.assertIn("build FAILED", report)
        self.assertIn("bounds", report)

    def test_runner_options_allow_only_authoring_tools(self):
        from agent.runner import make_options

        options = make_options()
        self.assertIn("mcp__paro__paro_build", options.allowed_tools)
        self.assertNotIn("Bash", options.allowed_tools)

    def test_profile_defaults_load_and_merge(self):
        from agent.profile import init_profile, load_profile

        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir) / "acme"
            init_profile(directory)
            (directory / "profile.json").write_text(
                '{"audience": "IB analysts", "diagram_density": "dense",'
                ' "theme": {"source": "template", "template_pptx": "corp.pptx"},'
                ' "notes": ["always waterfall for P&L"]}'
            )
            profile = load_profile(directory)
        self.assertEqual(profile["audience"], "IB analysts")
        self.assertEqual(profile["diagram_density"], "dense")
        # merged theme keeps default theme_name
        self.assertEqual(profile["theme"]["theme_name"], "ingested")
        self.assertEqual(profile["formality"], "corporate")  # default survives

    def test_profile_invalid_enum_raises_clearly(self):
        from agent.profile import ProfileError, load_profile

        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "profile.json").write_text('{"formality": "baroque"}')
            with self.assertRaises(ProfileError):
                load_profile(directory)

    def test_profile_prompt_carries_dials_theme_and_writeback(self):
        from agent.profile import load_profile, profile_prompt

        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "profile.json").write_text(
                '{"chart_complexity": "rich",'
                ' "theme": {"source": "template", "template_pptx": "corp.pptx"},'
                ' "notes": ["never clip-art icons"]}'
            )
            prompt = profile_prompt(load_profile(directory), directory)
        self.assertIn("rich", prompt)
        self.assertIn('theme_pptx="corp.pptx"', prompt)
        self.assertIn("never clip-art icons", prompt)
        self.assertIn("append a short", prompt)  # write-back instruction

    def test_read_source_xlsx_rows_and_sheets(self):
        from openpyxl import Workbook

        from agent.sources import read_source

        with tempfile.TemporaryDirectory() as tmpdir:
            book = Workbook()
            ws = book.active
            ws.title = "Revenue"
            ws.append(["Quarter", "Revenue"])
            ws.append(["Q1'26", 45.1])
            ws.append(["Q2'26", 48.2])
            path = Path(tmpdir) / "fin.xlsx"
            book.save(path)
            text = read_source(path)
        self.assertIn("sheets: Revenue", text)
        self.assertIn("| Q2'26 | 48.2 |", text)

    def test_read_source_docx_paragraphs_and_tables(self):
        import zipfile

        from agent.sources import read_source

        document = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>Executive summary.</w:t></w:r></w:p>"
            "<w:tbl><w:tr>"
            "<w:tc><w:p><w:r><w:t>KPI</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>96.4%</w:t></w:r></w:p></w:tc>"
            "</w:tr></w:tbl>"
            "</w:body></w:document>"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "memo.docx"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("word/document.xml", document)
            text = read_source(path)
        self.assertIn("Executive summary.", text)
        self.assertIn("| KPI | 96.4% |", text)

    def test_read_source_unsupported_and_missing(self):
        from agent.sources import SourceReadError, read_source

        with self.assertRaises(SourceReadError):
            read_source("/does/not/exist.xlsx")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "deck.pptx"
            path.write_text("x")
            with self.assertRaises(SourceReadError):
                read_source(path)

    def test_runner_options_include_profile_section(self):
        from agent.profile import init_profile
        from agent.runner import make_options

        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir) / "p"
            init_profile(directory)
            options = make_options(profile_dir=str(directory))
        self.assertIn("Design profile", options.system_prompt)


if __name__ == "__main__":
    unittest.main()
