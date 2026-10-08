# Issue #28 · HK split-date binding candidate

## Result and boundary

**The frozen active materializer has two proven defects: it cannot receive separate HK price/eligibility dates, and it discards the shared source's manifest/receipt/split-date provenance.** This delivery backports the already-present canonical projection into that owner's monolithic layout. Two existing production files change. No new producer or scheduler is introduced.

The candidate passes **19 offline synthetic tests**. The unmodified active Stage validator accepts a valid stored trio and continues to reject stale rows, missing provenance and a late eligibility capture. The baseline reproduces the observed missing-provenance failure. This does **not** establish that the real 2026-10-07 price source exists, that its original capture can be reconstructed, or that the active shared source/store/scheduler dependencies support the patch. Those remain **CANNOT_CONFIRM**. This is **not a standalone deployable package**.

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`.

Repository: `lexi2016/v4`; frozen commit: `00524e9050fe212f87911b56eea1c2db719dd94b`. The current source handoff is `handoff/stage-selection-issues-20261008`. Canonical and active-owner source roots remain separate throughout.

## 1. Proven call boundary and root cause

Line references below refer to the immutable `baseline/source` files unless marked candidate. The observation itself is fixed by `evidence/README.md` §3; the raw business artifact was not uploaded and was not inspected in this session.

| Boundary | Frozen evidence | Finding |
|---|---|---|
| Current scheduler identity | `evidence/README.md` §2; `SOURCE_MANIFEST.json` | Observed owner `hk-research-calendar-all-r1-20261007-scheduler`; plist SHA `c478c87e7866fa50154df674ea7cb570197251aaa5da3014b3666e7f22914da2`. The actual plist arguments and executor bytes are absent. |
| Materializer CLI | `active_producer_reference/ops/materialize_scheduled_preselection.py:113–124, 252–263, 280–291` | Only one `signal_date` enters the active entry point. No HK price or eligibility argument exists. The actual runtime value supplied by the scheduler is **CANNOT_CONFIRM**. |
| A/HK forwarding | Same file `165–170, 183–193` | The same `signal_date` is forwarded to both A and HK. This interface cannot represent A signal 9/30 and HK price signal 10/7 while preserving 9/30 Connect eligibility. |
| Original shared-data reader | `active_producer_reference/domains/preselection_materializer.py:402–424` | The existing owner loads `shared_data.hk_0_2` through the configured shared-package root and forwards only `target_date` and `expected_signal_date`. It does not select a second source owner. The active loaded module SHA/root arguments are absent from this handoff. |
| Adapter's output | Same file `441–477` | Row dates are checked against the caller's one signal date; the adapter retains artifact SHA and run id but omits the source manifest/receipt hashes and `historical_provenance`. Its `STRICT_0_2_READY` label therefore does not establish the later Stage date contract. |
| Strict Stage boundary | `active_stage_reference/stage_center/_runner_parts/hk_input_validation.py:127–140, 148–220, 222–235` | The unchanged validator independently resolves prior HK-securities and Connect sessions, verifies the physical trio, requires split-date provenance and matching hashes, validates the eligibility capture's Shanghai date and rejects stale rows. For 10/8 the required dates are 10/7 and 9/30. |

Observed business artifact SHA: `62d7716c51978a8e2b55c8aa423ae72691da1385fb80b97df35da714addee09b`; manifest SHA: `cc476019362896f89b37ca12b0f5d7c606fe188ef3b0a33b7c8224df21aa8de6`; receipt SHA: `1871468dda045659d1786b46576ec6290b92df667bcda7c5b325a62a0af01b28`. The handoff reports 100 unique HK rows all dated 9/30, no historical provenance, and failure before selection. These remain observation references, not fixtures fabricated from the live artifact.

### Canonical support already present

- `canonical/ops/materialize_scheduled_preselection.py:324–350, 557–564, 606–608` already accepts and forwards separate HK dates.
- `canonical/domains/_preselection_materializer_parts/hk_pool.py:44–55, 107–175` already projects verified source hashes and split-date provenance.
- `canonical/upstreams/v3_shared_data/shared_data/hk_0_2.py:1308–1333` loads the eligibility-date security master while scoring the requested price signal date. Its `score_frozen_hk_0_2` filters the panel at or before that signal date and rejects an absent signal date at `983–1012`.
- The same canonical shared module's publisher binds the actual verified security-master identity and encoded capture at `1082–1129`; its reader re-verifies the source trio and compares dates, run, SHA and capture at `1134–1180`.

These canonical files were not overwritten or treated as deployed. The frozen 10/5 canonical scheduler helper also forwards the proper upstream/materializer date arguments (`infrastructure/scheduling/_executor_registry_parts/preselection.py:449–454, 539–553`), but it is not the proven active scheduler source. Earlier `hk-close-hk-calendar-20261007/scheduler` slices show dispatch through `FixedExecutorRegistry`; they do not close the current executor identity gap.

## 2. Minimal per-owner change

Only `active_producer_reference` has a patch. Full after files are under `after/active_producer_reference`; the unified patch is `patches/active_producer_reference.patch`.

| Source path | Before SHA-256 | Candidate SHA-256 |
|---|---|---|
| `domains/preselection_materializer.py` | `f090146f39eaaf1ea5baaa5da60cddc2aefe738be16eb1609f166b643953d84e` | `521a66cd5018806197d99e40f7261f817345d3951761ccc280f89d25a8214110` |
| `ops/materialize_scheduled_preselection.py` | `2aac77c9a995c8e97488be5324e8dd105e19e68a08bfb71cceb2df670aaa5478` | `9ef7d07fa3fafbb8a63637fe80edb2488e795f52a48baf2abaec135468d0acfe` |

The CLI adds only `--hk-signal-date` and `--hk-eligibility-source-date`. Both default to the existing `--signal-date` for old callers. The existing `--trade-date` remains the target; this patch does not add another target-date/cadence policy. Existing A calls still receive their original signal date. Candidate CLI/function wiring is at `ops/materialize_scheduled_preselection.py:113–129, 191–198, 257–267, 293–305`.

The monolithic adapter adds `eligibility_source_date`, forwards it to the existing verified reader only when the two source dates differ, and backports the canonical provenance projection at `domains/preselection_materializer.py:409–574`. Capture decoding preserves the original ISO timestamp, including precision and offset. No current time or replacement capture value is inserted. Missing source provenance or required trio hashes raises an error. No retry with the old date or fallback source is added.

Canonical/source/scoring/model/Stage-validator files are unchanged. The strict active validator SHA remains `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735`. `SHA_MAPPING.json` records the relevant unchanged canonical and historical-close identities. The previously passed historical-close repair is not rewritten.

## 3. Focused verification and limitations

Environment: Linux; CPython **3.14.7** and pytest **9.1.1** provided by `work/test-venv`. Mac Python 3.14.6, actual loaded scheduler/Stage imports and their dependency closure were **NOT_RUN**.

| Probe | Baseline | Candidate |
|---|---|---|
| Four focused compatibility probes | **2 FAIL / 2 PASS** | Included in the 19 PASS suite |
| Split-date adapter and CLI acceptance | FAIL: unsupported keyword / unrecognized HK CLI arguments | PASS |
| Baseline stale 100-row artifact reproduction | PASS: exact `HK D1 split-date eligibility provenance missing` rejection reproduced | Same frozen-baseline regression remains PASS |
| Legacy equal source dates | PASS | PASS; legacy reader receives no new mandatory keyword |
| Full new HK focused suite | Not claimed as a baseline pass | **19 PASS** |

The positive path uses the original frozen canonical HK publisher and security-master publisher with explicitly **synthetic** dated rows in pytest temporary directories, then uses their real verified reader through the actual monolithic materializer, the real frozen canonical pool store and the exact unchanged active strict-validator body. It verifies the complete stored trio and all projected run/SHA/date/capture identities; source bytes remain unchanged after consumption. No market data, model inference, collection or natural execution is tested.

Negative cases cover stale source provenance, tampered source artifact/manifest/receipt, missing verified provenance fields/hashes, missing Stage provenance, stale row dates and wrong eligibility capture dates. The actual CLI is exercised and stores its output through the real store. Only unrelated A/research/baimao factories are substituted by named synthetic test factories; A's original dates and valid-row survival are checked. Canonical HK projection parity is also checked.

The handoff omits the split-module `_namespace.py` import. The test harness removes only that import from an in-memory AST and supplies an explicitly test-only globals adapter. It does not create an authoritative `_namespace.py`. Consequently the result is a **body-level/adapter/CLI integration test using canonical test dependencies**, not proof of the full active application import closure. `test_support` contains 22 exact frozen source files, each SHA/blob-verified in `TEST_SUPPORT_INDEX.json`; they are not deployment payloads.

The existing active error classifier maps a security-master ENOENT wrapped in `StoreError` to `HK_0_2_EXACT_INPUT_CONTRACT_INVALID` while preserving the actual `No such file or directory` reason and a zero-row `CANNOT_CONFIRM` artifact. The test records this behavior; classification is not changed by this date/provenance patch.

Reproduce the candidate from the prepared workspace:

```bash
work/test-venv/bin/python delivery/hk/tests/run_focused.py \
  --issue-root /workspace/scratch/29f34dd56853/issue28 \
  --owner-root /workspace/scratch/29f34dd56853/issue28/delivery/hk/after/active_producer_reference \
  --support-root /workspace/scratch/29f34dd56853/issue28/delivery/hk/test_support
```

For the original four-probe run, point `--owner-root` at `baseline/source/active_producer_reference` and add `--baseline-focus`. `--baseline-root` can identify an equivalent extracted frozen `source` directory. Exact commands, failures and pass counts are retained in `logs/before_focus.log`, `logs/after_focus.log` and `logs/results.json`.

## 4. Required current-owner fetches / source availability

These items are absent as proven current-owner bytes in the frozen tree. Luna Max must read them from the currently bound source roots, record SHA/size/runtime identity and adapt only after proving the match. Historical/canonical copies cannot fill this column.

| Required current-owner item | Why required | Current status |
|---|---|---|
| Scheduler plist argv and its loaded `infrastructure/scheduling/executor_registry.py` plus any delegated preselection helper | Establish actual dates, original source-production invocation and forwarding into this materializer | **CANNOT_CONFIRM** |
| Loaded shared-package root; `shared_data/hk_0_2.py`, producer script and security-master/consumer/store dependency pins | Establish support for `expected_eligibility_source_date`, producer eligibility binding and genuine source verification | **CANNOT_CONFIRM** |
| Active producer and Stage `infrastructure/preselection_pool_store.py` plus its source/reader/transaction dependencies | Establish new optional provenance fields are supported by both actual owners, rather than only the canonical test store | **CANNOT_CONFIRM** |
| Immutable 10/7 price source + its actual run/artifact/manifest/receipt/SHA and original capture witness | Establish the real source session and PIT boundary before materializing a corrected input | **CANNOT_CONFIRM** |
| Immutable 9/30 Connect eligibility source and original capture identity | Establish eligibility is genuinely captured/bound for 9/30 | **CANNOT_CONFIRM** |

The handoff reports that one earlier exact-root search did not locate 10/7 raw source. This is not proof of global nonexistence. No new search of the user's Mac data was performed. No source rows, capture timestamps or provenance were created for the real 10/8 artifact. Any newly acquired historical data would retain its actual acquisition time and would not prove original-slot PIT. The already-known historical-close/PIT P2s remain separate; no complete leakage certification is claimed.

## 5. Luna Max singleton canary — exact steps and NOT_RUN boundary

**All steps in this section are NOT_RUN in this session.** Luna Max is the sole local Writer. A different Reviewer must independently validate the adapted owner hashes and gates before any active-release change. No automatic install, active path replacement or Mac command is part of this delivery.

1. Re-read the current scheduler, producer, shared-data and Stage identities listed above. Check the two exact preimage SHAs before applying the two-file patch to an isolated candidate copy of the actual producer app. If the preimage differs, adapt the hunk against the current owner and obtain a new independent review. Do not overwrite it with canonical files.
2. Trace the current original scheduler/source invocation. Its correct 10/8 contract must be target `20261008`, price signal `20261007`, eligibility source `20260930`, while any A signal remains its own `20260930`. The source producer must itself use both dates; adding fields downstream cannot fix a stale source. Pin and review any necessary caller/upstream/store changes against their actual byte identities. This delivery provides no unproven replacement for those missing owners.
3. Read and verify the immutable real source trios and capture witnesses. If either source fails, keep `CANNOT_CONFIRM` and do not run selection. Do not use `--reuse-formal-pools` to reuse the known stale 10/8 HK artifact. Existing immutable source/artifact history must remain intact; a corrected candidate is written only to a new isolated input root.
4. After those prerequisites, execute the existing owner function once using the following concrete isolated materializer snippet. Each environment variable must be resolved from the reviewed current owner; these are placeholders for verified local paths, not proposed replacements. `HK_CANARY_INPUT_ROOT` is a new isolated root, and `HK_VERIFIED_SHARED_ROOT` is read-only original data. Use the reviewed actual producer interpreter and app root, not `test_support`.

```bash
cd "$HK_CANDIDATE_APP"
PYTHONPATH="$HK_CANDIDATE_APP" "$HK_PRODUCER_PY" - <<'PY'
import hashlib
import json
import os
from pathlib import Path
from domains.preselection_materializer import build_shared_hk_0_2_pool
from infrastructure.preselection_pool_store import PreselectionPoolStore

artifact = build_shared_hk_0_2_pool(
    Path(os.environ["HK_VERIFIED_SHARED_ROOT"]),
    trade_date="20261008",
    signal_date="20261007",
    eligibility_source_date="20260930",
    shared_package_root=Path(os.environ["HK_VERIFIED_SHARED_PACKAGE_ROOT"]),
)
root = Path(os.environ["HK_CANARY_INPUT_ROOT"])
store = PreselectionPoolStore(root)
result = store.materialize(artifact)
snapshot = store.read_pool_snapshot("20261008", "hkconnect_d1_top100")
print(json.dumps({
    "scope": "ISOLATED_MANUAL_CANARY_NOT_NATURAL",
    "stored": result,
    "row_count": len(artifact["rows"]),
    "signal_dates": sorted({row["signal_date"] for row in artifact["rows"]}),
    "historical_provenance": artifact["historical_provenance"],
    "source_run_id": artifact["source_run_id"],
    "source_sha256": artifact["source_sha256"],
    "source_manifest_sha256": artifact["source_manifest_sha256"],
    "source_receipt_sha256": artifact["source_receipt_sha256"],
    "trio_sha256": {name: snapshot[name] for name in (
        "artifact_raw_sha256", "manifest_raw_sha256", "receipt_raw_sha256"
    )},
    "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
}, ensure_ascii=False, sort_keys=True))
PY
```

5. From the independently reviewed **actual Stage app** and its actual interpreter, invoke only its original validator against that isolated trio. This snippet does not start Stage, collect data or select rows:

```bash
cd "$STAGE_BOUND_APP"
PYTHONPATH="$STAGE_BOUND_APP" "$STAGE_OWNER_PY" - <<'PY'
import json
import os
from pathlib import Path
from stage_center.runner import _validate_hk_d1

root = Path(os.environ["HK_CANARY_INPUT_ROOT"])
path, sha256 = _validate_hk_d1(root, "20261008", preselection_source_root=root)
print(json.dumps({"status": "STRICT_INPUT_ACCEPTED", "artifact": str(path), "sha256": sha256}))
PY
```

6. The Reviewer must also repeat the wrong-date, missing-provenance and source-trio tamper rejection cases in isolated roots; confirm all source bytes and the existing 10/8 business artifact are unchanged. A legal zero-selection outcome is meaningful only after input validation and a real selection run/artifact exist.
7. **Real singleton Stage canary remains NOT_RUN.** The current full Stage launcher, one-stage dispatch argv, source/cutoff inputs and singleton receipt/lock must first be resolved locally. This handoff does not supply a fabricated full Stage command. Luna then uses the original Stage owner's existing reviewed one-stage entry, under its singleton guard, with the reviewed isolated input binding and valid source window. Record actual selection run/artifact/manifest/receipt/SHA and execution mode. A late/manual 10/8 replay must remain recovery/replay, never NATURAL.
8. **8873 API/UI readback, integration, deployment and natural-slot validation remain separate NOT_RUN/CANNOT_CONFIRM layers.** After separately approved integration, read back the same Stage run/SHA via the existing 8873 API and original page, and distinguish valid zero rows from input failure. No BUY/model/manager/Vibe8910 change follows from this canary.

## Delivery contents

- `patches/active_producer_reference.patch`: the single actual-owner patch.
- `after/active_producer_reference/`: full after files, preserving the monolithic owner layout.
- `SHA_MAPPING.json`: exact preimages, after identities and unchanged canonical mapping.
- `tests/`: focused test and reproducible driver; the namespace/A-lane adaptations are test-only.
- `test_support/`, `TEST_SUPPORT_INDEX.json`: narrow SHA/blob-verified canonical offline support closure; no live inventory or market data.
- `logs/`: compact before/after results, including the baseline failures.

No GitHub write, active-release change, source collection, Stage tick, original business-data write, API/UI operation or natural-slot run was performed by this HK worker.
