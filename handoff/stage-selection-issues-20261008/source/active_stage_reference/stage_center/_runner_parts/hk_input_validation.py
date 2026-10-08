"""stage_center.runner: hk_input_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __candidate_from_hk_binding_body(_v4_scope, /, *, root, trade_date, binding):
    """Build a plan-only candidate view from the verified HK universe.

    Stage Center's historical ``AcquisitionPlan`` carries one candidate field
    for compatibility.  When the A current is absent, this adapter supplies
    only the HK lane's exact D-1 Top100 binding; it is never used to make
    an A-share selection appear ready.
    """
    from stage_center.candidate_input import CandidateInput

    return CandidateInput(
        root=_v4_global(_v4_scope, 'Path')(root).expanduser().resolve(),
        trade_date=trade_date,
        current_relative=f"bindings/{trade_date}/HK_CONNECT/{binding.role}/current.json",
        current_sha256=binding.sha256,
        run_id=binding.source_run_id or f"hk-{binding.sha256[:16]}",
        codes=_v4_global(_v4_scope, 'tuple')(binding.codes),
        artifact_sha256=binding.sha256,
        manifest_sha256=binding.sha256,
        receipt_sha256=binding.sha256,
        source_projection_sha256=binding.sha256,
        source_evidence=_v4_global(_v4_scope, 'tuple')(binding.evidence),
    )


def __validate_hk_d1_body(_v4_scope, /, root, trade_date, *, preselection_source_root):
    resolved_snapshot: Mapping[str, Any] | None = None
    source_resolver = None
    if preselection_source_root is not None:
        from infrastructure.preselection_pool_store import PreselectionSourceResolver

        source_resolver = PreselectionSourceResolver(root, source_root=preselection_source_root)
        try:
            resolved_snapshot = source_resolver.read_pool_snapshot(
                trade_date, "hkconnect_d1_top100"
            )
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'RunnerError')(f"HK D1 snapshot integrity invalid: {error}") from error
        path = _v4_global(_v4_scope, 'Path')(resolved_snapshot["physical_source_root"]) / resolved_snapshot["artifact_relative"]
    else:
        path = _v4_global(_v4_scope, '_find_exact_file')(root, trade_date, "hkconnect_d1_top100.json")
    try:
        payload = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 input unreadable") from error
    if resolved_snapshot is not None:
        if resolved_snapshot.get("artifact") != payload:
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 resolved trio changed during validation")
        try:
            current_snapshot = source_resolver.read_pool_snapshot(
                trade_date, "hkconnect_d1_top100"
            )
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 resolved source identity changed during validation") from error
        for identity_key in (
            "pool_sha256", "artifact_raw_sha256", "manifest_raw_sha256",
            "receipt_raw_sha256", "physical_source_root", "artifact_relative",
            "manifest_relative", "receipt_relative",
        ):
            if current_snapshot.get(identity_key) != resolved_snapshot.get(identity_key):
                raise _v4_global(_v4_scope, 'RunnerError')("HK D1 resolved source identity changed during validation")
        schema_version = payload.get("schema_version")
        if schema_version == "v3_5.preselection_pool.v1":
            if "target_date" in payload and payload.get("target_date") != trade_date:
                raise _v4_global(_v4_scope, 'RunnerError')("HK D1 exact-source target_date mismatch")
            if "stage_selection_eligible" in payload and payload.get("stage_selection_eligible") is not True:
                raise _v4_global(_v4_scope, 'RunnerError')("HK D1 exact-source stage_selection_eligible is not true")
        elif payload.get("target_date") != trade_date or payload.get("stage_selection_eligible") is not True:
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 exact-source explicit target/eligibility mismatch")
    if payload.get("status") != "STRICT_0_2_READY":
        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 status must be STRICT_0_2_READY")
    if resolved_snapshot is not None and (
        payload.get("pool_id") != "hkconnect_d1_top100"
        or payload.get("producer_id") != "v3_shared_hk_0_2_consumer_v1"
        or payload.get("source_role") != "SHARED_VERIFIED_HK_0_2"
    ):
        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 exact-source producer/source identity mismatch")
    if _v4_global(_v4_scope, 'any')(payload.get(flag) is not False for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')):
        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 safety flags must be false")
    rows = payload.get("rows", payload.get("data"))
    if not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(rows) != 100:
        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 input must contain exactly 100 rows")
    envelope_date = payload.get("target_date", payload.get("trade_date"))
    if envelope_date is not None:
        if envelope_date != trade_date:
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 target_date mismatch")
    else:
        row_dates = _v4_global(_v4_scope, 'set')()
        for row in rows:
            if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'RunnerError')("HK D1 row must be an object")
            row_date = row.get("target_date", row.get("trade_date"))
            if row_date is None:
                raise _v4_global(_v4_scope, 'RunnerError')("HK D1 target_date missing")
            row_dates.add(_v4_global(_v4_scope, 'str')(row_date))
        if row_dates != {trade_date}:
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 target_date mismatch")
    for row in rows:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 row must be an object")
        row_date = row.get("target_date", row.get("trade_date"))
        if row_date is not None and _v4_global(_v4_scope, 'str')(row_date) != trade_date:
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 row target_date mismatch")
    # Current authority rows identify the selected model as ``prob_active``
    # (some historical fixtures omit the optional field). When present, bind
    # it explicitly so a strict-status Top100 from another model cannot pass
    # as the HK primary contract.
    model_values = []
    for key in ("model_id", "model", "model_name", "selected_strategy", "weekly_tuning_selected_strategy"):
        value = payload.get(key)
        if value not in (None, ""):
            model_values.append(_v4_global(_v4_scope, 'str')(value))
    for row in rows:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            continue
        for key in ("model_id", "model", "model_name", "selected_strategy", "weekly_tuning_selected_strategy"):
            value = row.get(key)
            if value not in (None, ""):
                model_values.append(_v4_global(_v4_scope, 'str')(value))
    if model_values and _v4_global(_v4_scope, 'any')("prob_active" not in value.lower() for value in model_values):
        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 model identity must be prob_active")
    if payload.get("schema_version") == "v3_5.preselection_pool.v1":
        from infrastructure.preselection_pool_store import PreselectionPoolStore

        # Canonical V4 inputs must use the exact-date physical trio.  The
        # older, standalone D1 JSON adapter below remains a read-only legacy
        # contract; a canonical object cannot downgrade to that adapter.
        if path.parent.name != trade_date or path.parent.parent.name != "preselection_pools":
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 canonical snapshot path invalid")
        try:
            snapshot = PreselectionPoolStore(path.parent.parent.parent).read_pool_snapshot(
                trade_date, "hkconnect_d1_top100"
            )
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'RunnerError')(f"HK D1 snapshot integrity invalid: {error}") from error
        if snapshot.get("payload") != payload:
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 snapshot changed during validation")
        open_states = {
            _v4_global(_v4_scope, 'TradingDayState').FULL_TRADING_DAY,
            _v4_global(_v4_scope, 'TradingDayState').HALF_TRADING_DAY_AM,
        }

        def previous_session(market: str) -> str:
            cursor = _v4_global(_v4_scope, 'datetime').strptime(
                trade_date, "%Y%m%d"
            )
            for _ in _v4_global(_v4_scope, 'range')(15):
                cursor -= _v4_global(_v4_scope, 'timedelta')(days=1)
                candidate = cursor.strftime("%Y%m%d")
                state = _v4_global(_v4_scope, 'resolve_market_states')(candidate)[market]
                if state is _v4_global(_v4_scope, 'TradingDayState').UNKNOWN:
                    raise _v4_global(_v4_scope, 'RunnerError')(
                        "HK D1 signal/eligibility calendar CANNOT_CONFIRM"
                    )
                if state in open_states:
                    return candidate
            raise _v4_global(_v4_scope, 'RunnerError')(
                "HK D1 signal/eligibility calendar CANNOT_CONFIRM"
            )

        price_signal_date = previous_session("hk_securities")
        eligibility_source_date = previous_session("hk_connect")
        if payload.get("market") != "HK" or payload.get("source_role") != "SHARED_VERIFIED_HK_0_2":
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 market/source role mismatch")
        if payload.get("signal_date") not in (None, price_signal_date):
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 envelope signal_date mismatch")
        if price_signal_date != eligibility_source_date:
            provenance = payload.get("historical_provenance")
            if not _v4_global(_v4_scope, 'isinstance')(provenance, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'RunnerError')(
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
                    not _v4_global(_v4_scope, 're').fullmatch(
                        r"[0-9a-f]{64}", _v4_global(_v4_scope, 'str')(provenance.get(key) or "")
                    )
                    for key in required_hashes
                )
                or provenance.get("d1_source_run_id") != payload.get("source_run_id")
                or provenance.get("d1_source_artifact_sha256") != payload.get("source_sha256")
                or provenance.get("d1_source_manifest_sha256") != payload.get("source_manifest_sha256")
                or provenance.get("d1_source_receipt_sha256") != payload.get("source_receipt_sha256")
            ):
                raise _v4_global(_v4_scope, 'RunnerError')(
                    "HK D1 split-date provenance identity mismatch"
                )
            captured_at = _v4_global(_v4_scope, 'str')(
                provenance.get("eligibility_source_captured_at") or ""
            )
            try:
                from zoneinfo import ZoneInfo

                captured = _v4_global(_v4_scope, 'datetime').fromisoformat(captured_at)
            except ValueError as error:
                raise _v4_global(_v4_scope, 'RunnerError')(
                    "HK D1 eligibility source capture time invalid"
                ) from error
            if (
                captured.tzinfo is None
                or captured.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
                != eligibility_source_date
            ):
                raise _v4_global(_v4_scope, 'RunnerError')(
                    "HK D1 eligibility source capture date mismatch"
                )
        codes = []
        for row in rows:
            if row.get("market") != "HK" or row.get("signal_date") != price_signal_date:
                raise _v4_global(_v4_scope, 'RunnerError')("HK D1 row market/signal_date mismatch")
            code = row.get("symbol", row.get("code"))
            if not _v4_global(_v4_scope, 'isinstance')(code, _v4_global(_v4_scope, 'str')) or _v4_global(_v4_scope, 're').fullmatch(r"HK\.\d{5}", code) is None:
                raise _v4_global(_v4_scope, 'RunnerError')("HK D1 row code invalid")
            if _v4_global(_v4_scope, 'any')(row.get(key) not in (None, code) for key in ("code", "symbol")):
                raise _v4_global(_v4_scope, 'RunnerError')("HK D1 row code/symbol identity mismatch")
            if _v4_global(_v4_scope, 'any')(row.get(key) not in (None, trade_date) for key in ("trade_date", "target_date")):
                raise _v4_global(_v4_scope, 'RunnerError')("HK D1 row trade/target_date mismatch")
            codes.append(code)
        if _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(codes)) != 100:
            raise _v4_global(_v4_scope, 'RunnerError')("HK D1 unique Top100 required")
    digest = _v4_global(_v4_scope, '_sha')(path)
    if resolved_snapshot is not None and (
        digest != resolved_snapshot.get("artifact_raw_sha256")
        or source_resolver.root_for_date(trade_date)
        != _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(resolved_snapshot["physical_source_root"]))
    ):
        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 resolved source identity changed during validation")
    return path, digest


def __validate_hk_full_universe_body(_v4_scope, /, root, trade_date):
    path = _v4_global(_v4_scope, '_find_exact_file')(root, trade_date, "HK_CONNECT_FULL_MARKET.json")
    try:
        payload = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'RunnerError')("HK full universe unreadable") from error
    if payload.get("trade_date") != trade_date or payload.get("market") != "HK_CONNECT" or payload.get("scope") != "FULL_MARKET":
        raise _v4_global(_v4_scope, 'RunnerError')("HK full universe identity/scope mismatch")
    if _v4_global(_v4_scope, 'any')(payload.get(flag) is not False for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')):
        raise _v4_global(_v4_scope, 'RunnerError')("HK full universe safety flag must be false")
    codes = payload.get("codes")
    if not _v4_global(_v4_scope, 'isinstance')(codes, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(codes) < 500 or _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(codes)) != _v4_global(_v4_scope, 'len')(codes) or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 're').fullmatch(r"HK\.\d{5}", _v4_global(_v4_scope, 'str')(code)) for code in codes):
        raise _v4_global(_v4_scope, 'RunnerError')("HK full universe must contain unique 500+ HK codes")
    digest = _v4_global(_v4_scope, 'hashlib').sha256(_v4_global(_v4_scope, 'json').dumps(codes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if payload.get("codes_sha256") != digest:
        raise _v4_global(_v4_scope, 'RunnerError')("HK full universe codes SHA mismatch")
    return path, _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'str')(code) for code in codes), _v4_global(_v4_scope, '_sha')(path)


def __hk_selection_codes_body(_v4_scope, /, root, trade_date, *, preselection_source_root):
    if preselection_source_root is None:
        path, path_sha = _v4_global(_v4_scope, '_validate_hk_d1')(root, trade_date)
    else:
        path, path_sha = _v4_global(_v4_scope, '_validate_hk_d1')(
            root, trade_date, preselection_source_root=preselection_source_root
        )
    payload = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", payload.get("data"))
    codes: set[str] = _v4_global(_v4_scope, 'set')()
    for row in rows:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            continue
        raw = _v4_global(_v4_scope, 'str')(row.get("code") or row.get("ts_code") or row.get("stock_code") or "").strip().upper()
        match = _v4_global(_v4_scope, 're').search(r"(?:HK\.)?(\d{5})", raw)
        if match:
            codes.add(f"HK.{match.group(1)}")
    if _v4_global(_v4_scope, 'len')(codes) != 100:
        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 selection code set must contain exactly 100 unique codes")
    return codes, path_sha


def __build_hk_d1_binding_body(_v4_scope, /, root, trade_date, *, preselection_source_root):
    """Create the exact fixed D-1 membership shared by acquisition and selection."""
    if preselection_source_root is None:
        path, source_sha = _v4_global(_v4_scope, '_validate_hk_d1')(root, trade_date)
        codes, _codes_sha = _v4_global(_v4_scope, '_hk_selection_codes')(root, trade_date)
    else:
        path, source_sha = _v4_global(_v4_scope, '_validate_hk_d1')(
            root, trade_date, preselection_source_root=preselection_source_root
        )
        codes, _codes_sha = _v4_global(_v4_scope, '_hk_selection_codes')(
            root, trade_date, preselection_source_root=preselection_source_root
        )
    if _codes_sha != source_sha:
        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 membership SHA changed during binding")
    return _v4_global(_v4_scope, 'StageUniverseBinding').ready(
        market="HK_CONNECT",
        trade_date=trade_date,
        role="HK_CONNECT_D1_TOP100",
        codes=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'sorted')(codes)),
        source_run_id=f"hk-d1-{source_sha[:16]}",
        sha256=source_sha,
        evidence=(
            f"hk_d1_json={path}",
            f"hk_d1_sha256={source_sha}",
            "hk_d1_membership=exact_date_top100",
        ),
    )


def __validate_hk_second_filter_body(_v4_scope, /, root, trade_date):
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
        csv_path = _v4_global(_v4_scope, 'next')((item / f"{stem}.csv" for item in candidates if (item / f"{stem}.csv").is_file()), None)
        acceptance_path = _v4_global(_v4_scope, 'next')((item / f"{stem}.acceptance.json" for item in candidates if (item / f"{stem}.acceptance.json").is_file()), None)
        if csv_path is None or acceptance_path is None:
            raise _v4_global(_v4_scope, 'RunnerError')("exact-date HK 09:20 second-filter CSV/acceptance missing")
    if not csv_path.is_file() or not acceptance_path.is_file():
        raise _v4_global(_v4_scope, 'RunnerError')("exact-date HK 09:20 second-filter pair incomplete")
    try:
        acceptance = _v4_global(_v4_scope, 'json').loads(acceptance_path.read_text(encoding="utf-8-sig"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter acceptance unreadable") from error
    if acceptance.get("target_date") != trade_date or acceptance.get("status") != "AUCTION_SECOND_FILTER_READY":
        raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter identity/status mismatch")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'csv').DictReader(stream))
    if _v4_global(_v4_scope, 'int')(acceptance.get("row_count", -1)) != _v4_global(_v4_scope, 'len')(rows):
        raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter row_count mismatch")
    declared_sha = acceptance.get("csv_sha256")
    if not _v4_global(_v4_scope, 'isinstance')(declared_sha, _v4_global(_v4_scope, 'str')) or _v4_global(_v4_scope, 're').fullmatch(r"[0-9a-fA-F]{64}", declared_sha) is None:
        raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter csv_sha256 must be a 64-hex digest")
    actual_sha = _v4_global(_v4_scope, '_sha')(csv_path)
    if declared_sha.lower() != actual_sha:
        raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter CSV SHA mismatch")
    if acceptance.get("production_allowed") is not False:
        raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter production_allowed must be false")
    authority_v2 = acceptance.get("schema_version") == "hkconnect_0920_auction_second_filter.v2"
    # The historical v2 authority predates the envelope's explicit order and
    # buy-gate keys.  Its equivalent safety proof is shadow_only=true; the
    # stage-center envelope adds all three canonical false flags on publish.
    if not authority_v2 and acceptance.get("orders_sent") is not False:
        raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter orders_sent must be false")
    gate_keys = [key for key in ("buy_gate_updated", "buy_gate_changed") if key in acceptance]
    if gate_keys:
        if _v4_global(_v4_scope, 'any')(acceptance.get(key) is not False for key in gate_keys):
            raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter buy gate safety flag must be explicitly false")
    elif authority_v2:
        if acceptance.get("shadow_only") is not True:
            raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter shadow_only must be true for authority v2")
    else:
        raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter buy gate safety flag must be explicitly false")
    return csv_path, acceptance_path, actual_sha


def __hk_second_filter_codes_body(_v4_scope, /, root, trade_date):
    csv_path, _acceptance_path, csv_sha = _v4_global(_v4_scope, '_validate_hk_second_filter')(root, trade_date)
    codes: set[str] = _v4_global(_v4_scope, 'set')()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in _v4_global(_v4_scope, 'csv').DictReader(stream):
            raw = _v4_global(_v4_scope, 'str')(row.get("code") or row.get("ts_code") or row.get("stock_code") or "").strip().upper()
            match = _v4_global(_v4_scope, 're').search(r"(?:HK\.)?(\d{5})", raw)
            if match:
                codes.add(f"HK.{match.group(1)}")
    if not codes:
        raise _v4_global(_v4_scope, 'RunnerError')("HK second-filter selection code set is empty")
    return codes, csv_sha
