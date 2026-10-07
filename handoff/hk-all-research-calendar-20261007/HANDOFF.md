# HK all-research-calendar handoff

This handoff separates the canonical source delta from the API and scheduler runtime deltas; it is not a complete application release.

The canonical source patch has five modifications and one new test. It is based on commit `9ebb2faa954aa6c910d5fc4f4d4e0c418df9ca89` and baseline manifest SHA-256 `f6d42c8ee02c3c0a64f357df5b6c252f75b119978bbdf092e2754069e091e255`. The patch SHA-256 is `9044eec02eb44a84042327fe75846d3b184783055c103ed451b5d9ce32395e8e`.

The API and scheduler runtime packages were built from their actual R2 application roots. The currently applied candidate identities recorded by the service operation receipts are:

| Service | Release ID | PID in applied receipt | Manifest SHA-256 | App inventory SHA-256 | Runtime graph module SHA-256 |
|---|---|---:|---|---|---|
| API | `hk-research-calendar-all-r1-20261007-api` | 36518 | `a82609515bb91c206e2437b64d09ce5e8a8ae38be144482c425d75a0e7d13f65` | `614478ce925dd5d5b6b8a22ad07ecd8f9198ef365df85c713a634041a7604d13` | `328d936990876467d9e652c3fab28541be7d86aaf5d210ec38d4bc978bcb0444` |
| Scheduler | `hk-research-calendar-all-r1-20261007-scheduler` | 36534 | `f64f62f50a5dcc8e251ffbad10188946ca6308850d8486eed8e156435b546605` | `78d072dd80212dd282cb904080ff404ba2a233becfada3fa400a603f01df518b` | `3fbb73d4a1442c63c4688edc5c46154aa31a76cf326924738dbb32dca292ce65` |

**Current state, 2026-10-07:** both service preflights passed; the root ran `apply-batch`, which exited 0 with `BOTH_CANDIDATES_ACTIVE`. The independent cutover review is PASS (receipt SHA-256 `aff0d0e07f739fe855397db437bdb2c4e9ede6057f7b3023e97561d97cae2627`). Its `DEPLOYED: NO` predates the later root switch. The final independent live readback is [live_deployment_independent_receipt.json](../../review/live_deployment_independent_receipt.json), SHA-256 `382cca5a93af81a83ae3666b09ebcb9c68def772ee0b2c98386068f1f648851e`, observed at `2026-10-07T15:30:59Z`.

`DEPLOYED: PASS`: both expected LaunchAgents were read back running with the candidate app roots, manifest identities, and PIDs (API 36518; scheduler 36534). `API_VERIFIED: PASS` applies to live identity readback only: API app root, plist binding, manifest, process cwd, and loaded runtime-graph module SHA were verified. The API's overall runtime identity remains `CANNOT_CONFIRM` because its dependency manifest and inventory are missing and the runtime-graph snapshot is `EVIDENCE_GAP`/`SNAPSHOT_MISSING`. No date-specific calendar-eligibility GET route is exposed, so live target-date HTTP calendar semantics and `BEHAVIOR_VERIFIED` remain `CANNOT_CONFIRM`. The scheduler's process root, manifest, launcher, cwd, and first `PYTHONPATH` entry match the candidate, but it has no loaded-module identity endpoint. Existing Stage owners remain not running and match their pre-cutover readback; the batch did not restart them. No natural scheduler slot was observed after the switch (`NATURAL_SLOT_UNVERIFIED`), and UI verification is out of scope. Safety remains `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.

Local operation evidence remains under `receipts/hk-research-calendar-all-r1-20261007/` and is referenced by path and SHA-256 in `bundle_manifest.json`; raw operation receipts, release manifests, plists, market/runtime data, and logs are not uploaded. The batch receipt is `api_scheduler_cutover_batch_apply_operation.json` (SHA-256 `4a5f48257c573f0beb3877215adfa5b868710246b892ff3a3d7f5fa00098aed5`); API and scheduler applied receipts have SHA-256 `5399e0b150de28b2d578672b5e7d6c3d971d312aac22041f913d6402d18d26de` and `9cd944e1f75a13344883835e0c16809b4793aa5fe5efcd120ca1ca59f309f337` respectively.

The rollback entry point is `scripts/hk_research_calendar_cutover.py`; it uses the frozen helper at `/Users/lexi/Desktop/学习/agents调试/V4_HK_CLOSE_DAILY_20261007/hk_market_calendar/hk_calendar_candidate_cutover.py` (SHA-256 `264ad2d3f5535e17f6e7471dc12d7e00452104b505795857e9f0637c0a29e816`).

The `bundle_manifest.json` lists all handoff artifacts, including this handoff note. Its own row intentionally has no embedded SHA-256 or Git blob SHA-1 to avoid a recursive self-hash; the root should hash and upload the finalized manifest separately and record it in the local upload receipt.
