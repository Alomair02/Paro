# CHARTEX_SPEC.md — Statistical & Hierarchical Charts (the `cx:` family)

Status: DESIGN. Not yet built. Scope this fully, build it in phases (below).
Companion to `CHART_SPEC.md` — read that first; this reuses its data/style/finish split.

---

## 0. Why this is its own spec (and its own part type)

chartEx charts are **not** more types in the classic `c:` chart system. They are a
**separate OOXML part** with a different namespace, a different root, a different data
model, and a different grammar. The name "chartEx" is misleading: treat it as a sibling
of the chart system, not an extension of it. What transfers from `CHART_SPEC` is the
*method and the surrounding plumbing* (local namespace declaration, embedded workbook,
graphicFrame on the slide, style/finish reuse), NOT the XML.

### The validation reality — read before building anything

chartEx support in **LibreOffice is brand-new and partial** (added 2025, marked "narrow
input path", "TODO" across branches, "charts lost on input/re-export"). That means:

> **LibreOffice may render a chartEx chart blank or wrong even when the XML is correct.**
> Our normal loop (emit → render in LibreOffice → eyeball) has a BROKEN final step here.

Consequences for how we work this sprint:
- **Ground truth is real desktop PowerPoint**, not LibreOffice. The human has confirmed
  access. Each type is "done" only when it opens correctly in real PowerPoint.
- **Per-iteration check is structural**, not visual: validate the emitted XML against the
  known-good PowerPoint-emitted sample (below) and, when wired, against the MS-ODRAWXML
  XSD. LibreOffice "renders nothing" is NOT evidence the XML is wrong.
- **Treat each PowerPoint open as a milestone gate**, not an every-iteration step.

---

## 1. The `cx:` part — confirmed grammar

Namespace: `http://schemas.microsoft.com/office/drawing/2014/chartex` (prefix `cx:`).
Declared **locally on the chartEx part root only** — never in the global NSMAP (same rule
that `c:` follows; the golden tests enforce namespace locality).

Part path: `ppt/charts/chartEx{N}.xml` (note: chartEx, not chart). Content-type and
relationship type are the **ChartEx** variants (verify exact strings against MS-ODRAWXML
section 2.1.5 before building — do NOT reuse the classic chart content-type).

Confirmed structure (from a real PowerPoint-emitted treemap part + MS-ODRAWXML schema):

```
cx:chartSpace  (xmlns:cx, xmlns:a, xmlns:r)
  cx:chartData
    cx:externalData  r:id="rIdN" cx:autoUpdate="0"     ← points at embedded workbook
    cx:data id="0"
      cx:strDim type="cat"                              ← category dimension
        cx:f                Sheet1!$A$2:$A$5            ← formula (matches workbook)
        cx:lvl ptCount="N"
          cx:pt idx="0" … (the cached category strings)
      cx:numDim type="size"                             ← value dimension ("size" for treemap/funnel)
        cx:f                Sheet1!$B$2:$B$5
        cx:lvl ptCount="N" formatCode="General"
          cx:pt idx="0" … (the cached numeric values)
  cx:chart
    cx:title …                                          ← optional
    cx:plotArea
      cx:plotAreaRegion
        cx:series layoutId="{TYPE}" uniqueId="{GUID}"
          cx:tx …            (series name, optional)
          cx:spPr …          (DrawingML fill/line/effects — reuse make_* helpers)
          [type-specific layout sub-elements — see §4, VERIFY per type]
          cx:dataId val="0"  (binds series to the cx:data block)
```

### Cache-equals-workbook invariant (same as classic charts)
The `cx:pt` cached values in `cx:strDim`/`cx:numDim` MUST equal the embedded workbook
cell values. The `cx:f` formulas must point at the cells the workbook fills. This is the
chartEx form of the cache==workbook invariant; guard it with a test exactly like the
classic chart test does.

### Data-model note — the BIG difference from classic charts
Classic `c:` uses `c:cat` + `c:val` *inside each series*. chartEx hoists the data UP into
`cx:chartData/cx:data` (shared, id'd) and the series merely *references* it via `cx:dataId`.
- **Flat types** (funnel, waterfall, histogram, boxWhisker, pareto): one `cx:strDim type="cat"`
  + one `cx:numDim` — the SAME flat shape our resolver already produces. Reusable.
- **Hierarchical types** (treemap, sunburst): the category dimension has MULTIPLE `cx:lvl`
  levels (parent, child, leaf) inside one `cx:strDim`. This is the new data model and
  needs new DSL grammar (§5). This is why hierarchical is a separate phase.

---

## 2. Confirmed layoutId values (from LibreOffice TYPEID enum + MSO output)

| Type        | layoutId         | family       | data shape                    |
|-------------|------------------|--------------|-------------------------------|
| funnel      | `funnel`         | statistical  | flat cat + value              |
| waterfall   | `waterfall`      | statistical  | flat cat + value (+ subtotals)|
| histogram   | `histogram`      | statistical  | values (auto-binned) OR bins  |
| box-whisker | `boxWhisker`     | statistical  | values per category           |
| pareto      | `paretoLine` (+ `clusteredColumn`) | statistical | TWO series in one part |
| treemap     | `treemap`        | hierarchical | multi-level cat + size        |
| sunburst    | `sunburst`       | hierarchical | multi-level cat + size        |

(`regionMap` exists too — geographic — explicitly OUT OF SCOPE, needs map data.)

**Pareto is two series**, not one (`clusteredColumn` + `paretoLine` in one plotAreaRegion).
It is the most complex statistical type, not the simplest. Do NOT pick it to prove the
machinery — pick funnel or waterfall.

---

## 3. DSL surface

Reuse the existing `<chart>` element. Add the new types to the `type` allowlist. Flat
types need NO new DSL — they use `<categories>` + a single `<series>` of `<point value=…>`,
exactly like today:

```xml
<chart type="funnel" title="Pipeline" x="1in" y="1in" w="6in" h="4in">
  <categories>Leads, Qualified, Proposal, Won</categories>
  <series name="Count"><point cat="Leads" value="1000"/> … </series>
</chart>
```

Waterfall adds optional per-point subtotal marking (a point that is a running total, drawn
as a full column to the axis):

```xml
<point cat="Net" value="0" subtotal="true"/>
```

Hierarchical types need NEW grammar (Phase 2) — nested `<node>`:

```xml
<chart type="treemap" title="Budget">
  <node label="Eng">
    <node label="Backend" value="40"/>
    <node label="Frontend" value="30"/>
  </node>
  <node label="Sales" value="50"/>
</chart>
```

`<node>` is recursive: a node with children is a branch (its value = sum of children or
explicit), a node with `value` and no children is a leaf. Parser surface + a recursive
resolver walk produce the multi-level `cx:lvl` cache. This is the bulk of Phase 2's work
and is independent of the `cx:` part machinery proven in Phase 0/1.

---

## 4. Per-type layout sub-elements — VERIFY before building each

The `cx:series` for each type carries layout properties in `CT_SeriesLayoutProperties`
(MS-ODRAWXML, confirmed to exist; fields NOT yet read field-by-field). Before building a
given type, read that complex type and the type's `layoutPr`/`subtotals` children from the
MS-ODRAWXML schema and confirm against a real PowerPoint-emitted sample of THAT type.
Known so far:
- **funnel**: simplest — series + dataId, minimal layout props. Best Phase-0 candidate.
- **waterfall**: needs a `subtotals` list marking which indices are totals. VERIFY element name/shape.
- **boxWhisker**: needs quartile method config. VERIFY.
- **histogram**: needs binning config (bin count/width/auto). VERIFY.
- **pareto**: two series; second is `paretoLine`. VERIFY axis binding.
- **treemap/sunburst**: multi-level `cx:strDim`; series mostly default. The work is in DATA, not layout.

Rule: **never invent a layout field.** If the schema/sample doesn't confirm it, leave it
out and test what minimal output PowerPoint accepts — add fields only as needed.

## 5. Style / finish reuse

`cx:spPr` takes the SAME DrawingML fill/line/effect children as classic charts, so the
`make_solid_fill`/`make_gradient_fill`/`make_ln`/`make_effect_list` helpers and the
`ChartStyleRegistry` style/finish bundles apply unchanged. Palette assigns per-point colors
for single-series statistical types (funnel/waterfall slices), per-leaf for treemap/sunburst.
Range-safe color helpers still guard lumMod/lumOff ≤ 100000.

---

## 6. Build phases (each gated; never two unknowns at once)

**Phase 0 — prove the `cx:` part machinery on ONE type (funnel).**
New `ChartExBuilder` (separate from chart_part_builder), local `cx:` namespace, the
chartData/data/series structure, embedded workbook, ChartEx content-type + relationship,
graphicFrame on slide via the existing `assemble_package` part-wiring. Hardcode one funnel.
GATE: opens correctly in real PowerPoint. Until this passes, build nothing else — this is
the riskiest unknown (can we emit a cx: part MSO accepts at all), isolated.

**Phase 1 — rest of statistical** (waterfall, histogram, boxWhisker, pareto).
Same part machinery, different layoutId + per-type layout props (§4, verify each). Generalize
from hardcoded to resolver-driven flat data. Pareto last (two-series). GATE each in PowerPoint.

**Phase 2 — hierarchical** (treemap, sunburst) + the nested `<node>` DSL.
New parser surface + recursive resolver producing multi-level `cx:lvl`. Builds on the proven
cx: builder, so the only new thing is the data model. GATE in PowerPoint.

Lock each phase with a property test: part exists, cache==workbook (cx form), correct
layoutId per type, no lumMod/lumOff > 100000. Structural assertions, not byte-match.

---

## 6b. Phase-0 prerequisites — RESOLVED (confirmed from MS-ODRAWXML 2.1.5)

These were the can't-guess facts. Now pinned:

- **Content type:** `application/vnd.ms-office.chartex+xml`
- **Relationship type:** `http://schemas.microsoft.com/office/2014/relationships/chartEx`
  (NOTE: `schemas.microsoft.com/office/2014/relationships`, NOT the OOXML
  `schemas.openxmlformats.org/...` used by classic charts. Different host. Getting this
  wrong fails the part.)
- **chartEx content namespace:** `http://schemas.microsoft.com/office/drawing/2014/chartex`
  (the `cx:` prefix). Different 2014 URI from the relationship one above — don't conflate.
- **Part path:** `ppt/charts/chartEx{N}.xml`

Minimal funnel target (cache-only, no workbook yet — prove the part first, add workbook
second, exactly as classic charts were sequenced):

```xml
<cx:chartSpace xmlns:cx="http://schemas.microsoft.com/office/drawing/2014/chartex"
               xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
               xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <cx:chartData>
    <cx:data id="0">
      <cx:strDim type="cat"><cx:f>Sheet1!$A$2:$A$5</cx:f>
        <cx:lvl ptCount="4"><cx:pt idx="0">Leads</cx:pt>…</cx:lvl></cx:strDim>
      <cx:numDim type="val"><cx:f>Sheet1!$B$2:$B$5</cx:f>
        <cx:lvl ptCount="4" formatCode="General"><cx:pt idx="0">1000</cx:pt>…</cx:lvl></cx:numDim>
    </cx:data>
  </cx:chartData>
  <cx:chart><cx:plotArea><cx:plotAreaRegion>
    <cx:series layoutId="funnel" uniqueId="{GUID}"><cx:dataId val="0"/></cx:series>
  </cx:plotAreaRegion></cx:plotArea></cx:chart>
</cx:chartSpace>
```

## 7. Open questions to resolve before/while building (do not guess)

0. **At the Phase-0 PowerPoint gate:** if PowerPoint repairs/rejects the minimal funnel,
   toggle in this order: (a) `cx:numDim type="val"` vs `"size"`; (b) add `cx:externalData`
   + workbook; (c) confirm `uniqueId` GUID is required; (d) check whether `cx:plotArea`
   needs a `cx:spPr`/region children PowerPoint expects. Change ONE thing per gate trip.

1. Exact ChartEx **content-type string** and **relationship-type URI** (MS-ODRAWXML 2.1.5).
2. Does the embedded workbook for chartEx differ from the classic chart workbook? (Likely
   same .xlsx shape; verify the `cx:f` formula sheet name matches what we write.)
3. `CT_SeriesLayoutProperties` field-by-field for waterfall subtotals, boxWhisker quartiles,
   histogram bins.
4. Does PowerPoint require `uniqueId="{GUID}"` on every series, or tolerate omission? (Sample
   has it; generate a GUID per series to be safe.)
5. Minimal valid funnel: smallest set of children PowerPoint accepts without repair.
