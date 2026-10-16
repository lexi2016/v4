"""Build a deterministic V4 projection from the supplied v2r1 data archive.

Archive members are treated as data only. No code or shell instructions from
the archive are imported or executed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile
from typing import Any


EXPECTED_ARCHIVE_SHA256 = "48f1124c10ed3440c22910a9125038748c08d673fc3ec543635cc9aae0b344d4"
EXPECTED_BASE_CATALOG_SHA256 = "3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671"
EXPECTED_LEGACY_OVERLAY_SHA256 = "d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69"
EXPECTED_RELATIONS = 1003
EXPECTED_STOCKS = 667
EXPECTED_SIX_LAYERS = 6
EXPECTED_FIELD_ASSESSMENTS = 7
OVERLAY_SCHEMA = "v4.us_hk_mapping_recovery_overlay.v1"

HANDOFF_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = HANDOFF_DIR.parents[2]
CATALOG_PATH = REPO_ROOT / "v4/manager_workbench/research_data/us_hk_667_catalog_20261015.json"
LEGACY_OVERLAY_PATH = REPO_ROOT / "v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json"
DEFAULT_ARCHIVE = Path("/Users/lexi/Downloads/US_HK_667_1003_recovery_v2r1_20261016.zip")
DEFAULT_OUTPUT = REPO_ROOT / "v4/manager_workbench/research_data/us_hk_667_recovery_overlay_20261016.json"

CURRENT_MEMBERS = (
    "CURRENT/01A_full_667_original_and_history_plus_v2.csv",
    "CURRENT/01B_full_1003_original_and_history_plus_v2.csv",
    "CURRENT/RELATION_SUMMARY_1003.csv",
    "CURRENT/SIX_LAYERS_1003x6.csv",
    "CURRENT/FIELD_ASSESSMENTS_1003x7.csv",
    "CURRENT/EFFECTIVE_RESEARCH_1003.json",
    "CURRENT/VERSION_PRECEDENCE.json",
    "CURRENT/ACCEPTANCE_LEDGER.json",
    "CURRENT/METRICS.json",
    "CURRENT/ORIGINAL_URL_ACCESS_ACCOUNTING.json",
    "CURRENT/OPEN_RELATIONS_221.csv",
    "CURRENT/NO_ORIGINAL_B_RELATIONS_18.csv",
    "CURRENT/A_URL_OCCURRENCES_UNATTEMPTED_62.csv",
    "CURRENT/BASELINE_MANIFEST_REFERENCE.json",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member_path(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _read_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc


def _csv_rows(raw: bytes, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if not reader.fieldnames:
            raise ValueError("missing CSV header")
        rows = list(reader)
    except (UnicodeError, csv.Error, ValueError) as exc:
        raise ValueError(f"{label} is not a valid UTF-8 CSV") from exc
    if any(None in row for row in rows):
        raise ValueError(f"{label} has rows with extra columns")
    return list(reader.fieldnames), rows


def _verify_intake_receipt(archive_sha256: str) -> dict[str, Any]:
    receipt = _read_json((HANDOFF_DIR / "INTAKE_AUDIT.json").read_bytes(), "intake receipt")
    required = {
        "read_only": True,
        "archive_sha256": archive_sha256,
        "manifest_members": 3637,
        "manifest_size_sha_crc": "PASS",
        "base_catalog_sha256": EXPECTED_BASE_CATALOG_SHA256,
        "original_cell_mismatches": 0,
        "stock_count": EXPECTED_STOCKS,
        "relation_count": EXPECTED_RELATIONS,
        "processed_count": 1003,
        "closed_research_count": 757,
        "closed_excluded_count": 25,
        "open_count": 221,
        "stocks_with_relations": 649,
        "stocks_without_relations": 18,
    }
    if any(receipt.get(key) != value for key, value in required.items()):
        raise ValueError("intake receipt does not match the frozen recovery contract")
    return receipt


def _load_catalog() -> dict[str, Any]:
    raw = CATALOG_PATH.read_bytes()
    if _sha256_bytes(raw) != EXPECTED_BASE_CATALOG_SHA256:
        raise ValueError("base catalog SHA mismatch")
    catalog = _read_json(raw, "base catalog")
    if len(catalog.get("stocks", [])) != EXPECTED_STOCKS or len(catalog.get("relations", [])) != EXPECTED_RELATIONS:
        raise ValueError("base catalog stock or relation count mismatch")
    return catalog


def _load_legacy_history() -> dict[str, Any]:
    raw = LEGACY_OVERLAY_PATH.read_bytes()
    if _sha256_bytes(raw) != EXPECTED_LEGACY_OVERLAY_SHA256:
        raise ValueError("legacy 700 overlay SHA mismatch")
    value = _read_json(raw, "legacy 700 overlay")
    records = value.get("records")
    ids = [record.get("relation_id") for record in records] if isinstance(records, list) else []
    if len(ids) != 700 or len(set(ids)) != 700:
        raise ValueError("legacy 700 overlay history is incomplete")
    return {
        "sha256": EXPECTED_LEGACY_OVERLAY_SHA256,
        "record_count": len(ids),
        "relation_ids": ids,
        "source_package_sha256": value.get("source_package_sha256"),
        "retained_as_separate_history": True,
        "status_crosswalk": "NOT_ESTABLISHED",
    }


def _verify_source_rows(
    catalog: dict[str, Any],
    stock_fields: list[str],
    stock_rows: list[dict[str, str]],
    relation_fields: list[str],
    relation_rows: list[dict[str, str]],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    stock_original_count = 20
    relation_original_count = 60
    if len(stock_rows) != EXPECTED_STOCKS or len(relation_rows) != EXPECTED_RELATIONS:
        raise ValueError("package original stock or relation row count mismatch")
    if len(stock_fields) < stock_original_count or len(relation_fields) < relation_original_count:
        raise ValueError("package original field range is incomplete")

    stocks_by_code = {row["hk_code"]: row for row in catalog["stocks"]}
    source_stock_by_code: dict[str, dict[str, str]] = {}
    for index, source_row in enumerate(stock_rows, start=1):
        source_fields = {key: source_row[key] for key in stock_fields[:stock_original_count]}
        code = source_fields.get("代码")
        if source_fields.get("序号") != str(index) or code not in stocks_by_code or code in source_stock_by_code:
            raise ValueError("package original stock identity or order mismatch")
        if source_fields != stocks_by_code[code].get("source_record"):
            raise ValueError("package original stock fields differ from the immutable base catalog")
        source_stock_by_code[code] = source_fields

    relations_by_id = {row["source_record"].get("关系编号"): row for row in catalog["relations"]}
    source_relation_by_id: dict[str, dict[str, str]] = {}
    for index, source_row in enumerate(relation_rows, start=1):
        source_fields = {key: source_row[key] for key in relation_fields[:relation_original_count]}
        relation_id = source_fields.get("关系编号")
        base_row = relations_by_id.get(relation_id)
        if base_row is None or base_row["source_row"] != index or relation_id in source_relation_by_id:
            raise ValueError("package original relation identity or order mismatch")
        if source_fields != base_row.get("source_record"):
            raise ValueError("package original relation fields differ from the immutable base catalog")
        source_relation_by_id[relation_id] = source_fields
    if set(source_stock_by_code) != set(stocks_by_code) or set(source_relation_by_id) != set(relations_by_id):
        raise ValueError("package original identity coverage is incomplete")
    return source_stock_by_code, source_relation_by_id


def _manifest_entry(manifest_by_path: dict[str, dict[str, Any]], path: str, sha256: str | None = None) -> dict[str, Any]:
    entry = manifest_by_path.get(path)
    if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
        raise ValueError(f"source member is absent from manifest: {path}")
    if sha256 is not None and entry["sha256"] != sha256:
        raise ValueError(f"source member SHA differs from manifest: {path}")
    return {"path": path, "sha256": entry["sha256"], "bytes": entry["bytes"]}


def build_recovery_overlay(archive_path: Path | str = DEFAULT_ARCHIVE) -> dict[str, Any]:
    archive_path = Path(archive_path)
    if _sha256_file(archive_path) != EXPECTED_ARCHIVE_SHA256:
        raise ValueError("source ZIP SHA mismatch")
    intake = _verify_intake_receipt(EXPECTED_ARCHIVE_SHA256)
    catalog = _load_catalog()
    legacy_history = _load_legacy_history()

    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != 3638 or len(set(names)) != len(names) or "MANIFEST.json" not in names:
            raise ValueError("archive member count or identity mismatch")
        if any(not _safe_member_path(name) for name in names):
            raise ValueError("archive contains an unsafe member path")

        manifest_raw = archive.read("MANIFEST.json")
        manifest = _read_json(manifest_raw, "source manifest")
        manifest_rows = manifest.get("files")
        if not isinstance(manifest_rows, list) or len(manifest_rows) != 3637 or manifest.get("file_count") != 3637:
            raise ValueError("source manifest member count mismatch")
        manifest_by_path = {entry.get("path"): entry for entry in manifest_rows if isinstance(entry, dict)}
        if len(manifest_by_path) != 3637 or set(names) - {"MANIFEST.json"} != set(manifest_by_path):
            raise ValueError("archive and source manifest members differ")
        if manifest.get("uncompressed_bytes") != intake.get("manifest_content_bytes"):
            raise ValueError("source manifest uncompressed byte count mismatch")

        member_data: dict[str, bytes] = {}
        source_member_hashes: dict[str, dict[str, Any]] = {}
        for name in CURRENT_MEMBERS:
            raw = archive.read(name)
            entry = manifest_by_path.get(name)
            if not isinstance(entry, dict) or entry.get("bytes") != len(raw) or entry.get("sha256") != _sha256_bytes(raw):
                raise ValueError(f"current source member SHA/size mismatch: {name}")
            member_data[name] = raw
            source_member_hashes[name] = {"bytes": len(raw), "sha256": entry["sha256"]}

    stock_fields, stock_rows = _csv_rows(member_data[CURRENT_MEMBERS[0]], CURRENT_MEMBERS[0])
    relation_fields, relation_rows = _csv_rows(member_data[CURRENT_MEMBERS[1]], CURRENT_MEMBERS[1])
    _, source_relation_by_id = _verify_source_rows(
        catalog, stock_fields, stock_rows, relation_fields, relation_rows
    )

    _, summary_rows = _csv_rows(member_data["CURRENT/RELATION_SUMMARY_1003.csv"], "relation summary")
    _, layer_rows = _csv_rows(member_data["CURRENT/SIX_LAYERS_1003x6.csv"], "six-layer projection")
    _, field_rows = _csv_rows(member_data["CURRENT/FIELD_ASSESSMENTS_1003x7.csv"], "field assessment projection")
    _, open_rows = _csv_rows(member_data["CURRENT/OPEN_RELATIONS_221.csv"], "open relation inventory")
    _, no_edge_rows = _csv_rows(member_data["CURRENT/NO_ORIGINAL_B_RELATIONS_18.csv"], "no-edge stock inventory")
    _, unattempted_a_rows = _csv_rows(member_data["CURRENT/A_URL_OCCURRENCES_UNATTEMPTED_62.csv"], "unattempted A URL inventory")

    effective = _read_json(member_data["CURRENT/EFFECTIVE_RESEARCH_1003.json"], "effective research")
    version_precedence = _read_json(member_data["CURRENT/VERSION_PRECEDENCE.json"], "version precedence")
    acceptance_ledger = _read_json(member_data["CURRENT/ACCEPTANCE_LEDGER.json"], "acceptance ledger")
    metrics = _read_json(member_data["CURRENT/METRICS.json"], "current metrics")
    url_accounting = _read_json(member_data["CURRENT/ORIGINAL_URL_ACCESS_ACCOUNTING.json"], "URL access accounting")
    baseline_reference = _read_json(member_data["CURRENT/BASELINE_MANIFEST_REFERENCE.json"], "baseline manifest reference")

    effective_relations = effective.get("relations")
    if effective.get("count") != EXPECTED_RELATIONS or effective.get("unique_relation_count") != EXPECTED_RELATIONS:
        raise ValueError("effective research relation count mismatch")
    if not isinstance(effective_relations, list) or len(effective_relations) != EXPECTED_RELATIONS:
        raise ValueError("effective research relations are incomplete")
    if len(summary_rows) != EXPECTED_RELATIONS or len(layer_rows) != EXPECTED_RELATIONS * EXPECTED_SIX_LAYERS:
        raise ValueError("summary or six-layer row coverage mismatch")
    if len(field_rows) != EXPECTED_RELATIONS * EXPECTED_FIELD_ASSESSMENTS:
        raise ValueError("field assessment row coverage mismatch")

    summary_by_id = {row.get("relation_id"): row for row in summary_rows}
    if len(summary_by_id) != EXPECTED_RELATIONS:
        raise ValueError("summary relation identities are duplicated")
    layers_by_id: dict[str, list[dict[str, str]]] = {relation_id: [] for relation_id in summary_by_id}
    assessments_by_id: dict[str, list[dict[str, str]]] = {relation_id: [] for relation_id in summary_by_id}
    for row in layer_rows:
        relation_id = row.get("relation_id")
        if relation_id not in layers_by_id:
            raise ValueError("six-layer row references an unknown relation")
        try:
            json.loads(row["effective_layer_record"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("six-layer record JSON is malformed") from exc
        layers_by_id[relation_id].append(row)
    for row in field_rows:
        relation_id = row.get("relation_id")
        if relation_id not in assessments_by_id:
            raise ValueError("field assessment row references an unknown relation")
        try:
            json.loads(row["effective_field_assessment"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("field assessment JSON is malformed") from exc
        assessments_by_id[relation_id].append(row)

    counts = {"CLOSED_RESEARCH_SCOPE": 0, "CLOSED_EXCLUDED_SCOPE": 0, "OPEN": 0}
    records: list[dict[str, Any]] = []
    manifest_by_path = {entry["path"]: entry for entry in manifest["files"]}
    for index, effective_row in enumerate(effective_relations, start=1):
        relation_id = effective_row.get("relation_id")
        original = source_relation_by_id.get(relation_id)
        summary = summary_by_id.get(relation_id)
        if original is None or summary is None or relation_id != original.get("关系编号"):
            raise ValueError("effective research identity is not bound to the original relation")
        source_catalog_row = next(row for row in catalog["relations"] if row["source_row"] == index)
        if source_catalog_row["source_record"] != original or source_catalog_row["source_record"].get("asset_code") != summary.get("asset_code_original"):
            raise ValueError("effective research relation order or symbol binding mismatch")
        if (effective_row.get("original_B") != original or
                effective_row.get("effective_summary", {}).get("relation_id") != relation_id or
                summary.get("stock_code") != original.get("code") or
                summary.get("asset_code_original") != original.get("asset_code")):
            raise ValueError("effective research and original source fields disagree")
        if (summary.get("closure_status") != effective_row["effective_summary"].get("closure_status") or
                summary.get("primary_research_use") != effective_row["effective_summary"].get("primary_research_use")):
            raise ValueError("effective relation status disagrees with current summary")

        status = summary.get("closure_status")
        if status not in counts:
            raise ValueError("recovery closure status is unknown")
        counts[status] += 1
        if len(layers_by_id[relation_id]) != EXPECTED_SIX_LAYERS or len(assessments_by_id[relation_id]) != EXPECTED_FIELD_ASSESSMENTS:
            raise ValueError("recovery layer or field assessment count is invalid")

        provenance = effective_row.get("research_provenance")
        provenance_ref = _manifest_entry(manifest_by_path, provenance.get("path"), provenance.get("sha256"))
        if provenance.get("bytes") != provenance_ref["bytes"]:
            raise ValueError("effective research provenance byte count differs from manifest")
        summary_provenance_ref = _manifest_entry(
            manifest_by_path,
            summary.get("effective_research_file", ""),
            summary.get("effective_research_sha256"),
        )
        if (summary_provenance_ref["sha256"] != provenance_ref["sha256"] or
                summary_provenance_ref["bytes"] != provenance_ref["bytes"]):
            raise ValueError("effective summary provenance differs from relation provenance")
        effective_summary = effective_row.get("effective_summary", {})
        independent_reports = effective_summary.get("independent_acceptance_reports", [])
        if not isinstance(independent_reports, list):
            raise ValueError("independent acceptance report references are malformed")
        report_refs = []
        for report in independent_reports:
            report_ref = _manifest_entry(manifest_by_path, report.get("path", ""), report.get("sha256"))
            report_refs.append(report_ref)

        current_research = effective_row.get("effective_research")
        if not isinstance(current_research, dict) or current_research.get("relation_id") != relation_id:
            raise ValueError("full effective research record is absent or mismatched")
        for key, expected in {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }.items():
            if key in current_research and current_research[key] is not expected:
                raise ValueError("effective research safety state is invalid")
        if (effective_summary.get("prediction") != "UNTESTED" or
                effective_summary.get("historical_PIT") != "NOT_VALIDATED" or
                effective_summary.get("event_and_data_tests") != "NOT_RUN"):
            raise ValueError("effective research safety state is invalid")

        records.append({
            "relation_id": relation_id,
            "source_row": index,
            "hk_code": original["code"],
            "us_symbol": original["asset_code"],
            "source_original_fields": original,
            "original_B_canonical_sha256": effective_row["original_B_canonical_sha256"],
            "current_summary_csv_row": summary,
            "effective_summary": effective_summary,
            "acceptance": effective_row["acceptance"],
            "research_provenance": provenance_ref,
            "independent_report_provenance": report_refs,
            "effective_research": current_research,
            "six_layers": layers_by_id[relation_id],
            "field_assessments": assessments_by_id[relation_id],
        })

    if counts != {"CLOSED_RESEARCH_SCOPE": 757, "CLOSED_EXCLUDED_SCOPE": 25, "OPEN": 221}:
        raise ValueError(f"current closure status counts mismatch: {counts}")
    if [row["relation_id"] for row in records] != [row["source_record"].get("关系编号") for row in catalog["relations"]]:
        raise ValueError("effective relation order differs from the immutable base catalog")

    metrics_expected = {
        "processed_original_relations": EXPECTED_RELATIONS,
        "involved_original_stocks": 649,
        "all_original_edges_processed_stocks": 649,
        "bounded_research_closed": 757,
        "excluded_scope_closed": 25,
        "explicit_closed_total": 782,
        "accepted_open_relations": 221,
        "remaining_original_relations": 0,
        "original_A_stocks": EXPECTED_STOCKS,
        "stocks_without_original_B_relations": 18,
        "A_URL_occurrences_without_attempt": 62,
        "prediction": "UNTESTED",
        "historical_PIT": "NOT_VALIDATED",
        "event_and_data_tests": "NOT_RUN",
        "company_independent_acceptance": 0,
        "production_allowed": False,
        "orders_sent": False,
    }
    if any(metrics.get(key) != value for key, value in metrics_expected.items()):
        raise ValueError("current package metrics disagree with frozen acceptance counts")
    if (len(open_rows) != 221 or {row.get("relation_id") for row in open_rows} !=
            {row["relation_id"] for row in records if row["effective_summary"]["closure_status"] == "OPEN"}):
        raise ValueError("open relation inventory differs from current effective status")
    no_edge_codes = {row.get("代码") for row in no_edge_rows}
    if len(no_edge_codes) != 18 or no_edge_codes != set(catalog["coverage"]["stocks_without_relations"]):
        raise ValueError("no-original-relation inventory differs from immutable base catalog")
    if len(unattempted_a_rows) != 62 or metrics.get("A_URL_occurrences_without_attempt") != len(unattempted_a_rows):
        raise ValueError("unattempted A URL inventory count mismatch")

    ledger_metrics = acceptance_ledger.get("metrics", {})
    ledger_metric_keys = (
        "processed_original_relations", "involved_original_stocks",
        "all_original_edges_processed_stocks", "bounded_research_closed",
        "excluded_scope_closed", "explicit_closed_total", "accepted_open_relations",
        "remaining_original_relations",
    )
    if any(ledger_metrics.get(key) != metrics_expected[key] for key in ledger_metric_keys):
        raise ValueError("acceptance ledger metrics disagree with the current package")
    if url_accounting.get("A_occurrences_without_recorded_exact_URL_attempt") != 62:
        raise ValueError("URL access accounting no longer binds the 62 A URL gap")

    overlay: dict[str, Any] = {
        "schema_version": OVERLAY_SCHEMA,
        "overlay_id": "us_hk_667_1003_recovery_v2r1_20261016",
        "base_catalog_sha256": EXPECTED_BASE_CATALOG_SHA256,
        "source_package_sha256": EXPECTED_ARCHIVE_SHA256,
        "source_archive_name": archive_path.name,
        "source_manifest_sha256": _sha256_bytes(manifest_raw),
        "source_manifest_member_count": 3637,
        "source_manifest_content_bytes": manifest["uncompressed_bytes"],
        "source_member_hashes": source_member_hashes,
        "prior_700_history": legacy_history,
        "counts": {
            "snapshot_stocks": EXPECTED_STOCKS,
            "original_relations": EXPECTED_RELATIONS,
            "processed_relations": len(records),
            "closure_status_counts": counts,
            "research_scope_closed": counts["CLOSED_RESEARCH_SCOPE"],
            "excluded_scope_closed": counts["CLOSED_EXCLUDED_SCOPE"],
            "closed_total_including_exclusions": counts["CLOSED_RESEARCH_SCOPE"] + counts["CLOSED_EXCLUDED_SCOPE"],
            "open_relations": counts["OPEN"],
            "stocks_with_relations": 649,
            "stocks_without_relations": 18,
            "company_independent_acceptance": 0,
        },
        "research_safety": {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "fact_validation": "INDEPENDENT_ACCEPTANCE_0",
            "prediction_validation": "UNTESTED",
            "historical_PIT": "NOT_VALIDATED",
            "event_and_data_tests": "NOT_RUN",
            "semantic_mapping_validity": "CANNOT_CONFIRM",
        },
        "evidence_limits": {
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
        },
        "package_url_access_accounting": url_accounting,
        "version_precedence": version_precedence,
        "version_precedence_source_member": "CURRENT/VERSION_PRECEDENCE.json",
        "baseline_manifest_reference": baseline_reference,
        "projection_rule": (
            "closure_status and primary_research_use are exposed exactly as the current v2r1 fields; "
            "they are not crosswalked from the separate legacy 700 overlay research_use values."
        ),
        "records": records,
    }
    overlay["integrity_sha256"] = _sha256_bytes(canonical_bytes(overlay))
    return overlay


def write_overlay(overlay: dict[str, Any], output_path: Path | str = DEFAULT_OUTPUT) -> str:
    output_path = Path(output_path)
    raw = canonical_bytes(overlay) + b"\n"
    output_path.write_bytes(raw)
    return _sha256_bytes(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", default=str(DEFAULT_ARCHIVE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    overlay = build_recovery_overlay(args.archive)
    digest = write_overlay(overlay, args.output)
    print(json.dumps({
        "output": str(Path(args.output)),
        "bytes": Path(args.output).stat().st_size,
        "sha256": digest,
        "integrity_sha256": overlay["integrity_sha256"],
        "records": len(overlay["records"]),
        "closure_status_counts": overlay["counts"]["closure_status_counts"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
