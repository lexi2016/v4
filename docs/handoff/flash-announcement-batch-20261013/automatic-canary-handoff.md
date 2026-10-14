# Flash Next temporary automatic canary

Status: `CANARY_FAILED_WAITING_REVIEW`; mechanism review passed and overall semantic quality failed. The writer did not start the model request or temporary foreground service; this is a local research test harness, not a Workbench integration.

## Frozen input and admission

- Model: `qwen3_8_flash_next`; authorized prompt profile: `decision_grounded`; system prompt SHA-256: `107fb203c20440ed904763d12f90bee4ca6984c43292527dfc61ba6f8384f772`.
- The exact template/token counts were rebuilt for the current `decision_grounded` prompt and current tool schema. Tool schema SHA-256: `22b574965199bd1e960c91b2d4bab2b512e75a4f19c6032f4cc63fbcbfee6383`. The active manifest records one full-body request per article, the input SHA, source/body hashes and exact prompt token count. All 34 unique inputs fit the effective 262,144 context with the actual 32,768 completion maximum; max prompt is 10,558 and max prompt plus completion is 43,326 tokens. The 2,048-token reserve remains informational only.
- Current manifest SHA-256: `b5a0d67695d639d4e3d945439e57437588bf6fd886aeb4690d098bb4ba8f1578`; revision 2 supersedes the former `decision_first` manifest SHA `cf0a1c4a8d0dbd926a87d8b8d28f864cea0e91a7d7187351baccb03dbc4b6fc6`, preserved as `automatic-input-manifest-decision-first-superseded.json`. The older estimate-based manifest remains preserved separately. New queue ID: `automatic-20261014-b5a0d67695d639d4`; its state is in `evidence/automatic-20261014/queue-state/automatic-20261014-b5a0d67695d639d4/`. The old `decision_first` queue and its 34 pending entries remain at `queue-state/queue-state.json` without being reused or overwritten.
- The first phase is the frozen 6-ID A/B canary union. It must finish with six successes and no failures before pressure can start. The page then waits at `WAITING_QUALITY_REVIEW` and shows completed, failed and remaining counts. Pressure batch 03 contains 29 IDs, including one canary overlap; the successful overlap is reused, so pressure adds at most 28 model requests.
- The second action is the explicit UI confirmation **“已独立核验，运行压力29”**. The receipt records it as a user UI confirmation with `automated_semantic_review=false`; the harness does not claim to perform semantic review. If canary has failures, pressure remains blocked until the canary is retried successfully. Phase state and the gate are saved beside the new queue state. A restarted server does not infer automatically; click Start to resume an interrupted, already-authorized phase.
- The source population is the verified 277-complete-body capture from `evidence/decision-first-20261014/stress/stress-batch-manifest.json` (SHA-256 `45c3493a84c4cb70c9356821f1331dd7e9978cdf4168b29476a2dd360197e0e0`); the active manifest lists every frozen article ID and per-request input/source/body SHA. 26 incomplete bodies remain excluded. Full 277-item inference is not scheduled. Research flags remain `research_only=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.

## Start the visible run

Keep the existing local oMLX process on port 8802 running, with Flash Next explicitly loaded. Do not submit another model request from another client while this queue is active; the harness serializes only its own local queue.

From the test directory, run:

```bash
PYTHONDONTWRITEBYTECODE=1 "/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary/automatic_canary_server.py" \
  --port 0
```

The foreground process prints a temporary `UI_URL` on `127.0.0.1` and confirms `INFERENCE_STARTED=false`. Open that URL in the visible local browser and check the model/queue status. Press **Start：运行 / 继续当前阶段** once to run or resume the canary phase only. Page load and status polling do not call the model.

After six canary successes, inspect the displayed counts and perform the independent quality review. Only after that review, click **已独立核验，运行压力29**. This click is the explicit user authorization for the pressure phase. Do not use Start to bypass the gate. **停止后续排队** lets the in-flight request finish and prevents later claims. **有界重试失败项** is phase-scoped and limited by the queue's two-attempt bound.

When the selected phase reaches a terminal state, stop the foreground temporary server with Ctrl-C. If a request is in flight, shutdown waits for it to finish. The run writes phase-trigger/gate events, the persistent controller state, `automatic-run-receipt.json`, per-attempt raw stream receipts, and the existing queue's raw and validated per-article artifacts beneath `evidence/automatic-20261014/`.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 "/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python" -m unittest pipeline_canary.test_automatic_canary_server pipeline_canary.test_announcement_queue pipeline_canary.test_batch_runner -v`: 37 tests pass. Coverage includes the locked grounded prompt SHA and actual executor request body; six canary successes stop with zero pressure executions; explicit second-stage UI confirmation; failure blocking; overlap de-duplication; persisted/recovered phase state; and queue idempotency. Tests use fixtures, mock transports, and synthetic phase tracking; they send no model request.
- No model request, web lookup, UI import, local admin write, runtime setting change, model switch, foreground service start, or production action was performed by the writer. The user-triggered run and independent review outcome are recorded in the addendum below; no formal integration or natural-period validation was performed.

The evidence root and generated queue inputs/receipts use private permissions. The page uses same-origin and per-process CSRF checks and inserts model text only with `textContent`.

## 2026-10-14 run addendum

The user-triggered six-article canary finished with `CANARY_FAILED_WAITING_REVIEW`; the independent mechanism review passed, while overall semantic quality failed. The 29-item pressure phase did not start. See [automatic-canary-results.md](automatic-canary-results.md) for the redacted result summary and frozen receipt identities.

The UI metric formerly labeled TTFT is now labeled **首流事件（非首字）**. The receipt's `ttft_seconds` records the first SSE event, which can contain role metadata with empty content; first-content latency is `CANNOT_CONFIRM`. Historical receipt values were not changed, and the label edit did not rerun inference.
