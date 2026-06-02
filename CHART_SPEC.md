# Charts — Design Specification (v1)

This is the design-spec-first artifact for native charts. It mirrors the timeline spec's structure and reuses its proven split — **data model / mechanism / style / finish** — because that pattern survived the timeline sprint and is meant to generalize to every visual family. The difference: a chart is **Tier-2**. Unlike the timeline (a composite that lowers to shapes), a chart is a **native OOXML chart part** — a separate `chart1.xml` with its own namespace, embedded data, and relationship. The engine work is heavier; the authoring pattern is the same.

The governing decision for v1: **build the first-class chart types excellently, then compose the complex ones from them.** This is not a compromise — it is how OOXML itself works. Combo charts *are* multiple first-class plot types sharing axes. Many "complex" charts are compositions or data-transforms of primitives. So the core types are literally the material the complex tier is built from. Build the core right and the complex tier becomes reachable, not a second engine.

---

## 1. Data Model (style-independent, author-provided)

What `<chart>` carries in the DSL. Shared across nearly all chart types — the same series/category/value structure drives column, bar, line, area, pie, and scatter. This never changes when chart *types* or *styles* are added.

```xml
<chart type="column" title="Revenue by region">
  <categories>EMEA, APAC, Americas</categories>      <!-- the x-axis / slice labels -->
  <series name="2025" tone="accent1">
    <point cat="EMEA" value="42"/>
    <point cat="APAC" value="31"/>
    <point cat="Americas" value="58"/>
  </series>
  <series name="2026" tone="accent2">
    <point cat="EMEA" value="50"/>
    <point cat="APAC" value="38"/>
    <point cat="Americas" value="64"/>
  </series>
</chart>
```

| `<chart>` attribute | Values | Default | Notes |
|---|---|---|---|
| `type` | `column`, `bar`, `line`, `area`, `pie`, `scatter` | required | The first-class type (v1). One blessed enum; complex types added later. |
| `title` | string | none | Chart title; omit for no title |
| `style` | registered style name | per-type default | Resolved via ChartStyleRegistry |
| `finish` | registered finish name | per-style default | Overrides the style's finish for this chart |
| `legend` | `none`, `top`, `bottom`, `left`, `right` | per-style | Legend placement |
| `stacked` | `false`, `true`, `percent` | `false` | For column/bar/area: clustered (false), stacked, or 100%-stacked |
| `w`, `h`, `x`, `y` | unit / `%` | from container | Geometry |

| `<series>` attribute | Values | Default | Notes |
|---|---|---|---|
| `name` | string | required | Series name (legend label) |
| `tone` | theme token / hex | from palette | Series color; `tone` (semantic), resolved by the style/theme |
| `axis` | `primary`, `secondary` | `primary` | Reserved for combo/dual-axis; ignored by single-type v1 charts |

| `<point>` attribute | Values | Default | Notes |
|---|---|---|---|
| `cat` | category label | required (category charts) | Must match a `<categories>` entry |
| `value` | number | required | The y-value |
| `x`, `y` | number | required (scatter) | Scatter uses x/y pairs instead of cat/value |

Scatter is the one type with a different point shape (x/y pairs, no categories). Everything else shares the categories + series-of-values model. The data model is **intent only** — it says *what the numbers are*, never how the chart looks. Bar color is `tone` (semantic), resolved through the style/theme, exactly like timeline tasks.

**Data cache requirement (Tier-2 specific):** a native chart embeds a *cached copy* of its data inside the chart part (`c:numCache`/`c:strCache`), AND references an embedded spreadsheet part (`xl/embeddings/`). PowerPoint reads the cache to render and uses the embedded workbook when the user edits the chart. Both must be emitted and must agree. This is the core engine difference from the timeline.

---

## 2. Mechanism (v1: the native classic-chart part)

One mechanism backs all six first-class types: the **classic `c:` chart part** (`CT_ChartSpace`). Unlike the timeline's bars-in-columns (which lowered to shapes), this emits a real chart part. The six types differ only in which plot-type element sits inside `c:plotArea`:

- `column` / `bar` -> `c:barChart` with `c:barDir` = `col` / `bar`
- `line` -> `c:lineChart`
- `area` -> `c:areaChart`
- `pie` -> `c:pieChart` (single series; extra series ignored with a warning)
- `scatter` -> `c:scatterChart` (uses x/y point pairs)

The mechanism is responsible for emitting, in valid order, the parts and elements PowerPoint requires:

1. **The chart part** (`charts/chart1.xml`): `c:chartSpace` -> `c:chart` -> `c:plotArea` -> the plot-type element with `c:ser` children; each `c:ser` carries `c:tx` (series name), `c:cat` (categories, as `c:strRef`/`c:numRef` with cache), `c:val` (values, as `c:numRef` with `c:numCache`), and `c:spPr` (series fill/finish). Plus axes (`c:catAx`/`c:valAx` for category charts, two `c:valAx` for scatter), `c:legend`, `c:title`.
2. **The embedded workbook** (`xl/embeddings/Microsoft_Excel_Worksheet1.xlsx` or equivalent): a minimal spreadsheet holding the same data, so the chart is editable. Registered as a relationship from the chart part.
3. **Relationships and content-types**: the slide references the chart via a `graphicFrame` -> `a:graphic` -> `c:chart` relationship; the chart part references its embedded workbook; content-types declare the chart part and the spreadsheet part. (This is where Tier-2 is genuinely heavier than Tier-1 — multiple new parts and rels, all of which PowerPoint validates strictly.)
4. **The `graphicFrame` on the slide**: charts sit in a `p:graphicFrame` with the chart relationship, positioned by the resolver like any other block (managed box, free geometry, or placeholder="chart").

Axis handling, gridlines, legend, data labels, and title are emitted per the resolved **style** (next section). The data cache must exactly mirror the embedded workbook values.

The resolver's job (transpiler side) is unchanged in spirit: compute the chart's box (managed/free/placeholder), resolve type+style+finish through the registry, hand the engine a chart spec. The *engine* (a new `ChartBuilder` beside the other part builders) owns emitting the native part, the data cache, and the embedded workbook.

---

## 3. Style-Definition Schema (the long-lived contract)

A chart style is a curated bundle of visual parameters — the same idea as timeline styles, adapted to chart anatomy. New styles are a definition in the **ChartStyleRegistry**, never resolver/engine code. Fields:

| Field | Type | Purpose |
|---|---|---|
| `palette` | list of theme tokens | Series colors, cycled in order |
| `paletteMode` | `cycle`, `monochrome`, `sequential` | How palette maps to series |
| `gridlines` | `none`, `major`, `major-minor` | Value-axis gridlines |
| `gridColor` | token / hex | Gridline color |
| `gridWidth` | unit | Gridline stroke width |
| `axisColor` | token / hex | Axis line + tick color |
| `axisLabelRole` | type-scale role | Font role for axis labels (reuses the type scale) |
| `titleRole` | type-scale role | Font role for the chart title |
| `legendRole` | type-scale role | Font role for legend text |
| `legendPosition` | `none`, `top`, `bottom`, `left`, `right` | Default legend placement (DSL `legend` overrides) |
| `dataLabels` | `none`, `value`, `percent`, `category` | Whether/what data labels show |
| `dataLabelRole` | type-scale role | Font role for data labels |
| `plotBorder` | boolean | Border around the plot area |
| `gapWidth` | percent | Bar/column gap width (clustering tightness) |
| `finish` | registered finish name | Default series finish (see §4) |

Two rules carried from the timeline discipline:
- **Fonts come from the type scale, not hardcoded sizes.** Axis/title/legend/label roles resolve through the theme's type scale — same anti-drift, re-skinnable behavior as everywhere else.
- **Colors come from theme tokens, not literals**, so a chart re-skins with the deck.

---

## 4. Finish-Definition Schema (series surface treatment)

Charts reuse the **finish preset** concept proven on the timeline: a named, curated bundle of series-surface properties, selected per-style with per-chart override (`finish="..."`). Good finish is a small set of coordinated choices, never raw knobs. Finish applies to the **series marks** (bars, columns, areas, slices, line markers). Fields:

| Field | Type | Purpose |
|---|---|---|
| `fillMode` | `solid`, `gradient`, `tinted` | Series fill treatment |
| `border` | `none`, `tone-matched`, `contrast` | Series mark border |
| `borderWidth` | unit | Border thickness |
| `shadow` | `none`, `soft`, `elevated` | Series mark shadow (`outerShdw` params) |
| `cornerRadius` | unit | Rounded corners (column/bar marks) |
| `lineWidth` | unit | Stroke width (line/scatter series) |
| `markerStyle` | `none`, `circle`, `square`, `diamond` | Point markers (line/scatter) |

**Critical constraint learned the hard way:** all color transforms (`lumMod`/`lumOff` for tints/gradients) MUST stay within the valid 0-100000 range. To lighten, use `lumOff`, never `lumMod` above 100000. The engine must clamp/reject out-of-range luminance values. (This was a real repair-triggering bug in the timeline gradient; the chart finishes must not repeat it.)

---

## 5. Initial Style + Finish Definitions (shipped in v1)

A curated starter set — enough to look excellent across the six types, expandable later. Each is one entry in its registry.

### Chart styles
- **`clean`** (default): single-accent or cycled palette, major horizontal gridlines (low-emphasis), no plot border, legend bottom, no data labels, axis/title/legend roles = `caption`/`heading`/`caption`. The neutral, professional default.
- **`minimal`**: no gridlines, no axis lines (or very light), no legend border, data labels on (`value`), monochrome-to-sequential palette. Calm, label-driven — good for single-series emphasis.
- **`editorial`**: cycled accent palette, major-minor gridlines, plot border, legend top, bolder title role. More structured/reporty.
- **`vivid`**: full accent-cycle palette, no gridlines, data labels `value`, slightly larger gap width for punch. Presentation-forward.

### Finish presets (reuse timeline finishes where sensible, adapted to series marks)
- **`flat`**: solid fill, no border, no shadow, square (or 2pt) corners.
- **`soft-shadow`**: solid fill, no border, subtle `soft` shadow, 3pt corners.
- **`outlined`**: tinted fill, tone-matched 1pt border, no shadow.
- **`gradient-subtle`**: in-range two-stop gradient (lighten via `lumOff`, NOT lumMod>100000), soft shadow, 3pt corners.

Per-type sensible defaults (e.g. `line`/`scatter` default to a `flat` finish with `markerStyle=circle` and a sensible `lineWidth`; `column`/`bar` default to `clean`+`flat`; `pie` to `clean` with `dataLabels=percent`). The registry holds these mappings.

---

## 6. From First-Class to Complex (how the core composes upward)

This section is the point of building the core well. The complex types are **not a second engine** — they are compositions, configurations, or alternate parts built from or beside the core. Documented here so the architecture anticipates them; deferred from v1 build.

- **Stacked / 100%-stacked** (column/bar/area): already in v1 via the `stacked` attribute — a configuration of the existing plot types, not new types. (Listed here to note it's the first step up.)
- **Combo charts**: multiple first-class plot-type elements (`c:barChart` + `c:lineChart`) inside one `c:plotArea`, with the `axis="secondary"` series attribute (reserved in the data model) wiring a secondary `c:valAx`. This is *literally the v1 types sharing axes* — reachable once the core emits axes correctly. The data model already carries `axis`; v1 ignores it, the combo extension honors it.
- **Statistical** (histogram, box-whisker, waterfall, funnel): these are NOT classic `c:` charts — they live in the newer **chartEx (`cx:`) part** (Office 2016+), a different part type. They reuse the data model and the style/finish pattern, but need a second mechanism (a `ChartExBuilder`). Scoped as a distinct future sprint, not a tweak.
- **Hierarchical** (treemap, sunburst): also **chartEx (`cx:`)**, same as statistical — a `ChartExBuilder` concern. (Org-chart/tree *diagrams*, if ever wanted, are a Tier-1 composite that lowers to shapes — a timeline-like sprint, not a chart at all. Noted so the boundary is explicit.)

So the expansion ladder is: v1 core (six classic types) -> stacked (config, in v1) -> combo (compose core types + secondary axis) -> chartEx engine (statistical + hierarchical, a second mechanism) -> tree composites (separate, shape-based). Each rung reuses the data/style/finish contract; only chartEx introduces a genuinely new part type.

---

## 7. Expansion Seam (why future chart sprints are cheap)

- **New style or finish, existing types** -> add a definition to the ChartStyleRegistry / finish registry. No engine change.
- **New first-class type within classic `c:`** -> add the plot-type emission to ChartBuilder + the type to the enum. Small, because the part/cache/workbook machinery is shared.
- **Combo** -> honor the reserved `axis` attribute + emit multiple plot-type children + secondary axis. Isolated to ChartBuilder.
- **chartEx types (statistical/hierarchical)** -> a new `ChartExBuilder` (the `cx:` part) reusing the data model, style, and finish registries. A dedicated sprint, but the authoring surface and style system are already there.
- **Theme-supplied chart styles** -> the ChartStyleRegistry later loads definitions from the theme/design-system, so a corporate template ships its own chart look. DSL and engine untouched.

The same data/mechanism/style/finish split now spans timelines AND charts — confirming it as the standing pattern every visual family inherits.

---

## 8. v1 Scope

**In v1 (build excellently):** `<chart>` data model (`<categories>`, `<series>`, `<point>`); the six first-class types (`column`, `bar`, `line`, `area`, `pie`, `scatter`); `stacked`/`percent` for the applicable types; the native `c:` chart part with embedded data cache AND embedded workbook; correct relationships/content-types; the `graphicFrame` placement (managed/free/placeholder="chart"); the ChartStyleRegistry with the four styles and four finishes; type-scale-driven fonts; theme-token colors; in-range luminance only. Charts open and are editable in real PowerPoint.

**Deferred (spec'd, seam ready):** combo/dual-axis (data model's `axis` reserved); chartEx statistical (histogram, box-whisker, waterfall, funnel) and hierarchical (treemap, sunburst) via a future `ChartExBuilder`; tree/org diagrams as a separate shape composite; theme-supplied chart styles; data-label leader lines and advanced axis formatting.

**Validation requirement (Tier-2 specific):** because charts emit multiple new parts that PowerPoint validates strictly, the data cache must exactly match the embedded workbook, child-element ordering in `c:` elements must follow the schema, and all color transforms must be in range. Render in real PowerPoint (or LibreOffice on Linux as the practical bar) and confirm the chart both displays AND is editable, not just that the package opens.
