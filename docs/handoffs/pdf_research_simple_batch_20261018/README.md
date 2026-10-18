# Simple PDF research batch

The batch runner consumes the frozen `v4.pdf_research_simple_batch.manifest.v1` inventory at `R/inventory/batch-manifest.json`. Each document is keyed by its PDF SHA-256. It uses the existing page-text cache when valid and the pinned native extractor for missing native text; it does not download PDFs or invoke OCR. A document with unavailable pages remains `TEXT_UNAVAILABLE` or `PARTIAL_SOURCE_NO_MODEL_REQUEST`; a report from incomplete page text is explicitly marked `MODEL_GENERATED_SOURCE_PARTIAL`.

Short documents are analyzed in one request. Longer documents are split into page-numbered source units with exact offsets, capped at 8,000 source characters and 32,768 serialized request-envelope bytes. Each part is retained, then combined through bounded synthesis requests. The original page input remains alongside the report. Every generated report is labeled `MODEL_GENERATED` and `SOURCE_REVIEW_PENDING`; queue `SUCCEEDED` means only that the request and output schema passed. S18 is reused only for its exact PDF SHA and frozen user-acceptance receipt. Its copied report remains byte-identical to the accepted model report; the separate presentation note carries the accepted qualification, and the original raw output is not read or changed.

For each actual model request, the runner reads announcement queue metadata. Same-model `RUNNING`/claimed work defers the PDF batch. A historical `PENDING` count is recorded as advisory and does not block by itself. The PDF queue attempts the shared model lock once inside `SerialAnnouncementQueue.run_next(wait_for_model_slot=False)`; a busy lock defers without an attempt. After an attempted PDF request returns and releases the lock, the process waits at least three seconds before another request. It does not write announcement state.

The batch uses one singleton lock and the isolated state root:

```text
/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/batches/simple-20261018-r1
```

Run the focused tests from the repository root with the regular V4 development interpreter:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pdf_research_batch.py
```

The following is the reproducible command for a later root-activated run after independent source review. It is not part of this offline implementation milestone:

```sh
cd /Users/lexi/Desktop/学习/v4_app
PY=/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python
R=/Users/lexi/Desktop/学习/agents调试/V4_PDF_SIMPLE_BATCH_20261018_R1
STATE='/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/batches/simple-20261018-r1'
mkdir -p "$STATE/logs"
nohup env PYTHONDONTWRITEBYTECODE=1 "$PY" -m ops.run_pdf_research_batch --manifest "$R/inventory/batch-manifest.json" --execute >"$STATE/logs/batch.stdout.log" 2>"$STATE/logs/batch.stderr.log" </dev/null &
printf '%s\n' "$!" >"$STATE/runner.pid"
```

Check the saved PID against the process command before acting on it, then read progress and logs:

```sh
STATE='/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/batches/simple-20261018-r1'
PID=$(cat "$STATE/runner.pid")
ps -p "$PID" -o pid=,stat=,etime=,command=
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps({k:d.get(k) for k in ("status","manifest_sha256","document_count","documents","stop_reason")},ensure_ascii=False,indent=2))' "$STATE/run-progress.json"
tail -n 80 "$STATE/logs/batch.stderr.log"
```

To stop an activated batch, first confirm the displayed PID is the `ops.run_pdf_research_batch --execute` process, then send it `TERM` and wait for it to exit:

```sh
kill -TERM "$PID"
while kill -0 "$PID" 2>/dev/null; do sleep 1; done
```

`TERM` requests a cooperative stop. A model request already in flight is allowed to return; the runner then persists that request's raw and validated queue artifacts and its current chunk or synthesis receipt before it exits. It does not start another model request or document after the signal. The document and batch receipts use `STOPPED_GRACEFULLY`, and the same manifest/state root can resume unfinished work while reusing the successful queue result. A forced kill cannot provide this persistence guarantee.

Re-running the same frozen manifest and state root reuses completed document receipts and queue successes, preserves immutable artifacts, and works only unfinished requests. Failed requests have one attempt and remain recorded; the runner does not retry them. A changed manifest requires a new reviewed state root rather than mixing old and new inputs.
