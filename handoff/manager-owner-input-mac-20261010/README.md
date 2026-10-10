# Mac deployment and real manager experiment — 2026-10-10

The fused manager repair is deployed on the local V4 API at port 8873. A real owner refresh and two same-binding API readbacks succeeded, but the normal browser request does not present the new plan as current. **API acceptance is partial; UI acceptance fails; complete manager selection remains unconfirmed.**

## Actual result

- `DEPLOYED`: locked publisher completed at 2026-10-10T02:58:15Z; PID 10321 at verification; release `stage_r4_manager_r2_owner_input_r1_fused_r1`.
- Actual source root: `/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1/candidate/stage_r4_manager_r2_owner_input_r1_fused_r1/app`.
- Manifest SHA-256: `fd7f21af0205b9d25a8ab5d33592aff42bf76c0419799b7c1724b94a286aeb86`; app inventory SHA-256: `fe0c88e75a039380a0cc02435bdc5a082064094d235882abfd8e04827da3ff1c`.
- `API_VERIFIED=PARTIAL`: immediate readback verified for one authorized POST and two GETs with exact bindings plan/selection `20261009`, announcement `20261008`: same run `3bc75d1beea24036850b1af0f4d5f395`, product SHA `38eaad4b3d8adfd4738fa0bb4e6ef5ab969414447450e485614f384f48aab991`, owner state `PARTIAL`, zero formal recommendations.
- Actual US mapping: `VALID_EMPTY`, run `feda7f0209c74d7f8e27be3cee3908ef`; the UI says four reviewed relations and zero matches, not whole-market exhaustion.
- Announcement analysis is not imported; HK target-universe authority is missing; oversold has 693 pending rows and 695 gaps. These are not successful zero-selection results.
- `UI_VERIFIED=FAIL`: in-app browser reload and explicit dynamic view show `STALE_INPUTS_CHANGED / MANUAL_REFRESH`, no three-channel summary. Browser request: `GET /api/v4/manager/research/workspace?date=20261009&view=dynamic`. The upper US summary says unevaluated while the lower daily mapping shows `VALID_EMPTY`; large raw observation sections precede the key result sections. See [visual receipt](coordination/UI_VISUAL_INSPECTION_20261010.json).
- Manual retrospective execution on October 10; `NATURAL_VERIFIED=false`. `RESEARCH_ONLY=true`; production, BUY gate and orders remain false.

## Source and validation

Fixed parent commit: `c0fc35c7b39502f49e43c2e75139dad7822091cf`. All 16 deployed manager source blobs already exist in that commit. [Source references](coordination/SOURCE_REFERENCES.json) map exact runtime paths to existing repository paths, Git blobs and SHA-256 values; they are not duplicated here.

The deployed rollback baseline was the newly active Stage R5 release, manifest `a162a878c01b89f6769710f83bc0907467a05bf18d6e5838b760c7c83efe72d6`. Its 1,021-entry app tree exactly matched the reviewed frozen Stage base. Delta from that active release was only 16 manager source paths plus three manager static assets. All nine Stage protected sources were preserved. The canonical workspace was not overwritten.

Independent fused checks passed: clean web build reproducing 11 static files byte-for-byte, Vue TypeScript check, 25 Vitest tests, 19 Python checks and candidate import identities. The Stage-base rebind and execute-entry regressions independently passed. Publication retained the shared lock, actual-base compare-and-swap, rollback and 113 historical comparison pairs. Earlier Mac R1 checks and their known residual matrix failures remain explicit in the accompanying receipts; a partial matrix is not described as a full pass.

Before successful deployment, an adapter read-helper error and a relative receipt-path error failed before mutation. A concurrent Stage release invalidated the earlier Issue32 plan; that stale plan was not used and the actual Stage base was re-frozen. Nonblocking review-receipt path hardening remains backlog.

## Scope of this handoff

This branch contains only new task-local tools, necessary tests and compact acceptance evidence. It excludes generated dist, actual/staged service plists, full release plans, raw market/owner data, response bodies, credentials and environments. Local screenshots are referenced by digest in the visual receipt. Source, independent acceptance, deployment, API, UI and natural-run status are kept separate.

[Compact publication/API receipt](evidence/review/fused_publication_api_handoff_20261010.json) · [Independent fused candidate review](review/deployment/independent_fused_candidate_review_20261010.md) · [Independent publication plan review](review/fused_publication_plan_review.json)


## Independent post-publication result

[Independent runtime/API review](review/deployment/post_publication_runtime_review_20261010.md) confirms live PID/root/plist/manifest and all 1,022 inventory entries. Its later single GET returns `STALE_INPUTS_CHANGED`, `consumed=false`; the saved product remains unchanged. Date bindings, semantic version and cutoff are identical. The input identity changed from saved `4b7da9…` to current `e0f5ed…`; the exact changed source field or volatile identity component remains `CANNOT_CONFIRM`. Date/query mismatch and cutoff advancement are therefore excluded. `DEPLOYED=PASS`, `API_VERIFIED=PARTIAL`, `UI_VERIFIED=FAIL_TARGET`, `BEHAVIOR_VERIFIED=FAIL_TARGET_ACCEPTANCE`. No additional POST or full-suite rerun was performed.
