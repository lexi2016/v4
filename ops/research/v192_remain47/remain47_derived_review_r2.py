"""Independent new39 saved-artifact readback; never invokes canonical or the producer."""
from __future__ import annotations
import os
for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "ARROW_NUM_THREADS"):
    os.environ[var] = "1"
import argparse
import hashlib
import json
from pathlib import Path
import resource
import socket
import struct
import sys
import time
import traceback
sys.dont_write_bytecode = True


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def review(cp, reviewer):
    c = read(cp)
    b = read(c["input_binding_path"])
    output = Path(c["receipt_path"])
    assert not output.exists()
    assert reviewer and reviewer != c["WRITER"] and reviewer != "/root/current6_writer_resume"
    assert sha(__file__) == c["code_sha256"] and sha(c["input_binding_path"]) == c["input_binding_sha256"]
    start = read(c["registry_start_path"])
    assert start["execution_id"] == c["execution_id"] and start["event_type"] == "RUN_STARTED"
    began = time.monotonic()
    r = dict(execution_id=c["execution_id"], route_id=c["route_id"], reviewer=reviewer,
             contract_sha256=sha(cp), code_sha256=sha(__file__), input_binding_sha256=sha(c["input_binding_path"]),
             status="REMAIN47_INDEPENDENT_SAVED_READBACK_FAIL", artifacts={}, per_code=[],
             research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    old_socket = socket.socket
    attempts = [0]

    def blocked(*args, **kwargs):
        attempts[0] += 1
        raise RuntimeError("REVIEW_NETWORK_FORBIDDEN")

    socket.socket = blocked
    try:
        import numpy as np
        import pandas as pd
        import pyarrow as pa
        from pandas.testing import assert_frame_equal
        pa.set_cpu_count(1)
        pa.set_io_thread_count(1)
        for path, expected in b["files"].items():
            assert sha(path) == expected, f"SHA_DRIFT:{path}"
        original = read(b["derived_binding_path"])
        for path, expected in original["files"].items():
            assert sha(path) == expected, f"SOURCE_SHA_DRIFT:{path}"
        panel = original["panel_FAST_BIND"]
        s = Path(panel["path"]).stat()
        assert dict(inode=s.st_ino, mtime_ns=s.st_mtime_ns, size_bytes=s.st_size) == panel["stat"]
        proposal = read(original["proposal_path"])
        columns = proposal["source_columns63"]
        assert len(columns) == 63 and set(columns) == set(proposal["source63_provenance"])
        events = read(original["events_path"])["events"]
        assert len(events) == original["event_count"] == 81
        effective = [dict(row) for row in events]
        assert effective == events, "UNAUTHORIZED_EVENT_OVERRIDE"
        fields17 = b["required17"]
        extra3 = ["fd_volume_yin", "break_yesterday_keyline", "plry_first"]
        assert len(fields17) == 17
        codec = struct.Struct("<IIIIIfII")
        seen = []
        for receipt_path in b["writer_receipts"]:
            saved = read(receipt_path)
            assert saved["status"] == "REMAIN47_DERIVED_ENGINEERING_PASS"
            for item in saved["per_code"]:
                code = item["code"]
                seen.append(code)
                candidate = pd.read_parquet(item["candidate_path"])
                canonical = pd.read_parquet(item["canonical_path"])
                window = pd.read_parquet(item["window_path"])
                assert candidate.columns.tolist() == columns
                for frame in (candidate, canonical, window):
                    assert not frame.duplicated(["ts_code", "trade_date"]).any()
                    assert frame.ts_code.eq(code).all()
                    dates = frame.trade_date.astype(str).tolist()
                    assert dates == item["dates"] == sorted(set(dates))
                assert candidate.trade_date.iloc[0] >= "20240802" and candidate.trade_date.iloc[-1] == "20261020"
                assert len(candidate) >= 240
                if "expected_dates" in original["sources"][code]:
                    assert item["dates"] == original["sources"][code]["expected_dates"]
                assert_frame_equal(candidate[fields17+extra3], canonical[fields17+extra3], check_exact=True, check_dtype=True)
                assert np.isfinite(candidate[fields17].to_numpy(dtype=float)).all()
                assert item["source63_provenance"] == proposal["source63_provenance"]
                assert item["canonical_calls"] == 1 and item["observer_restored"] and item["no_schema_defaults_called"]
                # Independent native codec, without importing any writer/producer functions.
                native_path = original["sources"][code].get("path")
                if not native_path:
                    native_path = str(Path(c["batch_path"]) / f"NEXT_REMAIN47_DERIVED_{'CANARY' if code=='001313.SZ' else 'REST38'}_{code[:6]}_NATIVE.day")
                    bars = read(original["sources"][code]["eligible_path"])["response_rows"]
                    packed = b"".join(codec.pack(int(x["year"])*10000+int(x["month"])*100+int(x["day"]),
                        *[int(round(float(x[k])*100)) for k in ("open", "high", "low", "close")],
                        float(x["amount"]), int(round(float(x["vol"])*100)), 0) for x in bars)
                    assert Path(native_path).read_bytes() == packed, "RESTORED_NATIVE_UNITS_OR_BYTES"
                blob = Path(native_path).read_bytes()
                assert len(blob) % codec.size == 0 and sha(native_path) == item["native_input_sha256"]
                rows = []
                for d, op, hi, lo, cl, amount, volume, _ in codec.iter_unpack(blob[-800*codec.size:]):
                    if 20240802 <= d <= 20261020:
                        rows.append(dict(ts_code=code, trade_date=d, open=op/100.0, high=hi/100.0,
                                         low=lo/100.0, close=cl/100.0, amount=float(amount), vol=volume, volume=volume))
                decoded = pd.DataFrame(rows)
                assert_frame_equal(window, decoded, check_exact=True, check_dtype=True)
                raw_cols = ["open", "high", "low", "close", "volume", "amount"]
                assert_frame_equal(candidate[raw_cols], window[raw_cols], check_exact=True, check_dtype=True)
                # Independently compute the reference; all 12 event rows are bound.
                previous = candidate.close.shift(1)
                reference = previous.copy()
                event_checks = []
                for event in effective:
                    if event["ts_code"] != code:
                        continue
                    date = str(event["_xdxr_trade_date"])
                    idx = candidate.index[candidate.trade_date.eq(date)]
                    assert len(idx) == 1
                    j = idx[0]
                    denominator = 1.0+event["xdxr_songzhuangu"]/10.0+event["xdxr_peigu"]/10.0
                    reference.loc[j] = (previous.loc[j]-event["xdxr_fenhong"]/10.0+event["xdxr_peigujia"]*event["xdxr_peigu"]/10.0)/denominator
                    event_checks.append(date)
                np.testing.assert_allclose(candidate.pre_close.to_numpy(), reference.to_numpy(), rtol=0, atol=1e-12, equal_nan=True)
                expected_pct = (candidate.close/reference-1.0)*100.0
                np.testing.assert_allclose(candidate.pct_chg.to_numpy(), expected_pct.to_numpy(), rtol=0, atol=1e-12, equal_nan=True)
                # Independent estimates for these six A-share codes and their dated names.
                name = original["name_observations"][code]
                assert candidate.name.eq(name["name"]).all() and item["name_observation"] == name
                st = int("ST" in name["name"].upper())
                rate = 30.0 if code.endswith(".BJ") else (5.0 if st else (20.0 if code.startswith(("300", "301", "688", "689")) else 10.0))
                tolerance = 0.25 if rate == 5 else (0.35 if rate == 10 else (0.60 if rate == 20 else 0.85))
                up_price = (reference*(1+rate/100.0)).round(2)
                up = (candidate.high-candidate.close).abs().le(0.011) & (expected_pct.ge(rate-tolerance) | candidate.close.ge(up_price-0.031))
                one_word = up & (candidate.open-candidate.close).abs().le(0.011) & (candidate.high-candidate.close).abs().le(0.011) & (candidate.low-candidate.close).abs().le(0.011)
                assert candidate.is_st_snapshot.eq(st).all()
                assert np.array_equal(candidate.is_one_word_limit_up_est.to_numpy(), one_word.astype("int8").to_numpy())
                numeric = candidate.select_dtypes(include=["number", "bool"]).columns
                assert np.isfinite(candidate.iloc[-1][numeric].astype(float).to_numpy()).all()
                nonfinite = {col: candidate.loc[~np.isfinite(candidate[col].to_numpy(dtype=float)), "trade_date"].tolist()
                             for col in numeric if not np.isfinite(candidate[col].to_numpy(dtype=float)).all()}
                assert nonfinite == item["structural_nonfinite_dates_retained"]
                first_date = candidate.trade_date.iloc[0]
                expected_nan = {col: [first_date] for col in ["pre_close", "pct_chg", "amplitude_pct", "upper_shadow_pct", "lower_shadow_pct", "high_20_prev"]}
                delta = candidate.close.diff()
                rsi_denominator = delta.clip(lower=0).rolling(3, min_periods=1).mean()+(-delta).clip(lower=0).rolling(3, min_periods=1).mean()
                expected_nan["zge_rsi3"] = candidate.loc[rsi_denominator.isna() | rsi_denominator.eq(0), "trade_date"].tolist()
                for col, mask in [("bar_close_pos", candidate.high.eq(candidate.low)),
                                  ("amount_ratio_20", candidate.amount.rolling(20, min_periods=1).mean().eq(0))]:
                    if mask.any(): expected_nan[col] = candidate.loc[mask, "trade_date"].tolist()
                expected_nan = {k:v for k,v in expected_nan.items() if v}
                assert nonfinite == expected_nan, "STRUCTURAL_OR_ZERO_DENOMINATOR_NAN_MISMATCH"
                r["per_code"].append(dict(code=code, rows=len(candidate), native_struct_exact=True,
                    exact17_plus3=True, schema63_source_complete=True, event_dates=event_checks,
                    independent_reference_and_pct=True, independent_flags=True, target_finite=True,
                    whole_window_exact_keys=True, structural_nan_boundary=True, name_observed_date=name["trade_date"]))
        assert len(seen) == len(c["codes"]) == 39
        assert len(set(seen)) == len(set(c["codes"])) == 39
        assert sorted(seen) == sorted(c["codes"])
        assert sum(len(x["event_dates"]) for x in r["per_code"]) == sum(e["ts_code"] in c["codes"] for e in events)
        for path, expected in b["files"].items():
            assert sha(path) == expected, f"ARTIFACT_MUTATED:{path}"
        assert attempts[0] == 0
        r.update(status="REMAIN47_INDEPENDENT_SAVED_READBACK_PASS", error=None, resource_ok=True)
    except Exception as exc:
        r.update(error=dict(type=type(exc).__name__, repr=repr(exc), traceback=traceback.format_exc()), resource_ok=False)
    finally:
        socket.socket = old_socket
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    r.update(wall_seconds=time.monotonic()-began, peak_rss_bytes=peak if sys.platform=="darwin" else peak*1024,
             deterministic_metrics=dict(truth_positive_denominator=None, selection_slots=0, reviewed_codes=len(r["per_code"]),
                 canonical_calls=0, network_attempts=attempts[0], formal_writes=0, pointer_writes=0,
                 model_fit_predict_labels_returns=0, windows_connections=0, futu_calls=0, score_role_calls=0),
             scope="NEW39_CURRENT_REVISION_NON_PIT_ENGINEERING_SAVED_ARTIFACTS_ONLY")
    if r["peak_rss_bytes"] > c["resources"]["rss_max_bytes"]:
        r.update(status="REMAIN47_INDEPENDENT_SAVED_READBACK_FAIL", resource_ok=False, error={"repr": "RSS_LIMIT"})
    with output.open("x") as handle:
        json.dump(r, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(dict(status=r["status"], receipt=str(output), sha256=sha(output), error=r["error"] and r["error"]["repr"])))
    return 0 if r["status"] == "REMAIN47_INDEPENDENT_SAVED_READBACK_PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    raise SystemExit(review(args.contract, args.reviewer))
