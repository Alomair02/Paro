import unittest
import io
from pathlib import Path
from zipfile import ZipFile
from builders.deck_builder import SAMPLE_THEME, assemble_package
from tests.pptx_test_utils import parse_xml
from openpyxl import load_workbook

class TestCharts(unittest.TestCase):
    def test_radar_chart_invariants(self):
        output_path = Path("tests/fixtures/radar_chart.pptx")
        slide_data = [{
            "index": 1,
            "shapes": [{
                "type": "chart", "chart_type": "radar",
                "title": "This is my radar",
                "categories": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                "series": [
                    {"name": "Series 1", "values": [32, 32, 28, 12, 15]},
                    {"name": "Series 2", "values": [12, 12, 12, 21, 28]},
                ],
            }],
        }]
        assemble_package(SAMPLE_THEME, slide_data, output_path)

        C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
        ns = {"c": C_NS}

        with ZipFile(output_path) as pptx:
            names = pptx.namelist()
            chart_part = next(n for n in names
                              if n.startswith("ppt/charts/chart") and n.endswith(".xml")
                              and "chartEx" not in n and "_rels" not in n
                              and "colors" not in n and "style" not in n)
            root = parse_xml(pptx.read(chart_part).decode("utf-8"))

            # the radar plot element exists
            radar = root.find(".//c:plotArea/c:radarChart", ns)
            self.assertIsNotNone(radar, "must emit c:radarChart")

            # radarStyle (radar's signature element)
            rs = radar.find("c:radarStyle", ns)
            self.assertIsNotNone(rs, "radar needs radarStyle")
            self.assertEqual(rs.get("val"), "marker")

            # two series, each with a marker symbol=none
            sers = radar.findall("c:ser", ns)
            self.assertEqual(len(sers), 2, "two series")
            for ser in sers:
                sym = ser.find("c:marker/c:symbol", ns)
                self.assertIsNotNone(sym, "radar series needs a marker")
                self.assertEqual(sym.get("val"), "none")
                # radar must NOT carry c:smooth (that's line-only)
                self.assertIsNone(ser.find("c:smooth", ns), "radar series must not have smooth")

            # catAx + valAx pair, crossAx cross-referencing each other
            cat_ax = root.find(".//c:plotArea/c:catAx", ns)
            val_ax = root.find(".//c:plotArea/c:valAx", ns)
            self.assertIsNotNone(cat_ax, "radar has a catAx")
            self.assertIsNotNone(val_ax, "radar has a valAx")
            cat_id = cat_ax.find("c:axId", ns).get("val")
            val_id = val_ax.find("c:axId", ns).get("val")
            self.assertEqual(cat_ax.find("c:crossAx", ns).get("val"), val_id)
            self.assertEqual(val_ax.find("c:crossAx", ns).get("val"), cat_id)

            # THE RINGS: valAx majorGridlines (the radar skeleton — the bug that bit)
            self.assertIsNotNone(val_ax.find("c:majorGridlines", ns),
                                 "radar valAx must have majorGridlines (the concentric rings)")

            # cache == workbook (standard classic-chart invariant)
            cache = []
            for ser in sers:
                cache.extend(float(pt.find("c:v", ns).text)
                             for pt in ser.findall("c:val/c:numRef/c:numCache/c:pt", ns))
            wbs = [n for n in names if n.startswith("xl/embeddings/") and n.endswith(".xlsx")]
            ws = load_workbook(io.BytesIO(pptx.read(wbs[0]))).active
            wb = []
            for col in ("B", "C"):
                r = 2
                while ws[f"{col}{r}"].value is not None:
                    wb.append(float(ws[f"{col}{r}"].value)); r += 1
            self.assertEqual(sorted(cache), sorted(wb), "cache must equal workbook")