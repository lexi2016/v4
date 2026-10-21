"""Bound current-revision derivation. No materialization, scoring or network entrypoint."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import socket
import struct
import sys
import time
import traceback
from typing import Any, Dict

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "ARROW_NUM_THREADS"):
    os.environ[_var] = "1"
sys.dont_write_bytecode = True

ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
B = ROOT / "research/a_v192_signal_pool_return_stability_v1/batches/v192_logic_input_diagnostic_20261020"
EXTRA = ("fd_volume_yin", "break_yesterday_keyline", "plry_first")
SAFETY = dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def pure_functions(path, names, namespace):
    """Execute exact source AST functions only; exclude enrichment's root/pointer lookup."""
    tree = ast.parse(Path(path).read_text())
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in selected} == set(names), "PURE_FUNCTION_BINDING_MISSING"
    code = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
    exec(compile(ast.fix_missing_locations(code), str(path), "exec"), namespace)
    return {n.name: {"first_line": n.lineno, "last_line": n.end_lineno,
                     "ast_sha256": canonical_sha(ast.dump(n, include_attributes=False))} for n in selected}


def check_identity(binding):
    for path, expected in binding["files"].items():
        assert sha(path) == expected, f"INPUT_SHA_DRIFT:{path}"
    panel = binding["panel_FAST_BIND"]
    stat = Path(panel["path"]).stat()
    assert dict(inode=stat.st_ino, mtime_ns=stat.st_mtime_ns, size_bytes=stat.st_size) == panel["stat"], "PANEL_STAT_DRIFT"


def effective_events(binding):
    policy = load_json(binding["policy_path"])
    raw = load_json(policy["bound_events_path"])["events"]
    assert len(raw) == 12
    matches = [i for i, row in enumerate(raw) if all(row.get(k) == v for k, v in policy["selector"].items())]
    assert len(matches) == 1, "EVENT_NOT_UNIQUE"
    i = matches[0]
    assert raw[i] == policy["expected_raw_row"] and canonical_sha(raw[i]) == policy["expected_raw_row_sha256"]
    assert sha(binding["event_cache"]["path"]) == policy["source_cache_sha256"]
    assert sha(policy["official_evidence"]["path"]) == policy["official_evidence"]["sha256"]
    effective = [dict(row) for row in raw]
    effective[i][policy["only_changed_field"]] = policy["effective_value"]
    assert effective[i] == policy["effective_row"] and canonical_sha(effective[i]) == policy["effective_row_sha256"]
    assert all(a == b for j, (a, b) in enumerate(zip(raw, effective)) if j != i)
    return effective, {"raw_row_sha256": canonical_sha(raw[i]), "effective_row_sha256": canonical_sha(effective[i]),
                       "other_11_values_and_order_unchanged": True, "cache_sha256": policy["source_cache_sha256"],
                       "official_pdf_sha256": policy["official_evidence"]["sha256"], "unit": policy["unit"],
                       "restoration_basis": "EXPLICIT_CACHE_EXTRACTION_ORIGINAL_LOADER_EMPTY_WITHOUT_GBBQ"}


def assert_keys(frame, expected, code):
    assert not frame.duplicated(["ts_code", "trade_date"]).any(), "DUPLICATE_KEYS"
    assert frame["ts_code"].astype(str).eq(code).all(), "CODE_DRIFT"
    dates = frame["trade_date"].astype(str).tolist()
    assert dates == expected and dates == sorted(set(dates)), "EXACT_WINDOW_KEYS_DRIFT"


def derive_one(code, binding, proposal, producer, enrich, codec, events, phase, artifacts, counters):
    import numpy as np
    import pandas as pd
    from pandas.testing import assert_frame_equal

    source = binding["sources"][code]
    if source["kind"] == "RESTORED_RESPONSE":
        rows = load_json(source["eligible_path"])["response_rows"]
        native = B / f"NEXT_CURRENT6_DERIVED_{phase}_{code[:6]}_NATIVE.day"
        with native.open("xb") as handle:
            handle.write(b"".join(codec["pack_hq_bar"](bar) for bar in rows))
            handle.flush()
            os.fsync(handle.fileno())
        artifacts[str(native)] = sha(native)
    else:
        native = Path(source["path"])
    raw = producer.read_day_tail(code, native, tail_records=800)
    # Freeze window BEFORE every rolling/recursive formula. No 260-tail or year reset.
    hist = raw.loc[raw.trade_date.between(20240802, 20261020)].copy().reset_index(drop=True)
    dates = hist.trade_date.astype(str).tolist()
    assert len(hist) >= 240 and dates[-1] == "20261020", "INSUFFICIENT_OR_MISSING_TARGET"
    expected = source.get("expected_dates", dates)
    assert_keys(hist, expected, code)
    assert hist.columns.tolist() == ["ts_code", "trade_date", "open", "high", "low", "close", "amount", "vol", "volume"]
    assert np.isfinite(hist[["open", "high", "low", "close", "amount", "vol", "volume"]].to_numpy()).all()
    assert (hist[["open", "high", "low", "close"]] > 0).all().all()
    assert (hist[["amount", "volume", "vol"]] >= 0).all().all()
    captured = []
    original = producer._compute_canonical_v192_formula
    restored = False

    def observer(frame):
        assert not captured, "SECOND_CANONICAL_INVOCATION"
        counters["canonical_invocations"] += 1
        result = original(frame)
        captured.append(result.copy(deep=True))
        return result

    producer._compute_canonical_v192_formula = observer
    try:
        out = producer.compute_formula_features(hist, 20240801,
            {"name": binding["name_map"]}, producer._NoopLogger(), emit_all_rows=True,
            xdxr_events=pd.DataFrame(events))
    finally:
        producer._compute_canonical_v192_formula = original
        restored = producer._compute_canonical_v192_formula is original
    assert restored and len(captured) == 1, "OBSERVER_NOT_RESTORED_OR_CALL_COUNT"
    canonical = captured[0]
    assert_keys(canonical, expected, code)
    assert_keys(out, expected, code)
    required17 = list(producer.V192_REQUIRED_CANONICAL_PROJECTION_FIELDS)
    assert len(required17) == 17
    assert_frame_equal(out[required17], canonical[required17], check_exact=True, check_dtype=True)
    assert np.isfinite(out[required17].apply(pd.to_numeric).to_numpy(dtype=float)).all()
    # Key equality is proven before the same-call supplemental projection.
    assert not set(EXTRA) & set(out), "UNEXPECTED_SUPPLEMENTAL_SOURCE"
    assert set(EXTRA) <= set(canonical), "MISSING_CANONICAL_SUPPLEMENT"
    for col in EXTRA:
        out[col] = canonical[col].to_numpy(copy=True)
    assert_frame_equal(out[list(EXTRA)], canonical[list(EXTRA)], check_exact=True, check_dtype=True)
    _, out = enrich["add_limit_fields"](out)
    columns = proposal["source_columns63"]
    assert len(columns) == 63 and len(set(columns)) == 63
    assert set(columns) <= set(out), f"MISSING_SOURCE63:{set(columns)-set(out)}"
    assert set(columns) == set(proposal["source63_provenance"]), "PROVENANCE_NOT_TOTAL"
    selected = out[columns].copy()
    selected["trade_date"] = selected["trade_date"].astype(str)
    assert_keys(selected, expected, code)
    numeric = selected.select_dtypes(include=["number", "bool"]).columns.tolist()
    target = selected.iloc[-1]
    assert np.isfinite(target[numeric].astype(float).to_numpy()).all(), "NONFINITE_CRITICAL_TARGET"
    assert all(str(target[col]) != "" for col in set(columns)-set(numeric)), "EMPTY_TARGET_SOURCE"
    assert_frame_equal(selected[["open", "high", "low", "close", "volume", "amount"]], hist[["open", "high", "low", "close", "volume", "amount"]], check_exact=True)
    # Price/reference coherence uses the same canonical invocation, no recomputation.
    price_fields = ["pre_close", "pct_chg", "amplitude_pct", "upper_shadow_pct", "lower_shadow_pct"]
    assert_frame_equal(selected[price_fields], canonical[price_fields], check_exact=True, check_dtype=True)
    candidate = B / f"NEXT_CURRENT6_DERIVED_{phase}_{code[:6]}_CANDIDATE.parquet"
    canonical_path = B / f"NEXT_CURRENT6_DERIVED_{phase}_{code[:6]}_CANONICAL.parquet"
    raw_path = B / f"NEXT_CURRENT6_DERIVED_{phase}_{code[:6]}_WINDOW.parquet"
    assert not candidate.exists() and not canonical_path.exists() and not raw_path.exists()
    selected.to_parquet(candidate, index=False)
    canonical.to_parquet(canonical_path, index=False)
    hist.to_parquet(raw_path, index=False)
    for path in (candidate, canonical_path, raw_path):
        artifacts[str(path)] = sha(path)
    nonfinite = {col: selected.loc[~np.isfinite(pd.to_numeric(selected[col]).to_numpy(dtype=float)), "trade_date"].tolist()
                 for col in numeric if not np.isfinite(pd.to_numeric(selected[col]).to_numpy(dtype=float)).all()}
    return {"code": code, "rows": len(selected), "dates": dates, "window_key_sha256": canonical_sha([[code, date] for date in dates]),
            "required17_exact_same_canonical": True, "supplemental3_exact_same_canonical": True,
            "canonical_calls": 1, "observer_restored": restored, "schema63_before_defaults": True,
            "source63_provenance": proposal["source63_provenance"], "no_schema_defaults_called": True,
            "price_fields_exact_same_canonical": price_fields, "price_flags_function": "add_limit_fields",
            "name_observation": binding["name_observations"][code], "native_input_sha256": sha(native),
            "raw_source": source, "structural_nonfinite_dates_retained": nonfinite,
            "candidate_path": str(candidate), "canonical_path": str(canonical_path), "window_path": str(raw_path),
            "target": {key: (value.item() if hasattr(value, "item") else value) for key, value in target.items()},
            "warmup": {"first_observed": dates[0], "observed_rows": len(dates), "longest_dependency": 200,
                       "first24_mask": False, "tail260": False, "listing_complete": "CANNOT_CONFIRM"}}


def run(cp):
    c = load_json(cp)
    binding = load_json(c["input_binding_path"])
    phase = c["phase"]
    receipt_path = B / f"NEXT_CURRENT6_DERIVED_{phase}_RECEIPT.json"
    assert not receipt_path.exists(), "NO_OVERWRITE"
    assert sha(__file__) == c["code_sha256"] and sha(c["input_binding_path"]) == c["input_binding_sha256"]
    # Durable start must already be present; this command never silently starts numerical work.
    start = load_json(B / f"NEXT_CURRENT6_DERIVED_{phase}_REGISTRY_START.json")
    assert start["execution_id"] == c["execution_id"] and start["event_type"] == "RUN_STARTED"
    if phase.startswith("REST5"):
        prior = load_json(B / c["canary_receipt_filename"])
        assert prior["status"] == "CURRENT6_DERIVED_ENGINEERING_PASS" and prior["input_binding_sha256"] == c["input_binding_sha256"]
        assert prior["code_sha256"] == c["code_sha256"]
        for path, expected in prior["artifacts"].items():
            assert sha(path) == expected
    began = time.monotonic()
    receipt = dict(execution_id=c["execution_id"], route_id=c["route_id"], contract_sha256=sha(cp),
                   code_sha256=sha(__file__), input_binding_sha256=sha(c["input_binding_path"]),
                   status="CURRENT6_DERIVED_FAILED", artifacts={}, per_code=[], **SAFETY)
    old_socket = socket.socket
    calls = {"network_attempts": 0, "canonical_invocations": 0}

    def no_network(*args, **kwargs):
        calls["network_attempts"] += 1
        raise RuntimeError("NETWORK_FORBIDDEN")

    socket.socket = no_network
    try:
        import numpy as np
        import pandas as pd
        import pyarrow as pa
        pa.set_cpu_count(1)
        pa.set_io_thread_count(1)
        check_identity(binding)
        proposal = load_json(binding["proposal_path"])
        events, event_receipt = effective_events(binding)
        producer = load_module(proposal["producer"]["path"], "current6_bound_producer")
        producer.CANONICAL_FORMULA_PATH = Path(proposal["canonical"]["path"])
        enrich = dict(np=np, pd=pd, Any=Any)
        funcs = pure_functions(binding["enrichment"]["path"], ["as_number", "limit_pct_estimate", "consecutive_true_by_group", "add_limit_fields"], enrich)
        codec = dict(DAY_STRUCT=struct.Struct("<IIIIIfII"), Any=Any, Dict=Dict)
        codec_funcs = pure_functions(binding["sync"]["path"], ["day_int", "pack_hq_bar"], codec)
        for code in c["codes"]:
            receipt["per_code"].append(derive_one(code, binding, proposal, producer, enrich, codec, events, phase, receipt["artifacts"], calls))
        check_identity(binding)
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        receipt["peak_rss_bytes"] = peak if sys.platform == "darwin" else peak*1024
        assert receipt["peak_rss_bytes"] <= c["resources"]["rss_max_bytes"], "RSS_LIMIT"
        assert calls["network_attempts"] == 0
        receipt.update(status="CURRENT6_DERIVED_ENGINEERING_PASS", event_policy=event_receipt,
                       pure_function_bindings={"enrichment": funcs, "native_codec": codec_funcs},
                       identity_unchanged=True, resource_ok=True, error=None)
    except Exception as exc:
        receipt.update(error={"type": type(exc).__name__, "repr": repr(exc), "traceback": traceback.format_exc()}, resource_ok=False)
    finally:
        socket.socket = old_socket
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    receipt.setdefault("peak_rss_bytes", peak if sys.platform == "darwin" else peak*1024)
    receipt["wall_seconds"] = time.monotonic()-began
    receipt["deterministic_metrics"] = dict(truth_positive_denominator=None, selection_slots=0,
        derived_codes=len(receipt["per_code"]), canonical_calls=calls["canonical_invocations"],
        network_attempts=calls["network_attempts"], formal_writes=0, pointer_writes=0,
        model_fit_predict_labels_returns=0, windows_connections=0, futu_calls=0, score_role_calls=0)
    receipt["scope"] = "CURRENT_REVISION_NON_PIT_SIX_FIXED_CODES_ONLY_NO_44_CAUSAL_OR_FULL_POOL_CLAIM"
    receipt["CANNOT_CONFIRM"] = ["historical_PIT", "complete_listing_history", "Windows_parity", "full_pool", "44_difference_causality", "formal_publication", "remote_sync"]
    write_json(receipt_path, receipt)
    print(json.dumps({"status": receipt["status"], "receipt": str(receipt_path), "sha256": sha(receipt_path), "error": receipt["error"] and receipt["error"]["repr"]}))
    return 0 if receipt["status"] == "CURRENT6_DERIVED_ENGINEERING_PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().contract))
