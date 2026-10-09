"""Read-only R3 review probes; all state and source fixtures are temporary.

Run from r3-work/candidate with PYTHONPATH=.:tests and the native 3.14 venv.
This script reports observations rather than asserting the previously observed
bugs, so the same command can demonstrate their resolution after a code change.
No HTTPConnection is created and no production path is read or written.
"""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pytest import MonkeyPatch
from test_manager_r3_binding_identity import (
    DATE, NOW, _json_file, bound_owner, synthetic_binding, supervisor,
)
from test_manager_r3_cycle_outcomes import missing_input
from v4.manager_research import plan_owner_dispatch as dispatch
from v4.manager_research import workspace_plan_autorun as autorun
from ops import run_manager_announcement_cycle as cycle


def missing_then_ready():
    with TemporaryDirectory(prefix="r3-review-input-retry-") as tmp, MonkeyPatch.context() as mp:
        service, _, _, _, ref = bound_owner(Path(tmp), mp)
        real_refresh = service.refresh_workspace_plan
        ready = False

        def refresh(date, **kwargs):
            if not ready:
                service.owner_calls.append((date, kwargs))
                return missing_input(date)
            return real_refresh(date, **kwargs)

        service.refresh_workspace_plan = refresh
        first = dispatch.execute_bound_plan_cycle(service, DATE, ref["sha256"])
        ready = True
        mp.setattr(dispatch, "clock_now", lambda: NOW + timedelta(minutes=1))
        second = dispatch.execute_bound_plan_cycle(service, DATE, ref["sha256"])
        return {
            "case": "inputs_ready_on_second_trigger",
            "first_status": first["status"], "first_outcome": first["dispatch_outcome"],
            "second_status": second["status"], "second_outcome": second["dispatch_outcome"],
            "owner_calls": len(service.owner_calls),
            "same_receipt": first["dispatch_receipt"] == second["dispatch_receipt"],
            "second_run_id": second["plan_result"].get("run_id"),
        }


def window_expired_before_owner():
    with TemporaryDirectory(prefix="r3-review-window-") as tmp, MonkeyPatch.context() as mp:
        service, _, _, _, ref = bound_owner(Path(tmp), mp)
        admitted = NOW.replace(minute=29, second=59)
        expired = NOW.replace(minute=30, second=0)
        ticks = iter([admitted, admitted, expired, expired])
        mp.setattr(dispatch, "clock_now", lambda: next(ticks))
        result = dispatch.execute_bound_plan_cycle(service, DATE, ref["sha256"])
        return {
            "case": "window_expired_before_owner", "status": result["status"],
            "outcome": result["dispatch_outcome"], "owner_calls": len(service.owner_calls),
            "reason": result["failure_reasons"], "plan_status": result["plan_result"]["status"],
        }


def explicit_unconfirmed_readback():
    with MonkeyPatch.context() as mp:
        mp.setattr(autorun, "run_scheduled_preopen_plan_safe", lambda *a, **kw: {
            "status": "MATERIALIZED", "target_trade_date": DATE,
        })
        branch = cycle.run_scheduled_plan_target(object(), DATE, DATE, now=NOW,
            plan_config={"enabled": True}, preopen_config={"enabled": True, "lead_seconds": 180})
        identity = dispatch._parent_trigger_identity(DATE, DATE, "PREOPEN", "a" * 64)
        response = dispatch._cycle_result(identity, NOW, branch)
        return {
            "case": "explicit_unconfirmed_is_overwritten", "branch_status": branch["status"],
            "branch_outcome": branch["dispatch_outcome"], "dispatch_outcome": response["dispatch_outcome"],
            "reason": response["failure_reasons"],
            "owner_readback": response["parent_trigger_receipt"]["owner_readback_status"],
        }


def historical_dynamic_canary():
    with TemporaryDirectory(prefix="r3-review-historical-canary-") as tmp:
        binding, worker, _ = synthetic_binding(Path(tmp))
        canary_path = Path(binding["plan_activation_receipt"]["path"])
        canary = json.loads(canary_path.read_bytes())
        canary["scope"] = supervisor.PLAN_CANARY_HISTORICAL_SCOPE
        receipt_path = Path(canary["owner_evidence"]["readback"]["path"])
        receipt = json.loads(receipt_path.read_bytes())
        receipt["request"]["url"] += "&view=dynamic"
        canary["owner_evidence"]["readback"] = _json_file(receipt_path, receipt)
        binding["plan_activation_receipt"] = _json_file(canary_path, canary)
        try:
            supervisor.validate_binding(binding, expected_app=worker)
            outcome = "ACCEPTED"
        except ValueError as exc:
            outcome = str(exc)
        return {
            "case": "historical_canary_with_required_dynamic_view", "scope": canary["scope"],
            "get_url": receipt["request"]["url"], "outcome": outcome,
        }


if __name__ == "__main__":
    files = [
        "infrastructure/scheduling/manager_announcement_supervisor.py",
        "ops/render_manager_announcement_binding.py",
        "v4/manager_research/plan_owner_dispatch.py",
        "apps/api/v35_api/manager_research_router.py",
        "v4/manager_research/workspace.py",
        "v4/manager_research/workspace_plan_autorun.py",
        "ops/run_manager_announcement_cycle.py",
    ]
    print(json.dumps({"candidate_sha256": {
        path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in files
    }, "observations": [missing_then_ready(), window_expired_before_owner(),
        explicit_unconfirmed_readback(), historical_dynamic_canary()]}, ensure_ascii=False, indent=2))
