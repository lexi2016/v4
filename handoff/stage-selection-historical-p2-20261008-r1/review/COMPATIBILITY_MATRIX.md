# Historical P2 compatibility matrix — before implementation

**Verdict: date and close-output contracts defined; nested unknown-key P2 deferred for missing authoritative schema inventory.** This is a read-only contract review of the original frozen source and tests, not a review or PASS claim for candidate code. No tests were executed for this matrix; no R1 suite or product/test file was changed.

The authoritative scope is `evidence/README.md:114–118`. All five original source/test files listed in `READ_ONLY_SOURCE_IDENTITIES.json` match the frozen manifest by SHA-256, size and Git blob. The two product SHA-256 values are:

- `infrastructure/preselection_pool_store.py`: `028298a05ea44e310487c1159acc8147cf652e23ba716989135b178198795a92`.
- `ops/build_close_review.py`: `a361ae023285392ddf3b0e9674a9c506fae79252cc02c15df221ae09ba28e5aa`.

## Acceptance matrix

Line references below are to the original files under `baseline/source/canonical`, unless another location is named. Each row is a required focused contract, not an executed result.

| ID | Case | Required behavior | Focused evidence to produce |
|---|---|---|---|
| C01 | Equal-date observation and valid split dates | ACCEPT historical pool validation when each provenance source date is <= target/trade date, including equality. Keep signal/nested/source identity bindings. Do not add a strict D-1 rule or require eligibility date == price date. | Both historical schemas: equality for each source-date field, both equal, and existing split fixture remain valid. |
| C02 | Future provenance dates | REJECT either eligibility_source_date or price_signal_date later than target, even when every nested date, source digest and run binding is otherwise consistent. | One field future at a time for both schemas; use correctly bound payloads so the new upper-bound check is what rejects. Optional target_date absence still has trade_date as bound. |
| C03 | Late capture remains historical recovery | ACCEPT the existing valid timezone-bearing late capture in the historical store; retain HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM and false safety/natural flags. This gives no Stage/PIT acceptance. | Original as-of fixture target 20260930 with capture 2026-10-02T14:02:56+08:00 passes unchanged. Invalid/naive timestamps still reject. Do not modify captured_at. |
| C04 | Known nested required and optional fields | Preserve the current minimum required fields and valid optional fields in exact versioned eligibility_asof and price_recovery objects. Do not derive the full optional allowlist from the minimal fixture. | Minimal original fixture must pass. Any future allowlist must preserve fuller pinned producer/recovery examples and optional omissions. Deferred: full schema/producer bytes are not supplied. |
| C05 | Unknown nested object fields | REJECT an unregistered key in either known versioned nested object. Preserve existing schema/version/date/SHA and false-flag checks. | Deferred pending full schema inventory. Then check unknown scalar, mapping and list fields in each versioned object independently. Unknown top-level provenance remains rejected. |
| C06 | Open source-input digest maps | ACCEPT arbitrary string source names in source_input_sha256; reject empty maps, non-string names and invalid/non-string digest values by the existing hash contract. Do not apply nested object-key allowlists to these data keys. | At least two new source labels with valid digests pass; invalid digest/value/type still rejects. Preserve existing digest formats. |
| C07 | Legacy artifact without historical provenance | Keep generic v1 artifacts readable in their original wire shape; lineage fields remain optional. Absence does not prove historical PIT availability. | Real-store readback equals original payload and artifact/receipt bytes; no injected provenance, capture time, source hash or flags. Existing legacy close-review metrics remain usable. |
| C08 | Missing source evidence in close-review output | Use the existing uncertainty reason when historical_provenance is present OR, with provenance absent, either source_manifest_sha256 or source_receipt_sha256 is missing. Complete nonhistorical SHA pair keeps existing output. | Both missing, each missing independently, complete pair, and historical branch. Marker appears once and survives real ReviewStore readback; unchanged scores, counts, status logic and false safety flags. No date-specific 20260825 branch. |
| C09 | Exact absent-pool sentinel versus corrupt pool | Only FileNotFoundError with filename None and args exactly (hkconnect_d1_top100,) becomes a model-source gap. Other read/parse/contract errors propagate before review publication. | Exact absent pool retains MODEL_0_2_SOURCE_MISSING and 0 model rows plus uncertainty; missing manifest/receipt, bad JSON, wrong receipt or provenance errors never become an empty successful model. |
| C10 | Preserve source artifact, receipt and manifest | Validation and close-review generation do not rewrite source pool bytes, its receipt or its manifest entry. Rejecting a newly disallowed existing artifact leaves the historical evidence intact. | Hash source trio before/after successful reads, marker generation and rejection. Existing idempotent materialization/conflict behavior remains. No recovery or backfill call introduced. |
| C11 | Existing close-review publication contract | The unchanged explicit ReviewStore publication path may create or supersede a synthetic review under its existing expected-SHA contract; it does not authorize rerunning or overwriting actual historical outputs. | Marker persists after publication; current review readback/errors and expected-SHA behavior remain unchanged. Do not require a new publication/store schema or broad archival redesign for this P2. |
| C12 | Evidence limits and downstream gates | Source/test results can demonstrate the missing-evidence class, not restore Aug25/Sep30/Oct7 data or verify natural/PIT execution. Stage validation stays unchanged. | Report all actual data, current-owner integration, Mac, Stage canary, API/UI and natural execution as NOT_RUN/CANNOT_CONFIRM; preserve frozen R1. |

## Exact nested objects and open maps

The original validator requires `eligibility_asof.schema_version`, `source_date` and `captured_at`; it requires `price_recovery.schema_version` and `source_date`. Other fields below are known optional fields at that boundary. The minimal fixture is not a complete producer schema.

| Object | Optional fields directly established in the frozen fixture or consumers |
|---|---|
| `eligibility_asof` | `source_sha256`, `natural_verified`, `production_allowed`, `buy_gate_updated`, `orders_sent`, `source_role`, `validity` |
| `price_recovery` | `source_input_sha256`, `source_sha256`, `natural_verified`, `production_allowed`, `buy_gate_updated`, `orders_sent`, `provider`, `adjustment`, `volume_unit_status` |

Frozen support: `infrastructure/preselection_pool_store.py:190–217, 364–397`; `domains/preselection_materializer.py:195–234`; `tests/test_close_review_producer.py:103–123`. The two subsequently supplied recovery tests do not provide full nested objects. Independent readback of `work/continuation_1325/historical_validation/references/tests/test_hk_expected_missing_recovery.py:22–33` confirms that the test depends on external Mac `ACTIVE_BINDINGS.json`, the original source archive and `local_fix/roots/shared_package`. Those exact schema/producer bytes are not present. **Defer the nested unknown-field implementation and keep that P2 unresolved.** The inventory above is not exhaustive. Date bounds and the output marker have no dependency on this missing inventory.

`source_input_sha256` has open string data keys. The original validator checks every digest and rejects an empty map; it does not freeze labels to `core` (`infrastructure/preselection_pool_store.py:258–278`). Unknown keys in the two versioned object schemas and new source names in a digest map are different contracts.

## Evidence and interpretation

- Date bounds: `infrastructure/preselection_pool_store.py:355–375, 1179–1185`. Normalize and retain existing bindings, then compare each source date with the artifact target/trade date; equality is allowed by the requested “no later than” requirement.
- Late recovery: `tests/test_close_review_producer.py:81–124, 451–452` intentionally accepts capture on October 2 for a September 30 historical target. `ops/build_close_review.py:146–149` marks historical PIT availability uncertain. The separate unchanged Stage test at `tests/test_hk_prior_observation_source_binding.py:532–566` rejects late eligibility capture for Stage use; historical readability does not bypass it.
- Legacy shape: `infrastructure/preselection_pool_store.py:71–92, 301–307` explicitly preserves optional lineage and permits no provenance. The store-backed producer test at `tests/test_close_review_producer.py:369–440` has a valid legacy model pool and tests existing metrics/status. The narrow missing-manifest/receipt marker should add uncertainty without inventing provenance or changing score/status logic.
- Missing versus corrupt: `ops/build_close_review.py:127–138` deliberately catches only the exact absent-pool sentinel. The tests at `tests/test_close_review_producer.py:490–547` require corruption to escape and a true missing pool to remain a model-source gap.
- Preservation: `infrastructure/preselection_pool_store.py:549–601` validates before materialization and rejects conflicting existing bytes. Source-trio hashes should remain unchanged; the explicit close-review publication at `ops/build_close_review.py:150–154` keeps its existing expected-SHA semantics (`tests/test_close_review_producer.py:279–339`).

## Remaining boundaries

Independent after-code review and execution are **NOT_RUN**, pending exact final candidates. Actual August 25 raw/output bytes are not supplied; a matching missing-evidence fixture does not reproduce that day. Mac owner/dependency closure, deployment, historical data repair, Stage canary, API/UI readback, natural execution and comprehensive PIT verification remain **NOT_RUN/CANNOT_CONFIRM**. Frozen R1 stays unchanged.
