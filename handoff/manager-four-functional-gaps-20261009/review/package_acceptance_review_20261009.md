# Independent package acceptance review — 2026-10-09

## Verdict

`REVIEWED=PASS` for the offline handoff package. No confirmed P0/P1/P2 defect remains in the reviewed package. `TESTED=PASS` for the package verifier and bundled synthetic contract smoke. `BEHAVIOR_VERIFIED=PASS` is limited to the evidenced app-wired, read-only fail-closed GET and the synthetic failure envelope; a complete manager selection remains `CANNOT_CONFIRM`.

The ZIP reviewed is `ZIP/V4_MANAGER_FOUR_FUNCTION_GAPS_20261009.zip`, SHA-256 `67098b73089120e7f1758835ce48ce48258ff427a84faca6a19d2415f0306726` (609,101 bytes). It contains 64 files under the `package/` prefix.

## Independent checks

- `python3 tools/verify_bundle.py` passed: 51/51 source snapshots match both recorded source and bundle SHA-256; the package file manifest matches the directory; the ZIP member set and bytes match the manifest; ZIP SHA-256 is the value above.
- `python3 package/tools/contract_smoke.py` passed from the ZIP extraction root. It checks only the synthetic fail-closed envelope (target/date bindings, three `CANNOT_CONFIRM` lanes, unmaterialized plan, zero rows, and safety flags). It does not execute R2 code or establish a stock result.
- The GitHub sync inventory has 64 actual newline-delimited package entries. Its paths and byte sizes match the package directory exactly (2,585,210 bytes); no literal `\\n`/`\\t` escape sequences remain.
- The Chat handoff prompt now states the extraction-root command `python3 package/tools/contract_smoke.py`; the README makes the same working-directory explicit. The packaged and handoff prompt files have identical SHA-256 `745b8085bc9d4ec9221bb88a6f2f6be3a261b48eef1fffc81d83bbec13ece03a`.
- The credential-pattern scan returned no matches. The package manifest lists no raw market payloads, manager state, credentials, browser data, screenshots, distribution assets, dependencies, or compiled Python files; evidence JSON files are metadata projections.

## Target behavior and evidence boundaries

The four R2 app-wired observations match the referenced receipt/report: announcement is not imported for target `20261009` / publication `20261008`; HK Connect authority and target membership are unbound; the oversold reader lacks the exact `20261008` security-master entry; and the saved plan is `STALE_INPUTS_CHANGED`, `consumed=false`, with run readback `CANNOT_CONFIRM`. The matrix preserves the existing owner/consumer chain and requires evidence-backed rows or a verified empty result; it does not relax the identity guard or Buy/production safety.

The day-run document correctly distinguishes three dates/evidence sets. The user's reported standalone `2026-09-30` success entrypoint remains `CANNOT_CONFIRM` because its independent receipt was not located; this does not deny that it existed. The available 09:53 manager plan is `PARTIAL`, with only bounded US attention `READY` (24 proxy rows plus 33 configured symbols), announcement `NOT_RUN`, screen `CANNOT_CONFIRM`, and zero plan stocks. The 2026-10-07 announcement consumed on 2026-10-08 is a verified announcement subchain with a partial channel and no materialized plan, not a three-channel success. The 2026-10-09 owner replay is also partial (`VALID_EMPTY` only for 4/33 reviewed US symbols; plan `PARTIAL`, zero stocks), and is not presented as the user's 09/30 success.

The source snapshot contains the fixed R2 target, the pinned R3 reference, the R1 announcement consumer, and the actual 10/09 owner runner/checker sources, with 51 path/hash-bound entries. The existing 109 R2 regression tests were not repeated per the frozen parent scope; they remain distinct from the bundled synthetic smoke.

## Remaining status

`API_VERIFIED=NOT_RUN`, `UI_VERIFIED=NOT_RUN`, natural behavior `CANNOT_CONFIRM`, and fixed commit/GitHub remote file readback `CANNOT_CONFIRM` from this package review. The sync inventory is not proof that a commit was pushed or read back; the package output directory is not a Git repository. The parent must close the frozen GitHub sync/readback item before calling the overall `PASS_SIGNAL` complete.
