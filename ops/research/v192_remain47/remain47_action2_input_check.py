"""New two-event saved-input checks only. No SDK/network call or original22 rerun."""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import socket
import sys
import tempfile
import time
import traceback
sys.dont_write_bytecode = True
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def payload(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main(cp, reviewer):
    c = read(cp)
    b = read(c["input_binding_path"])
    assert reviewer and reviewer != c["WRITER"]
    assert sha(__file__) == c["code_sha256"] and sha(c["input_binding_path"]) == c["input_binding_sha256"]
    start = read(c["registry_start_path"])
    assert start["execution_id"] == c["execution_id"] and start["event_type"] == "RUN_STARTED"
    began = time.monotonic()
    r = dict(execution_id=c["execution_id"], route_id=c["route_id"], reviewer=reviewer,
        contract_sha256=sha(cp), code_sha256=sha(__file__), input_binding_sha256=sha(c["input_binding_path"]),
        payload_sha256=b["increment_sha256"], status="ACTION2_NEW_INPUT_CHECK_FAIL", artifacts={},
        passed_cases=[], event_results=[], research_only=True, production_allowed=False,
        buy_gate_updated=False, orders_sent=False)
    old_socket = socket.socket
    network_attempts = [0]

    def blocked(*args, **kwargs):
        network_attempts[0] += 1
        raise RuntimeError("ACTION2_NETWORK_FORBIDDEN")

    socket.socket = blocked
    try:
        for path, expected in b["files"].items():
            assert sha(path) == expected, path
        spec = importlib.util.spec_from_file_location("remain47_exact_two_action_inputs", b["increment_path"])
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        assert m.MAX_CROSS_DAY_CLOSE_RATIO == 1.5
        refs = m._load_action_reference_manifest(b["manifest_path"], b["manifest_sha256"])
        original_manifest = read(b["manifest_path"])
        assert set(refs["events"]) == {("688678", 1, 20240606), ("920976", 2, 20240606)}
        # One isolated directory owns all synthetic invalid manifests/local2bar files.
        with tempfile.TemporaryDirectory(prefix="NEXT_REMAIN47_ACTION2_TMP_", dir=c["batch_path"]) as temporary:
            temporary = Path(temporary)
            for item in b["cases"]:
                code, market = item["code"], item["market"]
                saved = read(item["full_response_path"])["response_rows"]
                rows = [row for row in saved if m.day_int(row) <= 20261020]
                before = payload(saved)
                calls = []

                class Replay:
                    def get_security_bars(self, category, request_market, symbol, start, count):
                        assert (category, request_market, symbol, start, count) == (9, market, code, 0, 800)
                        calls.append(1)
                        assert len(calls) == 1
                        return copy.deepcopy(rows)

                target = m.DailyTarget(code, market, Path(item["original_native_path"]))
                provider_audit = []
                accepted, reason = m._fetch_valid_target_bars(Replay(), target, 20261020, None, 800, None,
                    action_references=refs, reference_audit=provider_audit)
                assert reason == "OK" and accepted == rows and len(calls) == 1, (code, reason)
                assert payload(saved) == before
                assert len(provider_audit) == 1 and provider_audit[0]["identity_match"]
                event = next(event for event in original_manifest["events"] if event["code"] == code)
                # Independent arithmetic oracle only for the two newly approved references.
                expected = ((event["prior_close"]-event["terms"]["cash_per_share"])
                            /(1.0+event["terms"]["share_change_ratio"]))
                assert abs(provider_audit[0]["calculated_reference"]-expected) <= 1e-12
                assert 1/1.5 <= event["event_close"]/expected <= 1.5
                pair = [row for row in rows if m.day_int(row) in (20240605, 20240606)]
                assert len(pair) == 2
                prefix = {1: "sh", 2: "bj"}[market]
                local = temporary / (prefix+code+".day")
                local.write_bytes(b"".join(m.pack_hq_bar(row) for row in pair))
                local_audit = []
                local_bars, local_reason = m._local_history_status(local, 20240606,
                    action_references=refs, reference_audit=local_audit)
                assert local_reason is None and len(local_bars) == 2
                assert len(local_audit) == 1 and local_audit[0]["identity_match"]
                assert abs(local_audit[0]["calculated_reference"]-expected) <= 1e-12
                r["passed_cases"].extend([code+":saved_provider_guard", code+":native_pair_guard"])
                r["event_results"].append(dict(code=code, market=market,
                    calculated_reference=provider_audit[0]["calculated_reference"],
                    independent_reference=expected, eligible_rows=len(rows),
                    provider_reference_audit=provider_audit, local_reference_audit=local_audit,
                    raw_prices_unchanged=True, original_threshold=1.5))

            variants = [
                ("new_code_not_whitelisted", 0, "code", "688679"),
                ("new_date_not_whitelisted", 0, "event_date", 20240607),
                ("wrong_market_for_BJ", 1, "market", 0),
                ("market_bool_type", 1, "market", True),
                ("wrong_prior_date", 0, "prior_date", 20240604),
                ("wrong_prior_price", 0, "prior_close", 15.43),
                ("wrong_event_price", 1, "event_close", 9.01),
                ("wrong_prior_bar_bytes", 0, "prior_bar_sha256", "0"*64),
                ("wrong_event_bar_bytes", 1, "event_bar_sha256", "0"*64),
                ("nominal_cash_not_diluted", 0, "terms.cash_per_share", 0.30),
                ("nominal_ratio_not_diluted", 0, "terms.share_change_ratio", 0.40),
                ("cash_string_type", 0, "terms.cash_per_share", "0.2966"),
                ("ratio_per10_wrong_unit", 1, "terms.share_change_ratio", 4.0),
                ("unexpected_rights_term", 1, "terms.rights_price", 0.1),
                ("CS_domain_other_pdf_forbidden", 0, "evidence.0.url", "https://epaper.cs.com.cn/other.pdf"),
                ("Sina_url_suffix_change_forbidden", 1, "evidence.0.url", original_manifest["events"][1]["evidence"][0]["url"]+"?other=1"),
                ("PDF_byte_identity_mismatch", 0, "evidence.0.sha256", "0"*64),
                ("source_response_identity_mismatch", 1, "source_response.sha256", "0"*64),
            ]
            for n, (name, index, dotted, value) in enumerate(variants):
                changed = copy.deepcopy(original_manifest)
                target = changed["events"][index]
                parts = dotted.split(".")
                for part in parts[:-1]:
                    target = target[int(part)] if isinstance(target, list) else target[part]
                target[parts[-1]] = value
                path = temporary / (f"negative_{n}.json")
                path.write_bytes(payload(changed))
                try:
                    m._load_action_reference_manifest(path, sha(path))
                except m.ActionReferenceError:
                    r["passed_cases"].append(name)
                else:
                    raise AssertionError("NEGATIVE_NOT_REJECTED:"+name)
            # Unknown symbols keep the unadjusted original guard; the exception is not global.
            sample = b["cases"][0]
            pair = [row for row in read(sample["full_response_path"])["response_rows"]
                    if m.day_int(row) in (20240605, 20240606)]

            class UnknownReplay:
                def get_security_bars(self, *args):
                    assert args == (9, 1, "688679", 0, 800)
                    return copy.deepcopy(pair)

            _, unknown_reason = m._fetch_valid_target_bars(UnknownReplay(),
                m.DailyTarget("688679", 1, temporary/"sh688679.day"), 20240606, None, 800, None,
                action_references=refs)
            assert unknown_reason == m.CROSS_DAY_CLOSE_RATIO
            r["passed_cases"].append("unknown_symbol_original_ratio_guard_preserved")
        for path, expected in b["files"].items():
            assert sha(path) == expected, path
        assert network_attempts[0] == 0
        r.update(status="ACTION2_NEW_INPUT_CHECK_PASS", error=None, resource_ok=True)
    except Exception as exc:
        r.update(error=dict(type=type(exc).__name__, repr=repr(exc), traceback=traceback.format_exc()), resource_ok=False)
    finally:
        socket.socket = old_socket
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    r.update(wall_seconds=time.monotonic()-began, peak_rss_bytes=peak if sys.platform=="darwin" else peak*1024,
        deterministic_metrics=dict(truth_positive_denominator=None, selection_slots=0,
            passed_cases=len(r["passed_cases"]), new_events_checked=len(r["event_results"]),
            network_attempts=network_attempts[0], live_queries=0, canonical_calls=0,
            score_role_calls=0, formal_writes=0, source_writes=0, old22_reruns=0))
    if r["peak_rss_bytes"] > 2147483648:
        r.update(status="ACTION2_NEW_INPUT_CHECK_FAIL", error={"repr":"RSS_LIMIT"}, resource_ok=False)
    output = Path(c["receipt_path"])
    with output.open("x") as handle:
        json.dump(r, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(dict(status=r["status"], receipt=str(output), sha256=sha(output),
        passed_cases=len(r["passed_cases"]), error=r.get("error") and r["error"]["repr"])))
    return 0 if r["status"] == "ACTION2_NEW_INPUT_CHECK_PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.contract, args.reviewer))
