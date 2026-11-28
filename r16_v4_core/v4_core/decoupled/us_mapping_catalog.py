"""Read-only, source-bound US-to-HK research catalog validation and search.

This module preserves the supplied review package as user-provided research.
It does not validate company facts, promote source statuses, or assign
prediction eligibility.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping


SCHEMA_VERSION = "v4.us_hk_mapping_catalog.v1"
SOURCE_PACKAGE_SHA256 = "dac3c820fcd6919fabdccc9c37ee9055b729b200fcde5e48f0dcf527de81bc6d"
MEMBERSHIP_SHA256 = "9b799c0b74ac5047f4e44a1b3dfd1dfa5ca9ce978fa3b8e7877913c423424c9c"
BASE_FILE_SHA256 = "3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671"
OVERLAY_FILE_SHA256 = "d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69"
REVIEW_PACKAGE_SHA256 = "2894b3bca475965aa3553977a654b10fa4c6750bbcb80f70f1bea17bdde649b0"
REVIEW_MANIFEST_SHA256 = "8ba8ea7ef7c351bcd5a1b72ad8f449b7acf555a54a172ea66084248f28e26ab9"
PRIOR_220_OVERLAY_SHA256 = "72a0f074e6412036cd103c7f73ccf15230eb3d1633c09742c88653b863eba384"
RECOVERY_OVERLAY_NAME = "us_hk_667_recovery_overlay_20261016.json"
RECOVERY_OVERLAY_SHA256 = "3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c"
RECOVERY_MANIFEST_SHA256 = "6500e67d2d85e208b0f32c8c2ce5aeaf40298d8629f81ad414f050a29f913646"
RECOVERY_MEMBER_HASHES = {
    "CURRENT/01A_full_667_original_and_history_plus_v2.csv": "312423a9bc4036b24e393bb7ca14295c91997cb6dede3c2cb0fa334dffd6eb3c",
    "CURRENT/01B_full_1003_original_and_history_plus_v2.csv": "f27d4977a653ab981c12e5b5d523ee53f9777ff06410e66ef83608ca763184c5",
    "CURRENT/ACCEPTANCE_LEDGER.json": "98ae5272c2f5f81e6666d44464ce76f25d1ba73d3c4a1373097688a3c0d8577b",
    "CURRENT/A_URL_OCCURRENCES_UNATTEMPTED_62.csv": "07db9f282156f29cbfc6295280dec6a7cdc8c6660e5eb63e5ec8db38f0505173",
    "CURRENT/BASELINE_MANIFEST_REFERENCE.json": "966a329bfa143da1347475885d4b7d19f18feb76fda7cc763a7e562ed31af406",
    "CURRENT/EFFECTIVE_RESEARCH_1003.json": "43813adcdb39b81c45a827906f8a872af82bec1c11a0e2282153085d96a7b944",
    "CURRENT/FIELD_ASSESSMENTS_1003x7.csv": "f8d2985252d3a920f8cc52890a9e6bb720d68f242a07c7532ca5b43171525576",
    "CURRENT/METRICS.json": "a60ce260b7820a5e33fc335b26a2733c875311379bedc026b57d2bdc30609b0f",
    "CURRENT/NO_ORIGINAL_B_RELATIONS_18.csv": "b2500fe952951bbb45314b2ab270a8edf388cc4e67d87615c751e667f7dd3157",
    "CURRENT/OPEN_RELATIONS_221.csv": "811140d315c7701ef96a6be5db294afd962956bc9d2fbbaa826fbdbd20223030",
    "CURRENT/ORIGINAL_URL_ACCESS_ACCOUNTING.json": "c49b52a1899062b9ce70ef8a21d62beeb7656feb6441b751dcc32de0f9e69e2f",
    "CURRENT/RELATION_SUMMARY_1003.csv": "6e9dd2613ee6a6391c38f81651b7ee3f379b167b8d9545f86d840a89983fe345",
    "CURRENT/SIX_LAYERS_1003x6.csv": "596228bc4e37b5d69dab13c749930e131ce43f3ad26044d4c0dcfb8f988f38d0",
    "CURRENT/VERSION_PRECEDENCE.json": "ed3b1dbbee64683a187be53fb2a965608373768bd9617231ce4473a789ad0f95",
}
RECOVERY_STATUS_COUNTS = {
    "CLOSED_RESEARCH_SCOPE": 757,
    "CLOSED_EXCLUDED_SCOPE": 25,
    "OPEN": 221,
}
EXPECTED_REVIEWED_RELATION_COUNT = 700
RESEARCH_USES = {"PENDING_REVIEW", "CONDITIONAL_OBSERVATION", "BACKGROUND_HISTORICAL", "EXCLUDED_CURRENT"}
EXPECTED_STOCK_COUNT = 667
EXPECTED_RELATION_COUNT = 1003
_CODE_RE = re.compile(r"^[0-9]{5}$")
_US_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,19}$")


class CatalogValidationError(ValueError):
    """Raised when a catalog is damaged or violates its frozen source contract."""


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def integrity_sha256(value: Mapping[str, Any]) -> str:
    body = dict(value)
    body.pop("integrity_sha256", None)
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def validate_catalog(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogValidationError("catalog root must be an object")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise CatalogValidationError("catalog schema version is invalid")
    if value.get("integrity_sha256") != integrity_sha256(value):
        raise CatalogValidationError("catalog integrity check failed")

    source = value.get("source")
    if not isinstance(source, dict):
        raise CatalogValidationError("catalog source metadata is missing")
    if source.get("package_sha256") != SOURCE_PACKAGE_SHA256:
        raise CatalogValidationError("catalog source package identity is invalid")
    if source.get("membership_sha256") != MEMBERSHIP_SHA256:
        raise CatalogValidationError("catalog membership identity is invalid")
    if source.get("membership_snapshot") != "2026-10-14":
        raise CatalogValidationError("catalog membership snapshot is invalid")

    flags = value.get("safety")
    if flags != {
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "prediction_validation": "UNTESTED",
        "historical_PIT": "NOT_VALIDATED",
    }:
        raise CatalogValidationError("catalog safety flags are invalid")

    stocks = value.get("stocks")
    relations = value.get("relations")
    if not isinstance(stocks, list) or len(stocks) != EXPECTED_STOCK_COUNT:
        raise CatalogValidationError("catalog stock count is invalid")
    if not isinstance(relations, list) or len(relations) != EXPECTED_RELATION_COUNT:
        raise CatalogValidationError("catalog relation count is invalid")

    stock_by_code: dict[str, dict[str, Any]] = {}
    for index, stock in enumerate(stocks, start=1):
        if not isinstance(stock, dict) or stock.get("ordinal") != index:
            raise CatalogValidationError("catalog stock order is invalid")
        code = stock.get("hk_code")
        if not isinstance(code, str) or _CODE_RE.fullmatch(code) is None or code in stock_by_code:
            raise CatalogValidationError("catalog HK code is invalid or duplicated")
        if not isinstance(stock.get("source_record"), dict):
            raise CatalogValidationError("catalog stock source row is missing")
        if stock["source_record"].get("代码") != code:
            raise CatalogValidationError("catalog stock source row does not match code")
        stock_by_code[code] = stock

    observed_relation_ids: list[str] = []
    relation_codes: set[str] = set()
    for index, relation in enumerate(relations, start=1):
        if not isinstance(relation, dict) or relation.get("source_row") != index:
            raise CatalogValidationError("catalog relation order is invalid")
        code = relation.get("hk_code")
        symbol = relation.get("us_symbol")
        raw = relation.get("source_record")
        if not isinstance(code, str) or code not in stock_by_code:
            raise CatalogValidationError("catalog relation references an unknown HK code")
        if not isinstance(symbol, str) or not isinstance(raw, dict):
            raise CatalogValidationError("catalog relation identity or source row is missing")
        if raw.get("code") != code or raw.get("asset_code") != symbol:
            raise CatalogValidationError("catalog relation source row does not match identity")
        if relation.get("prediction_validation") != "UNTESTED" or relation.get("historical_PIT") != "NOT_VALIDATED":
            raise CatalogValidationError("catalog relation was promoted beyond source validation")
        if relation.get("fact_review_status") != "PENDING" or relation.get("prediction_eligible") is not False:
            raise CatalogValidationError("catalog relation safety state is invalid")
        if raw.get("prediction") != "UNTESTED" or raw.get("historical_PIT") != "NOT_VALIDATED":
            raise CatalogValidationError("catalog relation source prediction fields changed")
        relation_codes.add(code)
        relation_id = raw.get("relation_id")
        if relation_id:
            observed_relation_ids.append(relation_id)

    expected_relation_ids_by_code: dict[str, list[str]] = {code: [] for code in stock_by_code}
    for relation in relations:
        relation_id = relation["source_record"].get("relation_id")
        if relation_id:
            expected_relation_ids_by_code[relation["hk_code"]].append(relation_id)
    for code, stock in stock_by_code.items():
        if stock.get("relation_ids") != expected_relation_ids_by_code[code]:
            raise CatalogValidationError("catalog stock relation index is invalid")

    coverage = value.get("coverage")
    if not isinstance(coverage, dict):
        raise CatalogValidationError("catalog coverage metadata is missing")
    if coverage.get("membership_count") != EXPECTED_STOCK_COUNT:
        raise CatalogValidationError("catalog membership count is invalid")
    if coverage.get("main_table_a_rows") != EXPECTED_STOCK_COUNT or coverage.get("main_table_a_unique_codes") != EXPECTED_STOCK_COUNT:
        raise CatalogValidationError("catalog main table A coverage is invalid")
    for key in [
        "main_table_a_order_matches_membership",
        "main_table_a_names_match_membership",
        "coverage_table_order_matches_membership",
        "report_section_order_matches_membership",
        "report_section_names_match_membership",
        "relation_rows_reference_membership",
    ]:
        if coverage.get(key) is not True:
            raise CatalogValidationError(f"catalog structural check failed: {key}")
    if coverage.get("relation_row_count") != EXPECTED_RELATION_COUNT:
        raise CatalogValidationError("catalog relation coverage count is invalid")
    if coverage.get("stocks_with_relations") != len(relation_codes):
        raise CatalogValidationError("catalog relation coverage summary is invalid")
    if coverage.get("stocks_without_relations") != [stock["hk_code"] for stock in stocks if stock["hk_code"] not in relation_codes]:
        raise CatalogValidationError("catalog missing-relation list is invalid")
    return value


def load_catalog(path: Path | str) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CatalogValidationError("catalog file cannot be read as valid JSON") from exc
    return validate_catalog(value)


def load_review_overlay(path: Path | str, catalog: Mapping[str, Any]) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != OVERLAY_FILE_SHA256:
            raise CatalogValidationError("review overlay pinned SHA mismatch")
        value = json.loads(raw)
        if (value.get("schema_version") != "v4.us_hk_mapping_review_overlay.v1" or
                value.get("integrity_sha256") != integrity_sha256(value) or
                value.get("base_catalog_sha256") != BASE_FILE_SHA256 or
                value.get("source_package_sha256") != REVIEW_PACKAGE_SHA256 or
                value.get("source_package_kind") != "combined_560_700_supplement" or
                value.get("source_subtree") != "700/deliverable_batch35" or
                value.get("manifest_sha256") != REVIEW_MANIFEST_SHA256 or
                value.get("upstream_original_700_package") != {
                    "claimed_sha256": "589dd772...",
                    "received_locally": False,
                    "local_sha256_verified": False,
                }):
            raise CatalogValidationError("review overlay identity is invalid")
        if value.get("research_safety") != {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "prediction_validation": "UNTESTED",
            "historical_PIT": "NOT_VALIDATED",
            "event_validation": "NOT_RUN",
            "independent_local_review": "NOT_RUN",
        }:
            raise CatalogValidationError("review overlay research safety is invalid")
        prior = value.get("prior_220_preservation")
        if prior != {
            "prior_overlay_sha256": PRIOR_220_OVERLAY_SHA256,
            "prior_relation_count": 220,
            "prior_evidence_occurrences": 1831,
            "current_evidence_occurrences_for_prior_relations": 1931,
            "prior_evidence_occurrence_delta": 100,
            "prior_relations_with_added_evidence": 51,
            "prior_states_and_field_assessments_preserved": True,
            "prior_evidence_ids_preserved_by_relation": True,
            "prior_overlay_preimage": "preimage/us_hk_667_review_overlay_20261015.json",
        }:
            raise CatalogValidationError("prior 220 preservation receipt is invalid")
        records = value.get("records", [])
        if (len(records) != EXPECTED_REVIEWED_RELATION_COUNT or
                len({r["relation_id"] for r in records}) != EXPECTED_REVIEWED_RELATION_COUNT):
            raise CatalogValidationError("review overlay coverage is invalid")
        use_counts = Counter(record.get("research_use") for record in records)
        if use_counts != Counter({
            "PENDING_REVIEW": 682,
            "BACKGROUND_HISTORICAL": 10,
            "EXCLUDED_CURRENT": 5,
            "CONDITIONAL_OBSERVATION": 3,
        }):
            raise CatalogValidationError("review overlay research-use projection is invalid")
        parse_issue_count = 0
        for record in records:
            row = catalog["relations"][record["source_row"] - 1]
            if (row["source_record"].get("关系编号") != record["relation_id"] or
                    row["hk_code"] != record["hk_code"] or row["us_symbol"] != record["us_symbol"] or
                    record["source_review_status"] != "SOURCE_REVIEWED" or
                    record["independent_verification"] != "NOT_RUN" or
                    record["research_use"] not in RESEARCH_USES or
                    record["source_current_state"] != record["revision"].get("revision_current_applicability_state")):
                raise CatalogValidationError("review overlay relation identity or safety is invalid")
            revision = record["revision"]
            if (revision.get("revision_event_validation_state") != "NOT_RUN" or
                    revision.get("revision_prediction_validation_state") != "UNTESTED" or
                    revision.get("revision_historical_PIT_state") != "NOT_VALIDATED" or
                    revision.get("revision_independent_local_review_state") != "NOT_RUN" or
                    revision.get("revision_RESEARCH_ONLY") != "true" or
                    revision.get("revision_production_allowed") != "false" or
                    revision.get("revision_buy_gate_updated") != "false" or
                    revision.get("revision_orders_sent") != "false"):
                raise CatalogValidationError("review overlay revision safety is invalid")
            issues = record.get("revision_json_parse_issues")
            if not isinstance(issues, list):
                raise CatalogValidationError("review overlay JSON parse issue ledger is invalid")
            for issue in issues:
                raw_value = revision.get(issue.get("field"))
                if (issue.get("field") != "revision_failure_checks_json" or
                        issue.get("issue") != "INVALID_JSON_PRESERVED_AS_SOURCE_TEXT" or
                        issue.get("error_type") != "JSONDecodeError" or
                        not isinstance(raw_value, str) or
                        hashlib.sha256(raw_value.encode("utf-8")).hexdigest() != issue.get("raw_sha256") or
                        len(raw_value) != issue.get("raw_characters")):
                    raise CatalogValidationError("review overlay JSON parse issue does not bind raw source")
            parse_issue_count += len(issues)
            for evidence in record.get("evidence", []):
                if not isinstance(evidence, dict) or any(
                    not isinstance(evidence.get(key), str) for key in (
                        "declared_unresolved_navigation_reference_json",
                        "evidence_wording_clarifications_json",
                    )
                ):
                    raise CatalogValidationError("review overlay full evidence fields are missing")
        if parse_issue_count != 60:
            raise CatalogValidationError("review overlay JSON parse issue count is invalid")
        return value
    except CatalogValidationError:
        raise
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise CatalogValidationError("review overlay cannot be read") from exc


def load_recovery_overlay(path: Path | str, catalog: Mapping[str, Any],
                          legacy_overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Load the complete v2r1 projection without merging it into legacy states."""
    try:
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != RECOVERY_OVERLAY_SHA256:
            raise CatalogValidationError("recovery overlay pinned SHA mismatch")
        value = json.loads(raw, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
        if (value.get("schema_version") != "v4.us_hk_mapping_recovery_overlay.v1" or
                value.get("integrity_sha256") != integrity_sha256(value) or
                value.get("base_catalog_sha256") != BASE_FILE_SHA256 or
                value.get("source_package_sha256") != "48f1124c10ed3440c22910a9125038748c08d673fc3ec543635cc9aae0b344d4" or
                value.get("source_manifest_sha256") != RECOVERY_MANIFEST_SHA256 or
                value.get("source_manifest_member_count") != 3637 or
                {key: item.get("sha256") for key, item in value.get("source_member_hashes", {}).items()} != RECOVERY_MEMBER_HASHES):
            raise CatalogValidationError("recovery overlay source identity is invalid")

        old_records = legacy_overlay.get("records", [])
        old_ids = [record.get("relation_id") for record in old_records]
        prior = value.get("prior_700_history")
        if (not isinstance(prior, dict) or prior.get("sha256") != OVERLAY_FILE_SHA256 or
                prior.get("record_count") != EXPECTED_REVIEWED_RELATION_COUNT or
                prior.get("relation_ids") != old_ids or
                prior.get("retained_as_separate_history") is not True or
                prior.get("status_crosswalk") != "NOT_ESTABLISHED"):
            raise CatalogValidationError("separate legacy 700 history binding is invalid")

        if value.get("counts") != {
            "snapshot_stocks": 667,
            "original_relations": 1003,
            "processed_relations": 1003,
            "closure_status_counts": RECOVERY_STATUS_COUNTS,
            "research_scope_closed": 757,
            "excluded_scope_closed": 25,
            "closed_total_including_exclusions": 782,
            "open_relations": 221,
            "stocks_with_relations": 649,
            "stocks_without_relations": 18,
            "company_independent_acceptance": 0,
        }:
            raise CatalogValidationError("recovery closure count contract is invalid")
        if value.get("research_safety") != {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "fact_validation": "INDEPENDENT_ACCEPTANCE_0",
            "prediction_validation": "UNTESTED",
            "historical_PIT": "NOT_VALIDATED",
            "event_and_data_tests": "NOT_RUN",
            "semantic_mapping_validity": "CANNOT_CONFIRM",
        }:
            raise CatalogValidationError("recovery research safety state is invalid")
        if value.get("evidence_limits") != {
            "historical_path_gap_occurrences": 227,
            "historical_path_gap_unique_paths": 218,
            "separate_restored740_missing_path_sha_pairs": 404,
            "separate_restored740_missing_hashes": 388,
            "gap_scopes_additive": False,
            "A_url_occurrences_unattempted": 62,
            "available_at": "ABSENT",
            "access_dates_are_available_at": False,
            "access_date_interpretation": "Research access dates do not establish fact effective dates or available_at.",
            "all_statements_verified": False,
        }:
            raise CatalogValidationError("recovery evidence limit contract is invalid")
        if not isinstance(value.get("version_precedence"), dict):
            raise CatalogValidationError("recovery version precedence is missing")

        records = value.get("records")
        if not isinstance(records, list) or len(records) != EXPECTED_RELATION_COUNT:
            raise CatalogValidationError("recovery relation coverage is invalid")
        expected_relations = catalog["relations"]
        observed_ids: list[str] = []
        status_counts = Counter()
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise CatalogValidationError("recovery relation record is malformed")
            base = expected_relations[index - 1]
            relation_id = base["source_record"].get("关系编号")
            current = record.get("effective_summary")
            raw_summary = record.get("current_summary_csv_row")
            provenance = record.get("research_provenance")
            current_research = record.get("effective_research")
            if (record.get("source_row") != index or record.get("relation_id") != relation_id or
                    record.get("hk_code") != base["hk_code"] or record.get("us_symbol") != base["us_symbol"] or
                    record.get("source_original_fields") != base["source_record"] or
                    not isinstance(current, dict) or current.get("relation_id") != relation_id or
                    not isinstance(raw_summary, dict) or raw_summary.get("relation_id") != relation_id or
                    raw_summary.get("closure_status") != current.get("closure_status") or
                    raw_summary.get("primary_research_use") != current.get("primary_research_use") or
                    not isinstance(provenance, dict) or not isinstance(current_research, dict) or
                    current_research.get("relation_id") != relation_id):
                raise CatalogValidationError("recovery relation identity or original fields are invalid")
            if (current.get("stock_code") != base["hk_code"] or
                    current.get("asset_code_original") != base["us_symbol"] or
                    current.get("prediction") != "UNTESTED" or
                    current.get("historical_PIT") != "NOT_VALIDATED" or
                    current.get("event_and_data_tests") != "NOT_RUN" or
                    current.get("company_independent_acceptance") != 0 or
                    current.get("production_allowed") is not False or
                    current.get("orders_sent") is not False):
                raise CatalogValidationError("recovery relation summary or safety fields are invalid")
            if (provenance.get("path") != current.get("effective_research_file") or
                    provenance.get("sha256") != current.get("effective_research_sha256") or
                    not isinstance(provenance.get("bytes"), int) or provenance["bytes"] <= 0):
                raise CatalogValidationError("recovery relation provenance is invalid")
            if current.get("closure_status") not in RECOVERY_STATUS_COUNTS:
                raise CatalogValidationError("recovery relation closure status is invalid")

            layers = record.get("six_layers")
            assessments = record.get("field_assessments")
            if (not isinstance(layers, list) or len(layers) != 6 or
                    not isinstance(assessments, list) or len(assessments) != 7):
                raise CatalogValidationError("recovery relation layer or field assessment coverage is invalid")
            layer_names = set()
            for layer in layers:
                try:
                    layer_record = json.loads(layer.get("effective_layer_record", ""))
                except (AttributeError, TypeError, json.JSONDecodeError) as exc:
                    raise CatalogValidationError("recovery six-layer record is invalid") from exc
                if (layer.get("relation_id") != relation_id or not isinstance(layer.get("layer"), str) or
                        layer["layer"] in layer_names or not isinstance(layer_record, dict)):
                    raise CatalogValidationError("recovery six-layer identity is invalid")
                layer_names.add(layer["layer"])
            assessment_fields = set()
            for assessment in assessments:
                try:
                    assessment_record = json.loads(assessment.get("effective_field_assessment", ""))
                except (AttributeError, TypeError, json.JSONDecodeError) as exc:
                    raise CatalogValidationError("recovery field assessment record is invalid") from exc
                source_field = assessment.get("source_field") if isinstance(assessment, dict) else None
                if (assessment.get("relation_id") != relation_id or not isinstance(source_field, str) or
                        source_field in assessment_fields or not isinstance(assessment_record, dict)):
                    raise CatalogValidationError("recovery field assessment identity is invalid")
                assessment_fields.add(source_field)
            observed_ids.append(relation_id)
            status_counts[current["closure_status"]] += 1

        if observed_ids != [row["source_record"].get("关系编号") for row in expected_relations]:
            raise CatalogValidationError("recovery relation order differs from the original catalog")
        if status_counts != Counter(RECOVERY_STATUS_COUNTS):
            raise CatalogValidationError("recovery closure totals do not reconcile")
        return value
    except CatalogValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        raise CatalogValidationError("recovery overlay cannot be read") from exc


class CatalogStore:
    """Validated, stat-bound in-process cache; responses never expose cached objects.

    Both files are pinned by SHA on each identity change. The complete stat
    signature includes ctime to detect an in-place rewrite with restored mtime.
    A failed reload clears the previous cache and cannot serve stale success.
    """
    def __init__(self):
        self._lock = RLock()
        self._signature = None
        self._catalog = None
        self._overlay = None
        self._recovery_overlay = None

    def search(self, catalog_path: Path | str, overlay_path: Path | str, query=None, **kwargs):
        with self._lock:
            try:
                paths = [Path(catalog_path), Path(overlay_path)]
                recovery_path = paths[1].with_name(RECOVERY_OVERLAY_NAME)
                paths.append(recovery_path)
                signature = tuple((str(p.resolve()), s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                                  for p in paths for s in [p.stat()])
                if signature != self._signature:
                    self._signature = self._catalog = self._overlay = self._recovery_overlay = None
                    if hashlib.sha256(paths[0].read_bytes()).hexdigest() != BASE_FILE_SHA256:
                        raise CatalogValidationError("catalog pinned SHA mismatch")
                    catalog = load_catalog(paths[0])
                    overlay = load_review_overlay(paths[1], catalog)
                    recovery_overlay = load_recovery_overlay(paths[2], catalog, overlay)
                    # Reject a concurrent writer rather than cache mixed file versions.
                    after = tuple((str(p.resolve()), s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                                  for p in paths for s in [p.stat()])
                    if signature != after:
                        raise CatalogValidationError("catalog changed while loading")
                    self._catalog, self._overlay, self._recovery_overlay, self._signature = catalog, overlay, recovery_overlay, signature
                return _search_validated(self._catalog, query, overlay=self._overlay,
                                         recovery_overlay=self._recovery_overlay, **kwargs)
            except (OSError, CatalogValidationError) as exc:
                self._signature = self._catalog = self._overlay = self._recovery_overlay = None
                raise CatalogValidationError("catalog or review overlay unavailable") from exc


def search_catalog(catalog: Mapping[str, Any], query: str | None = None, *,
                   offset: int = 0, limit: int = 25, research_use: str | None = None) -> dict[str, Any]:
    return _search_validated(validate_catalog(dict(catalog)), query, offset=offset, limit=limit,
                             research_use=research_use)


def _review_summary(review):
    if review is None:
        return None
    revision_keys = {
        "revision_research_fact_state", "revision_current_applicability_state",
        "revision_research_fact_dates", "revision_current_applicability_checked_dates",
        "revision_reason", "revision_remaining_gaps_json",
        "revision_additional_research_findings_json", "revision_subsequent_research_addenda_json",
    }
    summary_keys = {
        "primary_use", "primary_use_reason", "verified_facts_json", "usage_limits_json",
        "current_usage_limits_with_addenda_json", "current_applicability_gaps_json",
        "current_applicability_gaps_with_addenda_json", "next_key_evidence_json",
        "current_next_key_evidence_with_addenda_json",
    }
    return {
        "relation_id": review["relation_id"], "source_row": review["source_row"],
        "hk_code": review["hk_code"], "us_symbol": review["us_symbol"],
        "source_review_status": review["source_review_status"],
        "independent_verification": review["independent_verification"],
        "research_use": review["research_use"],
        "revision": {k: v for k, v in review["revision"].items() if k in revision_keys},
        "source_summary": {k: v for k, v in review.get("source_summary", {}).items() if k in summary_keys},
    }


def _recovery_summary(record, *, full: bool):
    if record is None:
        return None
    current = record["effective_summary"]
    research = record["effective_research"]
    summary = {
        "detail_level": "FULL" if full else "SUMMARY",
        "relation_id": record["relation_id"],
        "closure_status": current["closure_status"],
        "primary_research_use": current["primary_research_use"],
        "primary_use_reason": current["primary_use_reason"],
        "verified_fact_scope": current["verified_fact_scope"],
        "applicable_period": current["applicable_period"],
        "closure_scope": current["closure_scope"],
        "closure_basis": current["closure_basis"],
        "remaining_gaps": current["remaining_gaps"],
        "next_key_evidence": current["next_key_evidence"],
        "research_access_date_and_version": current["research_access_date_and_version"],
        "effective_research_file": current["effective_research_file"],
        "effective_research_sha256": current["effective_research_sha256"],
        "evidence_ids": research.get("evidence_ids", []),
        "delivery_acceptance": current["delivery_acceptance"],
        "prediction": current["prediction"],
        "historical_PIT": current["historical_PIT"],
        "event_and_data_tests": current["event_and_data_tests"],
        "company_independent_acceptance": current["company_independent_acceptance"],
    }
    if full:
        summary["full_record"] = record
    return summary


def _search_validated(value, query=None, *, offset=0, limit=25, research_use=None,
                      overlay=None, recovery_overlay=None):
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise CatalogValidationError("offset must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise CatalogValidationError("limit must be between 1 and 200")
    if research_use and research_use not in RESEARCH_USES:
        raise CatalogValidationError("research use is invalid")
    needle = (query or "").strip()
    if len(needle) > 128:
        raise CatalogValidationError("query is too long")
    revisions = {r["source_row"]: r for r in (overlay or {}).get("records", [])}
    recovery_records = {r["relation_id"]: r for r in (recovery_overlay or {}).get("records", [])}
    by_code = {s["hk_code"]: [] for s in value["stocks"]}
    for row in value["relations"]:
        by_code[row["hk_code"]].append(row)
    normalized = needle.upper()
    if normalized.startswith("HK."):
        normalized = normalized[3:]
    exact_hk = normalized if _CODE_RE.fullmatch(normalized) else None
    # RID matching is exact to avoid R001 also finding a URL or unrelated text.
    exact_rid = normalized if re.fullmatch(r"R[0-9]{3,4}", normalized) else None
    selected = []
    for stock in value["stocks"]:
        rows = by_code[stock["hk_code"]]
        stock_match = not needle or (stock["hk_code"] == exact_hk if exact_hk else
            exact_rid is None and any(needle.casefold() in str(v).casefold() for v in stock["source_record"].values()))
        matched = []
        for row in rows:
            review = revisions.get(row["source_row"])
            use = review["research_use"] if review else "PENDING_REVIEW"
            if research_use and use != research_use:
                continue
            rid = row["source_record"].get("关系编号", "")
            relation_match = (rid.upper() == exact_rid if exact_rid else
                exact_hk is None and any(needle.casefold() in str(v).casefold() for v in row["source_record"].values()))
            if stock_match or relation_match:
                matched.append(row)
        if matched or (stock_match and not rows and not research_use):
            selected.append((stock, matched))
    items=[]
    for stock, rows in selected[offset:offset+limit]:
        item={key:stock.get(key) for key in ["ordinal","hk_code","name","english_name","source_record","relation_count"]}
        all_rows=by_code[stock["hk_code"]]
        item["source_reviewed_relation_count"] = sum(r["source_row"] in revisions for r in all_rows)
        item["unprocessed_relation_count"] = len(all_rows)-item["source_reviewed_relation_count"]
        item["relations"]=[]
        for row in rows:
            review=revisions.get(row["source_row"])
            relation_id = row["source_record"].get("关系编号")
            recovery = recovery_records.get(relation_id)
            item["relations"].append({**row,
                "relation_id":relation_id,
                "source_review_status":"SOURCE_REVIEWED" if review else "NOT_PROCESSED",
                "independent_verification":"NOT_RUN", "research_use":review["research_use"] if review else "PENDING_REVIEW",
                "review_detail_level":"FULL" if exact_rid and (review is not None or recovery is not None) else "SUMMARY",
                "review_revision":review if exact_rid and review is not None else _review_summary(review),
                "recovery_v2r1":_recovery_summary(recovery, full=bool(exact_rid and recovery is not None))})
        items.append(item)
    use_counts=Counter(revisions[r["source_row"]]["research_use"] if r["source_row"] in revisions else "PENDING_REVIEW" for r in value["relations"])
    reviewed_codes={r["hk_code"] for r in revisions.values()}
    full_codes=[code for code in reviewed_codes if all(r["source_row"] in revisions for r in by_code[code])]
    claims=value["source_claims"]
    return deepcopy({
        "catalog_id":value["catalog_id"], "catalog_state":"STRUCTURE_VALID_ONLY",
        "catalog_integrity_sha256":value["integrity_sha256"],
        "source":{k:v for k,v in value["source"].items() if k!="local_zip_path"},
        "coverage":value["coverage"],
        "source_claims":{k:claims.get(k) for k in ["main_table_a_progress","main_table_a_relationship_class",
            "main_table_a_prediction_state","main_table_b_prediction_state","main_table_b_old_action",
            "old_matrix_comparison","independent_fact_verification"]},
        "review_progress":{
            "source_reviewed_relations":len(revisions), "unprocessed_relations":1003-len(revisions),
            "source_reviewed_stocks":len(reviewed_codes), "all_original_relations_processed_stocks":len(full_codes),
            "independently_verified_relations":0, "independent_verification":"NOT_RUN",
            "research_use_counts":dict(use_counts),
        },
        "review_source":({k:overlay[k] for k in [
            "source_package_sha256", "source_package_kind", "source_subtree", "manifest_sha256",
            "upstream_original_700_package", "source_generated_at_utc", "integrity_sha256",
            "projection_rule", "prior_220_preservation",
        ]} if overlay else None),
        "recovery_v2r1":({
            "source_package_sha256":recovery_overlay["source_package_sha256"],
            "source_manifest_sha256":recovery_overlay["source_manifest_sha256"],
            "overlay_integrity_sha256":recovery_overlay["integrity_sha256"],
            "counts":recovery_overlay["counts"],
            "research_safety":recovery_overlay["research_safety"],
            "evidence_limits":recovery_overlay["evidence_limits"],
            "prior_700_history":{k:v for k,v in recovery_overlay["prior_700_history"].items() if k != "relation_ids"},
            "version_precedence":recovery_overlay["version_precedence"],
            "projection_rule":recovery_overlay["projection_rule"],
        } if recovery_overlay else None),
        "safety":value["safety"], "query":needle, "research_use":research_use or "",
        "total":len(selected), "offset":offset, "limit":limit, "items":items,
    })


__all__ = ["CatalogValidationError", "CatalogStore", "load_catalog", "load_review_overlay",
           "load_recovery_overlay", "search_catalog", "validate_catalog", "integrity_sha256"]
