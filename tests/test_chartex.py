import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
import io
import re


from openpyxl import load_workbook
from builders.deck_builder import SAMPLE_THEME, assemble_package
from core.xml_builder import NSMAP, qn
from tests.pptx_test_utils import parse_xml

class TestChartExFunnel(unittest.TestCase):
    def test_funnel_chartex_part_and_invariants(self):

        output_path = Path("tests/fixtures/funnel_chartex.pptx")
        slide_data = [{"index": 1, "shapes": [{"type": "funnel"}]}]
        assemble_package(SAMPLE_THEME, slide_data, output_path)

        CHARTEX_NS = "http://schemas.microsoft.com/office/drawing/2014/chartex"
        ns = dict(NSMAP, cx=CHARTEX_NS)

        with ZipFile(output_path) as pptx:
            names = pptx.namelist()
            chartex_parts = sorted(n for n in names if n.startswith("ppt/charts/chartEx") and n.endswith(".xml"))
            self.assertEqual(len(chartex_parts), 1, "expected exactly one chartEx part")
            chartex_part = chartex_parts[0]
            root = parse_xml(pptx.read(chartex_part).decode("utf-8"))

            series = root.find("cx:chart/cx:plotArea/cx:plotAreaRegion/cx:series", ns)
            self.assertIsNotNone(series, "no cx:series found")
            self.assertEqual(series.get("layoutId"), "funnel")

            # chartEx hoists data into cx:numDim (type="val"); the cx:pt text IS the cache.
            num_dim = root.find(".//cx:numDim[@type='val']", ns)
            cache_values = sorted(float(pt.text) for pt in num_dim.findall("cx:lvl/cx:pt", ns))

            workbooks = sorted(n for n in names if n.startswith("xl/embeddings/") and n.endswith(".xlsx"))
            self.assertEqual(len(workbooks), 1)
            ws = load_workbook(io.BytesIO(pptx.read(workbooks[0]))).active
            wb_values = []
            r = 2
            while ws.cell(row=r, column=2).value is not None:   # column B
                wb_values.append(float(ws.cell(row=r, column=2).value))
                r += 1
            self.assertEqual(cache_values, sorted(wb_values))

            rels = parse_xml(pptx.read(f"ppt/charts/_rels/{Path(chartex_part).name}.rels").decode("utf-8"))
            rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
            rel_types = sorted(rel.get("Type") for rel in rels.findall("r:Relationship", rel_ns))
            self.assertEqual(rel_types, sorted([
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/package",
                "http://schemas.microsoft.com/office/2011/relationships/chartStyle",
                "http://schemas.microsoft.com/office/2011/relationships/chartColorStyle",
            ]), "chartEx part must relate workbook + style + colorstyle")

            ct = pptx.read("[Content_Types].xml").decode("utf-8")
            self.assertIn("application/vnd.ms-office.chartex+xml", ct)
            self.assertIn("application/vnd.ms-office.chartstyle+xml", ct)
            self.assertIn("application/vnd.ms-office.chartcolorstyle+xml", ct)
            
            for part in [chartex_part] + [n for n in names if "style_chartEx" in n or "colors_chartEx" in n]:
                text = pptx.read(part).decode("utf-8")
                for m in re.finditer(r'(lumMod|lumOff)[^>]*val="(\d+)"', text):
                    self.assertLessEqual(int(m.group(2)), 100000,
                        f"{m.group(1)} > 100000 in {part} triggers PowerPoint repair")
                    
            self.assertNotIn("cx", NSMAP, "cx must be declared locally, never globally")
