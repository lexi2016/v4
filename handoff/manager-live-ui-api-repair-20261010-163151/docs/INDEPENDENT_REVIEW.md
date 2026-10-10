# Independent review — V4 Manager UI/API proposal

**Review result: no remaining P1/P2 defect found in the eight reviewed production files after the scheduled legacy-reuse and narrow-layout findings were corrected. Delivery status: `PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN`.**

This review supports a bounded code proposal. It does not establish that the deployed Mac application has been repaired, that the historical live mismatch has a unique known cause, or that the original owners now produce complete results. The final source SHA-256 values are recorded in `evidence/independent/backend_review_source_sha256.json` and `frontend_review_source_sha256.json`, relative to the delivery root.

## Review scope and execution boundary

The controlling supplied report is `PROBLEM_REPORT.md`, SHA-256 `83d25c253e8705ca6b87fca280e667c6548dcb942d530640d1a5a40b9aeeeec3`. It is byte-identical to the separately attached `PROBLEM_REPORT(2).md`. The approved work is the consumed-artifact semantic identity correction, source-backed stale diagnostics, actual panel wiring for the existing daily channels, truthful US scope/count presentation, and moving the complete raw observation audit after the core results.

The review compared the four backend files against the supplied/recovered before-images and the four frontend files against their supplied before-images. The existing `apps/web/src/api/managerWorkspace.ts` validator remains byte-identical at SHA-256 `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f`. No candidate source was edited by this reviewer. Reviewer tests used synthetic in-memory owner returns and an offline Chromium request boundary; all browser requests were locally fulfilled or aborted. No live API, owner, finance provider, service, scheduler, Mac state, deployment, or Git write was executed by this reviewer.

The target/selection date remains `20261009`, publication date `20261008`, and retrospective review date `20261010`. The safety contract remains `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.

## Findings resolved during review

### P1 — scheduled same-identity reuse bypassed the legacy guard

The first backend candidate rejected a sealed legacy product without the new identity schema/component baseline in ordinary `_readback_plan`. The shared scheduled `ALREADY_MATERIALIZED` branch still accepted the old product using the prior equality check. An independent regression constructed a same-hash legacy product with a valid exact morning attempt: normal readback was stale and unconsumed, while scheduled refresh reused the old run as consumed and verified.

The implementer added the same compatibility diagnostics and prepared-cutoff check to the shared morning/preopen reuse branch. All existing date, exact-attempt, deadline, and product checks remain. The independent regression passes after correction and confirms the old per-run product stays unchanged. The expanded backend suite covers both scheduled modes negatively for legacy products and positively for compatible v2 products. Review of the explicit consumed-return and identity-reuse branches found no remaining route around this guard.

Evidence: `backend_review_initial.log`, `backend_review_after_legacy_fix.log`, and the final paired backend logs under `evidence/independent/`. The initial failing evidence is preserved; it was not overwritten by the successful rerun.

### P2 — the intermediate layout kept narrow-view status labels below the fold

The intermediate frontend placed all business-status rows before the daily summary. The implementer’s 670-by-900 regression recorded all three daily status labels outside the initial viewport. The final layout places the existing plan status and stale-input explanation first, then the daily summary, followed by the remaining business-status rows. The US assessment and daily mapping rows remain adjacent. The daily grid’s minimum width was adjusted to allow three channels at that tested width.

Independent final geometry checks with an explicit local CJK font confirm all three status labels in the initial viewport at 1600×1200, 1280×800, 670×900, and 669×848. No horizontal document overflow was observed in those fixtures. Full channel provenance and longer diagnostics continue below the first viewport or in expandable details; this review does not claim every field fits above the fold.

Evidence: `frontend_red_narrow_implementer.log`, `frontend_viewport_probe.log`, and `viewport_geometry.json` under `evidence/independent/`. The red viewport result is attributed to the implementer; the final geometry probe was independently authored and executed.

## High-risk acceptance review

| Risk from the implementation plan | Independent assessment |
|---|---|
| A same-named global hash in business content, HK eligibility, or an incomplete binding is incorrectly ignored | The semantic helper exempts only `manifest_sha256` in recognized complete, verified, read-only V35 `source_refs`/`input_bindings`. Source/date/root/path, payload, receipt, optional entry hash, safety fields, semantic availability, and other data remain sensitive. Original source rows and structured content are not recursively normalized. Concrete negative regressions cover these boundaries. |
| Only the inner projection is corrected, leaving the outer identity unstable | Reviewed the projection, selection-material relation digest, outer relation-card digest, and admitted research-attention card digest. The full `_compute_workspace` synthetic integration executes these actual functions and the daily builder. Global-only changes remain semantically stable through the outer identity and same-run readback. Existing announcement, US, mapping, Connect, and cutoff-admitted extensions remain included. |
| Same input bypasses date, cutoff, semantic-version, product, or owner-attempt checks | Ordinary readback and shared scheduled reuse require the new component contract in addition to the retained guards. The suite exercises legacy rejection, current v2 reuse, changed date/version/cutoff, invalid product/safety, and exact-attempt failure. Diagnostics cannot override `OWNER_ATTEMPT_UNVERIFIED`; unavailable legacy evidence remains `CANNOT_CONFIRM`. |
| Collapsing raw observations loses rows or changes producer inputs | The actual panel test renders 100 synthetic rows, verifies their complete ordered stock-key collection, expands the last row’s source JSON, rereads, and verifies all 100 remain. The outer audit starts closed again after rendering. The patch changes DOM order and disclosure state; the original stock collection/render path remains. |
| UI weakens date/run/product/safety admission or converts unknown to zero | The full existing response validator is unchanged. Twelve invalid-response cases execute the real fetch/parser/panel path and clear previous candidates into explicit unknown channel states. Candidate/pending null counts stay unknown; ready-empty remains distinct. US reviewed-set counts of 4, 7, and null render dynamically and do not imply full-market coverage or assessment completeness. |

The daily renderer consumes `value.daily_channels` and `value.date_bindings` from the same validated workspace response. A refresh renders that validated POST response without another GET. Date changes clear the prior result before rendering the new response. The renderer adds visible status, owner, data date, run/product/input identity, counts, and concise gaps; full source data remains in lazy text-only details. There is no second producer or change to selection, Stage, BUY, HK/US pool, or execution rules.

The added stale-input panel displays supported changed-component names and the complete saved/current diagnostic object as text. Missing component evidence remains `CANNOT_CONFIRM`. The independent browser probe also supplies literal markup in source-derived display strings; it remains text and creates no injected DOM element or external request.

## Fresh executed evidence

| Check | Actual result | Interpretation |
|---|---|---|
| Supplied `verify_package.py` | Exit 0: 57 source files, 19 evidence items, 85 package files | Manifest integrity only. Its expected sibling-ZIP lookup is unavailable in this extraction layout. |
| Supplied `check_evidence_contract.py` | Exit 0 | The supplied metadata contract holds; no owner/API/UI behavior exercised. |
| Independent actual-upload check | ZIP CRC passes; 85 unique members all match extracted bytes and manifest | Resolves the verifier’s layout-specific ZIP limitation. |
| Independent source/receipt audit | 44 assertions pass | Cross-checks fixed-source Git blob/SHA identities, dates, run/product receipts, screenshot hashes, safety flags, and recovered source pins. |
| Same final backend suite on pristine assembled baseline | 21 methods ran; 19 assertion failures including subcases; no import/test errors; exit 1 | Before-image fails the intended new regressions. |
| Same final backend suite on candidate | 21 methods pass; exit 0 | Actual imported modules with explicit synthetic owner/import/calendar boundaries. |
| Independent scheduled legacy regression after correction | 1 passes; exit 0 | Reproduced alternate reuse path no longer consumes the legacy run. |
| Independent diagnostic scale probe | Exit 0 | 1,970 synthetic materials and 40 unique bindings; global-only change stable; one consumed receipt change accurately locatable. |
| Independent real-panel browser suite | 23 implementation cases plus 1 independent text-rendering case pass; exit 0 | Actual panel, fetch/parser, and validator modules in offline Chromium. |
| Independent four-size geometry probe | Exit 0 | Each status label is visible in the tested initial viewports; horizontal document width stays within the viewport. |

The scale fixture contains 17,628,420 bytes of synthetic material JSON. The one-component diagnosis contains 40 deduplicated saved and current source references and is 66,537 bytes. Its 0.912-second run checks representative source-list growth and locatability in this environment; it is not a live latency guarantee. No historical market payload or receipt body was used.

The frontend suite uses the actual nine TypeScript modules after type stripping, with two unchanged fixed-source support modules for missing imports. It uses test fonts and a synthetic page host, not the production Vue shell, final build bundle, or a Mac browser session. The harness provenance and rendered-source hashes record those boundaries. The independent copy preserves the implementation cases and changes only test-local dependency/launcher paths, then appends the text-rendering probe.

## Supplied evidence and source-provenance limits

The original archive `V4_MANAGER_LIVE_UI_API_PROBLEM_20261010(2).zip` is 1,037,157 bytes, SHA-256 `c8e8f42a108d144ab2a8182c516b7c0173f55cde8566d3d630709151303b5da4`. Origin filenames and SHA-256 values are listed in `evidence/independent/ORIGIN_REFERENCES.json`. No supplied screenshot or raw market data was copied into this review evidence directory.

The source count of 57 comprises 16 fixed references, 9 current UI/API context files, and 32 prior reference files. Only 25 current source files were supplied. The package omits the raw 1,970-material array, original artifact bytes for the 40 payload/receipt pairs, prior global manifest, live GET body/digest, loaded browser bundle, and full dependency/build metadata. The original subset has 59 missing directly referenced local Python modules; that count is a static inventory, not a transitive dependency result.

The source identity triad was physically absent despite its hashes in the root-cause receipt. The parent recovered exact blobs from `lexi2016/v4` commit `c0fc35c7b39502f49e43c2e75139dad7822091cf`; this reviewer independently recomputed their Git blob IDs and SHA-256 values. The correct `existing_materials.py` is the **api** variant with blob `37d68758dc987a919ffb28fee3c35cdde8d7c6aa` and SHA-256 `88144b666e4a78ef46513f6eaf9846367ad0189478d9b3b85b9ac8124a5ca6e1`. The different canonical variant is not an interchangeable before-image.

The `research_attention.py` before-image is recovered from that fixed commit but was not independently live-pinned in the supplied report. Its conditional precondition is SHA-256 `3f5385ed850b0336cb85ad85cac3aeab44d2908620c636a4cfc19f5fdf3619aa`. A different Mac file requires reconciliation before any later application of the proposal. This review does not authorize replacing mismatched deployed bytes.

The historical root-cause report cites evidence projection SHA-256 `dda047f7a8ee6b9a442ee7ae7ebf175d1edf6d0856430e5a03c4e1802e4b4805`, while the actual supplied `evidence/live_ui_api_problem_projection.json` has SHA-256 `0438d5b55e06bc36483edcdb4b98c801924431522a3b2b50ab855fc9dda4b7b7`. A prose example receipt hash is also truncated to 63 characters; the machine receipt contains the full 64-character value. These caveats are preserved without rewriting the input evidence. The supplied reproduction script was inspected but not executed because it reads hardcoded Mac state and overwrites its historical receipt.

## Claims that remain unconfirmed

The historical immediate POST/GET/GET and later stale GET agree on the deployed run, product, and target date. They show a real saved/current identity mismatch, but the exact changed live field and unique cause remain `CANNOT_CONFIRM`. The historical counterfactual receipt supports global-manifest coupling; its 40 distinct metadata pairs can be recounted, while its 1,970-material count and original owner bytes cannot be independently replayed from this package. The corrected isolated run is a different run with partial results and in-process readbacks, not deployed API/UI acceptance.

The corrected root establishes that the exact 20261008 panel exists. Exact-date security-master authority, six-session volume unit/scale, provider finality, target HK V2 membership, current announcement completion, and full-market US coverage remain outside this repair’s established evidence. The 693 pending/695 screen gaps and separate attention/workspace gap counts have different scopes. The four-reviewed-relation `VALID_EMPTY` result does not prove market-wide emptiness. The prior 613 Reader/613 Reviewer/33-selected announcement evidence belongs to target 20261008/publication 20261007. The user-reported 20260930 standalone run remains `CANNOT_CONFIRM` here and is not disproved.

Loaded production bundle identity, original full-project build/test success, post-repair Mac owner execution, repeated real same-run HTTP readbacks, real UI behavior, and natural-session acceptance remain `NOT_RUN` or `CANNOT_CONFIRM`. Compilation, isolated tests, source recovery, and this review must not be promoted into those runtime claims. Final patch replay and packaged source-integrity checks are the parent integrator’s separate gate.
