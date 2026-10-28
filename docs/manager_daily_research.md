# Daily HK announcement research chain

This candidate connects the existing date-scoped announcement capture to the existing V4 analysis importer and plan reader. It does not create a collector, fetcher, model provider, scorer, Stage input, recommendation, or BUY path.

## Heartbeat run

The restored 06:30 heartbeat supplies an exact pair for each run: `--target-date` is the current HK securities session, or the next verified HK session on a non-session day; `--publication-date` is the previous calendar date. Weekend publication dates that resolve to the same target session remain separate `(target_trade_date, publication_date)` products. Never omit the publication date when importing or reading a specific product.

1. Use the pinned V4 announcement Python and API app from the heartbeat environment. Run `ops/run_manager_daily_announcement.py capture --target-date YYYYMMDD --publication-date YYYY-MM-DD --api-base http://127.0.0.1:8873 --research-state-root "$V4_MANAGER_RESEARCH_STATE_ROOT"`. The command refreshes the exact Eastmoney date catalog through the existing V4 owner, reads it back for the same pair, and captures the whole catalog's article bodies through the existing shared `MaterialStore`. It writes the exact catalog readback, body corpus, page/body manifest, batch receipt and capture receipt under `announcement_agent_runs/<evidence-run-id>/evidence/` and prints the evidence run id. Preserve every article gap and source timestamp; do not use another source or treat transport completion as semantic or PIT validation.
   Use the printed `evidence_run_id` exactly and set `EVIDENCE_DIR="$V4_MANAGER_RESEARCH_STATE_ROOT/announcement_agent_runs/$EVIDENCE_RUN_ID/evidence"` for the remaining commands.

   A body-fetch canary is available only for the approved 20261008 / 2026-10-07 catalog article `AN202610071830178357`. It reuses the exact saved owner catalog and shared material cache; it does not refresh the listing. Use a new, empty output directory and do not rerun an existing canary directory:

   ```sh
   "$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/manager_announcement_body_batch.py" \
     --target-date 20261008 --publication-date 2026-10-07 \
     --catalog-read "$EVIDENCE_DIR/catalog_read.json" \
     --material-root "$V4_MANAGER_RESEARCH_STATE_ROOT/materials" \
     --output-root "$EVIDENCE_DIR/body_canary_AN202610071830178357" \
     --canary-article AN202610071830178357
   ```

   Its only terminal status is `CANARY_PARTIAL`, even when the article body is complete. It writes one article receipt/body under that isolated directory and no full `batch_receipt.json`, `body_corpus.json`, or `body_corpus_manifest.json`; it is never a formal import input. An unknown article or wrong date pair fails before creating the output directory. The H2479 applicant identity is retained as a source identity only; it does not establish listed-stock status, eligibility, or PIT.
2. The heartbeat runs the assigned semantic readers against that fixed evidence directory and saves their factual output as JSON, plus the independent reviewer output as JSON. A person or agent may provide an explicit article-level decision file only when the complete article set has been reviewed. If selection judgment was not made, omit decisions; the registered product remains `NOT_ASSESSED`. No default, generic, or override disposition is permitted.
3. Run `prepare` against the exact catalog readback, semantic catalog, and body corpus. This validates dates, source hashes, canonical hashes, body-to-listing bindings and input coverage without network calls or owner writes:

   ```sh
   "$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py" prepare \
     --target-date YYYYMMDD --publication-date YYYY-MM-DD \
     --catalog-read "$EVIDENCE_DIR/catalog_read.json" \
     --semantic-catalog "$READER_OUTPUT_JSON" \
     --body-corpus "$EVIDENCE_DIR/body_corpus.json"
   ```

4. Register the actual outputs against the captured run. `register-handoff` copies their original JSON bytes to fixed filenames under the same evidence root, binds their byte hashes and source pair in an immutable manifest, builds the analysis product, and preserves content gaps as `TEXT_INSUFFICIENT_UNASSESSED`:

   ```sh
   "$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py" register-handoff \
     --evidence-run-id "$EVIDENCE_RUN_ID" --research-state-root "$V4_MANAGER_RESEARCH_STATE_ROOT" \
     --target-date YYYYMMDD --publication-date YYYY-MM-DD \
     --semantic-catalog "$READER_OUTPUT_JSON" --reviewer-output "$REVIEWER_OUTPUT_JSON" \
     --parent-task-id "$HEARTBEAT_TASK_ID" --reader-identity "$READER_ID" --reviewer-identity "$REVIEWER_ID"
   ```

   Add `--decisions "$DECISIONS_JSON"` only for full-set decisions actually produced by the heartbeat. Repeating identical output bytes is an idempotent no-op; different existing bytes are rejected and preserved. The output reports `OUTPUT_BOUND` with external review status `DECLARED`; it proves byte binding, not platform identity authentication or a cryptographic signature.
5. Import the registered ref through the same loopback owner:

   ```sh
   "$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py" import \
     --evidence-run-id "$EVIDENCE_RUN_ID" --research-state-root "$V4_MANAGER_RESEARCH_STATE_ROOT" \
     --api-base http://127.0.0.1:8873
   ```

   The CLI sends only the run id, handoff-manifest SHA and product SHA to the loopback V4 API with a same-origin `Origin` header. The API derives fixed filenames under its own `service.store.root`, rejects symlinked files, verifies byte/date/source/product bindings, imports through `ManagerResearchJobService.import_announcement_analysis`, and reads the product back. An adjacent owner receipt records server `available_at` after readback.
6. Run `readback` with the exact target and publication dates. Confirm the product SHA and owner import receipt before declaring the owner import complete:

   ```sh
   "$V4_MANAGER_ANNOUNCEMENT_PYTHON" "$V4_MANAGER_ANNOUNCEMENT_APP_ROOT/ops/run_manager_daily_announcement.py" readback \
     --target-date YYYYMMDD --publication-date YYYY-MM-DD --api-base http://127.0.0.1:8873
   ```

## Reader evidence and decisions

The heartbeat must save its reader output and independent reviewer output as JSON bytes. The reviewer output declares `review_conclusion`, exact dates, evidence run id, reader/reviewer identities, reviewed time, source catalog/semantic/body hashes, `decision_status`, and `decision_payload_sha256`. The registered receipt is derived locally from those output bytes and carries matching hashes and `OUTPUT_BOUND`/`DECLARED` states. It does not claim platform identity authentication.

For explicit decisions, set `decision_status` to `EXPLICIT_DISPOSITIONS`, set `article_decision_count` to the full article count, and set `decision_payload_sha256` to the digest of the exact `article_decisions` list. The independent reviewer output must declare `PASS` for that same decision hash. `announcement_selection.make_extension` validates that every source article has one source-bound outcome; it does not choose or fill outcomes.

## Plan cutoff and scope

The workspace reads only product pairs in its existing HK announcement source-date window. A product is consumed only when the owner product/readback, every available listing/body acquisition time, `reviewed_at`, and owner `available_at` are valid and no later than that plan's actual `research_cutoff`. Late or invalid products remain visible with a reason and are omitted from plan input identity. Only explicit `SELECTED` and `CONDITIONAL_WATCH` research references are projected; `NOT_ASSESSED` yields no selection references. These references remain separate from the existing announcement body classifier and do not alter scores, selection thresholds, Stage eligibility, or BUY state. First-publication time, historical PIT and Connect eligibility remain `CANNOT_CONFIRM` unless an authorized source establishes them; Eastmoney semantic analysis is not a substitute for HKEX completeness.

For PREOPEN, the existing `ManagerResearchJobService.refresh_us_mapping_research` owner runs before the plan read. The plan reads its saved exact-date product and binds the artifact SHA only when it was available by the same plan cutoff. A failed or partial mapping remains visible and does not suppress the plan. Identical verified daily mapping content is reused to keep repeated triggers stable.

## Candidate runtime configuration

`staged_config/manager-plan-binding-c1.disabled.final2.json` and the two `*-c1-final2.plist` files are candidate-only and unactivated. API and scheduler point to separate split release roots and the same exact binding path and isolated candidate state root. `manager-plan-binding-c1.proposed-enabled.blocked.final2.json` records the intended `enabled=true` state, but deliberately omits the required owner activation canary receipt, so the supervisor validator rejects it. Neither staged plist references this proposal. The receipt is identity-only rollback evidence; no live plist, process, state root, service, or scheduler was changed.
