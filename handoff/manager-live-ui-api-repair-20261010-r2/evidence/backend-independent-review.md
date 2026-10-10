# Task 1 independent review — final v4 addendum

## Current verdict

**Specification verdict: PASS_SCOPED. Code-quality verdict: PASS_SCOPED. Original P2: RESOLVED in the frozen candidate. No new blocking finding.**

This addendum supersedes the v3 `CHANGES_REQUESTED` disposition for the independently reproduced materialized-catalyst defect. The original finding, v3 source identities, failed probe, and review limitations are preserved below. This is independent acceptance of the scoped offline proposal; `PROPOSAL_ONLY`, real live cause `CANNOT_CONFIRM`, and Mac/live/API/UI/natural-session `NOT_RUN` boundaries remain in force. It does not establish invariance for every historical/auto-view owner state.

### Final identities read back

| Candidate path | Final SHA256 | Re-review scope |
|---|---|---|
| `v4/manager_research/archive_catalyst_inputs.py` | `3a16ba2b996156ff923ce601d247c98778a546bae874850e1603ea7fcb8c5ae3` | New scoped P2 correction; exact preimage `968b26e66cb041adcf503e251c2c710728ce33638627123ff618357398b37b71` |
| `v4/manager_research/workspace.py` | `9a01a023f9c4244ba13a0d23c3f0f36e9e6e90db9d88073e3a4bf94bb7b8fa67` | Byte-unchanged from reviewed v3 |
| `v4/manager_research/workspace_projection.py` | `54e98d1d46c24719906dfef0ae4fe9f11524d7e8cb02c66126877fb15bb54f4c` | Byte-unchanged from reviewed v3 |
| `v4/manager_research/workspace_identity.py` | `bc4e516b98e518190dfa76277598cefc3da7b096610eebd5d3d32d2536acd0c6` | Byte-unchanged from reviewed v3 |
| `apps/web/src/api/managerWorkspace.ts` | `3dd4771366b5aa5e377024a94785c33159b89e396fde80f12f4a6a4cb4e7b7d5` | Byte-unchanged from reviewed v3 |
| `tests/test_manager_semantic_identity_20261010.py` | `bf16a6d5e94cc2d70e92735a6e69da998afc960569bda6d908c3712d4237ae42` | 56 final focused cases, including 23 new catalyst cases |

The additional `archive_catalyst_inputs.py` preimage is fixed-Git support from parent `c0fc35c7b39502f49e43c2e75139dad7822091cf`, rather than an uploaded `current_fused_app` file. Root must retain that provenance distinction and the exact Mac preimage check in the application handoff. This reviewer did not access the Mac or certify its current file bytes.

The final `task-1-report.md`, `task-1-source-sha.json`, `task-1-test-commands.json`, `task-1-verification-summary.json`, and six-fixture summary were inspected after their v4 updates. The report now states the two test boundaries and fixed-Git-only source provenance explicitly. All eight source/test rows in the final backend SHA inventory match actual candidate bytes; the frontend validator's unchanged SHA was checked separately.

### Why the P2 is resolved

The correction is confined to `archive_catalyst_inputs.py:21–43` and its call at `:95–96`:

1. `_read_archive` still performs the real current source read before the new comparison. Exact source validation was not replaced.
2. An exactly equal selected record keeps the original behavior. When it differs, both current and saved bindings must satisfy the existing `_archive_ref` recognition of a complete, VERIFIED V35 binding. Missing, unknown, malformed, or unverified mismatches cannot use the exception.
3. The comparison deep-copies the complete selected records and removes **only `binding.manifest_sha256`**. All other binding values and outer selected-record fields remain in the equality check: source/root/date/slot/mode, payload and receipt paths/SHAs, status, policies, flags, and any additional fields.
4. Only after that comparison succeeds does the code restore the saved capture provenance. Every rebound row must first have exactly `[current_binding]` as its top-level `source_refs`; then that single field receives the prior binding. `source_row`, content, material identity, availability, retrieval time, and other row fields are left untouched.
5. Frozen source selection still uses only the saved date/slot keys. Date/cutoff validation, duplicate/limit checks, `_clock_error`, acquisition-window checks, native identity witness comparison, and the original catalyst owner's full archive-projection/cards/envelope equality checks remain intact. `catalyst_observations.py` is unchanged; its whole-product SHA and equality guards were not relaxed.

This reproduces the sealed catalyst snapshot and its derived provenance after a registry-only update while allowing the direct workspace read to expose the current manifest provenance through its existing source/diagnostic fields. No saved catalyst or plan file is rewritten on GET, and no reader failure is swallowed to force `CURRENT`.

### Focused evidence inspected, without rerunning passed suites

| Evidence | Actual recorded result | Scope |
|---|---|---|
| `task-1-catalyst-red-valid.log` | 4 FAIL / 19 PASS, exit 1 | New 23 cases against the exact pre-correction catalyst source |
| `task-1-catalyst-green.log` | 23 PASS, exit 0 | Same new cases after correction |
| `task-1-red-final-v4.log` | 16 FAIL / 40 PASS, exit 1 | Entire final 56-case file against fixed baseline |
| `task-1-green-final-v4.log` | 56 PASS, exit 0 | Entire final 56-case file against final candidate |
| `task-1-independent-catalyst-green.log` | 1 PASS, exit 0 | Implementer's rerun of the unchanged reviewer-created failing probe |
| `task-1-regressions-final-v4.log` | 16 FAIL / 100 PASS, exit 1 | Same inherited failure names as baseline; no introduced/resolved delta |

The original reviewer failing probe remains byte-identical: `independent-catalyst-probe-runtime.log`, SHA256 `84c2fec47c9ee2e31c381a329a0839b9b9cb42b3409330b6d57219330f05063c`. Its subsequent green log is a separate artifact, SHA256 `b1970b20726a797c1ec766b2535891c51ec0232ce87b98bf2841df3f26f312de`. That green output records `CURRENT → CURRENT`, `consumed=true`, equal outer identity, zero changed components, one provenance difference, equal payload/receipt SHAs, and no GET side effects.

The native-witness negative test is one of the four catalyst RED failures because the old code stopped earlier at `ARCHIVE_CATALYST_SOURCE_CHANGED`; after correction it reaches the still-closed `ARCHIVE_CATALYST_IDENTITY_CHANGED` guard. Its RED therefore does not mean the baseline admitted an invalid native identity.

### Preserve the two test boundaries

- **Real fixed-store owner/router coverage:** `materialized_archive_catalyst` (`tests/...:383`) uses the unchanged actual archive reader, original refresh/read methods, registered routes, and workspace persistence. The fixed schema's missing acquisition clocks remain rejected: `clock_admitted_material_count == 0`, with `ARCHIVE_EXPLICIT_ACQUISITION_TIME_REQUIRED`. It verifies complete rejected-row/snapshot replay, global-only plan continuity, no new-slot enumeration, seven actual source fault controls, ten resealed binding fault controls, and no GET writes. This demonstrates the original reproduced failure and its correction without inventing admissible PIT evidence.
- **Nonempty explicit-clock projection coverage:** `explicit_clock_archive_projection_boundary` (`tests/...:523`) intentionally substitutes only `_read_archive`'s output boundary with invented coherent payload/binding values. The real clock checks, native master/classifier, card projection, and full owner equality then run. Those four cases cover one nonempty card, native witness loss, and availability/retrieval changes outside cutoff. They do **not** certify an extended `ResearchArchiveStore` schema or a naturally acquired live article.

The test code and verification JSON explicitly maintain this distinction. The correction neither adds those clock fields to the production archive schema nor changes any PIT gate.

### Sixth actual DTO — independent consumer check

The new `materialized_catalyst_manifest_only_match.json` response was independently consumed through the actual candidate `validateManagerWorkspace`, with its actual target and date bindings. Node `v24.19.0`: **PASS, exit 0, no mutation**; plan `CURRENT`, consumed, diagnostic `MATCH`, zero changed components and one provenance change. Only this new DTO was checked in this re-review; the previous five were not rerun.

- Fixture SHA256: `0a0fcbdfa6b6b20f4c46553bba30775ccebea6fcc3c1cc484ccb94917fe4f03e`.
- Evidence: `review/independent-catalyst-dto-consumer.json`, SHA256 `6e7ca0207e9d7364eaed1d186c345b75f5af6fc4da6e795cba90d60fcbd3968c`.
- The validator source SHA is recorded in that receipt and matches the final table above.

The final acceptance is limited to the reviewed code paths and actual isolated evidence. The historical/auto-view PIT limitations, Python 3.12 versus project >=3.14 deviation, inherited 16 failures, live root-cause uncertainty, full-app missing dependencies, and root-owned Git/deployment decisions recorded in the original review remain unchanged.

---

# Preserved original v3 review

## Verdict

**Specification verdict: CHANGES_REQUESTED. Code-quality verdict: CHANGES_REQUESTED.**

One **P2** acceptance gap is independently reproduced: with an existing materialized catalyst product, an unrelated global registry update still changes the outer workspace identity and changes saved-plan readback from `CURRENT` to `STALE_INPUTS_CHANGED`. The narrow material normalization works for the newly covered direct-material path, but it runs after the original catalyst owner has rejected its frozen binding.

No additional blocking defect was found in the reviewed semantic/provenance helper, the v3 saved-metadata shape checks, legacy optional-diagnostic compatibility, or the additive TypeScript diagnostic validator. Five actual synthetic backend DTOs were independently accepted by the actual candidate frontend validator without mutation.

This review is deliberately retained as evidence for the **v3 source identities below**. Root has accepted the P2 finding and assigned a correction. It is not a review of that future correction. Candidate status remains `PROPOSAL_ONLY`; no deployment or live acceptance is implied.

## Source and scope

- Task root: `/workspace/scratch/0e089a11ee60/live_ui_api_20261010`.
- Read-only baseline: `work/baseline/app`; reviewed candidate: `work/candidate/app`.
- External fixed Git parent: `c0fc35c7b39502f49e43c2e75139dad7822091cf`; these review roots have no `.git` checkout.
- Canonical project remains `/Users/lexi/Desktop/学习/v4_app`. No Mac, live 8873 service, owner state, or production source roots were accessed.
- Requirements inspected: `review/task-1-brief.md`, `input/package/CHAT_REPAIR_REQUEST.md`, `input/package/evidence/root_cause_report_20261010.md`, and candidate `AGENTS.md`.
- Diff and recorded identities inspected: `review/task-1-review.patch`, `review/task-1-review-source.json`; actual candidate file SHA256 values were read back and matched the v3 identity record.
- The implementer report `review/task-1-report.md` was not yet available while this review was completed. This review therefore relies on actual code, named test logs, the verification JSON, and its independent probes, rather than a report's narrative.

| Reviewed production path | Baseline SHA256 | Candidate SHA256 |
|---|---|---|
| `v4/manager_research/workspace.py` | `7a4875f1ab5ba46ac6c18bdaffe2c103a136734fda276fbee918163332844bb0` | `9a01a023f9c4244ba13a0d23c3f0f36e9e6e90db9d88073e3a4bf94bb7b8fa67` |
| `v4/manager_research/workspace_projection.py` | `027d855613e675e1f569b401b9a8344e40766b88c31e987e791d05a0b3a2f200` | `54e98d1d46c24719906dfef0ae4fe9f11524d7e8cb02c66126877fb15bb54f4c` |
| `v4/manager_research/workspace_identity.py` | New file | `bc4e516b98e518190dfa76277598cefc3da7b096610eebd5d3d32d2536acd0c6` |
| `apps/web/src/api/managerWorkspace.ts` | `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f` | `3dd4771366b5aa5e377024a94785c33159b89e396fde80f12f4a6a4cb4e7b7d5` |

Surrounding code inspected included `ResearchLaneSource`, `existing_materials`, `workspace_discovery`, `issuer_us_relations`, `research_evidence`, `research_attention`, `workspace_read_control`, `workspace_history`, `catalyst_observations`, and `archive_catalyst_inputs`. The original source/receipt validators and the plan persistence/readback/owner-attempt flow were read, not inferred solely from the patch.

## Actionable finding

### P2 — Complete the consumed-artifact boundary before the materialized catalyst owner can invalidate the workspace

**Changed-code location:** `v4/manager_research/workspace.py:706–710`, with the upstream owner read at `workspace.py:677` and the resulting input included at `workspace_projection.py:482–487`.

**Unchanged source of the residual coupling:** `v4/manager_research/archive_catalyst_inputs.py:65–69` and `v4/manager_research/catalyst_observations.py:473–481`.

The new `semantic_materials(...)` call normalizes direct existing materials before discovery and research-attention hashing. However, `_compute_workspace` first calls `service.get_catalyst_observations(date)`. If a saved catalyst product includes `archive_projection`, the original catalyst reader replays `project_archive_catalysts(..., frozen=previous['snapshot'])`. That replay compares the new `selected` binding against the saved binding verbatim. The binding still contains `manifest_sha256`, so a registry-only update triggers `ARCHIVE_CATALYST_SOURCE_CHANGED` before the new material boundary is reached. The workspace then receives a failed catalyst input and its `projection.catalyst` fingerprint changes.

The existing direct-material test creates a workspace plan while the catalyst product remains unmaterialized. It therefore proves that important path, but does not exercise this original-owner branch.

**Independent observed transition:**

1. In the existing temporary synthetic fixture, call the real `service.refresh_catalyst_observations(DATE)`. Its archive snapshot contains one artifact.
2. Save the workspace plan through the real owner and read it through the registered manager GET route: `CURRENT`, consumed.
3. Add only `synthetic-unconsumed/registry-only.json` to the research registry. Assert that the consumed archive's exact payload and receipt SHAs are unchanged and that only its global manifest SHA differs.
4. Read the same workspace GET. It returns `STALE_INPUTS_CHANGED`, `consumed=false`, and a changed outer input identity. Diagnostic component IDs are `outer.workspace_projection` and `projection.catalyst`; it also reports one provenance difference.
5. Snapshot every synthetic owner root around GET: no writes occur.

The test fails its expected `CURRENT` assertion. This is a safe rejection, but it leaves the requested registry-only invariance incomplete. It is **not** evidence that this path caused the historical live mismatch.

**Required correction:** carry the narrow consumed-artifact comparison through the original catalyst snapshot validation, without swallowing its error, bypassing its reader, forcing `CURRENT`, or weakening source root/date/slot/mode, payload/receipt SHA, source content, availability, PIT, owner-attempt, or saved-product guards. Add focused coverage for a materialized catalyst with an unrelated registry update and negative controls for genuine binding/content/receipt changes. Because the correction reaches an additional original-owner file, record its exact input provenance and preimage SHA before any Mac-side application.

Relevant surrounding-source SHA256 values at review time:

- `archive_catalyst_inputs.py`: `968b26e66cb041adcf503e251c2c710728ce33638627123ff618357398b37b71`.
- `catalyst_observations.py`: `9b1b4ecabc635c24580ba85fc293911f635ad056b8bf49a5feaa3adc1db5057f`.

## Verified review conclusions

| Requirement or risk | Review conclusion |
|---|---|
| Registry-only change on the direct-material path | Covered by the real-reader and real owner/GET tests; identity stays equal while provenance differs. P2 above limits the broader claim. |
| Semantic fields named `manifest_sha256` | The helper removes the field only from recognized top-level material `source_refs`; it does not recursively strip `source_row`, `original_source_row`, or arbitrary material content. Negative controls preserve semantic significance. |
| Payload, receipt, manifest-entry, dates, source root/path/mode | The original readers remain intact. Tests retain rejection of unsealed changes and hash changes for altered consumed bindings. |
| Availability | `available_at` remains in semantic material content. The frozen archive schema rejects unsupported added availability fields; projected availability is separately tested. The repair does not fabricate missing acquisition evidence. |
| Outer identity contributors | The existing ordered outer hash inputs are retained. Named components cover workspace projection, research attention, announcement inputs/reviewed analysis/product, US payload, and admitted daily US mapping references. `date_bindings` has a separate fingerprint and its existing equality guard remains. |
| Source-backed stale diagnosis | Material source IDs bind source date/path/receipt path/slot/mode and a hashed source root. Component records contain hashes and source locators, without original raw payloads. Added/removed/changed source cases remain distinct. |
| Saved metadata and migration | The v3 helper checks metadata checksum, schema/contract, workspace input binding, duplicate IDs, digest format, source shape, provenance shape, and source-derived component IDs. A new current workspace cannot reuse a saved workspace missing this metadata. |
| Both-legacy internal DTO compatibility | The existing exact-equality/owner guard is preserved only when both callers lack metadata, and v3 omits the optional diagnostic in that case. This avoids consumed legacy DTOs carrying a contradictory `CANNOT_CONFIRM` diagnostic. |
| Readback and immutable products | The existing saved plan/date/semantic/cutoff/exact-owner-attempt checks remain. Current provenance/diagnostics are a read overlay; GET does not rewrite the sealed saved product. |
| Frontend diagnostic contract | The additive validator rejects unknown schemas/statuses, malformed hashes/dates/paths, duplicate or incoherent component changes, false MATCH, and consumption with changed/uncertain diagnostics. Existing safety and readback validators are still called. |
| Actual producer-consumer compatibility | All five exported synthetic backend transition DTOs passed `validateManagerWorkspace` with their actual date bindings; no DTO was mutated. This was a validator probe, not a browser test. |
| Scope/safety | No reviewed change adds a producer or changes Stage, HK/US pool definitions, BUY, orders, Vibe8910, services, schedules, or authority roots. `RESEARCH_ONLY=true`; the three execution flags remain false. |

## Evidence and execution

Previously executed suites were **not rerun by this reviewer**. Their recorded results were inspected:

- `review/task-1-red-final-v3.log`: baseline **12 failed / 21 passed**, 33 cases, one warning.
- `review/task-1-green-final-v3.log`: candidate **33 passed**, one warning.
- `review/task-1-regressions-baseline.log` and `review/task-1-regressions-final-v3.log`: both **16 failed / 100 passed**. The named failure sets are identical in `review/task-1-verification-summary.json`; the 16 inherited failures remain FAIL, not green.
- `evidence/logs/diagnostic-validator-green.log`: **42 passed**, comprising the root's 23 diagnostic cases plus 19 existing regression cases. Root's reported diagnostic baseline was 16 failed / 7 passed. This review does not count the 42 again as an independent execution.

### Independent materialized-catalyst probe

Scratch-only test: `review/test_independent_catalyst_registry_only.py`.

```bash
PLAN_AUDIT_APP_ROOT=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app \
PYTHONPATH=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app \
PYTHONDONTWRITEBYTECODE=1 \
/workspace/scratch/0e089a11ee60/live_ui_api_20261010/runtime/bin/python -m pytest -q -s \
/workspace/scratch/0e089a11ee60/live_ui_api_20261010/review/test_independent_catalyst_registry_only.py \
--basetemp=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/review/independent-catalyst-probe-tmp \
-p no:cacheprovider
```

- Actual result: **exit 1; 1 failed**, at the expected-CURRENT assertion described above.
- Actual interpreter: Python **3.12.14**, pytest **9.1.1**, FastAPI **0.141.1**, through the task runtime and retained locked dependencies. Project requirement `>=3.14` is **NOT_MET**; this is isolated Linux verification.
- Log: `review/independent-catalyst-probe-runtime.log`.
- One earlier launch using the initial brief's missing `runtime_locked/bin/python` returned **exit 127**. Its error is preserved in `review/independent-catalyst-probe.log`; that is setup failure, not a code-test result. No runtime was edited by this reviewer.
- Test SHA256: `18cbacc52baf137c8c58c1fcbde08302249d9bfa30291de3b96bbaf77ea02722`.
- Actual failing log SHA256: `84c2fec47c9ee2e31c381a329a0839b9b9cb42b3409330b6d57219330f05063c`.

### Independent backend DTO consumption

The candidate `managerWorkspace.ts` was bundled with the existing local esbuild into a scratch CommonJS module. A Node **v24.19.0** script read all five JSON files under `review/backend-ui-fixtures`, called the exported `validateManagerWorkspace(value, value.target_trade_date, value.date_bindings)`, and checked that serialization before and after was identical.

Result: **exit 0; 5 PASS; zero mutations** for `manifest_only_match`, `consumed_content_changed`, `consumed_availability_rejected`, `legacy_missing_components`, and `date_bindings_changed`.

Evidence: `review/independent-backend-dto-consumer.json`, SHA256 `625375923dcec5267fdb8c883b837c63c24f3a14f63fb98b4435f767d42cfe15`. These DTOs are synthetic test products; they are not historical live receipts. No raw fixture products need to be uploaded as review evidence.

## Boundaries and behaviors not accepted by this review

- **Historical live changed component / unique root cause: CANNOT_CONFIRM.** The original whole-manifest bytes and the historical GET body identity remain unclosed. Neither this probe nor the earlier counterfactual identifies the original live change.
- **Live API/UI, browser-loaded JS SHA, Mac integration, deployment, and natural-time acceptance: NOT_RUN / CANNOT_CONFIRM.** No services were started or stopped, and no network, capture/import, business source writes, or publish action was performed.
- **Full `create_app` integration: NOT_RUN.** The fixed snapshot lacks `stage_center.research_read_binding` and another frozen support module; existing import failures are preserved in `evidence/logs/baseline-pytest-task-runtime.log`. The exercised app is the isolated existing manager router/service host, without a Stage substitute.
- **Historical/auto-view provenance invariance: NOT_PROVEN.** `workspace_history.py:330` compares frozen business fields, including full material/source refs, after provenance restoration. The provided V35 archive fixture has null `available_at`/`retrieved_at`, and the legitimate history PIT gate rejects it first. This reviewer did not bypass PIT or promote that downstream static concern to a second reproduced blocker. The current review's positive owner/GET transition evidence is dynamic-view evidence.
- **Legacy source/data/PIT deficiencies remain.** This review does not fill missing announcement imports, certify provider finality or scale, establish target HK authority, convert four reviewed US relationships into full-market coverage, or negate the user's earlier independent receipt report.
- **No Git synchronization verdict.** The reviewer made no commits or pushes. Root owns the explicit-path Git synchronization, remote readback, additional-file provenance, and final correction review.

Only the review report, its isolated synthetic probe, and scratch validation evidence were written by this reviewer. Production sources and frozen baseline files were not edited.
