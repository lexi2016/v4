# Minimal Mac concurrency correction candidate

Base FAIL: 11a28c3eaf352cbea20abf944cd8eaa99897cf14. Reported Mac single invocation: 30 instances, 29 PASS / 1 ERROR, only 23 unique tests. The repeated class's later success does not cancel the first failure. Keep task-3/daily-foundation-11a28c3e/tests.log and RESULT.json as the failed evidence; no cloud product test or Mac rerun is claimed here.

## Diagnosis and evidence limits

The error is at creation of `.lock`, before flock: run_ledger.locked used descriptor-relative os.open with O_CREAT but without O_EXCL. Existing directory helper only mkdir/fsync/open, no removal. Root is retained by TestCase and its bound cleanup; ThreadPoolExecutor exits/joins before unittest cleanup. Each locked invocation owns its fd/lane/day/lock locals; no shared numeric fd or cleanup of another thread appears in this path. Thus the supplied stack does not support blaming premature fixture cleanup or flock contention.

A closely matching Darwin first-create race has a primary reproducer report: https://github.com/golang/go/issues/81246 (openat O_CREAT without O_EXCL can return ENOENT when callers create the same absent name concurrently; both C/process and thread reproductions reported). This report is still NeedsInvestigation, not an Apple confirmation or direct trace of our Mac. The candidate diagnosis is based on that mechanism plus our exact syscall/stack. The user's full OS/version and syscall trace have not been supplied, so Mac verification remains necessary.

Minimal production change: exclusive creation with O_CREAT|O_EXCL; only FileExistsError enters a second open without O_CREAT. O_NOFOLLOW, regular-file validation, fd lifecycle, flock, serialization and persistence are unchanged. No ENOENT catch, retries, deletion or inode replacement is added. Other failures still propagate. No module_artifacts/shared API change, owner algorithm change, new feature, source capture or deployment.

Duplicate discovery was independently confirmed: unittest enumerates TestCase classes bound in module globals, including `from test_run_ledger import RunLedgerTests` in test_daily_dispatch. Both tests now import a plain data-fixture factory. Original seven RunLedgerTests methods remain; fixture resources are explicitly retained by each case and cleanup remains case-owned.

## Mac verification candidate

From the candidate checkout, execute this suite ONCE:

```bash
PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_us_mapping_scope test_run_ledger test_daily_dispatch test_daily_us_owner -v
```

Expected discovery: 26 UNIQUE test IDs = 7 scope + 10 ledger (original 7 + new 3) + 5 dispatch + 4 US wrapper. No repeated RunLedgerTests under another module. Any ERROR/FAIL means FAIL; no repeat-until-green acceptance.

Three new ledger cases:

1. Deterministic syscall fault model raises ENOENT for `.lock` O_CREAT without O_EXCL. It should be RED with base production source and GREEN with the candidate, while proving the existing-file branch opens without O_CREAT. This models the reported Darwin mechanism; it is not an actual kernel reproduction.
2. One bounded stability case: 20 fresh roots, four threads released by a barrier per root (80 claims total). Each round must return exactly one CLAIMED, three outcome-unknown/in-progress, one persisted attempt and a still-existing root. Worker exceptions are not caught; subtest failures all count. This races fresh directory and lock creation, not only an already-created lock. Roots remain alive until test cleanup after joined workers.
3. Injected real ENOENT category propagates on the first lock open with exactly one call, demonstrating no swallowed failure/retry.

Optional deterministic RED command, using an EXISTING separate base checkout plus candidate tests (do not overwrite the candidate or change online sources):

```bash
PYTHONPATH=/ABS/BASE_11a28c3/V5/src:/ABS/CANDIDATE/V5/tests python3 -B -m unittest test_run_ledger.RunLedgerTests.test_first_lock_creation_avoids_darwin_create_or_open_race -v
```

Base source is 11a28c3eaf352cbea20abf944cd8eaa99897cf14; test code must be from this correction candidate. Expected RED is FileNotFoundError at the legacy `.lock` O_CREAT call. This command does not invoke owner data or network. Exact fixed correction commit is provided in the delivery message.

Cloud checks: AST, static unique method counts, diff and remote-byte readback only. Functional, concurrency and stability results remain NOT_RUN pending the existing Mac task. Existing US diagnostics, stored products and dabcfbee preview are unchanged.
