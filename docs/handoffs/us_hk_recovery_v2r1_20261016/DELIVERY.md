# Complete US-HK recovery v2r1 delivery

The complete user-supplied package is integrated into the existing V4 mapping catalog on port 8873. The live API, independently verified runtime identity, and reloaded rendered UI passed.

- All 1,003 original relations are processed: 757 closed for research scope, 25 closed as excluded, and 221 open. The combined 782 closures include exclusions and do not establish 782 valid or active mappings.
- The snapshot contains 667 stocks: 649 with original relations and 18 without. Original fields are unchanged. The prior 700-record history remains separate; its research-use statuses are not translated into v2r1 closure statuses.
- Input: 508,906,833 bytes; SHA256 48f1124c10ed3440c22910a9125038748c08d673fc3ec543635cc9aae0b344d4. All 3,637 manifest-listed members passed size, SHA, and CRC checks.

Source root: /Users/lexi/Desktop/学习/v4_app.
Active release: us-hk-recovery-v2r1-20261016-r2. Independent readback found PID 52858 as the sole listener on 8873, with the matching release cwd.

Release manifest SHA256: ae2ca8cee0380217b8c09a3dc3baed5cc88f27c82b02d4cd68668b15d79c5359

Versioned config SHA256: 589eaa058b9abd9cef59ab71ef2c3f4c3c998bae18dd26777134bf0fa22ef86e

Active plist SHA256: 001b0b9dc70f041818d84b9c7ed1065df5ff856abeeccf888d0323df9eca5958

New derived overlay SHA256: 3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c

Original catalog SHA256: 3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671

Prior 700 overlay SHA256: d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69

IMPLEMENTED / TESTED / REVIEWED / INTEGRATED / DEPLOYED / API_VERIFIED / UI_VERIFIED / BEHAVIOR_VERIFIED: PASS within this static catalog engineering scope. An independent reviewer reran 17 backend tests and one frontend test; rollback repair and R2 review reran three targeted failure-path tests. Candidate and live verifiers confirmed the six-path delta, 1,211 preserved entries, exact-RID FULL queries, history separation, safety flags, and served JavaScript identity. Isolated build and targeted Vue typecheck passed. Repository-wide typecheck retains unrelated existing errors, documented in the source receipt.

The runtime was rebased onto the latest Futu industry R2 release, preserving parallel work. Initial runtime review found a rollback exception that could skip original-plist restoration; the bounded helper repair passed independent review. The initial FAIL and repair evidence are retained. Real rollback was not triggered and is not claimed as live-tested.

Remaining gaps: 227 historical attachment-path occurrences across 218 paths; a separate restored-740 scope has 404 path/SHA pairs and 388 hashes, which must not be added to the first scope. There are 62 unattempted A-table URLs. Independent fact acceptance is 0; semantic validity is CANNOT_CONFIRM; prediction is UNTESTED; historical PIT is NOT_VALIDATED; event/data tests are NOT_RUN; available_at is absent. Natural-slot acceptance is not applicable to this static catalog delivery. Saved plans and trading eligibility are unchanged.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.

Private branch: codex/us-hk-recovery-v2r1-20261016, based on 6c53b402ebf3eafa7df3e3511d84e00cf7bc9cd8. Synchronization includes necessary patches, builders, tests, and compact receipts. Raw archives, bulk data, dist, credentials, runtime plans, and screenshots are excluded. Remote patches are not merged or remotely deployed. See GITHUB_SYNC_RECEIPT.json for fixed refs and exact file readback.
