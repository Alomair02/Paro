# Paro — Project Handoff Note

This is an **index into the project's own artifacts**, not a summary that replaces them.
The reasoning behind every major decision lives in the spec files and tests in the repo;
this note tells you where to look and why each thing is the way it is. Read it alongside
the specs, not instead of them.

---

## What Paro is (and the end goal)

A generation-first engine that turns a custom high-level XML DSL into OOXML `.pptx` files.
An agent (or a human) writes the DSL; the transpiler resolves it to absolute geometry; the
engine emits standards-conformant OOXML that opens in real PowerPoint. It is **not** a
replication tool — it generates clean new slides, it does not clone existing decks. That
boundary is load-bearing and is why the grammar stays simple.

**The layered architecture, top to bottom, is the whole point:** an eventual **agent layer**
sits on top of a solid, robust **intermediate layer** (engine + transpiler + the DSL) and uses
that abstraction to build decks — from user prompts and from source material (Excel, PDFs,
reports) it processes and context-manages into the transpiler's contract. The agent should be
**accurate and familiar** with the intermediate layer and **creative and capable** in using it.
Target users: consultants, students/academia, company workers who make decks — technical and
non-technical. The agent infers deck content (including charts and other elements) from the
available resources and the user's requirements.

**Open design question for the agent layer (not yet decided):** does the agent author *raw DSL*
directly, or do we give it *Python functions / tools / hooks* as shortcuts that minimize misses
(e.g. a `make_chart_slide(...)` helper that always sets `flow`, roles, in-bounds geometry)?
Likely a mix. This is the next big discussion, and the probe below informs it heavily.

Ground truth for every milestone: **opens in real PowerPoint.** python-pptx and LibreOffice
are lenient and will accept files PowerPoint rejects — convenience checks, not the standard. On
Linux the practical bar is LibreOffice + the test suite; desktop PowerPoint is the gold standard
when reachable. PowerPoint **Online** is neither — it banners on upload regardless of validity.

## How we work (read before doing anything) — this is the method, not just the project

- **The human writes and runs all the code; the assistant is architect/reviewer.** The assistant
  does NOT generate the feature or emit XML on the human's behalf. It guides file-by-file; the
  human pastes code + command output back; the assistant diagnoses. Code snippets from the
  assistant are for the human to *review and place*, not for the assistant to "do" the build.
- **The source is truth, not the conversation's belief about the source.** Before building on
  anything claimed "already done," confirm it with `grep`/`cat`/`sed`. A plan from an earlier turn
  may never have been applied — this has bitten us (the axis-id allocator; and this session, a
  stale traceback against an already-edited file). A passing suite can be consistent with a change
  being absent. **Lead with recon commands, wait for the paste, then diagnose. Don't guess at code
  you haven't seen** — this session that discipline caught a chart bug that looked like a model
  error but was a latent resolver bug, and a "title coordinate" worry that turned out to be a
  sizing (role) issue, not positioning.
- **How the assistant gets context (it has NO filesystem access beyond attached `.md` files):**
  it asks for `grep -n` (find with line numbers), `sed -n 'A,Bp'` (view a range), `unzip -l`/`-p`
  on the generated `.pptx` (they're zips), `md5sum` for asset comparison, short `python -c`
  probes (including monkeypatch traces of resolver internals — used this session to find a
  double-applied geometry bug), and re-running a grep to confirm an edit landed.
- **Small, independently-verifiable steps:** prove the riskiest XML in isolation → wire it in →
  render-and-check → generalize hardcoded → data-driven → lock with a property test. Never several
  at once.
- **Tests verify structure; only a render verifies it looks right.** Opinionated visuals have been
  "wrong but passing." After a test passes, **bite-check** the guard: temporarily break the
  assertion, confirm it fails, restore. A green test that can't fail guards nothing. This applies
  to golden fixtures too — a freshly-blessed golden must be shown to fail before it's trusted.
- **Fail clearly, never silently-wrong.** Errors should name what's wrong AND what's expected, so
  an agent can recover (e.g. "3 categories but 1 value" not "invalid chart"). This is now an
  explicit design principle, reinforced by the probe.

## Where the reasoning lives (read these first)

- `SCHEMA_SPEC.md` — the DSL contract. Generation-first philosophy, the container model
  (stack/grid/free), blessed forms, type-scale roles. **NOTE (probe finding):** the container
  geometry model is **parent-relative and `flow`-dependent** in ways that are not obvious from the
  spec — see Probe Findings #1/#4. This spec likely needs a worked `<free>`/`flow` example.
- `TIMELINE_SPEC.md` — the timeline composite. Design-spec-first because the first timeline looked
  bad without one. Lesson: opinionated visuals need written design intent, not just a layout algo.
- `CHART_SPEC.md` — charts. data/mechanism/style/finish split. classic `c:` vs chartEx `cx:` vs combo.
- `CHARTEX_SPEC.md` — the `cx:` family (funnel/waterfall/histogram/box-whisker/pareto/treemap/
  sunburst). **ALL 7 BUILT** — `HANDOFF_CHARTEX_PHASE1.md` is the as-built source of truth.
- `ENGINE_REFERENCE.json` — canonical OOXML constants (namespaces, content-types, rel URIs, EMU
  factors, slide sizes, placeholder coordinates). The authority when code and a sample disagree.
  **NOTE:** it documents 6 layouts; the engine now implements all 6 (was 4 — see this session).

## Architecture (layers, bottom up)

`core/` (infrastructure: registries, xml_builder) → `builders/` (engine: part builders, shape
emitters, zip assembler — single `assemble_package` path) → `transpiler/` (parser → resolver →
validator → pipeline) → registries as the design-system seam. Cross-layer refs go through
registries. Adding a layout/theme/style is a **data** change.

**Registry seam — CONFIRMED uniform this session.** `ThemeRegistry`, `LayoutRegistry`,
`ShapeLibrary`, `TimelineStyleRegistry`, `ChartStyleRegistry` ALL accept injected data via
constructor (`__init__(self, ..., =None)`). `LayoutRegistry` was fixed to **merge-over-default**
like the style registries (was replace-wholesale — fail-dangerous: passing custom layouts dropped
built-ins). So the ingestion target is ready: feed any registry data, built-ins survive, custom
adds/overrides by name. **Known residual inconsistency (deferred):** `ThemeRegistry` does its
default-merge in the *caller* (`_inline_theme_map` in `pipeline.py`), not the constructor.

## What's built and tested (suite green, 106 tests)

- Engine + OPC packaging — opens in real PowerPoint. Frozen schema; transpiler (parse/resolve/
  validate/pipeline). Type scale (semantic `role` → theme sizes). Backgrounds, image pipeline.
- Timeline composite — 4 styles, 5 finishes, design-spec-driven.
- Charts (classic `c:`) — 7 types: column/bar/line/area/pie/scatter + radar; multi-series; native
  chart part + embedded editable workbook; combo (per-series type+axis, secondary-axis topology).
- chartEx (`cx:`) — ALL 7 types. Spec-map generic builder + Path-B (pareto) + shared hierarchical
  (treemap/sunburst). See `HANDOFF_CHARTEX_PHASE1.md`.
- **Layouts (6):** `title`, `titleBody`, `titleOnly`, `twoContent`, `picture`, `blank`. (titleOnly
  + twoContent added this session — were documented in ENGINE_REFERENCE but missing from
  `LAYOUT_DEFINITIONS`; golden fixtures created + master re-blessed.)
- **Font measurement — DONE (exact).** `transpiler/text_metrics.py` resolves a font name → installed
  file by exact family/weight/italic via token decomposition (fixed a bug where `Aptos` grabbed
  `Aptos-Black.ttf`). Scans Linux + macOS font dirs incl. `~/.local/share/fonts`. Reports
  `approximation_used` honestly. Aptos/Aptos Display provisioned; measured exactly. **Font
  *embedding* (cross-machine `p:embeddedFontLst`) deliberately deferred** — needs a brand-font
  forcing case; the second-machine gate now exists (dev on both Linux + macOS).
- **Font-name validation — DONE.** `Validator._validate_font_support` warns (not errors) when a
  referenced font — explicit or theme-inherited — is outside `SUPPORTED_FONTS`; message names the
  set so an agent can recover. Runs independent of `measure_text`.

## This session's fixes (the agent-DSL probe + hardening)

We ran a **fresh-agent probe**: gave a cold frontier model (Gemini) the specs + a fixed scenario,
had it write DSL, ran it through the real pipeline, and walked every failure. Then a **stress
harness** (`/tmp/stress_paro.py` — adversarial/edge inputs checking graceful-fail-vs-crash; worth
re-creating or promoting into the suite). Results: the engine is **robust** (zero true crashes
under adversarial input) and structurally sound, but it **under-validated data-shape and value
correctness** — exactly the silent-wrong failures non-technical users can't catch. Five fixes,
all locked in `tests/test_transpiler.py` class `EngineHardeningTests` (rejects-bad AND
accepts-good halves so the guards can't over-tighten):

- **#2 — missing layouts** (`titleOnly`/`twoContent`) → implemented from ENGINE_REFERENCE coords.
- **#3 — `_resolve_free` double-applied container geometry** → **the fix described here was
  never actually applied** ("Built ≠ built" struck this very entry). Actually fixed in commit
  `c572a9d`, with the regression test this entry owed
  (`test_free_container_offset_applied_once`).
- **#6 — parser crashed on XML comments** (lxml comment nodes have non-str tags) → fixed at the
  parse entry: `etree.XMLParser(remove_comments=True, remove_pis=True)`. Models emit comments
  constantly; this would have hit nearly every agent generation.
- **#8 — chart category/value count mismatch silently accepted** → now raises a clear ValueError
  naming the series and counts. Scoped to category charts (scatter uses xy pairs; histogram has
  no categories — both exempt). The implicit-data-contract trap, demonstrated.
- **#9 — theme hex not validated** → invalid hex (`accent1="notacolor"`) used to pass through to
  the theme part → PowerPoint file-repair. Now `_inline_theme_map` raises on non-6-hex. (This also
  surfaced that the `parse_resolve` test helper *stubs theme colors to defaults* and never
  exercised real inline-theme color resolution — the #9 tests are the first to cover that path.)

## Probe findings — RESOLVED 2026-06-09 (commits 9ff969b..c572a9d)

Everything in the section below is now fixed and locked in tests; it is kept for the reasoning.
- **#5** → placeholder text now derives its default role from the placeholder type
  (`title`/`ctrTitle`→`title`, `subTitle`→`subheading`, `body`→`body`); explicit `role=`
  overrides; `placeholder=` and `role=` paths produce identical styling. The actual pre-fix
  behavior was worse than "flat": placeholder titles got an explicit body-size run (17pt).
- **#7** → column/bar/area value axes baseline at zero when data is non-negative (combo:
  per-axis); the builder previously ignored every style's `dataLabels` entirely — now
  column/bar/pie emit labels, `clean` defaults to `value`, and a `dataLabels` chart attribute
  overrides. Bonus: single-type `stacked=` was silently ignored (hardcoded `clustered`) — fixed.
- **#8b** → category charts with no categories at all now fail with a recoverable message;
  scatter/histogram exempt.
- **#1/#4** (`<free>` geometry) → root cause was largely the un-applied #3 fix doubling offsets;
  with geometry applied once, free coordinates behave as documented. Spec still deserves a worked
  example.
- Also: `pareto` was built in the chartEx builder but missing from the resolver's CHARTEX set —
  unreachable from DSL. Added + end-to-end test. The 6-layout work claimed done above was only
  half-landed on this machine (fixtures/master test missing) — completed, re-blessed, bite-checked.
- The probe corpus lives in `probe_batch/` (11 DSL files); 07 now correctly fails, the rest
  transpile. Suite: 131 tests.

## Original probe findings (HISTORICAL — see resolution above)

The probe's headline conclusion: **the agent layer's hard problem is design judgment and data
honesty, NOT DSL syntax.** A cold model given standing scaffolding produced a structurally-correct,
in-bounds, multi-layout deck on a fresh scenario — the scaffolding generalized. What it got wrong
were *taste* and *implicit contracts*:

- **#5 — placeholder-vs-role text paths.** `placeholder="title"` binds to layout placeholders with
  master-default sizing; `role="title"` drives the type scale (the designed hierarchy). The model
  defaulted to `placeholder=` → flat, unstyled output. When BOTH are set, the resolver's
  `if placeholder:` branch (resolver ~190) takes precedence, so `role` alongside `placeholder` may
  do nothing. **This is a banana-system footgun** — two ways to place text, one looks designed, one
  flat, and nothing steers the author. Decide: make `placeholder=` text also run the type scale, or
  bless `role=` and make the agent always use it.
- **#7 — chart axis auto-scales off a non-zero baseline + no value labels.** A bar chart of values
  clustered at 3.8–4.5 rendered with the axis starting at 3.4 → wildly exaggerated, misleading. No
  value labels either. Non-technical users can't catch this. Bar charts should baseline at zero by
  default; value labels should likely be default-on. This is "opinionated visual needs design
  intent" again (the timeline lesson).
- **#1/#4 — `<free>` geometry contract.** `<free>` requires its own geometry, and free coordinates
  are **parent-relative**, with the slide root defaulting to `stack` (which slots children). So
  `<free x="1in" y="1.8in">` does NOT mean slide-absolute unless the slide is `flow="free"`. A
  capable model (and the assistant, with full context) both guessed wrong. Either document loudly
  with worked examples, or have the agent always set `flow` deliberately and compute absolute
  positions. Out-of-bounds (incl. negative) IS caught by the validator (`bounds` error) — that
  guard works.
- **#8b (noted, not fixed)** — a category chart with NO categories at all (author omits
  `<categories>` and points have no `cat`) isn't guarded; #8 only catches count *mismatch*.

## Invariants and the tests that guard them (the durable part)

If one fails, read *why it exists* before "fixing" it.
- **`tests/test_golden_outputs.py`** — byte-compares emitted parts to fixtures. A part declares only
  the namespaces it uses (chart `c:`/chartEx `cx:` declared LOCALLY, never global NSMAP). Adding a
  part type legitimately changes fixtures → verify the new output is correct, then re-bless, then
  bite-check.
- **Cache == workbook** (chart + combo) — `c:numCache`/`cx:` cache must equal the embedded `.xlsx`.
- **Luminance range guard** — no `lumMod`/`lumOff` > 100000 (118000 once caused file-repair). To
  lighten, use `lumOff`, never `lumMod` > 100000.
- **Plot-element-per-type**, **Combo property test**, **chartEx invariants** (`test_chartex.py`),
  **radar test** (valAx majorGridlines — the rings).
- **EngineHardeningTests** (`test_transpiler.py`, new this session) — #6 comments, #8 cat/val
  mismatch (+ matched-accepted), #9 theme hex (+ valid-accepted).

## Traps that bit us (so they don't bite again)

- **"Built" ≠ built.** Confirm claimed changes by reading source. Also: a *stale traceback* against
  an already-edited file (line numbers shift). Re-read, don't trust the old trace.
- **Double-application / unconditional-branch.** Now seen THREE times: duplicate plot element,
  stray combo series block, and this session `_resolve_free` re-resolving geometry. Watch when a
  caller and callee both transform the same thing.
- **Single assembly path** — wire new part types into `assemble_package` once.
- **Orphaned-part pattern** — part in rels+content-types but missing from zip → renderer drops it.
- **Lenient-consumer bugs** — pass python-pptx/LibreOffice, fail PowerPoint (XML decl quoting,
  child ordering, out-of-range lumMod). For chartEx, LibreOffice/Online are useless — desktop PP only.
- **Test helper can lie** — `parse_resolve` stubs theme colors to defaults; tests using it never
  exercised real theme-color resolution. Check what a helper actually does before trusting coverage.
- **Two-sources-of-truth drift** — ENGINE_REFERENCE documented 6 layouts, `LAYOUT_DEFINITIONS` had
  4. Consider deriving the registry from the reference to prevent recurrence.

## Pre-agent phases — DONE 2026-06-10 (commits c2a3cf0..de180ee, suite 176)

The three-phase plan to finish the lower layers before the agent layer, executed:

- **Phase 1 — primitive unlocks**: `<shape>` flipH/flipV/`adj`/`alpha`/`shadow`; `<line>`
  head/tail end markers; `<image>` duotone/grayscale/alpha (the brand photo wash);
  `<run field="slidenum">` true `a:fld`. All thin DSL exposures over existing engine plumbing.
- **Phase 2 — Tier-1 diagram composites**: `<funnel>` `<process>` `<pyramid>` `<venn>`,
  one resolver function each (the `<timeline>` pattern). Funnel/pyramid compute true cones
  via trapezoid `adj`. TRAP: LibreOffice mirrors text inside flipped shapes (PowerPoint
  doesn't) — composites emit labels as unflipped overlays. `<statcard>` deliberately skipped:
  styled stacks + `justify="ctr"` already express it (see AGENT_GUIDE pattern).
- **Phase 3 — guardrails**: design lint in the validator (`lint_tiny_text`, `lint_size_sprawl`,
  `lint_font_sprawl`, `lint_edge`) + fixed a latent bug where `_validate_text_fit` ran on only
  the last block per slide; `paro.py build deck.xml --png [--theme corp.pptx]` one-command
  loop; `AGENT_GUIDE.md` (authoring doctrine + worked-example corpus index over samples/).
- **Gate check** (replicate never-seen Alinma p.23 P&L Trends cold, per guide, no engine
  changes): PASSED structurally in 3 render iterations vs the 2 targeted. The extra iteration
  has two named causes, now backlog: (a) `<table>` has no text-size control — cells were
  hand-wrapped in `<p role="caption">` ×54; (b) intrinsic text measurement ignores bullet
  indents, so bulleted paragraphs under-measure and need explicit `h=` bands.

## Roadmap (priority order)

1. **Probe-finding fixes (design judgment) — the bridge to the agent layer.** In priority of
   user-harm: **#5** (placeholder/role footgun → flat decks), **#7** (chart zero-baseline + value
   labels → misleading charts). These are what make output *good*, not just valid. Plus the small
   debts: `_resolve_free` regression test, #8b empty-categories guard.
2. **Abstraction-soundness revision pass** (the "not a banana system" audit) — largely informed now
   by the probe. Colors/themes are CONFIRMED themeable end-to-end (theme is a parameter; chartEx
   assets are scheme-relative; deck theme drives everything). What's genuinely frozen is non-color
   style (radarStyle, treemap/sunburst label positions, per-type data-label/axis defaults). Full
   checklist in `HANDOFF_CHARTEX_PHASE1.md` PENDING.
3. **Agent layer** — natural language + source docs → decks. THE goal. Decide raw-DSL vs.
   Python-tool-hooks (or mix). Must consume the validator's warnings (overflow, font_unsupported,
   and now the clear data-shape/hex errors) to self-correct. The probe's standing-scaffolding
   experiment is the seed of its system prompt. Continue probing fresh agents on NEW scenarios to
   test whether scaffolding generalizes.
4. **Render-and-critique loop** — agent renders, self-assesses against specs as rubric, loops.
5. **Font embedding** — deferred until a brand-font case forces it.
6. **Design-system / template ingestion** — **Tier 0/1 BUILT (commit b58fbf3)**: `ingestion/`
   extracts a lossless theme bundle (colors/fonts/slide size/background/master text styles,
   provenance + coverage per INGESTION_SPEC.md) and `transpile_deck(..., themes=...)` injects it.
   Proven against the Deloitte template end-to-end (untracked; tests skip without it). Deferred,
   recorded in the spec: layout mapping (Tier 3/agent), gradient/image backgrounds, multi-master
   variants, Tier 2 inference from sample slides.

## Working method that made this affordable

Small, independently-verifiable steps; prove riskiest XML in isolation, wire, render one example,
generalize, lock with a property test (not byte-match — properties survive cosmetic edits).
Diagnose by isolating which layer lies: direct-call the builder, trace the resolver (monkeypatch
`_box_for_node` to print the geometry chain — did this for the free bug), unzip and grep the
package. Built largely by hand with an assistant reviewing — clean architecture + externalized
specs/tests are what made it feasible across many sessions and machines (Linux primary at
`/home/zeus/Projects/Paro`; also developing on macOS).
