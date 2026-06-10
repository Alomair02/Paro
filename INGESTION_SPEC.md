# Template Ingestion — Theme Bundle Specification (v1, Tier 0/1)

## Purpose and boundary

Ingestion turns a user-supplied `.pptx`/`.potx` into a **theme bundle**: a declarative,
JSON-serializable artifact that loads into the engine's registries so generated decks
inherit the template's theming. It captures *theming*, never content — Paro generates new
slides that belong to the template's family; it does not clone slides (the project's
load-bearing replication boundary).

Two operations, kept architecturally separate:

- **Extraction (this spec, Tiers 0/1)** — deterministic reads of what the file *declares*:
  theme part, master, layouts, presentation properties. Every `.pptx` carries these (OPC
  requires them), so extraction never yields nothing. Extraction failures are bugs.
- **Inference (Tier 2+, future)** — statistical reads of what the file *practices*:
  recurring hand-placed design elements, de facto type hierarchy, actual accent usage.
  Inference failures are judgment calls. Different tests, different confidence semantics.

## The contract: lossless capture, honest consumption

A user-supplied template is ground truth. The extractor's obligations:

1. **Capture is 100% lossless** for the theme surface: every color slot, both scheme fonts,
   slide size, master background, master text styles. What the engine cannot yet consume is
   still captured — either resolved into the bundle or preserved as raw XML under
   `preserved` — never dropped.
2. **Consumption is honest.** `coverage` says exactly which blocks the engine will `use`,
   which are `preserved` (captured, awaiting engine support), and which were `skipped`
   (with a reason). Nothing is silently absent.
3. **Provenance on every block.** `extracted` (read verbatim from a part) vs `derived`
   (computed by a documented deterministic formula). Tier 2 will add `inferred`
   (statistical, with sample counts). The agent layer uses this to know which blocks are
   solid and which to confirm with the user.

## Bundle format

```json
{
  "bundle_version": 1,
  "source": {
    "file": "Deloitte ... Template.pptx",
    "theme_part": "ppt/theme/theme1.xml",
    "theme_name": "Deloitte_US_Onscreen",
    "color_scheme_name": "Deloitte colors",
    "font_scheme_name": "Deloitte Powerpoint font"
  },
  "theme": {
    "colors": { "dk1": "000000", "lt1": "FFFFFF", "...": "all 12 slots, 6-hex uppercase" },
    "fonts": { "heading": "Verdana", "body": "Verdana" },
    "typeScale": {
      "title": { "size": 20.0, "provenance": "extracted" },
      "body":  { "size": 12.0, "weight": "normal", "provenance": "extracted" },
      "heading": { "size": 14.5, "provenance": "derived" }
    }
  },
  "slide_size": { "cx": 12192000, "cy": 6858000, "engine_size": "16:9" },
  "background": { "kind": "scheme", "token": "lt1", "provenance": "extracted" },
  "master_text_styles": { "raw per-style size/bold/font, for Tier-2 and audit" },
  "coverage": {
    "used": ["theme.colors", "theme.fonts", "..."],
    "preserved": { "fmtScheme": "<raw xml>", "layouts": {"count": 41} },
    "skipped": [ { "what": "...", "why": "..." } ]
  }
}
```

## Extraction rules (the load-bearing details)

- **Part discovery is rels-driven, never path-guessing.** `_rels/.rels` → officeDocument →
  `presentation.xml` → first `p:sldMasterId` rel → master part → its theme rel. Real files
  carry multiple theme parts (the Deloitte template has three: slide, notes, handout
  masters each own one) — only the **slide master's** theme is the deck theme.
- **Colors:** `a:srgbClr/@val`, or `a:sysClr/@lastClr` (dk1/lt1 are `sysClr` in real
  templates). Normalized to uppercase 6-hex; missing `lastClr` falls back to the sysClr
  defaults (windowText → 000000, window → FFFFFF) and is reported.
- **Fonts:** `a:majorFont/a:latin/@typeface` → `heading`, minor → `body`. Empty typeface
  is reported, not emitted.
- **Slide size:** `p:sldSz` EMU, mapped to the nearest engine size name; a non-matching
  size is reported in `coverage.skipped` and the engine default is used.
- **Background:** the master's `p:bg`. `bgPr` with solid `srgbClr`/`schemeClr` resolves
  directly. `bgRef` resolves through `fmtScheme`: idx 1–999 → `fillStyleLst[idx-1]`,
  idx ≥ 1001 → `bgFillStyleLst[idx-1001]`; the referenced style's `phClr` is substituted
  with the `bgRef` color (scheme tokens mapped per the default clrMap: bg1→lt1, tx1→dk1,
  bg2→lt2, tx2→dk2). Only solid fills resolve in v1; gradient/image background fills are
  preserved raw and reported.
- **Type scale (the hierarchy-coherence rule):** the master's `titleStyle`/`bodyStyle`
  lvl-1 sizes are extracted exactly (`sz`/100 → points) — these two are ground truth.
  The remaining roles (`heading`, `subheading`, `bodySmall`, `caption`) are **derived** by
  proportional interpolation against the default scale, because merging extracted
  title/body into the default scale naively can invert the hierarchy (e.g. a 20pt
  template title under a 24pt default heading). Formula: heading/subheading interpolate
  linearly between body and title at the same relative position they occupy in the default
  scale; bodySmall/caption scale from body by the default ratios; `minSize` keeps each
  role's default minSize/size ratio; results round to 0.5pt. Weights: extracted where the
  master declares `b`, otherwise the default role weight.
- **Explicit weight/font per style** are captured in `master_text_styles` even when the
  type scale doesn't consume them (audit + Tier 2).

## Engine seam

- `ingestion.extract_theme_bundle(path) -> dict` — the bundle.
- `ingestion.bundle_to_registry_themes(bundle, name) -> {name: theme_dict}` — strips
  provenance, returns exactly the `ThemeRegistry` injection shape.
- `transpile_deck(..., themes=...)` — injected themes are merged under inline `<theme>`
  definitions (inline wins; an author's explicit override outranks ingestion).
- A deck then opts in with `<deck theme="deloitte">`.

## Layout transplant (BUILT — ingestion/layout_extractor.py)

The gap the theme bundle left — placeholder slides resolving against Paro's generic
layouts — is closed by a second, parallel extraction: `extract_layout_transplant(path)`
captures the template's slideMaster, slideLayouts, theme part, their `.rels` and
referenced media **verbatim** (byte-for-byte under original part paths, so internal
relationships stay valid), plus a parsed placeholder inventory (idx/type/geometry,
master-inherited when the layout omits xfrm).

- **DSL name mapping**: designed layout names are the primary signal ("Title Slide…" →
  `title`, "Divider…"/"Section…" → `divider`, "Title Only", "Blank"), placeholder
  signatures the fallback; covers/dividers never stand in for content layouts. First
  match in template order wins.
- **Consumption**: `transpile_deck(..., layout_transplant=...)` swaps the generated
  theme/master/layouts for the template's, points each slide's layout relationship at
  the mapped template layout, and gives the resolver/validator the template's real
  placeholder geometry. `paro.py build --theme` does both extractions automatically.
- `title`/`ctrTitle` placeholder requests match either declared type — templates differ
  in which their cover uses, and the author intent is the same.

## Deferred (recorded so they're deliberate, not forgotten)

- **Semantic mapping beyond the heuristics** (which of 41 corporate layouts *best*
  fits a given slide's content) — Tier 3 (agent) judgment; the name map covers the
  blessed DSL names today and unmapped names fall back to the template's blank.
- **Gradient/image master backgrounds** — preserved raw now; needs background-fill
  vocabulary in the deck schema beyond solid/`image:` to consume faithfully.
- **Multiple slide masters** (dark/light variants) — bundle schema reserves a list;
  v1 extracts the first and reports the rest.
- **fmtScheme consumption** (fill/line/effect styles) — preserved raw; the engine's
  finishes own this surface today.
- **Tier 2 inference** — recurring design elements, de facto accent usage, chart styles
  from embedded charts, type-scale refinement from sample slides.
