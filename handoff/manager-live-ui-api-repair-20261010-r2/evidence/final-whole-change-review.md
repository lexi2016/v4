# Final independent whole-change review — Manager live UI/API repair

## Verdict

**APPROVE_SCOPED — specification PASS_SCOPED; code quality APPROVE_SCOPED.** No open introduced production defect was found in the final nine-file proposal. This approval covers the reviewed fixed source exports and the observed offline tests. Candidate status remains **PROPOSAL_ONLY**. Production readiness, complete application integration, real Mac API/UI behavior and natural-session behavior are not established.

**The full backend, full frontend, whole-app typecheck and complete build remain FAIL.** Their failures are part of this verdict. Passing targeted tests does not waive those gates. The one handoff-checker P3 found during this review was corrected and the actual correction was independently reread; it is outside the production patch.

This reviewer read the user request and problem report, workspace/app AGENTS, implementation plan, the complete production patch, the actual before/after sources and relevant original owners, validators, callers and tests. The two earlier independent task reviews were supporting evidence; this assessment did not rely solely on their verdicts. The referenced Mac parent AGENTS files are absent in this environment. No Mac source, live owner, network endpoint, Git operation, deployment or service operation was accessed or performed.

## Source identity and review boundary

- Fixed repository baseline: `lexi2016/v4@c0fc35c7b39502f49e43c2e75139dad7822091cf`, tree `21e0e3ae3cd9434ae95400b4ed2abbd0c16ff1bd`.
- Canonical project remains `/Users/lexi/Desktop/学习/v4_app`; the actual tested candidate is `/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app`, with the paired frozen `work/baseline/app` export.
- Final production patch SHA256: `d078eb55dd07d07456df71740f8f5cf434defd33586acfb124704cff6de4b111`.
- Source-manifest SHA256: `af84a5eb4093f1ad25657382b5ecf631f8261c7aee5b3c7c2ea3d9089c9b37b6`.
- Final handoff: `/workspace/scratch/0e089a11ee60/v4/handoff/manager-live-ui-api-repair-20261010-r2`; branch `chat/manager-live-ui-api-repair-20261010-r2`.
- The nine candidate source hashes match the manifest, complete handoff `after/` bytes and actual test roots. The baseline hashes and four new regression-file hashes also match. An independent paired code/artifact inventory found only these nine production differences; paired test bytes are identical.

Root reported that the originally planned R1 branch already exists at `8c8e35d9d53431c9082dec49f4976e363c275765`; the separate R1 delivery is preserved and excluded from this review. The R2 rename changes handoff/branch metadata only: the fixed baseline, all nine production hashes and patch remain identical. This reviewer performed no Git operation and did not integrate that parallel candidate. Already executed R1-path command receipts retain their actual historical paths.

Six replacement preimages are uploaded current-fused sources. `workspace_projection.py` is an uploaded previous-reference/fixed-Git byte match to the reported fused SHA, not one of the 25 uploaded current-fused files. `archive_catalyst_inputs.py` has only a fixed-Git preimage; its deployed Mac SHA remains **CANNOT_CONFIRM** and must be verified before application. `workspace_identity.py` is new. The handoff states these distinctions correctly.

| Production path | Baseline SHA256 | Final candidate SHA256 |
|---|---|---|
| `v4/manager_research/workspace_projection.py` | `027d855613e675e1f569b401b9a8344e40766b88c31e987e791d05a0b3a2f200` | `54e98d1d46c24719906dfef0ae4fe9f11524d7e8cb02c66126877fb15bb54f4c` |
| `v4/manager_research/workspace.py` | `7a4875f1ab5ba46ac6c18bdaffe2c103a136734fda276fbee918163332844bb0` | `9a01a023f9c4244ba13a0d23c3f0f36e9e6e90db9d88073e3a4bf94bb7b8fa67` |
| `v4/manager_research/workspace_identity.py` | `ABSENT` | `bc4e516b98e518190dfa76277598cefc3da7b096610eebd5d3d32d2536acd0c6` |
| `v4/manager_research/archive_catalyst_inputs.py` | `968b26e66cb041adcf503e251c2c710728ce33638627123ff618357398b37b71` | `3a16ba2b996156ff923ce601d247c98778a546bae874850e1603ea7fcb8c5ae3` |
| `apps/web/src/api/managerWorkspace.ts` | `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f` | `3dd4771366b5aa5e377024a94785c33159b89e396fde80f12f4a6a4cb4e7b7d5` |
| `apps/web/src/manager-selection/catalystObservationPanel.ts` | `6650b7948cdfd7fc7eee81dbe9e47d7b86e9aa64ac476e27a72f726c35749355` | `dc01e30151193e4e22966ba1621770b7e9c907b215acbd987da3244c7ba7011a` |
| `apps/web/src/manager-selection/businessStatus.ts` | `36228506f199f26dc59c7919634e4c347171d156ec89b3d6b2359c764ed45d90` | `f55b62da1af832386182752912f908bd387bc2b53f0351e56b7350267e83e9c0` |
| `apps/web/src/manager-selection/researchAttention.ts` | `3ec804fcb248eb50793eff6f237c7e211d75c2e60e138400d4a55f74a57be698` | `f250918be48647c0f3c1028e48ce4fa943922833797594dd67f95ebf08625baa` |
| `apps/web/src/manager-selection/dailyChannels.ts` | `c60254b69de369c8b50ef0ffa14dd49c802a3ae56ac4266dd9fe5f39ea40fecc` | `b7ad877a63d688709a3bb47f832f84fbaf7856ebb4c3888aa19beae8c7da529c` |

`research_lane_source.py`, `existing_materials.py`, `catalyst_observations.py`, the source schema, Connect/Stage gates, history/PIT code and memo implementation remain unchanged. No second source producer, data layer or user panel was added. No A/HK pool or BUY decision rule changed in the reviewed diff; the original four research-safety flags remain enforced.

## Backend assessment

### Consumed inputs and provenance remain distinct

`workspace_identity.py:26–56` recognizes the original verified V35 archive binding shape and removes only its top-level `manifest_sha256` at a material's `source_refs` boundary. Source/root/date/slot/mode, payload and receipt paths and SHAs, flags, additional binding fields, availability and semantic material content remain part of the input. Unknown/unverified bindings do not receive the exception. The helper never recursively deletes a same-named key from source content.

The original `_read_archive` still uses exact owner-store reads and verifies the payload digest against the artifact binding before projection (`existing_materials.py:98–116`). The original manifest/receipt/schema validation is unchanged. Real unsealed payload, receipt, manifest-entry, date/path/root or availability faults therefore remain identity changes or validation failures. They cannot be repaired by reusing a saved identity.

Normalization occurs before discovery/relation/research-attention hashes, followed by the existing workspace and Connect processing. `workspace_projection.py:482–510` introduces a versioned identity contract. `workspace.py:890–918` records the actual outer identity extensions and reseals diagnostics after them. Original provenance is restored only in the returned/copied DTO; source rows are preserved. Small source locators and hashes provide differences without adding raw material bodies to the new diagnostic. The UI correctly labels `source_root_sha256` as a path-string fingerprint.

### The materialized catalyst correction retains the original full guards

`archive_catalyst_inputs.py:21–43,95–96` compares the entire verified selected-source record except the top-level binding's manifest SHA. It then rebinds only rows whose current top-level refs are exactly `[current_binding]` to the original frozen provenance. All other binding/record fields must remain equal. New source slots are not enumerated during frozen replay.

The existing date/cutoff, clock/acquisition, native-identity witness and complete projection/card/envelope checks still execute. In particular, unchanged `catalyst_observations.py:473–481` still compares the complete reconstructed archive projection against the saved one. This is a narrow provenance replay exception, not a relaxation of full-product or PIT equality.

The real fixed-reader materialized-catalyst fixture binds one artifact and retains zero clock-admitted materials because its acquisition clocks are unavailable. Nonempty-card tests explicitly substitute the reader-output projection boundary with synthetic coherent clock-bearing rows; they do not establish that the fixed owner schema or a real PIT source supports those fields. The handoff retains that distinction.

### Metadata cannot overrule the saved-plan guard

`workspace_identity.py:131–221` verifies component shapes, source locators, uniqueness, metadata checksums and their binding to the workspace identity. Missing/invalid metadata on a new/old pair yields `CANNOT_CONFIRM`; a new saved plan must have valid matching semantic components to be reused. Both legacy DTOs without metadata retain the old exact-identity/owner guard and omit optional diagnostics.

`workspace.py:1033–1103` still independently requires same input identity, semantic version, date bindings, valid cutoff and verified owner attempt. The diagnostic is an additional condition, not an alternative authorization. The scheduled reuse branch adds the same component check at `:1196–1206`. GET overlays remain copies; saved run/product bytes are not rewritten. Tests cover legacy migration via a subsequent legitimate owner refresh, source changes, invalid component shapes, date drift and provenance-only matches.

An AST assignment scan plus caller inspection across the available production export found no writer that changes the final workspace identity after its component metadata is sealed. Connect gating changes the projection at `connect_selection.py:216` before the final outer reseal. `service.py` identity updates inspected are separate Stage research-job products/observations; channel/announcement/attempt identities are likewise separate contracts. This conclusion does not certify unavailable Mac code.

## Frontend and request-chain assessment

The existing `mountCatalystObservations` now passes `value.daily_channels` and `value.date_bindings` to `renderDailyChannels` from the same validated workspace response (`catalystObservationPanel.ts:470–477`). It does not assemble channels from different API responses. Existing workspace, owner/run, source, security and daily-channel validators are preserved. The new diagnostic validator is additive and cannot accept consumption for CHANGED or CANNOT_CONFIRM diagnostics; hostile strings render as text.

The request uses independent selection/source and plan dates. Explicit `announcement_date` takes precedence over `publication_date`; with neither override, the existing owner computes the prior-HK-day publication default. Returned dates must match the selected request. A plan-date change preserves the Stage/source date. Manual generation uses the existing POST, then one canonical GET for the selected view and the same bindings (`:631–657`). Existing sequence/view/date/disposal checks and the explicit aborted-signal check prevent an obsolete or cancelled result from becoming the current page. No retry loop or collection trigger is added by the GET.

Plan status, daily channels and research attention precede the original close-observation audit. The new outer `details` defaults closed, while the complete original row loops remain available. The 201-row mount case opens both the audit and last-row provenance and checks unchanged input serialization. No producer input or preselection collection is sliced to achieve the layout.

The upper US label states input assessment/completeness. The lower daily mapping label states the reviewed US-HK relation scope and uses its returned reviewed count. The four-relation VALID_EMPTY case expressly excludes full-market emptiness and complete US-input acceptance. Null/unknown channel counts remain unknown, including legacy DTOs without the optional channel contract.

The six cross-language cases consume unchanged actual registered-router/service DTOs through the real validator, request parser and production child-panel mount. Those cases are synthetic offline integration evidence. They do not establish complete `ManagerSelectionView` acceptance, actual-browser visual correctness or historical/auto-view behavior.

## Final recorded verification

The separate final validation agent executed the paired full commands. This reviewer independently read the raw JUnit/Vitest results, command receipts, actual failure logs, source hashes and final report. Full runs were not duplicated. Exact argv, environment, durations, exit codes, complete failure identities and hashes are in `evidence/final-validation.json` and the command receipts.

| Gate | Baseline | Candidate | Review disposition |
|---|---:|---:|---|
| Full pytest with collection continuation | 302 FAIL / 1241 PASS / 20 SKIP / 33 ERROR | 288 FAIL / 1255 PASS / 20 SKIP / 33 ERROR | FAIL retained; 8 collection + 25 setup errors each |
| New backend file | 16 FAIL / 40 PASS | 56 PASS | Focused proposal evidence |
| Full frontend | 60 FAIL / 332 PASS / 1 SKIP | 20 FAIL / 372 PASS / 1 SKIP | FAIL retained; same 4 suite-load failures |
| New frontend files | 34 FAIL / 10 PASS | 44 PASS | 23 diagnostic + 15 mount + 6 actual DTO cases, all executed |
| Original Issue8R2 guards | 76 PASS | 76 PASS | Original fixed bytes; no assertion changes |
| Whole-app typecheck | FAIL / exit 2 | FAIL / exit 2 | Same 3 errors |
| Whole-app build | FAIL / exit 1 | FAIL / exit 1 | Same missing `daily-research-command/index.html` |
| Changed TypeScript/specs strict check | NOT_RUN | PASS / exit 0 | Focused only |
| Independent bound late-input probe | 1 PASS | 1 PASS | Reviewer-executed sequential control described below |

The original Issue8R2 spec SHA is `3b8e004f31135674d63c1affd25cc41d759bfd10187a1dfc318f64c53636f873`. The candidate full-parent integration still has five FAIL cases. Missing `ResearchView.vue`, missing entry/fixture/support files, old behavior assertions and all other retained failure identities prevent a full-project or deployment-ready conclusion.

### Candidate-only old-test failures were investigated, not hidden

**Legacy late-input fixture.** `tests/test_manager_daily_automation_20261008.py:367–370` rewrites only the final `value['input_identity']`. New metadata remains sealed to the original identity, so the candidate rejects its readback with `WORKSPACE_PLAN_SAVE_READBACK_FAILED`. The old test remains FAIL in both the full candidate run and the targeted candidate rerun. It was not edited.

To distinguish this contract conflict from a real late-input regression, this reviewer created `test_final_review_bound_late_input.py` (SHA `48588485b18da6237feed3f4f26f3695dcc782f606f7b32a13040b2971bf2566`) and ran it sequentially on both source roots. It uses one synthetic archive through the unchanged source reader, changes/reseals actual synthetic title/payload/receipt bytes, and invokes the original same-day catch-up path without patching any workspace identity or metadata. Both runs pass: a new MANUAL_REFRESH/LATE_CATCHUP PARTIAL plan is produced, its readback is CURRENT/consumed, and the old preopen product bytes are preserved. Candidate components match the final identity. This proves that tested material/plan path, not nonempty catalyst, complete PIT, real dispatch admission or a live owner.

Its exact commands, environments, timings and log SHA are preserved in `whole-review-bound-late-input.json`; the handoff carries the unchanged probe and compact logs under `independent_checks/`.

**Short memo TTL.** The candidate full run failed `test_projection_memo_capacity_bytes_ttl_and_exceptions`; its 15ms real-clock TTL expired an expected one-entry cache to zero. The implementation is byte-identical across the pair. The one sequential paired rerun passes on both roots. This supports a timing-sensitive classification, while the original full-run FAIL and 288 count remain intact.

**POST-preview assertion.** The old frontend test requiring reuse of a successful POST response newly fails because the approved behavior now performs the selected canonical GET. The dedicated actual-mount selected-GET test passes. The old test remains a recorded contract-difference FAIL. The older second implicit binding-GET assertion is a shared FAIL, not a newly introduced failure. Seven other unmodified daily-channel tests now pass; nineteen old frontend failure identities remain shared.

## Resolved handoff-checker P3

The initial read-only checker treated `not path.exists()` as proof that a new-file path was absent. A dangling symlink pointing inside the target root makes `exists()` false despite an existing filesystem entry, so `--target-state before` could incorrectly pass that path.

Root changed both expected-absent checks at `tools/verify_handoff.py:61,76` to consider `path.is_symlink()` as well. This reviewer reread the actual fixed bytes, SHA `b590d9cd015eaa7419ff838c3d3aebd359856d6a0c0e9e530d03e39cdbf567b2`, and records the code finding as resolved. The root-owned `evidence/package-tool-verification.json` was then independently inspected: exact nine-path before/after checks pass; isolated patch application reproduces all nine after hashes; the within-root dangling-helper negative case returns exit 1 with `TARGET_SOURCE_MISMATCH`. `evidence/config-parity.json` also records matching effective Vue test configuration and exit 0. These checks were executed by root in temporary roots, not by this reviewer. Their recorded R1 paths are pre-rename execution evidence; final R2 package inventory/remote readback remains a separate root step. No production patch file changed for this correction.

## Remaining limits and acceptance disposition

- Actual runtime is Linux Python 3.12.14 and Node 24.19.0. All 31 locked Python third-party versions match, but the declared Python >=3.14 floor is **NOT_MET**. Mac/Python 3.14 validation is **NOT_RUN**.
- Full `create_app`, complete parent UI and production build acceptance remain unestablished. Child mount and isolated registered-router tests do not replace those gates.
- Historical/auto-view provenance invariance is **NOT_PROVEN**. Existing history full-business/PIT checks remain active; the unavailable-clock fixture is rejected before a downstream historical invariance claim can be made. This review does not bypass or waive that gate.
- The original live mismatch's unique cause and changed field remain **CANNOT_CONFIRM**. The code repairs a demonstrated over-broad contributor. Missing old manifest bytes and the historical GET body prevent attribution of that exact run; new component diagnostics cannot retroactively supply them.
- The reported deployment release/PID is input evidence, not this container's running identity. The added archive file's deployed preimage and browser-loaded bundle SHA remain **CANNOT_CONFIRM**. No deployment or live API/UI/browser acceptance was performed.
- Target09/publication08 announcement import, HK target membership authority, exact08 security-master evidence, six-session volume scale/finality and full-market US coverage gaps remain unchanged. The known panel must not be described as missing; the user's Sep30 successful-receipt report must not be negated. No data was backfilled or owner source expanded.
- A/HK separation, complete inputs, BUY safety, Stage and Vibe8910 remain outside the change. Natural-session acceptance is **NOT_RUN**. Git synchronization/remote readback remains root-owned and is not certified by this reviewer.

The final README and reproduction guidance accurately separate these scopes. This review approves the tested offline code proposal with the stated limitations; it does not approve deployment or treat the retained full-project failures as passes.
