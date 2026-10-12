# Issue 38 implementation / verification matrix — 2026-10-12

| Requirement | Evidence / state |
|---|---|
| Full original catalog row accounting | `audit_catalog`, including duplicate conflict/quarantine and body gaps. Offline synthetic PASS. Exact 23-row real corpus not in package => REAL_DATA_NOT_RUN. |
| Routine vs major/mixed routing | Strict communication template with full-body numeric/material exception veto; unknown always model route. Offline PASS, conservative recall; quantitative REAL_RECALL_NOT_RUN. |
| Qwen3.8 genuine model identity | Live local PID+ps+port listener+revision+config+weight SHA attestation required. Mac/model absent; CANNOT_CONFIRM. |
| Quote, subject/relationship, number/unit, event state | `verify_facts` source spans, SHA and negative controls including independent third party vs associate and outstanding vs completed. Offline PASS, independent semantic accuracy NOT_RUN. |
| Cross-process cache/singleflight | `flock`, atomic `os.replace`, canonical key of issuer/article/body/source/parser/rules/prompt/schema/verified model. Repeated concurrent synthetic calls one model invocation; body-only change invalidates one. 14/14 offline tests PASS. |
| Usage | Every attempted call (even failure) logs provider usage + elapsed; missing total NOT_REPORTED, no double add. Synthetic verification; ACTUAL_QWEN_TOKEN_USAGE_NOT_REPORTED. |
| Existing owner constraints | Explicit output NOT_IMPORTED / quote-checked review required. Original independent `reviewer_conclusion=PASS` gate unchanged. Full owner extension for `SKIPPED_ROUTINE` not implemented => OWNER_CONTRACT_BLOCKED. |
| Scheduler | Opt-in patch to ORIGINAL R6 daily capture command; original heartbeat is currently `service.refresh_announcements`, not proven to call daily body capture. NATURAL_SLOT_UNVERIFIED. No second timer. |
| Frozen dates | CLI requires original capture receipt, exact target/publication and SHA; real run `6557712...` not attached. DATE_IDENTITY_OFFLINE_TESTED, REAL_DATE_READBACK_NOT_RUN. |
| Security | No cloud fallback/proxy/redirect; no trade actions; safety flags preserved. OFFLINE_TESTED. |
| Mac/8873 deployment | NOT_RUN; no live files modified. |

## Critical acceptance before merge

1. On Mac verify R6 exact SHA, apply patch to an isolated copy, run original full regression suite and independent review; the package is only a source overlay.
2. Bind and confirm Qwen PID/endpoint/weight revision. Freeze independent 23-row labels and recall threshold **before** model calls. Capture real provider usage (including failures).
3. Run exact target `20261012` / publication `2026-10-11`, SHA-bound to frozen catalog and 21 good / 2 failed body rows. Check all 23 route rows and reject any accidental `pub09` consumption.
4. Implement and verify explicit script judgment within existing full semantic product and independent reviewer, then owner import/readback/workspace consumption, without changing BUY/PIT/source gates. Do not fabricate success receipts.
5. Prove existing scheduler/heartbeat naturally reaches the exact catalog-and-body capture + triage + owner flow; otherwise retain `NATURAL_SLOT_UNVERIFIED`.

These gates are NOT waived by a passing unit test, a successful GitHub upload or an HTTP 200.
