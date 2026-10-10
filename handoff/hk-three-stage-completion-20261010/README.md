# 20261009 HK three-stage recovery

15:45 and the 16:10 historical research comparison are restored in the existing 8873 UI. The three-stage request is not fully complete: the original 09:20 auction snapshot cannot be recovered from the available exact-date caches or later-session TDX bars.

## Changes

- `stage8_source/`: a two-file adaptation of the original R3 research path plus its focused test. Explicit current-day research uses the existing TDX collector and unchanged selector for 15:45. Ordinary RT_DATA replay behavior is preserved. The published result has 100 input rows and 10 observation rows.
- `close_source/`: the active-release close builder consumes verified historical backfills and a separately labeled original 0.2 research ranking. Formal metrics remain missing; observed 0.2 hits 10/20 and the existing seven-stage definition has six stages, 31 unique codes, and 6/20 hits. Stage1545 remains outside that pre-existing seven-stage definition.

These are candidate/runtime source snapshots, not a claim that the canonical worktree was modified. The canonical checkout lacks the active 0930 approved research binding. Existing canonical edits were preserved. See RESULT.json for exact runtime identity and boundaries.

## Validation

Independent tests: Stage8 10 passed, close Python 20 passed, close UI 3 passed. Live API and reloaded UI verified; all eight stage responses retained their pre-existing results, including the newly restored Stage8. All 11 served static files are byte-identical to the reviewed build. Four pre-existing typecheck errors remain in unchanged files. One nonblocking missing-signal-date validation edge case is recorded in RESULT.json; actual input dates and SHAs were verified.

Natural-slot execution and formal PIT/membership readiness are not claimed. All outputs remain research-only; no BUY gate or orders changed. Raw quotes, full API responses, runtime data, credentials, dependencies, and dist are excluded from this handoff.
