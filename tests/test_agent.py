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


if __name__ == "__main__":
    unittest.main()
