# Issue 32 — Stage / API acceptance findings

Scope: source-only audit of the 24 verified handoff files at commit `b00ca5a658a9de83cf5e54ad39aa68ddd5c23526`, plus the immutable Issue 30 API candidate at `2ead7eb9e9f067b69610d24990bc47f792bc75b4`. No service, live API, market-data, or natural-slot execution was performed. Dates below are the handoff's fixed requirements.

## 1. Current conclusion

**Target `20261009` remains input-blocked.** The handoff records no `entries["20261008"]` security-master entry, a zero-row `EXPECTED_MISSING` HK placeholder, and no exact target scoring-run directory. Price-panel refresh is unconfirmed. A has observed 37 + 186 rows / 216 preliminary distinct keys, not 216 accepted Stage inputs. The two dispatcher receipts report no started workload; their detailed dependency reason is absent. These states come from `HK_READINESS_STATE.json`, `A_POOL_SOURCE_STATE.json`, and `CURRENT_READBACK.json`.

The actual Stage validator should remain strict. A minimal preparation repair must still cross **shared producer → local verified pool → Stage binding → acquisition/selection artifact → API/UI**. A successful preparation command alone closes none of the later gates.

## 2. Exact Stage input contract established by supplied source

Source: `source/actual_stage/stage_center/_runner_parts/hk_input_validation.py`, especially `__validate_hk_d1_body` and `__build_hk_d1_binding_body`; `runner.py::_build_hk_stage_binding` / `_validated_hk_binding_evidence`.

| Contract | `20261009` | Separate historical `20261008` case |
|---|---|---|
| Target / trade date | `20261009` | `20261008` |
| Previous HK securities session / row `signal_date` | `20261008` | `20261007` |
| Previous Connect eligibility session | `20261008` | `20260930` |
| Split-date nested provenance | Stage requires it only if the two calendar dates differ | Required; cannot reuse/relabel the old 9/30 price pool |

For the canonical local-pool path:

- `schema_version="v3_5.preselection_pool.v1"`, physical path `<data-root>/preselection_pools/<target>/hkconnect_d1_top100.json`, and a verified local manifest/receipt snapshot. `PreselectionPoolStore.read_pool_snapshot` supplies the integrity check; its actual implementation is not included.
- `status="STRICT_0_2_READY"`, `market="HK"`, `source_role="SHARED_VERIFIED_HK_0_2"`; the configured-source route also requires `pool_id="hkconnect_d1_top100"` and `producer_id="v3_shared_hk_0_2_consumer_v1"`.
- Envelope safety flags `production_allowed`, `buy_gate_updated`, `orders_sent` must each be the boolean `false`. Exactly 100 object rows; 100 unique `HK.12345`-format symbols; `code` and `symbol`, when both present, agree. Each canonical row has `market="HK"` and the calendar-derived `signal_date`; present row target/trade dates agree with the target. `_hk_selection_codes` additionally reads `code` / `ts_code` / `stock_code`, so a symbol-only producer is insufficient for a complete binding.
- Envelope target/trade identity is checked; optional canonical `target_date` and `stage_selection_eligible` fields are checked when present. The producer should emit explicit target and `stage_selection_eligible=true`, rather than depending on legacy omissions. Present model identifiers must contain `prob_active`.
- Source-root fallback is date-owned: a primary target directory, even incomplete, prevents arbitrary fallback to a different owner's target directory. The exact source resolver and lease must be verified from the actual owner.

For the split-date case, `historical_provenance.schema_version="v4.hk_d1_split_date_provenance.v1"`; exact `price_signal_date` / `eligibility_source_date`; nonempty `eligibility_source_run_id`; 64-lowercase-hex `eligibility_source_artifact_sha256`; and `eligibility_source_captured_at` with an explicit timezone whose Shanghai date equals the eligibility date. `d1_source_run_id`, `d1_source_artifact_sha256`, `d1_source_manifest_sha256`, and `d1_source_receipt_sha256` must equal the local envelope's upstream `source_run_id`, `source_sha256`, `source_manifest_sha256`, and `source_receipt_sha256`. All three upstream hash fields are mandatory in that branch.

**No same-date provenance exemption authorizes stale prices, stale eligibility, malformed supplied provenance, synthetic source SHA, or rewritten capture time.** Same-date Stage acceptance still depends on the actual calendar and verified local snapshot. The supplied helper alone cannot prove the upstream verifier's behavior.

## 3. Keep three different identities separate

| Identity | Source-grounded binding |
|---|---|
| Shared HK producer | `shared_data/hk_0_2.py` publishes a CSV through `SafeRootStore`, role `HK_CONNECT_D1_TOP100_0_2`, stage `D1_PREMARKET`, selected strategy `prob_active`. Its manifest provenance binds signal date, panel SHA, frozen model/oracle SHAs, and verified security-master run/artifact. Exact run layout and receipt fields depend on omitted `shared_data/store.py`, `consumer.py`, and `paths.py`. |
| Local pool | `<data-root>/preselection_pools/20261009/hkconnect_d1_top100.json`, sibling `manifest.json`, and `receipts/hkconnect_d1_top100.json`. Resolver metadata includes `artifact_raw_sha256`, `manifest_raw_sha256`, `receipt_raw_sha256`, physical root and relative paths. Local envelope `source_*` identifies the upstream shared run, not this JSON. |
| Stage universe binding | `status="READY"`, `market="HK_CONNECT"`, target date, `role="HK_CONNECT_D1_TOP100"`, sorted 100 codes, `sha256=<local JSON raw SHA>`, `source_run_id="hk-d1-" + local_sha[:16]`. Evidence: `hk_d1_json=<physical path>`, `hk_d1_sha256=<local SHA>`, `hk_d1_membership=exact_date_top100`; validated evidence adds `hk_d1_binding_sha256`. This synthetic binding ID is not the shared producer's run ID. |

The actual shared producer's `_OUTPUT_FIELDS` contains only `signal_date`, `target_date` and its existing row fields, not the new price/eligibility/split provenance fields. A producer change must explicitly preserve new metadata through serialization and the **existing local consumer**. That conversion implementation is absent; a shared CSV patch cannot prove local JSON fields survive.

The only exact Stage output path supplied is `receipt_root / trade_date / stage_id / "receipt.json"` (`runner.py::_receipt_path`). Raw/selection artifact layouts, result statuses and run/receipt field names are delegated to omitted helpers. Do not invent a verified receipt schema from the facade or historical API fixtures. A valid empty selection still needs an actual verified run/artifact and exact input evidence.

## 4. CLI and minimal missing current evidence

**There is no Stage CLI in the supplied files.** Actual and canonical `stage_center/runner.py` have no `argparse`, `main`, or executable entrypoint; actual ends with `__all__`. `python -m stage_center.runner --trade-date ...` is unsupported. The source exposes `StageCenterRunner(config).tick(trade_date, evaluated_at, stage_id=..., historical_backfill=False, ...)`, but CLI flags must come from the real caller. Do not fabricate evaluated time, use historical backfill as a natural result, reset settled slots, or write live roots for a canary.

Acquire these files from the **actual Stage app root in SOURCE_MANIFEST**, with SHA/mode and relevant sanitized configuration. This is a direct-import list, not a reconstructed deployable closure:

- `stage_center/_runner_parts/{_namespace,configuration,selection_input_validation,row_evidence,slot_lock,slot_execution,tick_planning,runner_receipts,slot_idempotency,a_name_authority,a_candidate_authority,hk_candidate_authority}.py`.
- `stage_center/{end_to_end_deadline,acquisition,candidate_input,calendar,contracts,raw_store,scheduler,selection}.py` and package initializers if nonempty.
- `infrastructure/preselection_pool_store.py` and its actual delegated source/snapshot/lease modules, discovered from that file.
- The actual Stage entrypoint **named by launch argv**, plus sanitized argv, working directory, Python/venv identity and source roots. Do not guess an entrypoint filename. Required config evidence includes candidate acquisition, HK D1 / configured source, raw, selection, receipt, shared-data and Python roots; for the chosen stage also auction/second-filter, research/news, replay and A formal roots as applicable.

Acquire from the actual scheduler/consumer owner: `ops/materialize_scheduled_preselection.py` and the exact producer adapter(s) it imports for `v3_shared_hk_0_2_consumer_v1`; from the shared owner, `shared_data/{consumer,store,paths,allowlist,hashing}.py`. These are necessary to establish the shared-to-local conversion and upstream trios. Further imports should be requested from those current files, not populated from old tests.

Required local-only evidence after preparation: exact master entry and its run/trio/capture identity; `assets/hk_0_2/panel_latest.json` and the pointed manifest/panel digest with 10/8 coverage; exact target shared run trio; local pool trio with row/count/identity validation summary; detailed 17:30 and 18:00 dispatch gate evaluations and actual launch configuration; chosen isolated Stage run/artifact verification and actual loaded source SHA; later, natural-slot receipt. No raw market rows or credentials need be uploaded.

## 5. Concrete Issue 30 same-date API counterexample

Issue 30 `after/apps/api/v35_api/preselection_service.py::_is_exact_configured_hk_pool` requires nested split-date provenance unconditionally. Its call sites are the configured-source HK fallback and bounded legacy SHA-quarantine recovery. The main domain read path is a different dependency and is not certified by this finding.

An isolated execution of that exact pure helper with target `20261009`, signal `20261008`, complete source run/SHA fields, 100 unique rows with ranks 1–100, matching market/date/status fields, and all safety flags false returned **false** when nested provenance was absent. Adding a correctly shaped same-date nested provenance object alone changed the return to **true**. This is a synthetic contract counterexample, not Stage, real-source, or full-app acceptance. Stage's canonical path does not require nested provenance when the calendar dates are equal.

A narrow API repair must establish expected dates with existing API calendar authority, require explicit same-date price/eligibility identity, retain malformed-present and split-date provenance rejection, and retain all pool/row/SHA/safety/identity checks. `contracts.trading_calendar.py` already exists in Issue 30's historical API test closure and exposes `load_market_calendar` / `previous_session`; its live bytes and `market_calendar_2026.json` are still required. Do not import a separate Stage deployment or fabricate calendar authority.

## 6. Issue 30 reuse and exact readback recipe

Reuse its three business files and original integration tooling. Current active app is the integration base; preserve all non-delta manager code. The Issue 30 app before SHA is `90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7`; the service after SHA before any Issue 32 delta is `91eba3ad5d005161d876f9c2f1a69ff51db56f129267cde29394d4581d1a4c95`. Issue 32 service changes need their own after SHA; do not modify the immutable Issue 30 package or reuse its old changeset hash for changed bytes. If current active bytes differ, rebase the minimal changes on the actual app and review the fresh delta.

The existing delta CLI in Issue 30 `PROMPT_FOR_MAC.md` is legitimate: `create_api_module_delta.py --active-api-plist <actual plist> --after-root <reviewed after> --change-set <fresh exact changeset> --output <new evidence path>`. Do not run the old R2 cutover plan against a new candidate. The recorded Mac 218/218 covers portable source regression only; complete app/manager/source canary, deployment, API/UI recovery remain unperformed in `ISSUE30_MAC_STATUS.json`.

The reviewed API source supports these read-only requests; execute only against the intended locally reviewed instance, and keep raw results local:

```bash
curl --fail --silent --show-error 'http://127.0.0.1:8873/api/v3/preselection-pools?date=20261009&limit=200&offset=0'
curl --fail --silent --show-error 'http://127.0.0.1:8873/api/v3/preselection-pools?date=20261009&limit=200&offset=200'
curl --fail --silent --show-error 'http://127.0.0.1:8873/api/v3/stage-center/selection?date=20261009&stage=STAGE_0925&limit=200'
```

Verify requested/selected/trade dates, `market_totals`, full counts, pool/source digests, `input_fingerprint` invariant across pages, quarantine reasons and safety flags against current physical sources. Follow `pagination.next_offset` if more pages remain. A observed 216-key union is a count-only benchmark, not an enforced expected result. HK zero placeholder is not an accepted pool. Reload the same-date UI and verify manager/date/workspace behavior separately. Preserve A/HK lane isolation and research-only operation throughout.

## 7. Bounded API repair and source-test evidence

Implemented only `_is_exact_configured_hk_pool` in `after/source/actual_api/apps/api/v35_api/preselection_service.py`. All module statements outside that named function are AST-identical to Issue 30. Before SHA: `91eba3ad5d005161d876f9c2f1a69ff51db56f129267cde29394d4581d1a4c95`; final after SHA: `cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044`.

Both branches now load the existing API `contracts.trading_calendar` authority and require an open target HK securities session, a known Connect state, and the exact previous securities/Connect dates. The absent-provenance exception additionally requires explicit envelope `price_signal_date == eligibility_source_date == signal_date`. Present provenance retains its source/run/hash checks and additionally requires a parseable ISO capture timestamp with a timezone and Shanghai capture date equal to the eligibility date. Thus a well-shaped nested object cannot authorize stale dates, a wrong capture day, a naive timestamp, or a missing calendar. Contradictory present envelope/row date aliases and code/symbol identities are rejected. No API startup, release, manager, producer or Stage code is changed by this API delta.

Connect closure is not treated as HK securities closure: actual Stage `runner.py:585–604` permits HK observation when securities are open and Connect is known closed, using its prior-Connect binding; canonical `runner.py:1170+` additionally supports a verified exact-target research pool on that date. The API helper therefore requires Connect to be known, while preserving strict previous-date/provenance checks; it does not rebind or alter either Stage implementation. A targeted `20261007` / prices `20261006` / eligibility `20260930` fixture verifies this boundary. Target `20261009` remains the same-date case.

Current Mac `contracts/trading_calendar.py` and its resolved `market_calendar_2026.json` still require SHA/readback before full-app acceptance. The current pool store's field allowlist also needs inspection: the historical Issue 30 test store rejects top-level `price_signal_date` / `eligibility_source_date`, so the new absent-provenance branch's envelope cannot be assumed materializable by the actual current consumer/store. A truthful, calendar-valid nested provenance remains accepted using the existing fields. Test fixtures under `tests/api_support/contracts/` are explicitly historical and must never be copied into the production app: Python SHA `eca22a1e45271df45fc0a3b7cec28cec4e448d1af97b80371cc5c3c1953ec0f1` from Issue 30's verified test closure; JSON SHA `9e2638b69e25495478cecb6ed551713178fcb989a63ebb4ecfd59689615f0acb` from the already supplied Issue 28 calendar. This JSON digest equals the historical Stage calendar's source digest, not a newly observed current-runtime digest.

- Initial RED: `api_same_date_red.xml`, **1 expected failure + 30 passing controls** against unchanged Issue 30 bytes. The intermediate `api_combined_r1` result was 61/61, but review then exposed stale-date/capture bypasses in its present-provenance branch; this checkpoint is superseded.
- Review RED: `api_provenance_review_red.xml`, **8 expected failures + 33 controls passed**: stale dates; wrong, malformed and naive capture times; weekend/unknown-year targets; missing/malformed calendars with present provenance. `api_connect_observation_red.xml` records the additional HK-open/Connect-closed counterexample before removing the excessive target-Connect-open check.
- Frozen replay after the date/capture repair: `work/api_combined_r2/results/preselection/result.json`, **FAIL, 70/71**. All 41 then-current new cases passed; 29/30 old cases passed. The failing old case is `test_primary_a_pool_can_use_only_exact_configured_hk_fallback`: its positive fixture targeted `20261008` but used prices `20260930`, eligibility `20260929`, and capture `20260930`. Its acceptance expectation conflicts with the Issue 32 exact-date requirement. The original failure/log is preserved.
- A separate test-copy correction retains that case's positive fallback assertions and changes only its constructed pool to prices `20261007`, eligibility/capture `20260930`; the shared `_strict_hk_artifact` helper and other test AST are untouched. The first correction attempt additionally supplied top-level date aliases unsupported by the historical store: `api_combined_r3` **FAIL, 71/72**, also preserved. The final correction uses only the existing envelope `signal_date`, nested provenance dates, and row `signal_date`.
- Final GREEN: `work/api_combined_r4/results/preselection/result.json`, **72/72 = 29 unchanged regression cases + 1 corrected date fixture + 42 new helper cases**. No skipped/deselected/xfail, collection, or setup/teardown failures. The existing FastAPI/Starlette test environment emits one acknowledged `StarletteDeprecationWarning` about `httpx`; it is recorded in the log. Adjacent files contain JUnit, metrics, environment and dependencies; `LAYOUT.json` records prepared-file SHAs and test-only additions.
- The fixture-only patch and its reason/SHA record are `evidence/api/legacy_exact_date_fixture.patch` and `.json`. Test file before SHA `d1e605f9f6d4a0a024a4d104f8cd5dddc9fbbe154914ab4eae76107586c5cc75`; corrected test-copy SHA `93e43d4515c8874e83f2066e10912d3a7ebb880f3ace2a9b51f9aaeb397afec5`; patch SHA `7eadb54f472d173971828a4d1763b9f311e467c01d829408f4725d9d66524d48`.
- Combined runs use Issue 30's unchanged `run_tests.py` input verification, layout mapping, clean environment, metrics plugin and `execute_suite` function in fresh Issue 32 directories. The final copy overlays the candidate service, adds the explicit historical calendar JSON to the test runtime, and applies the documented one-case fixture correction. The immutable original Issue 30 package was not modified. Exact pytest argv/cwd are recorded in each `result.json`.

Portable targeted invocation from an Issue 32 package root (using an existing pytest environment):

```bash
python -B -m pytest -q -p no:cacheprovider tests/test_api_same_date.py
```

`ISSUE32_API_SERVICE_SOURCE` can explicitly select a before/after service file for an isolated replay. The new test executes the exact helper AST with the real, SHA-pinned historical calendar module and fixture; it does not substitute a mock producer, start the full app, or certify real input trios. Full current app, manager joint behavior, real-source canary, Stage execution, deployment, UI reload and natural-slot acceptance remain separate pending gates.

The thin `replay_api_regression.py` command reproduces the final 72-case composition without shipping an assembled application. It verifies the immutable Issue 30 runner/input manifest, reuses its input validation, layout mapping, clean environment, metrics and suite executor, verifies the Issue 32 source/fixture SHAs, applies the one-case patch with zero fuzz and exact before/after hashes, and checks that both packages remain unchanged. It requires the existing Python test environment and the standard `patch` utility; the output directory must be new and outside both packages.

```bash
python -B replay_api_regression.py \
  --issue30-package /absolute/fixed-issue30-package \
  --output-root /absolute/new-api-regression-run \
  --python /absolute/existing-test-environment/bin/python
```

An actual wrapper replay passed **72/72**, with the known single Starlette deprecation warning retained. Its new output directory, outside the package, is `../issue32_api_replay_smoke_r1/`; `COMMAND.json`, `LAYOUT.json`, `SUMMARY.json`, and `results/preselection/` record the command, identities and results. This verification does not change the fixed source candidate or any real service/data.
