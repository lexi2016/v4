# Task 2 independent frontend / API boundary review

## Verdict

**Spec: PASS within offline candidate scope. Code quality: APPROVE; the one P3 finding was addressed and independently reinspected.** The four frontend changes implement the requested existing-panel wiring, scope labels and collapsed complete close-observation audit. The root-owned API change adds diagnostic validation without removing or modifying existing validators. The initial review found one provenance label incorrectly identifying a path fingerprint as a source-code SHA. Root corrected it; the final inspected label states its actual path-fingerprint meaning.

This is a read-only production-source review of the fixed export comparison, not a checkout, Mac acceptance, running 8873 inspection or deployment approval. Fixed baseline Git parent: `c0fc35c7b39502f49e43c2e75139dad7822091cf`. Source reviewed: `/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app`; frozen preimages: `work/baseline/app`. Full review patch: `review/task-2-review.patch`. Candidate remains **PROPOSAL_ONLY**. **LIVE_API_UI_NOT_RUN**; natural-time acceptance **NOT_RUN**. No source edits, services, network, Git operations or subagents were used by this reviewer.

## Concrete finding

### P3 — source-root path digest was labelled as source-code-root SHA (ADDRESSED)

**Location:** `apps/web/src/manager-selection/businessStatus.ts:24`.

The new diagnostic renderer prints `源码根 SHA-256` for `source.source_root_sha256`. The actual producer computes this field in `v4/manager_research/workspace_identity.py:106` as `_digest(ref['source_root'])`; `_digest` at lines 21–23 hashes the JSON-encoded value. The archive reference requires `source_root` to be a string. This is therefore a fingerprint of the source-root **path**, not a digest of source-code or source-content bytes.

**Impact:** the UI's audit evidence can be read as proving which source-code bytes were used, which this field does not establish. The separate saved/current component hashes remain intact and admission is unaffected; severity is P3 rather than a trading-safety or identity bypass.

**Minimal fix:** replace the label with `来源根路径指纹 SHA-256` (or another explicitly path-based label). Preserve the field name/bytes and saved/current component semantics. A broad suite rerun is unnecessary for this text-only correction.

**Resolution:** root changed the label to `来源根路径指纹 SHA-256`. This reviewer reinspected the actual candidate line and SHA after the change: `f55b62da1af832386182752912f908bd387bc2b53f0351e56b7350267e83e9c0`. The field name, value, component semantics and safety behavior are unchanged. No additional test was executed for this display-only delta.

## Reviewed behavior and reasoning

- **Real parent relationship:** `ManagerSelectionView.vue:81` imports `mountCatalystObservations`; its existing post-flush watch at lines 2751–2755 disposes/remounts the child on host/reference-day changes. The implementation changes remain inside that child DOM host; no second page/data producer or Stage/BUY boundary is introduced. New HTTP tests invoke this production mount, request parser and full validator, instead of merely calling the daily helper in isolation. Existing whole-parent integration tests also exist; their final candidate outcome is root-owned.
- **Same response:** panel `render(value)` calls `renderDailyChannels` with `value.daily_channels` and `value.date_bindings`. Channel rows are not assembled from separate responses. `validateManagerWorkspace` continues to validate all existing workspace fields and validates daily bindings/channels before the renderer runs. Stale saved-plan status does not suppress otherwise valid channel cards.
- **Dates and aliases:** `selection_date ?? date ?? initialDate` is carried as an explicit source/selection binding. `announcement_date` wins over `publication_date`; the publication override is sent only when explicitly present. With neither override, canonical GET leaves the owner free to supply its prior-HK-day publication default. Returned optional binding is checked against the selected plan/source/explicit publication request. Changing plan day keeps the source day independent. Invalid explicit input remains rejected rather than silently normalized into a different day.
- **Older DTOs:** absent `date_bindings` and `daily_channels` remain admitted by the existing optional contract. Their display uses unverified cards with unknown candidate and pending counts; it does not infer zero or successful coverage. The absence of `input_identity_diagnostic` does not invoke its new validator. Malformed optional metadata, when present, fails closed.
- **Async and refresh:** one shared finite 180-second deadline remains. Sequence/view/date/disposal guards discard obsolete responses. The added aborted-signal check prevents a late resolved workspace response from becoming READY after cancellation. Manual generation passes the selected bindings to the existing POST and reads one canonical GET using the selected view and same bindings; neither a retry loop nor a new owner collection is introduced. A failed POST may still lead to the existing readback, visibly labelled with the generation failure.
- **Order and full audit reachability:** the panel places business plan status, daily channels, evidence/research and focus before the close-observation audit. The new semantic `details` defaults closed. Existing complete row loops remain; no producer input slice, mutation or 100/200-row limit was added. The focused 201-row mount case opens the audit and final row's full provenance, and asserts the input object remains unchanged. Existing manual-security inner fold remains another complete expandable layer.
- **US scopes:** stable business row key `美股` is preserved while display adds `美股输入评估／完整度`. The daily US-HK mapping label distinguishes the locally reviewed mapping workflow. VALID_EMPTY text reads the returned reviewed count and explicitly excludes full-market completeness and passing complete US input assessment. Existing raw US projection/assessment and mapping admission are unchanged.
- **Counts and escaping:** `candidate_count`/`pending_count` null or absent remain unknown; zero is only displayed when returned as a count. New owner/gap/hash/diagnostic values are written as text nodes. Diagnostic complete lists are lazily rendered under `details`; no raw payload body or internal component projection is added to the new visible diagnostic. The hostile source-name fixture stays literal text.
- **Plan diagnostic semantics:** the validator binds a nonnull current identity to workspace identity, enforces schema/status/shape, source locator dates/path/hash/mode/slot, unique component IDs and CHANGED/ADDED/REMOVED hash consistency. MATCH requires equal valid identities and no changed components; CHANGED/CANNOT_CONFIRM cannot assert product consumption. Separately guarded date changes can legitimately show CHANGED while the semantic hashes match. Provenance changes are rendered as provenance rather than stale causes; uncertainty visibly remains CANNOT_CONFIRM. Existing plan execution/run readback validation still runs afterwards and was not replaced.
- **Safety/scope:** production diffs add presentation/request-binding/optional-diagnostic logic only. No Stage, HK pool, A/HK separation, rank, price, BUY gate, owner/data producer or Vibe8910 changes were found in reviewed paths. Existing `RESEARCH_ONLY=true` and other three safety flags=false contracts remain enforced by the normal validator.

## Existing-test conflicts

Two reported legacy runtime expectations differ from the current controller-approved date/readback contract:

1. POST response reuse rather than a selected canonical GET.
2. A second implicit binding GET and target/source-day publication default rather than one source-bound GET with owner prior-HK-day default.

These are **recorded behavior-contract conflicts**, not evidence that the whole suite is green. For this review, canonical POST then selected GET and the one bound GET are consistent with the assigned current spec and the target09/publication08 distinction. A genuine wrong-date admission, stale response replacement or failure to read back the selected canonical response would still be a defect; code inspection and focused mount evidence do not show such a defect.

## Evidence checked and testing boundary

Reviewed the complete patch, real surrounding candidate files, frozen preimages, the task brief/request/report, `review/baseline-validation.md`, new synthetic mount/backend-DTO specs and root diagnostic validator spec. Inspected the final focused receipt showing **8 files / 71 tests PASS**, which includes **5 full actual backend router/service DTO → full validator → HTTP parser → production mount cases**. Root-provided diagnostic validator evidence is **23 new PASS plus 19 existing PASS**; focused strict TypeScript **PASS** is recorded. These receipts were not rerun, per the review assignment, and are not reported as reviewer-executed tests.

The baseline support audit retains missing source/fixtures and existing behavior failures. The task report retains **3 failed / 29 passed** runtime results and explicit legacy-contract conflicts. Candidate whole-suite comparison was still root-owned/pending at assignment time. No full-green or exact production-runtime claim is made. Fixture Python is 3.12.14 versus the project's declared >=3.14; offline acceptance is qualified accordingly.

## Declined to judge / acceptance exclusions

- Historical live changed field, unique original live cause, browser-loaded JS SHA and the reported independent 2026-09-30 successful receipt: **CANNOT_CONFIRM** from this frontend review.
- Mac canonical bytes, real owner roots/state, 8873 live API/UI, browser visual repair screenshots, deployment and natural-session receipts: **NOT_RUN**.
- Backend semantic identity implementation correctness, original manifest/payload/receipt history and PIT/finality/market membership closure: outside this frontend review; the actual emitted diagnostic envelopes were checked for interface compatibility only.
- Full-market US coverage, announcement target09/publication08 import completion, missing master entry/volume scale/provider finality and HK target membership gaps are not repaired or certified by UI changes.
- Final complete baseline/candidate suite comparison, final Git commit/remote SHA verification and Mac deployment decisions are root-owned and not certified here.
