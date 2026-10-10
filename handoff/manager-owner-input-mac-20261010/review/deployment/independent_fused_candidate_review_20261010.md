# Independent fused-candidate review — 2026-10-10

**Verdict:** `REVIEWED=PASS` for the frozen source fusion and candidate artifact. `TESTED=PASS` for the targeted independent rerun below. `BEHAVIOR_VERIFIED=PASS_SYNTHETIC_ONLY`; live selection behavior is `CANNOT_CONFIRM`. No P0, P1, or P2 source-merge finding was confirmed.

The candidate is local-only. Its own acceptance receipt says `READY_FOR_INDEPENDENT_REVIEW` / `LOCAL_CANDIDATE_ONLY`; no service or LaunchAgent change, live API, live UI, owner refresh, or natural run was performed. Deployment, API/UI runtime verification, and natural behavior remain `NOTRUN`.

## Frozen source and protected-path check

I recomputed the Stage R4 app inventory as 1,021 entries, SHA-256 `7a93420049f0558c4efda2feb05cd5831e4efc5a15b92fb2b445eb46a30dafe8`, and the fused pre-build app inventory as 1,022 entries, SHA-256 `2a0a277b9ae6dc3dd833077845228e92d5702df3340fbbaac618d31c2407d58a`. Both match the source receipt. The exact Stage-to-fused source diff is the 16 declared paths; there are no extra or missing source paths. All nine reviewed Stage R4 source files retain their Stage hashes. The Issue32 `preselection_router.py` and `preselection_service.py` remain at both Stage and R2 hashes.

`apps/api/v35_api/app.py` is intentionally retained from Stage R4 at SHA `a51b927e98e23ccdd33a849644abfa544232809aab29c2e7223969cc2308d0b8`; it differs from R2's base app SHA. I verified that this retained app still imports `create_manager_research_router` and mounts both the manager research and workbench routers. This preserves Stage app wiring instead of replacing it with the older R2 app.

The R2/R1 overlap is ordered correctly: Stage `workspace.py` SHA `183e3e…` → R2 SHA `a6225e…` → Owner R1/fused final SHA `7a4875…`. All final source-operation hashes match their intended frozen source; the final candidate inventory is 1,022 entries, SHA `fe0c88e75a039380a0cc02435bdc5a082064094d235882abfd8e04827da3ff1c`.

## Independent tests

I ran the checks against the exact fused candidate without modifying its files; the web build and test harness used copies under the review directory, and existing dependencies were read through a temporary review-owned symlink.

- Independent Vite clean build: 11 output files; all three entrypoints resolve every referenced asset. Rebuilt dist inventory SHA `cfd24a34a7b48323b86cf22236d4b641684fc49289232414b80e7127300788ed` exactly matches candidate dist and the Writer build receipt.
- `vue-tsc --noEmit` on `managerWorkspace.ts` and `dailyChannels.ts`: PASS.
- Manager selection and daily automation Vitest: 25/25 pass across 2 files.
- Fused app/plan/HK authority pytest set: 19/19 pass, 0 skipped/errors.
- Seven import checks loaded `app`, manager router, Stage consumer/binding, and manager workspace/connect-selection/service modules from the fused candidate with matching on-disk SHAs.
- Candidate full inventory was unchanged across the rerun; Vite dependency caches were unchanged.

These are synthetic contract and wiring checks. They do not demonstrate a current real-owner result, complete 2026-10-09 selection, or service/API/UI behavior.

## Remaining gate

The fused acceptance receipt marks the release gate `CANNOT_CONFIRM`: it records a pending Stage publisher historical-result-protection check and says no validator exception was added. The reported 59 historical rows were not independently re-audited in this review. The integration plan also records `PREPARATION_READY_WAITING_STAGE_R4_HANDOFF`; the candidate source receipt binds to a Stage R4 candidate manifest, not a fresh active plist/PID/runtime identity. Therefore this review does not grant deployment readiness. Keep real target behavior and deployment identity `CANNOT_CONFIRM` until the publisher gate and fresh release handoff are supplied, then review the exact deployment plan and post-deploy owner/API/UI readbacks.

The prior full manager matrix is historical pre-fusion evidence and was not repeated; this verdict relies on the focused fused-candidate checks above. No production source or business state was changed.

## Evidence

- Independent rerun receipt SHA-256: `90d304da82ca6a7de26ff8006803ffcbbd506f1fb3cb8d20492c4a803f3b41cc`
- Frozen source fusion receipt SHA-256: `903ed11b57be3bf7d3d3ec6c053086e4a5f1225f887bbb6c9c2e0938dab6084f`
- Fused candidate acceptance receipt SHA-256: `3fbe18f361cccc352ed171ac47d3c2ad712007b0544d58e09402891fb173df7c`
- Final candidate inventory file SHA-256: `f7ddf861579e2812a8ef6d77f50da8598afff3df19c3e1e3410c42157843d67d`
- Writer build receipt SHA-256: `45656c2ed670c8cee1d0f477c7d3b6ac14ad7f223762af86c3ecc9e1829d1455`
- Writer targeted-check receipt SHA-256: `3242c1b94ff92b7200ab126ceee56442ff2a9bfe79f8bd243b4e26d1b647fb85`
