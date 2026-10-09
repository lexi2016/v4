# Independent review — three-channel Mac candidate

**Verdict:** REVIEWED=PASS, TESTED=PASS, BEHAVIOR_VERIFIED=PASS for the frozen synthetic candidate scope only. No actionable P0, P1, or P2 issue was confirmed in the pinned diff.

Candidate: lexi2016/v4 commit 030b3a66f77f3b26aeb784a263429cff36c58d75, assembled at /Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009/candidate/mac_source_v2. I reviewed the six API runtime paths, the frontend API path, and all six test-delta paths against the rollback baseline. The exact three-profile delivery verifier passed on the candidate after-side and on the rollback copy before-side.

The focused behavior review found the announcement capture/readback identity checks, stripped non-empty distinct Reader/Reviewer identities, and run/catalog/handoff/judgment binding represented in code and tests. The US path uses the bounded owner refresh before reading the plan cutoff and continues the independent plan with scoped missing/busy/timeout diagnostics; tests cover same-run consumption and slot idempotency. The HK path retains exact-date missing-versus-invalid diagnostics, one-read master/witness checks, and unknown counts as null with counts_known=false; frontend validation rejects a fabricated READY/known-count result. I found no behavior change to the frozen algorithm or BUY safety boundary.

Independent Mac reruns used Python 3.14.6 / pytest 9.1.1 and Node 24.19.0 / Vitest 4.1.10 with existing dependencies only. Results:

- Core Python regression: 43 passed, one Starlette deprecation warning.
- The modified screen-summary contract test: 5 passed.
- Frontend regressions: 25 passed across two files.
- All three delivery profiles: PASS after-side and PASS against the restored before-side.
- The named compatibility failure reproduced identically on baseline and candidate: test_missing_original_archive_is_not_empty_connect_selection at line 381 expects READY, actual PARTIAL; exit 1 both times. It is preserved and is not a new regression.
- Six native-import receipt entries were independently checked against current __file__ paths and SHA-256 values inside the candidate; no canonical business modules were recorded. The smoke was not re-executed by this Reviewer.
- Full candidate integrity passed: 1,044 regular files; 1,019 unchanged baseline files, 8 changed files, 5 delivery additions, and 16 test-support files match their expected hashes. The three protected Issue32 files retain their expected hashes. Candidate source files remained byte-identical throughout Reviewer test reruns.
- Rollback copy independently matches all 1,027 original baseline file hashes; its only 12 additional files are the declared test-support additions. The three before-side profiles pass.

Evidence logs and SHA-256 values are in reviewer_receipt.json; raw Reviewer outputs are under tmp/reviewer-r1.

CANNOT_CONFIRM: today's three real business inputs and restoration; live integration/service identity; deployment; API/UI reload readback; natural-time behavior; full 174-test suite; and a dynamic announcement body capture. The producer's R3 source identity and fixed body_corpus.json static output contract were confirmed, but no actual body batch was run.

The initial Writer handoff quoted aggregate receipt SHA f43c2c3e...; the main controller confirmed it was an intermediate version and that terminal mac_acceptance_receipt.json is SHA 5d47fdeceb5cd0af5d448c23ee1345b03ef970d26b8fb1cb4cde2e2c77030eda. I independently verified the terminal receipt's candidate and test evidence above.
