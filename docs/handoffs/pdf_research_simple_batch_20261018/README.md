# Simple PDF research batch

The batch runner consumes the frozen `v4.pdf_research_simple_batch.manifest.v1` inventory at `R/inventory/batch-manifest.json`. Each document is keyed by its PDF SHA-256. It uses the pinned native extractor first and preserves an existing OCR cache only when the page geometry or stored raster dimensions show at least one raster pixel per PDF point on both axes. A geometry-triggered repair uses the existing PDF renderer and macOS Vision leaf in memory, writes derived text only under the new batch root, and is limited to two new page attempts per tick. It keeps the existing 32 MiB image, 45-second render, and 30-second Vision limits. The exact reviewed 5353-character page-one result is reused by PDF SHA `075d0083…d883c`; OCR is never repeated for that page. Other recovered OCR pages remain semantically unreviewed.

For rendered vertical pages taller than 10,000 pixels, the repair reuses the existing V3 `_crop_image` and `validate_slice_geometry` helpers with the same Vision leaf. It permits at most two contiguous full-width slices of 9,000 pixels each and rejects unsupported horizontal or taller layouts before OCR. Each page-level derived OCR receipt records slice bounds, image/text hashes, and timing; the existing immutable page receipt remains the resume unit. The exact 5,202-character page-one canary for PDF SHA `93930e82…89ee9` is reused only when its attempt, slice manifest, text, and independent review hashes match. Its accepted boundary permits only the Green Bubble narrative and air-show schedule/location, preserves stated uncertainty, and excludes market figures, table mappings, and other unreliable details.

Page text coverage and semantic acceptance are separate. Generated statuses use `MODEL_GENERATED_TEXT_*_SOURCE_REVIEW_PENDING`; they do not claim that OCR text has been semantically accepted. Reviewed source boundaries are carried into page input and the top of report and synthesis prompts as the highest-priority user instruction. The first page is suitable only for a conservative AstraZeneca–Insitro narrative with explicit unknowns. The OCR-only contingent-payment number and condition wording stay uncertain; no Insitro code is inferred; large announcement/mapping tables, market metrics, and footer chips are excluded or qualified. The second reviewed page permits only the Green Bubble narrative and air-show schedule/location; it excludes market figures and table mappings. Other OCR pages carry a generic transcription limitation that refers to extracted text, not original-PDF damage. A page with unresolved low-resolution text is deferred or isolated before model analysis.

Execution defaults to the first three manifest entries: accepted S18 reuse and the two content-fail PDFs after corrected source input. `--max-documents` controls the per-run cap. Values above three require a separate independent `REPORT_CONTENT_PASS` receipt bound to the three actual first-run page-input and report SHA-256 values. The full 2209-entry inventory is not selected by default.

Short documents are analyzed in one request. Longer documents are split into page-numbered source units with exact offsets, capped at 8,000 source characters and 32,768 serialized request-envelope bytes. Each part is retained, then combined through bounded synthesis requests. The original page input remains alongside the report. Every generated report is labeled `MODEL_GENERATED` and `SOURCE_REVIEW_PENDING`; queue `SUCCEEDED` means only that the request and output schema passed. S18 is reused only for its exact PDF SHA and frozen user-acceptance receipt. Its copied report remains byte-identical to the accepted model report; the separate presentation note carries the accepted qualification, and the original raw output is not read or changed.

For each actual model request, the runner reads announcement queue metadata. Same-model `RUNNING`/claimed work defers the PDF batch. A historical `PENDING` count is recorded as advisory and does not block by itself. The PDF queue attempts the shared model lock once inside `SerialAnnouncementQueue.run_next(wait_for_model_slot=False)`; a busy lock defers without an attempt. After an attempted PDF request returns and releases the lock, the process waits at least three seconds before another request. It does not write announcement state.

The runner retries the current document in the same process after only three benign deferrals: announcement priority, the shared model lock being busy, or the two-page source-repair tick budget being exhausted. It persists `WAITING_RETRYABLE_DEFER`, the current document/reason, and the next delay in `run-progress.json`, then uses an interruptible exponential wait from 5 to 60 seconds. A completed wait resets only the source-repair tick budget and resumes that document. Other source, configuration, identity, and request failures remain terminal for that attempt; they are not retried. A TERM signal during a wait records a stopped wait and exits cooperatively.

Pending source inputs are immutable snapshots under each document's `pending-source-inputs/` directory, named by their content SHA-256. Once source repair is complete, the final `page-input.json` is written once and its normalized extraction identity treats a rendered page and a later reuse of that same derived OCR artifact identically. This preserves resume qualification when a process relaunches after a completed repair tick. A relaunch reads the same R3 state root and reuses exact successful results; it does not alter historical R1 queue state.

The batch uses one singleton lock and the isolated R3 state root:

```text
/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/batches/simple-20261018-r3
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
STATE='/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/batches/simple-20261018-r3'
mkdir -p "$STATE/logs"
nohup env PYTHONDONTWRITEBYTECODE=1 "$PY" -m ops.run_pdf_research_batch --manifest "$R/inventory/batch-manifest.json" --max-documents 3 --execute >"$STATE/logs/batch.stdout.log" 2>"$STATE/logs/batch.stderr.log" </dev/null &
printf '%s\n' "$!" >"$STATE/runner.pid"
```

Check the saved PID against the process command before acting on it, then read progress and logs:

```sh
STATE='/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/batches/simple-20261018-r3'
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

`TERM` requests a cooperative stop. A model request already in flight is allowed to return; the runner then persists that request's raw and validated queue artifacts and its current chunk or synthesis receipt before it exits. It does not start another model request or document after the signal. The document and batch receipts use `STOPPED_GRACEFULLY`, and the same manifest/state root can resume unfinished work while reusing exact input-bound R1 results through read-only access. A forced kill cannot provide this persistence guarantee. For a benign defer, the same process waits and retries the current document; a relaunch is needed only after process exit or interruption.

Re-running the same frozen manifest and R3 state root reuses completed document receipts and queue successes, preserves immutable artifacts, and works only unfinished requests. Failed requests have one attempt and remain recorded; the runner does not retry them. A changed manifest requires a new reviewed state root rather than mixing old and new inputs.
