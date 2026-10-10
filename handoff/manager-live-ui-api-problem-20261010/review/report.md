# Independent package review — 2026-10-10

**Verdict: REVIEWED=PASS for the frozen package-delivery scope, with one accepted P2 replay limitation.** No business-source change, service/API call, owner run, UI retest, or natural-run acceptance was performed.

The final archive is `ZIP/V4_MANAGER_LIVE_UI_API_PROBLEM_20261010.zip`, SHA-256 `c8e8f42a108d144ab2a8182c516b7c0173f55cde8566d3d630709151303b5da4`, 1,037,157 bytes. It contains 85 files. The source manifest covers 16 fixed source references, 9 deployed UI/API context files, and 32 previous reviewed references. I independently matched all 25 entries with absolute source paths against the current source bytes: 0 missing and 0 SHA mismatches. The fixed source reference is commit `c0fc35c7b39502f49e43c2e75139dad7822091cf`, bound by source-reference manifest SHA `78e0b51888736cb14105d197ce90e0b20b4b420da1c34807e2d1c3cb2409ed8d`.

Package checks passed:

- `python3 package/tools/verify_package.py`: 57 source snapshots, 19 evidence files, 85 package files; ZIP member set and SHA match.
- `python3 package/tests/check_evidence_contract.py`: `REAL_EVIDENCE_CONTRACT=PASS`.
- `python3 -m zipfile -t ZIP/V4_MANAGER_LIVE_UI_API_PROBLEM_20261010.zip`: passed.
- Clean extraction to a temporary directory: both package commands passed. The verifier correctly reported `ZIP_CONSISTENCY=NOT_AVAILABLE` because the original ZIP was not a sibling of the extracted package; it exited 0 after validating the package manifests.

The report and evidence keep the live stale identity’s unique cause as `CANNOT_CONFIRM`, distinguish the three-channel renderer wiring defect from the independent plan-identity issue, and state that browser-loaded bundle identity is unconfirmed. The source snapshots, screenshots, and machine receipts are sufficient to locate the reported code paths and evidence without claiming a repaired or naturally verified behavior.

**P2 accepted limitation — backend counterfactual replay is not portable off the Mac.** `package/evidence/reproduce_global_manifest_identity_coupling.py:22-31` hardcodes the Mac-local saved plan, candidate source, and V3.5 data-root paths; `package/evidence/root_cause_report_20261010.md:41` gives an absolute local Python environment. The corresponding plan/data are excluded under the frozen no-raw-state boundary, so `BACKEND_REAL_INPUT_REPLAY_OFF_MAC=NOT_RUN/UNAVAILABLE`. The package retains the independent counterfactual receipt and source evidence, while the unique historical/live cause remains `CANNOT_CONFIRM`. This limitation is non-blocking for the frozen `reproduce/locate` package scope; no synthetic historical fixture was added.

No P0 or P1 finding. Package-level verification is complete; candidate business behavior remains `CANNOT_CONFIRM`, focused frontend regression tests are `NOT_RUN`, and API/UI/natural behavior was not re-exercised.
