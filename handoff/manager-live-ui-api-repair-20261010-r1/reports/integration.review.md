# Independent backend and integration review — integration_03

## Verdict

- **Spec: PASS** for the authorized offline repair candidate.
- **Code quality: APPROVE.** No blocking correctness, guard weakening, provenance loss, or scope violation was identified in the reviewed product bytes.
- **Acceptance status: PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN.** This is an offline source and regression review. It does not establish deployed repair behavior or a unique historical live cause.

The two low-severity boundary observations found in the preceding review were fixed by the original implementers and independently re-reviewed as scoped deltas. **No open findings remain.** Packaging, patch replay, remote synchronization, and assembled-deliverable verification are separate gates and are not claimed by this review.

## Exact review identity

The initial `integration_01` snapshot was internally consistent but older than the final binding-safety check and Python tests. The substantive review used immutable `integration_02`; this final approval applies to `work/reviews/integration_03/{before,after,hashes.json,tests,tools,support_hashes.json}`. The integration diff was examined in `integration_01/code.diff`, the helper in `integration_02/after`, and the complete `integration_02` → `integration_03` product/test delta was independently compared. That final product delta contains only a string-type check for mode and the diagnostic total-count limit changing from 32 to 64.

I independently computed all seven final runtime preimage/postimage hashes and compared every postimage with `work/candidate`. All matched. I also verified all seven frozen test/tool hashes in `integration_03/support_hashes.json`. The three backend and four frontend loaded-module hashes in the refreshed `reports/backend.final.json` and `reports/frontend.final.json` match the exact approved runtime files.

| Runtime file | Approved SHA-256 |
| --- | --- |
| `v4/manager_research/workspace.py` | `a6d6f067f04a3b543a8436e3080c9f7831e812a2cd10bbe16b783d23692ed33a` |
| `v4/manager_research/workspace_identity.py` | `3c0680ed3996c754ebf0849830e2cd820ebc32d5e01e196ec0e125b5e439062b` |
| `v4/manager_research/workspace_projection.py` | `06b1e5cc770f22db8e111aa61fec9ba1f6ef8b7da5dca3da9a32995203634b17` |
| `apps/web/src/manager-selection/businessStatus.ts` | `25504185cef4cb8fdae83ec3043b371631fe9448d752e24105a1fe9438f47aba` |
| `apps/web/src/manager-selection/catalystObservationPanel.ts` | `ba13f895bf8b315c9649e73b4a4a6e843cf5d1475b25587745d72a76e7ef7173` |
| `apps/web/src/manager-selection/dailyChannels.ts` | `44b2fa24a470e4dec6c4318a49c9d028e481a67e93d3f996775cd933bd1a040e` |
| `apps/web/src/manager-selection/researchAttention.ts` | `40c168a7f69a0bf5c655b550e865e6b54b0348d1c4c1bba9718696cc663fe9b0` |

The exact resolved original readers remain unchanged: `infrastructure/research_lane_source.py` is `2a58fe0db5c5d7915e7dbc884b8720e7d32a8c0084fe5e78b0e9e37f9e738cd4`; `v4/manager_research/existing_materials.py` is `88144b666e4a78ef46513f6eaf9846367ad0189478d9b3b85b9ac8124a5ca6e1`. I independently verified unchanged bytes for both, `connect_selection.py`, `workspace_plan.py`, the frontend API validator, and the real Vue callsite. An AST comparison confirmed that the generic `workspace_projection.digest` implementation is unchanged.

## Spec and safety assessment

### 1. Narrow consumed-reference normalization — PASS

`workspace_identity.py:28–93` removes exactly one field, `manifest_sha256`, from a reference inside `source_refs` or `input_bindings` when its recognized research binding is complete. Admission requires the expected source ID, verified status, read-only/research declarations, false production/BUY/order flags, an absolute root, a valid date, exact archive or hourly payload/receipt paths, and valid payload/receipt/manifest SHA values. An explicit `RESEARCH_ONLY` value must be true. An explicitly supplied manifest-entry digest must equal the payload digest; the original reader's payload digest is already the exact manifest entry.

All other fields remain in the semantic copy, including source root, ledger root, date, mode, slot, paths, payload/receipt SHA, optional entry SHA, and unknown extensions. Unknown owners, non-research manifest scopes, missing binding fields, wrong dates/paths, and unsafe flags receive no registry-insensitive compatibility. `source_row`, `original_source_row`, and literal content containers are copied opaquely; quoted binding-shaped source content stays identity-sensitive. The actual inputs and returned raw provenance are not mutated.

This helper recognizes already admitted provenance; it is not an artifact validator or an alternate admission path. The original `_read_archive` still calls the exact store reader before projection and checks the consumed payload digest against the returned binding (`existing_materials.py:100–116`). The real-source tests exercise that path with local files, retaining the manifest, receipt, schema, safety, and exact-date checks.

### 2. Complete identity chain and semantic sensitivity — PASS

The base projection now hashes its semantic copy and records the explicit `CONSUMED_RESEARCH_ARTIFACTS_V1` contract (`workspace_projection.py:478–507`). Its original input fields remain represented. Material content and semantic availability remain sensitive; source refs are not deleted from the raw workspace.

The same interpretation reaches the relation-material identity (`workspace.py:449–459`), attention projection, and relation-card extension (`663–680, 873–884`). This addresses the additional coupling points that a base-projection-only edit would leave behind.

`_extend_workspace_identity` (`683–703, 924–931`) preserves the original ordered outer chain and its conditional admission: gated projection, research attention, announcement selection, optional reviewed analysis, optional announcement product, exact US payload, and admitted daily mapping artifacts. Empty optional contributions remain absent rather than acquiring substitute data. The Connect gate and daily-mapping cutoff logic remain unchanged. Security-master/panel manifests keep their original identity meaning.

The generic digest continues to seal the complete serialized object. There is no global digest override, cached-success shortcut, blanket CURRENT assignment, dropped source row, or automatic reseal/migration.

### 3. Readback, versioning, failures and immutability — PASS

The original saved-product SHA, date, schema, owner/run, cutoff, semantic-version and sealed owner-attempt checks remain active. Readback additionally requires matching identity-contract versions (`workspace.py:1071–1082`); scheduled reuse has the same added requirement (`1206–1216`). A pre-repair saved plan is therefore not silently reinterpreted under the new contract. Adoption requires a new product from the existing authorized owner workflow.

Unchanged new-contract input identities can reuse the same saved run/product, with runtime overlays on a deep copy. Actual semantic changes remain stale and unconsumed. Stored bytes and journals are not rewritten by readback. The independent extra check for an existing, validly sealed attempt with the wrong input identity returned `OWNER_ATTEMPT_UNVERIFIED`, `consumed=false`, and `PLAN_OWNER_PRODUCT_ATTEMPT_READBACK_MISMATCH`.

The additional attention pass calls only the original pure projector. It replaces only the top-level attention input identity and returns the original business output and raw provenance. It has no catch-and-reuse fallback: failure in semantic reprojection propagates, and existing refresh failure handling applies. Checkpoints surround the additional projector call. This preserves fail-closed behavior, although cancellation remains cooperative and does not preempt a long pure call.

### 4. Bounded, attributable diagnostics — PASS for the current contract

The current producer records a fixed 22-component vocabulary: 12 projection components, three attention components, and seven outer components. The sealed new plan retains that evidence. Comparison returns SHA digests and names, sorted deterministically, with no raw article bodies and at most 16 displayed component records (`workspace_identity.py:96–147`). Missing, invalid or inconsistent evidence falls back to `CANNOT_CONFIRM`; old evidence is not reconstructed from assumptions.

The frontend consumes the additive diagnostic object through the existing API validator, verifies its binding to the returned workspace identity, and preserves stale/unconsumed status (`businessStatus.ts:48–65`). Components identify affected input groups; they are not a per-article or exact-field diff and do not prove a unique cause. The preserved saved product and current owner provenance supply the underlying audit evidence.

The historical live mismatch remains **CANNOT_CONFIRM**. Whole-registry coupling is a proven contributor, with insufficient evidence to claim it was the only changed field in the historical live GET.

### 5. Frontend integration and research-only scope — PASS

I consumed the independent frontend review at `reports/frontend.review.md`, checked its approved hashes against the combined snapshot, and cross-checked the additive diagnostics interface and unchanged API validator. Its four approved runtime files match `integration_02`; only the reviewed count-limit delta changes `businessStatus.ts` in `integration_03`. The existing daily renderer is connected to the actual panel with dates from the same workspace response; stale plans do not hide independently valid daily channels. The upper US assessment and daily reviewed-mapping scope remain distinct. Core research results precede an initially collapsed audit area that retains all raw rows.

No alternate producer, live read, capture/import, market backfill, schedule change, source-root change, rank/selection rewrite, deployment, BUY gate change, or order action was introduced. The safety flags remain `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.

## Evidence assessed and independent checks

- `reports/backend.final.json`: **35 tests, 0 failures, 0 errors, 0 skipped**, with loaded-module hashes matched to this snapshot. The real pure projection, attention stage, relation and outer identities, local sealed-plan readback and original exact-source guards are covered. The full `_compute_workspace` owner graph is not exercised end to end by this suite.
- `reports/frontend.final.json`: **22 passed, 0 failed**, `setup_error=null`, with all four runtime hashes matched. It executes actual panel/renderers/API validation with synthetic responses in LinkeDOM. The separate frontend review documents the DOM limitations and static race-condition review. The two additional final cases accept a valid 64-component union and reject an impossible count of 65 while preserving stale/unconsumed state.
- I independently ran nine additional narrow checks against `integration_02/after`: exact hourly bindings in LIVE/REPLAY/BACKFILL, receipt-slot mismatch conservatism in each mode, unknown extension preservation, a standalone binding outside declared provenance containers, and a mismatched sealed owner-attempt identity. All nine passed; loaded hashes and outcomes are in `reports/integration.narrow.json`. An initial reviewer assertion incorrectly expected a nested declared `source_refs` container to remain untouched outside its enclosing binding; the fixture was corrected before these recorded checks. No implementation change was needed.
- I independently ran four scoped checks against final `integration_03/after`: malformed modes `[]`, `{}`, and `['LIVE']` retain the complete fingerprint and remain sensitive to the manifest SHA; two disjoint 32-key component maps remain bounded to 64 total changes and 16 returned rows. All four passed, with final loaded hashes recorded in `reports/integration.delta.json`.
- The focused backend red log reproduces the original `TypeError` before the mode fix. The frontend boundary red report records **21 passed / 1 failed**, with the 64-count case failing against the former `businessStatus.ts` SHA; the same expanded suite is green in the final report. The 65-count case already rejected invalid totals before the fix and remains green afterward.
- The final broad offline suites were not redundantly rerun by this reviewer. Their recorded counts, commands and loaded bytes were checked directly; additional execution targeted uncovered boundaries only.

## Resolved review observations

### P3 — malformed unhashable mode — RESOLVED

**File:** `v4/manager_research/workspace_identity.py:54–56`.

The prior code raised `TypeError` for an unhashable mode such as `[]`, differing from its stated conservative-copy fallback. The final helper first checks `isinstance(mode, str)`, so malformed shapes retain the full fingerprint. The original owner never emitted the malformed mode, but the fix improves the helper's defensive contract without extending admission. The new regression and three independent malformed-mode checks pass on the final SHA.

### P3 — component union exceeds frontend total-count limit — RESOLVED

**Files:** `v4/manager_research/workspace_identity.py:101–107,133–146`; `apps/web/src/manager-selection/businessStatus.ts:59`.

Each input component map allows 32 keys, so their union can contain 64 changed keys. The final frontend admits totals through 64, matching the backend's bound, while keeping at most 16 received component rows and at most four visible names. A total of 65 remains invalid. The 64-count boundary was reproduced independently; the mounted 64/65 cases pass on the final frontend SHA. The fixed 22-key current producer is unchanged.

## Performance, portability and unverified limits

The recorded attention benchmark uses 1,970 synthetic refs and one company symbol, with three timing samples per variant. The median original pure call was **0.365 s**; the repaired attention stage was **0.831 s**, approximately **0.466 s additional / 2.28×** for that stage. The returned business output and original inputs matched. This measurement used the preceding helper SHA `0346db36ff99e4e323e1256854673ff3d4c8c32977b33c700108af914b605525`; it was not rerun after the final mode-type guard. It is neither an exact-final-byte performance result nor full-workspace latency, peak-memory measurement, concurrency testing, a broad issuer distribution, or Mac/API timing. The base projection also copies and hashes component inputs; deployment acceptance must assess total latency and the existing timeout budget.

The inspected portable backend runner reports empty discovery as an error, failure exit codes, skipped tests and loaded source origins. The offline orchestrator assembles temporary source trees and returns failing child statuses. The source gate is read-only and compares declared changed files and unchanged prerequisites against the supplied manifest. Those three tools do not apply patches or contact live services. The frontend runner requires Node APIs available in the recorded Node 24 environment; Python evidence used 3.12.14. The final tool snapshot's hashes were verified, but the later report-directory guard, new `verify_delivery.py`, and full portable execution against the assembled delivery belong to the separate packaging review and are not approved or claimed here.

Recovered `test_support/upstream` modules, including `research_attention.py`, remain **test support with unproved current-deployment identity**. Inspection confirms the supplied attention implementation is pure and deterministic on fixed inputs, but this review does not certify an unseen deployed variant. Original application build/full-repository tests, real-browser paint/layout, Mac owner execution, deployed API/UI readback, browser-loaded bundle SHA and natural-session acceptance remain **NOT_RUN / CANNOT_CONFIRM**, as applicable.

No live services, business data, GitHub mutation, or production implementation edits were performed by this reviewer.
