"""Full original Stage import/read with a verified, review-only dependency.

The exact recovered execution_evidence.py is selected by a narrowly scoped
import finder. No source function is stubbed; candidate files are untouched.
The original selector/store write only synthetic fixtures in TemporaryDirectory;
every subsequent consumer read must leave fixture bytes unchanged. This is not
Mac execution, an actual D1/membership authority, or natural-run acceptance.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types

REVIEW = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("candidate", type=Path, help="Candidate API source root; read only")
parser.add_argument("--execution-source", type=Path, required=True,
    help="Recovered original execution_evidence.py; Git blob 3af4fb13...")
parser.add_argument("--output-dir", type=Path, default=REVIEW)
args = parser.parse_args()
SOURCE = args.candidate.resolve()
EXECUTION = args.execution_source.resolve()
OUTPUT = args.output_dir.resolve()
if OUTPUT == SOURCE or OUTPUT.is_relative_to(SOURCE):
    raise ValueError("REVIEW_OUTPUT_MUST_BE_OUTSIDE_CANDIDATE")
OUTPUT.mkdir(parents=True, exist_ok=True)
EXECUTION_SHA = "1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b"
EXECUTION_BLOB = "3af4fb13f7da60e0822827fb834c671cef16a372"
sha = lambda raw: hashlib.sha256(raw).hexdigest()
canonical = lambda doc: json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
execution_bytes = EXECUTION.read_bytes()
assert sha(execution_bytes) == EXECUTION_SHA
assert hashlib.sha1(b"blob " + str(len(execution_bytes)).encode() + b"\0" + execution_bytes).hexdigest() == EXECUTION_BLOB


class RecoveredOriginalDependency(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "stage_center.execution_evidence":
            return importlib.util.spec_from_file_location(fullname, EXECUTION)
        return None


sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE))
sys.meta_path.insert(0, RecoveredOriginalDependency())
source_paths = [SOURCE / "stage_center" / name for name in
    ("__init__.py", "consumer.py", "selection.py", "contracts.py", "calendar.py", "acquisition.py")]
source_paths += [SOURCE / "infrastructure/owned_io.py", SOURCE / "infrastructure/interprocess_lock.py",
    SOURCE / "infrastructure/preselection_pool_store.py", EXECUTION,
    SOURCE / "v4/manager_research/workspace_daily_channels.py"]
source_before = {str(path):sha(path.read_bytes()) for path in source_paths}

# Import the actual complete Stage package, including its normal __init__.
import stage_center
from stage_center.consumer import StageSelectionConsumer
from stage_center.selection import SelectionStore, SelectionError, select_hk_four_lane
from stage_center import execution_evidence
assert Path(execution_evidence.__file__).resolve() == EXECUTION.resolve()
assert Path(stage_center.__file__).resolve() == (SOURCE / "stage_center/__init__.py").resolve()
for name, path in (("v4", SOURCE / "v4"), ("v4.manager_research", SOURCE / "v4/manager_research")):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
daily = importlib.import_module("v4.manager_research.workspace_daily_channels")
projection = importlib.import_module("v4.manager_research.workspace_projection")
# Full workspace import is outside this Stage reader test; no plan product is
# supplied, so its optional attempt validation may safely find this absent API.
workspace_module = types.ModuleType("v4.manager_research.workspace")
def no_plan_attempt(*args, **kwargs):
    raise ValueError("SYNTHETIC_STAGE_FIXTURE_HAS_NO_MANAGER_PLAN")
workspace_module.validate_attempt = no_plan_attempt
sys.modules[workspace_module.__name__] = workspace_module

DAY, STAGE = "20261009", "STAGE_0935_0940"
CODES = [f"HK.{index:05d}" for index in range(1, 101)]
D1_SHA = "2" * 64
source_evidence = ["SYNTHETIC_UNIT_FIXTURE_NOT_NATIVE_D1_AUTHORITY",
    "selection_contract=V3_TOP10_RECOMMENDATION", "hk_d1_membership=exact_date_top100",
    "hk_d1_status=STRICT_0_2_READY", "hk_d1_sha256="+D1_SHA, "hk_d1_json_sha256="+D1_SHA]
raw_rows = [dict(code=code, name="SYNTHETIC "+code,
    candidate_lanes=["LIVE_HKCONNECT_GAINER"], platform_circular_market_cap_hkd_yi=80.0,
    offer_float_market_cap_hkd_yi=15.0, pct_chg=4.0, volume_ratio=1.5,
    turnover_hkd_yi=0.2, turnover_rate=3.0, stage_id=STAGE) for code in CODES]
raw_sha = sha(canonical(raw_rows))


def state(root):
    return {str(path.relative_to(root)):sha(path.read_bytes())
            for path in root.rglob("*") if path.is_file()}


def membership_fixture():
    source = dict(source_date=DAY, market="HK_CONNECT", role="HK_CONNECT_FULL_MARKET_AUTHORITY", sha256="a"*64)
    return dict(status="OWNER_VERIFIED", target_trade_date=DAY, codes=CODES,
        source=source, membership_semantics="TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2",
        identity=projection.digest([DAY, CODES, source["sha256"]]), gaps=[],
        calendar_applicability=dict(status="APPLICABLE", target_trade_date=DAY))


def hk_channel(stage):
    membership = membership_fixture()
    value = dict(target_trade_date=DAY,
        date_bindings=dict(plan_date=DAY, selection_date=DAY, announcement_date="20261008"),
        plan_context=dict(plan_trade_date=DAY, research_cutoff="2026-10-09T10:00:00+08:00"),
        selection_diagnostics=dict(membership=membership, status="READY", connect_gaps=[]),
        stage_selection=stage)
    return next(row for row in daily.build_daily_channels(value)["channels"] if row["channel"] == "HK_CONNECT")


def receipt(envelope):
    return dict(schema_version="stage_center.runner.receipt.v1", runner="stage_center",
        trade_date=DAY, stage_id=STAGE, status="READY", dispatch_mode="MANUAL", due_status="DUE",
        recorded_at="2026-10-09T09:40:05+08:00", fixture_only=True,
        markets={"HK_CONNECT":dict(status="READY", write_performed=True,
            requested_rows=100, source_rows=100, selected_rows=envelope["selected_rows"],
            **{key:envelope[key] for key in ("run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256")})},
        production_allowed=False, buy_gate_updated=False, orders_sent=False)


results = []
with tempfile.TemporaryDirectory(prefix="full_stage_r2_", dir=OUTPUT) as temporary:
    root = Path(temporary)
    selection_root, receipt_root = root / "stage/selection", root / "stage/receipts"
    consumer = StageSelectionConsumer(selection_root, execution_receipt_root=receipt_root)
    before = state(root)
    missing = consumer.get(DAY, STAGE, markets=("HK_CONNECT",))
    assert state(root) == before
    assert missing["markets"]["HK_CONNECT"]["status"] == "CANNOT_CONFIRM"
    assert missing["markets"]["HK_CONNECT"]["rows"] == []
    results.append(dict(case="full_import_and_empty_store_read", status="PASS", creates_files=False))

    envelope = select_hk_four_lane(raw_rows, DAY, STAGE, raw_sha,
        requested_rows=100, source_evidence=source_evidence)
    assert envelope["source_rows"] == 100 and envelope["selected_rows"] == 10
    store = SelectionStore(selection_root)
    store.publish(envelope, market="HK_CONNECT")
    before = state(root)
    actual = store.read_verified(DAY, STAGE, "HK_CONNECT")
    assert actual == envelope
    response = consumer.get(DAY, STAGE, markets=("HK_CONNECT",))
    assert state(root) == before
    assert response["markets"]["HK_CONNECT"]["selection_manifest_receipt_verified"] is True
    unbound = hk_channel(response)
    assert unbound["status"] == "PARTIAL" and unbound["candidate_count"] == 10
    results.append(dict(case="actual_selection_store_trio_without_execution_receipt", status="PASS",
        selected_rows=10, hk_status=unbound["status"], consumer_read_changed_files=False))

    execution_receipt = receipt(envelope)
    receipt_path = receipt_root / DAY / STAGE / "receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(canonical(execution_receipt))
    before = state(root)
    response = consumer.get(DAY, STAGE, markets=("HK_CONNECT",))
    market = response["markets"]["HK_CONNECT"]
    assert response["execution_evidence"]["markets"]["HK_CONNECT"]["selection_binding"] == "BOUND_TO_VERIFIED_SELECTION"
    assert [(row["code"], row["rank"]) for row in market["rows"]] == [(row["code"], row["rank"]) for row in envelope["rows"]]
    channel = hk_channel(response)
    assert channel["status"] == "READY" and channel["candidate_count"] == 10
    assert channel["natural_run_verified"] is False
    assert response["execution_evidence"]["natural_verified"] is False
    assert response["write_performed"] is False and state(root) == before
    exact_entry = store._latest()["entries"][store._key(DAY, STAGE, "HK_CONNECT")]
    exact_artifact = selection_root / exact_entry["artifact_relative"]
    traceability = dict(
        scope="SAME_SYNTHETIC_RUN_EXACT_ORIGINAL_STORE_FILES_NO_NATIVE_AUTHORITY_CLAIM",
        input=dict(trade_date=DAY, stage_id=STAGE, market="HK_CONNECT", requested_rows=100,
            raw_rows_count=len(raw_rows), raw_rows_canonical_sha256=raw_sha,
            source_evidence=deepcopy(source_evidence),
            membership_fixture=membership_fixture(),
            membership_fixture_canonical_sha256=sha(canonical(membership_fixture())),
            d1_reference=dict(target_trade_date=DAY, d1_trade_date="20261008",
                asserted_sha256=D1_SHA, asserted_status="STRICT_0_2_READY",
                asserted_membership="exact_date_top100", synthetic_assertion_only=True,
                actual_d1_artifact_provided=False)),
        selection=dict(run_id=envelope["run_id"],
            **{key:envelope[key] for key in ("artifact_id", "algorithm_sha256", "raw_artifact_sha256")},
            source_rows=envelope["source_rows"], selected_rows=envelope["selected_rows"],
            code_rank_order=[{key:row.get(key) for key in ("code", "rank", "order")} for row in envelope["rows"]],
            latest_entry=deepcopy(exact_entry)),
        trio={name:dict(relative_path=str(path.relative_to(selection_root)),
            raw_file_sha256=sha(path.read_bytes()), bytes=path.stat().st_size)
            for name,path in (("artifact",exact_artifact),
                              ("manifest",exact_artifact.with_name("manifest.json")),
                              ("selection_receipt",exact_artifact.with_name("receipt.json")))},
        stage_execution_receipt=dict(relative_path=str(receipt_path.relative_to(receipt_root)),
            raw_file_sha256=sha(receipt_path.read_bytes()), bytes=receipt_path.stat().st_size,
            observed_sha256=response["execution_evidence"]["observed_sha256"],
            selection_binding=response["execution_evidence"]["markets"]["HK_CONNECT"]["selection_binding"]),
        projection=dict(status=channel["status"], candidate_count=channel["candidate_count"],
            input_identity=channel["input_identity"], source_selection=channel["source_selection"],
            natural_run_verified=channel["natural_run_verified"]))
    traceability["trio"]["artifact"].update(owner_verified_sha256=market["selection_artifact_sha256"],
        owner_checksum_basis="RAW_CSV_FILE_BYTES")
    for name,field in (("manifest","selection_manifest_sha256"),
                       ("selection_receipt","selection_receipt_sha256")):
        path = exact_artifact.with_name("manifest.json" if name == "manifest" else "receipt.json")
        traceability["trio"][name].update(owner_verified_sha256=market[field],
            owner_checksum_basis="CANONICAL_JSON_OBJECT_SHA256")
        assert sha(canonical(json.loads(path.read_bytes()))) == market[field]
    assert traceability["trio"]["artifact"]["raw_file_sha256"] == market["selection_artifact_sha256"]
    assert traceability["stage_execution_receipt"]["raw_file_sha256"] == response["execution_evidence"]["observed_sha256"]
    results.append(dict(case="full_consumer_original_store_and_recovered_execution_reader", status="PASS",
        fixture_run_id=envelope["run_id"], selected_rows=10, hk_status=channel["status"],
        original_order_preserved=True, natural_verified=False, consumer_read_changed_files=False))

    changed = deepcopy(execution_receipt)
    changed["markets"]["HK_CONNECT"]["run_id"] = "run-" + "0"*24
    receipt_path.write_bytes(canonical(changed))
    before = state(root)
    response = consumer.get(DAY, STAGE, markets=("HK_CONNECT",))
    assert state(root) == before
    assert response["execution_evidence"]["markets"]["HK_CONNECT"]["selection_binding"] == "SELECTION_IDENTITY_CONFLICT"
    assert hk_channel(response)["status"] == "PARTIAL"
    assert hk_channel(response)["candidate_count"] == 10
    results.append(dict(case="execution_receipt_wrong_run_does_not_erase_real_selection", status="PASS"))
    receipt_path.write_bytes(canonical(execution_receipt))

    entry = store._latest()["entries"][store._key(DAY, STAGE, "HK_CONNECT")]
    artifact_path = selection_root / entry["artifact_relative"]
    for label, path in (("artifact_tamper", artifact_path),
                        ("selection_receipt_tamper", artifact_path.with_name("receipt.json")),
                        ("selection_manifest_tamper", artifact_path.with_name("manifest.json"))):
        original = path.read_bytes()
        path.write_bytes(original + b"SYNTHETIC_CORRUPTION")
        before = state(root)
        response = consumer.get(DAY, STAGE, markets=("HK_CONNECT",))
        assert state(root) == before
        assert response["markets"]["HK_CONNECT"]["status"] == "CANNOT_CONFIRM"
        assert response["markets"]["HK_CONNECT"]["rows"] == []
        assert hk_channel(response)["candidate_count"] is None
        results.append(dict(case=label, status="PASS", bad_lane_rows=0))
        path.write_bytes(original)

    latest_original = store.latest_path.read_bytes()
    latest = json.loads(latest_original)
    latest["entries"][store._key(DAY, STAGE, "HK_CONNECT")]["artifact_sha256"] = "0"*64
    store.latest_path.write_bytes(canonical(latest))
    # The original reader checks manifest/receipt; R1's reused provenance helper
    # also verifies the artifact SHA in the mutable exact-latest pointer.
    assert store.read_verified(DAY, STAGE, "HK_CONNECT") == envelope
    before = state(root)
    response = consumer.get(DAY, STAGE, markets=("HK_CONNECT",))
    assert state(root) == before
    assert response["markets"]["HK_CONNECT"]["status"] == "CANNOT_CONFIRM"
    results.append(dict(case="latest_artifact_sha_conflict_rejected_by_full_consumer", status="PASS"))
    store.latest_path.write_bytes(latest_original)

    recovery_root = root / "recovery_fixture/selection"
    recovery = select_hk_four_lane(raw_rows, DAY, STAGE, raw_sha, requested_rows=100,
        source_evidence=[*source_evidence, "recovery_mode=HISTORICAL_BACKFILL"])
    SelectionStore(recovery_root).publish(recovery, market="HK_CONNECT")
    recovery_consumer = StageSelectionConsumer(recovery_root, execution_receipt_root=receipt_root)
    before = state(root)
    recovery_response = recovery_consumer.get(DAY, STAGE, markets=("HK_CONNECT",))
    assert recovery_response["markets"]["HK_CONNECT"]["selection_manifest_receipt_verified"] is True
    recovery_channel = hk_channel(recovery_response)
    assert recovery_channel["status"] == "CANNOT_CONFIRM" and recovery_channel["candidate_count"] is None
    assert state(root) == before
    results.append(dict(case="verified_recovery_trio_not_ordinary_hk_channel", status="PASS"))

assert not root.exists()
source_after = {str(path):sha(path.read_bytes()) for path in source_paths}
assert source_before == source_after, "A reviewed source changed; rerun on a stable snapshot"
result = dict(evidence_kind="FULL_ORIGINAL_STAGE_IMPORT_AND_SYNTHETIC_STORE_READ",
    candidate_modified=False, full_stage_package_imported=True,
    execution_dependency_route="REVIEW_ONLY_IMPORT_FINDER_FOR_EXACT_RECOVERED_ORIGINAL_FILE",
    recovered_execution_git_blob_sha1=EXECUTION_BLOB,
    recovered_execution_origin_commit="87853ef6c177f0243667b12b9eae8110c1be0f12",
    recovered_execution_origin_path="handoff/stage-research-recovery-20261009-r2/after/api/stage_center/execution_evidence.py",
    input_kind="SYNTHETIC_FIXTURES_NOT_NATIVE_D1_OR_MEMBERSHIP_AUTHORITY",
    original_selector_called_only_for_synthetic_fixture=True,
    original_selection_store_publish_called_only_for_synthetic_fixture=True,
    actual_mac_owner_executed=False, natural_run_verified=False, temporary_fixtures_cleaned=True,
    reviewed_sources_stable=True, full_source_sha256=source_after,
    same_run_traceability=traceability,
    passed=len(results), failed=0, cases=results)
output = OUTPUT / "full_stage_consumer_results_r2.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
