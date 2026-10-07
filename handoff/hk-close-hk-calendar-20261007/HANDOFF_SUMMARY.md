# HK Close Calendar source handoff — 2026-10-07

## Scope and identity
This branch is a receipt-bound delta snapshot based on `c776a7e8ad04df71200ef8a294cfa30fdc75816d`. It contains 36 verified source/test files in separate `canonical` (18), `api` (12), and `scheduler` (6) prefixes. Same-path files with different after-SHAs remain isolated by prefix. Dependency manifests and launchers match their respective baselines and are not duplicated. This is **not a standalone runnable package**.

Excluded: `dist`, raw receipts, full manifests/inventories, plist files, local paths, raw responses, market/runtime data, screenshots, logs, and credentials.

## Review and deployment evidence
Canonical writer receipt SHA-256: `78784cf38b6aff390fbfae59aebdcd074e1d7e69b5b4d8477f1d05412c0b96c8`; independent review receipt SHA-256: `46d485131e6d040de83b5bbf780abbe3beaa52a9a0080a37eaeaa61cdb4f2ed0`, verdict `PASS_WITH_NONBLOCKING_P2_COVERAGE_NOTE`. That review does not claim integration, deployment, API/UI readback, or natural-slot verification for the canonical delta. Baseline limitation: no independent round-start source snapshot exists. The canonical receipt records 14/18 before hashes as RECONSTRUCTED_FROM_EDIT, 3 as prefix/prior-receipt matches, and 1 dispatch test absent at round start. Current after hashes match, but change-only scope for those reconstructed paths is CANNOT_CONFIRM.

R2/R9 final independent review receipt SHA-256: `c615f48c04f17ae97d05a71124f5ee961c7f1d42fe38f25e482a285e1211c9b5`; current candidate identity SHA-256: `e6a770f02539b4eaddab510ca425fc8b8231a0670e2d1758c4f017ce4f328de8`. The reviewer was read-only and independently passed 20 isolated wrapper tests. A later root live-closure receipt SHA-256 `24ab924821fb9d15cd2fb6193994baf76b97f0ecd53e0c5854087e279d1bd706` records the successful R2 API / R9 scheduler apply. API manifest SHA-256: `46727f049c8bd490804f0a67779321dd4722971e0a027cff3dd61a32cb75101c`; scheduler manifest SHA-256: `2ab5e59af2a381c40fa6553f019c7aecc76af32b6718c4c29fc25f0ce84f818b`. Operation evidence digests are recorded as API `e76681da7f8325e9a1aaac2acbc0d9577513d69a2462e86d7f36419b3f6e7ba6` and scheduler `4f40d2951b0ca2e164166ea88cfa46ed77b94fcebc69511b76feba19451a755f`. The independent review did not itself apply services; live status comes from the later root closure.

An earlier real bootstrap attempt failed because the domain/target argument was wrong; automatic rollback then encountered an absent service label. Root recovery restored and verified the exact prior baseline (recovery evidence digest `ce4882f457188299c4a8cc07b19a2226df333c61c21cbac58f9260eb710df1a2`), the wrapper was corrected, and the later dual-service apply succeeded. Raw launchctl stdout/stderr is not included or inferred.

## Readback and safety
Root closure records six exact-date API readbacks: `20260911=MODEL_REVIEW_READY`; `20260929=CANNOT_CONFIRM`; `20260930=MODEL_0_2_SOURCE_MISSING` (20 close-top rows, zero model-0.2 and stage rows); `20261001=NON_TRADING_DAY`; `20261002=CANNOT_CONFIRM`; `20270102=CANNOT_CONFIRM`. On selected UI date `20261002`, the actual release badge, HK-open notice, and `16:10` close time were visible; status remained `CANNOT_CONFIRM / CLOSE_REVIEW_ARTIFACT_MISSING`, not a holiday classification.

Final reported R2/R9 layers: implemented PASS; targeted independent tests PASS; reviewed PASS; deployed PASS; API verified PASS; selected-date UI verified PASS; `NATURAL_SLOT_UNVERIFIED`. `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.
