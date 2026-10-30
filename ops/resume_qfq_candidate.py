"""Finish a preserved original QFQ candidate; never collect or rebuild prices.

Run this file directly with PYTHONPATH pointing at the verified Main release.
Preparation writes only the requested plan. Publication requires a bound review.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import base64
import importlib
import json
import os
from pathlib import Path
import plistlib

from ops import research_panel_qfq as q

FLAGS = q.FLAGS
WRITER = "/root/sop_binding_writer"
SCHEMA = "qfq_preserved_candidate_resume.v1"
EXTRA_RECEIPT_KEYS = {"status", "target_date", "run_dir", "candidates", "quarantine_manifest", "counts", "candidate_sha256"}
MODULES = ("research_panel_qfq", "research_panel_factor_cache", "research_panel_adjustment_inputs",
           "research_panel_tdx_adjustment_inputs", "research_panel_daily_source", "macos_research_panel_daily_authority",
           "macos_research_panel_daily_receipts", "macos_research_panel_daily", "research_panel_daily_product")
PRODUCT_RUNTIME_KEYS = ("V4_RESEARCH_EVENT_LABEL_SOURCE_ROOT", "V4_RESEARCH_EVENT_CASE_CACHE", "V4_WORKBENCH_STATISTICS_ROOT")


def reference(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=q.sha(path))


def checked(ref):
    return q._source(ref, owner="preserved candidate resume")


def value(ref):
    return json.loads(checked(ref).read_text())


def require(ok, reason):
    if not ok:
        raise q.QfqGateError("RESUME_" + reason)


def restore_release_environment(env):
    for name in ("V4_RELEASE_MANIFEST_PATH", "V4_RELEASE_MANIFEST_SHA256", "V4_RESEARCH_DAILY_PRODUCT_CONFIG",
                 "V4_RESEARCH_PANEL_RECEIPT_ROOT", "V4_A_SHARE_DAILY_PRODUCT_ROOT", *PRODUCT_RUNTIME_KEYS):
        if name in env:
            os.environ[name] = env[name]
        else:
            os.environ.pop(name, None)


def product_runtime_binding(env, target, *, include_mutable_identity=True):
    """Original operational paths, immutable label refs and initial cache bytes.

    SQLite and the product index can legitimately change during materialization.
    Their initial identities gate first publication, not a retry after publication.
    """
    bound = {key: dict(configured=False) for key in PRODUCT_RUNTIME_KEYS}
    for key in PRODUCT_RUNTIME_KEYS:
        if key not in env:
            continue
        path = Path(env[key])
        require(path.is_absolute() and not path.is_symlink() and path.resolve(strict=True) == path, "PRODUCT_RUNTIME_PATH:" + key)
        item = dict(configured=True, path=str(path))
        if key == "V4_RESEARCH_EVENT_LABEL_SOURCE_ROOT":
            require(path.is_dir(), "LABEL_SOURCE_DIRECTORY_REQUIRED")
            index_ref = reference(path / "index.json")
            index = value(index_ref)
            labels = {}
            for day, sync in sorted(index.get("history_sync", {}).items()):
                if int(day) <= target:
                    labels.update(sync.get("stock_results", {}))
            history = {}
            for symbol, result_ref in labels.items():
                result = value(result_ref)
                require(result.get("symbol") == symbol and result.get("status") == "COMPLETE_DESCRIPTIVE_NONPIT", "LABEL_RESULT_IDENTITY")
                checked(result["history_cache"])
                history[symbol] = dict(result=result_ref, history_cache=result["history_cache"])
            item.update(role="READ_ACCEPTED_LABELS", labels=history)
            if include_mutable_identity:
                item["pre_execution_index"] = index_ref
        elif key == "V4_RESEARCH_EVENT_CASE_CACHE":
            require(path.is_file(), "EXISTING_EVENT_CACHE_REQUIRED")
            item["role"] = "MUTABLE_EXISTING_SQLITE_CACHE"
            if include_mutable_identity:
                item["pre_execution_identity"] = [reference(p) for p in (path, Path(str(path) + "-wal")) if p.is_file()]
        else:
            require(path.is_dir(), "EXISTING_STATISTICS_OUTPUT_REQUIRED")
            item["role"] = "ORIGINAL_STATISTICS_OUTPUT_DIRECTORY"
        bound[key] = item
    return bound


def validate_product_runtime(expected, env, target, *, published):
    current = product_runtime_binding(env, target, include_mutable_identity=not published)
    if published:
        expected = {key: {k: v for k, v in item.items() if k not in ("pre_execution_identity", "pre_execution_index")}
                    for key, item in expected.items()}
    require(current == expected, "PRODUCT_RUNTIME_BINDING_DRIFT")


def context(plist_ref):
    plist = plistlib.loads(checked(plist_ref).read_bytes())
    env = plist["EnvironmentVariables"]
    app = Path(plist["WorkingDirectory"]).resolve()
    manifest_ref = dict(path=env["V4_RELEASE_MANIFEST_PATH"], sha256=env["V4_RELEASE_MANIFEST_SHA256"])
    manifest = value(manifest_ref)
    require(Path(manifest["app_root"]).resolve() == app == Path(q.__file__).resolve().parents[1], "MAIN_IMPORT_ROOT_CONFLICT")
    inventory = {r["path"]: r["sha256"] for r in manifest["application_inventory"]["entries"] if r.get("kind", "file") == "file"}
    code_refs = []
    modules = {}
    for name in MODULES:
        module = importlib.import_module("ops." + name)
        path = Path(module.__file__).resolve()
        relative = str(path.relative_to(app))
        require(inventory.get(relative) == q.sha(path), "MAIN_SOURCE_INVENTORY_DRIFT:" + relative)
        modules[name] = module
        code_refs.append(reference(path))
    ledger_module = importlib.import_module("infrastructure.scheduling.execution_ledger")
    ledger_path = Path(ledger_module.__file__).resolve()
    require(inventory.get(str(ledger_path.relative_to(app))) == q.sha(ledger_path), "LANE_OWNER_SOURCE_DRIFT")
    code_refs.append(reference(ledger_path))
    required = (q.publication_lock, q.verify_release_gate, q.publish_pair, q.check_baseline, q.factor_cache_identity,
        q.run_daily_rebuild, modules["macos_research_panel_daily_authority"]._formula_artifact_binding,
        modules["macos_research_panel_daily_receipts"].build_a_lane_outcome,
        modules["macos_research_panel_daily"].run_lanes, modules["research_panel_daily_product"].materialize_daily_product)
    require(all(callable(fn) for fn in required), "ORIGINAL_PHASE_API_UNAVAILABLE")
    # Restore only the existing release's relevant settings; no new config path.
    restore_release_environment(env)
    product_config, product_config_ref = modules["research_panel_daily_product"].config()
    data = Path(env["V4_RESEARCH_PANEL_A_DATA_ROOT"]).resolve()
    return dict(env=env, app=app, manifest_ref=manifest_ref, code_refs=code_refs, modules=modules,
                ledger=ledger_module.ExecutionLedger(Path(env["V4_DISPATCH_LEDGER_ROOT"])), data=data,
                product_config=product_config, product_config_ref=product_config_ref)


@contextmanager
def lane_owner(ctx):
    fd = ctx["ledger"].try_acquire_scheduler_lane("A_LONG")
    require(fd is not None, "A_LONG_OWNER_ALREADY_ACTIVE")
    try:
        yield
    finally:
        # Original stable inode/inherited ownership protocol: close, never unlink.
        os.close(fd)


def _already_published(ctx, receipt, baseline):
    pointers = {role: Path(item["pointer_path"]) for role, item in baseline["roles"].items()}
    expected_after = {role: path + "\n" for role, path in receipt["candidates"].items()}
    if not all(path.read_text(encoding="utf-8-sig") == expected_after[role] for role, path in pointers.items()):
        return False
    journal = json.loads((q.input_path(ctx["data"]).parent / "qfq_publication.json").read_text())
    require(journal.get("status") == "COMMITTED" and journal.get("after") == expected_after
            and journal.get("pointers") == {r: str(p) for r, p in pointers.items()}, "PUBLISHED_PAIR_JOURNAL_CONFLICT")
    for role, item in baseline["roles"].items():
        require(q.hashlib.sha256(base64.b64decode(journal["before_base64"][role])).hexdigest() == item["pointer_sha256"],
                "PUBLISHED_PAIR_BASELINE_CONFLICT")
    return True


def inspect_candidate(ctx, candidate_ref, baseline, *, published=False):
    """Full byte checks followed by stats; no computation or publication."""
    receipt = value(candidate_ref)
    target = receipt["asof_date"]
    require(receipt.get("status") == "CANDIDATE_READY" and receipt.get("target_date") == target
            and all(receipt.get(k) == v for k, v in FLAGS.items()), "CANDIDATE_STATE_OR_SAFETY")
    run = checked(candidate_ref).parent
    require(Path(receipt["run_dir"]) == run and Path(receipt["generation_manifest_path"]) == checked(candidate_ref), "RUN_DIR_CONFLICT")
    require(set(receipt["candidates"]) == set(receipt["candidate_sha256"]) == set(baseline["roles"]) == {"selector", "backtest"}, "ROLE_SCOPE")
    pointers = {role: Path(item["pointer_path"]) for role, item in baseline["roles"].items()}
    expected_pointers = dict(selector=ctx["data"] / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
                             backtest=ctx["data"] / "backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt")
    require(pointers == expected_pointers, "ORIGINAL_POINTER_SCOPE")
    if not published:
        q.check_baseline(pointers, baseline)
    snapshot_file = q.input_path(ctx["data"])
    snapshot = q.load_snapshot(snapshot_file, target)
    retained = value(receipt["adjustment_snapshot"])
    require(snapshot == retained and q.sha(snapshot_file) == receipt["snapshot_file_sha256"] == receipt["adjustment_snapshot"]["sha256"], "INPUT_SNAPSHOT_CHANGED")
    env = ctx["env"]
    driver = ctx["app"] / "ops/vendor/data_layer_daily_formula_increment_update_v1.py"
    formula = Path(env["V4_RESEARCH_PANEL_A_CANONICAL_FORMULA"]).resolve()
    contract_csv = Path(env["V4_RESEARCH_PANEL_A_CONTRACT_CSV"]).resolve()
    identity = q.generation_identity(snapshot, driver, formula, contract_csv)
    require(all(receipt.get(k) == v for k, v in identity.items()), "GENERATION_SOURCE_IDENTITY_DRIFT")
    baseline_hashes = {role: item["target_sha256"] for role, item in baseline["roles"].items()}
    generation = q.canonical_sha(dict(target=target, baseline_panel_sha256=baseline_hashes, **identity))
    require(generation == receipt["generation_id"] and receipt["baseline_panel_sha256"] == baseline_hashes, "GENERATION_ID_CONFLICT")
    require(run.name == "qfq_" + generation[:20], "GENERATION_DIRECTORY_CONFLICT")
    meta = {k: v for k, v in receipt.items() if k not in EXTRA_RECEIPT_KEYS}
    for role, path in receipt["candidates"].items():
        candidate = checked(dict(path=path, sha256=receipt["candidate_sha256"][role]))
        require(ctx["data"] in candidate.parents and q.panel_contract(candidate) == meta, "CANDIDATE_FOOTER_CONFLICT:" + role)
        require(q.pq.ParquetFile(candidate).metadata.num_rows == receipt["counts"][role]["panel_rows"], "CANDIDATE_ROW_COUNT:" + role)
        if role == "selector":
            require({"ts_code", "trade_date", "exchange", "name", "market_type", "open", "high", "low", "close", "volume"}
                    <= set(q.pq.ParquetFile(candidate).schema_arrow.names), "PRODUCT_READER_SCHEMA:" + role)
    quarantine = value(receipt["quarantine_manifest"])
    require(quarantine.get("generation_id") == generation and quarantine.get("excluded_from_accepted") is True
            and quarantine.get("legacy_basis_unknown") is True and quarantine.get("counts") == receipt["counts"], "QUARANTINE_MANIFEST_CONFLICT")
    require(set(quarantine["artifacts"]) == set(pointers), "QUARANTINE_ROLE_SCOPE")
    for role, artifact in quarantine["artifacts"].items():
        path = checked(artifact)
        require(artifact["original_sha256"] == baseline_hashes[role]
                and artifact["original_path"] == baseline["roles"][role]["target_path"]
                and q.pq.ParquetFile(path).metadata.num_rows == artifact["rows"] == receipt["counts"][role]["quarantined_old_rows"], "QUARANTINE_ARTIFACT_CONFLICT")
    for ref in quarantine.get("inherited_quarantine_manifests", []):
        checked(ref)
    refs = snapshot["source_files"] + [ref for item in snapshot["symbols"].values() for ref in item["raw_files"]]
    stats = []
    for ref in refs:
        path = checked(ref)
        st = path.stat()
        stats.append(dict(path=str(path), size=st.st_size, mtime_ns=st.st_mtime_ns))
    sync_ref = snapshot["research_factor_receipts"]["configuration"]
    config = value(sync_ref)
    raw_sync = value(config["prequery_sync_ref"])
    sync_receipt_ref = reference(Path(env["V4_RESEARCH_PANEL_RECEIPT_ROOT"]) / "a_sync_authority.json")
    sync_receipt = value(sync_receipt_ref)
    require(sync_receipt.get("status") == "READY" and sync_receipt.get("authority") == raw_sync
            and str(sync_receipt.get("target_date")) == str(target), "SAVED_SYNC_OUTCOME_CONFLICT")
    # Reuse the original normalizer's scope audit without invoking acquisition.
    authority = ctx["modules"]["macos_research_panel_daily_authority"]
    scope = authority._audit_sync_scope(Path(env["V4_RESEARCH_PANEL_A_TDX_ROOT"]), target,
                                        [Path(p) for p in sync_receipt["files"]], raw_sync)
    require(all(scope[k] == sync_receipt[k] for k in ("target_count", "accepted_count", "quarantine_count", "pending_count", "target_fingerprint")), "SAVED_SYNC_SCOPE_CONFLICT")
    if sync_receipt.get("formula_input_manifest"):
        manifest = Path(sync_receipt["formula_input_manifest"])
        checked(reference(manifest))
    readiness = dict(generation_id=generation, source_stats=stats,
        factor_cache_identity=q.factor_cache_identity(ctx["data"], target, snapshot),
        code_refs=[reference(p) for p in (driver, formula, contract_csv)])
    reader_ref = reference(pointers["selector"].with_name("DATA_LAYER_INTERFACE.py"))
    checked(reader_ref)
    return dict(identity=identity, meta=meta, readiness=readiness, sync_receipt=sync_receipt_ref, product_reader=reader_ref,
                source_sync=config["prequery_sync_ref"], product_config=ctx["product_config_ref"],
                module_refs=ctx["code_refs"], candidate_receipt=candidate_ref)


def prepare(plist_ref, candidate_ref):
    ctx = context(plist_ref)
    with lane_owner(ctx), q.publication_lock(ctx["data"]):
        baseline_ref = reference(q.input_path(ctx["data"]).with_name("qfq_expected_current.json"))
        baseline = value(baseline_ref)
        inspection = inspect_candidate(ctx, candidate_ref, baseline)
        product_runtime = product_runtime_binding(ctx["env"], inspection["meta"]["asof_date"])
    return dict(schema=SCHEMA, mode="MANUAL_AUTHORIZED_REPAIR_NOT_NATURAL", plist=plist_ref,
        main_manifest=ctx["manifest_ref"], helper=reference(__file__), baseline_ref=baseline_ref,
        baseline=baseline, inspection=inspection, product_runtime=product_runtime,
        original_failed_stage=reference(checked(candidate_ref).with_name("stage_status.json")), **FLAGS)


def execute(plan_ref, review_ref, *, complete_product=True):
    plan = value(plan_ref)
    review = value(review_ref)
    require(plan.get("schema") == SCHEMA and review.get("verdict") == "PASS"
            and review.get("reviewer") and review["reviewer"] != WRITER
            and review.get("resume_plan_sha256") == plan_ref["sha256"], "INDEPENDENT_REVIEW_REQUIRED")
    checked(plan["helper"])
    checked(plan["preserved_failed_stage"])
    require(plan["helper"] == reference(__file__), "HELPER_SOURCE_DRIFT")
    ctx = context(plan["plist"])
    require(ctx["manifest_ref"] == plan["main_manifest"], "MAIN_MANIFEST_CHANGED")
    receipt = value(plan["inspection"]["candidate_receipt"])
    baseline = plan["baseline"]
    pointers = {r: Path(v["pointer_path"]) for r, v in baseline["roles"].items()}
    result = dict(status="FAILED", phase="PREPUBLICATION_VALIDATION", mode=plan["mode"],
                  started_at=datetime.now(timezone.utc).isoformat(), plan=plan_ref, independent_review=review_ref, **FLAGS)
    with lane_owner(ctx):
        try:
            with q.publication_lock(ctx["data"]):
                published = _already_published(ctx, receipt, baseline)
                validate_product_runtime(plan["product_runtime"], ctx["env"], receipt["asof_date"], published=published)
                if not published:
                    checked(plan["baseline_ref"])
                inspection = inspect_candidate(ctx, plan["inspection"]["candidate_receipt"], baseline, published=published)
                require(inspection == plan["inspection"], "FROZEN_RESUME_PLAN_DRIFT")
                snapshot_file = q.input_path(ctx["data"])
                q.verify_release_gate(snapshot_file.parent, Path(receipt["candidates"]["selector"]), inspection["identity"],
                                      receipt["asof_date"], receipt["convention"])
                if not published:
                    result["phase"] = "ORIGINAL_PAIR_PUBLICATION"
                    expected = {r: p.read_bytes() for r, p in pointers.items()}
                    q.publish_pair(pointers, {r: Path(p) for r, p in receipt["candidates"].items()}, expected,
                                   snapshot_file.with_name("qfq_publication.json"), expected_baseline=baseline)
                result["price_pair_published"] = True
                result["phase"] = "ORIGINAL_PUBLICATION_TAIL"
                q._json(snapshot_file.with_name("qfq_expected_current.json"), q.baseline_binding(pointers))
                q._json(snapshot_file.with_name("qfq_readiness.json"), inspection["readiness"])
                ready = dict(receipt, status="READY", selector_pointer_ready=True, backtest_pointer_ready=True,
                    selector=receipt["candidates"]["selector"], backtest=receipt["candidates"]["backtest"],
                    authority=dict(final_status="PASS_QFQ_FULL_HISTORY", source_sha256=receipt["input_sha256"], generation_id=receipt["generation_id"]))
                code_refs = inspection["readiness"]["code_refs"]
                compatibility = dict(final_status="PASS_QFQ_FULL_HISTORY", run_dir=receipt["run_dir"], latest_trade_date=receipt["asof_date"],
                    selector_current_after=ready["selector"], backtest_current_after=ready["backtest"],
                    canonical_rebuild_stage_status="FULL_HISTORY_ORIGINAL_CANONICAL_PURE_FUNCTION", qfq_contract=inspection["meta"],
                    formula_processing=dict(worker_context=dict(driver_path=code_refs[0]["path"], driver_sha256=code_refs[0]["sha256"],
                        canonical_formula_path=code_refs[1]["path"], canonical_formula_sha256=code_refs[1]["sha256"])), **FLAGS)
                for name in ("meta.json", "task_summary.json"):
                    q._json(Path(receipt["run_dir"]) / name, compatibility)
                q._json(Path(receipt["run_dir"]) / "stage_status.json", ready)
            result["phase"] = "ORIGINAL_ALREADY_CURRENT"
            # This guard is checked before calling the original function. No refresh,
            # sync, provider, process pool or historical rebuild is permitted.
            for pointer in pointers.values():
                contract = q.panel_contract(Path(pointer.read_text().strip()))
                require(contract.get("generation_id") == receipt["generation_id"]
                        and all(contract.get(k) == v for k, v in inspection["identity"].items()), "ALREADY_CURRENT_GUARD")
            env = ctx["env"]
            formula = q.run_daily_rebuild(driver_path=Path(code_refs[0]["path"]), formula_path=Path(code_refs[1]["path"]),
                tdx_root=Path(env["V4_RESEARCH_PANEL_A_TDX_ROOT"]), data_root=ctx["data"], pointers=pointers,
                contract_csv=Path(code_refs[2]["path"]), return_root=Path(env["V4_RESEARCH_PANEL_A_RETURN_ROOT"]),
                target=receipt["asof_date"], publish=True, refresh_inputs=False)
            require(formula.get("already_current") is True, "ORIGINAL_FASTPATH_NOT_TAKEN")
            formula.update(ctx["modules"]["macos_research_panel_daily_authority"]._formula_artifact_binding(
                Path(formula["selector"]), Path(formula["backtest"])))
            # Exact count already proved by the preserved original candidate.
            formula["authority"]["selector_increment_rows"] = receipt["counts"]["selector"]["target_date_symbols"]
            result["formula"] = formula
            if complete_product:
                result["phase"] = "ORIGINAL_DAILY_PRODUCT"
                product = ctx["modules"]["research_panel_daily_product"].materialize_daily_product(
                    data_root=ctx["data"], target=receipt["asof_date"], formula_result=formula,
                    output_root=Path(env["V4_A_SHARE_DAILY_PRODUCT_ROOT"]) / "daily_products/a_share" if env.get("V4_A_SHARE_DAILY_PRODUCT_ROOT") else None)
                result["daily_product"] = product
                result["phase"] = "ORIGINAL_A_LANE_RECEIPT"
                outcome = ctx["modules"]["macos_research_panel_daily_receipts"].build_a_lane_outcome(
                    value(inspection["sync_receipt"]), formula, str(receipt["asof_date"]), None)
                outcome["daily_product"] = product
                lanes = ctx["modules"]["macos_research_panel_daily"].run_lanes(target_date=str(receipt["asof_date"]),
                    receipt_root=Path(env["V4_RESEARCH_PANEL_RECEIPT_ROOT"]), a_runner=lambda target: outcome,
                    hk_runner=lambda target: (_ for _ in ()).throw(AssertionError("HK_NOT_REQUESTED")), lane="A")
                result["lanes"] = lanes
                require(lanes["lanes"]["A"].get("status") in {"READY", "PARTIAL", "PARTIAL_WITH_ROWS"}, "A_LANE_RECEIPT_FAILED")
            result.update(status="COMPLETED", phase="COMPLETED")
        except Exception as error:
            # Once the original journal commits, later product/receipt failures
            # must not roll back a valid price pair or rewrite the old failure.
            result.update(error_type=type(error).__name__, error=str(error))
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
    return result


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--publish", action="store_true")
    parser.add_argument("--plist", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--candidate-sha256")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--review", type=Path)
    parser.add_argument("--review-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.prepare:
        result = prepare(reference(args.plist), dict(path=str(args.candidate.resolve()), sha256=args.candidate_sha256))
        before = checked(result["original_failed_stage"]).read_bytes()
        backup = args.output.parent / "BEFORE_stage_status.json"
        if backup.exists():
            require(backup.read_bytes() == before, "IMMUTABLE_FAILED_STAGE_BACKUP_CONFLICT")
        else:
            q._write(backup, before)
        result["preserved_failed_stage"] = reference(backup)
    else:
        require(args.output.resolve().parent == args.plan.resolve().parent, "RESULT_MUST_STAY_IN_PLAN_DIRECTORY")
        result = execute(dict(path=str(args.plan.resolve()), sha256=args.plan_sha256),
                         dict(path=str(args.review.resolve()), sha256=args.review_sha256))
    q._json(args.output, result)
    print(json.dumps(dict(status=result.get("status", "PREPARED"), phase=result.get("phase"), output=reference(args.output))))
    return 1 if result.get("status") == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
