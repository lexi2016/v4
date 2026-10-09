"""stage_center.runner: row_evidence (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _lane_status_bundle_body(_v4_scope, /, a_share, hk_connect):
    """Summarize independent A/HK universe readiness.

    This is deliberately a pure boundary helper.  It is used by the runner
    and by contract tests to ensure one lane's missing authority cannot erase
    a verified result from the other lane.
    """
    lanes = {"A_SHARE": a_share, "HK_CONNECT": hk_connect}
    output: dict[str, Any] = {}
    for market, binding in lanes.items():
        output[market] = {
            "status": binding.status,
            "trade_date": binding.trade_date,
            "role": binding.role,
            "row_count": _v4_global(_v4_scope, 'len')(binding.codes),
            "source_run_id": binding.source_run_id,
            "sha256": binding.sha256,
            "evidence": _v4_global(_v4_scope, 'list')(binding.evidence),
            **({"error": binding.error} if binding.error else {}),
        }
    if _v4_global(_v4_scope, 'all')(binding.status == "READY" for binding in lanes.values()):
        output["overall_status"] = "READY"
    elif _v4_global(_v4_scope, 'any')(binding.status == "READY" and binding.codes for binding in lanes.values()):
        output["overall_status"] = "PARTIAL_WITH_ROWS"
    else:
        output["overall_status"] = "CANNOT_CONFIRM"
    return output


def __atomic_json_body(_v4_scope, /, path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with _v4_global(_v4_scope, 'os').fdopen(fd, "w", encoding="utf-8") as stream:
            _v4_global(_v4_scope, 'json').dump(_v4_global(_v4_scope, 'dict')(payload), stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            _v4_global(_v4_scope, 'os').fsync(stream.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temporary):
            _v4_global(_v4_scope, 'os').unlink(temporary)


def __existing_binding_matches_body(_v4_scope, /, evidence, *, market, expected_sha):
    """Accept only this lane's candidate proof (or its exact HK authority).

    HK receipts written before the per-market binding fix may carry the A
    plan-carrier SHA, but their immutable D-1 JSON SHA still proves the HK
    authority.  That narrow compatibility path cannot make an A lane pass and
    still requires the current expected HK binding.
    """
    if expected_sha is None:
        return False
    if _v4_global(_v4_scope, '_evidence_has')(evidence, "candidate_current_sha256", expected_sha):
        return True
    return market == "HK_CONNECT" and _v4_global(_v4_scope, '_evidence_has')(
        evidence, "hk_d1_json_sha256", expected_sha
    )


def __latest_entry_body(_v4_scope, /, root, filename, key):
    path = root / filename
    if not path.is_file():
        return None
    try:
        payload = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'RunnerError')(f"{filename} is malformed") from error
    entries = payload.get("entries")
    if not _v4_global(_v4_scope, 'isinstance')(entries, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'RunnerError')(f"{filename} entries are malformed")
    entry = entries.get(key)
    if entry is None:
        return None
    if not _v4_global(_v4_scope, 'isinstance')(entry, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'RunnerError')(f"{filename} entry is malformed")
    return entry


def __read_verified_raw_source_body(_v4_scope, /, root, verified):
    """Rehydrate a SourceResult from one already verified immutable raw run."""
    artifact_path = root / _v4_global(_v4_scope, 'str')(verified["artifact_relative"])
    rows: list[dict[str, Any]] = []
    try:
        with artifact_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = _v4_global(_v4_scope, 'csv').DictReader(stream)
            if _v4_global(_v4_scope, 'tuple')(reader.fieldnames or ()) != ("trade_date", "bar_time", *_v4_global(_v4_scope, 'RAW_FIELDS')):
                raise _v4_global(_v4_scope, 'RunnerError')("verified raw artifact fields mismatch")
            for raw in reader:
                decoded = {field: raw.get(field, "") for field in _v4_global(_v4_scope, 'RAW_FIELDS')}
                for field in ("batch_index", "bar_count"):
                    try:
                        decoded[field] = _v4_global(_v4_scope, 'int')(decoded[field])
                    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
                        raise _v4_global(_v4_scope, 'RunnerError')(f"verified raw {field} is not an integer") from error
                for field in ("last_price", "open_price", "high_price", "low_price", "prev_close_price", "turnover", "volume", "bid_price", "ask_price", "bid_vol", "ask_vol"):
                    if decoded[field] in (None, ""):
                        decoded[field] = ""
                    else:
                        try:
                            decoded[field] = _v4_global(_v4_scope, 'float')(decoded[field])
                        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
                            raise _v4_global(_v4_scope, 'RunnerError')(f"verified raw {field} is not numeric") from error
                decoded["temporal_cutoff_safe"] = _v4_global(_v4_scope, 'str')(decoded["temporal_cutoff_safe"]).strip().lower() == "true"
                rows.append(decoded)
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'csv').Error) as error:
        raise _v4_global(_v4_scope, 'RunnerError')("verified raw artifact unreadable") from error
    return _v4_global(_v4_scope, 'SourceResult')(
        source_id=_v4_global(_v4_scope, 'str')(verified.get("source_id") or "verified_raw"),
        status=_v4_global(_v4_scope, 'str')(verified.get("status") or "CANNOT_CONFIRM"),
        rows=_v4_global(_v4_scope, 'tuple')(rows),
        cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'str')(item) for item in verified.get("cannot_confirm", ())),
        requested_rows=_v4_global(_v4_scope, 'int')(verified.get("requested_rows", _v4_global(_v4_scope, 'len')(rows))),
        missing_symbols=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'str')(item) for item in verified.get("missing_symbols", ())),
        source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'str')(item) for item in verified.get("source_evidence", ())),
    )


def __with_candidate_evidence_body(_v4_scope, /, result, candidate, extra, *, candidate_sha, candidate_run_id):
    """Bind a source to the candidate authority for its own market lane.

    ``CandidateInput`` is retained as the historical plan carrier, but A and
    HK have separate authorities.  A caller that has no verified binding for a
    lane must leave its candidate evidence absent instead of borrowing the
    other market's synthetic SHA.
    """
    evidence = _v4_global(_v4_scope, 'list')(result.source_evidence)
    if candidate_sha is not None:
        evidence.extend(
            (
                f"candidate_current_sha256={candidate_sha}",
                f"candidate_run_id={candidate_run_id if candidate_run_id is not None else candidate.run_id}",
            )
        )
    evidence.extend(extra)
    evidence = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(evidence))
    return _v4_global(_v4_scope, 'replace')(result, source_evidence=evidence)


def __project_raw_rows_body(
    _v4_scope, /, rows, *, trade_date, stage_id, market,
    research_observation_contract=None,
):
    """Project collector rows to the immutable SafeRootStore 19-field shape.

    Collector rows are intentionally richer than raw storage: auction rank,
    D-1 lanes, and second-filter fields belong to the selection-only copy.  We
    retain the original ``SourceResult`` for selection, but raw publication
    receives only the frozen fields.  Missing/invalid required fields are
    rejected before ``RawStore.publish`` so a malformed row cannot advance a
    CANNOT_CONFIRM latest pointer or leave an incomplete bundle behind.
    """
    projected = _v4_global(_v4_scope, 'tuple')(
        {field: row[field] for field in _v4_global(_v4_scope, 'RAW_FIELDS')}
        if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')) and _v4_global(_v4_scope, 'all')(field in row for field in _v4_global(_v4_scope, 'RAW_FIELDS'))
        else _v4_global(_v4_scope, 'dict')(row)
        for row in rows
    )
    if research_observation_contract is not None:
        legacy_contract = research_observation_contract == _v4_global(
            _v4_scope, 'HK_0930_TDX_RESEARCH_CONTRACT'
        )
        manifest_contract = (
            isinstance(research_observation_contract, str)
            and research_observation_contract.startswith(
                _v4_global(_v4_scope, 'HISTORICAL_OBSERVATION_CONTRACT_PREFIX')
            )
            and _v4_global(_v4_scope, 're').fullmatch(
                _v4_global(_v4_scope, 're').escape(
                    _v4_global(_v4_scope, 'HISTORICAL_OBSERVATION_CONTRACT_PREFIX')
                ) + r"[0-9a-f]{64}",
                research_observation_contract,
            ) is not None
        )
        if not (legacy_contract or manifest_contract):
            raise _v4_global(_v4_scope, 'RunnerError')(
                "unknown temporal-false research projection contract"
            )
    _validated, issues = _v4_global(_v4_scope, 'validate_rows')(
        projected,
        trade_date=trade_date,
        stage_id=stage_id,
        market=market,
        allow_temporal_false_observation=(research_observation_contract is not None),
    )
    if issues:
        raise _v4_global(_v4_scope, 'RunnerError')(f"raw projection validation failed for {market}: {'; '.join(issues[:3])}")
    return projected
