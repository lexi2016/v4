#!/usr/bin/env python3
"""Serve only the original workbench shell assets and three D17 archived CSVs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
from zipfile import ZipFile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


EXPECTED = {
    "00_全范围处置.csv": (5572, 7, 359810, "5be9f005f4fdf50cc14dde4e4d7efdb66ae3753b1e323b0f3f8e43832810e89c"),
    "01_量价初筛.csv": (822, 27, 241304, "1cb9eea994d571c5da2969cf93ea49d9777b59936a61c5c4c496f2dd52420c3d"),
    "03_模型精选排序.csv": (33, 20, 10843, "025c07b27f3b7be730fdddee6974edea7def6b848ce2e8979da0fabadcf33ee2"),
}
V3_PACKAGE_BYTES = 114472
V3_PACKAGE_SHA256 = "ee213ab48d96d951aa4810901cb11619ac2a5aee8b387fdc4d9a458fb08bacc0"
V3_ADAPTER_SHA256 = "ebe66235d2f27c0e84bd1680cc368f90ef0be7e2d6b215fc5cb1727604656d65"
V3_ADAPTER_VERSION = "P515_SELECTION_OUTPUT_ADAPTER_V3_LIFECYCLE_HARDENED"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_identity(path: Path, source_name: str) -> dict:
    raw = path.read_bytes()
    actual_sha = digest(raw)
    rows = list(csv.reader(raw.decode("utf-8-sig").splitlines()))
    expected_rows, expected_columns, expected_bytes, expected_sha = EXPECTED[source_name]
    if (len(rows) - 1, len(rows[0]) if rows else 0, len(raw), actual_sha) != (
        expected_rows, expected_columns, expected_bytes, expected_sha
    ):
        raise RuntimeError(f"source identity mismatch {source_name}: rows={len(rows)-1}, cols={len(rows[0]) if rows else 0}, bytes={len(raw)}, sha256={actual_sha}")
    return {
        "filename": source_name,
        "bytes": len(raw),
        "sha256": actual_sha,
        "rows": len(rows) - 1,
        "columns": len(rows[0]) if rows else 0,
        "headers": rows[0],
    }


def verify_v3_display_binding(source_root: Path, adapter_zip: Path) -> dict:
    """Bind the actual V3 bytes and execute only its pure display adapter on archived D17 rows."""
    package = adapter_zip.read_bytes()
    package_sha = digest(package)
    if len(package) != V3_PACKAGE_BYTES or package_sha != V3_PACKAGE_SHA256:
        raise RuntimeError(f"V3 package identity mismatch bytes={len(package)} sha256={package_sha}")

    with ZipFile(io.BytesIO(package)) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("V3 adapter ZIP CRC failure")
        adapter_bytes = archive.read("selection_output_adapter.py")
    adapter_sha = digest(adapter_bytes)
    if adapter_sha != V3_ADAPTER_SHA256:
        raise RuntimeError(f"V3 adapter source SHA mismatch: {adapter_sha}")

    disposition_path = source_root / "00_全范围处置.csv"
    shortlist_path = source_root / "01_量价初筛.csv"
    qualification_path = source_root / "02_模型输入资格逐股.csv"
    score_path = source_root / "03_模型精选排序.csv"
    def dict_rows(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as source_file:
            return list(csv.DictReader(source_file))

    disposition = dict_rows(disposition_path)
    primary = dict_rows(shortlist_path)
    qualifications = dict_rows(qualification_path)
    original_scores = dict_rows(score_path)
    if (len(disposition), len(primary), len(original_scores)) != (5572, 822, 33):
        raise RuntimeError("D17 archive row counts do not match the frozen 5572/822/33 contract")
    primary_by_code: dict[str, tuple[int, dict[str, str]]] = {}
    for row_number, row in enumerate(primary, 1):
        code = row["代码"]
        if not code or code in primary_by_code:
            raise RuntimeError(f"duplicate or empty D17 primary security: {code!r}")
        primary_by_code[code] = (row_number, row)
    qualification_status = {row["代码"]: row["状态"] for row in qualifications}

    records: list[dict] = []
    for row_number, row in enumerate(disposition, 1):
        code = row["代码"]
        primary_entry = primary_by_code.get(code)
        primary_row_number = primary_entry[0] if primary_entry else None
        primary_row = primary_entry[1] if primary_entry else None
        stage_raw = primary_row.get("结构回调日数", "") if primary_row else ""
        records.append({
            "security": code,
            "decision_date": "2026-11-17",
            "security_name": row["简称"],
            "prefilter_disposition": row["结构初筛"],
            "pullback_stage_k": int(stage_raw) if stage_raw else None,
            "r2_k3_qualified": qualification_status.get(code) == "MODEL_READY",
            "r2_probe_status_original": qualification_status.get(code, "NOT_IN_ORIGINAL_R2_PROBE"),
            "original_disposition_csv_record_number": row_number,
            "original_primary_csv_record_number": primary_row_number,
            "original_values": primary_row if primary_row else row,
        })

    with tempfile.TemporaryDirectory(prefix="p515-v3-display-binding-") as temp:
        adapter_path = Path(temp) / "selection_output_adapter.py"
        adapter_path.write_bytes(adapter_bytes)
        spec = importlib.util.spec_from_file_location("p515_v3_archive_display", adapter_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot import actual V3 archive adapter bytes")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if module.ADAPTER_VERSION != V3_ADAPTER_VERSION:
            raise RuntimeError(f"V3 adapter version mismatch: {module.ADAPTER_VERSION}")
        result = module.build_prefilter_display_view(records)

    ledger = result["display_rows"]
    main_view = result["main_candidates_pass"]
    if len(ledger) != 5572 or len(main_view) != 822:
        raise RuntimeError(f"V3 display result counts differ: ledger={len(ledger)}, PASS={len(main_view)}")
    expected_pass = set(primary_by_code)
    actual_pass = {row["display_row_identity"]["security"] for row in main_view}
    if actual_pass != expected_pass:
        raise RuntimeError("V3 PASS membership differs from the original 822-row source")
    if len(ledger) != len(records) or not all(row["source_record_immutable"] == original for row, original in zip(ledger, records)):
        raise RuntimeError("V3 display adapter mutated an original source record")
    attached_count = sum(1 for row in ledger if row.get("model_prob") is not None)
    if attached_count != 0 or any(row.get("composite_key") is not None for row in ledger):
        raise RuntimeError("V3 display adapter produced a score attachment or fabricated composite key")

    return {
        "status": "PASS",
        "adapter_version": module.ADAPTER_VERSION,
        "entry_point": "build_prefilter_display_view",
        "entry_mode": result["mode"],
        "adapter_package": {"path": str(adapter_zip.resolve()), "bytes": len(package), "sha256": package_sha},
        "adapter_member": {"path": "selection_output_adapter.py", "bytes": len(adapter_bytes), "sha256": adapter_sha},
        "input_rows": {"full_disposition": len(disposition), "main_candidates": len(primary), "original_scores_separate": len(original_scores)},
        "output_rows": {"full_disposition_ledger": len(ledger), "main_candidates_pass": len(main_view), "attached_scores": attached_count},
        "pass_membership_matches_original_822": True,
        "source_records_immutable": True,
        "model_score_records_provided": 0,
        "model_probability_calls": 0,
        "fit_calls": 0,
        "preprocessing_fit_calls": 0,
        "static_new_score_calls": 0,
        "score_rows_read_only_for_count_and_source_hash": 33,
        "screen_generation": json.loads((source_root / "SCREEN_RECEIPT.json").read_text(encoding="utf-8"))["generation"],
        "model_receipt_generation": json.loads((source_root / "MODEL_RECEIPT.json").read_text(encoding="utf-8"))["generation"],
        "original_33_scores_sha256": digest(score_path.read_bytes()),
        "qualification_source_sha256": digest(qualification_path.read_bytes()),
        "result_counts": result["counts"],
        "guard_execution_audit": result["guard_execution_audit"],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "P515ArchivePreview/1.0"

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/research-panel/workbench.html":
            data, content_type = self.server.preview_html.read_bytes(), "text/html; charset=utf-8"
        elif path == "/archive-preview.mjs":
            data, content_type = self.server.client_module.read_bytes(), "text/javascript; charset=utf-8"
        elif path == "/research-panel/workbench-host/dot/shell/workbench.css":
            data, content_type = self.server.workbench_css.read_bytes(), "text/css; charset=utf-8"
        elif path == "/archive-data/identity.json":
            data, content_type = json.dumps(self.server.identity, ensure_ascii=False).encode(), "application/json; charset=utf-8"
        elif path.startswith("/archive-data/"):
            name = path.rsplit("/", 1)[-1]
            if name not in EXPECTED:
                self.send_error(404)
                return
            data = (self.server.source_root / name).read_bytes()
            content_type = "text/csv; charset=utf-8"
        else:
            self.send_error(404)
            self.log_event(path, 404)
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)
        self.log_event(path, 200)

    def log_event(self, path: str, status: int) -> None:
        print(json.dumps({"event": "http_request", "method": "GET", "path": path, "status": status}, ensure_ascii=False), flush=True)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--workbench-root", required=True)
    parser.add_argument("--preview-html", required=True)
    parser.add_argument("--client-module", required=True)
    parser.add_argument("--adapter-zip", required=True)
    parser.add_argument("--binding-output", required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    source_root = Path(args.source_root).resolve()
    v3_binding = verify_v3_display_binding(source_root, Path(args.adapter_zip).resolve())
    Path(args.binding_output).write_text(json.dumps(v3_binding, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    server.source_root = source_root
    server.workbench_css = Path(args.workbench_root).resolve() / "workbench-host/dot/shell/workbench.css"
    server.preview_html = Path(args.preview_html).resolve()
    server.client_module = Path(args.client_module).resolve()
    server.identity = {
        "replay": json.loads((source_root / "D17_REPLAY_SCOPE.json").read_text(encoding="utf-8")),
        "screen": json.loads((source_root / "SCREEN_RECEIPT.json").read_text(encoding="utf-8")),
        "model": json.loads((source_root / "MODEL_RECEIPT.json").read_text(encoding="utf-8")),
        "files": {
            "disposition": file_identity(source_root / "00_全范围处置.csv", "00_全范围处置.csv"),
            "shortlist": file_identity(source_root / "01_量价初筛.csv", "01_量价初筛.csv"),
            "scores": file_identity(source_root / "03_模型精选排序.csv", "03_模型精选排序.csv"),
        },
        "v3_display_binding": v3_binding,
    }
    host, port = server.server_address
    print(json.dumps({"ready": True, "origin": f"http://{host}:{port}", "host": host, "port": port}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
