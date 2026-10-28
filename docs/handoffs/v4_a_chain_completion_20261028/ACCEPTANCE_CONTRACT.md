# Offline A-stage acceptance preparation

This checker prepares evidence review. It never calls an API, reads a path embedded in a response, starts a provider, writes market data, changes a claim or certifies a live stage. No previously accepted close/native source or test is changed.

Run with the verified absolute PANEL_PYTHON:

```sh
PYTHONDONTWRITEBYTECODE=1 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' acceptance/a_chain_stage_acceptance.py --trade-date 20261028 --input-dir /explicit/offline/captures --output-json /explicit/offline/report.json
```

The input directory contains one captured JSON response named `<STAGE_ID>.json` for each applicable A stage. The output filename is required and its parent must already exist. Exit0 means a report was written; it never means an A stage passed. The Python function is `check_a_chain(trade_date, captures_by_stage)`.

Supported captured shape is exactly `schema_version=stage_center.selection_consumer.v1`, with exact `trade_date`, `stage_id`, integer `selected_a_rows`, and `markets.A.rows`. Aliases `/api/v3` and `/api/v4` do not change the payload schema. Summary matrices and HTTP statuses are not selection evidence. Unknown shapes remain CANNOT_CONFIRM, with explicit reasons; they are not guessed into a supported shape.

For a captured A row contract to report `ROW_RESULT_PRESENT_VERIFIED`:

- There must be1–10 distinct canonical `A.######` codes and an exact count match. Any row date/stage declaration must agree with the requested identity.
- The market explicitly declares `selection_manifest_receipt_verified=true`. `execution_evidence.selection_artifact_bindings.A_SHARE.status` must be `BOUND_TO_VERIFIED_SELECTION_TRIO`.
- The response and outer `execution_evidence` carry the exact date/stage. `markets.A.market` is `A_SHARE`. Optional date/stage/market scope declarations on the market, execution lane, nested identity or binding cannot contradict those owners; optional outer market declarations also cannot contradict A scope.
- `markets.A` and `execution_evidence.markets.A_SHARE.declared_identity` agree on nonempty `artifact_id`, `run_id`, valid64-digit `algorithm_sha256` and `raw_artifact_sha256`. Direct execution-lane or binding identity fields, if present, cannot conflict. The owning v1 API does not require these identities to be repeated directly on the execution lane or binding.
- The binding's `run_id` matches the market identity and contains only a safe single path segment. Its three relative paths must exactly equal `selection_runs/{date}/A_SHARE_SELECTION_{stage}/{run}/artifact.csv`, `.../manifest.json`, `.../receipt.json`. No embedded path is read; absolute, traversing or cross-date/market/stage/run paths fail.
- The binding has valid `artifact_bytes_sha256`, `manifest_bytes_sha256`, `receipt_bytes_sha256`, `manifest_canonical_sha256`, `receipt_canonical_sha256`. Market `selection_artifact_sha256` matches artifact bytes; market `selection_manifest_sha256` and `selection_receipt_sha256` match the respective **canonical JSON** hashes. Canonical and serialized JSON byte hashes are deliberately distinct. Matching optional byte/canonical fields in market/execution declarations cannot conflict. Any declared market/execution/binding `selected_rows` must be an integer (never bool/string/float) equal to the actual A count.
- Top-level `production_allowed`, `buy_gate_updated`, `orders_sent` are explicitly false. Any nested occurrence of those fields is also false; an explicit `RESEARCH_ONLY` must be true. Missing top-level flags and true/string-valued flags fail closed.

This verifies consistency of the **captured API's explicit declarations**, not the actual artifact bytes. It performs no local trio rehash or whole-ledger authentication. The supported layout is the known owning R7 v1 API: outer execution scope, nested lane `declared_identity`, and path/hash binding returned by `_selection_trio_binding`. It is grounded in the parent's read-only owning-source evidence and synthetic `OWNING_SCHEMA_REPRO.json`. Unsupported shapes are not guessed into this layout.

Result presence, business quality and execution proof are separate:

- Rows can satisfy the captured row contract and remain `BUSINESS_PARTIAL`. All `cannot_confirm` lists are retained with their JSON paths; malformed gap values are retained and invalidate the row contract. Market statuses other than READY and missing/nonfinite score fields remain explicit business gaps. Every A-row declaration of `status`, `selection_status`, `source_status`, or `source_health` is retained with its row index/code/field/value. Any declared value other than READY (including null/unknown/partial) remains a business gap even if the market summary is READY. Absent optional row status fields are not invented. Research quality/news/bonus fields are checked for the six research stages;09:25 uses its separate auction/native contract.
- Execution/natural flags are preserved as declarations. The frozen API shape does not supply an authenticated owning-receipt proof contract, so this version always reports execution receipt inspection as unverified and `natural_verified=false`, even if API booleans say true.
- Historical/replay/afterfact modes, corresponding source-evidence markers, and explicit timestamps after the exact stage cutoff are reported as `RECOVERY_ONLY`. Missing timestamps and timestamps without a timezone remain explicit unknowns. File mtimes, row counts, HTTP200 and reader PASS never supply timing proof.
-09:25 additionally requires parent review of the owning native raw/manifest/capture-window receipt binding after shared read-only access resumes. Captured rows or a naked native provenance string do not satisfy it.

The applicable stages are09:25,09:35,09:40,09:45,10:30,13:15 and15:00, with their original exact cutoffs encoded in the checker. `STAGE_1545_1555` is always `NOT_APPLICABLE/HK_ONLY_BY_CONTRACT`, never a missing A stage. A-close1605 is a separate pending appendix and cannot close the intraday chain.

Focused fixtures are synthetic and certify no actual stock, stage, model or financial result. Tests cover HK-only false positives; ten verified rows with business gaps; wrong date/stage/raw/trio/safety; duplicates and cap; recovery timing; missing native09:25 proof; unknown schemas and timestamps;1555N/A; and the explicit-file CLI. Test temporary files are confined to this owned docs directory and removed by TemporaryDirectory.

Verification command: `PYTHONDONTWRITEBYTECODE=1 <absolute PANEL_PYTHON> -m unittest discover -s tests -p test_a_chain_stage_acceptance.py -v`. First implementation:11 tests passed, followed by independent review FAIL with two component-level findings (retained in OFFLINE_REVIEW_FAIL_R1.json). The bounded repair adds three direct `review_r1` tests: execution count mismatch/type rejection, row-level status gaps despite READY summaries, and a READY-row control. The same command with `-k review_r1` first reproduced10 failing subcases and then passed all3 tests after the repair; prior11 unchanged checks are reused. Independent repair review is pending.

The parent then supplied direct owning-schema evidence: the first checker incorrectly required date/stage/artifact/raw identities to repeat on binding objects that do not contain them. Four synthetic `owning_v1` tests cover the actual layout, cross-scope/raw contradictions, exact safe relative paths, and canonical-versus-byte JSON hashes. Before correction the two positive tests failed, reproducing the false rejection. After correction nine directly affected tests passed (four owning-layout, three R1 regressions, existing identity/safety rejection and verified-partial-row checks). The common synthetic fixture now uses the known owning shape. Unrelated old suites were not rerun; earlier results remain historical evidence and are not claimed as a fresh full-suite run on this layout.

The delivered OFFLINE_ACCEPTANCE_RESULT.json deliberately uses no actual stage captures: all seven A stages remain CANNOT_CONFIRM,1555isN/A, and live/natural certification stays false. It records source hashes and this synthetic test scope. No active API was queried or captured for this work.

Pending shared steps after parent coordination permits them: capture all seven actual A responses through the existing owner; retain source date/stage/SHA and real capture clock; independently read and bind original raw/selection trios and owning execution/native receipts; inspect business gaps; then perform the existing live API/UI and natural-stage acceptance. This offline preparation never marks those pending steps complete.
