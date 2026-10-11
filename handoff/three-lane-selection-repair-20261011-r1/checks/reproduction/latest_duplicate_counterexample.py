"""Synthetic read-only counterexample: latest duplication still spends budget."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from review_history_boundary import BOUNDARY, DATE, EARLY, HERE, LATE, body_bytes, h, make_plan, tracked
from v4.manager_research import workspace as w
from v4.manager_research.store import ManagerResearchStore


with TemporaryDirectory(prefix="duplicate-latest-", dir=HERE) as temporary:
    store = ManagerResearchStore(Path(temporary) / "store")
    late, _ = make_plan(store, 1, LATE, exact_bytes=24 * 1024 * 1024, journal=False, latest=True)
    early, _ = make_plan(store, 2, EARLY, exact_bytes=20 * 1024 * 1024)
    w.verified_plan_attempt(store, early)
    error = None
    with tracked(store) as reads:
        try:
            selected = h.select_plan(store, DATE, BOUNDARY)
        except ValueError as exc:
            selected = None
            error = f"{type(exc).__name__}:{exc}"
    result = dict(scope="SYNTHETIC_NOT_LIVE", unique_immutable_plan_bytes=44 * 1024 * 1024,
        cumulative_limit_bytes=h._MAX_SCAN_BYTES, valid_early_owner_verified=True,
        selected_run_id=selected and selected["run_id"], expected_early_run_id=early["run_id"],
        error=error, plan_bytes_returned=body_bytes(reads), reads=reads)
    (HERE / "latest_duplicate_result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))
