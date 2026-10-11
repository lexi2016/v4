"""Independent P1 behavior review against actual functions / SafeRoot.

All fixture files are synthetic and temporary beneath this reviewer directory.
No candidate source or candidate test file is written. No owner is refreshed.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from v4.manager_research import workspace as w
from v4.manager_research import workspace_history as h
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_plan import plan_context
from v4.manager_research.workspace_projection import FLAGS, build_workspace, digest

HERE = Path(__file__).resolve().parent
DATE = "20261009"
OWNER = "ManagerResearchJobService.refresh_workspace_plan"
BOUNDARY = h.boundary_context(DATE)
EARLY = "2026-10-09T09:28:00+08:00"
LATE = "2026-10-10T10:00:00+08:00"
CASES = []


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def make_plan(store, number, generated, *, started=None, finished=None,
              exact_bytes=None, journal=True, latest=False, execution_context=None):
    run = f"{number:032x}"
    body = build_workspace(DATE,
        catalyst={"target_trade_date": DATE, "status": "NOT_MATERIALIZED", "cards": [], "gaps": []},
        plan_context=plan_context(DATE, now=datetime.fromisoformat(generated)))
    product = dict(schema_version=w.PLAN_SCHEMA, target_trade_date=DATE,
        run_id=run, generated_at=generated, owner=OWNER, execution_kind="MANUAL_REFRESH",
        workspace=body, input_identity=body["input_identity"], sha256="0" * 64, **FLAGS)
    if execution_context is not None:
        product["execution_context"] = deepcopy(execution_context)
    if exact_bytes is not None:
        body["synthetic_padding"] = ""
        remaining = exact_bytes - len(encode(product))
        assert remaining >= 0
        body["synthetic_padding"] = "x" * remaining
    product["sha256"] = digest({k: v for k, v in product.items() if k != "sha256"})
    raw = encode(product)
    if exact_bytes is not None:
        assert len(raw) == exact_bytes
    store._io.write_bytes(f"workspace_plans/{DATE}/{run}.json", raw, require_absent=True)
    if latest:
        store._io.write_bytes(f"workspace_plans/{DATE}/latest.json", raw)
    attempt = w.seal_attempt(dict(schema_version=w.ATTEMPT_SCHEMA,
        target_trade_date=DATE, run_id=run, owner=OWNER, state="SUCCEEDED_EMPTY",
        execution_kind="MANUAL_REFRESH", started_at=started or generated,
        finished_at=finished or generated, last_success_at=generated,
        input_identity=body["input_identity"], input_coverage={}, summary={}, failure_reasons=[], **FLAGS))
    if execution_context is not None:
        attempt["execution_context"] = deepcopy(execution_context)
        attempt = w.seal_attempt(attempt)
    w.validate_attempt(attempt, DATE)
    if journal:
        store._io.write_bytes(f"workspace_plan_runs/{DATE}/{run}.json", encode(attempt))
    return product, attempt


@contextmanager
def tracked(store):
    reads = []
    original = store._io.read_bytes
    def read(path, **kwargs):
        item = {"path": path, "max_bytes": kwargs.get("max_bytes", 64 * 1024 * 1024)}
        try:
            raw = original(path, **kwargs)
        except Exception as exc:
            item.update(bytes_returned=0, error=f"{type(exc).__name__}:{exc}")
            reads.append(item)
            raise
        item["bytes_returned"] = len(raw)
        reads.append(item)
        return raw
    store._io.read_bytes = read
    try:
        yield reads
    finally:
        store._io.read_bytes = original


def body_bytes(reads):
    return sum(r["bytes_returned"] for r in reads if r["path"].startswith("workspace_plans/"))


def fingerprint_tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.json")) if p.is_file() and not p.is_symlink()}


def run_case(name, function):
    with TemporaryDirectory(prefix="synthetic-", dir=HERE) as directory:
        store = ManagerResearchStore(Path(directory) / "store")
        details = function(store)
        CASES.append(dict(name=name, status="PASS", **(details or {})))


def actual_inventory(store):
    # Exact byte sizes from the supplied 10/09 inventory; synthetic contents.
    sizes = [22668492, 14782489, 23388302, 23388296, 16152043, 23263586]
    for index, size in enumerate(sizes, 1):
        make_plan(store, index, LATE, exact_bytes=size, latest=index == 3)
    before = fingerprint_tree(store.root)
    with tracked(store) as reads:
        assert h.select_plan(store, DATE, BOUNDARY) is None
    assert fingerprint_tree(store.root) == before
    assert body_bytes(reads) == 23388302
    assert len([r for r in reads if r["path"].startswith("workspace_plan_runs/")]) == 6
    result = h.read_history(SimpleNamespace(store=store), DATE)
    assert result["read_context"]["status"] == "NOT_MATERIALIZED"
    assert result["read_context"]["candidate_count_known"] is False
    assert result["plan_product"]["reason"] == "HISTORY_QUALIFIED_SAVED_PLAN_MISSING"
    assert result["stocks"] == []
    return dict(synthetic_plan_directory_bytes=sum(sizes) + sizes[2],
                plan_bytes_returned=body_bytes(reads), full_read_status=result["read_context"]["status"], reads=reads)


def bad_journal(store, kind):
    _, attempt = make_plan(store, 1, LATE)
    make_plan(store, 2, LATE, latest=True)
    relative = f"workspace_plan_runs/{DATE}/{attempt['run_id']}.json"
    path = store.root / relative
    if kind == "oversize":
        path.write_bytes(b" " * (h._MAX_ATTEMPT_BYTES + 1))
    elif kind == "malformed_json":
        path.write_bytes(b"{broken")
    elif kind == "non_mapping":
        path.write_bytes(b"[]")
    elif kind in {"invalid_start", "invalid_state", "unsafe_flags", "wrong_input_shape"}:
        changed = deepcopy(attempt)
        field, value = {
            "invalid_start": ("started_at", "2026-10-10T10:00:00"),
            "invalid_state": ("state", "UNDECLARED"),
            "unsafe_flags": ("orders_sent", True),
            "wrong_input_shape": ("run_id", ["not-a-run"]),
        }[kind]
        changed[field] = value
        path.write_bytes(encode(w.seal_attempt(changed)))
    elif kind == "directory":
        path.unlink()
        path.mkdir()
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path)
    else:
        raise AssertionError(kind)
    with tracked(store) as reads:
        result = h.read_history(SimpleNamespace(store=store), DATE)
    assert result["read_context"]["status"] == "SOURCE_FAILED"
    assert result["read_context"]["candidate_count_known"] is False
    assert result["plan_product"]["consumed"] is False
    assert result["stocks"] == []
    assert not any(r["path"] == f"workspace_plans/{DATE}/{attempt['run_id']}.json" for r in reads)
    if kind in {"oversize", "directory", "fifo"}:
        failed = next(r for r in reads if r["path"] == relative)
        assert failed["bytes_returned"] == 0 and "error" in failed
    return dict(reason=result["plan_product"]["reason"], reads=reads)


def missing_journal_bounded(store):
    for n in range(1, 5):
        make_plan(store, n, LATE, exact_bytes=18 * 1024 * 1024, journal=False, latest=n == 4)
    before = fingerprint_tree(store.root)
    with tracked(store) as reads:
        result = h.read_history(SimpleNamespace(store=store), DATE)
    assert result["read_context"]["status"] == "SOURCE_FAILED"
    assert result["read_context"]["candidate_count_known"] is False
    assert body_bytes(reads) == 54 * 1024 * 1024
    rejected = [r for r in reads if r["path"].startswith("workspace_plans/") and "error" in r]
    assert len(rejected) == 1 and rejected[0]["max_bytes"] == 10 * 1024 * 1024
    assert fingerprint_tree(store.root) == before
    return dict(plan_bytes_returned=body_bytes(reads), reason=result["plan_product"]["reason"], reads=reads)


def missing_early_journal(store):
    expected, _ = make_plan(store, 1, EARLY, journal=False)
    make_plan(store, 2, LATE, latest=True)
    assert h.select_plan(store, DATE, BOUNDARY) == expected
    result = h.read_history(SimpleNamespace(store=store), DATE)
    assert result["read_context"]["status"] == "SOURCE_FAILED"
    assert result["plan_product"]["reason"] == "HISTORY_PLAN_OWNER_ATTEMPT_INVALID"
    assert result["plan_product"]["consumed"] is False
    return dict(selection="EARLY_PRODUCT_FOUND", full_read_reason=result["plan_product"]["reason"])


def boundary_equal(store):
    expected, _ = make_plan(store, 1, "2026-10-09T09:30:00+08:00")
    make_plan(store, 2, LATE, latest=True)
    with tracked(store) as reads:
        assert h.select_plan(store, DATE, BOUNDARY) == expected
    assert any(r["path"].endswith(f"/{expected['run_id']}.json") and r["path"].startswith("workspace_plans/") for r in reads)
    w.verified_plan_attempt(store, expected)
    return dict(boundary=BOUNDARY["research_cutoff"], selected_generated_at=expected["generated_at"])


def early_start_late_finish(store):
    expected, _ = make_plan(store, 1, EARLY, started="2026-10-09T09:27:00+08:00",
                            finished="2026-10-09T09:31:00+08:00")
    make_plan(store, 2, LATE, latest=True)
    assert h.select_plan(store, DATE, BOUNDARY) == expected
    attempt = w.verified_plan_attempt(store, expected)
    assert attempt["finished_at"] > BOUNDARY["research_cutoff"]
    return dict(owner_attempt_verified=True, generated_at=expected["generated_at"], finished_at=attempt["finished_at"])


def context_late_finish(store):
    execution = dict(trigger_kind="SCHEDULED", timing="ON_TIME", natural_run_verified=False,
        scheduled_for="2026-10-09T09:27:00+08:00", started_at="2026-10-09T09:27:00+08:00",
        finished_at="2026-10-09T09:31:00+08:00")
    make_plan(store, 1, EARLY, started=execution["started_at"], finished=execution["finished_at"],
              execution_context=execution)
    make_plan(store, 2, LATE, latest=True)
    assert h.select_plan(store, DATE, BOUNDARY) is None
    return dict(selection=None, basis="Existing explicit context gate still rejects finish after boundary")


def eligible_latest(store):
    expected, attempt = make_plan(store, 1, EARLY, latest=True)
    make_plan(store, 2, LATE)
    (store.root / f"workspace_plan_runs/{DATE}/{attempt['run_id']}.json").write_bytes(b"bad")
    with tracked(store) as reads:
        assert h.select_plan(store, DATE, BOUNDARY) == expected
    assert len(reads) == 1 and reads[0]["path"].endswith("/latest.json")
    result = h.read_history(SimpleNamespace(store=store), DATE)
    assert result["plan_product"]["reason"] == "HISTORY_PLAN_OWNER_ATTEMPT_INVALID"
    return dict(selection="LATEST_FAST_PATH", full_read_reason=result["plan_product"]["reason"], reads=reads)


def invalid_latest(store):
    make_plan(store, 1, EARLY)
    make_plan(store, 2, LATE, latest=True)
    (store.root / f"workspace_plans/{DATE}/latest.json").write_bytes(b"bad")
    result = h.read_history(SimpleNamespace(store=store), DATE)
    assert result["read_context"]["status"] == "SOURCE_FAILED"
    assert not result["plan_product"]["consumed"]
    return dict(reason=result["plan_product"]["reason"])


def late_corrupt_body_only_excluded(store):
    expected, _ = make_plan(store, 1, EARLY)
    late, _ = make_plan(store, 2, LATE)
    make_plan(store, 3, LATE, latest=True)
    (store.root / f"workspace_plans/{DATE}/{late['run_id']}.json").write_bytes(b"bad")
    with tracked(store) as reads:
        assert h.select_plan(store, DATE, BOUNDARY) == expected
    assert not any(r["path"] == f"workspace_plans/{DATE}/{late['run_id']}.json" for r in reads)
    w.verified_plan_attempt(store, expected)
    return dict(selection="EARLY_OWNER_VALID_PLAN", excluded_late_body_not_admitted=True)


def directory_bound(store, kind):
    store._io.ensure_directory(f"workspace_plans/{DATE}")
    count = 65 if kind == "runs" else 257
    for number in range(count):
        name = f"{number:032x}.json" if kind == "runs" else f"ignored-{number}.txt"
        (store.root / f"workspace_plans/{DATE}" / name).write_bytes(b"")
    expected = "HISTORY_RUN_COUNT_BOUND_EXCEEDED" if kind == "runs" else "HISTORY_RUN_DIRECTORY_BOUND_EXCEEDED"
    result = h.read_history(SimpleNamespace(store=store), DATE)
    assert result["plan_product"]["reason"] == expected
    assert result["read_context"]["candidate_count_known"] is False
    return dict(reason=expected)


def main():
    source = Path(h.__file__)
    source_before = hashlib.sha256(source.read_bytes()).hexdigest()
    caps = (h._MAX_PLAN_BYTES, h._MAX_SCAN_BYTES, h._MAX_RUNS, h._MAX_ATTEMPT_BYTES)
    assert caps == (33554432, 67108864, 64, 65536)
    run_case("actual_original_inventory_sizes_late_journals", actual_inventory)
    for kind in ("oversize", "malformed_json", "non_mapping", "invalid_start", "invalid_state",
                 "unsafe_flags", "wrong_input_shape", "directory", "fifo"):
        run_case("bad_journal_" + kind, lambda store, kind=kind: bad_journal(store, kind))
    run_case("missing_journals_actual_64mib_budget", missing_journal_bounded)
    run_case("missing_early_journal_never_admits_history", missing_early_journal)
    run_case("started_equal_boundary_not_pruned", boundary_equal)
    run_case("legacy_early_start_late_finish_owner_verified", early_start_late_finish)
    run_case("explicit_context_late_finish_still_rejected", context_late_finish)
    run_case("eligible_latest_still_requires_owner_on_full_read", eligible_latest)
    run_case("invalid_latest_fails_closed", invalid_latest)
    run_case("late_corrupt_body_excluded_without_admission", late_corrupt_body_only_excluded)
    run_case("existing_64_run_bound", lambda store: directory_bound(store, "runs"))
    run_case("existing_256_entry_bound", lambda store: directory_bound(store, "entries"))
    source_after = hashlib.sha256(source.read_bytes()).hexdigest()
    report = dict(scope="SYNTHETIC_INDEPENDENT_REVIEW_NOT_MAC_OR_MARKET_EVIDENCE",
        python=sys.version, checked_at_utc=datetime.now(timezone.utc).isoformat(),
        candidate_source=str(source), source_sha256_before=source_before,
        source_sha256_after=source_after, source_stable_during_review=source_before == source_after,
        limits=dict(plan_bytes=caps[0], cumulative_plan_bytes=caps[1], runs=caps[2], journal_bytes=caps[3]),
        cases=CASES, passed=len(CASES))
    (HERE / "history_review_results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, sort_keys=True))
    assert source_before == source_after, "Candidate changed concurrently; repeat the review."


if __name__ == "__main__":
    main()
