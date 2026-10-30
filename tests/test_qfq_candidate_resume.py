"""Small preserved artifacts exercise publication/CAS and phase failure boundaries."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_qfq as q
from ops import macos_research_panel_daily as daily
from ops import macos_research_panel_daily_authority as authority
from infrastructure.scheduling.execution_ledger import ExecutionLedger

spec = importlib.util.spec_from_file_location("candidate_resume_under_test", Path(__file__).resolve().parents[1] / "ops/resume_qfq_candidate.py")
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)


def save(path, obj):
    q._json(path, obj)
    return resume.reference(path)


def parquet(path, meta, count=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    names = ["ts_code", "trade_date", "exchange", "name", "market_type", "open", "high", "low", "close", "volume"]
    table = pa.table({name: ["000001.SZ"] * count for name in names})
    table = table.replace_schema_metadata({q.META_KEY: json.dumps(meta).encode()})
    pq.write_table(table, path)


@pytest.fixture
def case(tmp_path, monkeypatch):
    data = tmp_path / "data"
    app = Path(q.__file__).resolve().parents[1]
    pointers = {"selector": data / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
                "backtest": data / "backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt"}
    for role, pointer in pointers.items():
        old = tmp_path / (role + "_old.parquet")
        old.write_bytes(b"old immutable " + role.encode())
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(str(old) + "\n")
    baseline = q.baseline_binding(pointers)
    contract_csv = tmp_path / "contract.csv"
    contract_csv.write_text("original contract")
    raw = tmp_path / "raw.day"
    raw.write_bytes(b"unchanged source bytes")
    summary = dict(target_date="20261030", run_id="original_sync", target_count=1, accepted_count=1,
                   quarantine_count=0, pending_count=0, target_fingerprint="original_scope")
    summary_ref = save(tmp_path / "summary.json", summary)
    config_ref = save(tmp_path / "config.json", dict(prequery_sync_ref=summary_ref))
    snapshot = dict(asof_date=20261030, source_files=[resume.reference(raw)],
        symbols={"000001.SZ": dict(raw_files=[resume.reference(raw)])}, research_factor_receipts=dict(configuration=config_ref))
    save(q.input_path(data), snapshot)
    driver = app / "ops/vendor/data_layer_daily_formula_increment_update_v1.py"
    formula = app / "components/a_formula/build_canonical_formula_research_panel.py"
    identity = q.generation_identity(snapshot, driver, formula, contract_csv)
    baseline_hashes = {r: item["target_sha256"] for r, item in baseline["roles"].items()}
    generation = q.canonical_sha(dict(target=20261030, baseline_panel_sha256=baseline_hashes, **identity))
    run = tmp_path / ("qfq_" + generation[:20])
    retained = save(run / "adjustment_input_snapshot.json", snapshot)
    meta = dict(schema="a_share_qfq_panel_v1", asof_date=20261030, generation_id=generation,
        generation_manifest_path=str(run / "candidate_receipt.json"), snapshot_file_sha256=q.sha(q.input_path(data)),
        adjustment_snapshot=retained, baseline_panel_sha256=baseline_hashes, convention="ORIGINAL_CONVENTION", **identity, **q.FLAGS)
    candidates = {r: data / (r + ".parquet") for r in pointers}
    counts = {r: dict(panel_rows=3, quarantined_old_rows=2, target_date_symbols=1) for r in pointers}
    artifacts = {}
    for role, path in candidates.items():
        parquet(path, meta)
        sidecar = run / (role + "_quarantine.parquet")
        parquet(sidecar, {}, count=2)
        artifacts[role] = dict(**resume.reference(sidecar), rows=2, original_sha256=baseline_hashes[role],
                               original_path=baseline["roles"][role]["target_path"])
    quarantine = save(run / "quarantine_manifest.json", dict(generation_id=generation, counts=counts, artifacts=artifacts,
        excluded_from_accepted=True, legacy_basis_unknown=True, inherited_quarantine_manifests=[]))
    receipt = dict(status="CANDIDATE_READY", target_date=20261030, run_dir=str(run),
        candidates={r: str(p) for r, p in candidates.items()}, candidate_sha256={r: q.sha(p) for r, p in candidates.items()},
        quarantine_manifest=quarantine, counts=counts, **meta)
    receipt_ref = save(run / "candidate_receipt.json", receipt)
    baseline_ref = save(q.input_path(data).with_name("qfq_expected_current.json"), baseline)
    receipt_root = tmp_path / "receipts"
    sync = dict(status="READY", target_date=20261030, files=[str(raw)], authority=summary,
                **{k: summary[k] for k in ("target_count", "accepted_count", "quarantine_count", "pending_count", "target_fingerprint")})
    save(receipt_root / "a_sync_authority.json", sync)
    reader = pointers["selector"].with_name("DATA_LAYER_INTERFACE.py")
    reader.write_text("# original reader bytes\n")
    calls = []
    def product(**options):
        calls.append("product")
        return dict(status="PARTIAL_WITH_ROWS")
    modules = dict(macos_research_panel_daily_authority=SimpleNamespace(
        _audit_sync_scope=lambda *a: {k: summary[k] for k in ("target_count", "accepted_count", "quarantine_count", "pending_count", "target_fingerprint")},
        _formula_artifact_binding=authority._formula_artifact_binding),
        macos_research_panel_daily_receipts=SimpleNamespace(build_a_lane_outcome=lambda *a: dict(status="PARTIAL", target_date="20261030")),
        macos_research_panel_daily=daily, research_panel_daily_product=SimpleNamespace(materialize_daily_product=product))
    ctx = dict(data=data, app=app, env=dict(V4_RESEARCH_PANEL_A_CANONICAL_FORMULA=str(formula),
        V4_RESEARCH_PANEL_A_CONTRACT_CSV=str(contract_csv), V4_RESEARCH_PANEL_RECEIPT_ROOT=str(receipt_root),
        V4_RESEARCH_PANEL_A_TDX_ROOT=str(tmp_path / "tdx"), V4_RESEARCH_PANEL_A_RETURN_ROOT=str(tmp_path)),
        modules=modules, ledger=ExecutionLedger(tmp_path / "dispatcher"), code_refs=[resume.reference(Path(q.__file__))],
        manifest_ref=save(tmp_path / "manifest.json", dict(original=True)), product_config_ref=config_ref)
    monkeypatch.setattr(q, "load_snapshot", lambda path, target: snapshot)
    monkeypatch.setattr(q, "factor_cache_identity", lambda *a: "original_factor_identity")
    monkeypatch.setattr(resume, "context", lambda ref: ctx)
    plan = dict(schema=resume.SCHEMA, mode="MANUAL_AUTHORIZED_REPAIR_NOT_NATURAL", plist=ctx["manifest_ref"],
        main_manifest=ctx["manifest_ref"], helper=resume.reference(resume.__file__), baseline_ref=baseline_ref,
        baseline=baseline, inspection=resume.inspect_candidate(ctx, receipt_ref, baseline),
        product_runtime=resume.product_runtime_binding(ctx["env"], 20261030),
        preserved_failed_stage=save(tmp_path / "BEFORE_stage_status.json", dict(status="FAILED", error="original release gate")), **q.FLAGS)
    plan_ref = save(tmp_path / "resume_plan.json", plan)
    review_ref = save(tmp_path / "review.json", dict(verdict="PASS", reviewer="independent_review", resume_plan_sha256=plan_ref["sha256"]))
    def already_current(**options):
        calls.append("fastpath")
        assert options["refresh_inputs"] is False and options["publish"] is True
        return dict(status="READY", already_current=True, selector=str(candidates["selector"]), backtest=str(candidates["backtest"]), authority={})
    monkeypatch.setattr(q, "run_daily_rebuild", already_current)
    monkeypatch.setattr(q, "verify_release_gate", lambda *a: calls.append("release_gate"))
    return SimpleNamespace(root=tmp_path, ctx=ctx, pointers=pointers, receipt=receipt, receipt_ref=receipt_ref,
        baseline=baseline, plan=plan, plan_ref=plan_ref, review_ref=review_ref, calls=calls, raw=raw, snapshot=snapshot)


def test_original_pair_and_tail_then_fastpath_and_receipt(case):
    out = resume.execute(case.plan_ref, case.review_ref)
    assert out["status"] == "COMPLETED" and out["price_pair_published"] is True
    assert case.calls == ["release_gate", "fastpath", "product"]
    assert out["lanes"]["overall_status"] == "PARTIAL"
    for role, pointer in case.pointers.items():
        assert pointer.read_text() == case.receipt["candidates"][role] + "\n"
    run = Path(case.receipt["run_dir"])
    assert json.loads((run / "stage_status.json").read_text())["status"] == "READY"
    assert json.loads((run / "task_summary.json").read_text())["final_status"] == "PASS_QFQ_FULL_HISTORY"
    assert json.loads(Path(case.receipt_ref["path"]).read_text())["status"] == "CANDIDATE_READY"


def test_gate_failure_never_changes_current(case, monkeypatch):
    before = {r: p.read_bytes() for r, p in case.pointers.items()}
    monkeypatch.setattr(q, "verify_release_gate", lambda *a: (_ for _ in ()).throw(q.QfqGateError("ORACLE_NOT_ACCEPTED")))
    out = resume.execute(case.plan_ref, case.review_ref)
    assert out["status"] == "FAILED" and out["phase"] == "PREPUBLICATION_VALIDATION"
    assert {r: p.read_bytes() for r, p in case.pointers.items()} == before
    assert not case.calls


def test_product_failure_keeps_committed_pair_and_can_finish(case):
    product = case.ctx["modules"]["research_panel_daily_product"]
    original = product.materialize_daily_product
    product.materialize_daily_product = lambda **kw: (_ for _ in ()).throw(ValueError("SOURCE_PRODUCT_GAP"))
    out = resume.execute(case.plan_ref, case.review_ref)
    assert out["status"] == "FAILED" and out["phase"] == "ORIGINAL_DAILY_PRODUCT" and out["price_pair_published"] is True
    for role, p in case.pointers.items():
        assert p.read_text().strip() == case.receipt["candidates"][role]
    product.materialize_daily_product = original
    out = resume.execute(case.plan_ref, case.review_ref)
    assert out["status"] == "COMPLETED"


@pytest.mark.parametrize("bad", ["candidate_bytes", "snapshot_bytes", "raw_bytes", "baseline", "sync", "reader"])
def test_drift_fails_before_publish(case, bad):
    if bad == "candidate_bytes": Path(case.receipt["candidates"]["selector"]).write_bytes(b"drift")
    if bad == "snapshot_bytes": q.input_path(case.ctx["data"]).write_text("{}")
    if bad == "raw_bytes": case.raw.write_bytes(b"drift")
    if bad == "baseline": case.pointers["selector"].write_text("changed\n")
    if bad == "sync": save(Path(case.ctx["env"]["V4_RESEARCH_PANEL_RECEIPT_ROOT"]) / "a_sync_authority.json", dict(status="READY", authority={}))
    if bad == "reader": case.pointers["selector"].with_name("DATA_LAYER_INTERFACE.py").write_text("# drift")
    out = resume.execute(case.plan_ref, case.review_ref)
    assert out["status"] == "FAILED" and out["phase"] == "PREPUBLICATION_VALIDATION"
    assert not case.calls


def test_independent_review_must_bind_exact_plan(case):
    bad = save(case.root / "bad_review.json", dict(verdict="PASS", reviewer=resume.WRITER, resume_plan_sha256=case.plan_ref["sha256"]))
    with pytest.raises(q.QfqGateError, match="INDEPENDENT_REVIEW_REQUIRED"):
        resume.execute(case.plan_ref, bad)


def test_original_lane_lock_prevents_duplicate_owner(case):
    fd = case.ctx["ledger"].try_acquire_scheduler_lane("A_LONG")
    try:
        with pytest.raises(q.QfqGateError, match="A_LONG_OWNER_ALREADY_ACTIVE"):
            resume.execute(case.plan_ref, case.review_ref)
    finally:
        resume.os.close(fd)


def test_fastpath_required_no_fallthrough_rebuild(case, monkeypatch):
    monkeypatch.setattr(q, "run_daily_rebuild", lambda **kw: dict(status="READY", already_current=False))
    out = resume.execute(case.plan_ref, case.review_ref)
    assert out["status"] == "FAILED" and out["phase"] == "ORIGINAL_ALREADY_CURRENT"
    assert out["price_pair_published"] is True and "product" not in case.calls


@pytest.mark.parametrize("bad", ["code", "quarantine", "source_stat", "factor_semantics"])
def test_remaining_frozen_bindings_fail_before_publish(case, monkeypatch, bad):
    if bad == "code":
        monkeypatch.setattr(q, "generation_identity", lambda *a: dict(input_sha256="wrong"))
    if bad == "quarantine":
        Path(case.receipt["quarantine_manifest"]["path"]).write_text("{}")
    if bad == "source_stat":
        st = case.raw.stat()
        resume.os.utime(case.raw, ns=(st.st_atime_ns, st.st_mtime_ns + 1000))
    if bad == "factor_semantics":
        monkeypatch.setattr(q, "factor_cache_identity", lambda *a: "changed_factor_semantics")
    out = resume.execute(case.plan_ref, case.review_ref)
    assert out["status"] == "FAILED" and out["phase"] == "PREPUBLICATION_VALIDATION" and not case.calls


def test_original_pair_failure_rolls_back_without_advancing(case, monkeypatch):
    before = {r: p.read_bytes() for r, p in case.pointers.items()}
    original = q._write
    failed = []
    def fail_once(path, raw):
        if Path(path) == case.pointers["backtest"] and raw != before["backtest"] and not failed:
            failed.append(True)
            raise OSError("synthetic second pointer failure")
        return original(path, raw)
    monkeypatch.setattr(q, "_write", fail_once)
    out = resume.execute(case.plan_ref, case.review_ref)
    assert out["status"] == "FAILED" and out["phase"] == "ORIGINAL_PAIR_PUBLICATION"
    assert {r: p.read_bytes() for r, p in case.pointers.items()} == before
    journal = q.input_path(case.ctx["data"]).with_name("qfq_publication.json")
    assert json.loads(journal.read_text())["status"] == "ROLLED_BACK"
    assert case.calls == ["release_gate"]


@pytest.mark.parametrize("configured", [True, False])
def test_product_environment_restored_exactly_and_stale_values_removed(monkeypatch, configured):
    for key in resume.PRODUCT_RUNTIME_KEYS:
        monkeypatch.setenv(key, "/stale/inherited/" + key)
    env = {key: "/reviewed/main/" + key for key in resume.PRODUCT_RUNTIME_KEYS} if configured else {}
    resume.restore_release_environment(env)
    assert {key: resume.os.environ.get(key) for key in resume.PRODUCT_RUNTIME_KEYS} == {
        key: env.get(key) for key in resume.PRODUCT_RUNTIME_KEYS}


def test_product_runtime_binds_labels_and_initial_cache_but_allows_original_writes(tmp_path):
    labels = tmp_path / "labels"
    labels.mkdir()
    cache_ref = save(tmp_path / "accepted_label_history.json", dict(evaluations={"20261029": {}}))
    result_ref = save(tmp_path / "accepted_label_result.json", dict(symbol="000001.SZ", status="COMPLETE_DESCRIPTIVE_NONPIT", history_cache=cache_ref))
    index = dict(history_sync={"20261029": dict(stock_results={"000001.SZ": result_ref})})
    save(labels / "index.json", index)
    store = tmp_path / "event.sqlite3"
    store.write_bytes(b"existing cache identity")
    output = tmp_path / "statistics"
    output.mkdir()
    env = dict(zip(resume.PRODUCT_RUNTIME_KEYS, map(str, (labels, store, output))))
    bound = resume.product_runtime_binding(env, 20261030)
    resume.validate_product_runtime(bound, env, 20261030, published=False)
    store.write_bytes(b"original product updated cache")
    with pytest.raises(q.QfqGateError, match="PRODUCT_RUNTIME_BINDING_DRIFT"):
        resume.validate_product_runtime(bound, env, 20261030, published=False)
    index["dates"] = {"20261030": {"original_product": True}}
    save(labels / "index.json", index)
    resume.validate_product_runtime(bound, env, 20261030, published=True)
    Path(cache_ref["path"]).write_text("changed immutable accepted labels")
    with pytest.raises(q.QfqGateError, match="SOURCE_BINDING_FAILED"):
        resume.validate_product_runtime(bound, env, 20261030, published=True)
