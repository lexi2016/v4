# A1445 2026-09-29 historical backfill and API binding review

Date: 2026-10-01. Scope: read-only audit of the 2026-09-29 A1445 backfill receipt and its API/artifact binding, compared with the previously reviewed 2026-09-30 A1445 receipt. No live runner or acquisition was rerun.

## 2026-09-29 receipt and release binding

Canary receipt: `writer/stage_canary_20260929_a1445/canary_receipt.json`, SHA-256 `ae0368b313f4b268289369d090cb6d14f26e424ac37538edfc271ea9075b90d1`. It binds `exit_code=0`, `trade_date=20260929`, `STAGE_1445_1500`, `mode=BACKFILL`, and backfill namespace `dc880a6143f94a0d8d5d4747756490e9`. Receipt stdout/stderr hashes match their files; parsed stdout equals both the canary summary and the persisted backfill runner receipt (runner receipt file SHA-256 `f77a868ef012273f20be85022e00594001c41db349a475d85bc89fc7b2e9613d`).

The command points to inactive candidate `20261001-stage-pr16-a1445-r1`. The release manifest SHA-256 `fc1d5264c70b595d7ec7d7bb5cf91f7e51631ac44142a89ef166427882996b99`, Stage config SHA-256 `b3cebd21d3fe15fcd6a2772e29e8f26994313034ef554682b7262f976c033e1f`, and invoked `run_stage_center_tick.py` SHA-256 `4eb8e1a3be0e3780ff9cb62417c695c5aab67948f224db462d3f6e3a67299f42` all match the receipt. The candidate manifest says `activation_status=NOT_ACTIVATED` and `service_activated=false`; this run does not establish candidate deployment.

## Source, raw, selection, and runner chain

The declared A acquisition current file exists at `.../com.lexi.v4.local/state/data/current/20260929/A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3/current.json`; its byte SHA-256 `710652d69229244de73bed7ea854efc69bdd6eec9ddeb5bc466b1c35b47a956d` matches the canary and raw/selection evidence. Its run `20260929-a_share_stage_acquisition_universe_v3-933f5d1de9f8` has matching current, artifact, manifest, receipt, and commit-marker hashes; the artifact contains 134 unique codes. The source artifact declares `authority=STRICT_PHYSICAL_POOL_SNAPSHOT`, but also `owner_id=V3_5_STAGE_CENTER`, `producer_id=ops.materialize_stage_acquisition_universe`, `release_id=20260929-stage-scheduler-import-closure-r1`, and `preselection_source_root=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data`. The artifact chain is verified; independent reconciliation of that declared authority with the V4 source boundary is `CANNOT_CONFIRM`.

In isolated backfill namespace `dc880a6143f94a0d8d5d4747756490e9`, the A raw artifact SHA-256 is `100c2ca66611ca1878915f0102fbd87d42c38324cd0f02d809edeb3f1ec3c8eb`. Its pointer artifact hash matches the file hash; raw manifest and receipt canonical SHA-256 values match their respective pointer entries, and the receipt binds the manifest SHA. Raw data is `PARTIAL_WITH_ROWS`: 131 rows of 134, missing `SZ.920275`, `SZ.920786`, and `SZ.920808`; `temporal_cutoff_safe=false` and source status is `CANNOT_CONFIRM`.

The A selection artifact SHA-256 is `0b8113fec1d68d9300363b3bca3a4b50d156b8f740dedb0065b353c2e2b586d9`, with 10 unique codes. Selection manifest/receipt canonical hashes match the selection pointer; both bind raw SHA `100c2ca6…3c8eb`. All 10 selected codes are present in the raw artifact and in the persisted runner receipt. The runner receipt binds date/stage, raw SHA, selection run `run-362afbeb56c4a92e815da42e`, and artifact ID `selection-362afbeb56c4a92e815da42e`. The runner result is `PARTIAL_WITH_ROWS`; all ten A rows are `WATCH_ONLY`. HK is `CANNOT_CONFIRM` with zero rows after PyTDX ExHQ probe failure (`completed=0/100`).

`write_performed=true` is confined to the namespaced backfill paths. The runner records `current_updated=false`, `latest_updated=false`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`. The receipt's before/after ordinary pointer SHAs match, and current on-disk SHA-256 values remain `raw/latest.json=1a685f55…eb464c`, `raw/bundle_latest.json=208ed130…d61164a`, and `selection/selection_latest.json=9077c171…c3078a`.

## API readback and limits

A read-only GET to `/api/v3/workbench/stage?date=20260929&stage=STAGE_1445_1500&limit=10` returned HTTP 200, `response_source=SHARED_STAGE_CENTER`, `status=PARTIAL_WITH_ROWS`, `selection_mode=SHARED_STAGE_CENTER_READ_ONLY`, 10 A rows, 0 HK rows, and false top-level write/production/buy-gate/order flags. The nested A response's run ID, artifact ID, and raw-artifact SHA match the persisted 2026-09-29 backfill artifacts. This verifies API data readback and row/artifact binding.

The API's separate `execution_evidence` is not a verified binding to that isolated runner receipt: it reports `status=DECLARED_ONLY`, `execution_verified=false`, `candidate_binding=REFERENCE_ONLY_CURRENT_TRIO_NOT_BOUND`, `NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING`, and `first_failed_layer=EXACT_SELECTION_INPUT_BINDING` with `RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH`. Therefore API verification of the backfill selection rows is established, while API-side execution-receipt verification and natural execution remain `CANNOT_CONFIRM`. UI verification is also `CANNOT_CONFIRM`.

## 2026-09-30 companion receipt

The previously reviewed receipt `writer/stage_canary_20260930_a1445/canary_receipt.json` has SHA-256 `e940a495bbecf215915c5b46e7fdd51ed610a43c94b363274d472e2d91fcd9ce` and uses the same candidate release, manifest, config, and entrypoint hashes. It binds a separate isolated backfill run `2fc787c1b8fb4b75b7eb6bb8d74127cb`: A 202/205 raw rows and 10 selected rows; HK 0 because `HK D1 status must be STRICT_0_2_READY`; ordinary latest/current pointers unchanged and safety flags false. Its prior API readback matched that run and artifact. Neither date establishes a complete A/HK Stage result, natural-run behavior, UI behavior, or activation of the candidate release.

## Review verdict

`REVIEWED: PASS` for the 2026-09-29 backfill receipt, file-hash chain, and API row/artifact readback. No P0/P1 defect is shown by this evidence. P2 evidence limitation: the API's separate execution-evidence object does not bind the isolated runner receipt and explicitly remains `DECLARED_ONLY`; do not promote that to `API_VERIFIED` execution. Full temporal completeness, V4 source-authority reconciliation, candidate deployment, natural execution, and UI behavior are `CANNOT_CONFIRM`.
