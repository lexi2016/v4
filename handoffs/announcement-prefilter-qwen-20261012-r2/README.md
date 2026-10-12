# Issue #38 — V4 Announcement Prefilter + Local Qwen (candidate R2)

**Status:** isolated source candidate; **offline regression 14/14 PASS**; original R6 `run_manager_daily_announcement.py` patch dry-run and byte-compare PASS. **NOT DEPLOYED**, **NO REAL QWEN INVOCATION**, **NO FROZEN 23-ARTICLE REPLAY**, **NO OWNER IMPORT / WORKSPACE GET / NATURAL SCHEDULER PROOF**. Do not mark Issue #38 closed on this evidence.

## Files

- `ops/announcement_prefilter_qwen.py`: deterministic conservative routing, exact per-row reconciliation, conflicting article/issuer/body isolation, fully quoted model facts, local attestation, cross-process lock + atomic versioned semantic cache, raw provider usage receipts.
- `ops/run_manager_announcement_prefilter.py`: existing capture-receipt-bound CLI and distinct triage output; never creates a second capture producer/timer or owner-reviewed receipt.
- `tests/test_announcement_prefilter_qwen.py`: 14 tests; synthetic inputs only.
- `docs/R6_run_manager_daily_announcement_issue38.patch`: **applies only** to frozen R6 `ops/run_manager_daily_announcement.py` (SHA-256 `5e3eb65b3d758082010ba4cc367d03d3b4225e99a1394147a8e09ce9715ec45e`). It adds optional `capture --prefilter-after-capture`; it **does not** claim the live heartbeat calls capture.
- `docs/CANDIDATE_STATUS.md`: implementation boundaries and exact next acceptance gates.

## Installation (on isolated R6 test root, not live 8873)

```bash
sha256sum ops/run_manager_daily_announcement.py  # MUST equal the R6 SHA above
cp <candidate>/ops/announcement_prefilter_qwen.py ops/
cp <candidate>/ops/run_manager_announcement_prefilter.py ops/
patch -p1 --dry-run < <candidate>/docs/R6_run_manager_daily_announcement_issue38.patch
patch -p1 < <candidate>/docs/R6_run_manager_daily_announcement_issue38.patch
PYTHONPATH=<candidate> python -m pytest -q <candidate>/tests/test_announcement_prefilter_qwen.py
```

## Offline canary without claiming a model call

Only after the original capture has produced the complete `evidence` directory:

```bash
python ops/run_manager_announcement_prefilter.py \
  --evidence-root '<research_state>/announcement_agent_runs/<run_id>/evidence' \
  --cache-root '<research_state>/announcement_qwen_cache' \
  --out '<evidence>/prefilter_runs/manual_canary.json'
```

With no actual local verified model identity the script reports `NOT_ASSESSED` for all ambiguous/major events and `new_model_calls=0`. This is expected. For model calls provide `--model-pid`, `--model-dir`, `--model-name`, `--model-revision`, `--model-endpoint` verified from the local server; `.revision` must match the immutable revision and `config.json` must identify the expected model family. `lsof` must tie endpoint port to the model process. Weight SHA-256 is computed from local `.safetensors` files. A mere API alias, including `claude-sonnet-4-6`, is not proof of Qwen3.8.

## Safe boundaries

The model response must include quoted contiguous original-body text, subject and state, with source offset and SHA. The code can **reject demonstrable contradictions**; it does not assert that quote matching proves full semantic correctness. Model results remain `QUOTE_CHECKED_REVIEW_REQUIRED`; script skips remain `SCRIPT_ONLY_NOT_REVIEWED`. They are NOT compatible with an independently signed `EXPLICIT_DISPOSITIONS` owner receipt without further owner contract work. The existing `build-reviewed`, `register-handoff`, `import`, source/PIT checks, BUY gate and 8873 services must not be bypassed.

Key versions: parser `v4.body-identity-r1`, rule `v4.ann-prefilter-r1`, prompt `v4.qwen-body-facts-r1`, schema `v4.qwen-verifiable-facts-r1`. Cache excludes target trade date to reuse only unchanged body+policy+verified model; every run separately rebinds date, source and catalog. A cached result is never historical PIT proof. Provider `total_tokens` is not the sum of cached/reasoning components. Missing provider usage is `NOT_REPORTED`; synthetic test usage is not production usage.
