"""Frozen current-revision 47-code trace, using one invocation per consumer.

Only the separately approved observer copies target-date values. This file must
not be executed until its input contract and independent static review are bound.
"""
from __future__ import annotations
import os
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "ARROW_NUM_THREADS"):
    os.environ[_name] = "1"
import argparse
import ast
import csv
import hashlib
import importlib.util
import json
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


def write(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def scalar(value):
    import numpy as np
    import pandas as pd
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return {"nonfinite": repr(value)}
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        # A source str.split intermediate is a two-string target cell. Copy only
        # a bounded scalar sequence; never hand back or mutate the source list.
        assert len(value) <= 8, "TARGET_CELL_SEQUENCE_TOO_LONG"
        assert all(item is None or isinstance(item, (str, bool, int, float, np.generic))
                   for item in value), "TARGET_CELL_SEQUENCE_ELEMENT_TYPE"
        return [scalar(item) for item in value]
    raise TypeError("UNSUPPORTED_TARGET_SCALAR:" + type(value).__name__)


class TargetCopies:
    """Read target slices only; no mutation, expression evaluation, or scoring."""
    def __init__(self, codes):
        self.codes = set(codes)
        self.expressions = []
        self.assignments = []
        self.role_assignments = []
        self.mapping_cache = {}
        self.last_expression = {}
        self.previous_role = {}
        self.last_effective_role_assignment = {}

    def mapping(self, local):
        import pandas as pd
        frame = next((local[key] for key in ("out", "df", "raw")
                      if isinstance(local.get(key), pd.DataFrame)
                      and {"ts_code", "trade_date"} <= set(local[key])), None)
        if frame is None:
            return None, {}
        identity = (id(frame), id(frame.index), len(frame))
        if identity not in self.mapping_cache:
            assert frame.index.is_unique, "CALLBACK_CONTEXT_INDEX_NOT_UNIQUE"
            date = frame.trade_date.astype(str)
            mask = frame.ts_code.isin(self.codes) & date.eq("20261020")
            chosen = frame.loc[mask, ["ts_code", "trade_date"]]
            assert not chosen.ts_code.duplicated().any(), "CALLBACK_TARGET_KEY_DUPLICATE"
            pairs = [(index, str(row.ts_code)) for index, row in chosen.iterrows()]
            # Retain the actual context object so Python cannot reuse its id.
            self.mapping_cache[identity] = (frame, pairs)
        return frame, dict(self.mapping_cache[identity][1])

    def copy_value(self, value, local):
        import numpy as np
        import pandas as pd
        context, index_to_code = self.mapping(local)
        if isinstance(value, pd.Series):
            assert value.index.is_unique, "CALLBACK_VALUE_INDEX_NOT_UNIQUE"
            return {"kind": "TARGET_SERIES", "values": {
                code: scalar(value.loc[index]) for index, code in index_to_code.items()
                if index in value.index}}
        if isinstance(value, pd.DataFrame):
            assert value.index.is_unique, "CALLBACK_FRAME_INDEX_NOT_UNIQUE"
            if {"ts_code", "trade_date"} <= set(value):
                _, index_to_code = self.mapping({"df": value})
            return {"kind": "TARGET_FRAME", "values": {
                code: {str(col): scalar(value.at[index, col]) for col in value.columns}
                for index, code in index_to_code.items() if index in value.index}}
        if isinstance(value, np.ndarray):
            if context is not None and value.ndim == 1 and len(value) == len(context):
                locations = context.index.get_indexer(list(index_to_code))
                return {"kind": "TARGET_ARRAY", "values": {
                    index_to_code[index]: scalar(value[position])
                    for index, position in zip(index_to_code, locations)}}
            # Not an aligned per-row value: do not guess its stock association.
            return {"kind": "NON_TARGET_ARRAY_METADATA", "shape": list(value.shape)}
        if value is None or isinstance(value, (str, int, float, bool, np.generic)) or value is pd.NA:
            return {"kind": "SCALAR_EXPRESSION_CONTEXT", "value": scalar(value)}
        return {"kind": "NON_TARGET_OBJECT_METADATA", "type": type(value).__name__}

    def value(self, marker, value, local):
        copied = self.copy_value(value, local)
        event = {"sequence": len(self.expressions), **marker, "copied": copied}
        self.expressions.append(event)
        self.last_expression[(marker["function"], marker["expression"])] = copied

    def assignment(self, marker, local):
        function = marker["function"]
        for target in marker["targets"]:
            node = ast.parse(target, mode="eval").body
            name = None
            if isinstance(node, ast.Name):
                name = node.id
                value = local.get(name)
            elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
                name = node.value.id
                owner = local.get(name)
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    value = owner[node.slice.value]
                else:
                    # roles[mask]/pred[mask]: copy the post-assignment target array.
                    value = owner
            elif (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
                  and isinstance(node.value.value, ast.Name) and node.value.attr == "loc"
                  and isinstance(node.slice, ast.Tuple)
                  and isinstance(node.slice.elts[-1], ast.Constant)):
                name = node.value.value.id
                value = local[name][node.slice.elts[-1].value]
            else:
                # Tuple unpacking or a control-only target has no needed scalar.
                continue
            copied = self.copy_value(value, local)
            event = {"sequence": len(self.assignments), **marker,
                     "target": target, "copied": copied}
            self.assignments.append(event)
            if name not in ("roles", "pred"):
                continue
            after = copied.get("values", {})
            if isinstance(node, ast.Name):
                condition = "INITIAL_ROLE"
                matched = {code: True for code in after}
            else:
                condition = ast.unparse(node.slice)
                if isinstance(node.slice, ast.Name):
                    observed = self.copy_value(local[node.slice.id], local)
                else:
                    observed = self.last_expression.get((function, condition))
                assert observed is not None, "ROLE_PREDICATE_NOT_OBSERVED:" + condition
                matched = observed.get("values", {})
                assert set(after) <= set(matched), "ROLE_PREDICATE_TARGET_MISSING"
            before = self.previous_role.get((function, name), {})
            role_event = dict(sequence=len(self.role_assignments), function=function,
                              line=marker["line"], target=target, condition=condition,
                              before=dict(before), matched=dict(matched), after=dict(after))
            self.role_assignments.append(role_event)
            for code in after:
                if matched.get(code) is True:
                    self.last_effective_role_assignment[(function, name, code)] = {
                        "sequence": role_event["sequence"], "line": marker["line"],
                        "condition": condition, "role": after[code]}
            self.previous_role[(function, name)] = dict(after)


def load_consumers(binding, observer, captures):
    import numpy as np
    import pandas as pd
    original = read(binding["consumer_binding_path"])
    main = {"feature_source": ("vector_prepare_features",),
            "score_source": ("score_v19", "score_multi_head"),
            "role_source": ("base_fmla04_role",)}
    loaded, receipts = {}, {}
    for kind, names in main.items():
        path = original["files"][kind]["path"]
        tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in original["source_function_names"][kind]]
        assert {node.name for node in nodes} == set(original["source_function_names"][kind])
        namespace = dict(np=np, pd=pd, Any=object,
                         BOOL_COLUMNS=original["bool_columns"],
                         REQUIRED_BASE_COLUMNS=original["required_column_order"])
        for node in nodes:
            digest = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
            assert digest == original["source_function_ast_sha256"][kind][node.name], "CONSUMER_AST_DRIFT"
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), path, "exec"), namespace)
        for node in nodes:
            if node.name in names:
                function, receipt = observer.instrument(node, namespace, captures.value,
                                                         captures.assignment, path)
                loaded[node.name] = function
                receipts[node.name] = receipt
    return loaded, receipts, original


def target_rows(frame, codes):
    selected = frame.loc[frame.trade_date.astype(str).eq("20261020")].copy()
    assert len(selected) == len(codes) and set(selected.ts_code) == set(codes)
    assert not selected.ts_code.duplicated().any()
    return selected


def run(cp):
    c = read(cp)
    b = read(c["input_binding_path"])
    assert sha(__file__) == c["code_sha256"] and sha(c["input_binding_path"]) == c["input_binding_sha256"]
    start = read(c["registry_start_path"])
    assert start["execution_id"] == c["execution_id"] and start["event_type"] == "RUN_STARTED"
    assert not Path(c["receipt_path"]).exists()
    began = time.monotonic()
    r = dict(execution_id=c["execution_id"], route_id=c["route_id"],
             code_sha256=sha(__file__), contract_sha256=sha(cp),
             input_binding_sha256=sha(c["input_binding_path"]), artifacts={},
             status="REMAIN47_TRACE_FAILED", error=None, research_only=True,
             production_allowed=False, buy_gate_updated=False, orders_sent=False)
    attempts = [0]
    calls = {name: 0 for name in ("vector_prepare_features", "score_v19", "score_multi_head", "base_fmla04_role")}
    old_socket = socket.socket
    def block(*args, **kwargs):
        attempts[0] += 1
        raise RuntimeError("NETWORK_FORBIDDEN")
    socket.socket = block
    try:
        import numpy as np
        import pandas as pd
        import pyarrow as pa
        import pyarrow.dataset as ds
        pa.set_cpu_count(1)
        pa.set_io_thread_count(1)
        for path, expected in b["files"].items():
            assert sha(path) == expected, "INPUT_SHA_DRIFT:" + path
        for key, accepted in b["independent_acceptance"].items():
            saved = read(accepted["path"])
            assert saved["status"] == accepted["status"], "INDEPENDENT_ACCEPTANCE_REQUIRED:" + key
        panel = b["panel_FAST_BIND"]
        def panel_stat():
            s = Path(panel["path"]).stat()
            assert dict(inode=s.st_ino, mtime_ns=s.st_mtime_ns, size_bytes=s.st_size) == panel["stat"]
        panel_stat()
        codes = c["codes"]
        assert len(codes) == len(set(codes)) == 47 and set(b["per_code"]) == set(codes)
        frames, input_targets, key_receipts = [], {}, {}
        for code in codes:
            item = b["per_code"][code]
            frame = pd.read_parquet(item["candidate_path"])
            assert len(frame) == item["rows"] and frame.ts_code.eq(code).all()
            assert frame.trade_date.astype(str).tolist() == item["dates"]
            assert not frame.duplicated(["ts_code", "trade_date"]).any()
            target = target_rows(frame, [code]).iloc[0]
            input_targets[code] = {col: scalar(target[col]) for col in frame.columns}
            cropped = frame.loc[frame.trade_date.astype(str).between("20260101", "20261020")].copy()
            assert not cropped.empty and cropped.trade_date.iloc[-1] == "20261020"
            frames.append(cropped)
            key_receipts[code] = dict(accepted_lowlevel_first=item["dates"][0],
                accepted_lowlevel_rows=len(frame), consumer_first=str(cropped.trade_date.iloc[0]),
                consumer_rows=len(cropped), consumer_keys=cropped.trade_date.astype(str).tolist())
        raw = pd.concat(frames, ignore_index=True)
        captures = TargetCopies(codes)
        spec = importlib.util.spec_from_file_location("remain47_approved_observer", b["observer_path"])
        observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(observer)
        functions, ast_receipts, original = load_consumers(b, observer, captures)
        raw = raw[original["required_column_order"]].copy()
        calls["vector_prepare_features"] += 1
        features = functions["vector_prepare_features"](raw)
        feature_target = target_rows(features, codes)
        calls["score_v19"] += 1
        v19 = functions["score_v19"](features)
        v19_target = target_rows(v19, codes)
        calls["score_multi_head"] += 1
        multihead = functions["score_multi_head"](v19)
        day = target_rows(multihead, codes)
        calls["base_fmla04_role"] += 1
        role = functions["base_fmla04_role"](day)
        assert role.index.equals(day.index), "FINAL_ROLE_INDEX_DRIFT"
        # The original helper is called only inside base_fmla04_role. Its return
        # was already observed by the approved wrapper; do not invoke it again.
        observed_entry = captures.last_expression[("base_fmla04_role", "entry_pool(df)")]["values"]
        assert set(observed_entry) == set(codes)
        day["entry_pool"] = [observed_entry[code] for code in day.ts_code]
        day["candidate_role"] = role
        old_rows = {row["ts_code"]: row for row in csv.DictReader(Path(b["baseline93_path"]).open())}
        assert set(codes) <= set(old_rows)
        source = ds.dataset(panel["path"], format="parquet")
        source_cols = [col for col in b["source_columns63"] if col in source.schema.names]
        predicate = (ds.field("trade_date").cast("string") == "20261020") & ds.field("ts_code").isin(codes)
        old_input = source.to_table(columns=source_cols, filter=predicate, use_threads=False).to_pandas()
        assert not old_input.duplicated(["ts_code", "trade_date"]).any()
        old_inputs = {row["ts_code"]: {col: scalar(row[col]) for col in old_input.columns}
                      for _, row in old_input.iterrows()}
        result = []
        for _, row in day.iterrows():
            code = row.ts_code
            before = old_rows[code]
            old_role = before["candidate_role"]
            new_role = str(row.candidate_role)
            source_available = str(before["source_available"]).lower() in ("true", "1")
            compared = old_inputs.get(code)
            changed = {col: {"before": compared[col], "after": input_targets[code][col]}
                       for col in (compared or {}) if col not in ("trade_date", "ts_code")
                       and compared[col] != input_targets[code][col]}
            classification = ("REPAIRED_INPUT_CHANGED_LOCAL_RESULT" if source_available and old_role != new_role
                else "RESTORED_PREVIOUSLY_MISSING_INPUT" if not source_available
                else "REPAIRED_INPUT_STILL_SATISFIES_ORIGINAL_LOCAL_FORMULA" if new_role == "TEST_ONLY_BUY_CANDIDATE"
                else "REPAIRED_INPUT_REMAINS_REJECTED_BY_ORIGINAL_LOCAL_FORMULA")
            result.append(dict(ts_code=code, group=b["groups"][code],
                original56_member=before["original56_member"], windows_A_member=before["windows_A_member"],
                baseline_source_available=source_available, baseline_candidate_role=old_role,
                candidate_role=new_role, multi_head_final_role=str(row.multi_head_final_role),
                classification=classification, Windows_specific_rejection="CANNOT_CONFIRM_NO_AUTHENTICATED_WINDOWS_ENGINE_INPUT",
                target_source_field_changes=changed, baseline_target_missing_columns=sorted(set(b["source_columns63"])-set(source_cols)),
                final_fields={col: scalar(row[col]) for col in day.columns},
                effective_multihead_assignment=captures.last_effective_role_assignment[("score_multi_head", "roles", code)],
                effective_candidate_assignment=captures.last_effective_role_assignment[("base_fmla04_role", "pred", code)]))
        artifacts = {"INPUT_TARGETS": input_targets, "CONSUMER_KEYS": key_receipts,
                     "EXPRESSIONS": captures.expressions, "ASSIGNMENTS": captures.assignments,
                     "ROLE_ASSIGNMENTS": captures.role_assignments,
                     "PER_CODE": result, "OBSERVER_AST": ast_receipts,
                     "FEATURE_TARGETS": {row.ts_code: {col: scalar(row[col]) for col in feature_target.columns}
                                          for _, row in feature_target.iterrows()},
                     "V19_TARGETS": {row.ts_code: {col: scalar(row[col]) for col in v19_target.columns}
                                      for _, row in v19_target.iterrows()}}
        for name, value in artifacts.items():
            path = Path(c["batch_path"]) / ("NEXT_REMAIN47_TRACE_R2_" + name + ".json")
            write(path, value)
            r["artifacts"][str(path)] = sha(path)
        assert all(value == 1 for value in calls.values()) and attempts[0] == 0
        assert len(result) == len({item["ts_code"] for item in result}) == 47
        for path, expected in b["files"].items():
            assert sha(path) == expected, "INPUT_MUTATED:" + path
        panel_stat()
        r.update(status="REMAIN47_TRACE_ENGINEERING_READY", per_code_count=47,
                 expressions=len(captures.expressions), assignments=len(captures.assignments),
                 role_assignments=len(captures.role_assignments), resource_ok=True,
                 CANNOT_CONFIRM=["historical_PIT", "Windows_installed_formula_engine_parameters_inputs",
                                 "whole_pool_acceptance", "formal_publication", "remote_sync"])
    except Exception as exc:
        r.update(error=dict(type=type(exc).__name__, repr=repr(exc), traceback=traceback.format_exc()), resource_ok=False)
    finally:
        socket.socket = old_socket
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    r.update(wall_seconds=time.monotonic()-began, peak_rss_bytes=peak if sys.platform == "darwin" else peak*1024,
             deterministic_metrics=dict(truth_positive_denominator=None, selection_slots=0,
                 original_function_calls=calls, canonical_calls=0, network_attempts=attempts[0],
                 formal_writes=0, pointer_writes=0, windows_connections=0, orders=0))
    if r["peak_rss_bytes"] > c["resources"]["rss_max_bytes"]:
        r.update(status="REMAIN47_TRACE_FAILED", resource_ok=False, error={"repr": "RSS_LIMIT"})
    write(c["receipt_path"], r)
    print(json.dumps(dict(status=r["status"], receipt=c["receipt_path"], sha256=sha(c["receipt_path"]), error=r["error"] and r["error"]["repr"])))
    return 0 if r["status"] == "REMAIN47_TRACE_ENGINEERING_READY" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().contract))
