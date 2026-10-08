# Issue29 independent Mac review

REVIEWED: the candidate matches the exact seven-file manifest delta; all seven after hashes and nine preserve pins match. Final API inventory is 1020 entries and web inventory is 334; both aggregates match the postpatch receipts.

TESTED: reviewer Mac checks returned 78 passed and one frozen-baseline failure; the new Python subset passed 34, support tests passed 23, Vitest passed 13, and strict scoped TypeScript compilation exited 0. Writer's 95/7 run includes the same six new US fixture cases, which failed because TMPDIR was unset and TemporaryDirectory used the /var symlink path. They pass with TMPDIR=E/review/pytest-tmp. This explains the environment-specific test failures; it does not prove a production data-root failure. The other failure is the same HK02 test failure in the frozen baseline.

BEHAVIOR_VERIFIED: the isolated candidate ASGI historical GET reached exact run ba13fba330464300b760fe940ba579a1 and returned HTTP 200 with status SOURCE_FAILED and exact reason HISTORY_SOURCE_INPUTS_CHANGED. The target files remained stat-stable and the probe reported write_performed=false. This is the exact next rejection; successful consumption is not confirmed. The cutoff is hash-sanitized and attempt is null in the output.

The final probe SHA 81a98cc995c4c8d3ccc68a922e574b530a2177f9f336e097e3392a8c1b707aaf was reviewed. Its narrow changes accept the active python -B module command, preserve the configured V4_MANAGER_VIBE_BINDING path inside the filtered environment without printing it, and accept RESEARCH_ONLY=1 while retaining false-only transaction flags. The write guards and ASGI GET boundary remained intact.

No live API/page, integration, or natural-slot status is claimed. Release remains FROZEN; deployment was not run. Cleanup: 49 reviewer-generated candidate pyc files were removed; the final API inventory matches the recorded postpatch aggregate.

Receipt SHA-256: 3340b5b098ed925849b1a14d47fc92c10e8b66720026facb0aa0d2bfe418103b (review/independent_receipt.json).
