"""Independent read-only candidate review harness; no execution-module stub.

The only store writes are the unchanged historical repository unit fixture and
explicit corruption probes inside an automatically deleted TemporaryDirectory.
This is not live data, a producer repair, an API smoke test, or Mac evidence.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "candidate"
REFERENCES = ROOT / "readonly_references"
SUPPORT = ROOT / "support_source"
ATTACHED = ROOT / "source_package/V4_三路选股闭环_问题包_20261011/active_source"
REFERENCE_REF = "a1b722e4c82defcb9537d5c05915c6a8072c02d3"
FIXTURE_RELATIVE = "stage_center/tests/test_selection_consumer_batch3.py"
FIXTURE_BLOB_SHA1 = "95cb72cc630399ef32cf54b2371313705fc2acfe"
SELECTION_SHA256 = "31e80e068890be03957920870719030463262c78911953541be3074f8650d4c9"
sys.dont_write_bytecode = True
sys.path[:0] = [str(CANDIDATE), str(REFERENCES), str(SUPPORT), str(SUPPORT / "upstreams")]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_record(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha256(raw),
            "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def file_state(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): sha256(path.read_bytes())
            for path in sorted(root.rglob("*")) if path.is_file()}


def function_nodes(path: Path, names: set[str]) -> tuple[str, list[ast.FunctionDef]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names
    return source, nodes


def must_refuse_without_writes(store, helper, kwargs, error_type, expected: str) -> str:
    before = file_state(store.root)
    try:
        helper(store, **kwargs)
    except error_type as exc:
        message = str(exc)
        assert expected in message, message
    else:
        raise AssertionError("Invalid provenance was accepted")
    assert file_state(store.root) == before
    return message


def main() -> dict[str, Any]:
    selection_path = CANDIDATE / "stage_center/selection.py"
    consumer_path = CANDIDATE / "stage_center/consumer.py"
    fixture_path = REFERENCES / FIXTURE_RELATIVE
    assert source_record(selection_path)["sha256"] == SELECTION_SHA256
    assert source_record(fixture_path)["git_blob_sha1"] == FIXTURE_BLOB_SHA1

    # Use the exact downloaded original interprocess lock, not a replacement.
    import infrastructure
    infrastructure.__path__.insert(0, str(REFERENCES / "infrastructure"))
    from stage_center import selection
    assert Path(selection.__file__).resolve() == selection_path.resolve()

    helper_source, helper_nodes = function_nodes(consumer_path, {"_verified_selection_provenance"})
    _, attached_helper_nodes = function_nodes(ATTACHED / "stage_center/consumer.py", {"_verified_selection_provenance"})
    helper_ast = ast.dump(helper_nodes[0], include_attributes=False)
    assert helper_ast == ast.dump(attached_helper_nodes[0], include_attributes=False)
    helper_namespace = {"Any": Any, "Mapping": Mapping,
                        "SelectionStore": selection.SelectionStore, "SelectionError": selection.SelectionError}
    exec(compile(ast.Module(body=helper_nodes, type_ignores=[]), str(consumer_path), "exec"), helper_namespace)
    helper = helper_namespace["_verified_selection_provenance"]

    _, fixture_nodes = function_nodes(fixture_path, {"_a_row", "_hk_row", "_publish_both"})
    fixture_namespace = {"Path": Path, "select_a_stage": selection.select_a_stage,
                         "select_hk_four_lane": selection.select_hk_four_lane,
                         "publish_selection": selection.publish_selection}
    exec(compile(ast.Module(body=fixture_nodes, type_ignores=[]), str(fixture_path), "exec"), fixture_namespace)

    source_paths = [selection_path, consumer_path,
                    CANDIDATE / "v4/manager_research/workspace_daily_channels.py",
                    CANDIDATE / "v4/manager_research/workspace.py",
                    CANDIDATE / "tests/test_manager_three_lane_channels_r1.py",
                    fixture_path, ATTACHED / "stage_center/consumer.py"]
    source_before = {str(path): sha256(path.read_bytes()) for path in source_paths}
    results = []
    with tempfile.TemporaryDirectory(prefix="hk_original_selection_fixture_", dir=ROOT) as scratch:
        fixture_root = Path(scratch)
        fixture_namespace["_publish_both"](fixture_root)
        store = selection.SelectionStore(fixture_root)
        envelope = store.read_verified("20260813", "STAGE_0930_0935", "HK_CONNECT")
        original_envelope = deepcopy(envelope)
        kwargs = {"trade_date": "20260813", "stage_id": "STAGE_0930_0935", "market": "HK_CONNECT",
                  "run_id": envelope["run_id"]}
        before = file_state(fixture_root)
        provenance = helper(store, **kwargs)
        verified = store._verify_run(**kwargs)
        assert file_state(fixture_root) == before
        assert envelope == original_envelope
        assert provenance["selection_run_id"] == envelope["run_id"]
        assert provenance["selection_manifest_receipt_verified"] is True
        assert provenance["selection_artifact_sha256"] == verified["artifact_sha256"]
        assert provenance["selection_manifest_sha256"] == verified["manifest_sha256"]
        assert provenance["selection_receipt_sha256"] == verified["receipt_sha256"]
        assert provenance["selection_artifact_sha256"] != envelope["raw_artifact_sha256"]
        assert all(row["formal_eligible"] is False and row["action_level"] == "NO_BUY" for row in envelope["rows"])
        artifact_path = store.root / verified["artifact_relative"]
        manifest_path = artifact_path.with_name("manifest.json")
        receipt_path = artifact_path.with_name("receipt.json")
        manifest = json.loads(manifest_path.read_bytes())
        receipt = json.loads(receipt_path.read_bytes())
        canonical = lambda obj: sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        assert provenance["selection_manifest_sha256"] == canonical(manifest)
        assert provenance["selection_receipt_sha256"] == canonical(receipt)
        results.append({"test": "original_selection_store_valid_trio_and_hash_semantics", "status": "PASS",
                        "selected_rows": envelope["selected_rows"], "run_id": envelope["run_id"],
                        "provenance": provenance, "raw_artifact_sha256": envelope["raw_artifact_sha256"],
                        "manifest_file_byte_sha256": sha256(manifest_path.read_bytes()),
                        "receipt_file_byte_sha256": sha256(receipt_path.read_bytes()),
                        "preserves_research_only_rows": True, "read_did_not_modify_store": True})

        error = must_refuse_without_writes(store, helper,
            kwargs | {"run_id": "run-" + "0" * 24}, selection.SelectionError, "latest identity changed")
        results.append({"test": "different_latest_run_rejected", "status": "PASS", "error": error})

        latest_original = store.latest_path.read_bytes()
        latest = json.loads(latest_original)
        latest["entries"][store._key(kwargs["trade_date"], kwargs["stage_id"], kwargs["market"])]["artifact_sha256"] = "0" * 64
        store.latest_path.write_text(json.dumps(latest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        # The original reader checks the manifest/receipt pointer hashes;
        # the reused helper additionally checks latest.artifact_sha256.
        assert store.read_verified(kwargs["trade_date"], kwargs["stage_id"], kwargs["market"]) == original_envelope
        error = must_refuse_without_writes(store, helper, kwargs, selection.SelectionError, "latest pointer SHA mismatch")
        results.append({"test": "latest_artifact_sha_mismatch_rejected_by_original_helper", "status": "PASS",
                        "original_read_verified_still_read_envelope": True, "error": error})
        store.latest_path.write_bytes(latest_original)

        artifact_original = artifact_path.read_bytes()
        artifact_path.write_bytes(artifact_original + b"tamper\n")
        error = must_refuse_without_writes(store, helper, kwargs, selection.SelectionError, "artifact SHA mismatch")
        results.append({"test": "artifact_bytes_tamper_rejected", "status": "PASS", "error": error})
        artifact_path.write_bytes(artifact_original)

        receipt_original = receipt_path.read_bytes()
        changed_receipt = json.loads(receipt_original)
        changed_receipt["row_count"] = -1
        receipt_path.write_text(json.dumps(changed_receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        error = must_refuse_without_writes(store, helper, kwargs, selection.SelectionError, "row_count mismatch")
        results.append({"test": "receipt_row_count_tamper_rejected", "status": "PASS", "error": error})
        receipt_path.write_bytes(receipt_original)
        assert file_state(fixture_root) == before

    assert not fixture_root.exists()
    source_after = {str(path): sha256(path.read_bytes()) for path in source_paths}
    source_unchanged = source_before == source_after
    assert source_unchanged, "A reviewed source changed concurrently; rerun for a stable snapshot"

    import_environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join([str(CANDIDATE), str(REFERENCES), str(SUPPORT), str(SUPPORT / "upstreams")]))
    full_import = subprocess.run([sys.executable, "-B", "-c", "import stage_center.consumer"],
                                 cwd=ROOT, env=import_environment, capture_output=True, text=True, timeout=30)
    import_result = {"status": "BLOCKED" if full_import.returncode else "IMPORTED",
        "returncode": full_import.returncode, "stderr": full_import.stderr,
        "execution_module_candidate_present": (CANDIDATE / "stage_center/execution_evidence.py").exists(),
        "current_execution_contract": "Missing current research_source_projection and selection_store/selection_stores API; no stub supplied"}
    dependencies = []
    for name in ("stage_center.calendar", "stage_center.contracts", "infrastructure.interprocess_lock", "contracts.trading_calendar"):
        module = importlib.import_module(name)
        dependencies.append(source_record(Path(module.__file__)))
    return {"schema_version": "independent.hk_selection_provenance_review.v1",
        "python_version": sys.version, "platform": platform.platform(),
        "execution_scope": "Linux isolation; actual SelectionStore import plus unchanged consumer helper AST; original repository unit fixture only",
        "live_or_mac_verified": False, "natural_run_verified": False, "formal_eligible": False,
        "new_execution_module_or_stub_created": False,
        "reference_repository": "lexi2016/v4", "reference_ref": REFERENCE_REF,
        "fixture_repository_path": "handoff/v4-running-source-20261005/canonical/" + FIXTURE_RELATIVE,
        "helper_ast_sha256": sha256(helper_ast.encode()),
        "helper_source_sha256": sha256(ast.get_source_segment(helper_source, helper_nodes[0]).encode()),
        "helper_unchanged_from_attached_source": True, "reviewed_sources_unchanged_during_run": source_unchanged,
        "temporary_fixture_cleaned": True, "sources": [source_record(path) for path in source_paths],
        "dependencies": dependencies, "results": results,
        "passed": len(results), "failed": 0, "full_consumer_import": import_result,
        "limits": ["No current Mac process, scheduler, collector, API, or browser was accessed.",
                   "No native D1 Top100/V2 membership or all-stock rebound production data was generated.",
                   "No complete StageSelectionConsumer.get or original execution-reader integration was claimed.",
                   "Downloaded 20261005 references are test support, not an attestation of current deployed source."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    result = main()
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if options.output:
        options.output.write_text(rendered, encoding="utf-8")
        print(json.dumps({"output": str(options.output.resolve()), "sha256": sha256(rendered.encode()),
                          "passed": result["passed"], "failed": result["failed"],
                          "full_consumer_import": result["full_consumer_import"]["status"]}, ensure_ascii=False))
    else:
        print(rendered, end="")
