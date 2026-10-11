"""Independent synthetic artifact tests through the unchanged sidecar reader.

No collector or publication owner is invoked. Only fixture JSON/Parquet files
inside this review directory are written. The actual native calendar, sidecar
reader, its path/SHA/time/session/raw-decode gates, and workspace sidecar adapter
are retained. Panel/master witness injection is an explicit synthetic boundary;
these results do not attest real market input, a live owner, or a natural run.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import tempfile
import types

import pandas as pd

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("candidate", type=Path, help="Candidate API source root; read only")
parser.add_argument("--reference-sidecar", type=Path, required=True,
    help="Verified original final_20261010 hk_daily_supplement.py")
parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
args = parser.parse_args()
SOURCE_ROOT = args.candidate.resolve()
REFERENCE = args.reference_sidecar.resolve()
OUTPUT = args.output_dir.resolve()
if OUTPUT == SOURCE_ROOT or OUTPUT.is_relative_to(SOURCE_ROOT):
    raise ValueError("REVIEW_OUTPUT_MUST_BE_OUTSIDE_CANDIDATE")
OUTPUT.mkdir(parents=True, exist_ok=True)
fixture_directory = tempfile.TemporaryDirectory(prefix="sidecar_owner_gates_r2_", dir=OUTPUT)
FIXTURES = Path(fixture_directory.name)
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE_ROOT))
supplement = importlib.import_module("v3_shared_data.shared_data.hk_daily_supplement")
reference_name = "v3_shared_data.shared_data.hk_daily_supplement_verified_reference"
spec = importlib.util.spec_from_file_location(reference_name, REFERENCE)
reference = importlib.util.module_from_spec(spec)
sys.modules[reference_name] = reference
spec.loader.exec_module(reference)
for name, path in (("v4", SOURCE_ROOT / "v4"),
                   ("v4.manager_research", SOURCE_ROOT / "v4/manager_research")):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
plan = importlib.import_module("v4.manager_research.workspace_plan")

DAY, TARGET, CODE = "20261009", "20261012", "HK.00001"
CONTEXT = plan.plan_context(TARGET, now=datetime.fromisoformat("2026-10-11T12:00:00+08:00"))
assert plan.screen_context(CONTEXT)["market_session"] == DAY
SESSIONS, CALENDAR_SHA = supplement.requested_sessions(DAY)
HISTORY = plan.rebound_history_sessions(DAY)
assert SESSIONS == [*HISTORY["previous5"], DAY]
FLAGS = deepcopy(supplement.SAFETY)
CUT = CONTEXT["research_cutoff"]
sha = lambda data: hashlib.sha256(data).hexdigest()
canonical = lambda doc: json.dumps(doc, ensure_ascii=False, sort_keys=True,
    separators=(",", ":"), allow_nan=False).encode()
assert sha(REFERENCE.read_bytes()) == "5528a6b44bfb5b79265732b85beb1fb89860355b48a852da07264fb34231c79c"
module_paths = [SOURCE_ROOT / "v4/manager_research/workspace_plan.py",
    SOURCE_ROOT / "v4/manager_research/workspace_daily_channels.py",
    SOURCE_ROOT / "v4/manager_research/workspace.py",
    Path(supplement.__file__), SOURCE_ROOT / "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py",
    REFERENCE, SOURCE_ROOT / "v3_shared_data/shared_data/paths.py",
    SOURCE_ROOT / "contracts/trading_calendar.py", SOURCE_ROOT / "contracts/market_calendar_2026.json"]
source_before = {str(path):sha(path.read_bytes()) for path in module_paths}


def function_bytes(path: Path, name: str) -> bytes:
    source = path.read_text()
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    return ast.get_source_segment(source, node).encode()


def prepare_case(label: str):
    root = FIXTURES / label
    root.mkdir(parents=True, exist_ok=True)
    panel_path = root / "synthetic-panel.parquet"
    panel_manifest = root / "synthetic-panel.manifest.json"
    master_path = root / "synthetic-master.json"
    master_manifest = root / "synthetic-master.manifest.json"
    pd.DataFrame([dict(trade_date_compact=day, code_norm=CODE, name="SYNTHETIC",
        open=8.0, high=10.0, low=7.0, close=8.0, amount=10000.0,
        trade=100.0, pre_close=8.0) for day in [*HISTORY["prior60"], DAY]]).to_parquet(panel_path, index=False)
    panel_manifest.write_bytes(canonical(dict(synthetic_fixture=True)))
    master_path.write_bytes(canonical(dict(synthetic_fixture=True, codes=[CODE])))
    master_manifest.write_bytes(canonical(dict(synthetic_fixture=True, source_date=DAY)))
    panel = dict(owner="V4_SHARED_HK_0_2_PANEL_AUTHORITY", panel_path=str(panel_path),
        panel_sha256=sha(panel_path.read_bytes()), panel_manifest_path=str(panel_manifest),
        panel_manifest_sha256=sha(panel_manifest.read_bytes()),
        panel_available_at="2026-10-09T08:35:00+00:00", source_contract="SYNTHETIC_PANEL_WITNESS")
    master = dict(owner="V4_SHARED_HK_SECURITY_MASTER", names={CODE:dict(name="SYNTHETIC")},
        captured_at="2026-10-09T08:36:00+00:00", artifact_path=str(master_path),
        artifact_sha256=sha(master_path.read_bytes()), manifest_path=str(master_manifest),
        manifest_sha256=sha(master_manifest.read_bytes()))
    parent_panel = dict(panel_sha256=panel["panel_sha256"],
        panel_manifest_sha256=panel["panel_manifest_sha256"],
        manifest_prepared_at=panel["panel_available_at"])
    parent_master = dict(manifest_sha256=master["manifest_sha256"],
        artifact_sha256=master["artifact_sha256"], captured_at=master["captured_at"])
    source_rows = [dict(datetime=datetime.strptime(day, "%Y%m%d").strftime("%Y-%m-%d 15:00"),
        open=80.0, high=100.0, low=70.0, close=80.0,
        trade=200.0 if day == DAY else 100.0, amount=10000.0) for day in SESSIONS]
    request = dict(category=4, market=71, code="00001", start=0, count=6,
        requested_sessions=deepcopy(SESSIONS))
    record = dict(code=CODE, status="READY", error_code=None, request=request,
        request_sha256=sha(canonical(request)), request_started_at="2026-10-09T09:00:01+00:00",
        response_acquired_at="2026-10-09T09:00:02+00:00",
        request_finished_at="2026-10-09T09:00:03+00:00", returned_count=6,
        source_rows=source_rows, response_sha256=sha(canonical(source_rows)),
        bars=[supplement._decode_bar(row, DAY, set(SESSIONS)) for row in source_rows],
        missing_sessions=[])
    run = sha(label.encode())[:24]
    run_rel = f"daily_supplements/runs/{DAY}/{run}"
    capture = dict(schema_version=supplement.CAPTURE_SCHEMA, target_date=DAY,
        requested_sessions=deepcopy(SESSIONS), calendar_sha256=CALENDAR_SHA,
        capture_scope="FULL_MASTER", canary_codes=None,
        capture_started_at="2026-10-09T09:00:00+00:00",
        capture_prepared_at="2026-10-09T09:00:07+00:00",
        source=dict(provider="PYTDX_EXHQ", host=f"{supplement.SOURCE_HOST}:{supplement.SOURCE_PORT}",
            category=4, market=71, method="get_instrument_bars", start=0, count=6),
        records=[record], **FLAGS)
    manifest = dict(schema_version=supplement.MANIFEST_SCHEMA, status="READY", target_date=DAY,
        run_id=run, raw_capture_relative=f"{run_rel}/raw_capture.json", raw_capture_sha256=None,
        requested_sessions=deepcopy(SESSIONS), calendar_sha256=CALENDAR_SHA,
        capture_scope="FULL_MASTER", canary_codes=None, capture_started_at=capture["capture_started_at"],
        prepared_at=capture["capture_prepared_at"], provider="PYTDX_EXHQ",
        method="get_instrument_bars", category=4, market=71, start=0, count=6,
        code_count=1, master_code_count=1, selected_codes=[CODE],
        selected_codes_sha256=sha(canonical([CODE])), universe_codes_sha256=sha(canonical([CODE])),
        panel_identity=deepcopy(parent_panel), security_master_identity=deepcopy(parent_master),
        record_status_counts={"READY":1}, publication_status="OFFICIAL_DAILY_POINTER_CAS", **FLAGS)
    pointer = dict(schema_version=supplement.POINTER_SCHEMA, target_date=DAY, run_id=run,
        manifest_relative=f"{run_rel}/manifest.json", manifest_sha256=None,
        raw_capture_relative=manifest["raw_capture_relative"], raw_capture_sha256=None,
        published_at="2026-10-09T09:00:08+00:00", previous_manifest_sha256=None,
        panel_identity=deepcopy(parent_panel), security_master_identity=deepcopy(parent_master), **FLAGS)
    return root, panel, master, parent_panel, parent_master, capture, manifest, pointer


def write_case(root, capture, manifest, pointer, *, corrupt=None):
    raw_bytes = canonical(capture)
    manifest["raw_capture_sha256"] = sha(raw_bytes)
    manifest_bytes = canonical(manifest)
    pointer["raw_capture_sha256"] = sha(raw_bytes)
    pointer["manifest_sha256"] = sha(manifest_bytes)
    if corrupt == "manifest_sha":
        pointer["manifest_sha256"] = "0" * 64
    elif corrupt == "raw_sha":
        pointer["raw_capture_sha256"] = "0" * 64
    asset_root = root / "assets/hk_0_2"
    blobs = {manifest["raw_capture_relative"]:raw_bytes,
             pointer["manifest_relative"]:manifest_bytes,
             f"daily_supplements/pointers/{DAY}.json":canonical(pointer)}
    for relative, data in blobs.items():
        path = asset_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return {relative:sha(data) for relative, data in blobs.items()}


EXPECTATIONS = {
    "valid": "READY",
    "wrong_pointer_date": "HK_DAILY_SUPPLEMENT_POINTER_IDENTITY_INVALID",
    "wrong_manifest_sessions": "HK_DAILY_SUPPLEMENT_MANIFEST_CONTRACT_INVALID",
    "future_bar": "HK_DAILY_SUPPLEMENT_BAR_DATE_INVALID",
    "duplicate_bar": "HK_DAILY_SUPPLEMENT_BAR_DATE_INVALID",
    "manifest_sha": "HK_DAILY_SUPPLEMENT_CHECKSUM_MISMATCH",
    "raw_sha": "HK_DAILY_SUPPLEMENT_CHECKSUM_MISMATCH",
    "response_sha": "HK_DAILY_SUPPLEMENT_REQUEST_OR_RESPONSE_INVALID",
    "missing_session_claimed_ready": "HK_DAILY_SUPPLEMENT_MISSING_SESSION_STATUS_INVALID",
    "partial_pending": "PARTIAL_WITH_PENDING",
    "late_pointer": "HK_DAILY_SUPPLEMENT_POINTER_AFTER_CUTOFF",
    "wrong_panel_sha": "HK_DAILY_SUPPLEMENT_POINTER_IDENTITY_INVALID",
    "normalized_trade_changed": "HK_DAILY_SUPPLEMENT_NORMALIZED_ROWS_MISMATCH",
    "absolute_unit_promoted": "HK_DAILY_SUPPLEMENT_BAR_UNIT_INVALID",
}

results = []
for label, expected in EXPECTATIONS.items():
    root, panel, master, parent_panel, parent_master, capture, manifest, pointer = prepare_case(label)
    record = capture["records"][0]
    if label == "wrong_pointer_date":
        pointer["target_date"] = "20261008"
    elif label == "wrong_manifest_sessions":
        manifest["requested_sessions"][0] = "20261001"
    elif label == "future_bar":
        record["bars"][-1]["trade_date"] = "20261012"
    elif label == "duplicate_bar":
        record["bars"][1]["trade_date"] = record["bars"][0]["trade_date"]
    elif label == "response_sha":
        record["response_sha256"] = "0" * 64
    elif label in {"missing_session_claimed_ready", "partial_pending"}:
        removed = record["bars"].pop(0)["trade_date"]
        record["source_rows"].pop(0)
        record["returned_count"] -= 1
        record["response_sha256"] = sha(canonical(record["source_rows"]))
        if label == "partial_pending":
            record["status"] = "PENDING"
            record["missing_sessions"] = [removed]
            manifest["status"] = "PARTIAL_WITH_PENDING"
            manifest["record_status_counts"] = {"PENDING":1}
    elif label == "late_pointer":
        pointer["published_at"] = "2026-10-12T09:00:08+00:00"
    elif label == "wrong_panel_sha":
        pointer["panel_identity"]["panel_sha256"] = "0" * 64
        manifest["panel_identity"]["panel_sha256"] = "0" * 64
    elif label == "normalized_trade_changed":
        record["bars"][0]["trade"] += 1
    elif label == "absolute_unit_promoted":
        record["bars"][0]["native_fields"]["volume_unit"] = "SHARES"
    hashes = write_case(root, capture, manifest, pointer, corrupt=label)
    reader_outcomes = {}
    for name, reader in (("candidate", supplement), ("verified_reference", reference)):
        try:
            value = reader.read_verified_daily_supplement(root, target_date=DAY,
                requested=SESSIONS, research_cutoff=CUT, expected_panel=parent_panel,
                expected_master=parent_master, expected_codes=[CODE])
            outcome = value["status"] if value else "ABSENT"
        except ValueError as error:
            outcome = str(error)
        reader_outcomes[name] = outcome
        assert outcome == expected, (label, name, expected, outcome)
    # Keep the real workspace adapter and real sidecar verifier. Only upstream
    # panel/master witnesses are injected, expressly as a synthetic boundary.
    plan._read_hk02_panel_witness = lambda *args, **kwargs: (deepcopy(panel), [])
    plan._screen_security_master_witness = lambda *args, **kwargs: (deepcopy(master), {})
    diagnostics = {}
    screen = plan.read_rebound_screen(root, CONTEXT, diagnostics=diagnostics)
    row = next(row for group in ("strict", "near", "pending", "excluded", "screen_unresolved")
               for row in screen.get(group, []) if row["code"] == CODE)
    if label == "valid":
        assert row["strict_two_gate_oversold_5dvolume"] is True
        assert row["volume_ratio_5d"] == 2.0
        assert row["close"] == 8.0 and row["prior60_session_high"] == 10.0
        assert row["volume_unit_status"] == "NOT_PROVEN"
    else:
        assert row["strict_two_gate_oversold_5dvolume"] is False
        assert row["history_status"] == "PARTIAL_UNKNOWN"
        assert row["volume_source"] == "V4_SHARED_HK_0_2_PANEL_AUTHORITY"
        assert row["volume_flag_5d_ge_1_5"] is None
    assert row["close"] == 8.0 and row["prior60_session_high"] == 10.0
    if expected not in {"READY", "PARTIAL_WITH_PENDING"}:
        assert any(expected in reason for reason in screen["gaps"])
        assert any(expected in reason for reason in diagnostics.get("gaps", []))
    # Reader and screen calculations must leave the synthetic input bytes intact.
    for relative, original_sha in hashes.items():
        assert sha((root / "assets/hk_0_2" / relative).read_bytes()) == original_sha
    results.append(dict(case=label, owner_reader=reader_outcomes,
        screen_status=screen["status"], strict_count=len(screen["strict"]),
        pending_count=len(screen["pending"]), volume_source=row["volume_source"],
        volume_ratio_5d=row["volume_ratio_5d"], close=row["close"],
        prior60_high=row["prior60_session_high"], history_unknown_reasons=row["history_unknown_reasons"],
        screen_gaps=screen["gaps"], diagnostic_gaps=diagnostics.get("gaps"),
        expected_reader_reason_visible=(expected in {"READY", "PARTIAL_WITH_PENDING"}
            or any(expected in reason for reason in screen["gaps"]))))

source_hashes = {str(path):sha(path.read_bytes()) for path in module_paths}
assert source_before == source_hashes, "A reviewed source changed; rerun on a stable snapshot"
reader_equal = function_bytes(Path(supplement.__file__), "read_verified_daily_supplement") == function_bytes(REFERENCE, "read_verified_daily_supplement")
assert reader_equal
fixture_directory.cleanup()
assert not FIXTURES.exists()
output = dict(evidence_kind="SYNTHETIC_FILES_REAL_UNCHANGED_SIDECAR_READER",
    collector_called=False, publication_owner_called=False, real_market_owner_executed=False,
    reviewed_sources_stable=True, temporary_fixtures_cleaned=True,
    case_count=14, complete_ready_case_count=1, invalid_rejection_case_count=12,
    legitimate_partial_case_count=1, total_nonready_case_count=13,
    native_calendar_source_sha256=CALENDAR_SHA, requested_sessions=SESSIONS,
    full_source_sha256=source_hashes, reader_function_text_identical=reader_equal,
    real_workspace_sidecar_adapter=inspect.getsourcefile(plan._read_hk02_daily_supplement_witness),
    cases=results, assertion_result="PASS")
report = OUTPUT / "sidecar_owner_gate_results_r2.json"
report.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(output, ensure_ascii=False, indent=2))
