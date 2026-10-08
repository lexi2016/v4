# Issue #31 reviewer receipt — round 2

**Interim round-two status: superseded by the final review receipt.** The appendix candidate passes its frozen tests and the independent receipt-facts probe. The six previously reported fetch probes pass against the round-two fetch source. The first process-kill harness shown in the earlier interim receipt directly replaced `_write_bytes_create_only`, so it bypassed the helper and is retained only as superseded evidence. The corrected probe below wraps the actual `os.fdopen` file handle while forwarding arguments into the real helper; it confirms the same P1 on the immutable 068fb8… baseline and passes against final 5d648d… candidate.

## Frozen candidate identities

| Area | Path | SHA-256 | Size |
|---|---|---|---:|
| Fetch | `root_evidence/review_round2_source/wechat/scripts/wechat_article_fetch.py` | `068fb84876a8cd9da940effc4468e73f0a3f530d626fa7506e8cada528c68a1d` | 56,770 B |
| Fetch tests | `root_evidence/review_round2_source/wechat/tests/test_wechat_article_fetch_recovery.py` | `fa1fa08ea027ce1bacfbd32755269fcc6eff8d7b3a10a9acef74a106239f962a` | 25,247 B |
| Appendix | `candidate/wechat/scripts/wechat_yesterday_performance.py` | `840908dc4350d91abd7b74e94ec4993954ba32edca6bcc7eb8eac646824d3f5c` | 89,787 B; 1,596 CRLF lines |
| Appendix tests | `candidate/wechat/tests/test_prior_mentions_performance_appendix.py` | `969e5f05b2ecdc8e65d8de2255336b3a7f8ed275095640da755bac1168609588` | 26,675 B; 492 CRLF lines |

## Verification

- Fetch recovery suite: **16 passed**. Log SHA-256: `cb5663735f637ffd0b8d4f4562d5b9fc32ef88a21a4dd11d9badf96e169d62f5`.
- Independent fetch risk probes: **6 passed**. They cover article BODY validation, raw-HTML cache identity, prepared image URL identity, OCR-summary-only false readiness, abbreviated `--out` handling, and saved-HTML recovery after summary commit without a promotion receipt. Log SHA-256: `fb2c3e46eeae618c391d29e570126ae0b8dcc47a37424932b4c2f304c58ac93b`.
- Appendix tests: **7 passed**. Log SHA-256: `b1a8e1edb7a8cdae23b8eaac3a889f25dbc5ac9d0fa5b6559dc7e63eaf16518a`.
- Independent HK receipt-facts probe: **1 passed**. On a current-panel SHA binding failure, it confirms the actual current receipt status, receipt SHA, and row count remain disclosed while all HK returns remain null. Log SHA-256: `3dd8a455f93386b2d78b9d5605f1c2f52fd55f0962f89b0bd7d602cae0ead952`.
- R1 chat review regressions: **29 passed**, with one Starlette deprecation warning. Log SHA-256: `9aefe5efd4e0c871a29466958f51e1f81ec060ebe5ddeb43cf70bf8665b1135c`.
- Corrected actual-helper SIGKILL probe against the immutable round-two baseline: **failure reproduced**. The wrapper forwards `*args` and `**kwargs` to the real `_write_bytes_create_only`, then intercepts only its real `os.fdopen` handle. It writes and fsyncs 34 of 68 image bytes; the child is killed, leaving a truncated public image, and retry exits with code 2 and `ValueError: refusing to replace existing article image`. Probe SHA-256: `218241d2ab7aecfafa78ec95096ccb2d0b280864c1455bcc181afc3135e6ba00`; old-source log SHA-256: `7b3b48ff24fe791bdaa0158ec81382b3ad40fcc78e8ed044b3de9d34d25cff18`.
- The same corrected probe against the final 5d648d… candidate: **passed**. The public image path is absent at the kill point; retry cleans the private partial temp and completes source recovery with the expected image bytes. Log SHA-256: `0eff4e4aff1eeeb141db043497d78fb42345948aa43530a7fb15a8b925430661`.

The round-two P1 is closed in the final candidate by writing and fsyncing a private temporary file before atomically linking the complete bytes into the public destination; interrupted private temps are cleaned during pending recovery. The exact final-source verification is recorded in `FINAL_REVIEW`.

## Evidence boundary

These results are **SOURCE_CANDIDATE_TESTED** on the synthetic Linux fixture. They do not establish Mac behavior. The active Mac runner, external collector, parent AGENTS, real Vision execution, default Mac entry point, and complete recovery to Drive remain **CANNOT_CONFIRM**. No real WeChat, browser, market data, or Drive access was used.

An unrun supplemental `html_bytes` probe was moved to `reviewer_scratch` and is excluded from this receipt’s executed evidence.
