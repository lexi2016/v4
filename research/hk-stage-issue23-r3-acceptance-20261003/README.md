# Issue23 R3 Mac acceptance

R3 exact patch landed on Mac. Independent Stage A: full-module interface/helper 28/28 and R2 builder CLI 5/5 PASS. Original builder ran once with exactly one runner overlay, exit0. New candidate release_id 20261003-hk-binding-wrapper-r3.

Independent frozen offline Stage B acceptance PASS; REVIEWED/TESTED/BEHAVIOR_VERIFIED PASS within offline wrapper and read-only binding scope; P0/P1/P2 all zero. 914-path inventory: no added/removed paths, only runner and config differ, 912 paths identical to actual active R1. Config changes release_id/shared_data_root only. Candidate cold import, exact delivery-package 10-case wrapper smoke and fresh read-only dual-root binding PASS (100 unique, target20261002/source20260930/signal20260929).

The earlier R2 unexpected historical_markets keyword incompatibility is fixed for default/None requests. Explicit historical market requests remain forwarded and reject before body execution when an old helper lacks support. No helper overlay, other pin refresh, historical collection/selection, or trading change. Failed R2 remains preserved and NOT_ACTIVATED; activeR1/plist unchanged.

Start with reviewer_evidence/issue23_r3_stage_b_reviewer_report.md and machine-readable receipt. Stage A receipts and builder/Writer receipts are under evidence/. canonical/ contains exact landed source/test files; delivery/ holds precise patch and smoke script identities. SHA identities in SOURCE_MANIFEST.json. A superseded reviewer P2 was a scope misread of delivery-package vs candidate-tree script location; corrected by independently executing the exact manifest-bound external package script against candidate --app-root, not by changing candidate content.

R3 candidate remains NOT_ACTIVATED. DEPLOYED=NO, INTEGRATED=NO (inactive candidate); API/UI/actual Stage selection CANNOT_CONFIRM; NATURAL_SLOT_UNVERIFIED. Offline acceptance does not constitute full live Stage recovery. Next phase is the existing controlled publication/rollback process and actual Stage acceptance, without manufacturing historical captures or outcomes.
