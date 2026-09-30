"""infrastructure.research_store: manager_baseline (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchSelectionStore__verify_manager_baseline_body(_v4_scope, /, cls, baseline_ref, *, source_date, target_trade_date, decision_generated_at, _seen_paths):
    """Verify a real prior manager snapshot used by KEEP/ADD/REMOVE."""

    if not _v4_global(_v4_scope, 'isinstance')(baseline_ref, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline reference is missing")
    path_value = baseline_ref.get("path")
    if not _v4_global(_v4_scope, 'isinstance')(path_value, _v4_global(_v4_scope, 'str')) or not path_value:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline path is missing")
    path = _v4_global(_v4_scope, 'Path')(path_value)
    if not path.is_file() or path.is_symlink():
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline SHA mismatch")
    path_key = _v4_global(_v4_scope, 'str')(path)
    seen_paths = _v4_global(_v4_scope, 'set')(_seen_paths or _v4_global(_v4_scope, 'set')())
    if path_key in seen_paths:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline reference cycle")
    seen_paths.add(path_key)
    baseline_raw = path.read_bytes()
    if _v4_global(_v4_scope, 'hashlib').sha256(baseline_raw).hexdigest() != _v4_global(_v4_scope, 'str')(
        baseline_ref.get("raw_sha256") or ""
    ).lower():
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline SHA mismatch")
    try:
        baseline = _v4_global(_v4_scope, 'json').loads(baseline_raw.decode("utf-8"))
    except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline is invalid JSON") from error
    if not _v4_global(_v4_scope, 'isinstance')(baseline, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline is not an object")
    if baseline.get("source_date") != source_date:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline source date mismatch")
    if baseline.get("target_trade_date") != target_trade_date:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline target date mismatch")
    baseline_time = baseline.get("generated_at") or baseline.get("event_at")
    if not _v4_global(_v4_scope, 'isinstance')(baseline_time, _v4_global(_v4_scope, 'str')) or not baseline_time:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline timestamp is missing")
    try:
        prior = _v4_global(_v4_scope, 'datetime').fromisoformat(baseline_time.replace("Z", "+00:00"))
        current = _v4_global(_v4_scope, 'datetime').fromisoformat(decision_generated_at.replace("Z", "+00:00"))
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline timestamp is invalid") from error
    if (
        prior.tzinfo is None
        or prior.utcoffset() is None
        or current.tzinfo is None
        or current.utcoffset() is None
        or prior.astimezone(_v4_global(_v4_scope, '_SHANGHAI')) >= current.astimezone(_v4_global(_v4_scope, '_SHANGHAI'))
    ):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline is not earlier than decision")

    schema_version = baseline.get("schema_version")
    if schema_version == _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSION'):
        try:
            _v4_global(_v4_scope, 'validate_selection_research_product')(baseline)
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline selection product is invalid") from error
        try:
            cls._verify_product_sources(baseline, _seen_paths=seen_paths)
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline selection source is invalid") from error
        manager_proof = baseline.get("manager_decision_ref")
        formal_authority = baseline.get("formal_authority")
        if _v4_global(_v4_scope, 'isinstance')(manager_proof, _v4_global(_v4_scope, 'Mapping')):
            proof_ids = cls._verify_manager_baseline(
                manager_proof,
                source_date=source_date,
                target_trade_date=target_trade_date,
                decision_generated_at=decision_generated_at,
                _seen_paths=seen_paths,
            )
        elif (
            _v4_global(_v4_scope, 'isinstance')(formal_authority, _v4_global(_v4_scope, 'Mapping'))
            and formal_authority.get("status") == "READY"
            and baseline.get("formal_shortlist")
            and _v4_global(_v4_scope, 'isinstance')(formal_authority.get("manager_decision_ref"), _v4_global(_v4_scope, 'Mapping'))
        ):
            # _verify_product_sources above has already verified the
            # structured formal manager proof and its candidate bindings.
            proof_ids = _v4_global(_v4_scope, 'set')(baseline["formal_shortlist"])
        else:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline lacks a real manager proof")
        snapshots = baseline.get("snapshots")
        if not _v4_global(_v4_scope, 'isinstance')(snapshots, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline snapshots are missing")
        ready_phases = [
            phase
            for phase in ("2200", "0830", "0935", "1620")
            if _v4_global(_v4_scope, 'isinstance')(snapshots.get(phase), _v4_global(_v4_scope, 'Mapping'))
            and snapshots[phase].get("status") == "READY"
        ]
        if not ready_phases:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline has no READY snapshot")
        snapshot = snapshots[ready_phases[-1]]
        candidate_ids = snapshot.get("candidate_ids")
        if not _v4_global(_v4_scope, 'isinstance')(candidate_ids, _v4_global(_v4_scope, 'list')):
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline candidate set is invalid")
        if _v4_global(_v4_scope, 'len')(candidate_ids) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(candidate_ids)):
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline candidate set is invalid")
        if _v4_global(_v4_scope, 'isinstance')(manager_proof, _v4_global(_v4_scope, 'Mapping')) and _v4_global(_v4_scope, 'set')(candidate_ids) != proof_ids:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline manager proof set mismatch")
        return _v4_global(_v4_scope, 'set')(candidate_ids)

    if schema_version != _v4_global(_v4_scope, 'MANAGER_DECISION_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline schema is not an accepted product")
    baseline_supply_ref = baseline.get("supply_ref")
    if not _v4_global(_v4_scope, 'isinstance')(baseline_supply_ref, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply reference is missing")
    baseline_supply_path_value = baseline_supply_ref.get("path")
    if not _v4_global(_v4_scope, 'isinstance')(baseline_supply_path_value, _v4_global(_v4_scope, 'str')) or not baseline_supply_path_value:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply path is missing")
    baseline_supply_path = _v4_global(_v4_scope, 'Path')(baseline_supply_path_value)
    if not baseline_supply_path.is_file() or baseline_supply_path.is_symlink():
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply is unavailable")
    baseline_supply_raw = baseline_supply_path.read_bytes()
    baseline_supply_sha = _v4_global(_v4_scope, 'hashlib').sha256(baseline_supply_raw).hexdigest()
    if baseline_supply_sha != _v4_global(_v4_scope, 'str')(baseline_supply_ref.get("raw_sha256") or "").lower():
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply SHA mismatch")
    try:
        baseline_supply_document = _v4_global(_v4_scope, 'json').loads(baseline_supply_raw.decode("utf-8"))
    except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply is invalid JSON") from error
    if not _v4_global(_v4_scope, 'isinstance')(baseline_supply_document, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply is not an object")
    baseline_run_id = baseline.get("run_id")
    _v4_global(_v4_scope, 'validate_research_supply_envelope')(
        baseline_supply_document,
        expected_source_date=source_date,
        expected_target_trade_date=target_trade_date,
        expected_run_id=baseline_run_id,
    )
    if baseline_supply_ref.get("run_id") != baseline_run_id:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply run binding mismatch")
    if baseline_supply_ref.get("frozen_payload_sha256") != baseline_supply_document.get(
        "frozen_payload_sha256"
    ):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply frozen SHA mismatch")
    baseline_cards = baseline_supply_document["frozen_payload"].get("event_cards")
    if not _v4_global(_v4_scope, 'isinstance')(baseline_cards, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply cards are invalid")
    baseline_candidate_ids: list[str] = []
    for card in baseline_cards:
        ticker = _v4_global(_v4_scope, 'str')(card.get("ticker") or "") if _v4_global(_v4_scope, 'isinstance')(card, _v4_global(_v4_scope, 'Mapping')) else ""
        if not _v4_global(_v4_scope, 're').fullmatch(r"\d{5}\.HK", ticker):
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply card is invalid")
        candidate_id = f"HK.{ticker.split('.')[0]}|{ticker}"
        if candidate_id in baseline_candidate_ids:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply candidate is duplicated")
        baseline_candidate_ids.append(candidate_id)
    decision_ids = [
        row.get("candidate_id")
        for row in [*(baseline.get("core") or []), *(baseline.get("conditional") or [])]
        if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
    ]
    if _v4_global(_v4_scope, 'len')(decision_ids) != _v4_global(_v4_scope, 'len')(
        [row for row in [*(baseline.get("core") or []), *(baseline.get("conditional") or [])] if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))]
    ):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline candidate set is invalid")
    if _v4_global(_v4_scope, 'len')(decision_ids) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(decision_ids)):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline candidate set is invalid")
    _v4_global(_v4_scope, 'validate_manager_research_decision')(
        baseline,
        candidate_ids=baseline_candidate_ids,
        supply_envelope=baseline_supply_document,
    )
    if _v4_global(_v4_scope, 'set')(decision_ids) - _v4_global(_v4_scope, 'set')(baseline_candidate_ids):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline supply candidate binding mismatch")
    predecessor_ids: set[str] | None = None
    if baseline.get("baseline_ref") is not None:
        predecessor_ids = cls._verify_manager_baseline(
            baseline["baseline_ref"],
            source_date=source_date,
            target_trade_date=target_trade_date,
            decision_generated_at=_v4_global(_v4_scope, 'str')(baseline["generated_at"]),
            _seen_paths=seen_paths,
        )
    keep_ids = {row["candidate_id"] for row in baseline["KEEP"]}
    add_ids = {row["candidate_id"] for row in baseline["ADD"]}
    remove_ids = {row["candidate_id"] for row in baseline["REMOVE"]}
    if predecessor_ids is None:
        expected_ids = add_ids
    else:
        if not keep_ids.issubset(predecessor_ids) or remove_ids - predecessor_ids:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline action set mismatch")
        if add_ids & predecessor_ids:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline action set mismatch")
        expected_ids = (predecessor_ids - remove_ids) | add_ids
    if _v4_global(_v4_scope, 'set')(decision_ids) != expected_ids:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline action set mismatch")
    return _v4_global(_v4_scope, 'set')(decision_ids)


def _ResearchSelectionStore__verify_manager_qualification_refs_body(_v4_scope, /, cls, decision, *, source_date, target_trade_date, candidate_ids):
    """Check bytes for optional qualifications without promoting them."""

    for ref in decision.get("qualification_refs", []):
        if not _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification reference is invalid")
        path_value = ref.get("path")
        raw_sha = ref.get("raw_sha256")
        if path_value is None and raw_sha is None:
            continue
        if not _v4_global(_v4_scope, 'isinstance')(path_value, _v4_global(_v4_scope, 'str')) or not path_value:
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification path is missing")
        path = _v4_global(_v4_scope, 'Path')(path_value)
        if not path.is_file() or path.is_symlink():
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification SHA mismatch")
        raw = path.read_bytes()
        if _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest() != _v4_global(_v4_scope, 'str')(raw_sha or "").lower():
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification SHA mismatch")
        try:
            document = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8"))
        except (_v4_global(_v4_scope, 'UnicodeDecodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification document is invalid JSON") from error
        if not _v4_global(_v4_scope, 'isinstance')(document, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification document is not an object")
        if document.get("schema_version") != "v3_5.selection_formal_evidence.v1" or document.get("type") != "EXACT_DATE_PIT":
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification document schema is invalid")
        if (
            document.get("source_date") != source_date
            or document.get("target_trade_date") != target_trade_date
        ):
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification document date binding mismatch")
        documented_ids = document.get("candidate_ids")
        candidate_id = ref.get("candidate_id")
        if candidate_id not in candidate_ids:
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification candidate is unknown")
        if not _v4_global(_v4_scope, 'isinstance')(documented_ids, _v4_global(_v4_scope, 'list')) or candidate_id not in documented_ids:
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification document candidate binding mismatch")
        if document.get("status") not in {"READY", "ELIGIBLE"}:
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification document status is invalid")
        if "pit_status" in document and document.get("pit_status") != "READY":
            raise _v4_global(_v4_scope, 'ValueError')("manager qualification document PIT status is invalid")
        bindings = document.get("candidate_bindings")
        if bindings is not None:
            if not _v4_global(_v4_scope, 'isinstance')(bindings, _v4_global(_v4_scope, 'list')):
                raise _v4_global(_v4_scope, 'ValueError')("manager qualification document bindings are invalid")
            matching = [
                binding
                for binding in bindings
                if _v4_global(_v4_scope, 'isinstance')(binding, _v4_global(_v4_scope, 'Mapping'))
                and binding.get("candidate_id") == candidate_id
            ]
            if not matching or _v4_global(_v4_scope, 'any')(
                binding.get("eligibility") != "ELIGIBLE"
                or binding.get("pit_status") != "READY"
                or not _v4_global(_v4_scope, 'isinstance')(binding.get("source_refs"), _v4_global(_v4_scope, 'list'))
                or not binding["source_refs"]
                for binding in matching
            ):
                raise _v4_global(_v4_scope, 'ValueError')("manager qualification document proof is incomplete")
