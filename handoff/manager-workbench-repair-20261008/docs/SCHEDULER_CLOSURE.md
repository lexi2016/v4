# Scheduler / plan owner deployment closure

Scope: pinned remote source at `lexi2016/v4@0fd5eb374cb155232ed003d5fc4d0d3594252491`, compared in the isolated Linux workspace. This is not Mac process-loaded identity evidence. Reported configuration is API R3, active scheduler `hk-research-calendar-all-r1-20261007-scheduler`, inactive R2 scheduler, disabled plan binding. No binding or service was changed.

## 1. The frozen active daemon already contains the hook

The 20261007 startup snapshot has `AnnouncementCycleHook`, `_load_announcement_binding`, and its `run_daemon` invocation. `AnnouncementCycleHook` has an identical AST in the active snapshot and R2. The R2 daemon adds `_json_identity_sha`, `_release_inventory_entries`, `_validate_candidate_app_plan_binding`, `_validate_same_root_plan_canary_inventory`; it changes binding validation and truthful readiness / execution-status reporting. It does not add a previously absent scheduler.

| Release-relative file | Frozen active SHA-256 | Assembled baseline and unchanged candidate SHA-256 | Deployment treatment |
| --- | --- | --- | --- |
| `ops/run_v35_macos_scheduler_daemon.py` | `19e071da0c6b6748465853c4ad86a80d6060524333e9dab21647b67adc8b49ec` | `7e3ead4e646a599981878e7b5eca66ecde01217de83f0f3039637a411cfa1f5c` | Explicit prerequisite overlay for the R2 validation/readiness contract. A baseline-to-candidate repair diff omits it. |
| `ops/launch_v35_macos_scheduler.sh` | `0c577ae83b1f182dabf3b62e642a5bd5f0f8708b48e1806d8c653b691d2ec952` | `2634b60f718e4c94fec0d731d12102e27d85847d8e0b9e8bb6f5ab499ae6d9d5` | Preserve the actual active wrapper. Do not overlay the assembled copy. |
| `ops/run_v35_macos_scheduler.py` | `f707df50c31f03fd51e439eece0d86dd60647d8d989e9a760f2ef1f2222c6f0d` | `dd704a5ade7dd1f8a818dbeb94a9b3c7407cb403c8221373d899fdb4741f79b9` | Preserve the actual active runner and its dependency closure. Do not overlay the assembled copy. |

The active wrapper requires and verifies the HK panel TDX root, defaults HK02 to the no-site launcher, and passes `--a-daily-timeout-seconds 3600`. The assembled older wrapper loses those contracts. The active runner imports `ops.run_v35_macos_scheduler_due`; the assembled runner uses a different split-module layout. Wholesale deployment of the assembled scheduler could therefore regress unrelated active workloads.

The concrete deployment basis is a fresh byte-verified copy of the actual active scheduler release, preserving its launcher, runner, `ops/run_v35_macos_scheduler_due.py`, `ops/launch_hk_0_2_python_nosite.sh`, native dependencies, symlinks, modes and runtime/data bindings. Apply only the explicitly reviewed R2 daemon prerequisite there. Independently verify that its before SHA matches the actual source. Any mismatch requires reviewing that delta instead of assuming the frozen snapshot is still live. Copy the actual configured R3 API as the API basis and apply the separately recorded API repair deltas and required preimages. The assembled Linux tree is not a complete replacement release.

The hash comparison and AST delta are machine-readable in [scheduler_closure.json](../evidence/scheduler_closure.json).

## 2. Exact configuration interfaces

The existing launch wrapper must retain `V35_DAEMON_MODE=persistent-minute`; its other mode runs the one-shot scheduler. Preserve existing runtime, data, dispatch-ledger, preselection, selection, HK universe and HK panel bindings.

The scheduler environment pins the shared binding and the actual API owner:

```text
V4_MANAGER_ANNOUNCEMENT_BINDING=<exact shared binding path>
V4_MANAGER_ANNOUNCEMENT_APP_ROOT=<new immutable API app root>
V4_MANAGER_ANNOUNCEMENT_PYTHON=<original venv invocation path>
V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256=<resolved interpreter byte SHA>
V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256=<new API cycle file SHA>
V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256=<fresh exact-root plan canary SHA>
```

The API must have `V4_MANAGER_PLAN_OWNER_BINDING_PATH` pointing to the same exact binding, and its original formal manager-state/security-master roots. API release metadata, manifest, environment, `WorkingDirectory`, `PYTHONPATH`, interpreter invocation and process-loaded root need one consistent deployment identity.

The following is the proposed final contract to render and verify later; no enabled configuration was written here:

| Binding field | Required value / meaning |
| --- | --- |
| `schema_version` | `v4.manager_research.announcement_binding.v1` |
| `enabled` | Disabled during staging; final activation requires a fresh validated canary and scoped cutover. |
| `policy_status`, `policy` | `PROPOSAL_ONLY`, `BALANCED_V1` for every configured five-minute morning tick. |
| `app_root`, `manager_state_root`, `security_master_root` | Exact API root and original authoritative state roots, with non-overlap checks. |
| `python`, `python_resolved`, `python_sha256` | Preserve the venv invocation identity and pin the resolved executable bytes. |
| `files` | Exact `binding_inventory(new_api_root)` closed inventory; update after all source changes. |
| `priority_codes` | `[]`, unless an existing separately authorized source-bound list applies. |
| `plan_material_refresh_only` | `true` only in the final separately activated plan-only binding. |
| `announcement_collection_enabled` | `false`; the existing heartbeat owns announcement acquisition and judgments. |
| `activation_receipt` | Absent in plan-only mode. An announcement receipt cannot activate plans. |
| `plan_activation_receipt` | Fresh `{path, sha256}` for `HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK`, same exact candidate root / inventory and original formal state. |
| `morning_plan` | `{enabled:true, interval_seconds:300, status:"PROPOSAL_ONLY"}`. This explicit key is essential: omission defaults to disabled. |
| `preopen_plan` | `{enabled:true, lead_seconds:180, status:"PROPOSAL_ONLY"}`. |
| `plan_material_refresh` | `{enabled:true, start_local:"16:00", end_local:"23:00", max_attempts_per_target_date:3, retry_backoff_seconds:600, status:"PROPOSAL_ONLY"}`. The current plan-only validator requires this enabled evening section. |
| Safety flags | `research_only=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`. |

On verified HK securities sessions, morning is 07:00 through before 09:25; intervals 300/600/900 seconds are accepted. Preopen with lead 180 is 09:27 through before 09:30 and the original owner must finish before the opening boundary. Evening targets the next native-calendar HK session. `LOW_LOAD_V1` invokes the hook every two minutes; combined with a five-minute morning interval it yields only their ten-minute intersection, so it must not be described as every five minutes. Calls after the legal window are rejected, not silently backfilled as scheduled.

## 3. Existing render tools are not current deployment artifacts

`candidate/ops/prepare_manager_daily_chain_release.py` hardcodes `ACTIVE_BASES.api` to the 20261007 API and checks that identity. The reported API is now R3. Its C1 allowlist also does not describe the full current repair delta. Its generated binding includes preopen but omits `morning_plan`, and its staged canary SHA starts empty.

`remote/handoff/manager-daily-chain-20261008/tools/ops/prepare_final_release.py` similarly hardcodes obsolete API/base/output roots and previously reviewed exact source SHAs. Its blocked enabled proposal has no actual plan canary and no explicit morning key. It cannot be executed blindly for this repair. Its useful deployment pattern is copying the actual active scheduler tree and overlaying only the reviewed daemon. A current renderer must keep that pattern while deriving the newly observed bases, exact approved deltas, fresh inventory, new receipt paths and hashes. Existing evidence from R2 is not a fresh canary of changed R3-derived owner bytes.

## 4. Closed candidate call chain and remaining external dependencies

The candidate chain is existing hook -> pinned cycle CLI -> fixed loopback POST `/api/v4/manager/research/workspace/scheduled-cycle` -> fully injected existing API service -> original `refresh_workspace_plan` with real `SCHEDULED_MORNING` / `SCHEDULED_PREOPEN` identity -> immutable plan and same-run sealed terminal attempt -> durable dispatch receipt. Evening remains real `MANUAL_REFRESH` under a scheduled parent trigger; it is not relabeled preopen or natural evidence.

Plan admission/retry is serialized by the original store kernel transaction. Failed dispatches are limited to three per parent trigger, with 60-second backoff for morning/preopen and the configured evening backoff. A persisted `RUNNING` ambiguity requires explicit reconciliation. A failed result cannot reset its budget by changing input identity. Successful repeated owner calls rely on the existing owner product/attempt identity; partial results remain partial.

US preparation is now absent from the plan RPC. The original workspace readers continue to consume already available US owner material. Missing reader/owner is `CANNOT_CONFIRM`; when the API exists but no separate bounded execution hook is supplied, preparation is `NOT_ATTEMPTED`, assessment is `NOT_EVALUATED`, matches are `null`, and the gap is `US_MAPPING_REQUIRES_INDEPENDENT_OWNER_DISPATCH`. The original US refresh API remains unchanged. Its natural preparation is still an external dependency; this patch does not claim to have executed it. This avoids both a slow US call consuming the legal plan window and the coordinator's 30-second cooperative budget discarding an otherwise valid plan response. No extra worker/thread/producer was introduced.

Announcements still require the existing 06:30 heartbeat's actual article reader and independent reviewer. `automation-3` in old render metadata is a declaration, not a task definition or run receipt. The supplied closure has capture/prepare/register-handoff/import/readback tools but no independently verified native heartbeat definition or actual automatic reader/reviewer run. Reconnect those existing actors using the same evidence run, exact selection/publication pair, catalog/body/reader/reviewer/decision SHA and original import API. Missing article decisions remain `NOT_ASSESSED`; no rule-generated judgment is an acceptable substitute.

## 5. Acceptance and observed verification

Local targeted test command, with Python 3.14.6 and frozen lock dependencies:

```text
PYTHONPATH=.:upstreams /workspace/scratch/a154a3323e32/test_env/bin/python -m pytest -q tests/test_manager_daily_dispatch_20261008.py
```

Result: 24 passed. The reviewer-driven isolation regression first produced 4 failed / 20 passed, then passed after removing US mutation from the bound RPC. The tests cover actual original workspace-plan persistence in temporary state, exact owner/attempt identity, separate service instances, failed dispatch backoff and budget, corrupt/interrupted receipt handling, fixed client/server transport, legitimate clocks for duplicate reads, unavailable/slow US preparation, and both morning/preopen cutoff rejection. These are synthetic isolated fixtures. The validator itself is loaded from its real file while test bindings are injected; this is not full release-canary or Mac import-closure validation.

Mac acceptance remains `NOT_RUN` and must separately establish:

1. Actual before/after API and scheduler roots, plist/environment/interpreter/inventory identities, preserved native dependency closure and original authoritative state roots.
2. Fresh exact-root historical manual owner canary, matching POST/GET/immutable product/run/attempt/input SHA, with all safety flags and announcement network count zero.
3. After a separately authorized scoped activation, a real future native morning/preopen trigger, legal start/finish times, exact parent trigger/branch, API dispatch receipt, owner attempt and persisted product. A manual invocation, simulated clock or historical canary does not prove a natural run.
4. Original workspace/API/page readback of the same product and independent date/channel gaps. Missing US preparation and missing announcement judgment remain visible; neither suppresses unrelated valid outputs.
5. Actual heartbeat capture -> authenticated reader/reviewer evidence -> original announcement import -> analysis/workspace/page consumer parity for the same target/publication pair. Without the real heartbeat artifacts, complete announcement autorun remains blocked.

No Stage, BUY, Vibe8910, binding or launchd service was changed. Final integrated test results and delivery status are recorded in [results.json](../evidence/results.json); the dispatch cases are part of its 123-test backend total.
