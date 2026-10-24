"""Capture only the explicitly listed native input paths for existing ops.

No directory discovery, archive read, price decoding, formula, factor, SDK,
network, pointer or authority write occurs. The captured bytes and effective
source manifest are local derived inputs, not a second market-data authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FLAGS = dict(research_only=True, production_allowed=False,
             buy_gate_updated=False, orders_sent=False)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: str | Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_stat(path: str | Path) -> dict[str, int]:
    value = Path(path).stat()
    return dict(size=value.st_size, mtime_ns=value.st_mtime_ns, inode=value.st_ino)


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(sha(path) == hashlib.sha256(payload).hexdigest(), "CAPTURE_OUTPUT_DIFFERS:" + str(path))
        return
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def save(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  indent=2, allow_nan=False) + "\n").encode())


def capture_native_entry(entry: dict[str, Any], output: Path, maximum_file_bytes: int) -> dict[str, Any]:
    code = entry["code"]
    path = Path(entry["native_path"])
    reused = entry.get("reuse_canary_stock")
    original_stat = None
    try:
        if path.is_file():
            original_stat = file_stat(path)
    except OSError as exc:
        return dict(code=code, native_path=str(path), state="NATIVE_STAT_ERROR", error=repr(exc),
                    new_original_files_read=0, effective_native=None)
    if reused is not None and original_stat == entry["reused_original_native_stat"]:
        binding = next(source for source in reused["sources"] if source["name"] == "native")
        captured = Path(binding["path"])
        require(captured.is_file() and captured.stat().st_size == binding["bytes"], "REUSED_CANARY_CAPTURE_MISSING_OR_SIZE_DRIFT")
        return dict(code=code, native_path=str(path), state="REUSED_ORIGINAL_CANARY_CAPTURE",
                    native_stat=original_stat, effective_native=binding,
                    capture_vintage="UNCHANGED_R1_SAMPLE_CAPTURE; NO_NEW_CAPTURE_TIME_INVENTED",
                    new_original_files_read=0)
    if original_stat is None:
        if reused is not None:
            binding = next(source for source in reused["sources"] if source["name"] == "native")
            require(Path(binding["path"]).is_file() and Path(binding["path"]).stat().st_size == binding["bytes"],
                    "REUSED_CANARY_CAPTURE_MISSING_OR_SIZE_DRIFT")
            return dict(code=code, native_path=str(path), state="REUSED_CANARY_CAPTURE_ORIGINAL_NOW_MISSING",
                        native_stat=None, effective_native=binding, new_original_files_read=0,
                        capture_vintage="UNCHANGED_R1_SAMPLE_CAPTURE; ORIGINAL_PATH_MISSING_REQUIRES_REVIEW")
        return dict(code=code, native_path=str(path), state="NATIVE_MISSING_AT_CAPTURE",
                    previously_captured_canary_binding=reused, new_original_files_read=0,
                    effective_native=None)
    if original_stat["size"] > maximum_file_bytes:
        return dict(code=code, native_path=str(path), state="NATIVE_FILE_EXCEEDS_FROZEN_BYTE_CAP",
                    native_stat=original_stat, new_original_files_read=0, effective_native=None)
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        # One open/read of this original file. No record or price decoding.
        with path.open("rb") as stream:
            payload = stream.read(maximum_file_bytes + 1)
        after = file_stat(path)
    except OSError as exc:
        return dict(code=code, native_path=str(path), state="NATIVE_READ_ERROR", error=repr(exc),
                    native_stat_before=original_stat, new_original_files_read=1, effective_native=None)
    digest = hashlib.sha256(payload).hexdigest()
    captured = output / "original_native_bytes" / (code + "." + digest + ".day")
    atomic_bytes(captured, payload)
    stable = original_stat == after and len(payload) == original_stat["size"]
    valid_layout = bool(payload) and len(payload) % 32 == 0 and len(payload) <= maximum_file_bytes
    state = "NATIVE_CAPTURED_STABLE_BYTES" if stable and valid_layout else (
        "NATIVE_CHANGED_DURING_CAPTURE" if not stable else "NATIVE_INVALID_RECORD_LAYOUT")
    binding = dict(name="native", kind="day_bytes", path=str(captured), sha256=digest, bytes=len(payload))
    if stable and valid_layout and reused is not None:
        previous_binding = next(source for source in reused["sources"] if source["name"] == "native")
        if previous_binding["sha256"] == digest:
            binding = previous_binding
            state = "REUSED_CANARY_CAPTURE_STAT_CHANGED_BYTES_IDENTICAL"
    return dict(code=code, native_path=str(path), state=state,
                native_stat_before=original_stat, native_stat_after=after,
                captured_original_bytes=dict(path=str(captured), sha256=digest, bytes=len(payload)),
                capture_started_at=started_at, capture_completed_at=datetime.now(timezone.utc).isoformat(),
                new_identity_for_changed_canary_source=reused is not None,
                new_original_files_read=1, effective_native=binding if stable and valid_layout else None)


def execute(config: dict[str, Any], config_sha: str) -> dict[str, Any]:
    require(config["schema"] == "V194_EXPLICIT_NATIVE_INPUT_CAPTURE_CONFIG_V1", "CAPTURE_SCHEMA_DRIFT")
    require(config["safety_flags"] == FLAGS, "CAPTURE_UNSAFE_FLAGS")
    require(sha(__file__) == config["implementation_sha256"], "CAPTURE_IMPLEMENTATION_SHA_DRIFT")
    require(config["capture_workers"] == 1, "CAPTURE_IS_SEQUENTIAL_NOT_A_NEW_PARALLEL_BENCHMARK")
    require(config["maximum_file_bytes"] > 0 and config["maximum_total_capture_bytes"] > 0, "CAPTURE_BYTE_LIMIT_INVALID")
    for binding in config["metadata_bindings"]:
        require(sha(binding["path"]) == binding["sha256"], "CAPTURE_METADATA_SHA_DRIFT:" + binding["path"])
    source_binding = config["source_binding"]
    require(sha(source_binding["path"]) == source_binding["sha256"], "CAPTURE_SOURCE_LIST_SHA_DRIFT")
    source = json.loads(Path(source_binding["path"]).read_text())
    rows = source["stocks"]
    require(len(rows) == 5533 and len({row["code"] for row in rows}) == 5533, "CAPTURE_EXPECTS_EXACT_5533_KEYS")
    require([row["code"] for row in rows] == sorted(row["code"] for row in rows), "CAPTURE_KEYS_NOT_SORTED")
    require(sum(row.get("captured_canary_sample_bytes") is not None for row in rows) == 5, "CAPTURE_FIVE_REUSE_BINDINGS_REQUIRED")
    frozen_canary = json.loads(Path(config["canary_config"]["path"]).read_text())
    require(sha(config["canary_config"]["path"]) == config["canary_config"]["sha256"], "CAPTURE_CANARY_BINDING_DRIFT")
    canary_stocks = {stock["code"]: stock for stock in frozen_canary["stocks"]}
    canary_probe = json.loads(Path(config["sample_probe_config"]["path"]).read_text())
    require(sha(config["sample_probe_config"]["path"]) == config["sample_probe_config"]["sha256"], "CAPTURE_SAMPLE_BINDING_DRIFT")
    original_canary_stats = {sample["code"]: sample["native"]["stat"] for sample in canary_probe["samples"]}
    output = Path(config["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    identity = dict(capture_plan_sha256=canonical_sha({key: value for key, value in config.items()
                                                     if key != "attempt_name"}),
                    code_sha256=sha(__file__), source_binding=source_binding)
    save(output / "CAPTURE_IDENTITY.json", identity)
    run_dir = output / "executions" / config["attempt_name"]
    require(not run_dir.exists(), "CAPTURE_ATTEMPT_EXISTS_NO_BLIND_RETRY")
    run_dir.mkdir(parents=True)
    disk_before = shutil.disk_usage(output).free
    require(disk_before >= config["minimum_disk_reserve_bytes"] + config["maximum_total_capture_bytes"], "CAPTURE_DISK_RESERVE_INSUFFICIENT")
    save(run_dir / "START_OBSERVATION.json", dict(pid=os.getpid(), identity=identity, config_sha256=config_sha,
                                                disk_free_bytes=disk_before, **FLAGS))
    started = time.monotonic()
    total_new_bytes = 0
    selected_capture_bytes = 0
    reports, effective_stocks = [], []
    for item in rows:
        code = item["code"]
        entry = dict(code=code, native_path=item["native_candidate_path"])
        if code in canary_stocks:
            entry.update(reuse_canary_stock=canary_stocks[code], reused_original_native_stat=original_canary_stats[code])
        entry_identity = canonical_sha(dict(entry=entry, source_binding=source_binding,
                                           maximum_file_bytes=config["maximum_file_bytes"], code_sha256=identity["code_sha256"]))
        checkpoint = output / "checkpoints" / (code + "." + entry_identity + ".json")
        if checkpoint.exists():
            report = json.loads(checkpoint.read_text())
            binding = report.get("effective_native")
            if binding is not None:
                require(sha(binding["path"]) == binding["sha256"], "CAPTURE_CHECKPOINT_BYTES_DRIFT:" + code)
            # Captured snapshots retain their recorded vintage. A changed
            # original stat gets a new checkpoint, never an overwrite.
            previous = report.get("native_stat_after", report.get("native_stat"))
            try:
                current = file_stat(entry["native_path"]) if Path(entry["native_path"]).is_file() else None
            except OSError as exc:
                current = dict(stat_error=repr(exc))
            if current != previous:
                entry_identity = canonical_sha(dict(previous_identity=entry_identity, current_source_stat=current))
                checkpoint = output / "checkpoints" / (code + "." + entry_identity + ".json")
                report = capture_native_entry(entry, output, min(config["maximum_file_bytes"],
                                              config["maximum_total_capture_bytes"] - selected_capture_bytes))
                save(checkpoint, report)
            else:
                report = {**report, "checkpoint_reused_without_original_reread": True}
        else:
            report = capture_native_entry(entry, output, min(config["maximum_file_bytes"],
                                          config["maximum_total_capture_bytes"] - selected_capture_bytes))
            save(checkpoint, report)
        if not report.get("checkpoint_reused_without_original_reread"):
            total_new_bytes += report.get("captured_original_bytes", {}).get("bytes", 0)
        selected_capture_bytes += report.get("captured_original_bytes", {}).get("bytes", 0)
        require(selected_capture_bytes <= config["maximum_total_capture_bytes"], "CAPTURE_SELECTED_BYTE_CAP_EXCEEDED")
        require(total_new_bytes <= config["maximum_total_capture_bytes"], "CAPTURE_TOTAL_BYTE_CAP_EXCEEDED")
        reports.append(report)
        if code in canary_stocks:
            stock = {"code": code, "sources": [dict(value) for value in canary_stocks[code]["sources"] if value["name"] == "archive"]}
        else:
            archive = item["archive"]
            require(archive is not None, "ARCHIVE_COVERAGE_CHANGED_SINCE_SOURCE_LIST")
            stock = dict(code=code, sources=[dict(name="archive", **archive)])
        if report["effective_native"] is not None:
            stock["sources"].append(report["effective_native"])
        stock["sources"].sort(key=lambda value: value["name"])
        effective_stocks.append(stock)
        save(run_dir / ("progress_" + f"{len(reports):05d}" + ".json"),
             dict(completed_keys=len(reports), latest_code=code, checkpoint=str(checkpoint))) if len(reports) % 250 == 0 else None
    issues = [report for report in reports if report["state"] not in
              {"REUSED_ORIGINAL_CANARY_CAPTURE", "NATIVE_CAPTURED_STABLE_BYTES",
               "REUSED_CANARY_CAPTURE_STAT_CHANGED_BYTES_IDENTICAL"}]
    rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    result = dict(schema="V194_EFFECTIVE_RAW_SOURCE_INPUT_MANIFEST_V1",
                  status="NATIVE_INPUT_CAPTURE_COMPLETE_SOURCE_COVERAGE_REVIEW_REQUIRED",
                  identity=identity, research_code_count=5533, stocks=effective_stocks,
                  config_sha256=config_sha,
                  capture_reports=reports, source_issues=issues,
                  source_issue_count=len(issues), keys_dropped=0,
                  reused_canary_codes=[report["code"] for report in reports if report["state"].startswith("REUSED_")],
                  original_native_files_read=sum(report["new_original_files_read"] for report in reports
                      if not report.get("checkpoint_reused_without_original_reread")),
                  new_bytes_captured_this_attempt=total_new_bytes,
                  selected_native_capture_bytes=selected_capture_bytes,
                  archive_members_reopened=0, price_records_decoded=0,
                  elapsed_seconds=time.monotonic()-started,
                  process_peak_rss_bytes=rss if sys.platform == "darwin" else rss * 1024,
                  disk_free_before=disk_before, disk_free_after=shutil.disk_usage(output).free,
                  original_inventory_classification=source["source_coverage_summary"],
                  authority_status="DERIVED_LOCAL_CAPTURE_ONLY_NOT_SHARED_AUTHORITY_OR_QFQ_FIT_INPUT",
                  labels_computed=0, formula_evaluations=0, model_fits=0, pointer_writes=0, **FLAGS)
    save(run_dir / "EFFECTIVE_SOURCE_MANIFEST.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args()
    require(sha(args.config) == args.config_sha256, "CAPTURE_CONFIG_SHA_DRIFT")
    result = execute(json.loads(args.config.read_text()), args.config_sha256)
    print(json.dumps(dict(status=result["status"], keys=result["research_code_count"],
                          source_issues=result["source_issue_count"], keys_dropped=0)), flush=True)


if __name__ == "__main__":
    main()
