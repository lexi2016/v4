"""stage_center.runner: hk_input_validation (review candidate, not deployment)."""
from __future__ import annotations
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from stage_center.acquisition import StageUniverseBinding
from stage_center.calendar import TradingDayState
from stage_center.calendar import resolve_market_states
from stage_center.contracts import SAFETY_FLAGS
from typing import Mapping
import csv
import hashlib
import json
import re
from stage_center.runner import RunnerError, _find_exact_file, _hk_selection_codes, _sha, _validate_hk_d1, _validate_hk_second_filter


def __candidate_from_hk_binding_body(*, root, trade_date, binding):
    """Build a plan-only candidate view from the verified HK universe.

    Stage Center's historical ``AcquisitionPlan`` carries one candidate field
    for compatibility.  When the A current is absent, this adapter supplies
    only the HK lane's exact D-1 Top100 binding; it is never used to make
    an A-share selection appear ready.
    """
    from stage_center.candidate_input import CandidateInput

    return CandidateInput(
        root=Path(root).expanduser().resolve(),
        trade_date=trade_date,
        current_relative=f"bindings/{trade_date}/HK_CONNECT/{binding.role}/current.json",
        current_sha256=binding.sha256,
        run_id=binding.source_run_id or f"hk-{binding.sha256[:16]}",
        codes=tuple(binding.codes),
        artifact_sha256=binding.sha256,
        manifest_sha256=binding.sha256,
        receipt_sha256=binding.sha256,
        source_projection_sha256=binding.sha256,
        source_evidence=tuple(binding.evidence),
    )


def __validate_hk_d1_body(root, trade_date, *, preselection_source_root):
    resolved_snapshot: Mapping[str, Any] | None = None
    source_resolver = None
    if preselection_source_root is not None:
        from infrastructure.preselection_pool_store import PreselectionSourceResolver

        source_resolver = PreselectionSourceResolver(root, source_root=preselection_source_root)
        try:
            resolved_snapshot = source_resolver.read_pool_snapshot(
                trade_date, "hkconnect_d1_top100"
            )
        except (OSError, ValueError) as error:
            raise RunnerError(f"HK D1 snapshot integrity invalid: {error}") from error
        path = Path(resolved_snapshot["physical_source_root"]) / resolved_snapshot["artifact_relative"]
    else:
        path = _find_exact_file(root, trade_date, "hkconnect_d1_top100.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError("HK D1 input unreadable") from error
    if resolved_snapshot is not None:
        if resolved_snapshot.get("artifact") != payload:
            raise RunnerError("HK D1 resolved trio changed during validation")
        try:
            current_snapshot = source_resolver.read_pool_snapshot(
                trade_date, "hkconnect_d1_top100"
            )
        except (OSError, ValueError) as error:
            raise RunnerError("HK D1 resolved source identity changed during validation") from error
        for identity_key in (
            "pool_sha256", "artifact_raw_sha256", "manifest_raw_sha256",
            "receipt_raw_sha256", "physical_source_root", "artifact_relative",
            "manifest_relative", "receipt_relative",
        ):
            if current_snapshot.get(identity_key) != resolved_snapshot.get(identity_key):
                raise RunnerError("HK D1 resolved source identity changed during validation")
        schema_version = payload.get("schema_version")
        if schema_version == "v3_5.preselection_pool.v1":
            if "target_date" in payload and payload.get("target_date") != trade_date:
                raise RunnerError("HK D1 exact-source target_date mismatch")
            if "stage_selection_eligible" in payload and payload.get("stage_selection_eligible") is not True:
                raise RunnerError("HK D1 exact-source stage_selection_eligible is not true")
        elif payload.get("target_date") != trade_date or payload.get("stage_selection_eligible") is not True:
            raise RunnerError("HK D1 exact-source explicit target/eligibility mismatch")
    d1_status = payload.get("status")
    partial_d1 = d1_status == "PARTIAL_WITH_ROWS"
    if d1_status not in {"STRICT_0_2_READY", "PARTIAL_WITH_ROWS"}:
        raise RunnerError("HK D1 status is not stage-selection eligible")
    if resolved_snapshot is not None and (
        payload.get("pool_id") != "hkconnect_d1_top100"
        or payload.get("producer_id") != "v3_shared_hk_0_2_consumer_v1"
        or payload.get("source_role") != (
            "UPSTREAM_PRODUCER_ARTIFACT" if partial_d1 else "SHARED_VERIFIED_HK_0_2"
        )
    ):
        raise RunnerError("HK D1 exact-source producer/source identity mismatch")
    if partial_d1:
        run_id = str(payload.get("source_run_id") or "")
        source_sha = str(payload.get("source_sha256") or "").lower()
        reasons = payload.get("cannot_confirm")
        expected_source_path = (
            f"runs/{trade_date}/HK_CONNECT_D1_TOP100_0_2/{run_id}/artifact.csv"
        )
        if (
            payload.get("schema_version") != "v3_5.preselection_pool.v1"
            or payload.get("market") != "HK"
            or payload.get("target_date") != trade_date
            or payload.get("stage_selection_eligible") is not True
            or payload.get("signal_date") != str(payload.get("signal_date") or "")
            or re.fullmatch(r"\d{8}", str(payload.get("signal_date") or "")) is None
            or re.fullmatch(
                re.escape(trade_date) + r"-hk-connect-d1-top100-0-2-[0-9a-f]{12}",
                run_id,
            ) is None
            or payload.get("source_path") != expected_source_path
            or re.fullmatch(r"[0-9a-f]{64}", source_sha) is None
            or payload.get("source_artifact_sha256") != source_sha
            or payload.get("source_row_count") != len(payload.get("rows") or ())
            or not isinstance(reasons, list)
            or not reasons
            or any(
                not str(reason).startswith("HK_0_2_")
                for reason in reasons
            )
        ):
            raise RunnerError(
                "HK D1 partial source provenance/diagnostics invalid"
            )
    if any(payload.get(flag) is not False for flag in SAFETY_FLAGS):
        raise RunnerError("HK D1 safety flags must be false")
    rows = payload.get("rows", payload.get("data"))
    if (
        not isinstance(rows, list)
        or (partial_d1 and not 1 <= len(rows) <= 100)
        or (not partial_d1 and len(rows) != 100)
    ):
        raise RunnerError(
            "HK D1 partial input must contain 1..100 rows"
            if partial_d1 else "HK D1 input must contain exactly 100 rows"
        )
    envelope_date = payload.get("target_date", payload.get("trade_date"))
    if envelope_date is not None:
        if envelope_date != trade_date:
            raise RunnerError("HK D1 target_date mismatch")
    else:
        row_dates = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise RunnerError("HK D1 row must be an object")
            row_date = row.get("target_date", row.get("trade_date"))
            if row_date is None:
                raise RunnerError("HK D1 target_date missing")
            row_dates.add(str(row_date))
        if row_dates != {trade_date}:
            raise RunnerError("HK D1 target_date mismatch")
    for row in rows:
        if not isinstance(row, Mapping):
            raise RunnerError("HK D1 row must be an object")
        row_date = row.get("target_date", row.get("trade_date"))
        if row_date is not None and str(row_date) != trade_date:
            raise RunnerError("HK D1 row target_date mismatch")
    # Current authority rows identify the selected model as ``prob_active``
    # (some historical fixtures omit the optional field). When present, bind
    # it explicitly so a strict-status Top100 from another model cannot pass
    # as the HK primary contract.
    model_values = []
    for key in ("model_id", "model", "model_name", "selected_strategy", "weekly_tuning_selected_strategy"):
        value = payload.get(key)
        if value not in (None, ""):
            model_values.append(str(value))
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in ("model_id", "model", "model_name", "selected_strategy", "weekly_tuning_selected_strategy"):
            value = row.get(key)
            if value not in (None, ""):
                model_values.append(str(value))
    if model_values and any("prob_active" not in value.lower() for value in model_values):
        raise RunnerError("HK D1 model identity must be prob_active")
    if payload.get("schema_version") == "v3_5.preselection_pool.v1":
        from infrastructure.preselection_pool_store import PreselectionPoolStore

        # Canonical V4 inputs must use the exact-date physical trio.  The
        # older, standalone D1 JSON adapter below remains a read-only legacy
        # contract; a canonical object cannot downgrade to that adapter.
        if path.parent.name != trade_date or path.parent.parent.name != "preselection_pools":
            raise RunnerError("HK D1 canonical snapshot path invalid")
        try:
            snapshot = PreselectionPoolStore(path.parent.parent.parent).read_pool_snapshot(
                trade_date, "hkconnect_d1_top100"
            )
        except (OSError, ValueError) as error:
            raise RunnerError(f"HK D1 snapshot integrity invalid: {error}") from error
        if snapshot.get("payload") != payload:
            raise RunnerError("HK D1 snapshot changed during validation")
        open_states = {
            TradingDayState.FULL_TRADING_DAY,
            TradingDayState.HALF_TRADING_DAY_AM,
        }

        def previous_session(market: str) -> str:
            cursor = datetime.strptime(
                trade_date, "%Y%m%d"
            )
            for _ in range(15):
                cursor -= timedelta(days=1)
                candidate = cursor.strftime("%Y%m%d")
                state = resolve_market_states(candidate)[market]
                if state is TradingDayState.UNKNOWN:
                    raise RunnerError(
                        "HK D1 signal/eligibility calendar CANNOT_CONFIRM"
                    )
                if state in open_states:
                    return candidate
            raise RunnerError(
                "HK D1 signal/eligibility calendar CANNOT_CONFIRM"
            )

        price_signal_date = previous_session("hk_securities")
        eligibility_source_date = previous_session("hk_connect")
        expected_source_role = (
            "UPSTREAM_PRODUCER_ARTIFACT" if partial_d1 else "SHARED_VERIFIED_HK_0_2"
        )
        if payload.get("market") != "HK" or payload.get("source_role") != expected_source_role:
            raise RunnerError("HK D1 market/source role mismatch")
        if payload.get("signal_date") not in (None, price_signal_date):
            raise RunnerError("HK D1 envelope signal_date mismatch")
        if price_signal_date != eligibility_source_date:
            provenance = payload.get("historical_provenance")
            if not isinstance(provenance, Mapping):
                raise RunnerError(
                    "HK D1 split-date eligibility provenance missing"
                )
            required_hashes = (
                "eligibility_source_artifact_sha256",
                "d1_source_artifact_sha256",
                "d1_source_manifest_sha256",
                "d1_source_receipt_sha256",
            )
            if (
                provenance.get("schema_version") != "v4.hk_d1_split_date_provenance.v1"
                or provenance.get("price_signal_date") != price_signal_date
                or provenance.get("eligibility_source_date") != eligibility_source_date
                or provenance.get("eligibility_source_run_id") in (None, "")
                or any(
                    not re.fullmatch(
                        r"[0-9a-f]{64}", str(provenance.get(key) or "")
                    )
                    for key in required_hashes
                )
                or provenance.get("d1_source_run_id") != payload.get("source_run_id")
                or provenance.get("d1_source_artifact_sha256") != payload.get("source_sha256")
                or provenance.get("d1_source_manifest_sha256") != payload.get("source_manifest_sha256")
                or provenance.get("d1_source_receipt_sha256") != payload.get("source_receipt_sha256")
            ):
                raise RunnerError(
                    "HK D1 split-date provenance identity mismatch"
                )
            captured_at = str(
                provenance.get("eligibility_source_captured_at") or ""
            )
            try:
                from zoneinfo import ZoneInfo

                captured = datetime.fromisoformat(captured_at)
            except ValueError as error:
                raise RunnerError(
                    "HK D1 eligibility source capture time invalid"
                ) from error
            if (
                captured.tzinfo is None
                or captured.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
                != eligibility_source_date
            ):
                raise RunnerError(
                    "HK D1 eligibility source capture date mismatch"
                )
        codes = []
        for row in rows:
            if row.get("market") != "HK" or row.get("signal_date") != price_signal_date:
                raise RunnerError("HK D1 row market/signal_date mismatch")
            code = row.get("symbol", row.get("code"))
            if not isinstance(code, str) or re.fullmatch(r"HK\.\d{5}", code) is None:
                raise RunnerError("HK D1 row code invalid")
            if any(row.get(key) not in (None, code) for key in ("code", "symbol")):
                raise RunnerError("HK D1 row code/symbol identity mismatch")
            if any(row.get(key) not in (None, trade_date) for key in ("trade_date", "target_date")):
                raise RunnerError("HK D1 row trade/target_date mismatch")
            codes.append(code)
        unique_count = len(set(codes))
        if unique_count != len(rows) or (
            partial_d1 and not 1 <= unique_count <= 100
        ) or (not partial_d1 and unique_count != 100):
            raise RunnerError(
                "HK D1 partial rows must be unique and within 1..100"
                if partial_d1 else "HK D1 unique Top100 required"
            )
    digest = _sha(path)
    if resolved_snapshot is not None and (
        digest != resolved_snapshot.get("artifact_raw_sha256")
        or source_resolver.root_for_date(trade_date)
        != Path(str(resolved_snapshot["physical_source_root"]))
    ):
        raise RunnerError("HK D1 resolved source identity changed during validation")
    return path, digest


def __validate_hk_full_universe_body(root, trade_date):
    path = _find_exact_file(root, trade_date, "HK_CONNECT_FULL_MARKET.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError("HK full universe unreadable") from error
    if payload.get("trade_date") != trade_date or payload.get("market") != "HK_CONNECT" or payload.get("scope") != "FULL_MARKET":
        raise RunnerError("HK full universe identity/scope mismatch")
    if any(payload.get(flag) is not False for flag in SAFETY_FLAGS):
        raise RunnerError("HK full universe safety flag must be false")
    codes = payload.get("codes")
    if not isinstance(codes, list) or len(codes) < 500 or len(set(codes)) != len(codes) or any(not re.fullmatch(r"HK\.\d{5}", str(code)) for code in codes):
        raise RunnerError("HK full universe must contain unique 500+ HK codes")
    digest = hashlib.sha256(json.dumps(codes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if payload.get("codes_sha256") != digest:
        raise RunnerError("HK full universe codes SHA mismatch")
    return path, tuple(str(code) for code in codes), _sha(path)


def __hk_selection_codes_body(root, trade_date, *, preselection_source_root):
    if preselection_source_root is None:
        path, path_sha = _validate_hk_d1(root, trade_date)
    else:
        path, path_sha = _validate_hk_d1(
            root, trade_date, preselection_source_root=preselection_source_root
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", payload.get("data"))
    codes: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw = str(row.get("code") or row.get("ts_code") or row.get("stock_code") or "").strip().upper()
        match = re.search(r"(?:HK\.)?(\d{5})", raw)
        if match:
            codes.add(f"HK.{match.group(1)}")
    partial_d1 = payload.get("status") == "PARTIAL_WITH_ROWS"
    if len(codes) != len(rows) or (
        partial_d1 and not 1 <= len(codes) <= 100
    ) or (not partial_d1 and len(codes) != 100):
        raise RunnerError(
            "HK D1 partial code set must contain 1..100 unique codes"
            if partial_d1 else "HK D1 selection code set must contain exactly 100 unique codes"
        )
    return codes, path_sha


def __build_hk_d1_binding_body(root, trade_date, *, preselection_source_root):
    """Create the exact fixed D-1 membership shared by acquisition and selection."""
    if preselection_source_root is None:
        path, source_sha = _validate_hk_d1(root, trade_date)
        codes, _codes_sha = _hk_selection_codes(root, trade_date)
    else:
        path, source_sha = _validate_hk_d1(
            root, trade_date, preselection_source_root=preselection_source_root
        )
        codes, _codes_sha = _hk_selection_codes(
            root, trade_date, preselection_source_root=preselection_source_root
        )
    if _codes_sha != source_sha:
        raise RunnerError("HK D1 membership SHA changed during binding")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError("HK D1 binding status unreadable") from error
    if _sha(path) != source_sha:
        raise RunnerError("HK D1 binding status changed during read")
    partial_d1 = payload.get("status") == "PARTIAL_WITH_ROWS"
    binding_evidence = (
        f"hk_d1_json={path}",
        f"hk_d1_sha256={source_sha}",
        f"hk_d1_status={'PARTIAL_WITH_ROWS' if partial_d1 else 'STRICT_0_2_READY'}",
        f"hk_d1_membership={'available_source_rows' if partial_d1 else 'exact_date_top100'}",
    )
    return StageUniverseBinding.ready(
        market="HK_CONNECT",
        trade_date=trade_date,
        role="HK_CONNECT_D1_TOP100",
        codes=tuple(sorted(codes)),
        source_run_id=f"hk-d1-{source_sha[:16]}",
        sha256=source_sha,
        evidence=binding_evidence,
    )


def __validate_hk_second_filter_body(root, trade_date):
    stem = f"hkconnect_0920_auction_second_filter_{trade_date}"
    if root.is_file():
        csv_path = root
        acceptance_path = root.with_suffix(".acceptance.json")
    else:
        candidates = (
            root,
            root / trade_date,
            root / "hkconnect_0920_auction_second_filter",
        )
        csv_path = next((item / f"{stem}.csv" for item in candidates if (item / f"{stem}.csv").is_file()), None)
        acceptance_path = next((item / f"{stem}.acceptance.json" for item in candidates if (item / f"{stem}.acceptance.json").is_file()), None)
        if csv_path is None or acceptance_path is None:
            raise RunnerError("exact-date HK 09:20 second-filter CSV/acceptance missing")
    if not csv_path.is_file() or not acceptance_path.is_file():
        raise RunnerError("exact-date HK 09:20 second-filter pair incomplete")
    try:
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError("HK second-filter acceptance unreadable") from error
    if acceptance.get("target_date") != trade_date or acceptance.get("status") != "AUCTION_SECOND_FILTER_READY":
        raise RunnerError("HK second-filter identity/status mismatch")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if int(acceptance.get("row_count", -1)) != len(rows):
        raise RunnerError("HK second-filter row_count mismatch")
    declared_sha = acceptance.get("csv_sha256")
    if not isinstance(declared_sha, str) or re.fullmatch(r"[0-9a-fA-F]{64}", declared_sha) is None:
        raise RunnerError("HK second-filter csv_sha256 must be a 64-hex digest")
    actual_sha = _sha(csv_path)
    if declared_sha.lower() != actual_sha:
        raise RunnerError("HK second-filter CSV SHA mismatch")
    if acceptance.get("production_allowed") is not False:
        raise RunnerError("HK second-filter production_allowed must be false")
    authority_v2 = acceptance.get("schema_version") == "hkconnect_0920_auction_second_filter.v2"
    # The historical v2 authority predates the envelope's explicit order and
    # buy-gate keys.  Its equivalent safety proof is shadow_only=true; the
    # stage-center envelope adds all three canonical false flags on publish.
    if not authority_v2 and acceptance.get("orders_sent") is not False:
        raise RunnerError("HK second-filter orders_sent must be false")
    gate_keys = [key for key in ("buy_gate_updated", "buy_gate_changed") if key in acceptance]
    if gate_keys:
        if any(acceptance.get(key) is not False for key in gate_keys):
            raise RunnerError("HK second-filter buy gate safety flag must be explicitly false")
    elif authority_v2:
        if acceptance.get("shadow_only") is not True:
            raise RunnerError("HK second-filter shadow_only must be true for authority v2")
    else:
        raise RunnerError("HK second-filter buy gate safety flag must be explicitly false")
    return csv_path, acceptance_path, actual_sha


def __hk_second_filter_codes_body(root, trade_date):
    csv_path, _acceptance_path, csv_sha = _validate_hk_second_filter(root, trade_date)
    codes: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            raw = str(row.get("code") or row.get("ts_code") or row.get("stock_code") or "").strip().upper()
            match = re.search(r"(?:HK\.)?(\d{5})", raw)
            if match:
                codes.add(f"HK.{match.group(1)}")
    if not codes:
        raise RunnerError("HK second-filter selection code set is empty")
    return codes, csv_sha
