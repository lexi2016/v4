# Issue #31 writer receipt

Status: `IMPLEMENTED; FINAL_REVIEW=PASS_OFFLINE_SCOPE`. The earlier freeze-time `REVIEW_PENDING` status is superseded by the independent final review. This writer receipt records implementation/evidence; the reviewer decision is recorded in `issue31/reviewer_evidence/FINAL_REVIEW.md` and `FINAL_REVIEW.json`. Active Mac/runtime behavior remains `CANNOT_CONFIRM`.

## Candidate changes

Exactly five product/test/workflow files are changed in `candidate/`:

| File | Bytes | SHA-256 | Line endings |
| --- | ---: | --- | --- |
| `issue31/candidate/wechat/scripts/wechat_article_fetch.py` | 58,707 | `5d648dac0b712a05be2345d1fe73020d3e99520b8256b003c29120c232dedb17` | LF |
| `issue31/candidate/wechat/scripts/wechat_yesterday_performance.py` | 89,787 | `840908dc4350d91abd7b74e94ec4993954ba32edca6bcc7eb8eac646824d3f5c` | CRLF |
| `issue31/candidate/wechat/tests/test_wechat_article_fetch_recovery.py` | 31,535 | `3d5a55f32c62a1ea250f1bdfef3b41584abcccbb06199000357483acdde2e124` | LF |
| `issue31/candidate/wechat/tests/test_prior_mentions_performance_appendix.py` | 26,675 | `969e5f05b2ecdc8e65d8de2255336b3a7f8ed275095640da755bac1168609588` | CRLF |
| `issue31/candidate/wechat/WORKFLOW_公众号链接固定执行方案.md` | 37,675 | `6737f1b37f1bc6f7df90b654296b5f46fe3ee8ac8be06421ee6fbbc342ff592f` | LF |

Supporting plan: `issue31/IMPLEMENTATION_PLAN.md`, 2,111 bytes, SHA-256 `a5724edc9d2f04314b1a903069c089447e7a5bb1f80da6904c4506c29f460812`.

## What changed

The fetch adapter now validates the actual `js_content` body from the HTML using the shared parser. A text-bearing body is accepted; an image-only body is accepted only when its ordered body image URLs match the image manifest. HTTP failures, verification pages, empty bodies, malformed summaries, and unverified artifact sets remain in the isolated attempt directory. Explicit `--html-file` permission and its byte hash are written to the attempt-start event and bound to the promotion receipt.

Source reuse checks the raw HTML SHA, immutable promotion receipt, requested identity, and a stable image-source projection. The projection omits only prepare-stage fields that the existing OCR preparation step legitimately changes. It therefore permits a real `wechat_prepare_ocr.main()` pass to update image metadata while rejecting a changed image URL. A summary's `OCR_OK` label alone cannot report the package stage: the adapter lazily reuses the existing handoff `_identity_from_intake`, `_manifest_rows`, and `_ocr_records` checks for image bytes/order, result SHA/order, complete nonempty text, and slice provenance.

Publication now writes and fsyncs a uniquely named temporary file in the attempt directory, then uses an atomic create-only hard link to expose the complete bytes at the run path. It does not truncate or replace an existing target. Recovery removes only adapter-owned publication temp files from that same attempt before rolling it forward. The merged recovery tests use a child process that pauses after writing half of a real temporary PNG, kill that process, confirm the final image path never exposed those partial bytes, and verify the same attempt resumes without calling the collector again. CLI URL/output aliases, abbreviations, and duplicate protected options are rejected before the collector can receive them.

The R1 appendix retains readable A/BJ and HK receipt facts when a later panel binding check fails, while the per-market price maps remain empty. Failed A/BJ/HK probes are cached once per build. The synthetic 108-listing case retains 81 A + 3 BJ + 24 HK rows as `CANNOT_CONFIRM`; it reports the A/BJ `PARTIAL` receipt facts (`5137/5800`, coverage `0.8856896551724138`, `row_count=5261`, `REBUILD_REQUIRED`) as panel coverage facts, not a 108-code match rate. A current HK receipt's status, path, SHA, and row count survive current-panel SHA failure; no HK price is released. Markdown and JSON assertions also ensure that zero valid observations are not described as 0% returns. Existing per-code denominator checks remain in force.

The default-process paragraph in workflow section 0 now identifies the pipeline runner as the daily unified entry, requires an active-Mac argv check for `--skip-ocr`, documents `prepare_ocr`/`ocr_full`/validated `package` progression, and keeps the active Mac runner, external collector, and native OCR behavior as separate verification boundaries. Only this documentation paragraph changed after the final code test logs; no product source or test changed afterward.

## Verification evidence

All tests used temporary directories and synthetic inputs. No network, real article, market feed, Drive, macOS Vision OCR, service operation, deployment, or trade action was used. The OCR-ready positive case creates synthetic result records and validates them with the existing handoff consumer; it does not claim Vision OCR ran.

| Evidence | Command / phase | Exit | Result |
| --- | --- | ---: | --- |
| `red_tests.log` | Initial focused fetch/appendix red reproduction before implementation | 1 | 4 failed, 4 passed; exposed the original direct-output/nonzero-exit and uncached failed-probe defects. |
| `full_suite_failed_5_r1_gate.log` | Full candidate WeChat suite after an over-broad R1 probe-state gate | 1 | 5 HK denominator cases failed; 132 passed and 18 subtests passed. The top-level binding gate was removed because the validated helpers already returned empty maps on a failed binding. |
| `round2_fetch_red.log` | Writer-owned reproduction of six independent fetch counterexamples before the second-round fetch fixes | 1 | 6 failed. The temporary third test file used for red reproduction was removed; its six checks are merged into the existing recovery test file. |
| `reviewer_evidence/fetch_sigkill_probe.log` | Superseded early child-process harness | 1 | `NOT_BASIS_FOR_FINDING`: the harness replaced `_write_bytes_create_only` and wrote the destination itself, bypassing the helper. Retained as audit history only; see the superseded artifact entry in `FINAL_REVIEW.json`. |
| `reviewer_evidence/fetch_sigkill_real_io_old_baseline.log` | Corrected actual-helper SIGKILL probe against immutable baseline fetch SHA `068fb848…` | 1 | Expected baseline failure reproduced: the real helper wrote and fsynced 34 of 68 bytes at the public image path before SIGKILL; retry refused that partial file. Probe source SHA-256 `218241d2ab7aecfafa78ec95096ccb2d0b280864c1455bcc181afc3135e6ba00`; log SHA-256 `7b3b48ff24fe791bdaa0158ec81382b3ad40fcc78e8ed044b3de9d34d25cff18`. |
| `reviewer_evidence/fetch_sigkill_real_io_round3.log` | Same corrected actual-helper probe against final fetch SHA `5d648dac…` | 0 | 1 passed. Partial bytes remained private; retry removed the temp, resumed the same attempt, and published the expected image SHA. Log SHA-256 `0eff4e4aff1eeeb141db043497d78fb42345948aa43530a7fb15a8b925430661`. |
| `round3_fetch_atomic_17_green.log` | `test_wechat_article_fetch_recovery.py`, after the atomic publication fix | 0 | 17 passed, including the real child-process partial-temp-write/SIGKILL recovery case. |
| `round2_hk_8_green.log` | Appendix R1 tests plus independent HK read-facts probe | 0 | 8 passed. |
| `round3_targeted_atomic_green.log` | Recovery, handoff, handoff-v2, prepare-manifest, R1 appendix, review boundaries, and independent HK probe after the atomic fetch fix | 0 | 103 passed, 18 subtests passed. |

The final targeted pytest command is recorded verbatim in `round3_targeted_atomic_green.log`; its exact exit code and output are in that log. The earlier first-round 13/120/137 green runs remain under `round1/` as historical results for earlier hashes. Independent review later found concrete counterexamples against those hashes, so they are not presented as final verification.

Independent final decision: `PASS_OFFLINE_SCOPE`, with 0 open P0/P1/P2 in the exact five candidate files listed above. The reviewer bound that decision to the same source hashes in `issue31/reviewer_evidence/FINAL_REVIEW.md` and `FINAL_REVIEW.json` (SHA-256: `d9fc5bbe3c5a9173a7fd805693eeab1869dc75d626c855a4548e9115b36150f0` and `9163098d6661bafc2983baabaa5bcac72d046e961eb4f16837955ef24c1a636e`). The review is limited to the synthetic Linux source candidate; it does not upgrade Mac/runtime/collector/Drive behavior.

## Remaining `CANNOT_CONFIRM` boundaries

- The supplied snapshots do not contain the active `scripts/wechat_pipeline_runner.py`, the external `wechat_article_intake.py` collector, or actual parent-level `AGENTS.md`. The actual Mac default entrypoint, collector flags/schema, and active `--html-file` path remain unverified.
- The offline fixtures validate known summary, image-manifest, and checkpoint path relocation fields. The real external collector's additional path-bearing fields and checkpoint schema remain unverified.
- Native macOS Vision execution and active Mac cache behavior were not run. The current positive OCR-cache test uses synthetic records checked by existing handoff validation.
- The atomic hard-link publication and SIGKILL path passed independent actual-helper verification in this Linux test environment, not on the active Mac filesystem.
- Market fixtures are synthetic Parquet data only; no market-data repair or live-market assertion was made.
