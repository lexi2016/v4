# Dashboard framework collaboration — PUBLIC / synthetic only

**Parent-frozen source export, pending independent public-content review; not uploaded.** This isolated package contains pure framework modules and synthetic interface tests, not the source/data/configuration of the private deployed Site.

## Scope and ownership
- Overall framework: date/identity coordination, candidate presentation, observation ordering, source-time status, bounded upload utility, and read-only adapter contracts.
- Individual-stock module remains owned by its existing author. Public upstream handoff: `docs/handoffs/STOCK_PANEL_COLLAB_20261030.md` at commit `9ed9d82500de9023f2fbfd73e106ee8ed3ae34f7` of `lexi2016/v4`.
- That handoff explicitly says arbitrary historical date/symbol deep-link is not yet complete. This package does not assert it is installed or overwrite its renderer.

## Run without private data
`npm test` (Node >=22, no install or dependency download required).
The `demo/` folder can be served by an already authorized static host. It uses only `demo/synthetic.mjs`; there is no production endpoint or background collection. The demonstration date, stock identifiers/names, prices, hashes and statuses are all artificial. It is not a historical research example.

No `.openai`, Site project identity, deployment configuration, real day contract, candidate list, admission pin, private Drive link, company material, renderer implementation, image/projection, API credential or source receipt is included. Do not mistake this package for a backup or full restoration of the private system.

## Integration contract
`src/readonly-adapter.mjs` requires an explicit same-origin API base path; GET only, no default production endpoint. Bind source_date, observation_date, symbol, generation, input identity and immutable revision from the actual authorized host. Missing/invalid date or identity must clear data, not fall back to another day. Consumers must keep PENDING/UNKNOWN distinct from storage availability and never infer eligibility or trade permission from display fields.

The existing business names in source describe field contracts, not source data or formula computation. `projection-view.mjs` only validates/adapts frozen rows for an externally supplied renderer; no renderer implementation/data is shipped. `workflow-time.mjs` consumes an injected contract; no real user schedule/calendar is shipped. Unit conversion/evidence, source-admission authorization, private ingestion handlers and real source identity are intentionally not included.

The six pure modules were checked byte-for-byte against the parent-frozen source. SOURCE_MANIFEST.json records the exported bytes; sanitized files explicitly differ. New readonly adapter/demo/tests are separately identified collaboration scaffolding; they are not the deployed private-site implementation.

## Sanitized backend reference (added scope)
`src/backend/observations.mjs` retains the full validation, immutable storage and history/query logic. It uses a public-only authorization shim that **always denies writes**, extracted bounded-input utilities, and an intentionally unconfigured volume-evidence registry. It contains no deployed Site identity, real source pin or real dataset. This is more than presentation-only source but is deliberately not deployable as a production backend. All transformations are explicit in SANITIZATION_MANIFEST.json; production-byte equivalence is not claimed. The independent host storage/auth contract is documented in `schemas/HOST_STORAGE_CONTRACT.md`.

## Actual visual shell
`shell/index.html` and `shell/research-system.html` retain the actual framework's layout/CSS and interaction wiring, not merely a redesigned diagram. A public export intentionally has no `framework-api-base` meta configuration, so it stops at a clear unbound empty state without network requests. Explicit same-origin host injection is needed before reading any service. Real personal schedule literals and runtime counts are removed, timetable grouping is injected via `visual_stages`/`stage_index`, and real schedule/material JSON is not included. No chart is fabricated: external renderer is absent and the shell says so. Company validation is a deliberately disabled generic placeholder. These changes are recorded separately from byte-identical style/source. The synthetic demo remains independently runnable; neither shell nor demo claims production standalone completeness.
