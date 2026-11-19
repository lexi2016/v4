# D17 single K3 native input capture

## Frozen scope and result

- Selected `000407.SZ` solely as the first full code in the original 33 `MODEL_READY` rows; decision date `2026-11-17`.
- Read the existing V4 Reader once for `000407.SZ`, `2024-04-08..2026-11-17`, OHLCV only. Source generation: `dce3fe65d342f59043dc11e032a2058cb67b3a7a0db0f70759c7c337d6f66673`; returned 624 unique bars against 634 calendar sessions.
- Author execution: one frozen R2 run, one AST-verified frozen feature call, one actual call to each pinned Gemini V3 entry. The native D17 state is `SAME_EVENT_PULLBACK`, K3, family `P5146_EVENT_RULE_R2:000407.SZ:20261109`, PB `P5146_EVENT_RULE_R2:000407.SZ:20261109:PB1`. The native PB matches the original row; all 20 features match the archived row by strict float round-trip equality.
- The unstandardized `<20d` little-endian input row is 160 bytes, SHA-256 `6a08c608e3e746f5a9750359b550f9a4aeeb9de008c243f82cb7195fd1ec4b80`. Both V3 calls returned with an empty score list; attached scores: 0.
- Model FIT, preprocessing FIT, model API, new probabilities, static new score, and model deserialization: `0/0/0/0/0/0`. Old 33 scores remain separate; attached count 0. Historical PIT remains `UNKNOWN`; unexposed independent validation rows 0; production unpublished.

## Capture boundary and recovery

The only new panel read was the pinned Reader projection above. No other securities, dates after D17, market acquisition, rank loop, model, scaler, score table, or legacy training runner were used. The R2 author result, feature vector, 160-byte payload, V3 call inputs/outputs, and the run-bound rule/source evidence are under:

`/Users/lexi/Desktop/学习/v4_app/artifacts/p515_d17_single_k3_native_input_20261119/runs/p515-single-k3-000407-SZ-20261119T130039-82288dd6/`

The executed script reached the finalization block after writing the result files, then exited 1 because its `RUN_END` event call passed two positional arguments to a one-argument helper. This did not repeat or invalidate any capture call. A read-only recovery receipt rebuilt the counters and manifest from persisted events and result files. The executed script copy SHA-256 is `1b231206ad0d77e1b31a26aae9f0080fdb8c5a4f3a6ff40b0f37dc07452d82c1`; the current worktree script contains only the corrected `RUN_END` call and has SHA-256 `c43a484f324ed777386033495e8799ae16925d801a6d51d35a4f4cf29c0db00b`.

The original invocation was `"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" "/Users/lexi/.codex/worktrees/p515-d17-single-k3-native-20261119/ops/p515_archive_preview/capture_single_k3.py"`. By default it creates a new exclusive directory under `artifacts/p515_d17_single_k3_native_input_20261119/runs/p515-single-k3-000407-SZ-<timestamp>-<random>/`; an existing run directory is refused. This command is recorded for reproducibility only and must not be run again under this one-shot contract.

`RUN_RECEIPT.json` records the original exit code and the read-only recovery separately. `FILE_MANIFEST.json` lists 29 evidence files; all entries were read back and their bytes/SHA-256 matched. Its SHA-256 is `1def2acba4a92032a87d6d06d0c8418a32971a0293e2e71caadbb65373f14b0f`.

## Rollback

This source is isolated on branch `codex/p515-d17-single-k3-native-20261119`, based on frozen checkpoint `b5ac15f32e1186132c1fdd49905baa8d7b0d22b5`. It is not installed, imported by production, scheduled, or deployed; no service was started. To restore the branch source to its checkpoint, revert only this branch’s source/document change to that base. Keep the run artifacts and recovery record as historical evidence. No integration, publication, or production rollback operation was performed.
