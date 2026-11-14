"""Read the full 2026-11-16 natural session under the released storage contract."""
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
import argparse
import csv
import functools
import hashlib
import json
import os
import re
import subprocess
import time
import traceback

import natural_receipt as scan


DAY = "20261116"
STAGES = {
    "STAGE_0925": ("A_SHARE", "HK_CONNECT"),
    "STAGE_0930_0935": ("A_SHARE", "HK_CONNECT"),
    "STAGE_0935_0940": ("A_SHARE", "HK_CONNECT"),
    "STAGE_0940_0945": ("A_SHARE", "HK_CONNECT"),
    "STAGE_0945_1030": ("A_SHARE", "HK_CONNECT"),
    "STAGE_1300_1315": ("A_SHARE", "HK_CONNECT"),
    "STAGE_1445_1500": ("A_SHARE", "HK_CONNECT"),
    "STAGE_1545_1555": ("HK_CONNECT",),
}
FINAL_STAGE = "STAGE_1545_1555"
DAILY_SLOTS = ("1540", "1610", "1640")
SCHEDULER_ACTIVE = {"RUNNING", "QUEUED", "QUEUED_BEHIND"}
WORKBENCH_ACTIVE = {"RUNNING", "QUEUED"}
REGISTRY_ACTIVE = {"RUNNING", "VALIDATING"}
DEFER_ROLLBACK = ("KEEP_RUNNING", "CUTOVER_LOCK_BUSY", "STAGE_IS_RUNNING",
                  "NEAR_CUTOVER", "CHILD_IN_PROGRESS")
STAGE_REFS = ("artifact", "manifest", "receipt")
STAGE_TRIO_SCHEMA = "stage_center.runner.selection_binding.v1"
ENTRY_SCHEMA = "v4.runtime_execution_entry.v1"
MAX_STAGE_FILES = 96
MAX_STAGE_ARTIFACT = 32 * 1024**2
BYTES_SCOPE = "Exact payload bytes and allocated blocks of retained artifacts; not aggregate syscall writes."


def files(folder, pattern, budget=MAX_STAGE_FILES):
    paths = []
    for path in folder.glob(pattern):
        if len(paths) == budget:
            raise ValueError(f"Owner evidence file count exceeds budget: {folder}")
        paths.append(path)
    return sorted(paths)


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        point = datetime.fromisoformat(value)
    except ValueError:
        return None
    return point.astimezone(scan.TZ) if point.tzinfo is not None else None


def within_day(value, day):
    instant = timestamp(value)
    return instant is not None and instant.strftime("%Y%m%d") == day


def from_relative(root, value):
    if not isinstance(value, str):
        raise ValueError("OWNER_REFERENCE_PATH_INVALID")
    rel = PurePosixPath(value)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts or str(rel) != value:
        raise ValueError("OWNER_REFERENCE_PATH_INVALID")
    target = root.joinpath(*rel.parts)
    if target.resolve(strict=True) != target:
        raise ValueError("OWNER_REFERENCE_PATH_INVALID")
    return target


def candidate_receipts(folder, day, stage):
    # Keep original write receipts when a later attempt updates the stage pointer.
    current = folder / "receipt.json"
    candidates = []
    if current.is_file():
        row = scan.limited(current)
        candidates.append((current, row, None))
        history = row.get("receipt_history") or {}
        if history.get("schema_version") == "stage_center.runner.history_ref.v1":
            try:
                archived = from_relative(folder.parent.parent, history["relative_path"])
                if archived.is_relative_to(folder) and scan.info(archived)["sha256"] == history["sha256"]:
                    archived_body = scan.limited(archived)
                    if archived_body == {key: value for key, value in row.items() if key != "receipt_history"}:
                        candidates[0] = (current, row, scan.info(archived))
            except (OSError, ValueError, TypeError, KeyError):
                pass
    for path in files(folder / "attempt_evidence", "recorded-*/RECEIPT.json"):
        checksum = path.parent.name.removeprefix("recorded-")
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            continue
        if any(ref is not None and ref["path"] == str(path) for _, _, ref in candidates):
            continue
        ref = scan.info(path)
        if ref["sha256"] != checksum:
            continue
        value = scan.limited(path)
        if (value.get("trade_date"), value.get("stage_id")) == (day, stage):
            candidates.append((path, value, ref))
    return candidates


def executor_entries(graph, folder, day, stage, expected):
    result = {}
    for path in files(graph / "entry_observations" / day / "STAGE_CENTER" / stage, "*.json"):
        row = scan.limited(path)
        actor = Path(row.get("caller_file", ""))
        if (row.get("schema_version") != ENTRY_SCHEMA or row.get("owner") != "STAGE_CENTER"
                or row.get("phase") != "EXECUTOR_ENTERED" or row.get("node_id") != stage
                or row.get("business_date") != day or not within_day(row.get("observed_at"), day)
                or not scan.truth(row) or not actor.is_relative_to(expected) or not actor.is_file()
                or scan.info(actor)["sha256"] != row.get("caller_sha256")):
            continue
        attempt = row.get("run_id")
        source = Path(row.get("source_path", ""))
        if not isinstance(attempt, str) or not source.is_relative_to(folder) or not source.is_file():
            continue
        start = scan.limited(source)
        if (start.get("schema") != "stage.attempt_diagnostic.v1" or start.get("event") != "START"
                or start.get("attempt_id") != attempt or start.get("stage_id") != stage
                or start.get("trade_date") != day or start.get("pid") != row.get("pid")
                or start.get("due_status") != "DUE"):
            continue
        result.setdefault(attempt, []).append((path, row, source))
    return result


def linked_execution(folder, day, stage, body, entries):
    diagnostic = body.get("attempt_diagnostic") or {}
    attempt = diagnostic.get("attempt_id")
    allowed = diagnostic.get("relative_paths") or []
    if (body.get("dispatch_mode") != "NATURAL" or body.get("due_status") != "DUE"
            or body.get("record_time_source") != "OWNER_WRITE_CLOCK_UTC"
            or body.get("trade_date") != day or body.get("stage_id") != stage
            or not scan.truth(body) or not within_day(body.get("recorded_at"), day)):
        return None
    for entry_path, entry, start in entries.get(attempt, ()):
        if start.relative_to(folder).as_posix() not in allowed:
            continue
        for relative in allowed:
            if not isinstance(relative, str) or not relative.endswith("_RETURN.json"):
                continue
            ret_path = from_relative(folder, relative)
            ret = scan.limited(ret_path)
            if (ret.get("schema") == "stage.attempt_diagnostic.v1" and ret.get("event") == "RETURN"
                    and ret.get("attempt_id") == attempt and ret.get("stage_id") == stage
                    and ret.get("trade_date") == day and ret.get("pid") == entry.get("pid")
                    and ret.get("due_status") == "DUE"
                    and (ret.get("detail") or {}).get("status") == body.get("status")):
                return {"attempt_id": attempt, "pid": entry["pid"], "entered_at": entry["observed_at"],
                        "entry": scan.info(entry_path), "start": scan.info(start),
                        "return": scan.info(ret_path)}
    return None


@functools.lru_cache(maxsize=128)
def csv_rows(path, sha, size):
    if size > MAX_STAGE_ARTIFACT:
        raise ValueError("SELECTION_ARTIFACT_EXCEEDS_READ_BUDGET")
    with path.open(encoding="utf-8", newline="") as stream:
        count = sum(1 for _ in csv.DictReader(stream))
    if scan.info(path)["sha256"] != sha:
        raise ValueError("SELECTION_ARTIFACT_CHANGED_DURING_READ")
    return count


def stage_selection(root, day, stage, market, lane, bound):
    if not isinstance(lane, dict):
        return {"status": "MISSING_EXPECTED_MARKET"}
    result = {"lane_status": lane.get("status") or lane.get("selection_status"),
              "reported_rows": lane.get("selected_rows"), "run_id": lane.get("run_id"),
              "gaps": lane.get("cannot_confirm") or lane.get("gaps") or []}
    if not lane.get("run_id"):
        return {**result, "status": "NO_SELECTION_RUN_AT_OWNER_WRITE"}
    if not isinstance(bound, dict) or bound.get("schema_version") != STAGE_TRIO_SCHEMA:
        return {**result, "status": "SELECTION_TRIO_NOT_BOUND_AT_OWNER_WRITE"}
    keys = ("run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256", "selected_rows")
    if ((bound.get("trade_date"), bound.get("stage_id"), bound.get("market")) != (day, stage, market)
            or any(bound.get(key) != lane.get(key) for key in keys)):
        raise ValueError("STAGE_SELECTION_IDENTITY_MISMATCH")
    if (not isinstance(bound["selected_rows"], int) or bound["selected_rows"] < 0
            or not re.fullmatch(r"run-[0-9a-f]{24}", bound["run_id"])):
        raise ValueError("STAGE_SELECTION_IDENTITY_MISMATCH")
    parent = f"selection_runs/{day}/{market}_SELECTION_{stage}/{bound['run_id']}"
    expected_paths = dict(artifact=parent + "/artifact.csv", manifest=parent + "/manifest.json",
                          receipt=parent + "/receipt.json")
    result["files"] = {}
    for key in STAGE_REFS:
        if bound.get(key + "_relative") != expected_paths[key]:
            raise ValueError("STAGE_SELECTION_IDENTITY_MISMATCH")
        file = from_relative(root, bound[key + "_relative"])
        ref = scan.info(file)
        if ref["sha256"] != bound.get(key + "_bytes_sha256"):
            raise ValueError("STAGE_SELECTION_SHA_MISMATCH")
        if key != "artifact":
            payload = scan.limited(file)
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                   allow_nan=False).encode()
            if hashlib.sha256(canonical).hexdigest() != bound.get(key + "_canonical_sha256"):
                raise ValueError("STAGE_SELECTION_CANONICAL_SHA_MISMATCH")
        else:
            actual_rows = csv_rows(file, ref["sha256"], ref["bytes"])
            if actual_rows != bound["selected_rows"]:
                raise ValueError("STAGE_SELECTION_ROW_COUNT_MISMATCH")
            result["rows"] = actual_rows
        result["files"][key] = ref
    return {**result, "status": "OWNER_SELECTION_TRIO_VERIFIED"}


def stage_result(data, day, expected):
    results = []
    for stage, markets in STAGES.items():
        folder = data["stage_receipts"] / day / stage
        entries = executor_entries(data["graph"], folder, day, stage, expected)
        owner_receipts = candidate_receipts(folder, day, stage)
        matched = {}
        for path, body, archive_ref in owner_receipts:
            execution = linked_execution(folder, day, stage, body, entries)
            if execution is None or execution["attempt_id"] in matched:
                continue
            picks = {}
            for market in markets:
                try:
                    picks[market] = stage_selection(data["stage_selection"], day, stage, market,
                        (body.get("markets") or {}).get(market), (body.get("selection_artifacts") or {}).get(market))
                except (OSError, ValueError, TypeError, KeyError) as error:
                    picks[market] = {"status": "CANNOT_CONFIRM_SELECTION_TRIO", "reason": str(error)}
            receipt_path = Path(archive_ref["path"]) if archive_ref else path
            matched[execution["attempt_id"]] = {
                "stage_id": stage, "status": body.get("status"), "mode": body["dispatch_mode"],
                "recorded_at": body["recorded_at"], "receipt": scan.info(receipt_path),
                "selection": picks, "execution": execution, "matched_natural": True,
                "source_failures": [kind for kind in scan.CONTRACT_FAILURES
                    if any(isinstance(value, str) and kind in value for value in body.get("source_evidence", ()))],
            }
        attempts = sorted(matched.values(), key=lambda row: timestamp(row["recorded_at"]), reverse=True)
        results.append({"stage_id": stage, "markets": list(markets), "attempts": attempts,
                        "matched_natural": bool(attempts),
                        **({"receipt": attempts[0]["receipt"]} if attempts else {}),
                        "gap": None if attempts else "NO_NATURAL_OWNER_WRITE_LINKED_TO_INSTALLED_STAGE",
                        "observed_unmatched_receipt_count": len(owner_receipts) if not attempts else None})
    return results


def scheduled_slots(data, day):
    out = {}
    for slot in DAILY_SLOTS:
        folder = data["ledger"] / "scheduler_observations" / "live" / day / slot
        observations = []
        for path in files(folder, "*.observation.json"):
            row = scan.limited(path)
            if (row.get("business_date") == day and row.get("slot") == slot and scan.truth(row)
                    and within_day(row.get("observed_at"), day)):
                observations.append({"status": row.get("status"), "observed_at": row["observed_at"],
                    "pid": row.get("pid"), "result_status": row.get("result_status"),
                    "actual_started_at": row.get("actual_started_at"), "receipt": scan.info(path)})
        out[slot] = max(observations, key=lambda row: timestamp(row["observed_at"]), default=None)
    return out


def registry_tasks(data, day):
    tasks = []
    since = scan.local(day).timestamp()
    end = since + 24 * 3600
    root = data["daily_product"]
    receipt_parent = data["daily_receipts"]
    for key, row in scan.limited(data["registry"])["tasks"].items():
        heartbeat = row.get("heartbeat", 0)
        path = Path(row["directory"])
        related = (path.is_relative_to(root)
            or path.is_relative_to(receipt_parent / "a_sync_authority" / day)
            or path.is_relative_to(receipt_parent.parent / "a_formula_runs"))
        if not related or not since <= heartbeat < end:
            continue
        result = row.get("result") or {}
        tasks.append({"key": key, "state": row.get("state"), "error": row.get("error"),
            "directory": str(path), "heartbeat": datetime.fromtimestamp(heartbeat, scan.TZ).isoformat(),
            "logical_written_bytes": row.get("logical_written_bytes"), "owner": row.get("owner"),
            "result": {k: result.get(k) for k in ("schema", "status", "target_date", "data_date",
                                                  "generation_id", "source_generation") if k in result}})
    return tasks


def daily_result(data, day):
    current = data["daily_receipts"] / f"a-{day}.json"
    status = current.stat() if current.is_file() else None
    projection = cached_daily(data["daily_product"], current, day, status.st_mtime_ns, status.st_ino) if status else {
        "status": "PENDING_OR_MISSING"}
    return {**projection, "registry_tasks": registry_tasks(data, day), "scheduler_slots": scheduled_slots(data, day)}


@functools.lru_cache(maxsize=8)
def cached_daily(owner, current, day, mtime, inode):
    # This exact receipt can be over 100 MiB. Reproject only when it changes.
    # Scan the history heads on the completed owner receipt, never while pending.
    row = scan.daily_projection(current)
    if row.get("target_date") != day or not scan.truth(row):
        raise ValueError("DAILY_OWNER_RECEIPT_IDENTITY_MISMATCH")
    product = row.get("daily_product") or {}
    receipt = scan.info(current)
    if (mtime, inode) != (current.stat().st_mtime_ns, current.stat().st_ino):
        raise ValueError("DAILY_OWNER_RECEIPT_CHANGED_DURING_READ")
    artifacts = {}
    for key in ("artifact", "manifest"):
        bound = product.get(key)
        if not isinstance(bound, dict) or not bound.get("sha256"):
            continue
        path = Path(bound["path"])
        if not path.is_relative_to(owner) or path.resolve(strict=True) != path:
            raise ValueError("DAILY_OWNER_ARTIFACT_PATH_INVALID")
        actual = scan.info(path)
        if actual["sha256"] != bound["sha256"]:
            raise ValueError("DAILY_OWNER_ARTIFACT_SHA_MISMATCH")
        artifacts[key] = actual
    history = scan.history_items(owner, day) if set(artifacts) == {"artifact", "manifest"} else {}
    heads = [ref for path, ref in history.items() if Path(path).name.startswith("head-")]
    deltas = [ref for path, ref in history.items() if Path(path).name.startswith("delta-")]
    return {"status": row.get("status"), "reason": row.get("reason"),
            "product_status": product.get("status"), "history_status": product.get("history_status"),
            "history_write_evidence": ("DATED_HISTORY_HEADS_PRESENT" if heads else "NO_HISTORY_WRITE_OBSERVED"),
            "input_generation": product.get("source_generation"), "receipt": receipt,
            "artifacts_written": artifacts, "history_files": len(history),
            "history_totals": {"head": byte_totals(heads), "delta": byte_totals(deltas)},
            "history_components": list(history.values()),
            **{key: product.get(key) for key in ("processed_count", "unique_count", "unknown_count")}}


def byte_totals(refs):
    distinct = {(ref["device"], ref["inode"]): ref for ref in refs}
    return {"files": len(distinct), "bytes": sum(ref["bytes"] for ref in distinct.values()),
            "allocated_bytes": sum(ref["allocated_bytes"] for ref in distinct.values())}


def refs_from(row, keys):
    return [row[key] for key in keys if isinstance(row.get(key), dict) and "bytes" in row[key]]


def workbench_writes(rows, day):
    classified = {"session_attempts": [], "session_checkpoints": [], "session_input_blobs": [],
                  "preexisting_referenced": [], "session_result_files": []}
    for row in rows:
        for key in ("attempt", "input_checkpoint", "publish_checkpoint", "input_body", "final_plan"):
            item = row.get(key)
            if not item:
                continue
            if (not within_day(item.get("mtime"), day) or (key == "input_body" and row.get("input_body_reused"))
                    or (key == "final_plan" and row.get("reused_prior_run_without_input_write"))):
                bucket = "preexisting_referenced"
            else:
                bucket = {"attempt": "session_attempts", "input_checkpoint": "session_checkpoints",
                          "publish_checkpoint": "session_result_files", "input_body": "session_input_blobs",
                          "final_plan": "session_result_files"}[key]
            classified[bucket].append(item)
        for blob in row.get("shared_blobs", ()):
            key = "preexisting_referenced" if blob["present_before_trade_day"] or not within_day(
                blob.get("mtime"), day) else "session_input_blobs"
            classified[key].append(blob)
    return {name: byte_totals(values) for name, values in classified.items()}


def stage_writes(rows, day):
    sets = {"verified_selection_trios": [], "owner_receipts": [], "execution_evidence": [],
            "preexisting_referenced": []}

    def add(bucket, refs):
        for ref in refs:
            key = bucket if within_day(ref.get("mtime"), day) else "preexisting_referenced"
            sets[key].append(ref)

    for stage in rows:
        for attempt in stage["attempts"]:
            add("owner_receipts", [attempt["receipt"]])
            add("execution_evidence", refs_from(attempt["execution"], ("entry", "start", "return")))
            for selection in attempt["selection"].values():
                add("verified_selection_trios", selection.get("files", {}).values())
    return {key: byte_totals(values) for key, values in sets.items()}


def late_workbench(row, day):
    if row.get("phase") != "NEXT_DAY" or row.get("target_date", "") <= day:
        return False
    point = timestamp(row.get("started_at"))
    return row.get("source_hk_session") == day or (point is not None
        and scan.local(day) + timedelta(hours=16, minutes=30) <= point < scan.local(day) + timedelta(days=1))


def proved_workbench(row):
    return row["state"] in {"SUCCEEDED", "PARTIAL"} and not row.get("storage_failure") and (
        row.get("hydrated_logical_sha_verified") or row.get("reused_prior_run_without_input_write"))


def evidence_status(report, day):
    stages = report.get("stage", [])
    seen = {stage["stage_id"] for stage in stages if stage["matched_natural"]}
    final_close = any(
        item.get("status") == "OWNER_SELECTION_TRIO_VERIFIED"
        for stage in stages if stage["stage_id"] == FINAL_STAGE
        for attempt in stage["attempts"] for market, item in attempt["selection"].items()
        if market == "HK_CONNECT"
    )
    workbench = report.get("workbench", [])
    active_jobs = [row["job_id"] for row in workbench if row["state"] in WORKBENCH_ACTIVE]
    active_jobs.extend(row["job_id"] for row in report.get("workbench_unentered_active_claims", ()))
    daily = report.get("formal_daily", {})
    pending_daily = [task["key"] for task in daily.get("registry_tasks", ()) if task["state"] in REGISTRY_ACTIVE]
    slots = daily.get("scheduler_slots", {})
    pending_slots = [slot for slot, item in slots.items() if item and item["status"] in SCHEDULER_ACTIVE]
    missing_slots = [slot for slot in DAILY_SLOTS if not slots.get(slot)]
    success = [row["run_id"] for row in report.get("main_dispatch", ())
               if row["native_start_seen"] and "research_panel_daily_a" in (row["successful_workload_ids"] or ())
               and any(task["id"] == "research_panel_daily_a" and str(task["target_date"]) == day
                       for task in row["workload"])]
    proved_daily = bool(success) and set(daily.get("artifacts_written", {})) == {"artifact", "manifest"}
    late = [row["job_id"] for row in workbench if late_workbench(row, day) and proved_workbench(row)]
    gaps = []
    market_gaps = []
    missing_trios = []
    for stage in stages:
        for market in stage["markets"]:
            statuses = {attempt["selection"][market]["status"] for attempt in stage["attempts"]
                        if market in attempt["selection"]}
            if "OWNER_SELECTION_TRIO_VERIFIED" in statuses:
                continue
            if statuses:
                detail = {"stage_id": stage["stage_id"], "market": market, "statuses": sorted(statuses)}
                market_gaps.append(detail)
                if statuses & {"CANNOT_CONFIRM_SELECTION_TRIO", "SELECTION_TRIO_NOT_BOUND_AT_OWNER_WRITE"}:
                    missing_trios.append(detail)
    if seen != STAGES.keys():
        gaps.append({"kind": "STAGE_NATURAL_LINK_MISSING", "stages": sorted(STAGES.keys() - seen)})
    if not final_close:
        gaps.append({"kind": "FINAL_STAGE_HK_SELECTION_WRITE_UNPROVEN"})
    if not late:
        gaps.append({"kind": "WORKBENCH_POST_CLOSE_OWNER_WRITE_UNPROVEN"})
    if not proved_daily:
        gaps.append({"kind": "A_DAILY_DISPATCH_AND_ARTIFACTS_UNPROVEN"})
    if missing_trios:
        gaps.append({"kind": "EXPECTED_STAGE_SELECTION_TRIO_UNPROVEN", "markets": missing_trios})
    return {"complete": not (gaps or active_jobs or pending_daily or pending_slots),
            "gaps": gaps, "stages_linked": len(seen), "final_stage_hk_verified": final_close,
            "late_workbench_jobs": late, "active_workbench_jobs": active_jobs,
            "active_daily_registry_tasks": pending_daily, "active_daily_slots": pending_slots,
            "unobserved_optional_daily_slots": missing_slots,
            "stage_market_selection_gaps": market_gaps,
            "daily_dispatch_run_ids": success}


def enrich_workbench(rows, data, day):
    # Old collector already binds the installed jobs.py SHA and natural
    # scheduler context. Recover the genuine stage/task and late-run fields.
    filtered = []
    for row in rows:
        entry = scan.limited(Path(row["owner_execution_entry"]["path"]))
        if entry.get("phase") != "EXECUTOR_ENTERED" or entry.get("owner") != "MANAGER_WORKBENCH":
            continue
        if not scan.truth(entry) or not within_day(entry.get("observed_at"), day):
            continue
        if (entry.get("schema_version") != ENTRY_SCHEMA or entry.get("node_id") != "manager_workbench"
                or entry.get("source_path") != row["attempt"]["path"] or entry.get("run_id") != row["job_id"]
                or entry.get("business_date") != row["target_date"]):
            continue
        value = scan.limited(Path(row["attempt"]["path"]))
        context = value.get("context") or {}
        scope = context.get("scope_refs") or {}
        if value.get("started_at") != row.get("started_at") or value.get("state") != row.get("state"):
            continue
        row["entered_at"] = entry["observed_at"]
        row["requested_lanes"] = scope.get("requested_lanes") or []
        if row.get("reused_prior_run_without_input_write") and "final_plan" not in row:
            row["reused_prior_run_without_input_write"] = False
        filtered.append(row)
    return filtered


def queued_workbench(data, day, rows):
    """Report queued same-session claims before they can emit EXECUTOR_ENTERED."""
    already_seen = {row["job_id"] for row in rows}
    states = []
    wb = data["workbench"]
    for path in files(wb / "claims", "*.json", budget=4096):
        if not within_day(datetime.fromtimestamp(path.stat().st_mtime, scan.TZ).isoformat(), day):
            continue
        claim = scan.limited(path)
        job = claim.get("job_id")
        if not isinstance(job, str) or not re.fullmatch(r"[0-9a-f]{32}", job) or job in already_seen:
            continue
        attempt = wb / "attempts" / (job + ".json")
        if not attempt.is_file():
            continue
        item = scan.limited(attempt)
        context = item.get("context") or {}
        scope = context.get("scope_refs") or {}
        if (item.get("job_id") == job and item.get("state") in WORKBENCH_ACTIVE
                and context.get("trigger") == "SCHEDULED"
                and (context.get("target_date") == day or (context.get("phase") == "NEXT_DAY"
                        and scope.get("source_hk_session") == day))):
            states.append({"job_id": job, "state": item["state"], "claim": scan.info(path),
                           "attempt": scan.info(attempt), "target_date": context["target_date"]})
    return states


def checked_baseline(day):
    path = scan.MONITOR / "BASELINE.json"
    baseline = scan.limited(path)
    if baseline["date"] != day or baseline["activation"]["sha256"] != scan.info(scan.ACTIVATION)["sha256"]:
        raise ValueError("NATURAL_BASELINE_BINDING_DRIFT")
    return baseline


def collect(day, baseline):
    # Use the old collector's exact deployed identity, local health contract,
    # workbench input hydration, business dispatch and fault classification.
    readers = scan.stage_result, scan.workbench_result, scan.daily_result
    scan.stage_result = stage_result
    scan.workbench_result = lambda data, target, expected, base: enrich_workbench(
        readers[1](data, target, expected, base), data, target)
    scan.daily_result = daily_result
    try:
        row = scan.check_once(day, baseline)
    finally:
        scan.stage_result, scan.workbench_result, scan.daily_result = readers
    row["observer"] = "NATURAL_FULL_SESSION_V1"
    if "workbench" in row:
        data = {key: Path(path) for key, path in baseline["roots"].items()}
        row["workbench_unentered_active_claims"] = queued_workbench(data, day, row["workbench"])
    row["session_evidence"] = evidence_status(row, day)
    for stage in row.get("stage", ()):
        for attempt in stage["attempts"]:
            for reason in attempt["source_failures"]:
                row["release_storage_failures"].append({"kind": reason, "stage_id": stage["stage_id"]})
    row["release_storage_failures"] = sorted(
        {json.dumps(fault, sort_keys=True): fault for fault in row.get("release_storage_failures", ())}.values(),
        key=lambda fault: json.dumps(fault, sort_keys=True),
    )
    return row


def observed(day, baseline):
    try:
        return collect(day, baseline)
    except Exception as error:
        row = {"status": "PROBE_ERROR", "observer": "NATURAL_FULL_SESSION_V1", "trade_date": day,
               "observed_at": scan.instant().isoformat(), "error": repr(error),
               "traceback": traceback.format_exc()}
        health_tokens = ("LIVE_PROCESS_NOT_READY", "API_SMOKE_STATUS",
                         "Connection refused", "API_HEALTH_BODY_DRIFT")
        try:
            unloaded = "LIVE_LAUNCHD_PATH_DRIFT" in str(error) and any(
                not scan.release.state(role)[0]["loaded"] for role in scan.release.ROLE)
            activation = scan.limited(scan.ACTIVATION)["after"]["roles"]
            identity = all(scan.release.sha(scan.release.live(role)) == activation[role]["plist"]["sha256"]
                           for role in scan.release.ROLE)
        except (OSError, RuntimeError, KeyError, subprocess.TimeoutExpired):
            identity, unloaded = False, False
        if (isinstance(error, (OSError, RuntimeError)) and identity
                and (unloaded or any(token in str(error) for token in health_tokens))):
            row["release_storage_failures"] = [{"kind": "REPEATED_DEPLOYED_RUNTIME_HEALTH_FAILURE"}]
        return row


def finish_status(report, day, at):
    evidence = report.get("session_evidence") or {}
    date = scan.local(day)
    if (at >= date + timedelta(hours=17, minutes=15) and evidence.get("complete")
            and not report.get("release_storage_failures")):
        return "NATURAL_SESSION_EVIDENCE_VERIFIED"
    if at >= date + timedelta(hours=23, minutes=58):
        return "TRADING_DAY_WINDOW_ENDED_WITH_MISSING_RECEIPTS"
    return None


def final_receipts(row, day):
    evidence = row.get("session_evidence") or evidence_status(row, day)
    headers = {"trade_date": day, "observed_at": row["observed_at"], "session_status": row["status"],
               "bytes_scope": BYTES_SCOPE, "RESEARCH_ONLY": True,
               "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
               "auto_gc_enabled": False}
    stage = row.get("stage", [])
    workbench = row.get("workbench", [])
    daily = row.get("formal_daily", {})
    daily_refs = refs_from(daily, ("receipt",)) + list(daily.get("artifacts_written", {}).values())
    daily_history = daily.get("history_components", [])
    reports = {
        "STAGE_WRITE_RECEIPT.json": {**headers, "stages": stage, "stages_linked": evidence["stages_linked"],
            "final_stage_hk_verified": evidence["final_stage_hk_verified"], "totals": stage_writes(stage, day),
            "market_selection_gaps": evidence["stage_market_selection_gaps"]},
        "MWB_WRITE_RECEIPT.json": {**headers, "attempts": workbench, "totals": workbench_writes(workbench, day),
            "post_close_jobs": evidence["late_workbench_jobs"], "active_jobs": evidence["active_workbench_jobs"],
            "unentered_active_claims": row.get("workbench_unentered_active_claims", [])},
        "A_DAILY_WRITE_RECEIPT.json": {**headers, "owner": daily, "dispatch_attempts": row.get("main_dispatch", []),
            "successful_dispatch_ids": evidence["daily_dispatch_run_ids"], "totals": byte_totals(
                ref for ref in [*daily_refs, *daily_history] if within_day(ref.get("mtime"), day)),
            "preexisting_referenced": byte_totals(
                ref for ref in [*daily_refs, *daily_history] if not within_day(ref.get("mtime"), day))},
    }
    result = {}
    for name, report in reports.items():
        path = scan.MONITOR / name
        scan.release.save(path, report)
        result[name] = scan.info(path)
    summary = {"status": row["status"], "trade_date": day, "observed_at": row["observed_at"],
               "session_evidence": evidence, "write_receipts": result, "bytes_scope": BYTES_SCOPE,
               "release_storage_failures": row.get("release_storage_failures", ()),
               **{key: row[key] for key in ("rollback", "rollback_error", "error") if key in row}}
    scan.release.save(scan.MONITOR / "NATURAL_RESULT.json", summary)
    directory = os.open(scan.MONITOR, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def monitor(day, mode):
    scan.check_day(day)
    baseline = checked_baseline(day)
    latest_path = scan.MONITOR / "LATEST.json"
    deadline = scan.local(day) + timedelta(hours=23, minutes=58)
    signature, strikes = None, 0
    previous_good = None
    if latest_path.is_file():
        previous = scan.limited(latest_path)
        if previous.get("observer") == "NATURAL_FULL_SESSION_V1" and previous.get("status") == "OBSERVING":
            previous_good = previous
    while True:
        row = observed(day, baseline)
        if row["status"] == "OBSERVING":
            previous_good = row
        scan.release.save(latest_path, row)
        if mode == "once":
            print(json.dumps({"status": row["status"], "at": row["observed_at"],
                              "session_evidence": row.get("session_evidence")}, ensure_ascii=False))
            return
        faults = row.get("release_storage_failures", [])
        current = json.dumps(faults, sort_keys=True)
        strikes = (strikes + 1 if current == signature else 1) if faults else 0
        signature = current
        status = None
        if strikes >= 2:
            scan.release.save(scan.MONITOR / "ROLLBACK_TRIGGER.json", {
                "reason": "VERIFIED_RELEASE_STORAGE_FAILURE", "checks": faults, "observed_at": scan.instant().isoformat()})
            try:
                row["rollback"] = scan.release.operation("rollback")
                status = "ROLLED_BACK_COMPAT"
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                reason = str(error)
                scan.release.save(scan.MONITOR / "ROLLBACK_ATTEMPT.json", {
                    "status": "DEFERRED_OR_FAILED", "reason": reason, "at": scan.instant().isoformat()})
                if not any(token in reason for token in DEFER_ROLLBACK):
                    status = "COMPAT_ROLLBACK_CANNOT_CONFIRM"
                    row["rollback_error"] = reason
        status = status or finish_status(row, day, scan.instant())
        if status:
            information = dict(previous_good or {})
            information.update(row, status=status)
            final_receipts(information, day)
            return
        if scan.instant() < scan.local(day) + timedelta(hours=8):
            interval = 1800
        else:
            interval = 540
        # Wake at the day-end bound even when the last observation was recent.
        time.sleep(min(interval, max(0, (deadline - scan.instant()).total_seconds())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("day", choices=(DAY,))
    parser.add_argument("mode", choices=("once", "monitor"))
    args = parser.parse_args()
    monitor(args.day, args.mode)
