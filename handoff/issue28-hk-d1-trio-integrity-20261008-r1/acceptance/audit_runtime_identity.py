#!/usr/bin/env python3
"""Read only the frozen Issue #28 source paths, config and one dated receipt.

This is a file-identity inventory, not the pool validator or a recovery tool.
It imports no V4 module, opens no network connection and writes only stdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys


COMMIT = "30ad7bb633f715f30c4e10eb67e9041de92cf036"
DATE = "20261008"
STAGE = "STAGE_0930_0935"
PINS = {
    "source_identity.json": "a362cd71b66c55230232293368485d8034fe36602c6d2a6c85b5495a57639e18",
    "runtime_owners.json": "7459a70dcc83c2cee985734a0f40aeb9187fde8c8e6e2f1aebab36b6507d4bf3",
    "stage_receipt_summary.json": "58c737e7f19554e3984d5021e12b6a0ad69219acd9ee7f693f6bb8f06fd5e805",
}
FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
FROZEN_REASON = "HK D1 split-date eligibility provenance missing"
HASH = re.compile(r"[0-9a-f]{64}\Z")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_bytes(path, limit=2_000_000):
    """Read a bounded regular file without following symlink components."""
    path = Path(os.path.abspath(os.path.expanduser(str(path))))
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise ValueError("not a bounded regular file")
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            visible = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
            if len(raw) > limit or identity(before) != identity(after) or identity(after) != identity(visible):
                raise ValueError("file identity changed during read")
            return raw
    finally:
        os.close(directory)


def read_object(path, limit=2_000_000):
    raw = read_bytes(path, limit)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value, raw


def observe(path):
    try:
        raw = read_bytes(path)
        return {"bytes": len(raw), "sha256": digest(raw)}, raw
    except (OSError, ValueError) as error:
        return {"status": "MISSING" if isinstance(error, FileNotFoundError) else "UNREADABLE_OR_UNSTABLE",
                "error_type": type(error).__name__}, None


def safe_flags(value):
    value = value if isinstance(value, dict) else {}
    return {key: value[key] if type(value.get(key)) is bool else "CANNOT_CONFIRM" for key in FLAGS}


def read_frozen(problem_root):
    values = {}
    for name, expected in PINS.items():
        value, raw = read_object(problem_root / "evidence" / name)
        if digest(raw) != expected:
            raise ValueError("frozen evidence SHA mismatch")
        values[name] = value
    return values


def source_inventory(frozen):
    entries = {}
    for item in frozen["source_identity.json"]["files"]:
        relative = item["path"]
        for owner, prefix in (("canonical", "canonical"),
                              ("actual_stage_owner", "actual_stage_owner"),
                              ("api_runtime", "api_runtime")):
            if prefix + "_sha256" in item:
                entries[(owner, relative)] = item[prefix + "_sha256"]
    app = frozen["source_identity.json"]["api_app_full_file"]
    entries[("api_runtime", app["path"])] = app["api_runtime_sha256"]
    entries[("canonical", app["path"])] = app["canonical_sha256"]
    return entries


def read_candidate(path, entries):
    if path is None:
        return {}, None
    value, raw = read_object(path, 256_000)
    if set(value) != {"schema_version", "files"} or value["schema_version"] != "issue28.hk_stage_candidate_identity.v1":
        raise ValueError("candidate manifest schema invalid")
    if not isinstance(value["files"], list) or not value["files"]:
        raise ValueError("candidate manifest files must be nonempty")
    after = {}
    for item in value["files"]:
        if not isinstance(item, dict) or set(item) != {"owner", "path", "before_sha256", "after_sha256"}:
            raise ValueError("candidate entry fields invalid")
        if item["owner"] not in {"canonical", "actual_stage_owner"} or not isinstance(item["path"], str):
            raise ValueError("candidate owner or path invalid")
        key = (item["owner"], item["path"])
        if key not in entries or key in after or item["before_sha256"] != entries[key]:
            raise ValueError("candidate path or preimage is not the frozen allowlist")
        if not isinstance(item["after_sha256"], str) or not HASH.fullmatch(item["after_sha256"]) or item["after_sha256"] == entries[key]:
            raise ValueError("candidate after SHA invalid or unchanged")
        after[key] = item["after_sha256"]
    return after, digest(raw)


def audit(args):
    frozen = read_frozen(args.problem_root)
    entries = source_inventory(frozen)
    after, candidate_digest = read_candidate(args.candidate_manifest, entries)
    roots = {"canonical": args.canonical_root, "actual_stage_owner": args.stage_root,
             "api_runtime": args.api_root}
    sources = []
    for (owner, relative), before in sorted(entries.items()):
        observed, _ = observe(roots[owner] / relative)
        if "sha256" in observed:
            observed["status"] = ("MATCHES_AFTER" if observed["sha256"] == after.get((owner, relative))
                                  else "MATCHES_BEFORE" if observed["sha256"] == before else "DIFFERS")
        sources.append({"owner": owner, "path": relative, "before_sha256": before,
                        "after_sha256": after.get((owner, relative)), **observed})

    config_path = args.stage_root / "stage_center_tick_config.json"
    config_observed, config_raw = observe(config_path)
    config = None
    if config_raw is not None:
        try:
            config = json.loads(config_raw)
            if not isinstance(config, dict):
                raise ValueError("config is not an object")
            allowed = ("release_id", "python_path", "candidate_acquisition_root", "hk_d1_root",
                       "preselection_source_root", "raw_root", "selection_root", "receipt_root")
            fields = {key: config.get(key) for key in allowed}
            if any(value is not None and (not isinstance(value, str) or len(value) > 4096 or "\n" in value)
                   for value in fields.values()):
                raise ValueError("config projected field invalid")
            config_observed.update(status="OBSERVED_ONLY", fields=fields, safety=safe_flags(config.get("safety")),
                                   receipt_root_matches_requested_audit_root=(config.get("receipt_root") == str(args.receipt_root)))
        except (ValueError, TypeError):
            config_observed["status"] = "INVALID_CONFIG"

    receipt_path = args.receipt_root / DATE / STAGE / "receipt.json"
    receipt_observed, receipt_raw = observe(receipt_path)
    if receipt_raw is not None:
        try:
            receipt = json.loads(receipt_raw)
            if not isinstance(receipt, dict):
                raise ValueError("receipt is not an object")
            fields = ("schema_version", "trade_date", "stage_id", "status", "due_status", "node_outcome",
                      "node_attempt_count", "retry_exhausted", "write_performed")
            summary = {key: receipt.get(key) for key in fields}
            # Never print row objects, symbols, arbitrary exception text or source_evidence.
            if any(value is not None and type(value) not in (str, int, bool) for value in summary.values()):
                raise ValueError("receipt projected field invalid")
            markets = receipt.get("markets") if isinstance(receipt.get("markets"), dict) else {}
            for market in ("A_SHARE", "HK_CONNECT"):
                lane = markets.get(market) if isinstance(markets.get(market), dict) else {}
                summary[market] = {key: lane.get(key) for key in (
                    "status", "selection_status", "source_status", "requested_rows", "source_rows",
                    "selected_rows", "write_performed") if type(lane.get(key)) in (str, int, bool)}
                reasons = lane.get("cannot_confirm")
                summary[market].update(
                    frozen_provenance_missing_reason_observed=(isinstance(reasons, list) and FROZEN_REASON in reasons),
                    cannot_confirm_count=len(reasons) if isinstance(reasons, list) else None,
                    cannot_confirm_sha256=digest(json.dumps(reasons, ensure_ascii=False, sort_keys=True).encode()),
                )
            receipt_observed.update(status="OBSERVED_ONLY", summary=summary, safety=safe_flags(receipt),
                                    matches_frozen_receipt_sha256=(digest(receipt_raw) == frozen["stage_receipt_summary.json"]["source_receipt_sha256"]),
                                    date_stage_match=(receipt.get("trade_date") == DATE and receipt.get("stage_id") == STAGE))
        except (ValueError, TypeError):
            receipt_observed["status"] = "INVALID_RECEIPT"

    source_match = all(item["status"] in {"MATCHES_BEFORE", "MATCHES_AFTER"} for item in sources)
    report = {
        "schema_version": "issue28.hk_stage_runtime_identity_audit.v1",
        "frozen_input_commit": COMMIT,
        "audit_scope": "READ_ONLY_SOURCE_CONFIG_AND_ONE_RECEIPT",
        "host": {"platform": platform.platform(), "python": sys.version, "executable": sys.executable},
        "roots": {key: str(value) for key, value in roots.items()},
        "candidate_manifest_sha256": candidate_digest,
        "source_identity_status": "SOURCE_MATCH" if source_match else "CANNOT_CONFIRM",
        "sources": sources,
        "config": config_observed,
        "receipt": receipt_observed,
        "runtime_recovery_status": "CANNOT_CONFIRM",
        "not_executed": ["V4 imports", "pool validation", "upstream provenance validation", "Stage dispatch",
                         "deployment", "service or schedule change", "API GET", "UI", "natural-slot acceptance"],
        "limits": ["A source SHA match does not identify loaded process memory or prove a successful Stage run.",
                   "The receipt is one file observation; it is not a newly verified artifact trio.",
                   "No pool rows, price source, eligibility artifact or capture-time evidence is consumed.",
                   "Exit 0 means the inventory reads matched, never that HK recovery succeeded."],
    }
    complete = (source_match and config_observed.get("status") == "OBSERVED_ONLY"
                and config_observed.get("receipt_root_matches_requested_audit_root") is True
                and receipt_observed.get("status") == "OBSERVED_ONLY"
                and receipt_observed.get("date_stage_match") is True
                and all(config_observed.get("safety", {}).get(key) is False for key in FLAGS)
                and all(receipt_observed.get("safety", {}).get(key) is False for key in FLAGS))
    return report, 0 if complete else 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("problem-root", "stage-root", "canonical-root", "api-root", "receipt-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path)
    args = parser.parse_args()
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, Path(os.path.abspath(os.path.expanduser(str(value)))))
    try:
        report, code = audit(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        report, code = {"status": "INPUT_REJECTED", "error_type": type(error).__name__,
                        "reason": str(error) if isinstance(error, ValueError) else "unavailable or invalid audit input",
                        "runtime_recovery_status": "CANNOT_CONFIRM"}, 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
