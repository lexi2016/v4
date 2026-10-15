#!/usr/bin/env python3
"""Rebuild the source-bound US-to-HK catalog from the supplied ZIP, fail-closed."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile
from collections import Counter, defaultdict
from typing import Any
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[3]
ZIP_SHA256 = "dac3c820fcd6919fabdccc9c37ee9055b729b200fcde5e48f0dcf527de81bc6d"
MEMBERSHIP_SHA256 = "9b799c0b74ac5047f4e44a1b3dfd1dfa5ca9ce978fa3b8e7877913c423424c9c"
ZIP_DEFAULT = Path("/Users/lexi/Downloads/逐股审核_001-667_实际研究结果.zip")
MEMBERSHIP_DEFAULT = REPO / "docs/handoffs/hk_connect_list_20261014/港股通股票名单_667只_20261014.csv"
CATALOG_PATH = REPO / "v4/manager_workbench/research_data/us_hk_667_catalog_20261015.json"
RECEIPT_PATH = Path(__file__).resolve().parent / "source_audit.json"
SAFETY = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
    "prediction_validation": "UNTESTED",
    "historical_PIT": "NOT_VALIDATED",
}
EXPECTED_FILES = {
    "667只逐股审核报告.md",
    "FILE_MANIFEST.json",
    "README.md",
    "主表A_667只逐股结论.csv",
    "主表A_667只逐股结论.xlsx",
    "主表B_逐关系明细.csv",
    "主表B_逐关系明细.xlsx",
    "删除降级与缺口.csv",
    "剩余代码与断点.txt",
    "机器检查结果.json",
    "研究行业覆盖统计.csv",
    "行业与美国资产对应.csv",
    "行业与美国资产对应.xlsx",
    "覆盖与待办.csv",
    "阅读与更正说明.md",
}
EXPECTED_CLASSES = {
    "已审有具体关系候选": 410,
    "已审仅弱观察关系": 218,
    "已审无可靠关系": 30,
    "已审候选证据不足": 9,
}
REPORT_HEADING = re.compile(r"^#{1,4}\s*(\d+)\s*/\s*667\s*[｜|]\s*([0-9]{5})\s*[｜|]\s*(.*)$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def csv_rows(data: bytes, filename: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        headers = reader.fieldnames or []
        if not headers or len(headers) != len(set(headers)):
            raise ValueError(f"{filename}: invalid or duplicate headers")
        result = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{filename}: row contains an unmatched field")
            result.append(row)
        return headers, result
    except (UnicodeError, csv.Error) as exc:
        raise ValueError(f"{filename}: invalid UTF-8 CSV") from exc


def workbook_rows(data: bytes, filename: str) -> list[list[str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as workbook:
            sheet_xml = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
            shared_xml = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError(f"{filename}: workbook cannot be parsed") from exc
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared = ["".join(text.text or "" for text in item.findall(".//x:t", ns))
              for item in shared_xml.findall("x:si", ns)]

    def column_number(reference: str) -> int:
        letters = re.match(r"[A-Z]+", reference)
        if letters is None:
            raise ValueError(f"{filename}: invalid worksheet cell reference")
        value = 0
        for char in letters.group(0):
            value = value * 26 + ord(char) - ord("A") + 1
        return value

    content: dict[int, dict[int, str]] = {}
    max_column = 0
    for row in sheet_xml.findall(".//x:sheetData/x:row", ns):
        row_number = int(row.attrib["r"])
        cells: dict[int, str] = {}
        for cell in row.findall("x:c", ns):
            column = column_number(cell.attrib.get("r", ""))
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value = "".join(text.text or "" for text in cell.findall(".//x:t", ns))
            else:
                node = cell.find("x:v", ns)
                raw_value = "" if node is None or node.text is None else node.text
                if cell_type == "s":
                    shared_index = int(raw_value)
                    value = shared[shared_index]
                else:
                    value = raw_value
            cells[column] = value
            max_column = max(max_column, column)
        content[row_number] = cells
    if not content:
        raise ValueError(f"{filename}: workbook sheet is empty")
    return [[content.get(row, {}).get(column, "") for column in range(1, max_column + 1)]
            for row in range(1, max(content) + 1)]


def assert_workbook_equal(csv_data: bytes, xlsx_data: bytes, csv_name: str, xlsx_name: str) -> None:
    _, records = csv_rows(csv_data, csv_name)
    matrix = workbook_rows(xlsx_data, xlsx_name)
    expected = []
    if records:
        headers = list(records[0])
        expected.append(headers)
        expected.extend([[row.get(header, "") for header in headers] for row in records])
    if len(matrix) != len(expected):
        raise ValueError(f"{xlsx_name}: row count differs from {csv_name}")

    def values_equal(left: str, right: str) -> bool:
        if left == right:
            return True
        if left.casefold() in {"true", "false"} and left.casefold() == right.casefold():
            return True
        try:
            return json.loads(left) == json.loads(right)
        except (json.JSONDecodeError, TypeError):
            return False

    for row_no, (actual, wanted) in enumerate(zip(matrix, expected), start=1):
        actual = actual[:len(wanted)]
        if len(actual) < len(wanted):
            actual += [""] * (len(wanted) - len(actual))
        if any(not values_equal(left, right) for left, right in zip(actual, wanted)):
            raise ValueError(f"{xlsx_name}: values differ from {csv_name} at row {row_no}")


def load_membership(path: Path) -> tuple[list[dict[str, str]], str]:
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    if digest != MEMBERSHIP_SHA256:
        raise ValueError(f"membership SHA mismatch: {digest}")
    headers, rows = csv_rows(raw, path.name)
    required = {"港股代码", "中文简称", "英文简称", "品种", "名单更新日期"}
    if not required.issubset(headers) or len(rows) != 667:
        raise ValueError("membership schema or row count mismatch")
    codes = [row["港股代码"] for row in rows]
    if any(re.fullmatch(r"[0-9]{5}", code) is None for code in codes) or len(codes) != len(set(codes)):
        raise ValueError("membership contains an invalid or duplicate HK code")
    if any(row["名单更新日期"] != "2026-10-14" for row in rows):
        raise ValueError("membership contains an unexpected snapshot date")
    return rows, digest


def load_package(path: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    raw_zip = path.read_bytes()
    zip_sha = sha256_bytes(raw_zip)
    if zip_sha != ZIP_SHA256:
        raise ValueError(f"source ZIP SHA mismatch: {zip_sha}")
    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise ValueError(f"ZIP CRC failure: {bad}")
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != EXPECTED_FILES:
                raise ValueError("ZIP file list differs from the frozen 15-file package")
            for name in names:
                item = PurePosixPath(name)
                if item.is_absolute() or len(item.parts) != 1 or any(part in {"", ".", ".."} for part in item.parts):
                    raise ValueError(f"unsafe ZIP member path: {name}")
            content = {name: archive.read(name) for name in names}
    except zipfile.BadZipFile as exc:
        raise ValueError("source ZIP is damaged") from exc

    try:
        manifest = json.loads(content["FILE_MANIFEST.json"].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("source manifest is invalid") from exc
    manifest_rows = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(manifest_rows, list):
        raise ValueError("source manifest has no file list")
    expected_manifest_names = EXPECTED_FILES - {"FILE_MANIFEST.json"}
    actual_manifest_names = [item.get("name") for item in manifest_rows if isinstance(item, dict)]
    if len(actual_manifest_names) != len(manifest_rows) or set(actual_manifest_names) != expected_manifest_names or len(actual_manifest_names) != len(set(actual_manifest_names)):
        raise ValueError("source manifest coverage is invalid")
    for item in manifest_rows:
        data = content[item["name"]]
        if item.get("bytes") != len(data) or item.get("sha256") != sha256_bytes(data):
            raise ValueError(f"source manifest digest mismatch: {item.get('name')}")
    details = {
        "package_name": path.name,
        "package_sha256": zip_sha,
        "zip_crc": "PASS",
        "manifest": "PASS",
        "member_count": len(names),
        "files": [
            {"name": name, "bytes": len(content[name]), "sha256": sha256_bytes(content[name])}
            for name in sorted(names)
        ],
    }
    return content, details


def validate_report_sections(markdown: str, membership: list[dict[str, str]]) -> list[dict[str, Any]]:
    headings = []
    for line in markdown.splitlines():
        match = REPORT_HEADING.match(line)
        if match:
            headings.append({"ordinal": int(match.group(1)), "hk_code": match.group(2), "label": match.group(3).strip()})
    expected = [{"ordinal": i, "hk_code": row["港股代码"], "name": row["中文简称"]}
                for i, row in enumerate(membership, start=1)]
    if len(headings) != len(expected) or any(
        actual["ordinal"] != wanted["ordinal"] or actual["hk_code"] != wanted["hk_code"]
        or actual["label"] != wanted["name"]
        for actual, wanted in zip(headings, expected)
    ):
        raise ValueError("report chapter headings do not exactly match roster order")
    return headings


def build_catalog(zip_path: Path, membership_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    membership, membership_sha = load_membership(membership_path)
    package, package_receipt = load_package(zip_path)
    report = package["667只逐股审核报告.md"].decode("utf-8-sig")
    headings = validate_report_sections(report, membership)
    _, rows_a = csv_rows(package["主表A_667只逐股结论.csv"], "主表A_667只逐股结论.csv")
    _, rows_b = csv_rows(package["主表B_逐关系明细.csv"], "主表B_逐关系明细.csv")
    _, coverage_rows = csv_rows(package["覆盖与待办.csv"], "覆盖与待办.csv")
    if len(rows_a) != 667 or len(rows_b) != 1003 or len(coverage_rows) != 667:
        raise ValueError("A/B/coverage row counts differ from the frozen source contract")
    assert_workbook_equal(package["主表A_667只逐股结论.csv"], package["主表A_667只逐股结论.xlsx"], "主表A_667只逐股结论.csv", "主表A_667只逐股结论.xlsx")
    assert_workbook_equal(package["主表B_逐关系明细.csv"], package["主表B_逐关系明细.xlsx"], "主表B_逐关系明细.csv", "主表B_逐关系明细.xlsx")

    roster = {row["港股代码"]: row for row in membership}
    a_codes = [row.get("代码", "") for row in rows_a]
    if a_codes != [row["港股代码"] for row in membership]:
        raise ValueError("main table A codes or order differ from membership roster")
    for membership_row, row_a in zip(membership, rows_a):
        if row_a.get("名称", "") != membership_row["中文简称"]:
            raise ValueError(f"main table A name mismatch for {membership_row['港股代码']}")
        if row_a.get("名单日期", "") != "2026-10-14":
            raise ValueError(f"main table A date mismatch for {membership_row['港股代码']}")
    coverage_codes = [row.get("代码", "") for row in coverage_rows]
    if coverage_codes != a_codes:
        raise ValueError("coverage table codes or order differ from main table A")
    if any(row.get("研究进度") != "REVIEWED" for row in rows_a):
        raise ValueError("source main table A has an unexpected progress status")
    if any(row.get("预测状态") != "UNTESTED" for row in rows_a):
        raise ValueError("source main table A has an unexpected prediction state")
    class_counts = dict(Counter(row.get("关系分类", "") for row in rows_a))
    if class_counts != EXPECTED_CLASSES:
        raise ValueError(f"source relation classification counts differ: {class_counts}")
    if any(row.get("prediction") != "UNTESTED" or row.get("historical_PIT") != "NOT_VALIDATED" for row in rows_b):
        raise ValueError("source relation prediction or PIT state differs from the frozen safety state")

    relations_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    relations = []
    for source_row, raw in enumerate(rows_b, start=1):
        code = raw.get("code", "")
        if code not in roster:
            raise ValueError(f"relation row {source_row} references a code outside the membership roster")
        relations_by_code[code].append(raw)
        relations.append({
            "source_row": source_row,
            "hk_code": code,
            "us_symbol": raw.get("asset_code", ""),
            "source_record": raw,
            "fact_review_status": "PENDING",
            "prediction_eligible": False,
            "prediction_validation": "UNTESTED",
            "historical_PIT": "NOT_VALIDATED",
        })

    stocks = []
    for ordinal, (membership_row, raw) in enumerate(zip(membership, rows_a), start=1):
        code = membership_row["港股代码"]
        ids = [relation.get("relation_id", "") for relation in relations_by_code.get(code, []) if relation.get("relation_id", "")]
        stocks.append({
            "ordinal": ordinal,
            "hk_code": code,
            "name": membership_row["中文简称"] or None,
            "english_name": membership_row["英文简称"] or None,
            "membership_record": membership_row,
            "source_record": raw,
            "relation_count": len(relations_by_code.get(code, [])),
            "relation_ids": ids,
            "fact_review_status": "PENDING",
        })

    relation_codes = set(relations_by_code)
    raw_machine_claims = json.loads(package["机器检查结果.json"].decode("utf-8-sig"))
    report_readme = package["README.md"].decode("utf-8-sig")
    coverage = {
        "membership_count": len(membership),
        "main_table_a_rows": len(rows_a),
        "main_table_a_unique_codes": len(set(a_codes)),
        "main_table_a_order_matches_membership": True,
        "main_table_a_names_match_membership": True,
        "coverage_table_rows": len(coverage_rows),
        "coverage_table_order_matches_membership": True,
        "report_sections": len(headings),
        "report_section_order_matches_membership": True,
        "report_section_names_match_membership": True,
        "relation_row_count": len(relations),
        "relation_rows_reference_membership": True,
        "stocks_with_relations": len(relation_codes),
        "stocks_without_relations": [stock["hk_code"] for stock in stocks if stock["hk_code"] not in relation_codes],
        "csv_workbook_value_equality": {"main_table_a": "PASS", "main_table_b": "PASS"},
        "source_relation_status_values": dict(Counter(row.get("status", "") for row in rows_b)),
        "source_relation_type_values": dict(Counter(row.get("type", "") for row in rows_b)),
        "source_raw_flag_values": {
            key: dict(Counter(row.get(key, "") for row in rows_b))
            for key in ["audit_only", "current_observation_candidate", "effective_candidate", "prediction_eligible"]
        },
    }
    source_claims = {
        "README_text": report_readme,
        "main_table_a_progress": dict(Counter(row.get("研究进度", "") for row in rows_a)),
        "main_table_a_relationship_class": class_counts,
        "main_table_a_prediction_state": dict(Counter(row.get("预测状态", "") for row in rows_a)),
        "main_table_b_prediction_state": dict(Counter(row.get("prediction", "") for row in rows_b)),
        "main_table_b_old_action": dict(Counter(row.get("old_action", "") for row in rows_b)),
        "machine_check_claims": {
            key: raw_machine_claims.get(key)
            for key in ["count", "unique_codes", "reviewed", "unfinished", "in_progress", "not_reviewed", "csv_xlsx_equal_after_blank_normalization"]
        },
        "old_matrix_comparison": "NOT_RUN",
        "independent_fact_verification": "PENDING",
    }
    catalog = {
        "schema_version": "v4.us_hk_mapping_catalog.v1",
        "catalog_id": "us_hk_667_20261015_from_20261014_membership",
        "catalog_state": "STRUCTURE_VALID_ONLY",
        "source": {
            "package_name": package_receipt["package_name"],
            "package_sha256": package_receipt["package_sha256"],
            "zip_crc": package_receipt["zip_crc"],
            "manifest": package_receipt["manifest"],
            "package_member_count": package_receipt["member_count"],
            "package_files": package_receipt["files"],
            "membership_snapshot": "2026-10-14",
            "membership_file": "docs/handoffs/hk_connect_list_20261014/港股通股票名单_667只_20261014.csv",
            "membership_sha256": membership_sha,
            "local_zip_path": str(zip_path),
        },
        "coverage": coverage,
        "source_claims": source_claims,
        "safety": SAFETY,
        "stocks": stocks,
        "relations": relations,
    }
    body_sha = hashlib.sha256(canonical_bytes(catalog)).hexdigest()
    catalog["integrity_sha256"] = body_sha
    audit = {
        "source_zip": package_receipt,
        "membership": {
            "path": str(membership_path),
            "sha256": membership_sha,
            "count": len(membership),
            "snapshot": "2026-10-14",
        },
        "structural_validation": coverage,
        "source_claims": source_claims,
        "catalog_integrity_sha256": body_sha,
        "safety": SAFETY,
        "limits": [
            "Source report statuses and source classification counts are preserved claims, not independent fact verification.",
            "All relation rows remain prediction UNTESTED and historical PIT NOT_VALIDATED.",
            "The earlier 997-row matrix was unavailable; per-edge old/new comparison remains NOT_RUN.",
            "This catalog is read-only research material and is not today's selection result or an authoritative market-data source.",
        ],
    }
    return catalog, audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=ZIP_DEFAULT)
    parser.add_argument("--membership", type=Path, default=MEMBERSHIP_DEFAULT)
    parser.add_argument("--replace", action="store_true", help="replace this batch's derived catalog and audit receipt")
    args = parser.parse_args()
    if (CATALOG_PATH.exists() or RECEIPT_PATH.exists()) and not args.replace:
        print("STOP: derived output exists; pass --replace only when intentionally rebuilding this batch", file=sys.stderr)
        return 2
    try:
        catalog, audit = build_catalog(args.zip, args.membership)
        catalog["integrity_sha256"] = hashlib.sha256(canonical_bytes({k: v for k, v in catalog.items() if k != "integrity_sha256"})).hexdigest()
        CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        RECEIPT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({
            "catalog": str(CATALOG_PATH.relative_to(REPO)),
            "catalog_bytes": CATALOG_PATH.stat().st_size,
            "catalog_sha256": sha256_bytes(CATALOG_PATH.read_bytes()),
            "catalog_integrity_sha256": catalog["integrity_sha256"],
            "receipt": str(RECEIPT_PATH.relative_to(REPO)),
            "source_zip_sha256": ZIP_SHA256,
            "membership_sha256": MEMBERSHIP_SHA256,
            "stocks": len(catalog["stocks"]),
            "relations": len(catalog["relations"]),
            "stocks_with_relations": catalog["coverage"]["stocks_with_relations"],
            "report_sections": catalog["coverage"]["report_sections"],
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"CANNOT_CONFIRM: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
