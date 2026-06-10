# Paro Authoring Guide

How to write decks in Paro's DSL that look designed, not generated. Read this before
writing a single tag. `SCHEMA_SPEC.md` is the grammar reference; this is the doctrine —
what good authors do with that grammar.

## The loop

```
python paro.py build deck.xml --png
```

One command: transpile → validator + design lint on stdout → `.pptx` → per-slide PNGs.
**Always look at the PNGs.** Fix what the lint says, then fix what your eyes say, then
rebuild. Two iterations should be enough; if it isn't, your structure is wrong — restructure
instead of nudging coordinates. `--theme corp.pptx` ingests a real template's theme
(colors, fonts, type scale) so the deck inherits a company's identity exactly.

## Mental model

A slide is a tree of containers resolved to absolute geometry. You almost never place
things; you *structure* them:

- **`flow="stack"`** (the default) — vertical flow. Text children take their measured
  height; containers/charts/images flex into what remains. This is where 90% of slides live.
- **`<grid cols=N>`** — columns. Use generous column counts (12 or 24) for asymmetric
  layouts: `colspan="11"` + `colspan="4"` + `colspan="6"` reads like a design grid.
- **`flow="free"`** — absolute coordinates. Reserve it for covers, full-bleed art, and
  diagram annotation. If you find yourself hand-computing coordinates for *content*,
  you've chosen the wrong flow.

## Layout doctrine

- **Let text size itself.** Don't put `h=` on text unless you're deliberately creating a
  fixed band or breathing room (e.g. a subtitle with `h="0.55in"` to add space below).
  The stack measures real font metrics and will not overlap siblings.
- **Spacing rhythm.** Slide padding `0.4in`; panel padding `0.12–0.16in`; gaps inside a
  panel `0.03–0.08in`; between panels `0.1–0.16in`; between page sections `0.25in+`.
  Consistent rhythm is most of what reads as "professional".
- **Center stat groups with `justify="ctr"`** on the inner stack — never with spacer
  elements or padding arithmetic.
- **Outlined panels are styled stacks** (`line="9FC4C8" lineWidth="1pt" pad="0.12in"`),
  not hand-drawn rectangles behind content.

The stat-card pattern (this is the blessed form — five lines, no coordinates):

```xml
<stack line="9FC4C8" lineWidth="1pt" pad="0.12in" justify="ctr">
  <text align="ctr" bold="true" size="11pt" color="dk1">Net Profit Margin</text>
  <text align="ctr" bold="true" size="18pt" color="accent1">#3 in KSA</text>
  <text align="ctr" size="9pt" color="dk1">3.81% (4Q 2023)</text>
</stack>
```

## Type discipline

- **Roles first**: `role="title|heading|subheading|body|bodySmall|caption"` keys into the
  theme's type scale (and an ingested template's real scale). Explicit `size=` is for
  dense dashboards and replication.
- **At most ~4 distinct sizes per slide** (lint warns above 5). When you catch yourself
  writing `17pt` next to an `18pt`, use 18 for both.
- **8pt is the floor** (lint enforces). Footers and source lines live at 8–9pt.
- **One font pair per deck** — the theme's heading/body. Lint warns at a third family.
- Bold marks hierarchy (labels, stat values), not emphasis inside running text.

## Color doctrine

- **Theme tokens over hex** — `dk1`, `accent1`, `lt2`… Hex is for replicating a specific
  artifact. Tokens keep the deck re-themeable, which is the whole point.
- `dk1` is the brand *text* color slot (it may be a brand dark like Alinma's brown, not
  black). `accent1` carries data emphasis and stat values. `lt2` makes tint panels.
- Dark backgrounds: set `background=` on the deck/slide and use `lt1`/light grays for
  text; don't fake it with a full-bleed rectangle.

## Diagrams: composites before shapes

If the idea has a name, there's probably a composite. They compute all geometry and
inherit theming; raw shapes are the fallback, not the default.

| Idea | Tag | Notes |
|---|---|---|
| Conversion/funnel | `<funnel><stage>90%</stage>…</funnel>` | True cone; `tip="flat"` keeps the last band a trapezoid |
| Step flow | `<process><step>Discover</step>…</process>` | homePlate + chevrons |
| Hierarchy | `<pyramid><tier>Vision</tier>…</pyramid>` | Apex is tight — short top labels or `tip="flat"` |
| Overlap | `<venn><set>A</set>…</venn>` | 2–3 sets, alpha circles |
| Schedule | `<timeline periods=…>` | Tasks by `start`/`span`, milestones by `at` |
| Data | `<chart type="bar|column|line|pie|scatter|…">` | Native OOXML chart part — never a pile of shapes |

When raw shapes are right (brand decor, bespoke geometry): the full OOXML preset catalog
is available via `geom=` with `adj` handles, `flipH/flipV`, `alpha`, `shadow`, and
`<line head="oval">` leader lines for annotation.

## Imagery

- `fit="cover"` for photographic blocks; `contain` for logos and diagram panels.
- **The brand-wash pattern** for full-bleed photography (one dark brand color):

```xml
<image src="photo.png" x="0in" y="0in" w="13.333in" h="7.5in" fit="cover" duotone="0E2433"/>
<shape x="0in" y="0in" w="13.333in" h="7.5in" fill="0E2433" alpha="35%" line="none"/>
<!-- then light text on top -->
```

## Footers

```xml
<stack dir="h" anchor="bottom" h="0.26in" pad="0.05in">
  <text size="8pt" color="dk2">1Q 2026 INVESTOR PRESENTATION</text>
  <text size="8pt" color="dk2" align="r"><p>Page <run field="slidenum"/></p></text>
</stack>
```

`field="slidenum"` is a real PowerPoint field — it renumbers itself when slides move.

## Reading the lint

| Code | It means | Do |
|---|---|---|
| `text_overflow` | Measured text exceeds its box | Widen the box, shorten the text, or drop a size step |
| `lint_tiny_text` | Below 8pt | Raise it; if it's a footer, 8pt exactly is fine |
| `lint_size_sprawl` | >5 sizes on one slide | Consolidate near-duplicates (17→18, 9.5→9) |
| `lint_font_sprawl` | >2 families | Use the theme pair |
| `lint_edge` | ≥10.5pt text hugging the slide edge | Give content a margin; footers are exempt |
| `font_drift` | Sibling text sizes differ >4pt | Intentional hierarchy is fine; accidental drift is not |
| `free_overlap` | Free siblings overlap | Fine for scrims/decor; check it's intentional |

Warnings are advisory — a dense dashboard may legitimately carry a few. Zero warnings is
not the goal; *no warning you can't justify* is.

## Renderer ground truth

Desktop PowerPoint is the reference renderer. LibreOffice (what `--png` uses) is the fast
proxy, with known divergences the engine already compensates for: it mirrors text in
flipped shapes (composites emit labels as unflipped overlays) and silently drops chartEx
types (funnel/waterfall/etc. — prefer classic chart types when the deck must render
everywhere). When something looks odd in a PNG, suspect the proxy before the engine, and
confirm in PowerPoint.

## Worked examples (`samples/`)

Each pair of `.xml` + rendered images is a few-shot exemplar. Study the one nearest your task:

| Sample | Demonstrates |
|---|---|
| `alinma_replication.xml` | Dense KPI dashboard: 24-col grid, nested stat panels, `justify`, brand theme via inline `<theme>`, footer with slidenum |
| `mckinsey_replication.xml` | Dark editorial style: full-bleed photography, serif display type, restraint |
| `atlas_consulting_deck.xml` | 13-slide narrative deck on an ingested (Deloitte) theme: charts, tables, timelines, agenda patterns |
| `plsfix_funnel.xml` | Funnel composite + absolutely-positioned annotation column (when `free` is the right call) |
| `composites_showcase.xml` | All four diagram composites, default tones |

## Theme ingestion

A user-supplied `.pptx`/`.potx` template is ground truth. `--theme` (or
`ingestion.extract_theme_bundle` + `transpile_deck(themes=…)`) consumes its colors,
fonts, and a type scale derived from its master — exactly, no inference. An inline
`<theme>` with the same name deliberately wins over ingestion: explicit author intent
outranks the template. Write new decks with theme tokens and they inherit whatever
template the user supplies.

**Layout transplant: the template's designed layouts come along.** When a template is
supplied, its slideMaster/slideLayouts travel verbatim into the package and DSL layout
names map onto them — `layout="title"` gets the template's actual cover art,
`layout="divider"` its section break, plus `titleOnly`/`titleBody`/`twoContent`/
`picture`/`blank`. **On an ingested theme, prefer placeholder-based covers and
dividers** (`<text placeholder="title">` etc.) — that is what makes the output
indistinguishable from the company's own deck. `title` and `ctrTitle` both match
whichever the template's cover declares. Compose explicitly only for layouts the
template doesn't offer.
