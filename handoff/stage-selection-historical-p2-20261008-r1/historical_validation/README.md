# Issue #28 historical P2 continuation

## Outcome

The provenance **source-date upper bound** has a three-line isolated candidate and fresh RED → GREEN evidence. Both supported historical schemas now require `eligibility_source_date <= trade_date` and `price_signal_date <= trade_date`. The separate **nested unknown-key P2 remains DEFERRED**: the inspected frozen sources do not supply the complete original nested v1 producer schemas or their actual recovery outputs.

This continuation was prepared only under `work/continuation_1325/historical_validation`. It does not edit `delivery/`, frozen source slices, historical data, the Stage validator, or an active runtime. `DEPLOYED=false`; it provides no new API/UI/natural-run or historical-source verification.

## Exact change and source identity

Baseline commit: `00524e9050fe212f87911b56eea1c2db719dd94b`.

| File | Bytes | SHA256 |
|---|---:|---|
| `before/infrastructure/preselection_pool_store.py` | 56,442 | `028298a05ea44e310487c1159acc8147cf652e23ba716989135b178198795a92` |
| `after/infrastructure/preselection_pool_store.py` | 56,638 | `9f1606a977d36c063d9c650e54b9861947eb7b692e779837852e3831b7814bef` |
| `historical_date_upper_bound.patch` | 565 | `74b1d4fbd7352a25dd2e80f28c855502d0d0d98a62c7c9ba514a83a243565915` |

The before-image is the supplied frozen **canonical** historical pool validator, not a newly established identity for a Mac process. The Git blob is `cd05bfc4d0004cd57b5a94527ae46c4dd47cc04e`. The candidate changes only `_validate_historical_pool_provenance`, after the existing source signal-date binding:

```python
target_date = _date(str(payload["trade_date"]))
if eligibility_date > target_date or signal_date > target_date:
    raise ValueError("historical pool source date exceeds target date")
```

The outer `validate_pool_artifact` already validates `trade_date`; `target_date` remains optional and, when supplied, must equal `trade_date`. Both provenance dates have already passed `_validate_provenance_date`, which requires a real calendar date in canonical `YYYYMMDD` form. Comparing these normalized strings therefore imposes only the documented upper bound. This does not add a trading calendar, a D-1 requirement, or a capture-time cutoff.

The original source-artifact/manifest/receipt hashes, source run/path equality checks, exact top-level provenance schemas, false safety flags, generic legacy shapes, and store transaction logic remain unchanged. The candidate does not construct or re-date any source artifact.

## Contract basis

The original issue evidence, `evidence/README.md` §7, names the missing rule as provenance dates not later than the target day. Source facts below come from frozen files; line numbers refer to the unchanged before-images.

| Existing contract | Frozen source evidence | Candidate behavior |
|---|---|---|
| `trade_date` is the validated pool date; optional `target_date` must match it | `infrastructure/preselection_pool_store.py`, `validate_pool_artifact`, lines 1137–1202 | Uses `trade_date` even when the optional target field is absent |
| Each provenance source date is canonical and bound to the corresponding top-level/nested date | Same file, `_validate_historical_pool_provenance`, lines 301–397 | Adds only the upper bound after those date bindings |
| Source prices and Connect eligibility can have different dates | `tests/test_close_review_producer.py`, `_historical_split_pool_payload`, lines 27–78: target `20261007`, price `20261006`, eligibility `20260930` | Original split fixture still materializes and reads back |
| Historical recovery may be captured after the target date and remain unverified | Same test file, `_historical_asof_pool_payload`, lines 81–132: target `20260930`, capture `2026-10-02T14:02:56+08:00`, `natural_verified=False` | Exact timestamp and false flags remain accepted and unchanged |
| Historical provenance is optional for generic older pool shapes | Pool validator's early return when `historical_provenance` is absent | No new provenance requirement for generic legacy artifacts |
| `source_input_sha256` can be a nonempty map of arbitrary string labels to SHA256 digests | Same validator, `_validate_embedded_sha256_fields`, lines 257–278 | No label allowlist; dynamic labels remain accepted |

The source paths are recorded in `READ_ONLY_SOURCE_IDENTITIES.json`; portable copies needed for execution are pinned in `SOURCE_IDENTITIES.json`. The fixture/test source SHA256 is `c2501b342755bfa97064ceae1a8df0c936f912c9a635fc88c059d660d62b655f`.

## Fresh verification

| Suite | Frozen before-image | Date candidate | Interpretation |
|---|---|---|---|
| Date and compatibility suite | **5 FAIL / 8 PASS** | **13 PASS** | Five original failures are `DID NOT RAISE`, proving the missing source-date boundary |
| Separate nested-object probes | **2 FAIL** | **2 FAIL** | **DEFERRED_P2**, reproduced in both versions; no nested-key fix claimed |

No test is skipped or marked `xfail`. The nested probes remain rejection assertions and are not converted into acceptance tests. The runner reports the actual pytest exit codes, failure names, source SHA, and separate classification for each invocation. Runner exit zero means all explicitly expected outcomes were observed; it does **not** mean the deferred nested requirement passed.

The five date regressions cover future price and eligibility dates in both historical schemas, plus a future source date when `target_date` is omitted. Each calls the real `PreselectionPoolStore.materialize` and checks that rejection creates no pool JSON artifacts. The eight compatibility cases exercise the unchanged original historical contract test, equality with the target date in both schemas, the original late recovery capture, generic provenance-free legacy data, known optional consumer metadata, arbitrary input-hash labels, and a valid historical pool without the optional target field. Accepted cases use real store materialization and read-back.

`frozen_fixtures.py` checks the full frozen test file hash, then executes the two original fixture functions and the original historical validator test **unchanged** through AST selection. This avoids importing unrelated Stage/API modules; no pool validator or I/O component is stubbed. `conftest.py` verifies the actual imported validator path equals the chosen before/after path.

Test environment: Python **3.14.7**, pytest **9.1.1**, Linux **6.18.44 x86_64 / glibc 2.39**. The interpreter used here was `/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python`. The runner uses its executing interpreter and bundled support, so it can be moved as a directory and rerun with another compatible Python environment containing pytest.

From any working directory, rerun the complete evidence sequence:

```bash
/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python -B \
  /workspace/scratch/25c09a595aec/issue28/work/continuation_1325/historical_validation/run_validation.py \
  --mode all \
  --log-dir /workspace/scratch/25c09a595aec/issue28/work/continuation_1325/historical_validation/logs/replay
```

For a relocated copy, run `python -B /path/to/historical_validation/run_validation.py --mode all --log-dir /path/to/logs`. `--mode after` runs only the date/compatibility suite; `--mode nested_after` reproduces the unresolved nested P2 separately. The final recorded run is under `logs/final/`, with `RESULTS.json`, plaintext logs, and JUnit XML.

This is a focused offline verification of the supplied source slice. The original repository/application suite and the Mac recovery integration tests were not executed. The pinned handoff is explicitly a source-slice package, and the recovery tests require external actual-source bindings and archives that are absent here. These results do not replace the prior historical canary, source-capture, or runtime checks.

## Deferred nested unknown-key P2

The frozen validator enforces the two top-level historical provenance key sets. For nested `eligibility_asof` and `price_recovery`, it checks schema/date binding, an eligibility timestamp, safety flags, and embedded hashes. It currently accepts `unregistered_extension` in either nested object. The two probes preserve the issue's rejected-unknown-field expectation and demonstrate that behavior through actual store materialization.

A complete compatibility-preserving nested allowlist is not established by the available producer evidence:

* Frozen `domains/preselection_materializer.py` decodes `eligibility_asof_hex` and `price_history_recovery_hex` from an existing verified manifest and copies each entire decoded mapping into the pool provenance. Its consumer checks mention `validity`, `provider`, `adjustment`, and `volume_unit_status`; the recovery store also reads eligibility `source_role`. These accesses are not a complete schema declaration.
* The minimal original test fixture omits some of those known producer metadata fields. Turning its keys into the full required or permitted set would therefore be incompatible with existing consumers.
* The supplied canonical `shared_data/hk_0_2.py` does not contain either nested recovery schema or the two hex provenance fields. Its supplied reader signature also does not establish the external recovery reader with `eligibility_universe_root` used by the wrapper.
* Targeted, fresh-fetched frozen `hk_d1_evidence.py` and `hk_daily_supplement.py` contain other HK schemas, but neither nested recovery schema. This is a bounded search result, not a claim that every possible source was searched.

The following additional references were fetched by Git blob and verified against the fixed commit tree:

| Canonical reference | Git blob | SHA256 |
|---|---|---|
| `shared_data/hk_d1_evidence.py` | `7d53e2dce47b1f33d627eac79d26b7ccef6612c9` | `08c499732300a0e6026cda7ec7c2257807c542cd989f90a9427285dc34b73850` |
| `shared_data/hk_daily_supplement.py` | `4f215a304c55987ccd2e8ef3755232b4aa9fc477` | `fa7dcbce4ee026b0a02c47220820d0407af183553d3304afcc5db425dce33cbd` |
| `tests/test_hk_expected_missing_recovery.py` | `b5ef9b68a31fa3c471e5bbd836d27cf1b615c357` | `6f419e5b0457233ad587b6455ebb12594c807073d92129c046341518b7d0ebab` |
| `tests/test_hk_settled_pool_recovery_20261002.py` | `ebe8e1e1e4882e577f1e765f2eca67f283cdcce1` | `36932ae677b7117bc42926a5bb14dce98f9a76d77fa9f1d62bedd0623a5f43ca` |

The shared-data references reside in the commit under `handoff/v4-running-source-20261005/canonical/upstreams/v3_shared_data/shared_data/`; the tests reside under that canonical root's `tests/`. Full paths are in the identity manifest.

### Exact missing original contract/output dependencies

`test_hk_expected_missing_recovery.py`, lines 21–35 and its `_seed_exact_source_day`, requires these original external bindings; the test does not embed their contents:

* `RECOVERY_ROOT = /Users/lexi/Desktop/学习/agents调试/v4_hk_history_r5_acceptance_20261002`.
* `RECOVERY_ROOT/api_integration/ACTIVE_BINDINGS.json`, whose `environment_bindings.V35_PRESELECTION_SOURCE_ROOT` defines `SOURCE_ROOT`.
* `RECOVERY_ROOT/local_fix/roots/shared_package`, the bound recovery shared-package source needed to establish the complete emitters/contracts for `v4.hk_eligibility_asof.v1` and `v4.hk_history_price_recovery.v1`, including required and optional metadata keys.
* The original `SOURCE_ROOT/preselection_pools/20260930` and its `SOURCE_ROOT/preselection_revisions/20260930/hkconnect_d1_top100` archive, plus the verified shared manifests/nested objects used to create the recovery artifact. The test pins successor artifact SHA256 `f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901`; those actual bytes were not supplied in this continuation.
* The test's shared data root is `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data`, with the corresponding `v3_shared_data` eligibility root. Their original, identity-bound recovery source bytes are required; no local observation of these Mac paths is claimed.

The second test similarly reads `STAGE_RECOVERY_EVIDENCE_ROOT/pool_fixture/data` and other externally bound evidence. It supplies no nested v1 producer schema. Its full integration flow was not run.

Until the original emitters/schema and representative actual recovery outputs are available, the nested-key P2 remains **DEFERRED_PENDING_ORIGINAL_PRODUCER_SCHEMA_AND_OUTPUTS**. The open input-name-to-digest map must continue to permit arbitrary valid string input labels; those are data keys, not a nested object schema to freeze.

## Packaging boundary

`DELIVERY_FILES.json` provides an explicit relative-path allowlist for the parent handoff. It includes code, pinned source references, test definitions, identity records, this report, and final logs/XML/summary only. Do not include `logs/*-tmp`, caches, or any synthetic pool, receipt, or manifest generated by pytest. No business artifacts are part of this continuation's deliverable.
