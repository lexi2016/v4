# Minimal next source scope — proposal only, not implemented

The completed batch is a same-source rendering artifact. It is not yet bound
to the live daily page or a natural daily owner run. No service/pin change is
implied by this proposal.

The smallest immediate C scope is three existing files plus focused GET/UI tests:

1. `infrastructure/research_lane_source.py`: add a GET-only reader for the
   existing original-chart manifest. Bind requested symbol/date to the exact
   current product manifest/artifact, source generation/input, formula/engine,
   and per-stock HTML/PNG/projection refs/SHA. Use an explicitly bound artifact
   root; accept no arbitrary file/path argument. Missing/stale chart evidence
   stays typed CANNOT_CONFIRM and does not alter the numeric candidate list.
2. `apps/api/v4_api/research_router.py`: expose that existing artifact through
   the already-mounted research router. The current daily-product/history
   routes have no d35c chart-manifest read contract. Serve validated existing
   HTML/PNG or their bound URLs, without computing formulas or rendering on GET.
3. `research-panel/numeric283-panel.js`: its `loadChart` currently requests
   ACTIVE_MA history, not d35c51/22. Read the same-date manifest/ref for the
   selected stock and use the already generated original-chart HTML in the
   existing chart area. Reuse the current request-token/abort/date/generation
   checks and current completion listener; no per-minute polling and no daily
   rebuild of `daily.html`. The HTML already contains the unchanged R19 renderer,
   so this first binding does not require new chart semantics.

Natural daily materialization is a separate, explicitly frozen small follow-up:

- `ops/macos_research_panel_daily_gate.py:584-590` is the existing A owner call
  to `materialize_daily_product`. It should own deriving only missing current
  candidate chart artifacts and publishing the matching completion, rather
  than scheduling a second producer or an independent timer.
- `ops/research_panel_daily_product.py:131-137` currently computes the pinned
  full51/22 in `source_inputs` and then discards that sequence. Guaranteeing
  zero duplicate formula computation requires Root to explicitly authorize a
  narrow output-retention handoff in this frozen file: pass the already computed
  one-stock result to the owner/render sink, release it after use, and leave all
  numeric predicates/membership/statistics unchanged. Do not accumulate5808
  histories. Without this approved handoff, daily zero-repeat behavior remains
  CANNOT_CONFIRM; the immediate GET binding can still reuse this completed batch.
- `ops/render_original_formula_projection.py` needs only a separately reviewed
  move from the current frozen D29/247 batch constants to the owner's explicitly
  supplied product date/allowlist. Key reuse by source/formula/engine/bars SHA;
  do not reinterpret a changed QFQ prefix as an unchanged incremental tail.
- `apps/api/v4_api/research_lane_router.py` and the existing completion descriptor
  need an optional hash-bound chart-manifest reference only if charts finish
  after the product event. Prefer producing chart sidecars from the retained
  result before the existing final completion is published, so no parallel
  event channel or timer is introduced. Exact event timing is a next-scope
  decision, not behavior established by this export.

Keep the current main HTML/renderer static. Each owner generation changes data
artifacts/manifests; the existing SSE refresh consumes them. The current scope
did not modify any of these files or claim live/natural integration acceptance.
