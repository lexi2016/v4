"""LOCAL ONLY: replay the existing HK Connect reader and emit metadata.

No network, collector, publisher, ensure function, service mutation, or source
file write is performed. Run in a separate local diagnostic process with the
existing service's three V4_MANAGER_UNIVERSE_* bindings and its two optional
D-1 receipt-root bindings. A second authority root, when supplied, must be the
actual HK owner's --hk-asset-root from existing config. The unchanged reader
may also read the configured D-1 roots and their original source references.
This program outputs no stock codes, names, SDK rows, account data, or quotes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True

EXPECTED_CONSUMERS = {
    "v4/manager_research/connect_selection.py": "238f608d8b130aaed6ecfeaea6a66550bf918045c82adeb9aa3ce4f7000ea291",
    "domains/manager_research_evidence.py": "4bfd8ec335eade9a97340fe17fc0742f2dba546d0e254fdfed2833ed324bb73d",
}
BINDINGS = ("V4_MANAGER_UNIVERSE_ROOT", "V4_MANAGER_UNIVERSE_OWNER_ROOT", "V4_MANAGER_UNIVERSE_OWNER_SHA256")
D1_BINDINGS = ("V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT", "V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT")
SOURCE_KEYS = (
    "owner", "role", "market", "source_date", "sha256", "run_id", "acquired_at",
    "available_at", "read_at", "capture_run_id", "capture_sha256", "source_sha256",
    "artifact_ref", "manifest_ref", "receipt_ref", "current_ref", "capture_ref", "publication_ref",
)
OWNER_KEYS = ("workload_id", "code_ref", "code_sha256", "role", "forward_source_set_sha256")
DIAGNOSTIC_KEYS = ("schema_version", "layer", "kind", "code", "field", "artifact_ref",
                   "source_owner", "producer_owner", "source_code_ref", "source_code_sha256")
CALENDAR_KEYS = ("status", "reason", "target_trade_date", "calendar_owner", "calendar_sha256",
                 "hk_securities_state", "hk_connect_state")
D1_SOURCE_KEYS = ("owner", "role", "market", "source_date", "sha256", "capture_manifest_sha256",
                  "panel_receipt_sha256", "panel_summary_sha256", "master_manifest_sha256",
                  "master_receipt_sha256", "master_artifact_sha256", "master_run_id",
                  "dispatch_receipt_sha256", "dispatch_run_id", "dispatch_finished_at",
                  "availability_upper_bound", "availability_semantics", "membership_semantics",
                  "capture_run_id", "capture_codes_sha256")


def sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_root(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts or path.is_symlink() or path.resolve() != path:
        raise ValueError("DIAGNOSTIC_ROOT_NOT_CANONICAL")
    return path


def bounded_error(error):
    message = str(error)
    return message if re.fullmatch(r"[A-Z0-9_:.-]{1,180}", message) else type(error).__name__


def scalar_metadata(value, keys):
    if not isinstance(value, dict):
        return {}
    return {key: item for key in keys if key in value
            and ((item := value[key]) is None or type(item) in (int, bool)
                 or (type(item) is str and len(item) <= 2048
                     and "\n" not in item and "\r" not in item))}


def gap_metadata(value):
    if not isinstance(value, list) or any(
        type(item) is not str or not re.fullmatch(r"[A-Za-z0-9_: .-]{1,240}", item)
        for item in value
    ):
        raise ValueError("DIAGNOSTIC_GAP_METADATA_INVALID")
    return list(value)


def d1_binding_metadata():
    result = {}
    invalid = False
    for name in D1_BINDINGS:
        configured = os.environ.get(name, "").strip()
        if not configured:
            result[name] = {"status": "NOT_CONFIGURED", "normalized_root": None}
            continue
        try:
            root = canonical_root(configured)
            result[name] = {"status": "BOUND_CANONICAL", "normalized_root": str(root),
                            "exists": root.exists(), "is_directory": root.is_dir()}
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            invalid = True
            result[name] = {"status": "CANNOT_CONFIRM", "normalized_root": None,
                            "diagnostic_error": bounded_error(error)}
    return result, invalid


def file_metadata(owner, root, relative):
    path = owner._resolve_under(root, relative)
    item = {"relative_path": relative, "is_file": path.is_file()}
    if item["is_file"]:
        item.update(size_bytes=path.stat().st_size, sha256=sha_file(path))
    return item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--context-json", required=True,
                        help="Small local export with plan_context and context_source keys; no raw rows")
    parser.add_argument("--producer-hk-asset-root",
                        help="Actual original HK job --hk-asset-root, from its existing config")
    args = parser.parse_args()
    app = canonical_root(args.app_root)
    raw_context = Path(args.context_json).read_bytes()
    envelope = json.loads(raw_context)
    if not isinstance(envelope, dict):
        raise ValueError("DIAGNOSTIC_CONTEXT_ENVELOPE_INVALID")
    context = envelope.get("plan_context")
    if not isinstance(context, dict) or context.get("plan_trade_date") != "20261009":
        raise ValueError("DIAGNOSTIC_EXACT_TARGET_CONTEXT_REQUIRED")
    market_session = context.get("market_session")
    if type(market_session) is not str or not re.fullmatch(r"\d{8}", market_session):
        raise ValueError("DIAGNOSTIC_MARKET_SESSION_DATE_INVALID_OR_MISSING")
    try:
        datetime.strptime(market_session, "%Y%m%d")
    except ValueError as error:
        raise ValueError("DIAGNOSTIC_MARKET_SESSION_DATE_INVALID_OR_MISSING") from error
    calendar_sha = context.get("calendar_sha256")
    if type(calendar_sha) is not str or not re.fullmatch(r"[0-9a-f]{64}", calendar_sha):
        raise ValueError("DIAGNOSTIC_CALENDAR_SHA_INVALID_OR_MISSING")
    context = {key: context.get(key) for key in (
        "plan_trade_date", "research_cutoff", "market_session", "calendar_sha256")}
    consumers = {}
    for relative, expected in EXPECTED_CONSUMERS.items():
        actual = sha_file(app / relative)
        if actual != expected:
            raise ValueError("DIAGNOSTIC_RUNNING_READER_SOURCE_DIFFERS_FROM_REVIEWED_PACKAGE")
        consumers[relative] = actual
    sys.path.insert(0, str(app))
    selection = importlib.import_module("v4.manager_research.connect_selection")
    domain = importlib.import_module("domains.manager_research_evidence")
    if Path(selection.__file__).resolve() != app / "v4/manager_research/connect_selection.py":
        raise ValueError("DIAGNOSTIC_CONSUMER_IMPORT_ROOT_MISMATCH")
    if Path(domain.__file__).resolve() != app / "domains/manager_research_evidence.py":
        raise ValueError("DIAGNOSTIC_DOMAIN_IMPORT_ROOT_MISMATCH")
    if selection.timestamp(context.get("research_cutoff")) is None:
        raise ValueError("DIAGNOSTIC_PERSISTED_CUTOFF_REQUIRED")
    bindings = {key: os.environ.get(key, "").strip() for key in BINDINGS}
    d1_bindings, d1_invalid = d1_binding_metadata()
    report = {
        "schema_version": "v4.hk_connect.local_metadata_inspection.v1",
        "scope": "ORIGINAL_READER_REPLAY_WITHOUT_SERVICE_CONFIGURATION_CHANGE",
        "context_source": scalar_metadata(envelope.get("context_source"),
                                           ("path", "sha256", "size_bytes", "run_id", "plan_sha256")),
        "context_export_sha256": hashlib.sha256(raw_context).hexdigest(),
        "context": {key: context.get(key) for key in (
            "plan_trade_date", "research_cutoff", "market_session", "calendar_sha256")},
        "consumer_code_sha256": consumers,
        "inherited_bindings": bindings,
        "d1_receipt_bindings": d1_bindings,
        "read_scope_access": {
            "authority_root_policy": "AT_MOST_TWO_EXPLICIT_AUTHORITY_ROOTS",
            "d1_policy": "ORIGINAL_OPTIONAL_FALLBACK_USING_UNCHANGED_EXISTING_RECEIPT_BINDINGS",
            "other_reads": "ORIGINAL_CALENDAR_AND_D1_CAPTURE_DISPATCH_SECURITY_MASTER_SOURCE_REFERENCES",
        },
        "binding_provenance": "THESE_ARE_THIS_DIAGNOSTIC_PROCESS_BINDINGS;VERIFY_AGAINST_EXISTING_SERVICE_CONFIG",
        "roots": [],
    }
    if d1_invalid:
        report.update(status="CANNOT_CONFIRM", diagnostic_error="DIAGNOSTIC_D1_RECEIPT_ROOT_BINDING_INVALID")
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    owner = None
    try:
        owner = domain.load_universe_owner(
            canonical_root(bindings[BINDINGS[1]]), bindings[BINDINGS[2]], require_v2=True)
        report["owner_source_sha256"] = sha_file(Path(owner.__file__))
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        report["owner_binding_error"] = bounded_error(error)
    roots = [("CURRENT_MANAGER_BINDING", bindings[BINDINGS[0]])]
    if args.producer_hk_asset_root:
        asset = canonical_root(args.producer_hk_asset_root)
        candidate = str(asset.parent.parent)
        report["producer_root_derivation"] = {
            "hk_asset_root": str(asset), "store_root": candidate,
            "source": "ops/_macos_research_panel_daily_parts/hk_capture_gate.py:26-42",
            "configuration_source": "OPERATOR_SUPPLIED_EXISTING_HK_JOB_ARGUMENT;NOT_AUTO_DISCOVERED",
        }
        if candidate != bindings[BINDINGS[0]]:
            roots.append(("EXISTING_HK_PRODUCER_ROOT", candidate))
    original = os.environ.get(BINDINGS[0])
    try:
        for label, root_text in roots:
            item = {"root_role": label, "root": root_text}
            report["roots"].append(item)
            try:
                root = canonical_root(root_text)
                if owner is not None:
                    target = context["plan_trade_date"]
                    artifact = file_metadata(owner, root, f"universes/{target}/HK_CONNECT_FULL_MARKET.json")
                    item["files"] = [artifact]
                    if artifact["is_file"]:
                        run = owner.authority_run_id(target, artifact["sha256"])
                        paths = owner._authority_relative_paths(target, run)
                        base = f"universes/{target}/HK_CONNECT_FULL_MARKET.authority/{run}"
                        relatives = [paths["manifest_relative"], paths["receipt_relative"],
                                     paths["current_relative"], f"{base}/capture.json", f"{base}/publication.json"]
                        item["derived_authority_run_id"] = run
                        item["files"].extend(file_metadata(owner, root, relative) for relative in relatives)
                    else:
                        item["files"].append(file_metadata(owner, root, f"universes/{target}/HK_CONNECT_FULL_MARKET.current.json"))
                # This environment assignment is private to this diagnostic
                # child process. It never edits the running service binding.
                os.environ[BINDINGS[0]] = str(root)
                scope = selection.read_scope(context)
                item.update(status=scope.get("status"), gaps=gap_metadata(scope.get("gaps")),
                            membership_identity=scope.get("identity"),
                            code_count=len(scope.get("codes") or []),
                            authority_reader_binding=scalar_metadata(scope.get("authority_reader_binding"),
                                ("mode", "owner_root", "source_code_ref", "source_code_sha256")),
                            authority_diagnostic=scalar_metadata(scope.get("authority_diagnostic"), DIAGNOSTIC_KEYS),
                            calendar_applicability=scalar_metadata(scope.get("calendar_applicability"), CALENDAR_KEYS))
                source = scope.get("source") or {}
                item["source"] = scalar_metadata(source, SOURCE_KEYS)
                for key in ("producer_owner", "contract_owner"):
                    if isinstance(source.get(key), dict):
                        item["source"][key] = scalar_metadata(source[key], OWNER_KEYS)
                if isinstance(scope.get("previous_session_capture"), dict):
                    previous = scope["previous_session_capture"]
                    item["previous_session_capture"] = scalar_metadata(previous, ("status", "source_date"))
                    item["previous_session_capture"]["gaps"] = gap_metadata(previous.get("gaps"))
                    item["previous_session_capture"]["source"] = scalar_metadata(previous.get("source"), D1_SOURCE_KEYS)
            except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
                item.update(status="CANNOT_CONFIRM", diagnostic_error=bounded_error(error))
    finally:
        if original is None:
            os.environ.pop(BINDINGS[0], None)
        else:
            os.environ[BINDINGS[0]] = original
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(json.dumps({"status": "CANNOT_CONFIRM", "diagnostic_error": bounded_error(error)}))
        raise SystemExit(2)
