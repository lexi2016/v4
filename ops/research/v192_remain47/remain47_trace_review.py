"""Independent saved47 trace readback; never imports consumers or calls scores."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import resource
import socket
import sys
import time
import traceback
sys.dont_write_bytecode = True


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def role_assignment_literals(source_paths):
    """Read the original literal RHS; no evaluation of any expression."""
    literals = {}
    for path in source_paths:
        tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
        for function in tree.body:
            if not isinstance(function, ast.FunctionDef) or function.name not in ("score_multi_head", "base_fmla04_role"):
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                    continue
                target = node.targets[0]
                name = target.id if isinstance(target, ast.Name) else target.value.id if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) else None
                if name not in ("roles", "pred"):
                    continue
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    label = value.value
                elif isinstance(target, ast.Name) and isinstance(value, ast.Call):
                    strings = [item.value for item in value.args if isinstance(item, ast.Constant) and isinstance(item.value, str)]
                    assert len(strings) == 1, "ROLE_INIT_LITERAL_AMBIGUOUS"
                    label = strings[0]
                else:
                    raise AssertionError("ROLE_ASSIGNMENT_NOT_LITERAL")
                literals[(function.name, node.lineno, ast.unparse(target))] = label
    return literals


def review(cp, reviewer):
    c = read(cp)
    assert reviewer != c["WRITER"] and reviewer != "/root/current6_writer_resume"
    assert sha(__file__) == c["code_sha256"]
    assert sha(c["input_binding_path"]) == c["input_binding_sha256"]
    b = read(c["input_binding_path"])
    start = read(c["registry_start_path"])
    assert start["execution_id"] == c["execution_id"] and start["event_type"] == "RUN_STARTED"
    output = Path(c["receipt_path"])
    assert not output.exists()
    began = time.monotonic()
    r = dict(execution_id=c["execution_id"], route_id=c["route_id"],
             contract_sha256=sha(cp), code_sha256=sha(__file__),
             input_binding_sha256=sha(c["input_binding_path"]), reviewer=reviewer,
             status="REMAIN47_SAVED_TRACE_REVIEW_FAIL", artifacts={}, error=None,
             research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    attempts = [0]
    old_socket = socket.socket
    def block(*args, **kwargs):
        attempts[0] += 1
        raise RuntimeError("REVIEW_NETWORK_FORBIDDEN")
    socket.socket = block
    try:
        for path, expected in b["files"].items():
            assert sha(path) == expected, "SHA_DRIFT:" + path
        saved = read(b["trace_receipt_path"])
        assert saved["status"] == "REMAIN47_TRACE_ENGINEERING_READY"
        trace_contract = read(b["trace_contract_path"])
        original = read(trace_contract["input_binding_path"])
        codes = set(trace_contract["codes"])
        assert len(codes) == 47 and codes == set(c["codes"]) == set(original["per_code"])
        rows = read(b["trace_outputs"]["PER_CODE"])
        assert len(rows) == 47 and {row["ts_code"] for row in rows} == codes
        assert len({row["ts_code"] for row in rows}) == 47
        by_code = {row["ts_code"]: row for row in rows}
        metrics = saved["deterministic_metrics"]
        assert metrics["original_function_calls"] == dict(vector_prepare_features=1, score_v19=1, score_multi_head=1, base_fmla04_role=1)
        assert all(metrics[key] == 0 for key in ("canonical_calls", "network_attempts", "formal_writes", "pointer_writes", "windows_connections", "orders"))
        keys = read(b["trace_outputs"]["CONSUMER_KEYS"])
        assert set(keys) == codes
        for code in codes:
            expected = [date for date in original["per_code"][code]["dates"] if "20260101" <= date <= "20261020"]
            assert keys[code]["consumer_keys"] == expected
            assert keys[code]["consumer_rows"] == len(expected)
        ast_receipts = read(b["trace_outputs"]["OBSERVER_AST"])
        consumer = read(original["consumer_binding_path"])
        expected_asts = {name: digest for kind in consumer["source_function_ast_sha256"].values() for name, digest in kind.items()}
        assert set(ast_receipts) == set(metrics["original_function_calls"])
        markers = {}
        for function, receipt in ast_receipts.items():
            assert receipt["original_ast_sha256"] == receipt["stripped_ast_sha256"] == expected_asts[function]
            assert receipt["returned_objects_unchanged"] and receipt["data_or_score_calls_in_instrument"] == 0
            for marker in receipt["expressions"]:
                markers[(function, marker["id"])] = marker
        expressions = read(b["trace_outputs"]["EXPRESSIONS"])
        for event in expressions:
            marker = markers[(event["function"], event["id"])]
            assert all(event[key] == value for key, value in marker.items())
            assert set(event["copied"].get("values", {})) <= codes
        assignments = read(b["trace_outputs"]["ASSIGNMENTS"])
        for event in assignments:
            assert set(event["copied"].get("values", {})) <= codes
        literal = role_assignment_literals([consumer["files"][kind]["path"] for kind in ("score_source", "role_source")])
        role_events = read(b["trace_outputs"]["ROLE_ASSIGNMENTS"])
        state, final_marker = {}, {}
        for event in role_events:
            function = event["function"]
            name = "roles" if function == "score_multi_head" else "pred"
            key = (function, name)
            before = state.get(key, {})
            assert event["before"] == before
            assert set(event["after"]) == set(event["matched"]) == codes
            assert all(type(value) is bool for value in event["matched"].values())
            value = literal[(function, event["line"], event["target"])]
            expected = {code: value if event["matched"][code] else before[code] for code in codes}
            assert event["after"] == expected
            for code in codes:
                if event["matched"][code]:
                    final_marker[(function, code)] = dict(sequence=event["sequence"], line=event["line"], condition=event["condition"], role=expected[code])
            state[key] = dict(event["after"])
        for code, item in by_code.items():
            assert item["multi_head_final_role"] == state[("score_multi_head", "roles")][code]
            assert item["candidate_role"] == state[("base_fmla04_role", "pred")][code]
            assert item["effective_multihead_assignment"] == final_marker[("score_multi_head", code)]
            assert item["effective_candidate_assignment"] == final_marker[("base_fmla04_role", code)]
            assert item["Windows_specific_rejection"].startswith("CANNOT_CONFIRM")
        for path, expected in b["files"].items():
            assert sha(path) == expected, "ARTIFACT_MUTATED:" + path
        r.update(status="REMAIN47_SAVED_TRACE_REVIEW_PASS", reviewed_codes=47,
                 checked_expression_records=len(expressions), checked_assignment_records=len(assignments),
                 checked_role_assignment_records=len(role_events), resource_ok=True)
    except Exception as exc:
        r.update(error=dict(type=type(exc).__name__, repr=repr(exc), traceback=traceback.format_exc()), resource_ok=False)
    finally:
        socket.socket = old_socket
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    r.update(wall_seconds=time.monotonic()-began, peak_rss_bytes=peak if sys.platform == "darwin" else peak*1024,
             deterministic_metrics=dict(truth_positive_denominator=None, selection_slots=0,
                 reviewed_codes=r.get("reviewed_codes", 0), canonical_calls=0, feature_score_role_calls=0,
                 network_attempts=attempts[0], formal_writes=0, pointer_writes=0, windows_connections=0))
    if r["peak_rss_bytes"] > c["resources"]["rss_max_bytes"]:
        r.update(status="REMAIN47_SAVED_TRACE_REVIEW_FAIL", resource_ok=False, error={"repr": "RSS_LIMIT"})
    with output.open("x") as handle:
        json.dump(r, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(dict(status=r["status"], receipt=str(output), sha256=sha(output), error=r["error"] and r["error"]["repr"])))
    return 0 if r["status"] == "REMAIN47_SAVED_TRACE_REVIEW_PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    raise SystemExit(review(args.contract, args.reviewer))
