"""domains.research_day_product: day_assembly (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_research_day_product_body(_v4_scope, /, archive_date, slots, *, source_refs, stock_mentions_registry, transformer_identity_sha256):
    """Build one day product from eight named, already materialized slots."""

    (
        archive_date, slot_matrix, evidence_rows, exclusions, excluded_by_date,
        lineage_refs, cannot_confirm,
    ) = _collect_day_slot_inputs_phase(_v4_scope, archive_date, slots, source_refs)
    mention_pairs, stock_groups = _group_day_mentions_phase(
        _v4_scope, evidence_rows, cannot_confirm
    )
    stock_rollups = _rollup_day_stocks_phase(_v4_scope, stock_groups)
    (
        high_priority, high_status, jyg_coverage, cannot_confirm, transformer,
    ) = _project_day_registry_phase(
        _v4_scope, stock_mentions_registry, cannot_confirm, transformer_identity_sha256
    )
    return _assemble_day_product_phase(
        _v4_scope, archive_date, slot_matrix, evidence_rows, exclusions,
        excluded_by_date, lineage_refs, cannot_confirm, mention_pairs,
        stock_rollups, high_priority, high_status, jyg_coverage, transformer,
    )


def _collect_day_slot_inputs_phase(_v4_scope, /, archive_date, slots, source_refs):
    archive_date = _v4_global(_v4_scope, '_date')(archive_date)
    if _v4_global(_v4_scope, 'set')(slots) != _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')):
        missing = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')) - _v4_global(_v4_scope, 'set')(slots))
        extra = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(slots) - _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')))
        raise _v4_global(_v4_scope, 'ValueError')(f"research day requires exact slots missing={missing} extra={extra}")
    source_refs = source_refs or {}
    slot_matrix: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    exclusions = {"date_mismatch": 0, "pit_violation": 0, "invalid_row": 0}
    excluded_by_date: dict[str, int] = {}
    lineage_refs: dict[str, dict[str, Any]] = {}
    cannot_confirm: list[str] = []

    for slot in _v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS'):
        payload = slots[slot]
        if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')(f"research day slot {slot} is not an object")
        ref = _v4_global(_v4_scope, '_lineage_ref')(slot, payload, source_refs.get(slot))
        ref["artifact_path"] = ref["artifact_path"].replace("{date}", archive_date)
        ref["receipt_path"] = ref["receipt_path"].replace("{date}", archive_date)
        lineage_refs[slot] = {
            **ref,
            "slot": slot,
            "source_input_sha256": ref["source_input_sha256"],
        }
        rows = _v4_global(_v4_scope, '_source_rows')(payload)
        exact_count = 0
        for index, raw_row in _v4_global(_v4_scope, 'enumerate')(rows):
            if not _v4_global(_v4_scope, 'isinstance')(raw_row, _v4_global(_v4_scope, 'Mapping')):
                exclusions["invalid_row"] += 1
                cannot_confirm.append(f"INVALID_ROW:{slot}:{index}")
                continue
            row = _v4_global(_v4_scope, 'dict')(raw_row)
            try:
                published_at = _v4_global(_v4_scope, '_published_timestamp')(row.get("published_at"))
            except _v4_global(_v4_scope, 'ValueError'):
                exclusions["invalid_row"] += 1
                cannot_confirm.append(f"PUBLISHED_AT_INVALID:{slot}:{index}")
                continue
            published_date = published_at.strftime("%Y%m%d")
            if published_date != archive_date:
                exclusions["date_mismatch"] += 1
                excluded_by_date[published_date] = excluded_by_date.get(published_date, 0) + 1
                continue
            row["archive_date"] = archive_date
            row["slot"] = slot
            row["source_row_ref"] = f"{slot}:{index}"
            row["source_artifact_path"] = ref["artifact_path"]
            row["source_artifact_sha256"] = ref["artifact_sha256"]
            row["source_receipt_path"] = ref["receipt_path"]
            row["source_receipt_sha256"] = ref["receipt_sha256"]
            row["source_input_sha256"] = ref["source_input_sha256"]
            if _v4_global(_v4_scope, 'normalize_pair_identity')(
                row.get("url") or row.get("source_url"),
                row.get("stock_code") or row.get("code"),
            ) is None:
                row["identity_status"] = "URL_REQUIRED/CANNOT_CONFIRM"
            else:
                row["identity_status"] = "READY"
            evidence_rows.append(row)
            exact_count += 1
        slot_matrix.append(
            {
                "slot": slot,
                "status": "READY",
                "raw_rows": _v4_global(_v4_scope, 'len')(rows),
                "exact_rows": exact_count,
                "excluded_rows": _v4_global(_v4_scope, 'len')(rows) - exact_count,
                "artifact_path": ref["artifact_path"],
                "artifact_sha256": ref["artifact_sha256"],
                "receipt_path": ref["receipt_path"],
                "receipt_sha256": ref["receipt_sha256"],
                "source_input_sha256": ref["source_input_sha256"],
            }
        )
    return archive_date, slot_matrix, evidence_rows, exclusions, excluded_by_date, lineage_refs, cannot_confirm


def _group_day_mentions_phase(_v4_scope, /, evidence_rows, cannot_confirm):
    evidence_rows.sort(key=lambda row: (_v4_global(_v4_scope, '_slot_number')(row["slot"]), row["source_row_ref"]))
    groups: dict[str, list[dict[str, Any]]] = _v4_global(_v4_scope, 'defaultdict')(_v4_global(_v4_scope, 'list'))
    for row in evidence_rows:
        pair_key = _v4_global(_v4_scope, 'normalize_pair_identity')(
            row.get("url") or row.get("source_url"),
            row.get("stock_code") or row.get("code"),
        )
        if pair_key is None:
            cannot_confirm.append("URL_REQUIRED/CANNOT_CONFIRM")
            continue
        row["_variant_sha256"] = _v4_global(_v4_scope, '_sha256')(_v4_global(_v4_scope, '_variant')(row))
        groups[pair_key].append(row)

    mention_pairs: list[dict[str, Any]] = []
    stock_groups: dict[str, list[dict[str, Any]]] = _v4_global(_v4_scope, 'defaultdict')(_v4_global(_v4_scope, 'list'))
    for pair_key in _v4_global(_v4_scope, 'sorted')(groups):
        rows = groups[pair_key]
        winner = _v4_global(_v4_scope, 'sorted')(
            rows,
            key=lambda row: (
                -_v4_global(_v4_scope, '_level_rank')(row.get("evidence_level")),
                -_v4_global(_v4_scope, '_slot_number')(row.get("slot")),
                -_v4_global(_v4_scope, '_confidence_rank')(row.get("confidence")),
                -_v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, '_text')(row.get("evidence_sentence"))),
                row["_variant_sha256"],
            ),
        )[0]
        for row in rows:
            row["changed_fields"] = _v4_global(_v4_scope, '_changed_fields')(row, winner)
        variants = _v4_global(_v4_scope, 'sorted')({row["_variant_sha256"] for row in rows})
        source_slots = _v4_global(_v4_scope, 'sorted')({row["slot"] for row in rows})
        code = _v4_global(_v4_scope, 'unicodedata').normalize(
            "NFKC", _v4_global(_v4_scope, '_text')(winner.get("stock_code") or winner.get("code"))
        ).upper()
        pair = {
            "pair_key": pair_key,
            "normalized_url": _v4_global(_v4_scope, 'unicodedata').normalize(
                "NFKC", _v4_global(_v4_scope, '_text')(winner.get("url") or winner.get("source_url"))
            ),
            "stock_code": code,
            "stock_name": _v4_global(_v4_scope, '_text')(winner.get("stock_name") or winner.get("name")),
            "winner": {
                key: value
                for key, value in winner.items()
                if not key.startswith("_")
            },
            "source_slots": source_slots,
            "occurrence_count": _v4_global(_v4_scope, 'len')(rows),
            "variant_count": _v4_global(_v4_scope, 'len')(variants),
            "article_ids": _v4_global(_v4_scope, 'sorted')(
                {
                    _v4_global(_v4_scope, '_text')(row.get("article_id") or row.get("evidence_id"))
                    for row in rows
                    if _v4_global(_v4_scope, '_text')(row.get("article_id") or row.get("evidence_id"))
                }
            ),
            "dedupe_keys": _v4_global(_v4_scope, 'sorted')(
                {
                    _v4_global(_v4_scope, '_text')(row.get("dedupe_key"))
                    for row in rows
                    if _v4_global(_v4_scope, '_text')(row.get("dedupe_key"))
                }
            ),
            "source_refs": [
                _v4_global(_v4_scope, '_source_ref')(row)
                for row in _v4_global(_v4_scope, 'sorted')(rows, key=lambda item: item["source_row_ref"])
            ],
            "duplicate_reason": (
                "UNIQUE"
                if _v4_global(_v4_scope, 'len')(rows) == 1
                else "CROSS_SLOT_REPEAT"
                if _v4_global(_v4_scope, 'len')(source_slots) > 1
                else "INTRA_SLOT_REPEAT"
            ),
            "tiebreaker": {
                "evidence_level": _v4_global(_v4_scope, '_text')(winner.get("evidence_level")) or "UNKNOWN",
                "slot": winner["slot"],
                "confidence": _v4_global(_v4_scope, '_text')(winner.get("confidence")) or "UNKNOWN",
                "evidence_sentence_length": _v4_global(_v4_scope, 'len')(
                    _v4_global(_v4_scope, '_text')(winner.get("evidence_sentence"))
                ),
                "variant_sha256": winner["_variant_sha256"],
                "order": [
                    "evidence_level",
                    "slot",
                    "confidence",
                    "evidence_sentence_length_desc",
                    "variant_sha256_asc",
                ],
            },
            "recommendation_status": "RESEARCH_ONLY",
        }
        mention_pairs.append(pair)
        stock_groups[code].append(pair)
    return mention_pairs, stock_groups


def _rollup_day_stocks_phase(_v4_scope, /, stock_groups):
    stock_rollups = []
    for code in _v4_global(_v4_scope, 'sorted')(stock_groups):
        pairs = stock_groups[code]
        stock_rollups.append(
            {
                "stock_code": code,
                "stock_name": _v4_global(_v4_scope, '_text')(pairs[0].get("stock_name")),
                "mention_pair_count": _v4_global(_v4_scope, 'len')(pairs),
                "evidence_row_count": _v4_global(_v4_scope, 'sum')(
                    _v4_global(_v4_scope, 'int')(pair["occurrence_count"]) for pair in pairs
                ),
                "source_slots": _v4_global(_v4_scope, 'sorted')(
                    {slot for pair in pairs for slot in pair["source_slots"]}
                ),
                "urls": _v4_global(_v4_scope, 'sorted')({pair["normalized_url"] for pair in pairs}),
                "pair_keys": [pair["pair_key"] for pair in pairs],
                "duplicate_pair_count": _v4_global(_v4_scope, 'sum')(
                    1 for pair in pairs if pair["occurrence_count"] > 1
                ),
                "recommendation_status": "RESEARCH_ONLY",
            }
        )
    return stock_rollups


def _project_day_registry_phase(_v4_scope, /, stock_mentions_registry, cannot_confirm, transformer_identity_sha256):
    high_priority, high_status, registry_gaps = _v4_global(_v4_scope, '_registry_projection')(
        stock_mentions_registry
    )
    cannot_confirm.extend(registry_gaps)
    jyg_coverage = _v4_global(_v4_scope, '_jyg_coverage')(stock_mentions_registry)
    if jyg_coverage["gap"]:
        cannot_confirm.append(_v4_global(_v4_scope, 'str')(jyg_coverage["gap"]))
    cannot_confirm = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(cannot_confirm))
    transformer = (
        transformer_identity_sha256
        if transformer_identity_sha256
        else _v4_global(_v4_scope, '_sha256')({"contract_id": _v4_global(_v4_scope, 'CONTRACT_ID'), "workflow_name": _v4_global(_v4_scope, 'WORKFLOW_NAME')})
    )
    if _v4_global(_v4_scope, 'len')(transformer) != 64:
        raise _v4_global(_v4_scope, 'ValueError')("research day transformer identity must be SHA-256")
    return high_priority, high_status, jyg_coverage, cannot_confirm, transformer


def _assemble_day_product_phase(_v4_scope, /, archive_date, slot_matrix, evidence_rows, exclusions, excluded_by_date, lineage_refs, cannot_confirm, mention_pairs, stock_rollups, high_priority, high_status, jyg_coverage, transformer):
    counts = {
        "raw_rows": _v4_global(_v4_scope, 'sum')(row["raw_rows"] for row in slot_matrix),
        "evidence_rows": _v4_global(_v4_scope, 'len')(evidence_rows),
        "excluded_rows": _v4_global(_v4_scope, 'sum')(row["excluded_rows"] for row in slot_matrix),
        "mention_pairs": _v4_global(_v4_scope, 'len')(mention_pairs),
        "urls": _v4_global(_v4_scope, 'len')({pair["normalized_url"] for pair in mention_pairs}),
        "stock_rollups": _v4_global(_v4_scope, 'len')(stock_rollups),
        "high_priority": _v4_global(_v4_scope, 'len')(high_priority),
        "duplicate_pairs": _v4_global(_v4_scope, 'sum')(
            1 for pair in mention_pairs if pair["occurrence_count"] > 1
        ),
    }
    lineage = {
        "source_refs": lineage_refs,
        "artifact_sha256": _v4_global(_v4_scope, '_sha256')(
            {
                "archive_date": archive_date,
                "evidence_rows": evidence_rows,
                "mention_pairs": mention_pairs,
                "stock_rollups": stock_rollups,
                "excluded_by_date": excluded_by_date,
                "jyg_coverage": jyg_coverage,
            }
        ),
        "manifest_sha256": _v4_global(_v4_scope, '_sha256')(slot_matrix),
        "receipt_sha256": _v4_global(_v4_scope, '_sha256')(lineage_refs),
        "current_sha256": None,
        "transformer_identity_sha256": transformer,
    }
    product = {
        "schema_version": _v4_global(_v4_scope, 'PRODUCT_SCHEMA_VERSION'),
        "contract_id": _v4_global(_v4_scope, 'CONTRACT_ID'),
        "workflow_name": _v4_global(_v4_scope, 'WORKFLOW_NAME'),
        "pass_signal": _v4_global(_v4_scope, 'PASS_SIGNAL'),
        "archive_date": archive_date,
        "timezone": _v4_global(_v4_scope, 'TIMEZONE'),
        "date_mode": _v4_global(_v4_scope, 'DATE_MODE'),
        "status": "READY_WITH_DECLARED_GAPS" if cannot_confirm else "READY",
        "authoritative": not cannot_confirm and high_status["status"] == "READY",
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "expected_slots": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')),
        "coverage": {
            "expected_slots": _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')),
            "ready_slots": _v4_global(_v4_scope, 'len')(slot_matrix),
            "missing_slots": [],
            "complete": True,
            "slot_matrix": slot_matrix,
        },
        "counts": counts,
        "exclusions": exclusions,
        "excluded_by_date": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'sorted')(excluded_by_date.items())),
        "slot_matrix": slot_matrix,
        "evidence_rows": [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in evidence_rows
        ],
        "mention_pairs": mention_pairs,
        "stock_rollups": stock_rollups,
        "high_priority": high_priority,
        "high_priority_status": high_status,
        "jyg_coverage": jyg_coverage,
        "lineage": lineage,
        "cannot_confirm": cannot_confirm,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    _v4_global(_v4_scope, 'validate_research_day_product')(product)
    return product

