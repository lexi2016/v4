"""One reviewed, HK-only 20261021 09:31–09:35 cached Futu observation recovery.

PREPARED ONLY. The controller executes after independent review and narrow
runtime integration. This is an incident capsule, never a scheduled entry.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
DATE, STAGE = "20261021", "STAGE_0930_0935"
SHANGHAI = ZoneInfo("Asia/Shanghai")
OPERATOR_ORIGIN = "HK_AUTHORIZED_ONE_SHOT_OPERATOR_RECOVERY"
OPERATOR_MODE = "OPERATOR_RECOVERY"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def exclusive_bytes(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write_once(name, value):
    exclusive_bytes(HERE / name, (json.dumps(value, ensure_ascii=False,
                    indent=2, sort_keys=True) + "\n").encode())


def deny_external(*args, **kwargs):
    raise RuntimeError("EXTERNAL_PROVIDER_FORBIDDEN_IN_EXACT_CSV_RECOVERY")


def seal_one_shot_receipt(payload):
    """Native settled partial means A exists and this one-shot cannot retry.

    HK outcome and pending/partial-commit state remain explicit. This is not
    an assertion that HK completed successfully, or that cap 3 was exhausted.
    Every inner owner write uses this seal, including a crash reservation.
    """
    result = dict(payload)
    require("A_SHARE" in (result.get("markets") or {}), "preserved A lane absent")
    result.update(status="PARTIAL_WITH_ROWS", node_outcome="SETTLED_PARTIAL",
                  node_attempt_count=2, retry_exhausted=False,
                  dispatch_mode=OPERATOR_MODE, execution_origin=OPERATOR_ORIGIN,
                  operator_attempt_limit=1, operator_attempt_consumed=True,
                  operator_retry_authorized=False)
    return result


class OneShotScope:
    """Keep the existing scope merge, seal every native owner receipt write."""

    def __init__(self, original):
        self.original = original

    def __getattr__(self, name):
        return getattr(self.original, name)

    def merge(self, payload, trade_date, stage_id):
        return seal_one_shot_receipt(self.original.merge(payload, trade_date, stage_id))


def a_snapshot(config):
    """Preserve A pointer entries and all its immutable run-file bytes."""
    key = f"{DATE}/{STAGE}/A_SHARE"
    out = {}
    for root_key, index in (("raw_root", "latest.json"),
                            ("selection_root", "selection_latest.json")):
        root = Path(config[root_key]).resolve()
        entry = json.loads((root / index).read_text())["entries"][key]
        artifact = (root / entry["artifact_relative"]).resolve()
        require(artifact.is_relative_to(root), "A artifact escaped original root")
        out[root_key] = {"entry": entry, "files": {
            str(p.relative_to(root)): sha(p) for p in sorted(artifact.parent.iterdir())
            if p.is_file()}}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--review-receipt", required=True, type=Path)
    parser.add_argument("--review-receipt-sha256", required=True)
    parser.add_argument("--execute-reviewed", action="store_true")
    args = parser.parse_args()
    require(args.execute_reviewed, "execution requires reviewed controller command")
    pins = json.loads((HERE / "operator_capsule_pins.json").read_text())
    require(sha(args.review_receipt) == args.review_receipt_sha256, "review identity changed")
    review = json.loads(args.review_receipt.read_text())
    require(review.get("verdict", review.get("status")) == "PASS", "independent PASS absent")
    require(review.get("operator_capsule_sha256") == sha(__file__), "capsule not bound to PASS")
    require(review.get("operator_pins_sha256") == sha(HERE / "operator_capsule_pins.json"),
            "capsule pins not bound to PASS")
    require(datetime.now(SHANGHAI).strftime("%Y%m%d") == DATE, "same-day authorization expired")
    root = args.runtime_root.resolve()
    require(root == Path(pins["expected_runtime_root"]), "release root changed")
    require(args.config.resolve() == Path(pins["expected_config_path"]), "config path changed")
    require(sha(args.config) == pins["expected_config_sha256"], "release config bytes changed")
    require(sha(root.parent / "release-manifest.json") == pins["expected_release_manifest_sha256"],
            "release manifest identity changed")
    require(sha(root / pins["target_relative"]) == pins["candidate_sha256"], "reviewed fix absent")
    for relative, digest in pins["dependency_pins"].items():
        require(sha(root / relative) == digest, f"runtime dependency changed: {relative}")
    config = json.loads(args.config.read_text())
    require(config == pins["expected_config"], "exact reviewed release config changed")
    require(config["release_id"] == "hk-ready-status-20261021-r1", "release_id changed")
    require(config["shared_data_root"] == str(root / "upstreams/v3_shared_data"),
            "shared runtime root changed")
    for path, digest in pins["input_pins"].items():
        require(sha(path) == digest, f"preserved exact input changed: {path}")
    receipt_path = Path(pins["original_receipt_path"])
    require(sha(receipt_path) == pins["original_receipt_sha256"], "original stage receipt changed")
    # All subsequent imports and business work are forbidden from starting a
    # child provider or a network connection. The native slot mutex is POSIX.
    socket.socket.connect = deny_external
    socket.socket.connect_ex = deny_external
    socket.create_connection = deny_external
    subprocess.Popen = deny_external
    os.system = deny_external
    sys.path.insert(0, str(root))
    from ops import run_stage_center_nodes as nodes
    from stage_center import runner as rm
    from stage_center import live_collectors as lc
    from stage_center._runner_parts.runner_receipts import scoped_recovery_runner
    from ops._run_stage_center_nodes_parts.stage_dispatch import _clear_stale_scoped_recovery_failure

    require(Path(rm.__file__).resolve() == root / "stage_center/runner.py", "mixed runtime imports")
    original = nodes._build_runner(config)
    require(not original.config.injected_test_mode, "production input validation must remain enabled")
    lock = rm.SlotLock(rm._slot_lock_path(original.config, DATE, STAGE))
    require(lock.acquire(), "original slot lock busy; leave healthy owner running")
    try:
        require(sha(receipt_path) == pins["original_receipt_sha256"], "receipt changed while locking")
        pending = rm._deadline.pending_receipt_marker(receipt_path)
        require(not pending.exists() and not pending.is_symlink(), "pending deadline receipt marker present")
        prior_raw = receipt_path.read_bytes()
        prior = json.loads(prior_raw)
        require(prior["trade_date"] == DATE and prior["stage_id"] == STAGE, "wrong slot")
        require(prior["node_attempt_count"] == pins["original_attempt_count"] == 1, "budget changed")
        require(config["node_max_attempts"] == 3, "original attempt cap changed")
        require(prior["markets"]["HK_CONNECT"]["cannot_confirm"] ==
                ["HK D1 status is not stage-selection eligible"], "original HK failure changed")
        require(object_sha(prior["markets"]["A_SHARE"]) == pins["expected_a_lane_sha256"], "A lane changed")
        before_a = a_snapshot(config)
        require(before_a == pins["expected_a_snapshot"], "A frozen pointer/files changed")
        binding = rm._build_hk_d1_binding(original.config.hk_d1_root, DATE,
                            preselection_source_root=original.config.preselection_source_root)
        require(set(binding.codes) == set(pins["expected_codes"]) and len(binding.codes) == 100,
                "fixed100 membership changed")
        rm._validated_hk_binding_evidence(binding, DATE)
        rm._validate_hk_second_filter(original.config.hk_second_filter_root, DATE)
        now = datetime.now(SHANGHAI)
        decision = next(d for d in original.due_decisions(DATE, now) if d.stage_id == STAGE)
        require(decision.status in {"DUE", "LATE_CATCHUP_REPLAY"}, "slot is not due")
        decision.same_day_late_observation_recovery = True
        observed = {}

        from cached_source import cached_collector
        require(sha(HERE / "cached_source.py") == pins["support_sha256"], "cache adapter changed")
        csv_only = cached_collector(root, original.config, pins, observed)

        # Use the package's unchanged pure builder and record its real input.
        builders = lc.production_selection_builders(STAGE)
        hk_builder = builders["HK_CONNECT"]

        def recorded_builder(source, plan, raw):
            observed["selector_input_codes"] = [r["code"] for r in source.rows]
            result = hk_builder(source, plan, raw)
            observed["selector_output_codes"] = [r["code"] for r in result["rows"]]
            return result

        original.collectors = {"HK_CONNECT": csv_only}
        def recorded_factory(stage_id, **kwargs):
            require(stage_id == STAGE and not kwargs, "builder scope changed")
            return {"HK_CONNECT": recorded_builder}

        # Observe the production builder factory in this one process. Setting
        # config.selection_builders would enable injected_test_mode and skip
        # production input checks, so that configuration remains untouched.
        lc.production_selection_builders = recorded_factory
        require(not original.config.injected_test_mode, "production checks disabled")
        # The O_EXCL marker plus native counter reservation consumes exactly
        # one authorized attempt even if this process later fails or crashes.
        write_once("operator_recovery_attempt_marker.json", {
            "started_at": now.isoformat(), "original_receipt_sha256": sha(receipt_path),
            "review_receipt_sha256": args.review_receipt_sha256,
            "attempt_number": 2, "market": "HK_CONNECT", "RESEARCH_ONLY": True})
        exclusive_bytes(HERE / "operator_original_receipt.json", prior_raw)
        write_once("operator_a_before.json", before_a)
        scoped = scoped_recovery_runner(original, markets=("HK_CONNECT",), prior_receipt=prior,
                          attempt_count=2, origin=OPERATOR_ORIGIN)
        scoped._execution_scope = OneShotScope(scoped._execution_scope)
        scoped._write_receipt({**prior, "status": "CANNOT_CONFIRM", "node_outcome": "TRANSIENT",
            "node_attempt_count": 2, "retry_exhausted": False, "dispatch_mode": OPERATOR_MODE,
            "execution_pending": True, "partial_commit_possible": True,
            "operator_phase": "RESERVED_PENDING", "write_performed": False}, DATE, STAGE)
        result = scoped._run_one(decision)
        result = _clear_stale_scoped_recovery_failure(prior, result, origin="HK_ORIGINAL_BUDGET_RECOVERY")
        result.update(dispatch_mode=OPERATOR_MODE, node_id=STAGE, execution_pending=False,
                      node_attempt_count=2, retry_exhausted=False,
                      recovered_at=datetime.now(SHANGHAI).isoformat(),
                      operator_phase="RETURNED",
                      recovery_mode="CACHED_AFTERFACT_OBSERVATION_HK_ONLY_OPERATOR")
        hk = result["markets"]["HK_CONNECT"]
        result.update(same_day_late_observation_recovery=True, recovered_observation=True,
            pit_safe=False, temporal_cutoff_safe=False, natural_time_capture="CANNOT_CONFIRM",
            formal_stage_eligibility="CANNOT_CONFIRM", original_window_snapshot="CANNOT_CONFIRM",
            recovery_source_capture_sha256=pins["capture_sha256"], provider_network_requests=0)
        require(hk.get("selected_rows") == 10 and hk.get("selection_status") == "PARTIAL_WITH_ROWS",
                "recovered HK observation10 absent; attempt remains consumed")
        require(len(observed.get("selector_input_codes", [])) == 100
                and set(observed["selector_input_codes"]) == set(pins["expected_codes"]),
                "native full100 selector input absent")
        require({"FUTU_AFTERFACT_CAPTURE_NOT_PIT_SAFE", "HK_HISTORICAL_ORDERBOOK_UNAVAILABLE"}
                <= set(hk.get("cannot_confirm", [])), "recovery gaps absent")
        result["source_evidence"] = list(dict.fromkeys((*result.get("source_evidence", []),
            "recovered_observation=true", "pit_safe=false", "natural_time_capture=CANNOT_CONFIRM",
            "formal_stage_eligibility=CANNOT_CONFIRM", "original_window_snapshot=CANNOT_CONFIRM",
            "active_snapshot_authority=CANNOT_CONFIRM", "provider_network_requests=0",
            "temporal_cutoff_safe_scope=BAR_TIMESTAMPS_ONLY_NOT_CAPTURE_CLOCK",
            f"futu_capture_sha256={pins['capture_sha256']}",
            "futu_captured_at=2026-10-21T09:41:22.678854+08:00")))
        result["node_outcome"] = "SETTLED_PARTIAL"
        result = scoped._write_receipt(result, DATE, STAGE)
        require(result["markets"]["A_SHARE"] == prior["markets"]["A_SHARE"], "A object changed")
        require(a_snapshot(config) == before_a, "A immutable bytes or pointer changed")
        for path, digest in pins["input_pins"].items():
            require(sha(path) == digest, "historical source bytes changed")
        exclusive_bytes(HERE / "operator_recovered_receipt.json", receipt_path.read_bytes())
        write_once("operator_consumption.json", {
            **observed, "finished_at": datetime.now(SHANGHAI).isoformat(),
            "receipt_sha256": sha(receipt_path), "A_PRESERVED": True,
            "provider_invocations": 0, "original_window_full100_capture": "CANNOT_CONFIRM",
            "RESEARCH_ONLY": True, "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False})
        print(json.dumps({"status": "RECOVERY_ATTEMPT_RECORDED", "HK": hk.get("selection_status"),
                          "selected_rows": hk.get("selected_rows"), "evidence_root": str(HERE)}))
    except BaseException as error:
        if (HERE / "operator_recovery_attempt_marker.json").exists():
            failure = {"status": "CANNOT_CONFIRM", "failed_at": datetime.now(SHANGHAI).isoformat(),
                       "error_type": type(error).__name__, "error": str(error),
                       "receipt_sha256": sha(receipt_path), "partial_commit_possible": True,
                       "retry_authorized": False}
            # The reservation and every inner owner write were already sealed.
            # When catchable, also record the honest terminal execution error;
            # an uncatchable crash retains the sealed pending reservation.
            if "scoped" in locals():
                current = json.loads(receipt_path.read_text())
                scoped._write_receipt({**current, "execution_pending": False,
                    "execution_status": "CANNOT_CONFIRM", "operator_phase": "ERROR",
                    "operator_error_type": type(error).__name__, "operator_error": str(error),
                    "partial_commit_possible": True}, DATE, STAGE)
                failure["receipt_sha256"] = sha(receipt_path)
            if not (HERE / "operator_failure.json").exists():
                write_once("operator_failure.json", failure)
        raise
    finally:
        lock.release()


if __name__ == "__main__":
    main()
