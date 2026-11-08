#!/usr/bin/env python3
"""Snapshot the official Tushare menu; optionally probe three selected APIs.

The default is documentary only. Provider guidance disallows batch probing;
the explicit probe action is limited to three research-relevant interfaces.
"""
from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import hmac
import json
import os
import re
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infrastructure.tushare_relay import FLAGS, RelayConfig, canonical, query, sha256


MENU = "https://tushare.pro/document/2"
MAX_DOC = 2_097_152
PARSER_VERSION = 2
PLANS = {
    "index_member_all": {
        "params": {"ts_code": "000001.SZ", "is_new": "N", "limit": 1},
        "fields": "l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new",
        "market": "A", "source_date": "HISTORY_INTERVAL_REQUEST", "doc_id": 335,
        "purpose": "historical industry membership and inclusion/exclusion dates"},
    "income": {
        "params": {"ts_code": "000001.SZ", "period": "20251231", "limit": 1},
        "fields": "ts_code,ann_date,f_ann_date,end_date,report_type,total_revenue",
        "market": "A", "source_date": "20251231_REPORT_PERIOD", "doc_id": 33,
        "purpose": "financial report and disclosure-date fields"},
    "daily_basic": {
        "params": {"ts_code": "000001.SZ", "trade_date": "20260930", "limit": 1},
        "fields": "ts_code,trade_date,total_share,float_share,free_share,total_mv,circ_mv",
        "market": "A", "source_date": "20260930", "doc_id": 32,
        "purpose": "dated capital and market-value fields"},
}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def write_json(path: Path, obj: object) -> None:
    data = canonical(obj)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def init_root(root: Path) -> None:
    if root.is_symlink():
        raise ValueError("output root cannot be a symlink")
    if not root.exists():
        root.mkdir(parents=True, exist_ok=False)
        write_json(root / "run.json", {"schema": "tushare_relay_audit.v1", "created_at": now(), **FLAGS})
    elif not (root / "run.json").is_file():
        raise ValueError("existing output must contain this audit's run.json")
    if json.loads((root / "run.json").read_text()).get("schema") != "tushare_relay_audit.v1":
        raise ValueError("invalid audit root")


@contextmanager
def locked(root: Path):
    with (root / ".lock").open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def fetch(url: str) -> bytes:
    with requests.get(url, timeout=(10, 20), stream=True, allow_redirects=False) as r:
        if r.status_code != 200:
            raise ValueError("official HTTP status " + str(r.status_code))
        body = bytearray()
        for chunk in r.iter_content(16384):
            body.extend(chunk)
            if len(body) > MAX_DOC:
                raise ValueError("official page exceeded size limit")
        return bytes(body)


def menu_items(html: bytes) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = {}
    for a in soup.select('#jstree a[href*="doc_id="]'):
        u = urlsplit(a.get("href", ""))
        ident = parse_qs(u.query).get("doc_id", [""])[0]
        if u.path != "/document/2" or not ident.isdigit():
            continue
        parent = a.parent
        ancestors = []
        while parent:
            if parent.name == "li":
                link = parent.find("a", recursive=False)
                if link:
                    ancestors.append(link.get_text(" ", strip=True))
            parent = parent.parent
        name = a.get_text(" ", strip=True)
        row = items.setdefault(ident, {"doc_id": int(ident), "menu_titles": [], "menu_paths": []})
        if name not in row["menu_titles"]:
            row["menu_titles"].append(name)
        path = list(reversed(ancestors))
        if path not in row["menu_paths"]:
            row["menu_paths"].append(path)
    if not items:
        raise ValueError("official menu has no doc_id entries")
    return list(items.values())


def example_calls(content, api: str) -> list[dict]:
    """Extract literal kwargs without executing documentation code."""
    calls = []
    for pre in content.select("pre"):
        source = pre.get_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            f = node.func
            if not isinstance(f.value, ast.Name) or f.value.id not in ("pro", "api"):
                continue
            if f.attr == "query":
                if not node.args or not isinstance(node.args[0], ast.Constant) or node.args[0].value != api:
                    continue
            elif f.attr != api:
                continue
            values = {}
            for kw in node.keywords:
                if not kw.arg or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", kw.arg):
                    continue
                try:
                    v = ast.literal_eval(kw.value)
                except (ValueError, TypeError):
                    continue
                if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 200 and not re.search("token|password|secret", kw.arg, re.I):
                    values[kw.arg] = v
            calls.append(values)
    return calls[:5]


def parse_doc(raw: bytes, item: dict, fetched_at: str) -> dict:
    soup = BeautifulSoup(raw, "html.parser")
    content = soup.select_one(".content")
    base = {**item, "source_url": MENU + "?doc_id=" + str(item["doc_id"]),
            "fetched_at": fetched_at, "html_sha256": sha256(raw), "parser_version": PARSER_VERSION}
    if content is None:
        return {**base, "doc_status": "PARSE_CONTENT_MISSING", "api_name": None}
    title = content.find(["h1", "h2"])
    blocks = content.find_all(["p", "h1", "h2", "h3"], limit=8)
    lead = " ".join(x.get_text(" ", strip=True) for x in blocks)
    match = re.search(r"接口(?:名称|名)?\s*[：:]\s*([A-Za-z][A-Za-z0-9_]{1,79})", lead)
    api = match.group(1) if match else None
    text = content.get_text(" ", strip=True)
    named = list(dict.fromkeys(re.findall(r"接口(?:名称|名)?\s*[：:]\s*([A-Za-z][A-Za-z0-9_]{1,79})", text)))
    additional = [name for name in named if name != api]
    tables = []
    for table in content.find_all("table"):
        headers = [x.get_text(" ", strip=True) for x in table.select("thead th")]
        if any("必选" in h or "是否必" in h or h == "必须" for h in headers):
            rows = [[x.get_text(" ", strip=True) for x in tr.find_all("td")] for tr in table.select("tbody tr")]
            tables.append({"headers": headers, "rows": [x for x in rows if x]})
    path_text = " ".join(" ".join(x) for x in item["menu_paths"])
    local = api == "pro_bar" or "SDK层做了一些逻辑处理" in lead
    unsafe = bool(re.search(r"自选组合|组合保存|组合删除|订阅接口|流式接口|websocket接口", path_text, re.I))
    if unsafe:
        state = "SKIPPED_ACCOUNT_SUBSCRIPTION_OR_STREAM"
    elif local:
        state = "LOCAL_SDK"
    elif api and not tables:
        state = "NOT_TESTED_PARAMETER_UNRESOLVED"
    elif api:
        state = "DOCUMENTED_NOT_PROBED"
    elif "不提供API方式" in text or "不提供api方式" in text.lower():
        state = "NO_API_CSV_DELIVERY_DOCUMENTED"
    else:
        state = "API_NOT_IDENTIFIED"
    return {**base, "title": title.get_text(" ", strip=True) if title else None,
            "api_name": api, "additional_api_names": additional, "doc_status": state, "input_tables": tables,
            "example_literal_calls": example_calls(content, api) if api else []}


def catalogue(root: Path, interval: float) -> None:
    docs = root / "official_docs"
    docs.mkdir(exist_ok=True)
    menu_file = root / "official_menu.html"
    menu_meta = root / "official_menu_meta.json"
    if not menu_file.exists():
        raw = fetch(MENU)
        menu_file.write_bytes(raw)
        write_json(menu_meta, {"source_url": MENU, "fetched_at": now(), "sha256": sha256(raw)})
    if sha256(menu_file.read_bytes()) != json.loads(menu_meta.read_text())["sha256"]:
        raise ValueError("official menu identity mismatch")
    items = menu_items(menu_file.read_bytes())
    for i, item in enumerate(items, 1):
        ident = str(item["doc_id"])
        meta = docs / (ident + ".json")
        if meta.exists():
            old = json.loads(meta.read_text())
            if old.get("parser_version") != PARSER_VERSION and old.get("html_sha256"):
                raw = (docs / (ident + ".html")).read_bytes()
                if sha256(raw) != old["html_sha256"]:
                    raise ValueError("cached official page identity mismatch")
                write_json(meta, parse_doc(raw, item, old["fetched_at"]))
            continue
        raw_path = docs / (ident + ".html")
        try:
            body = fetch(MENU + "?doc_id=" + ident)
            raw_path.write_bytes(body)
            record = parse_doc(body, item, now())
        except (requests.RequestException, ValueError) as exc:
            # The type is diagnostic; never persist exception strings that can contain URLs.
            record = {**item, "source_url": MENU + "?doc_id=" + ident,
                      "fetched_at": now(), "doc_status": "DOC_FETCH_FAILED",
                      "error_type": type(exc).__name__, "api_name": None}
        write_json(meta, record)
        if i % 25 == 0 or i == len(items):
            print(f"official pages {i}/{len(items)}", flush=True)
        time.sleep(interval)
    records = [json.loads((docs / (str(x["doc_id"]) + ".json")).read_text()) for x in items]
    result = {"schema": "tushare_official_catalog.v1", "menu": json.loads(menu_meta.read_text()),
              "created_at": now(), "menu_unique_doc_ids": len(items),
              "status_counts": dict(Counter(x["doc_status"] for x in records)),
              "records": records, **FLAGS}
    write_json(root / "official_catalog.json", result)
    print(json.dumps({"official_pages": len(records), "statuses": result["status_counts"]}, ensure_ascii=False), flush=True)


def prior_daily(path: Path, primary: str) -> dict:
    receipt = json.loads(path.read_text())
    for row in receipt.get("results", []):
        if (row.get("role") == "primary" and row.get("endpoint") == primary and row.get("api") == "daily"
                and row.get("params") == {"ts_code": "000001.SZ", "trade_date": "20260930"}
                and row.get("status") == "PASS_RESPONSE_STRUCTURE"):
            artifact = Path(row["artifact"])
            if sha256(artifact.read_bytes()) != row.get("sha256"):
                raise ValueError("prior daily artifact identity mismatch")
            return {"status": "PRIOR_SUCCESS_RESPONSE", "source_receipt": str(path),
                    "source_receipt_sha256": sha256(path.read_bytes()),
                    "artifact": str(artifact), "artifact_sha256": row["sha256"],
                    "row_count": row["rows"], "observed_at": receipt["time"]}
    raise ValueError("matching prior daily receipt missing")


def save_report(path: Path, report: dict) -> None:
    api_records = {}
    for item in report["records"]:
        api = item.get("api_name")
        if api in report["probes"]:
            item["audit_status"] = report["probes"][api]["status"]
        elif api == "daily":
            item["audit_status"] = "PRIOR_SUCCESS_RESPONSE"
        else:
            item["audit_status"] = item["doc_status"]
        for name in [api] + item.get("additional_api_names", []):
            if not name:
                continue
            entry = api_records.setdefault(name, {"api": name, "sources": [], "statuses": [], "primary_document": False})
            entry["sources"].append({"doc_id": item["doc_id"], "url": item.get("source_url")})
            if name == api:
                entry["primary_document"] = True
                entry["statuses"].append(item["audit_status"])
    for name, entry in api_records.items():
        if name in report["probes"]:
            entry["status"] = report["probes"][name]["status"]
        elif name == "daily":
            entry["status"] = "PRIOR_SUCCESS_RESPONSE"
        elif entry["primary_document"]:
            entry["status"] = entry["statuses"][0]
        else:
            entry["status"] = "NOT_TESTED_PARAMETER_UNRESOLVED"
    report["api_records"] = [api_records[x] for x in sorted(api_records)]
    report["api_status_counts"] = dict(Counter(x["status"] for x in report["api_records"]))
    report["page_status_counts"] = dict(Counter(x["audit_status"] for x in report["records"]))
    report["page_count"] = len(report["records"])
    report["identified_unique_api_count"] = len(api_records)
    write_json(path, report)
    samples = {api: {"path": row["artifact"], "sha256": row["artifact_sha256"],
                     "run_id": row["run_id"], "market": row["market"], "source_date": row["source_date"]}
               for api, row in report["probes"].items() if row.get("artifact")}
    write_json(path.parent / "manifest.json", {"schema": "tushare_isolated_manifest.v1",
               "catalog_sha256": report["official_catalog_sha256"], "report_sha256": sha256(path.read_bytes()),
               "samples": samples, "pit_status": "CANNOT_CONFIRM", **FLAGS})


def probe(root: Path, config: RelayConfig, api_names: list[str], receipt: Path,
          pause: float, allow_fallback: bool) -> None:
    catalog_bytes = (root / "official_catalog.json").read_bytes()
    catalog = json.loads(catalog_bytes)
    record_path = root / "capability_report.json"
    if record_path.exists():
        report = json.loads(record_path.read_text())
        if report["official_catalog_sha256"] != sha256(catalog_bytes):
            raise ValueError("catalog identity changed; use a new audit root")
        binding = hmac.new(config.token.encode(), report["created_at"].encode(), hashlib.sha256).hexdigest()
        if (report.get("credential_binding") != binding or report.get("primary_endpoint") != config.primary
                or report.get("fallback_endpoint") != config.fallback):
            raise ValueError("configured endpoint or credential changed; use a new audit root")
    else:
        created = now()
        report = {"schema": "tushare_capability_report.v1", "created_at": created,
                  "official_catalog_sha256": sha256(catalog_bytes), "records": catalog["records"],
                  "previous_daily": prior_daily(receipt, config.primary), "probes": {},
                  "primary_endpoint": config.primary, "fallback_endpoint": config.fallback,
                  "credential_binding": hmac.new(config.token.encode(), created.encode(), hashlib.sha256).hexdigest(),
                  "provider_guidance": "No bulk probing; at most three selected research samples",
                  "pit_status": "CANNOT_CONFIRM", **FLAGS}
    for api, row in report["probes"].items():
        if row["status"] == "REQUEST_DISPATCHED":
            row["status"] = "INTERRUPTED_OUTCOME_UNKNOWN_NO_RETRY"
    save_report(record_path, report)
    for api in api_names:
        if api in report["probes"]:
            continue
        if len(report["probes"]) >= 3:
            raise ValueError("three-probe limit already reached")
        plan = PLANS[api]
        if not any(x["doc_id"] == plan["doc_id"] and x.get("api_name") == api for x in report["records"]):
            raise ValueError("planned API absent or changed in frozen official catalog")
        run_id = "ts-audit-" + sha256(canonical({"created_at": report["created_at"], "api": api}))[:20]
        row = {"api": api, **plan, "run_id": run_id, "requested_at": now(),
               "status": "REQUEST_DISPATCHED", "pit_status": "CANNOT_CONFIRM"}
        report["probes"][api] = row
        save_report(record_path, report)  # Durable before external request; never replay an unknown outcome.
        response = query(config, api, plan["params"], fields=plan["fields"],
                         allow_fallback=allow_fallback)
        data = response.pop("data", None)
        row.update(response)
        row["observed_at"] = now()
        if data is not None and response["row_count"] <= 3:
            sample = {"schema": "tushare_isolated_sample.v1", "api": api, "run_id": run_id,
                      "source_kind": "THIRD_PARTY_RELAY", "source_url": row["endpoint"],
                      "official_doc_url": MENU + "?doc_id=" + str(plan["doc_id"]),
                      "requested_params": plan["params"], "requested_fields": plan["fields"],
                      "market": plan["market"], "source_date": plan["source_date"],
                      "source_date_basis": "REQUEST_ONLY_NOT_VALIDATED",
                      "observed_at": row["observed_at"], "available_at": "CANNOT_CONFIRM",
                      "pit_status": "CANNOT_CONFIRM", "row_count": response["row_count"],
                      "data": data, **FLAGS}
            sample_path = root / ("sample_" + api + ".json")
            write_json(sample_path, sample)
            row["artifact"] = sample_path.name
            row["artifact_sha256"] = sha256(sample_path.read_bytes())
        elif data is not None:
            row["status"] = "SERVER_IGNORED_SAMPLE_LIMIT"
        save_report(record_path, report)
        print(json.dumps({"api": api, "status": row["status"], "rows": row.get("row_count")}, ensure_ascii=False), flush=True)
        time.sleep(pause)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("catalog")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--interval", type=float, default=0.2)
    p = sub.add_parser("probe")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--env-file", required=True, type=Path)
    p.add_argument("--prior-receipt", required=True, type=Path)
    p.add_argument("--api", action="append", choices=tuple(PLANS), required=True)
    p.add_argument("--pause", type=float, default=3)
    p.add_argument("--allow-fallback", action="store_true")
    args = parser.parse_args()
    if args.command == "catalog" and args.interval < 0.1:
        parser.error("official document interval must be >= 0.1 seconds")
    if args.command == "probe" and (args.pause < 3 or len(set(args.api)) != len(args.api)):
        parser.error("probe pause must be >= 3 seconds and APIs must be unique")
    init_root(args.out)
    with locked(args.out):
        if args.command == "catalog":
            catalogue(args.out, args.interval)
        else:
            probe(args.out, RelayConfig.from_file(args.env_file), args.api, args.prior_receipt,
                  args.pause, args.allow_fallback)


if __name__ == "__main__":
    main()
