from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
TRADE_DATE = "20260930"
STAGE_ID = "STAGE_0925"
CUTOFF_AT = datetime.fromisoformat("2026-09-30T09:25:05+08:00")
APP = Path("[REDACTED_LOCAL_CANDIDATE_APP_ROOT]")
CANARY_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP / "stage_center_tick_config.json"


def file_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def codes_sha(codes: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()


def iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


def main() -> int:
    started_at = datetime.now(SHANGHAI)
    receipt: dict[str, object] = {
        "schema_version": "a0925_single_stock_recovery_canary.v1",
        "canary_status": "CANNOT_CONFIRM",
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "cutoff_at": CUTOFF_AT.isoformat(timespec="seconds"),
        "started_at": iso(started_at),
        "timezone": "Asia/Shanghai",
        "requested_capture_mode": "RECOVERY",
        "provider_capture_mode": None,
        "provider_snapshot_calls": 0,
        "selected_code": None,
        "result_status": None,
        "rows": [],
        "cannot_confirm": [],
        "error": None,
        "formal_writes_performed": False,
        "service_started": False,
        "hk_d1_called": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }

    sys.path.insert(0, str(APP))
    sys.path.insert(0, str(APP / "upstreams"))

    try:
        if started_at.strftime("%Y%m%d") != TRADE_DATE:
            raise RuntimeError("local Asia/Shanghai date is not the requested trade date")
        if started_at <= CUTOFF_AT:
            raise RuntimeError("current local time has not passed the 09:25:05 cutoff")

        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if config.get("release_id") != "20260930-stage-auction-witness-hk-recovery-r1":
            raise RuntimeError("candidate release identity mismatch")
        data_root = Path(config["candidate_acquisition_root"])
        source_root = Path(config["preselection_source_root"])
        from stage_center.candidate_input import read_candidate_input
        from stage_center.acquisition import build_plan
        from stage_center.live_collectors import collect_a_share_auction
        from infrastructure.preselection_pool_store import PreselectionPoolStore
        from infrastructure.stage_acquisition_universe_contracts import read_strict_a_preselection_snapshot
        from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider

        candidate = read_candidate_input(data_root, TRADE_DATE)
        if candidate.trade_date != TRADE_DATE or len(candidate.codes) != 205 or len(set(candidate.codes)) != 205:
            raise RuntimeError("canonical candidate input is not the verified 205-code exact-date set")
        snapshot = read_strict_a_preselection_snapshot(PreselectionPoolStore(source_root), TRADE_DATE)
        if not snapshot.ready or snapshot.row_count != 205 or snapshot.codes != candidate.codes:
            raise RuntimeError("fresh strict pool snapshot does not match canonical 205-code candidate input")

        eligible = []
        for code in candidate.codes:
            if not re.fullmatch(r"A\.\d{6}", code):
                continue
            numeric = code[2:]
            if numeric.startswith(("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688")):
                eligible.append(code)
        if not eligible:
            raise RuntimeError("verified input has no eligible Shanghai/Shenzhen A-share code")
        selected_code = eligible[0]
        numeric = selected_code[2:]
        exchange = "SH" if numeric.startswith(("600", "601", "603", "605", "688")) else "SZ"

        plan = build_plan(data_root, TRADE_DATE, STAGE_ID, candidate=candidate)
        if plan.trade_date != TRADE_DATE or plan.stage_id != STAGE_ID or plan.codes_for("A_SHARE") != candidate.codes:
            raise RuntimeError("public acquisition plan is not bound to the verified candidate input")
        if any(plan.safety.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")):
            raise RuntimeError("public acquisition plan safety flags are not all false")

        class OneShotProvider:
            def __init__(self) -> None:
                self.inner = TdxMinuteReplayProvider()
                self.calls = 0
                self.request: dict[str, object] | None = None
                self.payload: dict[str, object] | None = None
                self.error: dict[str, object] | None = None

            def snapshot(self, symbols, *, trade_date, stage_id, cutoff_at):
                self.calls += 1
                if self.calls != 1:
                    raise RuntimeError("canary permits exactly one provider snapshot call")
                self.request = {
                    "symbols": list(symbols),
                    "trade_date": trade_date,
                    "stage_id": stage_id,
                    "cutoff_at": cutoff_at,
                }
                try:
                    self.payload = self.inner.snapshot(
                        symbols,
                        trade_date=trade_date,
                        stage_id=stage_id,
                        cutoff_at=cutoff_at,
                    )
                    return self.payload
                except Exception as error:
                    diagnostics = getattr(error, "diagnostics", None)
                    self.error = {
                        "type": type(error).__name__,
                        "message": str(error)[:5000],
                        "diagnostics": diagnostics,
                    }
                    raise

        provider = OneShotProvider()
        collector_started_at = datetime.now(SHANGHAI)
        result = collect_a_share_auction(
            plan,
            codes=(selected_code,),
            python_path=config["python_path"],
            shared_root=config["shared_data_root"],
            auction_root=config["a_auction_root"],
            replay_provider=provider,
        )
        finished_at = datetime.now(SHANGHAI)

        rows = [dict(row) for row in result.rows]
        payload = provider.payload or {}
        type_error = bool(provider.error and provider.error.get("type") == "TypeError") or "TypeError" in str(result.error)
        exact_expected_tick = f"{TRADE_DATE[:4]}-{TRADE_DATE[4:6]}-{TRADE_DATE[6:]} 09:25:00"
        row_ok = (
            len(rows) == 1
            and rows[0].get("code") == selected_code
            and rows[0].get("trade_date") == TRADE_DATE
            and rows[0].get("update_time") == exact_expected_tick
            and rows[0].get("source_last_tick_time") == exact_expected_tick
            and rows[0].get("temporal_cutoff_safe") is True
        )
        payload_cutoff = None
        payload_capture = None
        if payload.get("market_cutoff_at"):
            payload_cutoff = datetime.fromisoformat(str(payload["market_cutoff_at"]))
        if payload.get("captured_at"):
            payload_capture = datetime.fromisoformat(str(payload["captured_at"]))
        methods = {"pytdx.hq.get_transaction_data", "pytdx.hq.get_history_transaction_data"}
        payload_ok = (
            payload.get("trade_date") == TRADE_DATE
            and payload.get("stage_id") == STAGE_ID
            and payload.get("temporal_cutoff_safe") is True
            and payload.get("capture_mode") == "RECOVERY"
            and payload.get("source_method") in methods
            and payload_cutoff == CUTOFF_AT
            and payload_capture is not None
            and payload_capture.strftime("%Y%m%d") == TRADE_DATE
            and payload_capture > CUTOFF_AT
            and all(payload.get(key) is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
            and "CANNOT_CONFIRM_NATURAL_0925_CAPTURE_RECOVERY_ONLY" in (payload.get("cannot_confirm") or [])
        )
        if type_error:
            canary_status = "FAIL"
        elif row_ok and payload_ok and provider.calls == 1:
            canary_status = "PASS"
        else:
            canary_status = "CANNOT_CONFIRM"

        receipt.update({
            "canary_status": canary_status,
            "candidate_input": {
                "root": str(candidate.root),
                "trade_date": candidate.trade_date,
                "run_id": candidate.run_id,
                "code_count": len(candidate.codes),
                "unique_code_count": len(set(candidate.codes)),
                "codes_sha256": codes_sha(candidate.codes),
                "current_relative": candidate.current_relative,
                "current_bytes_sha256": candidate.current_bytes_sha256,
                "artifact_sha256": candidate.artifact_sha256,
                "artifact_bytes_sha256": candidate.artifact_bytes_sha256,
                "manifest_sha256": candidate.manifest_sha256,
                "manifest_bytes_sha256": candidate.manifest_bytes_sha256,
                "receipt_sha256": candidate.receipt_sha256,
                "receipt_bytes_sha256": candidate.receipt_bytes_sha256,
                "commit_id": candidate.commit_id,
                "commit_marker_bytes_sha256": candidate.commit_marker_bytes_sha256,
                "source_projection_sha256": candidate.source_projection_sha256,
                "source_pool_set_sha256": candidate.source_pool_set_sha256,
                "source_evidence": list(candidate.source_evidence),
            },
            "fresh_preselection_snapshot": {
                "trade_date": snapshot.trade_date,
                "status": snapshot.status,
                "ready": snapshot.ready,
                "row_count": snapshot.row_count,
                "unique_code_count": len(set(snapshot.codes)),
                "codes_sha256": codes_sha(snapshot.codes),
                "pool_contribution_counts": dict(snapshot.pool_contribution_counts),
                "blocking_reasons": list(snapshot.blocking_reasons),
                "pool_diagnostics": {key: list(value) for key, value in snapshot.pool_diagnostics.items()},
            },
            "plan": {
                "trade_date": plan.trade_date,
                "stage_id": plan.stage_id,
                "a_share_route": plan.a_share_route,
                "candidate_code_count": len(plan.codes_for("A_SHARE")),
                "safety": dict(plan.safety),
            },
            "selection_rule": "first candidate-order code in verified 205 matching known Shanghai/Shenzhen A-share prefixes",
            "selected_code": selected_code,
            "selected_exchange": exchange,
            "selected_code_in_verified_input": selected_code in candidate.codes,
            "provider_snapshot_calls": provider.calls,
            "provider_request": provider.request,
            "provider_payload": payload or None,
            "provider_error": provider.error,
            "collector": {
                "status": result.status,
                "rows": rows,
                "requested_rows": result.requested_rows,
                "missing_symbols": list(result.missing_symbols),
                "cannot_confirm": list(result.cannot_confirm),
                "error": result.error,
                "source_evidence": list(result.source_evidence),
            },
            "type_error_seen": type_error,
            "exact_tick_row_verified": row_ok,
            "recovery_payload_verified": payload_ok,
            "collector_started_at": iso(collector_started_at),
            "finished_at": iso(finished_at),
            "runtime": {
                "executable": sys.executable,
                "configured_executable": config["python_path"],
                "python_version": sys.version,
                "pytdx_version": version("pytdx"),
                "pandas_version": version("pandas"),
            },
            "candidate_code_sha256": {
                "stage_center_tick_config.json": file_sha(CONFIG_PATH),
                "release-manifest.json": file_sha(APP.parent / "release-manifest.json"),
                "stage_center/acquisition.py": file_sha(APP / "stage_center/acquisition.py"),
                "stage_center/candidate_input.py": file_sha(APP / "stage_center/candidate_input.py"),
                "stage_center/live_collectors.py": file_sha(APP / "stage_center/live_collectors.py"),
                "stage_center/_live_collectors_parts/a_auction.py": file_sha(APP / "stage_center/_live_collectors_parts/a_auction.py"),
                "infrastructure/tdx_minute_replay_provider.py": file_sha(APP / "infrastructure/tdx_minute_replay_provider.py"),
                "infrastructure/stage_acquisition_universe_contracts.py": file_sha(APP / "infrastructure/stage_acquisition_universe_contracts.py"),
            },
            "generated_exact_date_auction_csv": str(Path(config["a_auction_root"]) / "generated_stages" / TRADE_DATE / f"generated_stage1_0925_auction_{TRADE_DATE}.csv"),
            "generated_exact_date_auction_csv_sha256": file_sha(Path(config["a_auction_root"]) / "generated_stages" / TRADE_DATE / f"generated_stage1_0925_auction_{TRADE_DATE}.csv"),
        })
    except Exception as error:
        receipt["canary_status"] = "CANNOT_CONFIRM"
        receipt["error"] = {"type": type(error).__name__, "message": str(error)[:5000]}
        if isinstance(error, TypeError):
            receipt["type_error_seen"] = True
            receipt["canary_status"] = "FAIL"
    finally:
        receipt["finished_at"] = iso(datetime.now(SHANGHAI))
        receipt["script_sha256"] = file_sha(Path(__file__).resolve())
        receipt_path = CANARY_DIR / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "canary_status": receipt.get("canary_status"),
            "selected_code": receipt.get("selected_code"),
            "provider_snapshot_calls": receipt.get("provider_snapshot_calls"),
            "type_error_seen": receipt.get("type_error_seen", False),
            "receipt_path": str(receipt_path),
        }, ensure_ascii=False))
    return 0 if receipt.get("canary_status") in {"PASS", "CANNOT_CONFIRM"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
