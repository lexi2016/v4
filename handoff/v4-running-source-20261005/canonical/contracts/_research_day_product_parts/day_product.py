"""contracts.research_day_product: day_product (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_slot_matrix_body(_v4_scope, /, value):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(value) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')):
        raise _v4_global(_v4_scope, 'ValueError')("research day slot matrix must cover all expected slots")
    seen: set[str] = _v4_global(_v4_scope, 'set')()
    for row in value:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day slot matrix row")
        if _v4_global(_v4_scope, 'set')(row) != {
            "slot",
            "status",
            "raw_rows",
            "exact_rows",
            "excluded_rows",
            "artifact_path",
            "artifact_sha256",
            "receipt_path",
            "receipt_sha256",
            "source_input_sha256",
        }:
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day slot matrix fields")
        slot = row.get("slot")
        if slot not in _v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS') or slot in seen:
            raise _v4_global(_v4_scope, 'ValueError')("research day slot matrix identity mismatch")
        seen.add(_v4_global(_v4_scope, 'str')(slot))
        if row.get("status") != "READY":
            raise _v4_global(_v4_scope, 'ValueError')("research day slot matrix has non-ready slot")
        for field in ("raw_rows", "exact_rows", "excluded_rows"):
            if _v4_global(_v4_scope, 'type')(row.get(field)) is not _v4_global(_v4_scope, 'int') or row[field] < 0:
                raise _v4_global(_v4_scope, 'ValueError')(f"invalid research day slot {field}")
        for field in (
            "artifact_sha256",
            "receipt_sha256",
            "source_input_sha256",
        ):
            _v4_global(_v4_scope, '_sha')(row.get(field), field)
        if not _v4_global(_v4_scope, 'isinstance')(row.get("artifact_path"), _v4_global(_v4_scope, 'str')) or not row["artifact_path"]:
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day artifact path")
        if not _v4_global(_v4_scope, 'isinstance')(row.get("receipt_path"), _v4_global(_v4_scope, 'str')) or not row["receipt_path"]:
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day receipt path")
    if _v4_global(_v4_scope, 'tuple')(row["slot"] for row in value) != _v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS'):
        raise _v4_global(_v4_scope, 'ValueError')("research day slot matrix must be chronological")
    return value


def __validate_not_materialized_product_body(_v4_scope, /, payload):
    """Validate a typed base-envelope gap without accepting stale rows."""

    expected = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS'))
    coverage = payload.get("coverage")
    if not _v4_global(_v4_scope, 'isinstance')(coverage, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(coverage) != {
        "expected_slots",
        "ready_slots",
        "missing_slots",
        "complete",
        "slot_matrix",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day NOT_MATERIALIZED coverage")
    if (
        coverage.get("expected_slots") != _v4_global(_v4_scope, 'len')(expected)
        or coverage.get("ready_slots") != 0
        or coverage.get("missing_slots") != expected
        or coverage.get("complete") is not False
        or coverage.get("slot_matrix") != []
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research day NOT_MATERIALIZED coverage must list all missing slots")
    counts = payload.get("counts")
    if not _v4_global(_v4_scope, 'isinstance')(counts, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(counts) != {
        "raw_rows",
        "evidence_rows",
        "excluded_rows",
        "mention_pairs",
        "urls",
        "stock_rollups",
        "high_priority",
        "duplicate_pairs",
    } or _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value != 0 for value in counts.values()):
        raise _v4_global(_v4_scope, 'ValueError')("research day NOT_MATERIALIZED counts must be zero")
    exclusions = payload.get("exclusions")
    if not _v4_global(_v4_scope, 'isinstance')(exclusions, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(exclusions) != {
        "date_mismatch",
        "pit_violation",
        "invalid_row",
    } or _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value != 0 for value in exclusions.values()):
        raise _v4_global(_v4_scope, 'ValueError')("research day NOT_MATERIALIZED exclusions must be zero")
    if payload.get("excluded_by_date") != {}:
        raise _v4_global(_v4_scope, 'ValueError')("research day NOT_MATERIALIZED excluded_by_date must be empty")
    for field in ("evidence_rows", "mention_pairs", "stock_rollups", "high_priority"):
        if payload.get(field) != []:
            raise _v4_global(_v4_scope, 'ValueError')(f"research day NOT_MATERIALIZED {field} must be empty")
    if payload.get("slot_matrix") != [] or payload.get("lineage") is not None:
        raise _v4_global(_v4_scope, 'ValueError')("research day NOT_MATERIALIZED cannot carry product rows or lineage")
    high_status = payload.get("high_priority_status")
    if not _v4_global(_v4_scope, 'isinstance')(high_status, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(high_status) != {
        "status",
        "rule_id",
        "registry",
        "cannot_confirm",
    } or high_status.get("status") != "CANNOT_CONFIRM" or high_status.get("registry") != "MISSING":
        raise _v4_global(_v4_scope, 'ValueError')("research day NOT_MATERIALIZED high priority must be CANNOT_CONFIRM")
    cannot_confirm = payload.get("cannot_confirm")
    if not _v4_global(_v4_scope, 'isinstance')(cannot_confirm, _v4_global(_v4_scope, 'list')) or not cannot_confirm:
        raise _v4_global(_v4_scope, 'ValueError')("research day NOT_MATERIALIZED requires a typed gap")
    _v4_global(_v4_scope, '_sorted_strings')(cannot_confirm, "cannot_confirm")

    excluded_by_date = payload.get("excluded_by_date")
    if not _v4_global(_v4_scope, 'isinstance')(excluded_by_date, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day excluded_by_date")
    excluded_dates = _v4_global(_v4_scope, 'list')(excluded_by_date)
    if excluded_dates != _v4_global(_v4_scope, 'sorted')(excluded_dates):
        raise _v4_global(_v4_scope, 'ValueError')("research day excluded_by_date must be chronological")
    for date, count in excluded_by_date.items():
        _v4_global(_v4_scope, '_date')(date)
        if _v4_global(_v4_scope, 'type')(count) is not _v4_global(_v4_scope, 'int') or count <= 0:
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day excluded_by_date count")

    jyg_coverage = payload.get("jyg_coverage")
    if not _v4_global(_v4_scope, 'isinstance')(jyg_coverage, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(jyg_coverage) != {
        "status",
        "articles",
        "expected_articles",
        "stock_mentions",
        "registry",
        "gap",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day jyg coverage")
    if jyg_coverage.get("status") not in {"VALIDATED", "CANNOT_CONFIRM"}:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day jyg coverage status")
    if jyg_coverage.get("registry") not in {"VALIDATED", "MISSING"}:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day jyg coverage registry")
    for field in ("articles", "expected_articles", "stock_mentions"):
        value = jyg_coverage.get(field)
        if value is not None and (_v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value < 0):
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid research day jyg coverage {field}")
    if jyg_coverage.get("status") == "CANNOT_CONFIRM":
        if jyg_coverage.get("registry") != "MISSING" or not jyg_coverage.get("gap"):
            raise _v4_global(_v4_scope, 'ValueError')("research day jyg coverage gap is incomplete")
    elif jyg_coverage.get("registry") != "VALIDATED" or jyg_coverage.get("gap") is not None:
        raise _v4_global(_v4_scope, 'ValueError')("research day jyg coverage validation mismatch")


def _validate_research_day_product_body(_v4_scope, /, payload):
    """Validate the complete exact-date day-product envelope."""

    archive_date, status = _validate_day_product_header_phase(_v4_scope, payload)
    if status == "NOT_MATERIALIZED":
        _v4_global(_v4_scope, '_validate_not_materialized_product')(payload)
        return archive_date
    slot_matrix, counts = _validate_day_product_slots_phase(_v4_scope, payload)
    _validate_day_product_exclusions_phase(_v4_scope, payload, counts)
    _validate_day_product_evidence_phase(_v4_scope, payload, archive_date, status)
    _validate_day_product_pairs_phase(_v4_scope, payload, counts)
    _validate_day_product_rollups_phase(_v4_scope, payload)
    _validate_day_product_lineage_phase(_v4_scope, payload, archive_date, slot_matrix)
    return archive_date


def _validate_day_product_header_phase(_v4_scope, /, payload):
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day product fields")
    if _v4_global(_v4_scope, 'set')(payload) != _v4_global(_v4_scope, '_PRODUCT_FIELDS'):
        missing = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, '_PRODUCT_FIELDS') - _v4_global(_v4_scope, 'set')(payload))
        extra = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(payload) - _v4_global(_v4_scope, '_PRODUCT_FIELDS'))
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if extra:
            detail.append(f"extra={extra}")
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid research day product fields {' '.join(detail)}")
    archive_date = _v4_global(_v4_scope, '_date')(payload.get("archive_date"))
    if payload.get("schema_version") != _v4_global(_v4_scope, 'PRODUCT_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day product schema")
    if payload.get("contract_id") != _v4_global(_v4_scope, 'CONTRACT_ID'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day product contract")
    if payload.get("workflow_name") != _v4_global(_v4_scope, 'WORKFLOW_NAME'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day product workflow")
    if payload.get("pass_signal") != _v4_global(_v4_scope, 'PASS_SIGNAL'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day product pass signal")
    if payload.get("timezone") != _v4_global(_v4_scope, 'TIMEZONE') or payload.get("date_mode") != _v4_global(_v4_scope, 'DATE_MODE'):
        raise _v4_global(_v4_scope, 'ValueError')("research day product must be exact-date Asia/Shanghai")
    if payload.get("write_policy") != "read_only":
        raise _v4_global(_v4_scope, 'ValueError')("unsafe research day write policy")
    if payload.get("recommendation_status") != "RESEARCH_ONLY":
        raise _v4_global(_v4_scope, 'ValueError')("unsafe research day recommendation status")
    for key, expected in _v4_global(_v4_scope, 'SAFETY_FLAGS').items():
        if payload.get(key) is not expected:
            raise _v4_global(_v4_scope, 'ValueError')(f"unsafe research day safety boundary: {key}")
    expected_slots = payload.get("expected_slots")
    if _v4_global(_v4_scope, 'tuple')(expected_slots or ()) != _v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS'):
        raise _v4_global(_v4_scope, 'ValueError')("research day expected slots mismatch")
    status = payload.get("status")
    if status not in {"READY", "READY_WITH_DECLARED_GAPS", "NOT_MATERIALIZED"}:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day status")
    if _v4_global(_v4_scope, 'type')(payload.get("authoritative")) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day authoritative flag")
    return archive_date, status


def _validate_day_product_slots_phase(_v4_scope, /, payload):
    slot_matrix = _v4_global(_v4_scope, '_validate_slot_matrix')(payload.get("slot_matrix"))
    coverage = payload.get("coverage")
    if not _v4_global(_v4_scope, 'isinstance')(coverage, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(coverage) != {
        "expected_slots",
        "ready_slots",
        "missing_slots",
        "complete",
        "slot_matrix",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day coverage")
    if coverage["expected_slots"] != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')):
        raise _v4_global(_v4_scope, 'ValueError')("research day expected slot count mismatch")
    if coverage["ready_slots"] != _v4_global(_v4_scope, 'len')(slot_matrix):
        raise _v4_global(_v4_scope, 'ValueError')("research day ready slot count mismatch")
    if coverage["missing_slots"] != [] or coverage["complete"] is not True:
        raise _v4_global(_v4_scope, 'ValueError')("research day product requires a complete slot matrix")
    if coverage["slot_matrix"] != slot_matrix:
        raise _v4_global(_v4_scope, 'ValueError')("research day coverage slot matrix mismatch")

    counts = payload.get("counts")
    if not _v4_global(_v4_scope, 'isinstance')(counts, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(counts) != {
        "raw_rows",
        "evidence_rows",
        "excluded_rows",
        "mention_pairs",
        "urls",
        "stock_rollups",
        "high_priority",
        "duplicate_pairs",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day counts")
    for field in counts:
        if _v4_global(_v4_scope, 'type')(counts[field]) is not _v4_global(_v4_scope, 'int') or counts[field] < 0:
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid research day count: {field}")
    if counts["raw_rows"] != _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(row["raw_rows"]) for row in slot_matrix):
        raise _v4_global(_v4_scope, 'ValueError')("research day raw row count mismatch")
    if counts["evidence_rows"] != _v4_global(_v4_scope, 'len')(payload["evidence_rows"]):
        raise _v4_global(_v4_scope, 'ValueError')("research day evidence row count mismatch")
    if counts["excluded_rows"] != _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(row["excluded_rows"]) for row in slot_matrix):
        raise _v4_global(_v4_scope, 'ValueError')("research day excluded row count mismatch")
    if counts["mention_pairs"] != _v4_global(_v4_scope, 'len')(payload["mention_pairs"]):
        raise _v4_global(_v4_scope, 'ValueError')("research day mention pair count mismatch")
    if counts["stock_rollups"] != _v4_global(_v4_scope, 'len')(payload["stock_rollups"]):
        raise _v4_global(_v4_scope, 'ValueError')("research day stock rollup count mismatch")
    if counts["high_priority"] != _v4_global(_v4_scope, 'len')(payload["high_priority"]):
        raise _v4_global(_v4_scope, 'ValueError')("research day high priority count mismatch")
    return slot_matrix, counts


def _validate_day_product_exclusions_phase(_v4_scope, /, payload, counts):
    exclusions = payload.get("exclusions")
    if not _v4_global(_v4_scope, 'isinstance')(exclusions, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(exclusions) != {
        "date_mismatch",
        "pit_violation",
        "invalid_row",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day exclusions")
    if _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value < 0 for value in exclusions.values()):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day exclusion count")
    if _v4_global(_v4_scope, 'sum')(exclusions.values()) != counts["excluded_rows"]:
        raise _v4_global(_v4_scope, 'ValueError')("research day exclusion count mismatch")

    excluded_by_date = payload.get("excluded_by_date")
    if not _v4_global(_v4_scope, 'isinstance')(excluded_by_date, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day excluded_by_date")
    excluded_dates = _v4_global(_v4_scope, 'list')(excluded_by_date)
    if excluded_dates != _v4_global(_v4_scope, 'sorted')(excluded_dates):
        raise _v4_global(_v4_scope, 'ValueError')("research day excluded_by_date must be chronological")
    for date, count in excluded_by_date.items():
        _v4_global(_v4_scope, '_date')(date)
        if _v4_global(_v4_scope, 'type')(count) is not _v4_global(_v4_scope, 'int') or count <= 0:
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day excluded_by_date count")
    if exclusions["date_mismatch"] != _v4_global(_v4_scope, 'sum')(excluded_by_date.values()):
        raise _v4_global(_v4_scope, 'ValueError')("research day excluded_by_date mismatch")


def _validate_day_product_evidence_phase(_v4_scope, /, payload, archive_date, status):
    evidence_rows = payload.get("evidence_rows")
    if not _v4_global(_v4_scope, 'isinstance')(evidence_rows, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day evidence rows")
    identity_gap = False
    for row in evidence_rows:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day evidence row")
        if row.get("archive_date") != archive_date:
            raise _v4_global(_v4_scope, 'ValueError')("research day evidence date mismatch")
        if row.get("slot") not in _v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS'):
            raise _v4_global(_v4_scope, 'ValueError')("research day evidence slot mismatch")
        if not _v4_global(_v4_scope, 'isinstance')(row.get("source_row_ref"), _v4_global(_v4_scope, 'str')) or not row["source_row_ref"]:
            raise _v4_global(_v4_scope, 'ValueError')("research day evidence source ref missing")
        if _v4_global(_v4_scope, '_pair_identity')(row) is None:
            identity_gap = True
            if row.get("identity_status") != "URL_REQUIRED/CANNOT_CONFIRM":
                raise _v4_global(_v4_scope, 'ValueError')("research day evidence identity is unverified")
        elif row.get("identity_status") != "READY":
            raise _v4_global(_v4_scope, 'ValueError')("research day evidence identity status mismatch")
    if identity_gap:
        if status != "READY_WITH_DECLARED_GAPS" or payload.get("authoritative") is not False:
            raise _v4_global(_v4_scope, 'ValueError')("research day product cannot authorize an unverified identity")
        if "URL_REQUIRED/CANNOT_CONFIRM" not in payload.get("cannot_confirm", []):
            raise _v4_global(_v4_scope, 'ValueError')("research day product identity gap is undeclared")


def _validate_day_product_pairs_phase(_v4_scope, /, payload, counts):
    mention_pairs = payload.get("mention_pairs")
    if not _v4_global(_v4_scope, 'isinstance')(mention_pairs, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day mention pairs")
    pair_keys: set[str] = _v4_global(_v4_scope, 'set')()
    for row in mention_pairs:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day mention pair")
        pair_key = row.get("pair_key")
        if not _v4_global(_v4_scope, 'isinstance')(pair_key, _v4_global(_v4_scope, 'str')) or not pair_key or pair_key in pair_keys:
            raise _v4_global(_v4_scope, 'ValueError')("research day mention pair identity mismatch")
        pair_keys.add(pair_key)
        if _v4_global(_v4_scope, 'type')(row.get("occurrence_count")) is not _v4_global(_v4_scope, 'int') or row["occurrence_count"] < 1:
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day occurrence count")
        if _v4_global(_v4_scope, 'type')(row.get("variant_count")) is not _v4_global(_v4_scope, 'int') or row["variant_count"] < 1:
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day variant count")
        for field in ("source_slots", "article_ids", "dedupe_keys", "source_refs"):
            if not _v4_global(_v4_scope, 'isinstance')(row.get(field), _v4_global(_v4_scope, 'list')):
                raise _v4_global(_v4_scope, 'ValueError')(f"invalid research day pair {field}")
    if counts["duplicate_pairs"] != _v4_global(_v4_scope, 'sum')(
        1 for row in mention_pairs if row["occurrence_count"] > 1
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research day duplicate pair count mismatch")


def _validate_day_product_rollups_phase(_v4_scope, /, payload):
    stock_rollups = payload.get("stock_rollups")
    if not _v4_global(_v4_scope, 'isinstance')(stock_rollups, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day stock rollups")
    stock_codes: set[str] = _v4_global(_v4_scope, 'set')()
    for row in stock_rollups:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research day stock rollup")
        code = row.get("stock_code")
        if not _v4_global(_v4_scope, 'isinstance')(code, _v4_global(_v4_scope, 'str')) or not code or code in stock_codes:
            raise _v4_global(_v4_scope, 'ValueError')("research day stock rollup identity mismatch")
        stock_codes.add(code)

    high_priority = payload.get("high_priority")
    if not _v4_global(_v4_scope, 'isinstance')(high_priority, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day high priority")
    high_status = payload.get("high_priority_status")
    if not _v4_global(_v4_scope, 'isinstance')(high_status, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(high_status) != {
        "status",
        "rule_id",
        "registry",
        "cannot_confirm",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day high priority status")
    if high_status["registry"] == "MISSING" and high_priority:
        raise _v4_global(_v4_scope, 'ValueError')("registry-missing high priority must be empty")
    if high_status["registry"] == "MISSING" and high_status["status"] != "CANNOT_CONFIRM":
        raise _v4_global(_v4_scope, 'ValueError')("registry-missing high priority must be CANNOT_CONFIRM")
    _v4_global(_v4_scope, '_sorted_strings')(payload.get("cannot_confirm"), "cannot_confirm")

    jyg_coverage = payload.get("jyg_coverage")
    if not _v4_global(_v4_scope, 'isinstance')(jyg_coverage, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(jyg_coverage) != {
        "status",
        "articles",
        "expected_articles",
        "stock_mentions",
        "registry",
        "gap",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day jyg coverage")
    if jyg_coverage.get("status") not in {"VALIDATED", "CANNOT_CONFIRM"}:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day jyg coverage status")
    if jyg_coverage.get("registry") not in {"VALIDATED", "MISSING"}:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day jyg coverage registry")
    for field in ("articles", "expected_articles", "stock_mentions"):
        value = jyg_coverage.get(field)
        if value is not None and (_v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value < 0):
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid research day jyg coverage {field}")
    if jyg_coverage.get("status") == "CANNOT_CONFIRM":
        if jyg_coverage.get("registry") != "MISSING" or not jyg_coverage.get("gap"):
            raise _v4_global(_v4_scope, 'ValueError')("research day jyg coverage gap is incomplete")
    elif jyg_coverage.get("registry") != "VALIDATED" or jyg_coverage.get("gap") is not None:
        raise _v4_global(_v4_scope, 'ValueError')("research day jyg coverage validation mismatch")


def _validate_day_product_lineage_phase(_v4_scope, /, payload, archive_date, slot_matrix):
    lineage = payload.get("lineage")
    if not _v4_global(_v4_scope, 'isinstance')(lineage, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(lineage) != {
        "source_refs",
        "artifact_sha256",
        "manifest_sha256",
        "receipt_sha256",
        "current_sha256",
        "transformer_identity_sha256",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day lineage")
    if not _v4_global(_v4_scope, 'isinstance')(lineage["source_refs"], _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day source refs")
    source_refs = lineage["source_refs"]
    if _v4_global(_v4_scope, 'set')(source_refs) != _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')):
        raise _v4_global(_v4_scope, 'ValueError')("research day source refs must cover every exact slot")
    matrix_by_slot = {_v4_global(_v4_scope, 'str')(row["slot"]): row for row in slot_matrix}
    for slot in _v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS'):
        ref = source_refs.get(slot)
        if not _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(ref) != {
            "slot",
            "artifact_path",
            "artifact_sha256",
            "receipt_path",
            "receipt_sha256",
            "source_input_sha256",
        }:
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid research day source ref: {slot}")
        if ref["slot"] != slot:
            raise _v4_global(_v4_scope, 'ValueError')(f"research day source ref slot mismatch: {slot}")
        if ref["artifact_path"] != f"research/hourly/live/{archive_date}/{slot}.json":
            raise _v4_global(_v4_scope, 'ValueError')(f"research day source artifact date mismatch: {slot}")
        if ref["receipt_path"] != f"receipts/research/hourly/live/{archive_date}/{slot}.json":
            raise _v4_global(_v4_scope, 'ValueError')(f"research day source receipt date mismatch: {slot}")
        for field in ("artifact_sha256", "receipt_sha256", "source_input_sha256"):
            _v4_global(_v4_scope, '_sha')(ref[field], f"source_refs.{slot}.{field}")
        matrix_row = matrix_by_slot[slot]
        for field in ("artifact_path", "artifact_sha256", "receipt_path", "receipt_sha256", "source_input_sha256"):
            if ref[field] != matrix_row[field]:
                raise _v4_global(_v4_scope, 'ValueError')(f"research day source ref mismatch: {slot}.{field}")
    for field in (
        "artifact_sha256",
        "manifest_sha256",
        "receipt_sha256",
        "transformer_identity_sha256",
    ):
        _v4_global(_v4_scope, '_sha')(lineage[field], field)
    current_sha = lineage["current_sha256"]
    if current_sha is not None:
        _v4_global(_v4_scope, '_sha')(current_sha, "current_sha256")

