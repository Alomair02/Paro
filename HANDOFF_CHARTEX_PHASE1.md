# Paro chartEx — Phase 1 Handoff (refreshed)

Supersedes the pre-compaction summary (which described a 2-type, mid-legend state).
Working method unchanged: human writes/runs all code, assistant reviews; small verifiable
steps; **ground truth = opens clean in real desktop PowerPoint** (LibreOffice + PowerPoint
Online are NOT trustworthy for chartEx). Per-iteration check = structural diff vs a known-good
sample in `/tmp/samples.pptx` (re-downloadable, ~244k, made in desktop PowerPoint; contains
funnel/waterfall/treemap/boxWhisker/histogram + classic charts, each with custom titles).

## STATUS: 5 chartEx types DONE (built, DSL-wired, PowerPoint-gated, test-locked)

| type       | layoutId           | data model                                    | path    | locked test |
|------------|--------------------|-----------------------------------------------|---------|-------------|
| funnel     | funnel             | flat: categories + 1 value each               | generic | yes |
| waterfall  | waterfall          | flat + subtotals (running-total indices)      | generic | yes |
| histogram  | clusteredColumn(!) | NO categories — raw values, PP auto-bins      | generic | yes |
| boxWhisker | boxWhisker         | multi-series: N data blocks, raw observations | generic | yes |
| pareto     | clusteredColumn + paretoLine | raw observations, PP aggregates+ranks | **dedicated (Path B)** | yes |

Suite 97 green. Tests in `tests/test_chartex.py`, class `TestChartEx`. Each test asserts: layoutId,
the type's distinguishing feature, cache==workbook, rels triple. All guards bite-verified (break →
fail → restore). Legend assertions folded into funnel (no legend) + waterfall (legend pos=t) tests.

## ARCHITECTURE — the spec map (registry seam; "add a type = a data change")

`builders/chartex_part_builder.py` holds `CHARTEX_TYPES`, a dict keyed by type with SIX per-type knobs:
- `layout_id` — series layoutId string (note histogram→"clusteredColumn", NOT "histogram")
- `style` — name of style asset (loads `{style}_style.xml`)
- `axes` — `lambda sd -> list[axis_el] | None`  (None → builder default single catScaling axis)
- `layout_pr` — `lambda sd -> (lambda s_idx -> element | None)`  ← FACTORY form, see GOTCHA below
- `data_labels` — dict of visibility attrs, or None (no dataLabels element)
- `data_labels_pos` — optional top-level key (waterfall only: "outEnd")
- `legend` — dict {pos,align,overlay} or None (type default; DSL can override)

`build_chartex_part_xml(workbook_rid, categories, series_list, layout_id, data_labels,
  data_labels_pos=None, title=None, layout_pr=None, axes=None, legend=None)`:
- Loops `series_list` → N `cx:data` blocks (id=str(s_idx)), each strDim($A) + numDim(col B+s_idx).
  `if categories:` builds strDim; else (histogram) numDim references col A, no strDim.
- Loops `series_list` → N `cx:series` (uniqueId=`_series_guid(s_idx)`, dataId=str(s_idx)),
  each gets dataLabels (if not None), layout_pr factory called per s_idx, layoutId.
- N=1 reproduces single-series output BYTE-IDENTICAL (regression anchor = the 3 single-series tests).
- legend emitted as child of `cx:chart` AFTER plotArea (schema order critical).

`emit_chartex(shape_data, ...)` — type-agnostic wiring (workbook, style/colors parts, rels,
graphicFrame). Reads spec, resolves legend (DSL `legend` "t"/"none" overrides spec default),
calls builder. Single emission path; all parts ride `slide_state.chart_parts`.

PATH B — dedicated builders for structurally-distinct types. `emit_chartex` branches:
`if "build" in spec:` → calls `spec["build"](workbook_rid, categories, series_list, title=...)`
(pareto's dedicated `build_pareto_part_xml`); `else:` → the generic spec-driven `build_chartex_part_xml`.
ALL generic-path spec reads (layout_id, data_labels, layout_pr, axes, legend) live INSIDE the else,
so a Path-B type's minimal spec ({"style","build"}) never KeyErrors on generic keys. Shared wiring
(workbook/style/colors/rels/graphicFrame) runs for both. This is the documented extension point for
future types that don't fit the common shape. Rule: build Path B for ONE oddball; if a SECOND
similar type appears, generalize the dedicated path from two real examples (don't pre-abstract).

`build_pareto_part_xml(workbook_rid, categories, series_list, title=None)` — pareto's body:
ONE data block (raw observations); TWO asymmetric series — clusteredColumn (has dataId=0,
`<cx:layoutPr><cx:aggregation/></cx:layoutPr>`, `<cx:axisId val="1"/>`) + paretoLine (DERIVED:
`ownerIdx="0"` attr, no dataId, only `<cx:axisId val="2"/>`); THREE axes — catScaling(0),
valScaling+majorGridlines(1, count), valScaling max=1/min=0 + `<cx:units unit="percentage"/>`(2, %).

Helpers: `_waterfall_layout_pr(subtotal_indices)`, `_binning_layout_pr(interval_closed)`,
`_boxwhisker_layout_pr()`, `_two_axes(cat_gap)` (cat catScaling + val valScaling/majorGridlines),
`_series_guid(s_idx)` = `{00000000-0000-0000-0000-{s_idx+1:012d}}` (idx0→...001 byte-identical to old).

## ASSETS — builders/chartex_assets/
- `chartex_colors.xml` — SHARED across all types (verified md5-identical: 25cfc3...).
- `{funnel,waterfall,histogram,boxwhisker}_style.xml` — PER-TYPE (each differs; verified).
- pareto SHARES histogram's style (verified md5-identical 57ec...; spec "style":"histogram",
  no separate pareto asset). Both are PowerPoint "histogram family" charts.
  Style parts theme-aware (schemeClr accent1..6, not hardcoded hex).

## RESOLVER (transpiler/resolver.py) + DISPATCH (builders/slide_builder.py)
- `CHARTEX = {"funnel","waterfall","histogram","boxWhisker","pareto"}`; type tag emits chart_type if in CHARTEX.
- Category synthesis guarded: `if not categories and all("cat" in p.attrs for p in points)` —
  so histogram (bare value points) leaves categories=[] (no-strDim path).
- `subtotals` collected from first series' points marked `subtotal="true"` → shape_data["subtotals"].
- `legend` captured from `<chart legend=...>` → shape_data["legend"] (DSL override).
- Parser point allowlist includes "subtotal". Dispatch routes all 5 types to emit_chartex.

## LEGEND — unified across classic + chartEx (Option 2, done)
- chartEx: spec-map default per type (waterfall=t, others none), DSL `legend="t"/"none"` overrides.
- CLASSIC charts (chart_part_builder.py): now ALSO honor DSL `legend` — `legend_pos = legend or
  style.get("legendPos","b")`. So `legend="t"` means top legend on EVERY chart type. The previously
  dead DSL `legend` attr is now consumed for both families. Classic supports t/b/l/r/none (full
  OOXML); chartEx verified only for t/none.

## GOTCHAS / hard-won
- **layout_pr MUST be a per-series factory** `(s_idx)->fresh element`, NOT a prebuilt element:
  lxml gives an element one parent, so appending the same element to N series RELOCATES it.
  Each series needs its own fresh layoutPr.
- **histogram layoutId is "clusteredColumn"** — histogram-ness is the binning layoutPr, not the id.
- **DATA-SHAPE CONTRACT (critical for agent layer):** statistical types (boxWhisker, histogram,
  pareto) consume RAW OBSERVATIONS, not pre-aggregated values. categories repeat (boxWhisker,
  pareto) or are absent (histogram); len(categories)==len(each series.values), parallel rows.
  pareto: PP counts+ranks the observations (values typically all 1). Feeding summary values →
  degenerate plots (single-point "boxes", uncounted bars). Agent MUST know this per-type.
- **histogram has NO dataLabels** (sample-verified; old hardcoded value="1" was spurious).
- chartEx acceptance contract (from Phase 0, still holds): cx: part needs embedded workbook +
  externalData (cache-only rejected), chartStyle + chartColorStyle sibling parts, cx: namespace
  declared LOCALLY (never global NSMAP). 3 URIs not to conflate: cx ns =.../2014/chartex;
  rel =.../2014/relationships/chartEx (microsoft.com); content-type = vnd.ms-office.chartex+xml.

## PENDING
1. **treemap / sunburst (Phase 2)** — hierarchical: multi-level cx:lvl strDim, numDim type="size",
   parentLabelLayout. Needs NEW DSL grammar (nested <node>, not flat categories) → parser+resolver
   work, not just a spec-map row. treemap sample exists in samples.pptx (3 lvls Leaf/Stem/Branch).
   Likely another Path-B dedicated builder (hierarchical data won't fit the flat series loop).

## Phase-1 deferred (cosmetic, not blocking)
- Title uses minimal bodyPr (no sz/color); sample has cosmetic sz/effectLst we omit. Works.
- float .0 in caches engine-wide (_chart_number does float() unconditionally); PP renders fine.
- box-plot data labels left off (clean, conventional). If labelling wanted: make a labelled box
  plot in PP, read its dataLabels structure, mirror. Not pursued.
