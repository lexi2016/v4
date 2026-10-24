"""Adopt an accepted immutable pair through the original publisher; no producer.

The reviewed plan contains immutable before/after byte references. This outer
journal extends the original pointer CAS to the required acceptance metadata.
Readers that ignore the publication lock can observe the bounded transition.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROLES = {"selector", "backtest"}
METADATA = {"qfq_adjustment_input.json", "qfq_readiness.json",
            "qfq_expected_current.json", "qfq_futu_oracle.json",
            "qfq_convention_acceptance.json"}


class AdoptionConflict(RuntimeError):
    pass


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def source(ref):
    path = Path(ref["path"])
    if not path.is_absolute() or not path.is_file() or digest(path) != ref["sha256"]:
        raise AdoptionConflict(f"IMMUTABLE_REF_CONFLICT:{path}")
    return path


def payload(ref):
    return None if ref is None else source(ref).read_bytes()


def current(path):
    path = Path(path)
    if path.is_symlink():
        raise AdoptionConflict(f"MUTATION_SYMLINK_FORBIDDEN:{path}")
    return path.read_bytes() if path.exists() else None


def check_paths(config, snapshot):
    root = Path(config["data_root"]).resolve()
    cache = root / "runtime/cache/data_layer_daily_formula_increment_update_v1"
    pointers = {r: Path(p) for r, p in config["pointers"].items()}
    expected = {"selector": root / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
                "backtest": root / "backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt"}
    if pointers != expected or set(config["candidates"]) != ROLES:
        raise AdoptionConflict("EXACT_TWO_ROLE_SCOPE_REQUIRED")
    paths = [Path(m["path"]) for m in config["metadata"]]
    if len(paths) != len(set(paths)) or not paths:
        raise AdoptionConflict("DUPLICATE_OR_EMPTY_METADATA_SCOPE")
    closure = {Path(r["path"]).resolve() for r in snapshot["source_files"]}
    for path in paths:
        if path.parent != cache or path.name not in METADATA:
            raise AdoptionConflict(f"METADATA_SCOPE_FORBIDDEN:{path}")
        if path.resolve() in closure:
            raise AdoptionConflict(f"IMMUTABLE_SOURCE_CLOSURE_OVERWRITE:{path}")
    if set(p.name for p in paths) != METADATA:
        raise AdoptionConflict("REQUIRED_METADATA_SET_INCOMPLETE")
    for path in [*pointers.values(), *paths]:
        current(path)
        if path.parent.resolve() != path.parent:
            raise AdoptionConflict(f"MUTATION_PARENT_SYMLINK_FORBIDDEN:{path}")
    return pointers


def authorize(config_ref, review_ref, go_ref, start_ref):
    """Evidence is controller-issued, content-bound, and independently reviewed."""
    config_path = source(config_ref)
    config = json.loads(config_path.read_text())
    review = json.loads(source(review_ref).read_text())
    go = json.loads(source(go_ref).read_text())
    started = json.loads(source(start_ref).read_text())
    identity = {"plan_sha256": config_ref["sha256"], "helper_sha256": digest(__file__)}
    if (review.get("decision") != "PASS_DEFAULT_CANDIDATE_ADOPTION_INTEGRATION"
            or not review.get("reviewer_id") or review.get("writer_id") == review.get("reviewer_id")
            or any(review.get(k) != v for k, v in identity.items())):
        raise AdoptionConflict("INDEPENDENT_INTEGRATION_PASS_REQUIRED")
    if (go.get("decision") != "GO_DEFAULT_CANDIDATE_ADOPTION"
            or go.get("review_ref") != review_ref
            or go.get("plan_sha256") != config_ref["sha256"]
            or go.get("execution_id") != started.get("execution_id")
            or started.get("event_type") != "RUN_STARTED"
            or started.get("decision") != "RUN_STARTED"):
        raise AdoptionConflict("CONTROLLER_GO_AND_REGISTERED_START_REQUIRED")
    return config


def validate(q, config):
    for ref in config["code_refs"]:
        source(ref)
    if digest(q.__file__) != config["publisher_sha256"]:
        raise AdoptionConflict("PUBLISHER_CODE_CONFLICT")
    snapshot = json.loads(source(config["snapshot"]).read_text())
    pointers = check_paths(config, snapshot)
    # Reuse the accepted snapshot; only rebind its immutable source bytes.
    # This is the original publication integrity boundary, not a new data audit.
    refs = snapshot["source_files"] + [ref for item in snapshot.get("symbols", {}).values()
                                      for ref in item["raw_files"]]
    for ref in {r["path"]: r for r in refs}.values():
        source(ref)
    candidates = {r: source(ref) for r, ref in config["candidates"].items()}
    identity = config["identity"]
    if q.canonical_sha(snapshot) != identity["input_sha256"]:
        raise AdoptionConflict("CANONICAL_INPUT_CONFLICT")
    for role, path in candidates.items():
        contract = q.panel_contract(path)
        for key in ("generation_id", "input_sha256", *q._code_binding(identity)):
            if contract.get(key) != identity[key]:
                raise AdoptionConflict(f"CANDIDATE_IDENTITY_CONFLICT:{role}:{key}")
    expected = config["expected_baseline"]
    q.check_baseline(pointers, expected)
    for item in config["metadata"]:
        if current(item["path"]) != payload(item["before"]):
            raise AdoptionConflict(f"METADATA_BASELINE_CONFLICT:{item['path']}")
        source(item["after"])
    staged = {Path(m["path"]).name: source(m["after"]) for m in config["metadata"]}
    if len({p.parent for p in staged.values()}) != 1 or any(p.name != n for n, p in staged.items()):
        raise AdoptionConflict("STAGED_GATE_FILENAMES_OR_DIRECTORY_CONFLICT")
    if staged["qfq_adjustment_input.json"].read_bytes() != source(config["snapshot"]).read_bytes():
        raise AdoptionConflict("STAGED_SNAPSHOT_CONFLICT")
    future_baseline = dict(schema="qfq_expected_current_v1", roles={
        r: dict(pointer_path=str(pointers[r]), pointer_sha256=hashlib.sha256((str(p) + "\n").encode()).hexdigest(),
                target_path=str(p), target_sha256=config["candidates"][r]["sha256"])
        for r, p in candidates.items()})
    if json.loads(staged["qfq_expected_current.json"].read_text()) != future_baseline:
        raise AdoptionConflict("STAGED_NEXT_BASELINE_CONFLICT")
    readiness = json.loads(staged["qfq_readiness.json"].read_text())
    if readiness.get("generation_id") != identity["generation_id"]:
        raise AdoptionConflict("STAGED_READINESS_GENERATION_CONFLICT")
    oracle = json.loads(staged["qfq_futu_oracle.json"].read_text())
    original = json.loads(source(config["original_oracle_backup"]).read_text())
    for key in ("rows", "required_dates", "source_files", "observed_at", "asof_date"):
        if oracle.get(key) != original.get(key):
            raise AdoptionConflict(f"ORIGINAL_ORACLE_OBSERVATION_CHANGED:{key}")
    convention = json.loads(staged["qfq_convention_acceptance.json"].read_text())
    receipt = json.loads(source(convention["initial_oracle_receipt"]).read_text())
    if (convention.get("status") != "PASS" or not convention.get("reviewer_id")
            or convention.get("convention") != config["convention"]
            or convention.get("initial_asof_date") != config["target"]
            or convention.get("code_binding") != q._code_binding(identity)
            or receipt.get("status") != "PASS_FUTU_DISPLAY_ORACLE"
            or receipt.get("asof_date") != config["target"]
            or receipt.get("code_binding") != q._code_binding(identity)
            or receipt.get("input_sha256") != identity["input_sha256"]
            or receipt.get("candidate_sha256") != {r: v["sha256"] for r, v in config["candidates"].items()}):
        raise AdoptionConflict("NEW_CODE_CONVENTION_BINDING_CONFLICT")
    q.verify_release_gate(staged["qfq_futu_oracle.json"].parent, candidates["selector"],
                          identity, config["target"], config["convention"])
    return pointers, candidates


def _restore_metadata(q, metadata):
    for item in metadata:
        path, before = Path(item["path"]), payload(item["before"])
        if before is None:
            if path.exists():
                path.unlink()
                fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        else:
            q._write(path, before)


def rollback(q, record, journal):
    """Check the complete ownership set before restoring any path."""
    pointers = {r: Path(p) for r, p in record["pointers"].items()}
    before = {r: base64.b64decode(v) for r, v in record["pointer_before_base64"].items()}
    after = {r: (p + "\n").encode() for r, p in record["candidates"].items()}
    for role, path in pointers.items():
        if current(path) not in (before[role], after[role]):
            raise AdoptionConflict(f"ROLLBACK_POINTER_OWNERSHIP_CONFLICT:{role}")
    for item in record["metadata"]:
        if current(item["path"]) not in (payload(item["before"]), payload(item["after"])):
            raise AdoptionConflict(f"ROLLBACK_METADATA_OWNERSHIP_CONFLICT:{item['path']}")
    # Preserve the original publisher's exact two-pointer CAS and rollback logic.
    q.publish_pair(pointers, {r: Path(v.decode("utf-8-sig").strip()) for r, v in before.items()},
                   {r: p.read_bytes() for r, p in pointers.items()}, journal.with_name("rollback_pair.json"))
    _restore_metadata(q, record["metadata"])
    q._json(journal, {**record, "status": "ROLLED_BACK"})


def recover(q, config_ref, journal):
    """Explicit recovery uses the already-authorized durable transaction scope."""
    config = json.loads(source(config_ref).read_text())
    with q.publication_lock(Path(config["data_root"])):
        record = json.loads(Path(journal).read_text())
        if record.get("plan_ref") != config_ref:
            raise AdoptionConflict("RECOVERY_PLAN_CONFLICT")
        authorize(config_ref, record["review_ref"], record["go_ref"], record["start_ref"])
        if (digest(q.__file__) != config["publisher_sha256"]
                or record["metadata"] != config["metadata"]
                or record["pointers"] != config["pointers"]
                or record["candidates"] != {r: v["path"] for r, v in config["candidates"].items()}):
            raise AdoptionConflict("RECOVERY_TRANSACTION_SCOPE_CONFLICT")
        for role, value in record["pointer_before_base64"].items():
            if hashlib.sha256(base64.b64decode(value)).hexdigest() != config["expected_baseline"]["roles"][role]["pointer_sha256"]:
                raise AdoptionConflict("RECOVERY_POINTER_BACKUP_CONFLICT")
        check_paths(config, json.loads(source(config["snapshot"]).read_text()))
        if record.get("status") in ("PREPARED", "ROLLBACK_REQUIRED"):
            rollback(q, record, Path(journal))
        return json.loads(Path(journal).read_text())["status"]


def adopt(q, config_ref, review_ref, go_ref, start_ref, journal):
    config = authorize(config_ref, review_ref, go_ref, start_ref)
    journal = Path(journal)
    if journal.exists():
        raise AdoptionConflict("EXISTING_TRANSACTION_USE_EXPLICIT_RECOVERY")
    with q.publication_lock(Path(config["data_root"])):
        pointers, candidates = validate(q, config)
        record = dict(schema="EXISTING_CANDIDATE_ADOPTION_TRANSACTION_R1", status="PREPARED",
                      plan_ref=config_ref, review_ref=review_ref, go_ref=go_ref, start_ref=start_ref,
                      pointers={r: str(p) for r, p in pointers.items()},
                      candidates={r: str(p) for r, p in candidates.items()},
                      pointer_before_base64={r: base64.b64encode(p.read_bytes()).decode() for r, p in pointers.items()},
                      metadata=config["metadata"], research_only=True, production_allowed=False,
                      buy_gate_updated=False, orders_sent=False)
        q._json(journal, record)
        try:
            for item in config["metadata"]:
                if current(item["path"]) != payload(item["before"]):
                    raise AdoptionConflict(f"METADATA_CHANGED_DURING_ADOPTION:{item['path']}")
                q._write(Path(item["path"]), payload(item["after"]))
            q.publish_pair(pointers, candidates,
                           {r: base64.b64decode(v) for r, v in record["pointer_before_base64"].items()},
                           journal.with_name("publish_pair.json"), config["expected_baseline"])
            for item in config["metadata"]:
                if current(item["path"]) != payload(item["after"]):
                    raise AdoptionConflict(f"METADATA_READBACK_CONFLICT:{item['path']}")
            q._json(journal, {**record, "status": "COMMITTED"})
        except BaseException:
            try:
                rollback(q, record, journal)
            except BaseException as exc:
                q._json(journal, {**record, "status": "ROLLBACK_REQUIRED", "recovery_error": str(exc)})
                raise
            raise
    return {"status": "COMMITTED", "generation_id": config["identity"]["generation_id"],
            "journal": str(journal), "journal_sha256": digest(journal)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--review-sha256", required=True)
    parser.add_argument("--go", required=True)
    parser.add_argument("--go-sha256", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--start-sha256", required=True)
    parser.add_argument("--journal", required=True)
    args = parser.parse_args()
    plan_ref = {"path": args.plan, "sha256": args.plan_sha256}
    config = json.loads(source(plan_ref).read_text())
    publisher = source(config["publisher_source"])
    sys.path.insert(0, str(publisher.parent.parent))
    spec = importlib.util.spec_from_file_location("adoption_original_publisher", publisher)
    q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(q)
    print(json.dumps(adopt(q, plan_ref,
                          {"path": args.review, "sha256": args.review_sha256},
                          {"path": args.go, "sha256": args.go_sha256},
                          {"path": args.start, "sha256": args.start_sha256}, args.journal)))


if __name__ == "__main__":
    main()
