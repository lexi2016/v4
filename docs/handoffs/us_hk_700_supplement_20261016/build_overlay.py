"""Build the source-reviewed 700-relation overlay from the received supplement.

The archive is treated as data. No archive scripts are executed. The prior 220
overlay is pinned as a byte-for-byte preimage so the refreshed source package
cannot erase the earlier evidence wording or revision snapshot.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[3]
SUPPLEMENT_SHA256 = "2894b3bca475965aa3553977a654b10fa4c6750bbcb80f70f1bea17bdde649b0"
UPSTREAM_700_PACKAGE_SHA256_CLAIM = "589dd772..."
BASE_CATALOG_SHA256 = "3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671"
PRIOR_220_OVERLAY_SHA256 = "72a0f074e6412036cd103c7f73ccf15230eb3d1633c09742c88653b863eba384"
MANIFEST_SHA256 = "8ba8ea7ef7c351bcd5a1b72ad8f449b7acf555a54a172ea66084248f28e26ab9"
SUBTREE = "700/deliverable_batch35"
PREFIX = SUBTREE + "/"
OUTPUT = ROOT / "v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json"
BASE_CATALOG = ROOT / "v4/manager_workbench/research_data/us_hk_667_catalog_20261015.json"
PRIOR_OVERLAY = ROOT / "docs/handoffs/us_hk_700_supplement_20261016/preimage/us_hk_667_review_overlay_20261015.json"

# Preserve the existing exact-state routing rule. New states remain pending by
# default; they do not become accepted facts or predictions by wording similarity.
BACKGROUND = {
    "CONTEXT_ONLY_NO_DIRECT_ECONOMIC_LINK_PROVEN",
    "CONTEXT_ONLY_NO_DIRECT_LINK_CONFIRMED",
    "BACKGROUND_MACRO_ONLY_NO_DIRECT_RELATION_VERIFIED",
    "CONTEXT_ONLY_CURRENT_SEGMENT_COMPARISON",
    "CONTEXT_ONLY_MACRO_NET_SENSITIVITY_UNCONFIRMED",
    "CONTEXT_ONLY_CURRENT_PROPERTY_COMPARISON",
    "LIMITED_CONTEXT_AFTER_ASSET_DISPOSAL",
    "WEAK_MACRO_CONTEXT_ONLY",
}
EXCLUDED = {
    "EXCLUDED_CURRENT_OLD_SECURITY",
    "EXCLUDED_CURRENT_HISTORICAL_ADS",
    "EXCLUDED_CURRENT_HISTORICAL_ADR",
    "ORIGINAL_49_PERCENT_EQUITY_BRIDGE_ENDED_2026_07_30",
}
CONDITIONAL = {
    "CURRENT_DOCUMENTARY_MAPPING_SUPPORTED_EXECUTABILITY_PENDING",
    "CONDITIONAL_MACRO_OBSERVATION_ONLY",
    "SUPPORTED_AT_2026_H1_CURRENT_WEBSITE_CORROBORATED_PRECISE_OCTOBER_CAPITAL_PENDING",
}
EXPECTED_RESEARCH_USES = {
    "PENDING_REVIEW": 682,
    "BACKGROUND_HISTORICAL": 10,
    "EXCLUDED_CURRENT": 5,
    "CONDITIONAL_OBSERVATION": 3,
}


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _read_csv(archive: ZipFile, name: str) -> list[dict[str, str]]:
    raw = archive.read(PREFIX + name)
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def _parse_json_field(value: str, field: str, issues: list[dict]) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        issues.append({
            "field": field,
            "issue": "INVALID_JSON_PRESERVED_AS_SOURCE_TEXT",
            "error_type": "JSONDecodeError",
            "raw_sha256": _sha256_bytes(value.encode("utf-8")),
            "raw_characters": len(value),
        })
        return value


def _use_for_state(state: str) -> str:
    if state in EXCLUDED:
        return "EXCLUDED_CURRENT"
    if state in BACKGROUND:
        return "BACKGROUND_HISTORICAL"
    if state in CONDITIONAL:
        return "CONDITIONAL_OBSERVATION"
    return "PENDING_REVIEW"


def _validate_archive(archive: ZipFile) -> tuple[dict, dict[str, str]]:
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("duplicate ZIP member")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("unsafe ZIP member path")
    bad_member = archive.testzip()
    if bad_member is not None:
        raise ValueError(f"ZIP CRC failed: {bad_member}")

    manifest_path = PREFIX + "DELIVERABLE_MANIFEST.json"
    manifest_raw = archive.read(manifest_path)
    if _sha256_bytes(manifest_raw) != MANIFEST_SHA256:
        raise ValueError("700 subtree manifest SHA mismatch")
    manifest = json.loads(manifest_raw)
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != 394:
        raise ValueError("700 subtree manifest coverage mismatch")
    expected_members = set()
    member_hashes = {}
    for entry in entries:
        relative = entry.get("file")
        if not isinstance(relative, str):
            raise ValueError("manifest member path is invalid")
        member_path = PurePosixPath(relative)
        if member_path.is_absolute() or ".." in member_path.parts or "\\" in relative:
            raise ValueError("unsafe manifest member path")
        expected_members.add(PREFIX + relative)
        raw = archive.read(PREFIX + relative)
        if len(raw) != entry.get("bytes") or _sha256_bytes(raw) != entry.get("sha256"):
            raise ValueError(f"manifest member identity mismatch: {relative}")
        member_hashes[relative] = entry["sha256"]
    actual_subtree_members = {name for name in names if name.startswith(PREFIX)}
    if actual_subtree_members != expected_members | {manifest_path}:
        raise ValueError("700 subtree manifest member set mismatch")
    return manifest, member_hashes


def _validate_original_rows(archive: ZipFile, base: dict) -> None:
    main = _read_csv(archive, "01A_full_667_original_plus_revision.csv")
    revised = _read_csv(archive, "01B_full_1003_original_plus_revision.csv")
    if len(main) != 667 or len(revised) != 1003:
        raise ValueError("original source row count mismatch")
    for old, new in zip(base["stocks"], main):
        if any(new.get(key) != value for key, value in old["source_record"].items()):
            raise ValueError("original stock field changed")
    for old, new in zip(base["relations"], revised):
        if any(new.get(key) != value for key, value in old["source_record"].items()):
            raise ValueError("original relation field changed")


def _validate_prior_220(records: list[dict], prior: dict) -> dict:
    previous = {row["relation_id"]: row for row in prior.get("records", [])}
    current = {row["relation_id"]: row for row in records}
    if len(previous) != 220 or not set(previous).issubset(current):
        raise ValueError("prior 220 relation coverage was not retained")

    prior_evidence_occurrences = 0
    current_evidence_occurrences = 0
    evidence_growth_relations = 0
    for relation_id, old in previous.items():
        new = current[relation_id]
        if (old["source_current_state"] != new["source_current_state"] or
                old["revision"].get("revision_research_fact_state") !=
                new["revision"].get("revision_research_fact_state") or
                old["revision"].get("revision_current_applicability_state") !=
                new["revision"].get("revision_current_applicability_state") or
                old["revision"].get("revision_field_assessments_json") !=
                new["revision"].get("revision_field_assessments_json")):
            raise ValueError(f"prior 220 review state changed: {relation_id}")
        old_ids = {item["evidence_id"] for item in old.get("evidence", [])}
        new_ids = {item["evidence_id"] for item in new.get("evidence", [])}
        if not old_ids.issubset(new_ids):
            raise ValueError(f"prior evidence reference was dropped: {relation_id}")
        old_count = len(old.get("evidence", []))
        new_count = len(new.get("evidence", []))
        prior_evidence_occurrences += old_count
        current_evidence_occurrences += new_count
        evidence_growth_relations += new_count > old_count

    evidence_delta = current_evidence_occurrences - prior_evidence_occurrences
    if (prior_evidence_occurrences != 1831 or evidence_delta != 100 or
            evidence_growth_relations != 51):
        raise ValueError("prior 220 evidence delta does not match the supplied audit")
    return {
        "prior_overlay_sha256": PRIOR_220_OVERLAY_SHA256,
        "prior_relation_count": len(previous),
        "prior_evidence_occurrences": prior_evidence_occurrences,
        "current_evidence_occurrences_for_prior_relations": current_evidence_occurrences,
        "prior_evidence_occurrence_delta": evidence_delta,
        "prior_relations_with_added_evidence": evidence_growth_relations,
        "prior_states_and_field_assessments_preserved": True,
        "prior_evidence_ids_preserved_by_relation": True,
        "prior_overlay_preimage": "preimage/us_hk_667_review_overlay_20261015.json",
    }


def build(zip_path: Path) -> dict:
    zip_path = Path(zip_path)
    if _sha256_file(zip_path) != SUPPLEMENT_SHA256:
        raise ValueError("source supplement SHA mismatch")
    if _sha256_file(BASE_CATALOG) != BASE_CATALOG_SHA256:
        raise ValueError("base catalog SHA mismatch")
    if _sha256_file(PRIOR_OVERLAY) != PRIOR_220_OVERLAY_SHA256:
        raise ValueError("prior 220 overlay preimage SHA mismatch")

    base = json.loads(BASE_CATALOG.read_bytes())
    prior = json.loads(PRIOR_OVERLAY.read_bytes())
    with ZipFile(zip_path) as archive:
        manifest, source_members = _validate_archive(archive)
        _validate_original_rows(archive, base)

        revised = _read_csv(archive, "01B_full_1003_original_plus_revision.csv")
        processed = _read_csv(archive, "04_cumulative_results.csv")
        evidence = _read_csv(archive, "03_evidence_by_url.csv")
        summaries = {row["relation_id"]: row for row in _read_csv(
            archive, "11_cumulative_processed_relation_summary.csv"
        )}
        if len(processed) != 700 or len({row["关系编号"] for row in processed}) != 700:
            raise ValueError("source-reviewed relation count mismatch")
        if len(summaries) != 700:
            raise ValueError("source summary relation coverage mismatch")

        relation_to_source = {row["source_record"].get("关系编号"): row for row in base["relations"]}
        decoded_evidence_relations = {}
        for item in evidence:
            try:
                relation_ids = json.loads(item["relation_ids_json"])
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError("evidence relation_ids_json is invalid") from exc
            if not isinstance(relation_ids, list) or not all(isinstance(value, str) for value in relation_ids):
                raise ValueError("evidence relation_ids_json is not a string list")
            decoded_evidence_relations[id(item)] = set(relation_ids)

        records = []
        revision_parse_issue_count = 0
        for row in processed:
            relation_id = row["关系编号"]
            source_row = int(relation_id[1:])
            original = relation_to_source.get(relation_id)
            if (original is None or original["source_row"] != source_row or
                    original["source_record"].get("code") != row["code"] or
                    original["us_symbol"] != row["asset_code"]):
                raise ValueError(f"review relation identity mismatch: {relation_id}")
            if row != revised[source_row - 1]:
                raise ValueError(f"cumulative revision differs from full table: {relation_id}")

            revision_parse_issues = []
            revision = {}
            for key, value in row.items():
                if key.startswith("revision_"):
                    revision[key] = _parse_json_field(value, key, revision_parse_issues) if key.endswith("_json") else value
            revision_parse_issue_count += len(revision_parse_issues)
            if (revision.get("revision_event_validation_state") != "NOT_RUN" or
                    revision.get("revision_prediction_validation_state") != "UNTESTED" or
                    revision.get("revision_historical_PIT_state") != "NOT_VALIDATED" or
                    revision.get("revision_independent_local_review_state") != "NOT_RUN" or
                    revision.get("revision_RESEARCH_ONLY") != "true" or
                    revision.get("revision_production_allowed") != "false" or
                    revision.get("revision_buy_gate_updated") != "false" or
                    revision.get("revision_orders_sent") != "false"):
                raise ValueError(f"research-only revision flags changed: {relation_id}")

            evidence_ids = revision.get("revision_evidence_ids_json")
            if not isinstance(evidence_ids, list) or not all(isinstance(value, str) for value in evidence_ids):
                raise ValueError(f"revision evidence IDs are invalid: {relation_id}")
            evidence_id_set = set(evidence_ids)
            linked = [
                item for item in evidence
                if item["evidence_id"] in evidence_id_set and relation_id in decoded_evidence_relations[id(item)]
            ]
            if evidence_id_set != {item["evidence_id"] for item in linked}:
                raise ValueError(f"missing referenced review evidence: {relation_id}")

            summary_raw = summaries.get(relation_id)
            if (summary_raw is None or summary_raw["code"] != row["code"] or
                    summary_raw["asset_code_original"] != row["asset_code"]):
                raise ValueError(f"review summary identity mismatch: {relation_id}")
            summary_parse_issues = []
            summary = {}
            plain_text_json_fields = []
            for key, value in summary_raw.items():
                if key.endswith("_json") and value:
                    parsed = _parse_json_field(value, key, summary_parse_issues)
                    summary[key] = parsed
                    if isinstance(parsed, str):
                        plain_text_json_fields.append(key)
                else:
                    summary[key] = value
            sidecar_ids = summary.get("all_sidecar_evidence_ids_json", [])
            addendum_ids = summary.get("subsequent_revision_evidence_ids_json", [])
            if not isinstance(sidecar_ids, list) or not isinstance(addendum_ids, list):
                raise ValueError(f"review summary evidence IDs are invalid: {relation_id}")
            extra_ids = set(sidecar_ids) | set(addendum_ids)
            extra = [item for item in evidence if item["evidence_id"] in extra_ids and item not in linked]
            summary["source_plain_text_json_fields"] = plain_text_json_fields
            summary["source_json_parse_issues"] = summary_parse_issues

            state = revision["revision_current_applicability_state"]
            records.append({
                "relation_id": relation_id,
                "source_row": source_row,
                "hk_code": row["code"],
                "us_symbol": row["asset_code"],
                "source_review_status": "SOURCE_REVIEWED",
                "independent_verification": "NOT_RUN",
                "research_use": _use_for_state(state),
                "use_rule": "exact_current_state_v1",
                "source_current_state": state,
                "revision": revision,
                "revision_json_parse_issues": revision_parse_issues,
                "evidence": linked + extra,
                "source_summary": summary,
            })

        records.sort(key=lambda record: record["source_row"])
        if len(records) != 700 or len({record["relation_id"] for record in records}) != 700:
            raise ValueError("overlay relation coverage mismatch")
        use_counts = {key: 0 for key in EXPECTED_RESEARCH_USES}
        for record in records:
            use_counts[record["research_use"]] += 1
        if use_counts != EXPECTED_RESEARCH_USES:
            raise ValueError(f"research-use projection mismatch: {use_counts}")
        if revision_parse_issue_count != 60:
            raise ValueError(f"revision JSON parse issue count mismatch: {revision_parse_issue_count}")
        if any(
            issue["field"] != "revision_failure_checks_json"
            for record in records for issue in record["revision_json_parse_issues"]
        ):
            raise ValueError("unexpected revision JSON parse issue field")

        prior_preservation = _validate_prior_220(records, prior)
        result = {
            "schema_version": "v4.us_hk_mapping_review_overlay.v1",
            "source_package_sha256": SUPPLEMENT_SHA256,
            "source_package_kind": "combined_560_700_supplement",
            "source_subtree": SUBTREE,
            "upstream_original_700_package": {
                "claimed_sha256": UPSTREAM_700_PACKAGE_SHA256_CLAIM,
                "received_locally": False,
                "local_sha256_verified": False,
            },
            "base_catalog_sha256": BASE_CATALOG_SHA256,
            "source_generated_at_utc": manifest["generated_at_utc"],
            "manifest_sha256": MANIFEST_SHA256,
            "source_members": source_members,
            "prior_220_preservation": prior_preservation,
            "projection_rule": {
                "id": "exact_current_state_v1",
                "meaning": "Research use only; source states are not independent acceptance.",
                "BACKGROUND_HISTORICAL": sorted(BACKGROUND),
                "EXCLUDED_CURRENT": sorted(EXCLUDED),
                "CONDITIONAL_OBSERVATION": sorted(CONDITIONAL),
                "default": "PENDING_REVIEW",
            },
            "research_safety": {
                "RESEARCH_ONLY": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
                "prediction_validation": "UNTESTED",
                "historical_PIT": "NOT_VALIDATED",
                "event_validation": "NOT_RUN",
                "independent_local_review": "NOT_RUN",
            },
            "records": records,
        }
        result["integrity_sha256"] = _sha256_bytes(_canonical_bytes(result))
        return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--zip", type=Path,
        default=Path("/Users/lexi/Downloads/US_HK_560_700_完整补件_20261015.zip"),
    )
    args = parser.parse_args()
    overlay = build(args.zip)
    encoded = json.dumps(overlay, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    OUTPUT.write_text(encoded, encoding="utf-8")
    output_sha = _sha256_file(OUTPUT)
    print(json.dumps({
        "source_package_sha256": overlay["source_package_sha256"],
        "manifest_sha256": overlay["manifest_sha256"],
        "records": len(overlay["records"]),
        "research_use_counts": EXPECTED_RESEARCH_USES,
        "prior_220_preservation": overlay["prior_220_preservation"],
        "revision_json_parse_issues": sum(len(r["revision_json_parse_issues"]) for r in overlay["records"]),
        "evidence_occurrences": sum(len(r["evidence"]) for r in overlay["records"]),
        "integrity_sha256": overlay["integrity_sha256"],
        "overlay_file_sha256": output_sha,
    }, ensure_ascii=False, sort_keys=True))
