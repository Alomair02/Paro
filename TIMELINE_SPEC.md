# Timeline Composite — Design Specification (v1)

This is the design-spec-first artifact for the `<timeline>` composite. The first timeline shipped without one — it had a placement algorithm but no design intent, and it looked bad. This spec fixes that by separating three concerns, the same way the rest of the system separates them:

- **Data model** — what the author/agent provides (tasks, milestones, groups). Style-independent. Lives in the DSL.
- **Style-definition schema** — the bundle of visual parameters a named style supplies. The long-lived contract that makes new styles a *definition*, not code.
- **Initial style definitions** — 3-4 genuinely good styles, each spec'd carefully, each one entry in a style registry.

The architecture mirrors typography: the DSL carries **intent** (a `style` name + data), the **theme/registry** owns the **look** (the style definition), and the **resolver** owns the **mechanism** (the layout math). Adding a style later is a definition change, not a resolver change. This is the expansion seam, and getting the style-definition schema right is the center of gravity of this sprint.

The same three-layer split (data in DSL / mechanism in engine / style in registry) is intended to generalize to all chart families later. Building the timeline's style registry well now establishes the convention every future visual-family inherits.

---

## 1. Data Model (style-independent, author-provided)

This is what `<timeline>` carries in the DSL. It never changes when styles are added or swapped.

```xml
<timeline style="gantt-grid" periods="10" unit="week">
  <group label="Discovery">                          <!-- optional grouping (swimlanes) -->
    <task label="Research"   start="1" span="3" tone="accent2"/>
    <task label="Synthesis"  start="3" span="2" tone="accent2"/>
  </group>
  <group label="Delivery">
    <task label="Build"      start="4" span="4" tone="accent1"/>
    <task label="Rollout"    start="7" span="4" tone="accent3"/>
  </group>
  <milestone label="Kickoff"  at="1"/>
  <milestone label="Go-live"  at="10"/>
</timeline>
```

| `<timeline>` attribute | Values | Default | Notes |
|---|---|---|---|
| `style` | registered style name | `gantt-grid` | Resolved via the TimelineStyleRegistry |
| `finish` | registered finish name | style default | Curated visual finish preset for this timeline's bars |
| `borderWidth` | unit | finish default | Small editability hook; overrides the selected finish's bar border thickness |
| `shadow` | boolean | finish default | Small editability hook; forces bar shadow on/off without changing the whole finish |
| `periods` | integer | required | Number of time columns |
| `unit` | `week`, `month`, `quarter`, `day` | `week` | Drives default period labels |
| `labels` | list of strings | from `unit` | Explicit period labels, overrides `unit` defaults |
| `w`, `h`, `x`, `y` | unit / `%` | from container | Geometry |

| `<group>` (optional) | Values | Default | Notes |
|---|---|---|---|
| `label` | string | required | Swimlane / workstream label |

`<group>` is optional. A timeline with no `<group>` is a flat list of `<task>`s. A timeline with groups is swimlane-organized. Styles declare whether they render groups (see style schema).

| `<task>` attribute | Values | Default | Notes |
|---|---|---|---|
| `label` | string | required | Task name |
| `start` | integer (1-based period) | required | Starting period |
| `span` | integer | `1` | Periods spanned |
| `tone` | theme token / hex | style default | Bar color; `tone` (not `fill`) to read as semantic intent, resolvable by the style |

| `<milestone>` attribute | Values | Default | Notes |
|---|---|---|---|
| `label` | string | required | Marker label |
| `at` | integer (1-based period) | required | Period of the milestone |

The data model is **intent only**. It says *what* happens *when*, never *how it looks*. `start`/`span` encode position and length (the thing proportional-width bars and table-fakes could not do). `tone` names a semantic color the style resolves through the theme.

---

## 2. Style-Definition Schema (the long-lived contract)

A style definition is a bundle of visual parameters that drives one of the resolver's layout mechanisms. This schema is the contract that must be designed carefully — too narrow and future styles can't express their look; too baggy and it becomes a parameter free-for-all that pushes design decisions onto the agent. New styles are added by writing a definition against this schema, never by changing the resolver.

A style definition has these fields:

| Field | Type | Purpose |
|---|---|---|
| `mechanism` | enum: `bars-in-columns`, `pills-in-flow` | Which resolver layout mechanism this style uses. v1 ships `bars-in-columns` only; `pills-in-flow` reserved. |
| `gutterRatio` | fraction (0–1) | Task-label gutter width as a fraction of total timeline width |
| `gutterMin` | unit | Minimum gutter width (so labels stay readable) |
| `headerHeight` | unit | Period header band height; `0` = no header |
| `showGrid` | boolean | Vertical period gridlines in the plot area |
| `gridColor` | theme token / hex | Gridline color |
| `gridWidth` | unit | Gridline stroke width |
| `rowHeight` | unit / `auto` | Per-task row height; `auto` divides plot height by row count, with a min |
| `rowHeightMin` | unit | Floor for `auto` row height |
| `barHeightRatio` | fraction (0–1) | Bar height as a fraction of row height (the rest is vertical padding) |
| `barRadius` | unit | Bar corner radius |
| `barInset` | unit | Horizontal inset of bar within its period columns (breathing room) |
| `labelPlacement` | enum: `gutter`, `on-bar`, `none` | Where task labels go |
| `labelOverflow` | enum: `truncate`, `shrink` | What happens when a label exceeds its space; `truncate` adds ellipsis, `shrink` reduces within the role floor (uses text measurement) |
| `renderGroups` | boolean | Whether `<group>` produces swimlane headers/banding |
| `groupHeaderStyle` | enum: `band`, `label`, `none` | How a group is visually marked |
| `milestoneMarker` | enum: `diamond`, `circle`, `triangle`, `flag` | Milestone marker shape |
| `milestoneLabelPlacement` | enum: `below`, `above`, `inline` | Where milestone labels sit relative to the marker |
| `milestoneLabelOverflow` | enum: `extend`, `stagger`, `truncate` | How milestone labels avoid collision; `extend` lets the label exceed its column width centered on the marker; `stagger` offsets colliding labels vertically |
| `defaultTones` | list of theme tokens | Bar colors cycled when a `<task>` has no explicit `tone` |
| `paletteMode` | enum: `cycle`, `by-group`, `uniform` | How default tones are assigned across tasks |
| `finish` | registered finish name | Per-style default finish preset for task bars |

Two design rules enforced by this schema:

- **Labels never wrap into a too-small box.** `labelOverflow` is `truncate` or `shrink` — never wrap. The original timeline's worst failure was milestone labels wrapping in narrow cells; this schema makes wrapping unexpressible.
- **Milestone labels can leave their column.** `milestoneLabelOverflow="extend"` is the default fix for "Project status meeting" in a one-week-wide column — the label centers on the marker and extends past the column edges into clear space, staggering vertically if two collide.

A style definition lives in the **TimelineStyleRegistry** (initially hardcoded data, later loadable / theme-supplied — the same seam as the other registries). The DSL references it by name; the resolver reads `mechanism` to pick the layout math and the rest of the bundle to parameterize the look.

### Finish Presets

Finish is deliberately curated. Authors pick a named preset, then make only small local edits (`tone` per task, `borderWidth`, `shadow`) instead of tuning raw visual knobs. A finish preset bundles:

| Field | Type | Purpose |
|---|---|---|
| `fill` | solid / gradient treatment | Uses the task tone as the base color |
| `border` | enabled, tone, weight | Bar outline, normally tone-matched or omitted |
| `shadow` | optional outer shadow | Coordinated blur, distance, direction, and opacity |
| `cornerRadius` | unit | Emitted as a real OOXML roundRect adjustment guide |

Initial finish presets:

- `flat` — solid task-tone fill, no border, no shadow, 2pt radius.
- `soft-shadow` — solid fill, no border, subtle outer shadow, 3pt radius.
- `elevated` — solid fill, tone-matched 0.75pt border, slightly stronger outer shadow, 3pt radius.
- `outlined` — light tint of the task tone, tone-matched 1pt border, no shadow, 2pt radius.
- `accent-gradient` — subtle two-stop gradient within the task tone (`lumMod=100000` + `lumOff=18000` to lighten, `lumMod=82000` to darken), no border, soft shadow, 8pt radius.

Per-style defaults choose one of these presets; `<timeline finish="...">` overrides that style default for one timeline. This is the expansion seam for future template-supplied finishes, but v1 keeps the backing data hardcoded.

---

## 3. Initial Style Definitions (3-4 good styles, shipped in v1)

All four use the `bars-in-columns` mechanism — one solid layout engine, four well-designed looks. Distinct mechanisms (e.g. `pills-in-flow` roadmap) come in a later sprint once the seam is proven.

### `gantt-grid` (default) — the clean gridded gantt
```
mechanism: bars-in-columns
gutterRatio: 0.22   gutterMin: 1.2in
headerHeight: 0.32in
showGrid: true   gridColor: dk2 (low emphasis)   gridWidth: 0.5pt
rowHeight: 0.5in   rowHeightMin: 0.46in
barHeightRatio: 0.55   barRadius: 2pt   barInset: 0.04in
labelPlacement: gutter   labelOverflow: truncate
renderGroups: false   groupHeaderStyle: none
milestoneMarker: diamond   milestoneLabelPlacement: below   milestoneLabelOverflow: extend
defaultTones: [accent1, accent2, accent3]   paletteMode: cycle
finish: flat
```
The anatomy: left label gutter, period header, gridded plot, bars at 55% row height with breathing room, diamond milestones with labels below that extend past their column. The reference "good gantt."

### `gantt-minimal` — no grid, lighter
```
Same as gantt-grid except:
showGrid: false
headerHeight: 0.28in
rowHeight: 0.48in   rowHeightMin: 0.44in
barRadius: 3pt
milestoneLabelPlacement: below   milestoneLabelOverflow: stagger
finish: soft-shadow
```
Cleaner, less ink — bars float on an open plot, no vertical gridlines. Good for executive summaries where precision matters less than calm.

### `roadmap` — rounded pills, label-on-bar, no gutter
```
mechanism: bars-in-columns
gutterRatio: 0   gutterMin: 0
headerHeight: 0.32in
showGrid: false
rowHeight: 0.56in   rowHeightMin: 0.5in
barHeightRatio: 0.64   barRadius: 8pt (pill)   barInset: 0.06in
labelPlacement: on-bar   labelOverflow: truncate
renderGroups: false
milestoneMarker: flag   milestoneLabelPlacement: above   milestoneLabelOverflow: extend
defaultTones: [accent1, accent2, accent3, accent4]   paletteMode: cycle
finish: accent-gradient
```
No label gutter — task names ride on the pills. Taller bars, rounded ends, flag milestones. The "marketing roadmap" look.

### `swimlane` — grouped by workstream
```
mechanism: bars-in-columns
gutterRatio: 0.22   gutterMin: 1.2in
headerHeight: 0.32in
showGrid: true   gridColor: dk2   gridWidth: 0.5pt
rowHeight: 0.46in   rowHeightMin: 0.42in
barHeightRatio: 0.55   barRadius: 2pt   barInset: 0.04in
labelPlacement: gutter   labelOverflow: truncate
renderGroups: true   groupHeaderStyle: band
milestoneMarker: diamond   milestoneLabelPlacement: below   milestoneLabelOverflow: stagger
defaultTones: [accent1, accent2, accent3]   paletteMode: by-group
finish: elevated
```
Uses `<group>`. Each workstream gets a banded header row and its tasks share a tone (`by-group`). The "program plan" look. Falls back gracefully to `gantt-grid` behavior if the timeline has no groups.

---

## 4. Resolver Mechanism (v1: bars-in-columns)

One mechanism backs all four initial styles. It:

1. Computes the **gutter** (`gutterRatio` of width, floored at `gutterMin`) and the **plot area** (the rest).
2. Divides the plot width into `periods` equal columns; records column x-positions as a **shared track** that bars, gridlines, and milestones all align to (the thing the table-fake and proportional-bars approaches couldn't share).
3. Lays out rows: if `renderGroups`, emits a group header (`groupHeaderStyle`) before each group's tasks; row height from `rowHeight`/`rowHeightMin`.
4. Places each task bar from the left edge of its `start` column to the right edge of its `start+span-1` column, inset by `barInset`, at `barHeightRatio` of row height, centered vertically, with the selected finish's `cornerRadius`. Tone from `task.tone` or `defaultTones` per `paletteMode`.
5. Places task labels per `labelPlacement`, applying `labelOverflow` (truncate-with-ellipsis or measured shrink — uses the existing text-measurement module; never wraps).
6. Draws gridlines if `showGrid`; draws the period header if `headerHeight > 0`.
7. Places milestone markers (`milestoneMarker` shape) centered on their `at` column in the plot/milestone band below the task rows, with labels per `milestoneLabelPlacement`/`milestoneLabelOverflow` (extend past column or stagger; never wrap).

Output lowers to the engine's existing primitives — shapes, lines, text boxes — exactly as a Tier-1 composite should. No new engine part.

---

## 5. Expansion Seam (why future sprints are cheap)

- **New style, same mechanism** → add a definition to the TimelineStyleRegistry. No resolver change. (e.g. a `gantt-dense` with smaller rows.)
- **New mechanism** (e.g. `pills-in-flow` for a no-grid free roadmap, or calendar-gridded) → add a mechanism to the resolver and the styles that use it. Larger, but isolated.
- **Theme-supplied styles** → the registry later loads style definitions from the theme/design-system, so a corporate theme can ship its own timeline look. The DSL and resolver are untouched.
- **Generalization to charts** → charts reuse this exact split: data in the DSL, mechanism in the engine (Tier-2 native chart part), style definition in a registry. The convention established here is the convention every future visual-family inherits.

---

## 6. v1 Scope

**In v1:** the data model (`<timeline>`/`<group>`/`<task>`/`<milestone>`), the style-definition schema, the `bars-in-columns` mechanism, the four style definitions (`gantt-grid`, `gantt-minimal`, `roadmap`, `swimlane`), and the TimelineStyleRegistry (hardcoded data, registry seam in place). Label overflow via truncate/measured-shrink, milestone overflow via extend/stagger — never wrap.

**Deferred:** the `pills-in-flow` mechanism, calendar/nested-period grids, dependency arrows between tasks, theme-supplied style definitions (the registry is ready for them), and additional styles beyond the initial four.
