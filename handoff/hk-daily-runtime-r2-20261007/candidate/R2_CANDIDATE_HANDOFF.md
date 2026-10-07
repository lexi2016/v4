# HK daily Stage R2 candidate handoff

## Candidate identity and dependency lineage

`hk-daily-runtime-r2-20261007` is an inactive release candidate. Its release manifest is SHA-256 `fdc7dc01d7d37093766cd595fb12c892370545c683a228dc218a72b708c40a49`; the 918-entry app inventory is `e505a303f53f5d96cd037743d8c81cd438bbbc4a1001c6819b10cbefa6aa543c`; its scheduler plist is `53fa0280b50c084e6705f2dcb5c59b2bb4239f4cab711dbe58b16b3f57646513`. The runner config in the inactive package is pinned at `4d8c8c6a2e4a11b17469e19397c825e5c6ab9360ca53a80cb39f02a4a82fb350`.

The package keeps the R1 release lineage and includes the frozen Stage runtime delta based on R3 manifest `f642954ebcb2c7af86e9c7ea84674e485ab82530503474536167766624895434`. Its manifest pins 21 Stage source/test paths: an 18-path runtime dependency closure plus the focused Stage regression tests. The closure carries the existing Stage contract, runner, collectors, dispatcher, snapshot pre-capture/reader and research-context dependencies; the R2 runner adds the reviewed exact-target fail-closed binding and existing-lock publication-race recheck. Do not treat that package lineage as activation: R2 remains `NOT_ACTIVATED`; the existing R3 runtime remains in place.

The package uses the observed V3.5 runtime (`Python 3.14.6`, `futu-api 10.6.6608`, `numpy 2.5.2`, `pandas 3.0.5`, `pyarrow 25.0.1`, `pytdx 1.72`). A formal lockfile and rebuildable wheelhouse are still `CANNOT_CONFIRM`. The sanitized [config example](stage_center_tick_config.example.json) replaces all 16 absolute path values with placeholders. The loader does not expand those placeholders; this file is structural documentation and must be populated for an environment before any config check.

## Cross-date replay result

Both dates were run through the same R2 package identity using the existing 100-row D-1 pools and raw artifacts with a bar window of 14:46–14:59; the artifacts were captured after the target cutoff. In each case, the 100 pool codes matched the 100 unique raw codes and the raw input remained `PARTIAL_WITH_ROWS` with `temporal_cutoff_safe=false`.

| Target date | D-1 signal | D-1 pool SHA-256 | Existing raw artifact SHA-256 | R2 Stage result |
| --- | --- | --- | --- | --- |
| 2026-09-24 | 2026-09-23 | `50a014bb51a66ca5bf56853bcf25bc6dc2dacbda257a03e0bb0db2abd7448564` | `59ee4e3ca3d030c0fb3ee19e40513a81e464760108cbd3851af4d95c93cba669` | `CANNOT_CONFIRM`: `HK_ACTIVE_SNAPSHOT_EVIDENCE_MISSING`; legacy pool schema has no explicit `stage_selection_eligible` marker |
| 2026-09-30 | 2026-09-29 | `f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901` | `b8de882a59460a4ce9e4b4e9f16e2969bb9c778f14300dbe9726084b37fdb295` | `CANNOT_CONFIRM`: `HK_ACTIVE_SNAPSHOT_EVIDENCE_MISSING`; pool carries `stage_selection_eligible=true`, but no valid cutoff/date/stage/pool-SHA-bound active snapshot is present |

The production binding gate stopped both runs before a selection envelope was written. No selection rows or per-code exclusion reasons are asserted. No active snapshot was synthesized, no live provider or natural scheduler was used, and the source raw-store latest/trio/run IDs were unchanged. A remained `NOT_PROVIDED_IN_HK_ONLY_REPLAY/CANNOT_CONFIRM`; `production_allowed`, `buy_gate_updated`, and `orders_sent` remained false. Formal Stage eligibility, PIT safety, online snapshot-v2 acceptance, and natural-slot acceptance remain `CANNOT_CONFIRM`/`NOT_RUN`.

The compact replay receipt is recorded separately as `cross_date_stage_replay_receipt_r2_attempt2.json` (SHA-256 `061dc996c85a4bc116cce1dd7951f5d7e9f4e01b4ccece7f87ac1ac522d0be6d`). Per-date runner receipts are `37f1803675afb93893e1457ca1c097d1f7d2d29aaa9444cda383fae61354f7c8` (2026-09-24) and `a11a020be9e20e6105d2e5b0e880af21248d3d0d5d3f8c98cf2230cf1e7de8b9` (2026-09-30). These hashes identify evidence files; no raw prices or large source-evidence payloads are included in this handoff.

## Acceptance and remaining blocker

The final independent receipt is `independent_review_receipt_20261007_r2.json` (SHA-256 `2c9697aca108a8581befac1db381109f27533b09d3935aa3c9e6cb44d7e8a751`). It reports `engineering_package=PASS`, `requested_crossdate=BLOCKED`, `selection=NOT_VERIFIED`, `behavior_verified=CANNOT_CONFIRM`, `ready_to_apply=false`, and `deployment=NOT_AUTHORIZED_BY_ACCEPTANCE`; the reviewer recorded no source findings. The receipt records 19 passes for the focused target-publication-race regression, reuse of the prior independent snapshot regression receipt (33 passed) because those source bytes were unchanged, and a candidate config check of `CHECK_OK` for 16 node identities. It also verifies the final-identity 2026-10-07 exact-target binding readback: `candidate_exact_target_binding_readback_20261007_r2_racefix.json` (SHA-256 `e8c82ecc6478538663d1f35d965be061063e298aeaf6873e61b21d47f9de78c0`) pins the final manifest and runner, with 100/100 source-to-binding membership for pool SHA `29f8118784b892091aa001ae676cd339cb14eef9e80e9406e65cbb3637af57e8`. That readback confirms membership only; capture timing and PIT remain `CANNOT_CONFIRM`, and it does not resolve the separate 2026-09-24/2026-09-30 cross-date blocker.

For the requested 2026-09-24 and 2026-09-30 replay, each 100-row input matrix reached the StageRunner but the production binding gate stopped before HK collection: both returned `CANNOT_CONFIRM/HK_ACTIVE_SNAPSHOT_EVIDENCE_MISSING`, observed rows were 0/100, and no selection envelope or selection artifact was written. The missing input is a genuine cutoff-timed snapshot bound to the target date, stage, and pool SHA. The matrices do not establish zero selections or a Top100-to-stage outcome. A remained `NOT_PROVIDED_IN_HK_ONLY_REPLAY/CANNOT_CONFIRM`; PIT and natural-slot acceptance remain `CANNOT_CONFIRM`.

Previously measured broad suites are diagnostic only: one Stage suite showed two failures also present on the R3 baseline, while a separate 47-test scope showed 40 passed / 7 candidate dependency or fixture mismatches. They are not represented as a full-suite PASS or as the final reviewer’s run. The current apply wrapper still carries pre-race-fix pins and a pending-review gate; it was not run. R2 remains inactive, and the reviewer’s blocked acceptance does not authorize application.

The separate HK daily TDX chain still has an open P1: its exact-date Security Master preflight precedes the TDX day-file/panel refresh needed to provide date-specific inputs, leaving a bootstrap dependency. This candidate did not change or verify that chain. No service switch, scheduler action, shared-state write, or public deployment has occurred.

## Sync preparation

The local sync manifest targets the existing branch `codex/hk-daily-recovery-20261007`. The path prefix `handoff/hk-daily-runtime-r2-20261007/candidate/` is a directory prefix, not a branch. The manifest maps the 21 candidate paths and substitutes the sanitized config example for the absolute-path config. It is prepared locally only; no GitHub push or remote commit has been made.
