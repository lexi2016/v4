# Issue #31 writer receipt

Status: `IMPLEMENTED; REVIEW_PENDING` (writer receipt only; no reviewer approval is claimed).

## Frozen changed files

| File | Bytes | SHA-256 | Line endings |
| --- | ---: | --- | --- |
| `issue31/candidate/wechat/scripts/wechat_article_fetch.py` | 49555 | `988d6d10acb427c2ba8624443342c22f248cce08348d3bf0e09aff4477d2b597` | LF |
| `issue31/candidate/wechat/scripts/wechat_yesterday_performance.py` | 88428 | `6723cb4b57e7c95c6bfe4ed3fce4dc61cbcb588e5d633a8be11bb753f49d6445` | CRLF |
| `issue31/candidate/wechat/tests/test_wechat_article_fetch_recovery.py` | 13499 | `cd5fcaaa24b8fa33ba8ee756f70c2b13a45a0e5134e262860405b7b18c5340c4` | LF |
| `issue31/candidate/wechat/tests/test_prior_mentions_performance_appendix.py` | 25364 | `315b78978e0ba8c715d573229a5eeee40c0351cafa6a644430c8288c6ce340df` | CRLF |
| `issue31/candidate/wechat/WORKFLOW_公众号链接固定执行方案.md` | 37176 | `7290617a8bbe4c8d542db96a74da6c8ba0651f5ce4c394b0538ca3105df5b18c` | LF |

Supporting plan: `issue31/IMPLEMENTATION_PLAN.md`, 2111 bytes, SHA-256 `a5724edc9d2f04314b1a903069c089447e7a5bb1f80da6904c4506c29f460812`.

## Test evidence

| Evidence file | Command / phase | Exit | Result |
| --- | --- | ---: | --- |
| `red_tests.log` | Focused fetch recovery + appendix baseline reproduction, before product edits | 1 | 4 failed, 4 passed; failures exposed direct-output / nonzero-exit behavior and uncached failed A/BJ probes. |
| `full_suite_diagnostic_pre_gate_fix.log` | Full candidate WeChat suite after initial appendix change, before restoring per-code R1 behavior | 1 | 5 HK invalid-denominator cases failed; 132 passed; 18 subtests passed. The new top-level probe-state gate was removed because it was stricter than the R1 baseline; validated helpers already return empty row maps on source-binding failure. |
| `green_core_13.log` | `test_wechat_article_fetch_recovery.py` + `test_prior_mentions_performance_appendix.py` | 0 | 13 passed: 7 fetch recovery functions and 6 appendix functions. |
| `green_targeted_regression.log` | Identity/source-handoff, fetch recovery, R1 appendix and review boundary files listed in the log | 0 | 120 passed; 18 subtests passed; one dependency deprecation warning. |
| `green_full_wechat_tests.log` | All `candidate/wechat/tests` | 0 | 137 passed; 18 subtests passed; one dependency deprecation warning. |

The initial red log and pre-fix full-suite failure log are retained as separate evidence. All fixture data uses temporary directories and synthetic article/market inputs; no network, real article, market feed, OCR installation, service operation, or trading action was used.

## Remaining CANNOT_CONFIRM boundaries

- The input snapshots do not contain the active `scripts/wechat_pipeline_runner.py`, external `wechat_article_intake.py` collector, or actual parent-level `AGENTS.md`. A historical runner is not evidence of the active Mac version. Actual Mac default-entrypoint wiring, flags, collector behavior, and the effects of `--html-file` remain `CANNOT_CONFIRM`.
- The adapter has bounded path relocation for known summary, image-manifest, and checkpoint path fields. The test collector is synthetic; the active collector checkpoint schema, additional path-bearing fields, and complete absolute-path behavior remain `CANNOT_CONFIRM`.
- Native macOS Vision OCR was not run. Linux tests call the existing prepare stage with synthetic valid PNGs, but do not establish Mac Vision execution or live runner continuation.
- Explicit saved-HTML permission was tested against the offline collector and attempt receipt. Compatibility with the missing real collector remains `CANNOT_CONFIRM`.
- The frozen test set covers verify-page rejection, recognized OCR interruption, unknown exception, and interruption during image promotion. A standalone empty-`js_content` collector case, a raw-HTML tamper-between-runs case, and interruption exactly after the summary commit but before its promotion receipt are not independently asserted here; treat those exact scenarios as `CANNOT_CONFIRM` pending reviewer findings or a follow-up test.
