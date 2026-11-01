# F10 Main / Stage binding candidate — writer handoff

Status: `PREPARED_NOT_ACTIVATED`; writer checks passed; independent review pending. Nothing was deployed or activated. No production data, plist, service, panel, web source or external asset was changed. `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.

## Frozen scope and identity

- Goal: new F10 Main hourly publications may be consumed by Stage only with the same exact source, publication, manifest, original scheduler witness and cutoff checks; retain the three explicitly pinned earlier identities.
- Writer: `/root/f10_binding_writer`, sole source writer; Reviewer: `/root/schedule_graph_reviewer`, read-only independent identity.
- Source: `/Users/lexi/Desktop/学习/v4_app/.task_worktrees/v4-f10-stage-binding-20261102`, branch `codex/v4-f10-stage-binding-20261102`, baseline `ca20c4edf4f715cf075da0eb9c309aec055bf0d7`.
- Allowed source: `infrastructure/manager_input_attestation.py`, `ops/prepare_f10_stage_binding.py`, direct tests and this handoff directory. Forbidden: panel/web, business data, active releases/plists/services; no activation, merge or deployment.
- PASS_SIGNAL: new identity positive + strict negatives + preserved historical source/cutoff/witness + exact candidate allowlist and protected bytes. A writer result is not Reviewer PASS or natural execution.
- STOP: unknown writes, active identity/config drift or any non-allowlisted candidate delta; retain evidence and stop the affected mutation.

Actual loaded plist and launchctl identities were checked before/after preparation: Main `f10-daily-20261101-c94609b4e5fff848-main` SHA `3f9a184c28884411bfc79872b44e6b2189cd33a44bc8413da0f79b9644a83388`; Stage `stage-four-repairs-20261101-r3-stage` SHA `ff62078ab7fb5d05318233fbfab18bd34408a0fc5b162359080c080633ee4115`; API `junda-single-20261101-52b837fa7688cb5d` SHA `0e142b6ae23ee825182893653df24f1bfb48c76d384d69507a9e4c5fd025d341`. Source canonical was not edited.

## Repair and exact candidate differences

Candidate bundle: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/f10-stage-binding-20261102-r1`.

| Role | Manifest SHA256 | Runtime app differences |
| --- | --- | --- |
| Stage | `df06194b880f72cf64ccc7e2c331dbfab45bc80a37f14694d72071ed8a7e4817` | `stage_center_tick_config.json`, `infrastructure/manager_input_attestation.py` |
| API | `c724f07e10c7c5ba17d599d7ead6ce28a6dbfadb82bebcafa858c1c7f231a3a1` | `config/api-v4_manual_collection_stage_config.json`; omit one generated cache below |

Stage current binding becomes the exact F10 tuple. History remains exactly `[workbench-daily-chain-20261031-r6-main, a-daily-name-zoom-20261030-r1-main, a-daily-sop-closure-20261029-r1-main]`, each with its original root and manifest SHA. Maximum history is three; fourth and duplicate entries are rejected. No latest discovery, artifact-selected root, imports from historical owners, evidence waiver or cutoff change was added.

The source baseline has max-one history and obsolete same-materializer selection. The active Stage already has max-two plus correct iteration across pinned owners, using a full original dispatch witness to disambiguate identical code. That active fix is retained in source, and the runtime candidate changes only `len(historical) > 2` to `> 3`. F10 and r6 share materializer bytes; a code SHA alone still cannot establish release identity. Only `HOURLY_COMPLETION_WITNESS_MISSING` permits trying the next explicit owner; source/SHA/ledger/clock/cutoff failures propagate.

API is copied from the currently loaded `52b837fa7688cb5d` app. The manual configuration is based on the actual loaded external `stage-four-repairs-20261101-r4-api` configuration; its only semantic key change is `stage_owner_root` pointing to candidate Stage. Proposed API environment preserves all original external panel/asset/host bindings and changes only the four release identity variables and `V4_MANUAL_COLLECTION_STAGE_CONFIG`. Proposed Stage environment changes only the four identity variables and `STAGE_CENTER_CONFIG`.

One API manifest-listed generated file is omitted in candidate only: `components/wechat_ocr/__pycache__/wechat_common.cpython-312.pyc`, 36,179 bytes, original SHA `12875f1cd96f2cae1ee64bd6139846719b0cb5af57fce48da760880583916bca`. The original cache and original manifest remain untouched. Neither candidate contains `__pycache__`, `.pyc` or `.pyo` files. Official inventory and manifests record the actual omission; this is **two API path differences**, not a config-only byte delta.

Main is not rebuilt: its original source/publication writer identity must remain intact. A precapture is not rebuilt: installed node `PRECAPTURE_A_0925` follows the `node.is_prep` branch to `infrastructure.stage_quote_provider.precapture_native_a_opening` and bypasses stage selection/research context/hourly attestation. The unchanged fixed manual owner program is HK-only: `_prepare_hk_active_snapshots` or `tick(... historical_backfill=True, historical_markets=("HK_CONNECT",))`. It does not consume the hourly Stage manifest contract. Its inherited API manifest env is preserved and explicitly reported as unconsumed by that program; it is not asserted to be a Stage manifest identity.

## Verification and limits

- 13 tests passed, including paired failure under the old r6 binding then success under the F10 binding, full source/publication/original-witness contract with a **fixture dispatch release**, r6 retained historical witness, identical materializer disambiguation, unknown dispatch release, fourth/duplicate history, bad owner manifest/config SHA, bad input SHA, publication after cutoff and dispatch completion after cutoff. Source data is read-only; negative writes and fixture dispatch edits are under the writer's isolated test state only.
- Three **real historical read-only** replays passed: r6 `20261101/2300`, name-zoom `20261030/1000`, sop `20261029/2300`; each resolves its original full dispatch receipt and source SHA without rewriting anything. Replays use original elapsed-day cutoff and are not fresh natural execution.
- Actual candidate Stage fixed manifest/research file verifier passed. Candidate API official `validate_release_identity` passed. Existing `activate_stage_four_repairs.verify_release` and official API inventory verified both complete candidates.
- API config parsed through actual candidate `ManualCollectionService`; real child transport passed with a clearly labelled fixture runner and the real Stage config builder. Cwd/root/release/PYTHONPATH and stdin config match candidate Stage, original data roots are preserved, no collector or production lock ran.
- Mechanical protection audit: Stage 991 inventory entries (989 unchanged); API 1,330 entries (1,329 unchanged plus one explicit cache omission); external panel 491 files, 488 manifest-listed asset SHAs; 27 representative original source files and 3 original dispatch receipts verified unchanged; actual loaded role environments and plist SHAs unchanged.
- `NATURAL_VERIFIED=NOT_RUN`: no F10-original hourly receipt was present in the inspected `20261101` and `20261102` publication/dispatch slots at verification time. F10 positive is fixture-only. API HTTP/UI, natural scheduler execution and deployment are `NOT_RUN`.
- Source-only and isolated candidate testing do not authorize deployment. Rollback requires no action because active roles remain at their preimages. If later authorized, use the existing activation workflow, recheck current loaded identities and all protected external bindings immediately before activation; stale candidates must not overwrite a newer API/panel generation.

## Reproduction

Use `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python -B`, from the source worktree. Do not invoke the preparation command against an existing output; it refuses overwrites. Preparation is `-m ops.prepare_f10_stage_binding --output <new isolated candidate path>` and never activates anything.

```sh
PANEL_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python'
F10_CANDIDATE='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/f10-stage-binding-20261102-r1'
F10_EVIDENCE='/Users/lexi/Desktop/学习/agents调试/v4_f10_stage_binding_20261102_r1/writer'
"$PANEL_PYTHON" -B docs/handoffs/f10-stage-binding-20261102/replay_real.py --candidate "$F10_CANDIDATE" --output "$F10_EVIDENCE/real_replay.json"
F10_BINDING_CANDIDATE="$F10_CANDIDATE" F10_BINDING_REPLAY="$F10_EVIDENCE/real_replay.json" "$PANEL_PYTHON" -B -m pytest -q -p no:cacheprovider --basetemp="$F10_EVIDENCE/reviewer-new-isolated-state" tests/test_f10_stage_binding.py tests/test_v4_research_provenance_boundary.py
"$PANEL_PYTHON" -B docs/handoffs/f10-stage-binding-20261102/verify_manual_transport.py --candidate "$F10_CANDIDATE" --state "$F10_EVIDENCE/reviewer-new-manual-fixture-state"
"$PANEL_PYTHON" -B docs/handoffs/f10-stage-binding-20261102/verify_protection.py --candidate "$F10_CANDIDATE" --replay "$F10_EVIDENCE/real_replay.json"
```

Full receipts, active environment snapshots, original file SHA traces and logs stay in the candidate bundle and `/Users/lexi/Desktop/学习/agents调试/v4_f10_stage_binding_20261102_r1/writer/`. Only source, tests and this concise handoff are eligible for Git. Parent controls push after allowlist review; no push by writer.

## Preserved failures

`prepare-initial-cache-refusal.log`: exact allowlist correctly refused the cache omission before it was explicitly accounted for. The incomplete self-generated candidate was removed and rebuilt, retaining this error log. `regression.log`: pytest's global old temporary-tree cleanup hit an unrelated EPERM; all subsequent runs use a new task-specific `--basetemp` and leave others' temp content untouched. `regression-isolated-r1/r2.log`: fixture construction initially lacked the original store manifest and then correctly rejected relocating absolute source proof paths; fixtures were corrected to read the original proof root without writes. No business validator was weakened. An early Stage probe used the Main/API dispatcher schema and rejected it; Stage was then verified through its existing fixed research manifest validator and full official release inventory instead.

## Existing release workflow integration boundary

`release-proposal.json` plus `release-proposal/{stage,api}.{original,proposed}.plist` in the candidate bundle contain exact copied current preimages and **review-only** proposed bytes. They were never written to LaunchAgents or loaded. Candidate role app/manifest identities are in the table above and full `candidate_receipt.json`; API manual config path is `<candidate>/f10-stage-binding-20261102-r1-api/app/config/api-v4_manual_collection_stage_config.json`, SHA `e80cf630b9ce24757ac99a2ea9a14d335fb25602e31f3b8d463dd46bf1d704a1`.

Stage proposal updates cwd and absolute `ops/run_stage_center_nodes.py` argv to candidate Stage, updates `PYTHONPATH` by exact old-app-root replacement, and updates the four release identity env variables plus `STAGE_CENTER_CONFIG`. Its existing interpreter, calendar, retry and data roots remain. API proposal keeps its interpreter/module argv, port and every unrelated env variable, updates cwd and four identity variables plus manual-config path. The preceding source paragraph's Stage env description also includes this necessary `PYTHONPATH` replacement.

The current `ops/activate_stage_four_repairs.py` is a fixed previous-operation script. Its `API`, `BUNDLE`, `BASE_API`, `TARGETS`, `ENV_PIN`, panel-generation pins, old forward-check pins and hardcoded `('stage','pre','api')` switch loop refer to that operation. **Its original command is not directly usable for this candidate.** This batch reuses its `verify_release` and official inventory checks only. A later authorized release must adapt that existing workflow to exactly **Stage + API**, leave precapture protected, bind the two exact old/new tuples and current external panel generation, point to this proposed environment/manual config, and replace stale forward-check constants. No activation wrapper or new publishing framework was created here.

Before any later authorized mutation, existing prepare/admission must recapture the real current plist raw bytes/load states, current API idle/children state and panel/asset/host bindings under the existing release mutex and manual/announcement guards. Compare them to this candidate's original tuple and preimage SHAs; drift is a stop, not permission to overwrite. Stage's calendar owner must be idle. Keep exact original/staged plist backup bytes and hashes in the release evidence directory. Existing CAS `replace`, owned `unload`/`start`, `restore_touched` and reverse recovery model should then be used for only the touched two roles. Rollback references are current r3 Stage and current `52b837fa7688cb5d` API plus their copied original plist bytes; restore the original API manual path (r4 config), original panel bindings and current legitimate business data. Do not roll data back or change Main/precapture. This is a concrete release proposal requiring independent review and a future explicit activation authorization, not a deployment claim.

The complete machine-readable two-role plan is `<candidate>/two-role-release-plan.json`, with current preimage pins and plist SHAs, both candidate identities, exact env deltas/manual config, forward order `[stage, api]`, reverse owned rollback `[api, stage]`, copied backup references and every other current `com.lexi*.plist` label as protected. It explicitly records `direct_original_command_usable=false`, `generic_plan_loader_available=false` and `requires_future_explicit_activation_authorization=true`. The fixed existing script requires this round's parameter transplant; no tool currently loads this JSON and performs activation automatically.
