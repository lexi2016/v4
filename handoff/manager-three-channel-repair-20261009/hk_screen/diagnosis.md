# HK screen candidate repair — isolated synthetic verification

## Proven failure and remaining uncertainty

The supplied `../reference/problem/evidence/hk_reader_projection.json` and
`../reference/problem/evidence/hk_reader_reproduction_1734.json` show that the exact requested
`20261008` key was absent from the observed authority root's date index. The
original reader executed `entries[trade_date]` before loading that date's
manifest or receipt and wrapped the resulting KeyError as
`StoreError: HK security-master metadata invalid: '20261008'`. The screen
caller then reduced the reason to `SCREEN_SECURITY_MASTER_READ_FAILED:StoreError`.

The historical 16:01 index observation was 36 entries through 20260930; the
17:34 observation was 37 entries through 20261009, still without 20261008.
The original historical index bytes were not supplied. The new tests use
independent, clearly synthetic temporary fixtures; they are not a replay or
reconstruction of either real index.

The separate 17:23 live screen selected session 20261009 and disclosed only
StoreError. Its inner cause remains **CANNOT_CONFIRM**. The separately observed
16:50 exact-date panel missing condition also remains independent. A 695-row
Futu snapshot has not been established as a D1 security master and was neither
used nor converted into one.

## Candidate implementation

1. The supplied upstream master reader now emits bounded `HKSecurityMasterReadError`
   diagnostics. It distinguishes a missing date index, a missing exact-date
   key, invalid index/entry structure, unreadable referenced metadata, identity
   or safety mismatch, checksum mismatch, and invalid artifact rows. Each
   diagnostic contains only status, reason code, requested trade date,
   validation stage, index SHA-256, entry count, latest bounded date key, and
   requested-key presence. Raw errors, paths, and security rows are not exposed.
2. The existing two-value `load_verified_hk_security_master` API remains intact.
   It delegates to a new snapshot reader that reads the index once, verifies
   exact-date identity and all existing safety/checksum conditions, and parses
   the same artifact bytes whose checksum was verified. The receipt's trade
   date is now explicitly required to match the requested date, as the
   manifest's trade date already was.
3. The screen witness explicitly imports the supplied
   `upstreams.v3_shared_data.shared_data.hk_security_master` owner. This is an
   import-owner correction for the assembled source's two same-named package
   paths. The nested daily-supplement import remains unchanged. The witness
   consumes one verified snapshot, avoiding the previous second index lookup
   that could mix one run's rows with another same-day run's manifest path/hash.
   That pointer-race defect is a separate code-level finding demonstrated by a
   synthetic regression; it is not asserted as a cause of a real observed run.
4. The actual screen caller carries the safe diagnostic in
   `data_context.security_master_read`. Generic errors remain unclassified and
   cannot be mislabeled as a missing key. The existing workspace projection
   already forwards this data context. Research-cutoff checks remain in place.
5. A failed screen emits `coverage.counts_known=false` and null for its nine
   unavailable counts. A successfully read screen emits numeric counts with
   `counts_known=true`. Empty result arrays remain empty. Existing web DTO
   adaptation is owned by the parent task. No page layout is changed here.

No index entry is synthesized, no alternate date is selected, and no directory
scan, restore, acquisition, schedule, or secondary producer is introduced.
No real authority root, business state, announcement, quote, trading gate,
Stage/BUY/Vibe boundary, or service deployment was changed.

## Source identity

The isolated assembled baseline is local commit
`7ca0190a721a7fd0fc0c88b79a872889867d111f`; source blobs were supplied by the
parent task from `lexi2016/v4` fixed ref
`b19eb112bd641ca97cac1246af7c81d8873641f4`.
The two production-file preimage hashes agree with the package's
`r3_candidate_reference` entries. Full details are in `changed_files.json`,
and actual import file paths and code hashes are in
`runtime_source_identity.json`.

Changed paths:

- `upstreams/v3_shared_data/shared_data/hk_security_master.py`
- `v4/manager_research/workspace_plan.py`
- `tests/test_manager_three_channel_hk_reader.py` (new synthetic regression)
- `tests/test_manager_screen_summary_contract.py` (old zero-count assertion
  changed to the explicit unknown-count contract)

Neither store.py nor the duplicate nested master reader was modified.
The integrated [source_manifest.json](../source_manifest.json) and [patches](../patches) include all four paths, including the new test. The workstream patch duplicate is not shipped.

## Verification actually performed

Before production edits, the new regression file produced **12 failures**,
exit 1, recorded in `before.log` and `before_result.json`. These were real
behavior failures: missing bounded reason, caller diagnostic loss, mixed
same-date pointer hashes, shadow-reader resolution, accepted inconsistent
receipt date, and absent explicit unknown counts. They were not fixture setup
or missing-import failures. A valid synthetic master reached the actual
READY_WITH_GAPS screen before failing the new diagnostic assertion.

The first candidate run of the same 12 cases passed. The combined targeted
compatibility run initially produced 46 passes and one failure in
`test_source_unverified_screen_preserves_status_and_unknown_counts`, because
that test still asserted the old raw zero fields. The failure was retained in
`compatibility_initial.log`; the intended contract assertion was then updated.

Final targeted command, executed from the assembled app root:

```bash
PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/a154a3323e32/test_env/bin/python -m pytest -q --tb=short tests/test_manager_three_channel_hk_reader.py tests/test_security_master_store_error.py tests/test_manager_screen_summary_contract.py tests/test_manager_input_contracts_20261008.py
```

Result: **47 passed in 0.70s, exit 0**. Complete output and command receipt are
in `after.log` and `after_result.json`. Runtime: Python 3.14.6, pytest 9.1.1,
pandas 3.0.6, pyarrow 24.0.0. `git diff --check` also exited 0.

The positive exact-date case includes a later date in the index, consumes the
requested run, and reaches the real panel/screen calculation. It reports one
known input and one pending row, with zero selected rows; its unproved volume
unit remains NOT_PROVEN and its volume gate remains unknown. Missing and
invalid input cases cannot generate candidates. Tests compare all temporary
authority files before and after reads to verify byte-preserving read-only
behavior. Existing cutoff, calendar, volume provenance, and arithmetic boundary
tests remain included in the 47 checks.

## CANNOT_CONFIRM / not run

- No historical raw index replay was performed; the required originals are absent.
- No legitimate missing 20261008 input was recovered or created.
- The real 20261009 live StoreError inner cause is still unknown.
- The separate exact-date panel missing condition was not repaired by this change.
- No production API/UI, live owner/worker process, deployed import path, natural
  time-window behavior, or Mac local acceptance was executed here.
- The full repository suite and unrelated historical/Stage/BUY suites were not
  run. Verification remained within the user-authorized safe targeted suites.
- This is candidate code only. It does not establish deployment, integration,
  real-data readiness, or resolution of every current external input gap.
