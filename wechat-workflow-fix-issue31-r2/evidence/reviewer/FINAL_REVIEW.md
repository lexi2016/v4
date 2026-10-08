# Issue #31 — `FINAL_REVIEW`

**Decision: `PASS_OFFLINE_SCOPE`.** I found no open P0, P1, or P2 issue in the five exact candidate files listed below. The review is limited to the synthetic Linux source candidate and local tests. Active Mac/runtime/collector/Drive behavior remains **CANNOT_CONFIRM**.

## Exact candidate reviewed

| Candidate file | SHA-256 | Size |
|---|---|---:|
| `candidate/wechat/scripts/wechat_article_fetch.py` | `5d648dac0b712a05be2345d1fe73020d3e99520b8256b003c29120c232dedb17` | 58,707 B |
| `candidate/wechat/tests/test_wechat_article_fetch_recovery.py` | `3d5a55f32c62a1ea250f1bdfef3b41584abcccbb06199000357483acdde2e124` | 31,535 B |
| `candidate/wechat/scripts/wechat_yesterday_performance.py` | `840908dc4350d91abd7b74e94ec4993954ba32edca6bcc7eb8eac646824d3f5c` | 89,787 B; 1,596 CRLF lines |
| `candidate/wechat/tests/test_prior_mentions_performance_appendix.py` | `969e5f05b2ecdc8e65d8de2255336b3a7f8ed275095640da755bac1168609588` | 26,675 B; 492 CRLF lines |
| `candidate/wechat/WORKFLOW_公众号链接固定执行方案.md` | `6737f1b37f1bc6f7df90b654296b5f46fe3ee8ac8be06421ee6fbbc342ff592f` | 37,675 B; LF |

The workflow document differs from the baseline by the single added paragraph. It keeps the documented existing pipeline runner as the ordinary entry point, says the active Mac argv must be checked for `--skip-ocr`, and ties `prepare_ocr`, `ocr_full`, and `package` progression to verified artifacts. The paragraph explicitly leaves active Mac behavior unverified.

## Previously confirmed issues now closed

The final candidate closes all eight issues confirmed during review:

1. **P1 — Empty or non-article BODY accepted from summary claims.** The adapter validates captured HTML and real article body content rather than trusting the collector’s `article_body_found` claim.
2. **P1 — Stale raw HTML could pass cached identity.** Cached raw HTML is bound to source identity evidence.
3. **P1 — Prepared image URL mutation could be accepted as the same source.** The image URL projection is bound to immutable attempt evidence while legal prepare metadata updates remain possible.
4. **P1 — `OCR_OK` summary alone could imply package readiness.** Progression requires verified OCR result and slice artifacts through the existing handoff validation path.
5. **P1 — Abbreviated collector `--out` could escape the attempt directory.** The adapter constrains the collector output arguments before execution.
6. **P1 — Saved-HTML summary commit without a promotion receipt could strand recovery.** The permission is bound to attempt evidence and pending recovery resumes the promotion.
7. **P2 — HK receipt facts could disappear after current-panel binding failure.** The appendix retains actual receipt status, SHA-256, and row count, reports binding as unconfirmed, and keeps affected HK returns null.
8. **P1 — SIGKILL during direct promotion could leave a partial public image and block recovery.** Final publication writes to a private temp, atomically links the completed bytes, and cleans leftover private temps during recovery.

No P0/P1/P2 remains open within the tested offline scope.

## Independent verification and evidence

Each result below is tied to its log by SHA-256. Counts are reported per command; they are not combined across review rounds.

| Test scope | Result | Exit | Log SHA-256 |
|---|---:|---:|---|
| Final fetch recovery test module | 17 passed | 0 | `304728422255963bb71e8667ad5f7810e8affd44077ba5fbc4cfa7bbe0158313` |
| Six independent fetch acceptance probes | 6 passed | 0 | `67310d9acd9a1c5a29b924d230c4d19fc83865de935de7ad99e8a5f1ebcbf384` |
| Corrected real-I/O SIGKILL probe against immutable `068fb8…` source | Expected baseline failure reproduced | 1 | `7b3b48ff24fe791bdaa0158ec81382b3ad40fcc78e8ed044b3de9d34d25cff18` |
| Corrected real-I/O SIGKILL probe against final `5d648d…` source | 1 passed | 0 | `0eff4e4aff1eeeb141db043497d78fb42345948aa43530a7fb15a8b925430661` |
| Appendix tests against unchanged exact final appendix SHA | 7 passed | 0 | `b1a8e1edb7a8cdae23b8eaac3a889f25dbc5ac9d0fa5b6559dc7e63eaf16518a` |
| Independent HK receipt facts after panel-binding failure | 1 passed | 0 | `3dd8a455f93386b2d78b9d5605f1c2f52fd55f0962f89b0bd7d602cae0ead952` |
| Adjacent R1 chat-review regression module | 29 passed; one dependency deprecation warning | 0 | `9aefe5efd4e0c871a29466958f51e1f81ec060ebe5ddeb43cf70bf8665b1135c` |

The corrected process-kill probe source is `test_fetch_sigkill_real_io_probe.py`, SHA-256 `218241d2ab7aecfafa78ec95096ccb2d0b280864c1455bcc181afc3135e6ba00`. It loads the selected source SHA in both parent and child, forwards `*args`/`**kwargs` into the real `_write_bytes_create_only` helper, and wraps only the helper’s real `os.fdopen` file handle. Against the exact immutable round-two source, the actual helper wrote and fsynced 34 of 68 image bytes before the child was killed; the truncated public path remained and retry refused it. Against the final source, the public path remained absent at the kill point; retry removed the private partial temp, recovered to `SOURCE_RECOVERED_NEED_OCR`, and promoted the expected image SHA.

Other independent test sources are bound as follows: `test_fetch_risk_probes.py` SHA-256 `1f797894e15ad4ff6b32997360f9f629aedbe72f500829cf8f0a5f846c91f135`; `test_appendix_read_facts_probe.py` SHA-256 `74bf4d4285d731d5691f62e58a7deddcce73c1bb47f9ff48a02c2c252c404929`; and `candidate/wechat/tests/test_chat_review_regressions.py` SHA-256 `baf72d48c13b27629caf2399a59db974b7b9697b3568d02fe7b9b6aa8c753698`.

An earlier process-kill harness replaced `_write_bytes_create_only` and created the partial target itself. It bypassed the helper and is explicitly **not** evidence for this decision. Its source and log remain preserved as superseded artifacts in the interim round-two receipt. The valid red/green evidence above uses the corrected actual-I/O probe.

## Evidence boundary

These results are **SOURCE_CANDIDATE_TESTED** on Python 3.12.14, pytest 9.1.1, Linux, with synthetic fixtures and the specified local dependencies. The active Mac runner and its actual `--skip-ocr` argv, external collector behavior, real macOS Vision OCR, default entry point in the active installation, and complete recovery to Drive remain **CANNOT_CONFIRM**. No real WeChat, browser, market feed, order, or Drive access was used.

The supplemental `html_bytes` probe was not run and has been moved under `reviewer_scratch`; it is excluded from the evidence above.
