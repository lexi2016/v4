"""contracts.research_day_product: supply_envelopes (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_supply_safety_body(_v4_scope, /, value, label):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(value) != _v4_global(_v4_scope, '_SUPPLY_SAFETY_FIELDS'):
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid {label} safety fields")
    expected = {
        "RESEARCH_ONLY": True,
        "WATCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    for field, required in expected.items():
        if value.get(field) is not required:
            raise _v4_global(_v4_scope, 'ValueError')(f"unsafe {label} safety boundary: {field}")


def __validate_supply_action_rows_body(_v4_scope, /, value, field, *, candidate_ids, maximum):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid supply {field}")
    if maximum is not None and _v4_global(_v4_scope, 'len')(value) > maximum:
        raise _v4_global(_v4_scope, 'ValueError')(f"supply {field} exceeds maximum size")
    selected: list[str] = []
    for row in value:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(row) != {"candidate_id", "reason"}:
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid supply {field} row")
        candidate_id = row.get("candidate_id")
        if not _v4_global(_v4_scope, 'isinstance')(candidate_id, _v4_global(_v4_scope, 'str')) or not candidate_id.strip():
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid supply {field} candidate")
        if not _v4_global(_v4_scope, 'isinstance')(row.get("reason"), _v4_global(_v4_scope, 'str')) or not row["reason"].strip():
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid supply {field} reason")
        if candidate_ids is not None and candidate_id not in candidate_ids:
            raise _v4_global(_v4_scope, 'ValueError')(f"supply {field} candidate is unknown")
        if candidate_id in selected:
            raise _v4_global(_v4_scope, 'ValueError')(f"duplicate supply {field} candidate")
        selected.append(candidate_id)
    return selected


def __validate_supply_card_body(_v4_scope, /, value):
    required = {
        "event_id",
        "ticker",
        "entity",
        "market",
        "candidate_status",
        "bucket",
        "published_at",
        "event_at",
        "source",
        "catalyst",
        "financial_bridge",
        "counterevidence",
        "invalidation",
        "evidence_level",
        "consensus",
        "overnight_pending",
        "origin_routes",
        "content_source_receipts",
        "official_source",
        "independent_evidence_dimensions",
        "sector_watch_basket",
        "eligibility_status",
        "price_confirmation_plan_0925_0935",
        "promotion_missing_fields",
    }
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or not required.issubset(value):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research supply event card fields")
    ticker = value.get("ticker")
    if not _v4_global(_v4_scope, 'isinstance')(ticker, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SUPPLY_TICKER').fullmatch(ticker):
        raise _v4_global(_v4_scope, 'ValueError')("research supply ticker must be a five-digit HK code")
    if value.get("market") != "HK":
        raise _v4_global(_v4_scope, 'ValueError')("research supply event card market must be HK")
    if not _v4_global(_v4_scope, 'isinstance')(value.get("event_id"), _v4_global(_v4_scope, 'str')) or not value["event_id"].strip():
        raise _v4_global(_v4_scope, 'ValueError')("research supply event card event_id is invalid")
    # The supply envelope is an evidence ledger, not a completed research
    # card.  Unknown facts are represented by null or by a structured typed
    # value and must remain available for later verification.  Only identity
    # and container shape are required here; downstream promotion gates do
    # the stricter evidence/PIT checks.
    flexible_fields = (
        "entity",
        "candidate_status",
        "bucket",
        "published_at",
        "event_at",
        "source",
        "catalyst",
        "financial_bridge",
        "counterevidence",
        "invalidation",
        "evidence_level",
        "consensus",
        "overnight_pending",
        "independent_evidence_dimensions",
        "sector_watch_basket",
        "eligibility_status",
        "price_confirmation_plan_0925_0935",
    )
    if _v4_global(_v4_scope, 'any')(
        not _v4_global(_v4_scope, 'isinstance')(value.get(field), (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'Mapping'), _v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'type')(None), _v4_global(_v4_scope, 'bool'), _v4_global(_v4_scope, 'int'), _v4_global(_v4_scope, 'float')))
        for field in flexible_fields
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research supply event card contains an invalid field value")
    if value.get("source") is None:
        # A missing source is still a typed, reviewable supply card; the
        # official_source identity container below records the gap.
        pass
    elif not _v4_global(_v4_scope, 'isinstance')(value.get("source"), (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'Mapping'), _v4_global(_v4_scope, 'list'))):
        raise _v4_global(_v4_scope, 'ValueError')("research supply event card source is invalid")
    routes = value.get("origin_routes")
    if not _v4_global(_v4_scope, 'isinstance')(routes, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
        not _v4_global(_v4_scope, 'isinstance')(route, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'Mapping'))) for route in routes
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research supply event card origin_routes must be a list")
    if not _v4_global(_v4_scope, 'isinstance')(value.get("content_source_receipts"), _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("research supply event card content receipts are invalid")
    official = value.get("official_source")
    if not _v4_global(_v4_scope, 'isinstance')(official, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("research supply official source is incomplete")
    identity_status = official.get("identity_status")
    if identity_status is not None and (
        not _v4_global(_v4_scope, 'isinstance')(identity_status, _v4_global(_v4_scope, 'str')) or not identity_status.strip()
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research supply official source identity status is invalid")
    for field in ("url", "publisher", "published_at", "event_at"):
        if field in official and not _v4_global(_v4_scope, 'isinstance')(
            official.get(field), (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'Mapping'), _v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'type')(None), _v4_global(_v4_scope, 'bool'), _v4_global(_v4_scope, 'int'), _v4_global(_v4_scope, 'float'))
        ):
            raise _v4_global(_v4_scope, 'ValueError')(f"research supply official source {field} is invalid")
    eligibility = value.get("eligibility_status")
    if _v4_global(_v4_scope, 'isinstance')(eligibility, _v4_global(_v4_scope, 'str')):
        if eligibility.strip() not in {
            "ELIGIBILITY_CANNOT_CONFIRM",
            "ELIGIBLE",
        }:
            raise _v4_global(_v4_scope, 'ValueError')("research supply eligibility status is invalid")
    elif _v4_global(_v4_scope, 'isinstance')(eligibility, _v4_global(_v4_scope, 'Mapping')):
        if (
            not _v4_global(_v4_scope, 'isinstance')(eligibility.get("status"), _v4_global(_v4_scope, 'str'))
            or not eligibility["status"].strip()
        ):
            raise _v4_global(_v4_scope, 'ValueError')("research supply eligibility status is invalid")
    elif eligibility is not None:
        raise _v4_global(_v4_scope, 'ValueError')("research supply eligibility status is invalid")
    if not _v4_global(_v4_scope, 'isinstance')(value.get("promotion_missing_fields"), _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
        not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) for item in value["promotion_missing_fields"]
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research supply promotion gaps are invalid")
    return ticker


def _validate_research_supply_envelope_body(_v4_scope, /, value, *, expected_source_date, expected_target_trade_date, expected_run_id):
    """Validate the new Baimao supply envelope without reading external files."""

    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, '_SUPPLY_ENVELOPE_FIELDS').issubset(value):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research supply envelope fields")
    extra = _v4_global(_v4_scope, 'set')(value) - _v4_global(_v4_scope, '_SUPPLY_ENVELOPE_FIELDS') - {"safety"}
    if extra:
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid research supply envelope fields extra={_v4_global(_v4_scope, 'sorted')(extra)}")
    if value.get("type") != _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research supply envelope type")
    if value.get("schema_version") != _v4_global(_v4_scope, 'RESEARCH_SUPPLY_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research supply envelope schema")
    if value.get("owner") != _v4_global(_v4_scope, 'RESEARCH_SUPPLY_OWNER'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research supply envelope owner")
    if value.get("phase") != _v4_global(_v4_scope, 'RESEARCH_SUPPLY_PHASE'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research supply envelope phase")
    source_date = _v4_global(_v4_scope, '_selection_date')(value.get("source_date"), "supply source_date")
    target_date = _v4_global(_v4_scope, '_selection_date')(value.get("target_trade_date"), "supply target_trade_date")
    if expected_source_date is not None and source_date != expected_source_date:
        raise _v4_global(_v4_scope, 'ValueError')("research supply source date mismatch")
    if expected_target_trade_date is not None and target_date != expected_target_trade_date:
        raise _v4_global(_v4_scope, 'ValueError')("research supply target date mismatch")
    run_id = value.get("run_id")
    if not _v4_global(_v4_scope, 'isinstance')(run_id, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SELECTION_RUN_ID').fullmatch(run_id):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research supply run_id")
    if expected_run_id is not None and run_id != expected_run_id:
        raise _v4_global(_v4_scope, 'ValueError')("research supply run_id mismatch")
    generated = _v4_global(_v4_scope, '_selection_parsed_timestamp')(value.get("generated_at"), "supply generated_at")
    coverage_started = _v4_global(_v4_scope, '_selection_parsed_timestamp')(
        value.get("coverage_started_at"), "supply coverage_started_at"
    )
    coverage_through = _v4_global(_v4_scope, '_selection_parsed_timestamp')(
        value.get("coverage_through"), "supply coverage_through"
    )
    cutoff = _v4_global(_v4_scope, '_selection_parsed_timestamp')(value.get("cutoff_at"), "supply cutoff_at")
    if coverage_started > coverage_through or coverage_through > generated:
        raise _v4_global(_v4_scope, 'ValueError')("research supply coverage interval is invalid")
    if cutoff != coverage_through:
        raise _v4_global(_v4_scope, 'ValueError')("research supply cutoff must equal coverage_through")
    frozen_payload = value.get("frozen_payload")
    if not _v4_global(_v4_scope, 'isinstance')(frozen_payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("research supply frozen_payload is missing")
    if _v4_global(_v4_scope, '_selection_canonical_sha')(frozen_payload) != _v4_global(_v4_scope, 'str')(
        value.get("frozen_payload_sha256") or ""
    ).lower():
        raise _v4_global(_v4_scope, 'ValueError')("research supply frozen_payload SHA mismatch")
    if _v4_global(_v4_scope, 'set')(frozen_payload.get("route_status", {})) != _v4_global(_v4_scope, '_SUPPLY_ROUTE_FIELDS'):
        raise _v4_global(_v4_scope, 'ValueError')("research supply route status coverage is incomplete")
    if _v4_global(_v4_scope, 'any')(
        not _v4_global(_v4_scope, 'isinstance')(status, _v4_global(_v4_scope, 'str')) or not status.strip()
        for status in frozen_payload["route_status"].values()
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research supply route status is invalid")
    if not _v4_global(_v4_scope, 'isinstance')(frozen_payload.get("source_receipts"), _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("research supply source receipts are invalid")
    cards = frozen_payload.get("event_cards")
    if not _v4_global(_v4_scope, 'isinstance')(cards, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("research supply event cards are invalid")
    card_ids = []
    for card in cards:
        ticker = _v4_global(_v4_scope, '_validate_supply_card')(card)
        if ticker in card_ids:
            raise _v4_global(_v4_scope, 'ValueError')("duplicate research supply ticker")
        card_ids.append(ticker)
    candidate_id_set = {f"HK.{ticker.split('.')[0]}|{ticker}" for ticker in card_ids}
    for field in ("core_research_candidates", "conditional_watch_candidates"):
        rows = frozen_payload.get(field)
        if not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(rows) > 5:
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid research supply {field}")
        for row in rows:
            if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'str')):
                candidate_id = row
            elif _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
                candidate_id = row.get("candidate_id")
            else:
                raise _v4_global(_v4_scope, 'ValueError')(f"invalid research supply {field} row")
            if candidate_id not in candidate_id_set:
                raise _v4_global(_v4_scope, 'ValueError')(f"research supply {field} candidate is unknown")
    core_ids = [
        row if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'str')) else row.get("candidate_id")
        for row in frozen_payload["core_research_candidates"]
    ]
    conditional_ids = [
        row if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'str')) else row.get("candidate_id")
        for row in frozen_payload["conditional_watch_candidates"]
    ]
    if _v4_global(_v4_scope, 'set')(core_ids) & _v4_global(_v4_scope, 'set')(conditional_ids):
        raise _v4_global(_v4_scope, 'ValueError')("research supply core and conditional candidates overlap")
    action_ids: set[str] = _v4_global(_v4_scope, 'set')()
    for field in ("KEEP", "ADD", "REMOVE"):
        selected = _v4_global(_v4_scope, '_validate_supply_action_rows')(
            frozen_payload.get(field), field, candidate_ids=candidate_id_set
        )
        if action_ids.intersection(selected):
            raise _v4_global(_v4_scope, 'ValueError')("research supply candidate action is duplicated")
        action_ids.update(selected)
    _v4_global(_v4_scope, '_validate_supply_safety')(frozen_payload.get("safety"), "research supply envelope")
    if "safety" in value:
        _v4_global(_v4_scope, '_validate_supply_safety')(value["safety"], "research supply envelope")
        if value["safety"] != frozen_payload["safety"]:
            raise _v4_global(_v4_scope, 'ValueError')("research supply top-level safety does not reconcile")
    return target_date


def _validate_research_supply_receipt_body(_v4_scope, /, value, *, envelope, artifact_path, artifact_sha256):
    """Validate a supply receipt and, when supplied, bind it to its envelope."""

    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, '_SUPPLY_RECEIPT_FIELDS').issubset(value):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research supply receipt fields")
    extra = _v4_global(_v4_scope, 'set')(value) - _v4_global(_v4_scope, '_SUPPLY_RECEIPT_FIELDS') - {"type"}
    if extra:
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid research supply receipt fields extra={_v4_global(_v4_scope, 'sorted')(extra)}")
    if value.get("schema_version") != _v4_global(_v4_scope, 'RESEARCH_SUPPLY_RECEIPT_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research supply receipt schema")
    if not _v4_global(_v4_scope, 'isinstance')(value.get("artifact_path"), _v4_global(_v4_scope, 'str')) or not value["artifact_path"]:
        raise _v4_global(_v4_scope, 'ValueError')("research supply receipt artifact path is missing")
    _v4_global(_v4_scope, '_selection_sha')(value.get("artifact_sha256"), "supply artifact SHA")
    _v4_global(_v4_scope, '_selection_sha')(value.get("frozen_payload_sha256"), "supply frozen SHA")
    _v4_global(_v4_scope, '_selection_date')(value.get("source_date"), "supply receipt source_date")
    _v4_global(_v4_scope, '_selection_date')(value.get("target_trade_date"), "supply receipt target_trade_date")
    _v4_global(_v4_scope, '_selection_timestamp')(value.get("generated_at"), "supply receipt generated_at")
    _v4_global(_v4_scope, '_selection_timestamp')(value.get("coverage_started_at"), "supply receipt coverage_started_at")
    _v4_global(_v4_scope, '_selection_timestamp')(value.get("coverage_through"), "supply receipt coverage_through")
    _v4_global(_v4_scope, '_selection_timestamp')(value.get("cutoff_at"), "supply receipt cutoff_at")
    if value.get("cutoff_at") != value.get("coverage_through"):
        raise _v4_global(_v4_scope, 'ValueError')("research supply receipt cutoff does not equal coverage_through")
    _v4_global(_v4_scope, '_validate_supply_safety')(value.get("safety"), "research supply receipt")
    if artifact_path is not None and value.get("artifact_path") != artifact_path:
        raise _v4_global(_v4_scope, 'ValueError')("research supply receipt artifact path mismatch")
    if artifact_sha256 is not None and value.get("artifact_sha256") != artifact_sha256:
        raise _v4_global(_v4_scope, 'ValueError')("research supply receipt artifact SHA mismatch")
    if envelope is not None:
        target = _v4_global(_v4_scope, 'validate_research_supply_envelope')(envelope)
        for field in (
            "run_id",
            "source_date",
            "target_trade_date",
            "generated_at",
            "cutoff_at",
            "coverage_started_at",
            "coverage_through",
        ):
            if value.get(field) != envelope.get(field):
                raise _v4_global(_v4_scope, 'ValueError')(f"research supply receipt {field} mismatch")
        if value.get("frozen_payload_sha256") != envelope.get("frozen_payload_sha256"):
            raise _v4_global(_v4_scope, 'ValueError')("research supply receipt frozen SHA mismatch")
        if value.get("safety") != envelope["frozen_payload"]["safety"]:
            raise _v4_global(_v4_scope, 'ValueError')("research supply receipt safety mismatch")
        return target
    return _v4_global(_v4_scope, 'str')(value["target_trade_date"])
