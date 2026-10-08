# Daily HK announcement research chain

This runbook describes the candidate V4 entry and its owner contracts. A file in this candidate tree does not prove release activation, a live API result, or a natural daily run. The API and scheduler releases remain separate immutable roots; the manager research state stays at the formal owner root below. Do not describe the candidate as deployed until the exact release, binding, canary, and scoped cutover receipts have been read back.

## Runtime boundary

The intended API entry is `$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py`, using the pinned `$V4_MANAGER_ANNOUNCEMENT_PYTHON` and loopback owner API at `http://127.0.0.1:8873`. The inactive candidate roots are:

```text
API:       /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r2-api/app
Scheduler: /Users/lexi/Library/Application Support/com.lexi.v35.local/releases/manager-daily-chain-20261008-r2-scheduler/app
State:     /Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research
```

The 06:30 heartbeat owns announcement capture and the article-level reader/reviewer work. It must save factual reader output and independent reviewer output as JSON against one exact evidence run. The scheduler announcement-collection hook stays disabled (`announcement_collection_enabled=false`); a plan-only scheduler binding, if separately activated after a fresh owner canary, may call only the existing workspace-plan owner. It does not collect articles, choose decisions, score securities, change Stage eligibility, or issue BUY/order actions. Keep `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.

## Capture and review

For a fresh run, use the exact target HK securities session and publication date pair. On a non-session day, use the next verified HK securities session; the publication date remains the prior calendar date. Weekend publication dates remain separate products even when they resolve to the same target session.

```sh
"$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py" capture \
  --target-date YYYYMMDD --publication-date YYYY-MM-DD \
  --api-base http://127.0.0.1:8873 \
  --research-state-root "$V4_MANAGER_RESEARCH_STATE_ROOT"
```

The command refreshes and reads back the exact Eastmoney date catalog through the existing V4 owner, then captures article bodies through the shared `MaterialStore`. It writes `catalog_read.json`, `body_corpus.json`, `body_corpus_manifest.json`, `body_batch_receipt.json`, and `capture_receipt.json` beneath `announcement_agent_runs/<evidence-run-id>/evidence/`. Preserve every source timestamp and body gap. A terminal partial capture is visible as partial: failed body rows stay failed and unassessed; do not convert a failure to `COMPLETE` or infer a selection.

For an interrupted capture, resume only the saved exact catalog run. This avoids issuing another owner refresh:

```sh
"$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py" capture \
  --target-date YYYYMMDD --publication-date YYYY-MM-DD \
  --api-base http://127.0.0.1:8873 \
  --research-state-root "$V4_MANAGER_RESEARCH_STATE_ROOT" \
  --resume-evidence-run-id "$EVIDENCE_RUN_ID"
```

Use the returned evidence run id exactly:

```sh
EVIDENCE_RUN_ID='<exact evidence_run_id>'
EVIDENCE_DIR="$V4_MANAGER_RESEARCH_STATE_ROOT/announcement_agent_runs/$EVIDENCE_RUN_ID/evidence"
```

The heartbeat runs its assigned readers against this fixed evidence directory and saves the factual output as JSON. A different reviewer saves a separate reviewer-output JSON. Add an article-decision JSON only when every source article has been reviewed and explicit dispositions were produced. If decisions were not made, omit them; the owner product remains `NOT_ASSESSED`. No generic or override disposition is permitted.

## Validate, register, import, and read back

Run `prepare` against the exact saved owner catalog, reader output, body corpus, and capture-evidence root. It validates source identity and body lineage without network or owner writes. The capture evidence root is required for the terminal body-capture contract:

```sh
"$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py" prepare \
  --target-date YYYYMMDD --publication-date YYYY-MM-DD \
  --catalog-read "$EVIDENCE_DIR/catalog_read.json" \
  --semantic-catalog "$READER_OUTPUT_JSON" \
  --body-corpus "$EVIDENCE_DIR/body_corpus.json" \
  --body-capture-evidence-root "$EVIDENCE_DIR"
```

Register the actual output bytes against that same capture run. The register command validates the terminal body set again, binds reader/reviewer bytes and the exact date pair, builds the product, and preserves content gaps as `TEXT_INSUFFICIENT_UNASSESSED`:

```sh
"$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py" register-handoff \
  --evidence-run-id "$EVIDENCE_RUN_ID" \
  --research-state-root "$V4_MANAGER_RESEARCH_STATE_ROOT" \
  --target-date YYYYMMDD --publication-date YYYY-MM-DD \
  --semantic-catalog "$READER_OUTPUT_JSON" \
  --reviewer-output "$REVIEWER_OUTPUT_JSON" \
  --parent-task-id "$HEARTBEAT_TASK_ID" \
  --reader-identity "$READER_ID" --reviewer-identity "$REVIEWER_ID"
```

Add `--decisions "$DECISIONS_JSON"` only for complete, explicit, source-bound dispositions. The CLI copies source JSON bytes to fixed filenames under the evidence root, writes an immutable handoff manifest, and rejects conflicting existing bytes. The resulting `OUTPUT_BOUND` receipt binds output bytes and declared reviewer fields; it does not authenticate a platform identity or constitute a cryptographic signature.

Import through the same-origin loopback V4 owner API. The CLI sends the evidence run id, handoff-manifest SHA, and product SHA; the API derives fixed filenames beneath its own `service.store.root`, verifies the bindings, imports through `ManagerResearchJobService.import_announcement_analysis`, and reads the product back. An owner receipt records `available_at` after that readback.

```sh
"$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py" import \
  --evidence-run-id "$EVIDENCE_RUN_ID" \
  --research-state-root "$V4_MANAGER_RESEARCH_STATE_ROOT" \
  --api-base http://127.0.0.1:8873
```

Read the exact target/publication pair back from the owner. Confirm product SHA and owner import-receipt SHA before marking the import complete:

```sh
"$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py" readback \
  --target-date YYYYMMDD --publication-date YYYY-MM-DD \
  --api-base http://127.0.0.1:8873
```

## Plan cutoff and activation

The workspace reads only announcement products in its existing HK source-date window. It admits a product only when the owner product/readback, listing/body acquisition times, reviewer `reviewed_at`, and owner `available_at` are valid and no later than that plan's actual `research_cutoff`. Late or invalid products stay visible with a reason and are omitted from plan input identity. Only explicit `SELECTED` and `CONDITIONAL_WATCH` research references are projected. References remain outside scoring/ranking; historical PIT, first-publication time, and Connect eligibility remain `CANNOT_CONFIRM` unless an authorized source establishes them.

For PREOPEN, the existing `ManagerResearchJobService.refresh_us_mapping_research` owner must run before the plan read. The plan binds the saved exact-date mapping artifact SHA only when it was available by the same cutoff. A failed or partial mapping remains visible and does not suppress the plan. Verified identical daily mapping content is reused to keep repeated triggers stable.

Any plan-only scheduler activation requires a fresh historical `MANUAL_REFRESH` owner canary against the exact inactive API release and the original formal manager-state root. The canary contract binds the actual POST `/api/v4/manager/research/workspace/refresh?date=YYYYMMDD`, subsequent GET `/api/v4/manager/research/workspace?date=YYYYMMDD`, response bytes, owner run/product/input identity, persisted readback, and safety flags. The target must be a verified past HK securities session. The scheduler binding must pin the same canary SHA and formal state; announcement collection remains disabled. Until the canary receipt, final binding, release inventory, and scoped cutover receipt are independently checked, the plan-only scheduler is not active and no deployed or natural-run status is claimed.

## Separate HK daily volume-unit work

The B3 TDX capture/gate and 20-day volume-unit changes remain candidate-only and are `NOT_INTEGRATED` into this D1 release. Keep the current canonical six-bar implementation unchanged. Its 20-day background is `NOT_CAPTURED_IN_SIX_BAR_SUPPLEMENT` and remains `CANNOT_CONFIRM`; no master, volume-unit, or 20-session evidence may be inferred from the candidate-only canary.
