"""Trace one actual application owner save/read with a synthetic screen.

The real ManagerResearchJobService, ManagerResearchStore, original decision
ledger, sealed plan/attempt checks and HTTP route are retained. The clock,
screen-source input and unavailable announcement catalog are fixture boundaries.
No live data, network capture, Mac service or natural execution is attested.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("candidate", type=Path)
parser.add_argument("--execution-source", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
source = args.candidate.resolve()
execution = args.execution_source.resolve()
output = args.output_dir.resolve()
if output == source or output.is_relative_to(source):
    raise ValueError("REVIEW_OUTPUT_MUST_BE_OUTSIDE_CANDIDATE")
output.mkdir(parents=True, exist_ok=True)
sha = lambda raw: hashlib.sha256(raw).hexdigest()
assert sha(execution.read_bytes()) == "1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b"


class RecoveredOriginalDependency(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "stage_center.execution_evidence":
            return importlib.util.spec_from_file_location(fullname, execution)
        return None


sys.dont_write_bytecode = True
sys.path[:0] = [str(source), str(source / "tests")]
sys.meta_path.insert(0, RecoveredOriginalDependency())
relative_sources = [
    "v4/manager_research/workspace.py", "v4/manager_research/workspace_plan.py",
    "v4/manager_research/workspace_daily_channels.py", "v4/manager_research/research_attention.py",
    "v4/manager_research/workspace_projection.py", "v4/manager_research/workspace_identity.py",
    "v4/manager_research/workspace_history.py", "v4/manager_research/workspace_semantics.py",
    "v4/manager_research/service.py", "v4/manager_research/store.py",
    "apps/api/v35_api/manager_research_router.py", "infrastructure/owned_io.py",
    "tests/three_lane_announcement_original_fixture.py", "tests/test_manager_research_selection_ledger.py",
]
source_paths = [source / path for path in relative_sources] + [execution]
before_sources = {str(path):sha(path.read_bytes()) for path in source_paths}

import three_lane_announcement_original_fixture as original
from test_manager_research_selection_ledger import _fixture as screen_fixture
from v4.manager_research import workspace as work
from v4.manager_research.contracts import canonical_json

clock = datetime(2026, 10, 8, 1, tzinfo=timezone.utc)
original.NOW = clock


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return clock.astimezone(tz) if tz else clock.replace(tzinfo=None)


original.api.datetime = Clock
original.consumer._now = lambda: clock.isoformat()
work._now = lambda: clock.isoformat()
screen, _ = screen_fixture()
screen.update(target_trade_date=original.TARGET, verified_session="20261007",
    status="READY", strict=[], near=[], pending=[], cards=[], gaps=[])
for row in screen["excluded"]:
    row.update(target_monday=int(original.TARGET), verified_session=20261007)
screen["coverage"].update(input_candidate_count=1, history_complete_count=1,
    history_pending_count=0, strict_count=0, near_candidate_count=0, selected_count=0,
    excluded_count=1, screen_unresolved_count=0, row_accounted_count=1)
# Explicit upstream source fixture. Owner save, source ledger, store, attempt,
# product validation and API readback are not replaced.
work.read_rebound_screen = lambda *args, **kwargs: deepcopy(screen)


def lane(value):
    return next(row for row in value["daily_channels"]["channels"] if row["channel"] == "OVERSOLD")


def file_ref(path, root):
    raw = path.read_bytes()
    return dict(relative_path=str(path.relative_to(root)), raw_file_sha256=sha(raw), bytes=len(raw))


with tempfile.TemporaryDirectory(prefix="original_o_owner_save_r2_", dir=output) as temporary:
    root = Path(temporary)
    source_fixture = root / "synthetic_screen_input.json"
    source_fixture.write_bytes(canonical_json(screen))
    service = original._FixtureService(root / "original_owner_state")
    try:
        preview = work.get_workspace(service, original.TARGET, include_saved=False, now=clock)
        assert lane(preview)["status"] == "PARTIAL" and lane(preview)["candidate_count"] is None
        saved = service.refresh_workspace_plan(original.TARGET, now=clock)
        assert saved["plan_product"]["status"] == "CURRENT" and saved["plan_product"]["consumed"] is True
        assert lane(saved)["status"] == "READY_EMPTY" and lane(saved)["candidate_count"] == 0
        assert saved["market_screen"] == preview["market_screen"]
        ledger = saved["research_attention"]["research_selection"]
        assert ledger["decision_identity"] == preview["research_attention"]["research_selection"]["decision_identity"]
        run_id = saved["plan_product"]["run_id"]
        product_path = service.store.root / "workspace_plans" / original.TARGET / (run_id + ".json")
        product_latest = product_path.with_name("latest.json")
        attempt_path = service.store.root / "workspace_plan_runs" / original.TARGET / (run_id + ".json")
        attempt_latest = attempt_path.with_name("latest.json")
        product = service.store._read(product_path)
        attempt = work.verified_plan_attempt(service.store, product)
        assert product["sha256"] == saved["plan_product"]["sha256"] == lane(saved)["product_sha256"]
        assert attempt["run_id"] == run_id
        before_read = original._snapshot(service.store.root)
        reread = service.get_workspace(original.TARGET)
        assert lane(reread)["status"] == "READY_EMPTY" and lane(reread)["candidate_count"] == 0
        assert lane(reread)["run_id"] == run_id and lane(reread)["product_sha256"] == product["sha256"]
        with original._client(service) as client:
            response = client.get("/api/v4/manager/research/workspace", params={"date":original.TARGET, "view":"dynamic"})
            assert response.status_code == 200, response.text
            api_value = response.json()
        assert lane(api_value)["status"] == "READY_EMPTY" and lane(api_value)["candidate_count"] == 0
        assert lane(api_value)["run_id"] == run_id and lane(api_value)["product_sha256"] == product["sha256"]
        assert original._snapshot(service.store.root) == before_read
        result = dict(evidence_kind="ORIGINAL_APPLICATION_O_OWNER_SAVE_STORE_SERVICE_AND_HTTP_READBACK_WITH_SYNTHETIC_SCREEN",
            assertion_result="PASS", scope="ISOLATED_APPLICATION_FUNCTIONS_NOT_MAC_OWNER_OR_REAL_MARKET_DATA",
            original_owner_called="ManagerResearchJobService.refresh_workspace_plan",
            original_store_class="ManagerResearchStore", source_screen_reader_injected=True,
            original_archive_and_attempt_gates_retained=True, actual_mac_owner_executed=False,
            natural_run_verified=False, target_trade_date=original.TARGET, source_date="20261007",
            research_cutoff=saved["plan_context"]["research_cutoff"], clock=clock.isoformat(),
            source_fixture=file_ref(source_fixture, root),
            source_input_identity=screen["input_identity"], source_refs=screen.get("source_refs"),
            decision_identity=ledger["decision_identity"], decision_coverage=ledger["coverage"],
            original_plan_product=dict(run_id=run_id, owner=product["owner"],
                generated_at=product["generated_at"], execution_kind=product["execution_kind"],
                product_sha256=product["sha256"], input_identity=product["input_identity"],
                immutable_file=file_ref(product_path,service.store.root),
                latest_file=file_ref(product_latest,service.store.root)),
            original_owner_attempt=dict(run_id=attempt["run_id"], owner=attempt["owner"],
                state=attempt["state"], attempt_sha256=attempt["sha256"],
                run_file=file_ref(attempt_path,service.store.root),
                latest_file=file_ref(attempt_latest,service.store.root)),
            preview=dict(status=lane(preview)["status"], candidate_count=lane(preview)["candidate_count"]),
            save_return=dict(status=lane(saved)["status"], candidate_count=lane(saved)["candidate_count"],
                run_id=lane(saved)["run_id"], product_sha256=lane(saved)["product_sha256"]),
            service_readback=deepcopy(reread["plan_product"]["run_readback"]),
            http_readback=dict(path="/api/v4/manager/research/workspace", query={"date":original.TARGET,"view":"dynamic"},
                status_code=response.status_code, status=lane(api_value)["status"], candidate_count=lane(api_value)["candidate_count"],
                run_id=lane(api_value)["run_id"], product_sha256=lane(api_value)["product_sha256"],
                decision_identity=api_value["research_attention"]["research_selection"]["decision_identity"]),
            get_changed_store_files=False)
    finally:
        service.close()
assert not root.exists()
after_sources = {str(path):sha(path.read_bytes()) for path in source_paths}
assert before_sources == after_sources, "Reviewed source changed; rerun"
result.update(temporary_store_cleaned=True, candidate_modified=False,
    reviewed_sources_stable=True, full_source_sha256=after_sources)
destination = output / "original_o_owner_save_trace_r2.json"
destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
