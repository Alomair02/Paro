# Slide DSL — Schema Specification (v2, generation-first)

This is the contract between the agent (which generates this XML), the transpiler (which parses and resolves it), and the engine (which emits OOXML). It is a design document, not code. Pin it down before building the parser.

**This DSL is a generation format, not a replication format.** Its job is to let an agent produce clean, correct new slides from intent. It is deliberately *not* a pixel-faithful clone format for existing corporate decks. Reproducing an existing template's exact slides is the job of the **ingestion layer** (OOXML to design system), not this DSL. When you point the system at a company template, the ingestion layer extracts its *theme, layouts, color tokens, and fonts* — a reusable design system the agent then generates against. It does not reproduce the original slides. This boundary is load-bearing: it is why the grammar can stay simple.

---

## 1. Philosophy

A slide is a **tree of containers**. Each container chooses a layout strategy for its children. Everything resolves to absolute EMU coordinates in the transpiler's layout pass before reaching the engine — which already knows how to emit a flat shape tree.

This is the model used by CSS (grid / flex / absolute), Figma (auto-layout / absolute), and SwiftUI (VStack / HStack / ZStack / offset). It is deliberately familiar, because a GUI built on top of this maps onto it directly.

Four design rules drive every decision below:

1. **Scalar properties are attributes; structured or repeating content is child elements.** `bold`, `size`, `fill` are attributes. Paragraphs, grid cells, reusable definitions are child elements.
2. **Managed containers are the default and the happy path; `<free>` is a rare, deliberate escape hatch.** `<stack>` and `<grid>` own spacing and bounds, so text is always measured against a known box. This is what prevents the overflow / overlap / spacing bugs. An agent should reach for `<free>` only when it explicitly wants freeform placement — and the validator treats `<free>` as the only place overlap can occur.
3. **Omission means inherit.** A property not written is not emitted, so the value falls through the OOXML inheritance chain (slide to layout to master to theme). This is what prevents font-size drift between slides.
4. **One blessed way to express each thing.** Where two encodings could express the same result, the spec names the one to use. Ambiguity is a defect, because it makes the agent inconsistent with itself.

---

## 2. Core Concepts

### Units
Human-readable strings, parsed by the existing `UnitConverter`:
`"1in"`, `"24pt"`, `"2cm"`, `"10px"`, `"914400emu"`, and `"50%"` (percentage of the containing region's relevant dimension). Never raw EMU integers in authored XML.

### Colors
Two forms, both accepted by the existing `make_solid_fill`:
- **Theme token** (recommended): `accent1`-`accent6`, `dk1`, `lt1`, `dk2`, `lt2`, `bg1`, `tx1`, etc. Resolves through the theme, so the deck is re-skinnable.
- **Hex literal** (escape hatch): `#0B5CAD`. Fixed color, not re-skinnable.

Prefer tokens; use hex only when interoperating with an externally specified brand color the theme does not carry.

### Inheritance
Deck sets defaults, slide overrides, container sets child defaults (gap, padding), block overrides. Text is sized semantically through `role`; the active theme's `typeScale` owns the point size, weight, and paragraph spacing for each role. Explicit `size` is reserved for deliberate one-off emphasis and opts that text out of the theme scale.

### Type Scale
Each registered theme carries a `typeScale` map. The v1 roles are `title`, `heading`, `subheading`, `body`, `bodySmall`, and `caption`. Each role maps to:

```json
{
  "size": 17,
  "minSize": 15,
  "weight": "normal",
  "spaceBefore": "0pt",
  "spaceAfter": "4pt",
  "lineSpacing": 1.18
}
```

`size` and `minSize` are in points, `weight` is `normal` or `bold`, and spacing values are optional. Authors select hierarchy with `role` on `<text>` or `<p>`; the resolver looks up the role through `ThemeRegistry.get(deck.theme)["typeScale"]`. Default role when omitted is `body` — **except** for text bound to a layout placeholder, where the default derives from the placeholder type (`title`/`ctrTitle` → `title`, `subTitle` → `subheading`, `body` → `body`). The type scale therefore always runs: `<text placeholder="title">` and `<text role="title">` produce identically styled text, and an explicit `role` on placeholder text overrides the derived default. `minSize` is the lower bound for optional validator-driven auto-shrink; it is not a second role and does not let text cross into a smaller role's visual territory.

### The layout strategies
Every container is one of three:

| Container | Strategy | Children positioned by | Overlap possible? | Use when |
|---|---|---|---|---|
| `<stack>` | flow in a direction, container owns gaps | order + gap | No (structural) | **Default.** Title-over-body, lists, anything sequential |
| `<grid>` | rows/columns with gutters | col/row/span attrs | No (structural) | Multi-column / comparison layouts |
| `<free>` | absolute coordinates | x/y/w/h attrs | Yes (warned) | Deliberate freeform only — the rare exception |

`<stack>` is the default and the target an agent should reach for first.

---

## 3. Element Reference

### `<deck>`
Root element. Holds defaults and reusable definitions.

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `theme` | theme name | `"default"` | Resolved via ThemeRegistry |
| `size` | `16:9`, `4:3`, `16:10` | `16:9` | Slide dimensions |
| `font` | font family | from theme | Default body font |
| `background` | token / hex / `image:path` | none | Default background for every slide; slide-level `background` overrides |

Children: optional `<theme>` (inline theme def), optional `<defs>` (reusable definitions), one or more `<slide>`.

### `<theme>` (optional, inline)
Inline theme definition, **attribute form only** (this is the one blessed shape — the child-`<colors>`/`<fonts>` form is removed). All twelve OOXML color slots and both fonts are accepted; any omitted slot falls back to the registered `default` theme's value.

```xml
<theme name="deloitte"
       dk1="#000000" lt1="#FFFFFF" dk2="#53565A" lt2="#F2F2F2"
       accent1="#86BC25" accent2="#00A3E0" accent3="#007C89"
       accent4="#43B02A" accent5="#012169" accent6="#ED8B00"
       hlink="#0076A8" folHlink="#7A4183"
       heading="Verdana" body="Verdana"/>
```

Usually you reference a registered theme by name on `<deck>` instead of inlining. Inlining is for one-off decks.

Registered theme data also includes a `typeScale` object for semantic text roles. Inline XML themes inherit the registered default type scale; future design-system ingestion can replace the entire scale in registry data without changing authored slide XML.

### `<defs>`, `<def>`, `<use>`
Deck-level named, reusable elements declared once and referenced on any slide. The mechanism for repeated furniture (logo, footer, page number, draft watermark).

| `<def>` attribute | Values | Default | Notes |
|---|---|---|---|
| `name` | identifier | required | Reference key |
| `auto` | boolean | `false` | If true, applied to every slide automatically without an explicit `<use>` |

```xml
<defs>
  <def name="footer" auto="true">
    <text placeholder="ftr" size="9pt" color="dk2">Acme Corp — Confidential</text>
  </def>
</defs>
```

`auto="true"` defs are emitted on every slide, after that slide's own content (so they layer on top). An `auto` def that targets a placeholder (e.g. `ftr`, `sldNum`) fills the layout's corresponding placeholder; an `auto` def with free geometry is placed identically on each slide. Referenced explicitly with `<use ref="footer"/>`.

> **What belongs in an `auto` def:** genuinely repeating *furniture* that appears identically on every slide — a small footer, a page number, a logo. **Not** content that appears once or that the author chooses per deck. (In the pressure test, one author folded a one-time classification bar into an auto footer, which would wrongly stamp it on every slide.) If it appears on one slide, put it on that slide; if it varies per slide, it is not furniture.

> Note: cloning a *source deck's* master/footer artwork is an **ingestion-layer** concern, not a DSL one. `<defs>` is for furniture the author/agent defines, not for reproducing an existing template's chrome.

### `<slide>`
A slide is itself the root container of its content.

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `layout` | registered layout name | `blank` | Binds placeholders; resolved via LayoutRegistry |
| `flow` | `stack`, `grid`, `free` | `stack` | The slide root's own layout strategy |
| `pad` | unit | from layout | Padding inside the slide edge |
| `gap` | unit | `0.2in` | Gap between root children (if `flow="stack"`) |
| `background` | token / hex / `image:path` | deck background | Per-slide background override |

Children: containers (`<stack>`, `<grid>`, `<free>`) and/or blocks (`<text>`, `<image>`, `<shape>`, `<table>`, `<line>`).

`background` accepts a theme token (`accent5`, `lt2`), a hex literal (`#0F172A`), or an image reference (`image:cover.jpg`). Deck-level background is the default for every slide; slide-level background wins when both are present. Omit both to leave the slide background inherited/white.

### `<stack>`
Flows children in one direction; the container owns the spacing between them.

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `dir` | `v`, `h` | `v` | Vertical or horizontal flow |
| `gap` | unit | inherit | Space between children |
| `align` | `start`, `ctr`, `end`, `stretch` | `stretch` | Cross-axis alignment |
| `justify` | `start`, `ctr`, `end`, `between` | `start` | Main-axis distribution |
| `pad` | unit | `0` | Inner padding |
| `w`, `h` | unit / `%` | auto | Optional explicit size |
| `anchor` | `none`, `top`, `bottom`, `left`, `right`, `fill` | `none` | **New.** Pin the stack to a slide edge; `fill` makes it full-bleed along its main axis. See Edge Anchoring. |
| `fill` | token / hex / `none` | `none` | **New.** Background fill — makes the stack a styled card |
| `line` | token / hex / `none` | `none` | **New.** Border color |
| `lineWidth` | unit | `1pt` | **New.** Border width |
| `radius` | unit | `0` | **New.** Corner radius (for fill/border) |

### `<grid>`
Places children in a column/row grid with gutters.

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `cols` | integer | `12` | Number of columns |
| `rows` | integer | auto | Number of rows (auto from content if omitted) |
| `gap` | unit | `0.2in` | Gutter between cells (both axes) |
| `colgap`, `rowgap` | unit | `gap` | Per-axis gutter override |
| `pad` | unit | `0` | Inner padding |
| `fill`, `line`, `lineWidth`, `radius` | as `<stack>` | `none` / `0` | **New.** Styled-card support |

Grid children carry placement attributes:

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `col` | integer (1-based) | next free | Starting column |
| `row` | integer (1-based) | next free | Starting row |
| `colspan` | integer | `1` | Columns spanned |
| `rowspan` | integer | `1` | Rows spanned |

### `<free>`
Absolute positioning. **The rare, deliberate escape hatch — not for general layout.** Children carry explicit geometry.

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `x`, `y` | unit / `%` | required | Top-left position |
| `w`, `h` | unit / `%` | required | Size |
| `rot` | degrees | `0` | Rotation |

The transpiler warns on overlapping children and errors on off-slide children here, since structural safety is not guaranteed. If an agent finds itself putting most of a slide in `<free>`, it is using the DSL wrong — that is the replication pattern, which this DSL does not serve.

### Edge Anchoring (new)
A `<stack>` with `anchor` is pinned to a slide edge rather than flowed in document order. This expresses full-bleed bands (e.g. a bottom classification bar) without hand-computed coordinates:

```xml
<stack dir="h" anchor="bottom" align="stretch" gap="0" h="0.4in">
  <shape fill="#E53935" text="HIGH RISK CONFIDENTIAL"/>
  <shape fill="#FB8C00" text="CONFIDENTIAL"/>
  <shape fill="#43A047" text="PUBLIC"/>
</stack>
```
The resolver computes equal thirds across the full slide width and pins the band to the bottom edge — no `13.333in` arithmetic by the author. `anchor="fill"` stretches the stack to span its main axis fully.

### `<text>`
A text block. Contains paragraphs. Block-level attributes set defaults for all paragraphs inside.

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `placeholder` | placeholder type | none | Binds to a layout placeholder; inherits its position/style |
| `idx` | integer | none | **New.** Disambiguates when a layout has multiple placeholders of the same type. Required when ambiguous. |
| `font` | family | inherit | |
| `size` | unit (pt) | inherit | Escape hatch for deliberate one-off emphasis; prefer `role` for hierarchy |
| `role` | `title`, `heading`, `subheading`, `body`, `bodySmall`, `caption` | `body`, or derived from `placeholder` | Semantic type role resolved through the active theme's `typeScale`; preferred over `size`. When `placeholder` is set the default derives from the placeholder type, so placeholder text is never flat. |
| `color` | token / hex | inherit | |
| `align` | `l`, `ctr`, `r`, `just` | inherit | |
| `bold`, `italic`, `underline` | boolean | false | **Whole-block formatting goes here, not in a wrapping `<run>`** (blessed form) |
| `anchor` | `t`, `ctr`, `b` | inherit | Vertical anchor in the box |
| `wrap` | `square`, `none` | `square` | |
| `lineSpacing` | number / unit | inherit | **New.** Multiple (e.g. `1.5`) or absolute |
| `spaceBefore`, `spaceAfter` | unit | inherit | **New.** Paragraph spacing |
| `list` | `none`, `bullet`, `number`, … | `none` | **New.** Default list marker for all child `<p>`; each `<p>` inherits this unless it sets its own `bullet`. A risk list is `<text list="number">` with plain `<p>` children. See List Model below. |
| `x`, `y`, `w`, `h` | unit / `%` | from container | Geometry — **used only inside a `<free>` container** (or to override). Every block element gains these in a `<free>` context. |

`placeholder` accepts **any** OOXML placeholder type: `title`, `ctrTitle`, `subTitle`, `body`, `pic`, `tbl`, `chart`, `dt`, `ftr`, `sldNum`, `hdr`. When `placeholder` is set and no parent forces geometry, **no geometry is emitted**, so the placeholder inherits from the layout (the over-specification rule, surfaced into the schema).

Content: a bare string (shorthand for one paragraph), or one or more `<p>` children. (The `<block>` element from v1 is removed — see Blessed Forms.)

### `<p>`
A paragraph inside `<text>`.

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `level` | 0-8 | 0 | Outline / bullet level |
| `role` | `title`, `heading`, `subheading`, `body`, `bodySmall`, `caption` | parent `<text>` role or `body` | Paragraph-level semantic type override |
| `align` | `l`, `ctr`, `r`, `just` | inherit | Overrides block align |
| `bullet` | `none`, `bullet`, `number`, `dash`, `check` | inherit from `<text list>` | **Blessed, extensible enum.** `bullet` = default theme glyph; `number` = ordered; `dash`/`check` = alternate markers; `none` = no marker. Inherits the parent `<text>`'s `list` value unless set. No literal-glyph form — the glyph for `bullet` comes from the theme. New marker types are added to this enum, never as new tags. |
| `bold`, `italic` | boolean | inherit | Whole-paragraph emphasis (not a wrapping run) |

Content: a bare string, or one or more `<run>` children for **mixed inline formatting within the paragraph only**.

### `<run>`
An inline span with its own formatting. **Use a `<run>` only for mixed formatting *within* a single paragraph** (e.g. one bold word in a sentence). Do not wrap an entire paragraph in a `<run>` to bold it — set `bold` on the `<p>` or `<text>` instead. This is the blessed boundary that the pressure test showed both authors violating.

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `bold`, `italic`, `underline` | boolean | inherit | |
| `size` | unit (pt) | inherit | |
| `color` | token / hex | inherit | |
| `font` | family | inherit | |
| `link` | URL | none | Hyperlink |
| `field` | `slidenum` | none | Emits an auto-updating `a:fld` (e.g. footer `<p>Page <run field="slidenum"/></p>`); the run's text is just the placeholder literal |

Content: the text string.

### `<image>`

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `src` | path | required | Media file |
| `placeholder` | `pic` (or other) | none | **New.** Fills a picture placeholder, inheriting its position |
| `idx` | integer | none | Disambiguates multiple picture placeholders |
| `fit` | `contain`, `cover`, `stretch` | `contain` | `contain` preserves aspect ratio; prevents the stretch bug |
| `alt` | string | none | Accessibility text |
| `w`, `h`, `x`, `y` | unit / `%` | from container | Only in `<free>`, or to override |
| `duotone` | one or two colors | none | Brand wash: `duotone="0F2B3C"` (dark→that color, highlights→white) or `duotone="dk2 lt2"` |
| `grayscale` | `true`/`false` | `false` | Desaturate the picture data |
| `alpha` | `%` | opaque | Picture opacity (`a:alphaModFix`) |

### `<shape>`

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `geom` | `rect`, `roundRect`, `ellipse`, `triangle`, ... | `rect` | Preset geometry |
| `fill` | token / hex / `none` | `none` | |
| `line` | token / hex / `none` | `none` | Stroke color |
| `lineWidth` | unit | `1pt` | Stroke width |
| `radius` | unit | `0` | Corner radius (roundRect) |
| `text` | string | none | Shorthand for centered text inside |
| `w`, `h`, `x`, `y`, `rot` | unit / `%` / deg | from container | Geometry (required in `<free>`) |
| `flipH`, `flipV` | `true`/`false` | `false` | Mirror the geometry without rotating its text |
| `adj` | `40%` or `adj1:30%, adj2:12500` | preset default | Preset adjustment guides; `%` → 1000ths, bare numbers raw. Wins over `radius` |
| `alpha` | `%` | opaque | Fill opacity (`60%` = 60% opaque). Requires a fill |
| `shadow` | `true`/`false` | `false` | Soft outer shadow (same finish as timeline `soft-shadow`) |

A shape may contain a nested `<text>` for richer text than the `text` shorthand.

### `<line>` (new, v1)
A straight line / connector — needed for timelines, separators, and rules. Both pressure-test authors had to fake this with thin rectangles.

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `color` | token / hex | `dk1` | Stroke color |
| `width` | unit | `1pt` | Stroke width |
| `dash` | `solid`, `dot`, `dash`, `dashDot` | `solid` | Dash style |
| `x1`, `y1`, `x2`, `y2` | unit / `%` | required in `<free>` | Endpoints |
| `cap` | `flat`, `round`, `square` | `flat` | End cap |
| `head`, `tail` | `triangle`, `stealth`, `diamond`, `oval`, `arrow`, `none` | `none` | End markers; `head` = the (x1,y1) end. For leader lines: `head="oval"` |

In a `<stack>`/`<grid>`, a `<line>` spans the cell it occupies (a horizontal rule fills the cell width).

### `<table>` (new, v1)
Pulled into v1: "title + intro + table" is a top-five business slide and both authors could not express it. A table is a managed container of cells; the resolver computes column widths and row heights.

| `<table>` attribute | Values | Default | Notes |
|---|---|---|---|
| `cols` | integer | from first row | Column count |
| `colWidths` | list of units / `%` | equal | Per-column widths |
| `rowHeights` | list of units | auto | Per-row heights |
| `header` | boolean | `false` | First row styled as header |
| `headerFill` | token / hex | `accent1` | Header row background |
| `headerColor` | token / hex | `lt1` | Header row text color |
| `fill`, `line`, `lineWidth` | token / hex | theme | Default cell fill / border color / border width |
| `w`, `h`, `x`, `y` | unit / `%` | from container | Geometry |

Children: `<row>` elements; each `<row>` holds `<cell>` elements.

| `<cell>` attribute | Values | Default | Notes |
|---|---|---|---|
| `colspan`, `rowspan` | integer | `1` | Cell merging |
| `align` | `l`, `ctr`, `r` | inherit | Horizontal alignment |
| `valign` | `t`, `ctr`, `b` | inherit | Vertical alignment |
| `fill` | token / hex | inherit | Per-cell fill |
| `color` | token / hex | inherit | Cell text color |
| `bold`, `italic` | boolean | inherit | **New.** Whole-cell emphasis — all three pressure-test authors independently assumed this works; now it does. For a total row, set `bold` on the cells. |

A `<cell>` contains a bare string or `<p>` children, like `<text>`. Per-cell `bold`/`fill`/`color` is the blessed way to style header and total rows; do not wrap cell content in a `<run>` to emphasize the whole cell.

```xml
<table cols="4" header="true" colWidths="40%,20%,20%,20%">
  <row><cell>Position</cell><cell>Daily rate</cell><cell>Days</cell><cell>Total</cell></row>
  <row><cell>Partner</cell><cell align="r">1000</cell><cell align="r">10</cell><cell align="r">10000</cell></row>
</table>
```

### Composites vs. native charts — the extensibility model
Two tiers of higher-level element exist, and the distinction is load-bearing because they sit on different OOXML substrates:

- **Tier 1 — composites that lower to primitives.** A composite is a layout helper that the transpiler resolves into shapes, lines, and table cells you already emit. It costs one resolver function and **zero engine changes**. `<timeline>` is the first; future composites (process flow, pyramid, funnel, comparison card) are added the same way. This is the cheap, freely-extensible tier.
- **Tier 2 — native charts.** A native OOXML chart (`bar`, `line`, `pie`, `scatter`) is **not** built from shapes — it is a separate OOXML part (`charts/chart1.xml`, namespace `c:`, its own relationship, embedded data). It requires a new engine capability (a `ChartBuilder` beside the other part builders) and is a substantial project. `<chart>` is reserved and sketched below, but **deferred** — it is not built in v1.

The principle for the spec: composites lower to primitives (add freely); charts are native parts (one heavy engine extension, later). A timeline is a composite. A bar chart is a native part. Do not build a timeline as a chart, or a chart as a pile of shapes.

### `<timeline>` (new, v1 — Tier-1 composite)
A composite for time-based visuals. Resolves to a table-like grid of week/period columns plus bars, milestones, and gridlines — no `<free>`, no hand-computed coordinates. This exists because three independent pressure-test authors produced three incompatible Gantt encodings; a blessed composite ends that divergence.

| Attribute | Values | Default | Notes |
|---|---|---|---|
| `style` | `gantt-grid`, `gantt-minimal`, `roadmap`, `swimlane` | `gantt-grid` | Registered style name resolved through the `TimelineStyleRegistry` |
| `finish` | `flat`, `soft-shadow`, `elevated`, `outlined`, `accent-gradient` | style default | Curated finish preset for bars; overrides the selected style's default |
| `borderWidth` | unit | finish default | Optional local border thickness override |
| `shadow` | boolean | finish default | Optional local shadow on/off override |
| `periods` | integer | required | Number of time columns (e.g. 10 weeks) |
| `unit` | `week`, `month`, `quarter`, `day` | `week` | Drives generated period labels when `labels` is omitted |
| `labels` | list of strings | from `unit` | Column header labels |
| `w`, `h`, `x`, `y` | unit / `%` | from container | Geometry |

Children: optional `<group>` elements, flat `<task>` elements, and/or `<milestone>` elements. A timeline with no `<group>` is a flat task list; a timeline with groups is swimlane-organized when the selected style renders groups.

| `<group>` attribute | Values | Default | Notes |
|---|---|---|---|
| `label` | string | required | Swimlane / workstream label |

| `<task>` attribute | Values | Default | Notes |
|---|---|---|---|
| `label` | string | required | Row label |
| `start` | integer (1-based period) | required | Starting period |
| `span` | integer | `1` | Periods spanned |
| `tone` | theme token / hex | style default | Semantic bar color; resolved by the selected style |

| `<milestone>` attribute | Values | Default | Notes |
|---|---|---|---|
| `label` | string | required | Marker label |
| `at` | integer (1-based period) | required | Period of the milestone |

```xml
<timeline style="gantt-grid" periods="10" unit="week">
  <group label="Discovery">
    <task label="Research"  start="1" span="3" tone="accent2"/>
    <task label="Synthesis" start="3" span="2" tone="accent2"/>
  </group>
  <group label="Delivery">
    <task label="Build"     start="4" span="4" tone="accent1"/>
    <task label="Rollout"   start="7" span="4" tone="accent3"/>
  </group>
  <milestone label="Kickoff"   at="1"/>
  <milestone label="Go-live"   at="10"/>
</timeline>
```
`start` + `span` encode both offset and length — the thing proportional-width bars could not do and the table-as-Gantt idiom did awkwardly. The resolver computes column geometry once and aligns task bars, gridlines, and milestone markers to the same period tracks. Labels never wrap into too-small boxes; style definitions use truncate/shrink policies for task labels and extend/stagger/truncate policies for milestone labels. Timeline finish is curated: authors choose a named preset and may only make small local edits (`tone`, `borderWidth`, `shadow`), not arbitrary CSS-like styling.

### `<chart>` (reserved, deferred — Tier-2 native part)
**Not implemented in v1.** Reserved so the grammar anticipates it and stays coherent. A `<chart>` will emit a native OOXML chart part with an embedded data model, not shapes.

Sketched shape (subject to change when built):
```xml
<chart type="bar" title="Revenue by region">
  <series name="2025"><point cat="EMEA" value="42"/><point cat="APAC" value="31"/></series>
  <series name="2026"><point cat="EMEA" value="50"/><point cat="APAC" value="38"/></series>
</chart>
```
`type` ∈ `bar`, `line`, `pie`, `scatter`, `area`. Building this is a dedicated engine milestone (ChartBuilder + chart part + relationship + embedded workbook), tracked separately from the DSL.

---

## 4. Layout Resolution (what the transpiler computes)

Each container type has a resolver that converts its children into absolute EMU boxes:

- **stack resolver** (trivial): walk children in order along `dir`, place each after the previous plus `gap`, size the cross-axis per `align`. If `anchor` is set, pin to the slide edge and (for `fill`/`stretch`) span the main axis fully, dividing space among children.
- **grid resolver** (moderate): divide container width into `cols` columns minus gutters; place each child at its `col`/`row`, sized by `colspan`/`rowspan`. Row heights from content or equal division.
- **table resolver** (moderate): like grid, but with header styling, per-column widths, and cell merging; emits an OOXML `a:tbl`.
- **timeline resolver** (moderate, Tier-1 composite): computes period-column geometry once, then aligns task bars (by `start`/`span`) and milestone markers (by `at`) to the same column tracks; emits shapes + lines + labels. No new engine part.
- **free resolver** (passthrough): children carry absolute geometry; convert units to EMU.

Resolution is recursive: a container's resolved box becomes the coordinate space for its children. Styled containers (`fill`/`line`/`radius`) emit a background `<shape>` behind their children automatically — the author never draws it. Output is a flat list of absolutely-positioned blocks: the slide dict the engine's `shape_emitters` already consume.

Percentages resolve against the parent container's resolved dimension at this step.

---

## 5. Validation Rules

Run after parsing, before emitting, on the resolved coordinates:

**Structural (errors):**
- Any block's resolved box extends past slide bounds.
- A grid child placed outside its declared `cols`/`rows`.
- A `placeholder` reference (with `idx` if needed) that the chosen layout does not define.

**Heuristic (warnings):**
- Two children of a `<free>` container overlap.
- Text whose measured size exceeds its resolved box (overflow). The validator measures text with font metrics and reports the overflow amount. Optional auto-shrink is bounded to the active role's `minSize`; default behavior is warn-only.
- Sibling text blocks whose font sizes differ beyond a threshold (drift signal).

Managed containers (stack/grid/table) cannot produce overlap, so warnings essentially only fire inside `<free>`. That is the point: the safe path is warning-free by construction, and `<free>` is where the author has opted out of safety.

---

## 6. Worked Examples

### Title slide (placeholder inheritance, zero geometry)
```xml
<deck theme="acme" size="16:9">
  <slide layout="title">
    <text placeholder="title">Quarterly Results</text>
    <text placeholder="subtitle">Q4 2026 — Revenue Review</text>
    <text placeholder="dt">17 July 2026</text>
    <image placeholder="pic" idx="11" src="hero.jpg" fit="cover"/>
  </slide>
</deck>
```

### Three styled panels (grid + styled containers)
```xml
<slide layout="titleOnly">
  <text placeholder="title">Project Plan for SectorMetric</text>
  <grid cols="3" gap="0.3in" pad="0.5in">
    <stack col="1" fill="lt2" radius="6pt" pad="0.2in" gap="0.1in">
      <text role="heading" color="accent1">Our understanding</text>
      <text role="body">
        <p bullet="bullet">Speed</p>
        <p bullet="bullet">Accessibility</p>
      </text>
    </stack>
    <stack col="2" fill="lt2" radius="6pt" pad="0.2in" gap="0.1in">
      <text role="heading" color="accent1">Risks &amp; issues</text>
      <text role="body"><p bullet="bullet">Vendor security risk</p></text>
    </stack>
    <stack col="3" fill="lt2" radius="6pt" pad="0.2in">
      <text role="heading" color="accent1">Project plan</text>
    </stack>
  </grid>
</slide>
```
The panels are styled stacks — no manual background shapes, no coordinates.

### Bottom classification bar (edge-anchored stack)
```xml
<slide layout="blank">
  <stack dir="h" anchor="bottom" align="stretch" gap="0" h="0.4in">
    <shape fill="#E53935" text="HIGH RISK CONFIDENTIAL"/>
    <shape fill="#FB8C00" text="CONFIDENTIAL"/>
    <shape fill="#43A047" text="PUBLIC"/>
  </stack>
</slide>
```
Full-bleed thirds, pinned to the bottom — no `13.333in` arithmetic.

### Fee table (native table)
```xml
<slide layout="titleOnly">
  <text placeholder="title">Resource plan and estimation of fees</text>
  <table cols="4" header="true" colWidths="40%,20%,20%,20%">
    <row><cell>Position</cell><cell>Daily rate</cell><cell>Days</cell><cell>Total</cell></row>
    <row><cell>Partner</cell><cell align="r">1000</cell><cell align="r">10</cell><cell align="r">10000</cell></row>
    <row><cell>Senior Consultant</cell><cell align="r">2000</cell><cell align="r">20</cell><cell align="r">40000</cell></row>
  </table>
</slide>
```

### Mixed inline formatting (the correct `<run>` use)
```xml
<text role="body">
  <p><run bold="true">Guidance:</run> Provide comfort that you understand the deliverables.</p>
</text>
```
One bold word inside a sentence — a `<run>`. A whole bold paragraph would set `bold` on the `<p>`, not wrap it.

---

## 7. Blessed Forms (resolved ambiguities)

The pressure test showed both authors picking different valid encodings. These are now the single blessed forms:

- **Whole-block / whole-paragraph bold/italic** -> `bold`/`italic` attribute on `<text>` or `<p>`. **Not** a `<run>` wrapping the entire content.
- **Mixed inline formatting** -> `<run>` children, used only for spans *within* a paragraph.
- **Semantic text hierarchy** -> `role` on `<text>` or `<p>` (`title`, `heading`, `subheading`, `body`, `bodySmall`, `caption`). Theme `typeScale` owns size/weight/spacing. Use explicit `size` only for deliberate one-off emphasis, such as a callout number.
- **Bullets** -> `bullet="bullet"` (default glyph) or `bullet="number"` (ordered). No literal-glyph form.
- **Heading-then-body in a panel** -> two sibling `<text>` blocks inside the panel container (the first styled as a heading). The `<block type="heading">` element is **removed**.
- **Inline theme** -> attribute form only; the child `<colors>`/`<fonts>` form is removed.
- **Filling a placeholder** -> `placeholder` (+ `idx` if ambiguous) on `<text>` or `<image>`. **Not** a free-positioned block faking the placeholder's location.
- **Lists** -> one mechanism: set the marker default with `list` on `<text>`, override per paragraph with `bullet` on `<p>`. Marker kinds (`bullet`, `number`, `dash`, `check`, `none`) are an extensible enum, never separate tags. There is no `<list>`/`<ol>`/`<ul>` element and no `<item>` — a list line is always a `<p>`. Infer `number` vs `bullet` from whether the content implies sequence (steps, ranked risks → `number`; unordered points → `bullet`).
- **Cell emphasis** -> `bold`/`fill`/`color` on `<cell>`. **Not** a `<run>` wrapping the whole cell.
- **Timelines / Gantts** -> the `<timeline>` composite, never hand-placed bars in `<free>` and never a table faking columns. One blessed form.
- **Slide backgrounds** -> set `background` on `<deck>` for the deck default, and on `<slide>` only when that slide intentionally overrides it. Use a theme token for re-skinnable backgrounds, hex for fixed brand colors, and `image:path` for full-slide image backgrounds.

---

## 8. v1 Scope Boundary

**In v1:** `<deck>`, deck/slide `background`, `<theme>` (attr form), theme `typeScale`, `<defs>`/`<def>`/`<use>`, `<slide>`, `<stack>` (with anchor + styled-container attrs), `<grid>` (with styled-container attrs), `<free>`, `<text>` (with `role` + `list`), `<p>` (with paragraph-level `role`), `<run>`, `<image>` (with placeholder), `<shape>`, `<line>`, `<table>`/`<row>`/`<cell>` (with cell emphasis + styling), `<timeline>`/`<task>`/`<milestone>` (Tier-1 composite). Theme tokens + hex. Stack/grid/table/timeline resolvers, free passthrough, edge anchoring. Geometry validation (arithmetic) + overflow warning.

**Deferred to later:** `<chart>` (Tier-2 native chart part — a dedicated engine milestone: ChartBuilder + chart part + relationship + embedded workbook), additional Tier-1 composites (process flow, pyramid, funnel, comparison card), transitions/animations, layout reflow / text restructuring, nested grids spanning edge cases, quote/code styled blocks.

**Explicitly out of scope for the DSL (ingestion-layer responsibilities):** extracting/reusing assets from an existing PPTX, cloning a source deck's master/footer artwork, pixel-faithful replication of existing slides. The DSL generates; the ingestion layer turns an existing template into a reusable theme + layout set the DSL generates against.

**The registry seam:** `theme=`, `layout=`, and any named-asset reference resolve through registries (`ThemeRegistry.get`, `LayoutRegistry.get`). In v1 these are thin wrappers over hardcoded data; the schema does not change when they later load from files or ingested templates.
