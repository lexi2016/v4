# US mapping candidate repair — 2026-10-09

## Result and source identity

Two reproducible connection defects are repaired in the isolated candidate. Before independent review, the focused synthetic run passed **68 tests, 0 failures, 1 existing Starlette TestClient deprecation warning** (10 new cases and 58 existing cases). Independent review then found an artifact/run diagnostic pairing gap. After that narrow fix, the final requested rerun passed **12 tests, 0 failures, 1 existing warning**: all 11 permanent new parameter cases plus the independent boundary probe. The earlier 68-test output remains preserved and is identified as preceding that final validation tightening. The test result is not live API/UI or natural scheduler acceptance.

The source root is `/workspace/scratch/21926b793c00/three_channel/app`. Its local assembly baseline is `7ca0190a721a7fd0fc0c88b79a872889867d111f`, assembled from fixed `lexi2016/v4` problem package commit `b19eb112bd641ca97cac1246af7c81d8873641f4` plus its exact frozen R3 candidate API after files. The frozen candidate identity is `ca01c4d0260fecf7aae3c89e96899f36901bf8f7`; it is not evidence of a deployed service. The changed API/dispatch before SHA values match the package's `candidate_after` entries in `source_index.json`.

`manifest.json` contains the US workstream's exact before/after SHA-256 values and file lengths. The integrated delivery's complete source and patches are governed by [source_manifest.json](../source_manifest.json) and [patches](../patches); workstream after/patch duplicates are not shipped. `diff_check.log` records `git diff --check` exit 0.

## Proven connection and specific fixes

### 1. Existing manual action did not prepare daily mapping

The existing page action invokes `POST /api/v4/manager/research/workspace/refresh`. The frozen API route called only `ManagerResearchJobService.refresh_workspace_plan`. That owner consumed an existing saved daily mapping through `workspace._daily_mapping_plan_reference`, but did not run the daily mapping owner. Therefore an exact-session source could be present and the explicit action could create a current plan while the US daily result remained `NOT_RUN`.

The new regression used a temporary original `ResearchPeripheralStore` containing an explicitly synthetic 20261008 POST_CLOSE source with the unchanged fixed 33-symbol universe. Before the fix, the real POST returned daily `NOT_RUN`; the expected legitimate zero assessment was `VALID_EMPTY` (03/04 RED logs). No daily result was fabricated by the test.

The API action now invokes the original `refresh_us_mapping_research` owner with the existing five-second budget, server-owned MANUAL execution context and server-generated trigger. It validates the original owner result's schema, target, status and safety flags; a result with a run is independently read through the original immutable run validator before it can be reported. The plan action obtains a fresh server clock after US preparation, allowing the newly published daily artifact to precede or equal the plan cutoff. Reusing the click's initial cutoff would exclude that new artifact as after-cutoff.

Normal missing input, timeout and busy results remain in the original owner's own run/attempt records. Timeout/busy uses the already-existing internal reader bypass contract to let the original independent plan lanes finish without reentering a blocked reader. No router-side attempt/product is persisted. Unexpected owner RuntimeError or ImportError remains visible as a compact, bounded, same-target `us_mapping_preparation` FAILED response diagnostic, with exception class only, while the independent plan proceeds. Future-target manual plan creation retains its original behavior and reports `FUTURE_TARGET_NOT_DUE` without running the US daily owner.

The new response diagnostic is not an owner receipt and is not the saved plan authority. Canonical GET continues to read the original persisted mapping/attempt and saved plan. GET was byte-checked before/after and did not write state.

### 2. One morning US trigger hid later source arrival

`execute_bound_daily_cycle` assigned all admitted morning slots the same US phase identifier `MORNING_US`, while the plan trigger already identified each admitted slot. `persist_daily_run` deliberately treats a terminal trigger as immutable and replays it. A 07:00 `INPUT_MISSING` result therefore remained the US result at 07:05 even after the original source appeared.

The new real-code dispatch regression proves the sequence: original owner at 07:00 produces `INPUT_MISSING`; synthetic source is published into that same temporary source owner; same-slot replay stays byte-identical; at the next existing admitted 07:05 slot the frozen code still returns `INPUT_MISSING` (03/04 RED logs).

The phase identifier now includes the already-admitted morning slot: `MORNING_US:<slot>`. Repeated calls in one slot still replay the same immutable US and plan receipts. A later admitted slot can read newly available inputs through the original owner and materialize a plan consuming its exact run/SHA. No schedule file, slot list, interval, dispatch window or retry threshold was changed. PREOPEN continues to skip the US mutating owner; the legacy independent scheduled plan endpoint also retains its existing no-US-dispatch behavior.

## Actual owner chain exercised

Existing worker/cycle daily dispatch → bound daily API admission → `execute_bound_daily_cycle` → bounded `ManagerResearchJobService.refresh_us_mapping_research` → actual `build_daily_run` / exact-session bridge → original immutable daily run + latest pointer + dispatch terminal → original plan owner → `workspace._daily_mapping_plan_reference` → canonical workspace GET.

The manual path now connects the existing page's plan action to the same original daily owner before continuing through the same plan/persisted GET consumer. No second mapping producer, source acquisition path, synthetic runtime registry, rank change or selection-threshold change was introduced.

## Verification and preserved failures

All commands, environment overrides, actual exits and output are recorded under matching `.json` / `.log` names.

- `01_red_unscoped`: direct native-style pytest invocation failed collection because the supplied scoped source closure lacks `ops.daily_materialize`, reached by eager scheduling package initialization. This is not a regression result. Parent confirmed the file exists elsewhere in fixed b19, but no unrelated closure was expanded.
- `02_red_scoped`: two intended manual-action failures plus a test assertion comparing ephemeral read metrics; the latter test-only comparison was corrected before any runtime fix.
- `03_red_scoped`: three intended failures: manual complete source still NOT_RUN; manual missing source still NOT_RUN; next morning slot still INPUT_MISSING.
- `04_red_scoped`: four failures / one pass before runtime edits, adding missing failure diagnostic and preserving already-valid future-plan behavior.
- `05_green_scoped`: five core cases passed after the two initial runtime changes.
- `06_diagnostic_red_scoped`: test collection error from pytest's reserved `request` parameter name; corrected and preserved, with no claim of a meaningful RED from that attempt.
- `07_diagnostic_red_scoped`: one intended failure / eight pass; an unbounded owner diagnostic was copied into the new summary. The route now rejects that diagnostic contract.
- `08_green_scoped`: nine cases passed, including real five-second timeout, source gaps and mutation rejection boundaries.
- `09_existing_scoped`: 56 pass / one failure in `test_admitted_morning_slot_survives_minute_rollover_after_us_preparation`. The original test-only `r3_scoped_loader` registered the namespace in sys.modules but not its normal parent attribute, preventing pytest string monkeypatch resolution. No production behavior was involved.
- `10_final_scoped`: 67 pass after explicitly linking those namespace parent attributes in the test command.
- `11_import_error_red`: one intended ImportError isolation failure / one RuntimeError pass; extended the original-owner exception boundary to retain independent plan completion when the US import is unavailable.
- `12_final_scoped`: **68 pass**, zero failures, one pre-existing deprecation warning. This precedes the independent artifact/run diagnostic pairing fix.
- `13_artifact_boundary_red`: **2 failures / 1 pass**. Both the independent probe and the newly retained permanent artifact-field variant reproduced arbitrary artifact text copied from a failed owner DTO with no run.
- `14_boundary_final_green`: **12 pass**, zero failures, one existing warning. This covers all 11 permanent new parameter cases and the independent US probe, on the final code SHA set in the manifest.

The final runner uses the existing test-only scoped loader plus explicit `v4.manager_research` / `infrastructure.scheduling` parent links. Every exercised target body is the actual supplied source. The loader creates no missing implementation. It excludes unrelated eager package initialization, so it must not be presented as complete native Mac application import verification.

### New cases cover

- Explicit plan POST with complete synthetic 33/33 source gives legitimate zero `VALID_EMPTY`, four reviewed symbols, zero US/HK matches and `full_market_coverage=false`.
- The plan consumes the exact daily run/SHA, remains CURRENT, and canonical GET returns the same plan and daily identities without writing files.
- Missing US input keeps match counts unknown, records INPUT_MISSING and still persists the original partial plan.
- Unexpected RuntimeError and ImportError remain sanitized visible failures while the independent plan materializes.
- Future-target plan behavior and PREOPEN restriction are preserved.
- Unbounded owner diagnostics are rejected; source bodies are not copied into the new diagnostic.
- A real blocked source reader times out within the original five-second budget; an immediate second action reports busy; neither plan reenters it and abandoned work cannot publish late.
- Cross-origin and client-body mutations are rejected before either owner executes.
- Same-slot dispatch is immutable; the next admitted morning slot recovers when the original source arrives.

The focused existing cases additionally cover independent plan RPC restrictions, exact page bindings, morning minute rollover, cross-instance dispatch serialization, saved-run recovery, same-trigger replay, input-equivalent deduplication, US DTO failure isolation and date-distinct positive synthetic matches.

## Explicit limits and CANNOT_CONFIRM

The package reports a historical isolated 20261008 source owner run `a95450cd4b264fb6840308d7d2681cf6`, product SHA `2ac764fa1d5b691c6db518ff35b278f89cceeedd3614549a6741d4e8987bfa67`, status VALID_EMPTY, 33/33 coverage, four reviewed symbols, zero US/HK matches and no full-market coverage. It separately reports 17:23 live daily NOT_RUN and plan NOT_MATERIALIZED. These isolated facts are retained. Neither the package nor these synthetic tests prove the historical first trigger/dispatch break or prove the observed binding mismatch caused that live result: **CANNOT_CONFIRM**.

The actual `us_mapping_reviewed_20260930.json` and `us_mapping_relation_registry.json` runtime artifacts are not in the provided package or fixed b19 source tree. They were not invented or replaced in runtime code. Tests point the original JSON validators at explicitly synthetic temporary files. Replay using the original relation artifacts and the historical owner product remains **CANNOT_CONFIRM / NOT_PROVIDED**.

The complete Mac app import/test run without the scoped loader is **NOT_RUN**. The full repository suite is **NOT_RUN** under the user's synthetic-only/limited-scope instruction. Live API/UI reload/readback, service deployment/restart, schedule updates, real announcement imports, market acquisition, trading and natural scheduler-period acceptance are **NOT_RUN**. This workstream performed no GitHub mutation; the integrated package's later transport is recorded separately in the ZIP's top-level REMOTE_READBACK.json.

The US algorithm and bridge source files are byte-identical to baseline. Their exact hashes, along with unchanged workspace/service/autorun files, are recorded in the manifest. All four research-only safety flags remain unchanged.

## Independent review follow-up — artifact/run pairing

Independent review found that a failed owner DTO with `run_id=None` could still supply an arbitrary non-null `artifact_sha256`, which the compact response diagnostic copied. Its original RED is retained in `../independent_review/boundary_checks.log`; the permanent regression variant and repeated independent RED are also retained in `13_artifact_boundary_red.log`.

The router now requires a null artifact when no run exists. When a run is supplied, its ID must follow the original 32-lowercase-hex run contract and its artifact must be a 64-lowercase-hex SHA before the existing exact immutable readback. Invalid identity pairs produce the sanitized FAILED preparation diagnostic with null run/artifact while the independent plan still materializes. This follow-up changes no other runtime behavior or owner. The original 10 new cases, the new permanent artifact-field variant, and the independent probe all passed in `14_boundary_final_green.log`.
