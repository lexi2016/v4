"""Low-frequency, single-session Dot entry points for the original V5 release."""
from argparse import ArgumentParser
from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
import gzip
import io
import json
import os
import shutil
import tempfile
import zipfile

from dot_connector import (ROLES, action, create_journal, journal_file, load_plan, object_name, pinned_path, plan_path,
                           remote_inputs, save_plan)
from dot_runtime import (BJT, CONFIG, admit_slot, backfill_source, capture_g4, capture_source, load_runtime,
                         market_day, parse_day, stage_g4, today)
from dot_state import FLAGS, Board, artifact, atomic, digest, json_bytes, mkdir, read_pin, require, writer_lock

HANDLED = (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError, ImportError, RuntimeError, zipfile.BadZipFile)
BACKFILL_FLAGS = {"backfill": True, "natural_verified": False}


def utc_result(parent, node, reason):
    return {"schema": "V5_DOT_RUN_V1", "status": "BLOCKED", "business_date": parent, "phase": node,
            "reason": reason, "publication": "NOT_RUN", **FLAGS}


def brief(exc):
    if isinstance(exc, OSError):
        return type(exc).__name__ + ":" + str(exc.errno)
    return str(exc).strip()[:220] or type(exc).__name__


def seed(board, intake):
    pin = CONFIG["original_board"]
    return board.seed(pin["date"], pin, "PINNED_ORIGINAL_DRIVE:" + pin["drive_id"],
                      lambda: read_pin(intake, pin))


def owner_binding(journal_id, journal_sha256, current_sha256):
    pin = CONFIG["original_board"]
    return {"schema": "V5_DOT_DURABLE_STATE_V1", "seed_date": pin["date"], "seed_sha256": pin["sha256"],
            "seed_drive_id": pin["drive_id"], "parent": CONFIG["parent"], "journal_id": journal_id,
            "journal_sha256": journal_sha256, "current_sha256": current_sha256, **FLAGS}


def open_live_board(state):
    try:
        marker = state / "DOT_OWNER.json"
        _, journal = journal_file(state)
        owner = json.loads(marker.read_bytes())
        require(owner == owner_binding(journal["journal_id"], digest(json_bytes(journal)), owner["current_sha256"]),
                "DOT_OWNER_RECORD")
        board = Board(state, writable=False, bind_pointer=True)
        good = board.current()["last_success"]
        if good["origin"].startswith("PINNED_ORIGINAL_DRIVE:"):
            anchor = CONFIG["original_board"]
            require(good["origin"] == "PINNED_ORIGINAL_DRIVE:" + anchor["drive_id"]
                    and good["data_date"] == anchor["date"]
                    and good["raw"]["sha256"] == anchor["sha256"]
                    and good["raw"]["bytes"] == anchor["bytes"], "ORIGINAL_BOARD_PIN")
        return board
    except HANDLED as exc:
        raise ValueError("DURABLE_STATE_RESTORE_REQUIRED:" + brief(exc)) from None


def initialize(intake, state):
    marker = state / "DOT_OWNER.json"
    if marker.exists():
        current = open_live_board(state).current()
        return {"status": "STATE_ALREADY_INITIALIZED", "data_date": current["last_success"]["data_date"], **FLAGS}
    require({path.name for path in state.iterdir()} <= {"writer.lock"}, "DURABLE_STATE_RESTORE_REQUIRED")
    board = Board(state)
    original = seed(board, intake)
    atomic(marker, json_bytes(owner_binding(*create_journal(state), digest(board.pointer.read_bytes()))))
    return {"status": "STATE_INITIALIZED", "data_date": original["data_date"],
            "original_sha256": original["raw"]["sha256"], **FLAGS}


def record_stale(board, day, reason):
    try:
        value = board.fail(day, reason)
    except HANDLED as exc:
        return {"stale": True, "data_date": None, "attempted_date": day,
                "reason": reason + " · LAST_GOOD_UNAVAILABLE:" + brief(exc), "view": None, **FLAGS}
    return {key: value[key] for key in ("stale", "data_date", "attempted_date", "reason", "view")}


def artifact_pin(state, path, ref):
    obj = {key: ref[key] for key in ("bytes", "sha256")} | {"path": path.relative_to(state).as_posix()}
    pinned_path(state, obj)
    return obj


def freeze_plan(state, day, run, computed):
    node = computed["node"]
    objects = {ref["role"]: artifact_pin(state, run / ref["path"], ref) for ref in computed["files"]}
    return save_plan(state, day, node, objects)


def get_remote(runtime, remote, receipt, role):
    return runtime.main.read_published(remote, receipt, role)


def remote_node(runtime, remote, day, node):
    if remote is None:
        return None
    name = object_name(day, node, "RECEIPT.json")
    receipt = remote.read_receipt(day, node)
    if any(entry["name"] == name for entry in remote.exact_list(runtime.driveio.PARENT, name)):
        require(receipt is not None, "CONNECTOR_RECEIPT_INVALID:" + node)
    return receipt


def close_files(state, day, runtime, remote, node):
    plan = load_plan(state, day, node)
    terminal = remote_node(runtime, remote, day, node)
    if terminal is not None:
        objects = terminal["objects"]
        require(set(objects) == ROLES[node], "REMOTE_CLOSE_OBJECT_SCOPE:" + node)
        if plan:
            require(all((objects[key]["bytes"], objects[key]["sha256"]) == (ref["bytes"], ref["sha256"])
                        for key, ref in plan["objects"].items()), "LOCAL_REMOTE_CLOSE_CONFLICT:" + node)
        return terminal["status"], objects, lambda role: get_remote(runtime, remote, terminal, role)
    if plan:
        return plan["status"], plan["objects"], lambda role: read_pin(state, plan["objects"][role])
    return None


def validate_top(day, runtime, info):
    status, objects, get = info
    require(status == "COMPUTED", "TOP200_STATUS")
    top = json.loads(get("TOP200.json"))
    source = json.loads(get("SOURCE.json"))
    g4 = get("G4.zip")
    require(source["business_date"] == day and source["g4"]["sha256"] == digest(g4)
            and source["g4"]["bytes"] == len(g4) and top["source_sha256"] == source["g4"]["sha256"]
            and top["business_date"] == day and top["scope"] == 5575 and len(top["ranking"]) == 200,
            "TOP200_SOURCE_DATE_SCOPE")
    sources = runtime.sources
    origin = source["g4"]
    require(origin["url"] == sources.RAWSOURCE.format(date=day) and origin["http_status"] == 200,
            "TOP200_G4_PROVENANCE")
    sources.admit_clock(origin["observed_at"], day, "G4")
    sources.zip_check(g4, day, "G4")
    return top, source["g4"], g4, objects


def validate_stock_member(raw, day, symbol, runtime):
    roles = ("STATE51", "DAY109", "FACTS", "TAIL", "DAY51")
    names = {f"{day}-{role}.json" for role in roles} | {"PRODUCER_PREFIX.json.gz"}
    with zipfile.ZipFile(io.BytesIO(raw)) as stock:
        require(len(stock.infolist()) == len(names) and set(stock.namelist()) == names, "PAR_INNER_STOCK_CONTRACT")
        state, value, facts, tail, day51 = [json.loads(stock.read(f"{day}-{role}.json")) for role in roles]
        prefix = json.loads(gzip.decompress(stock.read("PRODUCER_PREFIX.json.gz")))
    require(state["schema"] in ("EXACT_DAILY_STATE_MOTHER_CANDIDATE_V1", "v5.cloud.exact.daily.state.v1")
            and state["symbol"] == value["symbol"] == tail["symbol"] == symbol
            and state["last_date"] == day51["trade_date"] == int(day)
            and value["event_date"] == tail["event_date"] == day
            and state["count"] == facts["component_state"]["count"]
            and len(value["fields"]) == 109 and len(day51["values"]) == 51,
            "PAR_INNER_STOCK_DATE_OR_FIELDS")
    runtime.par.check_prefix(prefix, symbol, state["count"], day)
    require(prefix[-1] == tail, "PAR_INNER_STOCK_TAIL")
    return value


def validate_daily(day, previous, top, info, runtime):
    status, objects, get = info
    require(status == "COMPUTED_ISOLATED", "PAR_STATUS:" + status)
    value = json.loads(get("PAR_LEDGER.json"))
    sample = json.loads(get("SAMPLE109.json"))
    summary = json.loads(get("SUMMARY.json"))
    source = json.loads(get("SOURCE.json"))
    counts = Counter(row["status"] for row in value["rows"])
    require(value["business_date"] == summary["business_date"] == source["business_date"] == day
            and len(value["rows"]) == value["scope"] == summary["scope"] == 5575
            and len({row["symbol"] for row in value["rows"]}) == 5575
            and counts == summary["counts"] and counts["COMPUTED"] >= 5297
            and set(counts) <= {"COMPUTED", "ISOLATED"} and summary["status"] == status
            and summary["parent_date"] == previous and source["g4"]["sha256"] == top["source_sha256"]
            and objects["G4.zip"]["sha256"] == top["source_sha256"]
            and source["gbbq"]["sha256"] == objects["GBBQ.zip"]["sha256"]
            and sample and all(row["event_date"] == day and row["symbol"] == symbol
                               and len(row["fields"]) == 109 for symbol, row in sample.items()),
            "PAR_DATE_SCOPE_SOURCE_OR_COVERAGE")
    rights = source["gbbq"]
    raw_rights = get("GBBQ.zip")
    require(rights["url"] == runtime.sources.GBBQ and rights["http_status"] == 200
            and rights["bytes"] == len(raw_rights) and rights["sha256"] == digest(raw_rights),
            "PAR_GBBQ_PROVENANCE")
    runtime.sources.admit_clock(rights["observed_at"], day, "RIGHTS")
    runtime.sources.zip_check(raw_rights, day, "RIGHTS")
    decoder = runtime.par.module(runtime.main.ROOT / "vendor" / "gbbq_reader_fork_reference.py",
                                 runtime.par.DECODER_SHA, "dot_certify_gbbq")
    try:
        _, counts = runtime.par.observed_rights(raw_rights, day, decoder)
    except HANDLED as exc:
        raise ValueError("PAR_GBBQ_DECODE_REJECTED:" + type(exc).__name__) from exc
    require(source["right_counts"] == {str(market): count for market, count in counts.items()},
            "PAR_GBBQ_DECODE_COUNT_PIN")
    members = {index: {} for index in range(1, 9)}
    for row in value["rows"]:
        if row["status"] == "COMPUTED":
            require(row.get("fields") == 109 and row["part"] in members, "PAR_SHARD_LEDGER_ROW")
            members[row["part"]][row["symbol"] + ".zip"] = row
    for index, expected in members.items():
        with zipfile.ZipFile(io.BytesIO(get(f"PAR_STATE_{index:02d}.zip"))) as part:
            require(len(part.infolist()) == len(expected) and set(part.namelist()) == set(expected),
                    "PAR_SHARD_SCOPE")
            for member in part.infolist():
                row = expected[member.filename]
                stock_bytes = runtime.par.pin_member(part.read(member), row)
                stock_value = validate_stock_member(stock_bytes, day, row["symbol"], runtime)
                if row["symbol"] in sample:
                    require(sample[row["symbol"]] == stock_value, "PAR_INNER_SAMPLE_CONTENT")
    require({row["symbol"] for row in value["rows"] if row["status"] == "COMPUTED"} >= set(sample),
            "PAR_SAMPLE_STATUS")
    return value, sample, objects


class TopReadback:
    """Supply the already computed local Top200 bytes to the frozen daily-update route."""

    def __init__(self, day, info):
        self.day, self.info = day, info

    def read_receipt(self, day, node):
        if day == self.day and node == "a-top200":
            return {"objects": {role: {**ref, "name": role} for role, ref in self.info[1].items()}}
        return None

    def get(self, role, ref):
        return ref, self.info[2](role)


def build_prior(intake, run, day, previous, runtime):
    """Project the older original ledger and read-back parts into the frozen input catalog."""
    stage = intake / "stage"
    # The frozen source has one specific archive reader for its historic D27 reconstruction.
    if day == "20261127":
        accepted = CONFIG["accepted_close"]
        require(previous == CONFIG["original_board"]["date"], "LEGACY_PREVIOUS_TRADE_DATE")
        close_raw = read_pin(intake, accepted)
        catalog = json.loads(runtime.driveio.manifested(close_raw)["D26_PRIOR_CATALOG_DRIVE.json"])
        base = json.loads(runtime.map_raw)["assets"]
        refs = [ref for ref in base if ref["role"] in ("wave2b_d24_restore_parent", "h16_d25_shard_1",
                                                       "h16_d25_shard_2")
                or ref["role"].startswith("wave2b_shard_")]
        refs.extend(row["remote"] | {"drive_id": row["remote"]["id"]} for row in catalog["parts"])
        require(len(refs) == 33, "LEGACY_PAR_PREVIOUS_SCOPE")
        estimated = sum(ref["bytes"] for ref in refs) * 2 + 128 * 1024 * 1024
        require(shutil.disk_usage(run).free > estimated, "INSUFFICIENT_PAR_DISK_BUDGET")
        legacy = stage / previous / "legacy"
        for ref in refs:
            name = ref["drive_id"] + ".zip"
            require((legacy / name).exists() or (legacy / name).is_symlink(),
                    "WAITING_INPUT_EXACT_PREVIOUS_PAR:" + previous + ":" + name)
            source = pinned_path(legacy, {**ref, "path": name})
            os.link(source, run / name, follow_symlinks=False)
        runtime.sources.immutable(run, "D26.zip", close_raw)
        runtime.sources.immutable(run, "20261126_g4.zip", read_pin(intake, CONFIG["canary"][previous]))
        return
    remote_base = stage / previous
    remote = remote_inputs(remote_base, previous, runtime)
    receipt = remote_node(runtime, remote, previous, "daily-update")
    require(receipt is not None and receipt["status"] == "COMPUTED_ISOLATED",
            "WAITING_INPUT_EXACT_PREVIOUS_PAR:" + previous)
    ledger = json.loads(get_remote(runtime, remote, receipt, "PAR_LEDGER.json"))
    require(ledger["business_date"] == previous and ledger["scope"] == len(ledger["rows"]) == 5575
            and set(receipt["objects"]) == ROLES["daily-update"], "PREVIOUS_PAR_DATE_OR_SCOPE")
    parts = {part: receipt["objects"][f"PAR_STATE_{part:02d}.zip"] for part in range(1, 9)}
    estimated = sum(ref["bytes"] for ref in parts.values()) * 2 + 128 * 1024 * 1024
    require(shutil.disk_usage(run).free > estimated, "INSUFFICIENT_PAR_DISK_BUDGET")
    for ref in parts.values():
        original = pinned_path(remote_base, {**ref, "path": f"remote_{ref['id']}.raw"})
        os.link(original, run / (ref["id"] + ".zip"), follow_symlinks=False)
    rows = [{**row, "remote_part_id": parts[row["part"]]["id"]} if row["status"] == "COMPUTED" else row
            for row in ledger["rows"]]
    catalog = {"schema": "V5_W9E_PREVIOUS_PAR_CATALOG_V1", "business_date": previous,
               "scope": 5575, "rows": rows, "parts": list(parts.values()), **FLAGS}
    runtime.sources.immutable(run, "VERIFIED_PREVIOUS_PAR_CATALOG.json", json_bytes(catalog))


def close_batch(intake, state, run, day, previous, deadline, runtime, clock, *, backfill_cache=None):
    stage = intake / "stage"
    session = stage / day
    remote = remote_inputs(session, day, runtime)
    top_info = close_files(state, day, runtime, remote, "a-top200")
    daily_info = close_files(state, day, runtime, remote, "daily-update")
    if top_info is None:
        if backfill_cache is None:
            g4 = capture_g4(run, day, runtime, deadline, clock=clock)
        else:
            g4 = backfill_source(backfill_cache, session, run, day, "G4", runtime, clock)
        runtime.sources.immutable(run, "SAME_DAY_SOURCE_RECEIPT.json", json_bytes({"business_date": day, "g4": g4}))
        result = runtime.main.compute_close(None, "a-top200", day, run, run, "first-top", None, None)
        pending = result["remote_publish"][0]
        freeze_plan(state, day, run, pending)
        top_info = close_files(state, day, runtime, remote, "a-top200")
    top, top_source, _, _ = validate_top(day, runtime, top_info)
    refs = {"top200": {"count": 200, "ranked": top["ranked"], "scope": top["scope"],
                       "source_sha256": top_source["sha256"], "observed_at": top_source["observed_at"]}}
    nodes = ["a-top200"] if load_plan(state, day, "a-top200") else []
    if daily_info is None:
        daily = run / "daily"
        mkdir(daily)
        try:
            if backfill_cache is not None:
                gbbq = backfill_source(backfill_cache, session, daily, day, "RIGHTS", runtime, clock)
            previous_stage = stage / previous / "REMOTE_READBACKS.json"
            if day != "20261127":
                require(previous_stage.is_file(), "WAITING_INPUT_EXACT_PREVIOUS_PAR:" + previous)
            if backfill_cache is None:
                gbbq = capture_source(daily, day, "RIGHTS", runtime, deadline, clock=clock)
            build_prior(intake, daily, day, previous, runtime)
            runtime.sources.immutable(daily, "map.json", runtime.map_raw)
            context = {"business_date": day, "gbbq": gbbq}
            runtime.sources.immutable(daily, "SAME_DAY_SOURCE_RECEIPT.json", json_bytes(context))
            result = runtime.main.compute_close(None, "daily-update", day, daily, daily, "first-par", None,
                                                TopReadback(day, top_info))
            plan = result["remote_publish"][0]
            require(plan["node"] == "daily-update" and plan["status"] == "COMPUTED_ISOLATED",
                    "PAR_FROZEN_RESULT_NOT_READY:" + plan["status"])
            objects = {ref["role"]: artifact_pin(state, daily / ref["path"], ref) for ref in plan["files"]}
            validate_daily(day, previous, top, (plan["status"], objects, lambda role: read_pin(state, objects[role])), runtime)
            save_plan(state, day, "daily-update", objects)
        except HANDLED as exc:
            return {"status": "MISSING_UPSTREAM", "reason": brief(exc), "pending_connector_nodes": nodes, **refs}
    else:
        validate_daily(day, previous, top, daily_info, runtime)
    if load_plan(state, day, "daily-update"):
        nodes.append("daily-update")
    return {"status": "CLOSE_READY", "pending_connector_nodes": nodes, **refs}


def render_local(day, runtime, receipts, top, ledger, sample, anchors):
    assembly = runtime.evening.assemble_v3(day, receipts)
    assembly["slot"] = "18:30"
    for key in ("us-close", "hk-continuous-close", "hk-auction-final"):
        assembly["inputs"][key] = {"status": "MISSING_UPSTREAM"}
        if key not in assembly["missing"]:
            assembly["missing"].append(key)
    nodes = [{**node, "status": assembly["inputs"].get(node["id"], {}).get("status", "MISSING_UPSTREAM")}
             for node in runtime.main.registry()]
    return assembly, runtime.w10_board.render(day, nodes, ledger, top, sample, anchors)


def evening_batch(intake, state, run, day, previous, runtime, board, *, backfill=False):
    old_plan = load_plan(state, day, "evening-prepare")
    if old_plan:
        current = board.current()
        require(current["last_success"]["data_date"] == day
                and current["last_success"]["raw"] == old_plan["objects"]["BOARD.html"], "EVENING_LOCAL_PLAN_CURRENT")
        if current["stale"] and (not backfill or current["attempted_date"] <= day):
            current = board.publish(day, old_plan["objects"]["BOARD.html"], "ORIGINAL_V5_W11C_EVENING",
                                    {"evening_input": old_plan["objects"]["INPUT.json"]})
        return {"status": "EVENING_READY", "pending_connector_nodes": ["evening-prepare"], "board": current["view"]}
    stage = intake / "stage" / day
    remote = remote_inputs(stage, day, runtime)
    top_info = close_files(state, day, runtime, remote, "a-top200")
    daily_info = close_files(state, day, runtime, remote, "daily-update")
    receipts = {}
    anchors = {"asset_map_sha256": CONFIG["asset_map"]["sha256"]}
    top = ledger = sample = None
    missing = []
    if top_info:
        top, _, _, refs = validate_top(day, runtime, top_info)
        receipts["a-top200"] = {"business_date": day, "node": "a-top200", "status": top_info[0],
                                "objects": refs, **FLAGS}
        anchors["top200"] = refs["TOP200.json"]["sha256"]
    else:
        missing.append("MISSING_SAME_DAY_TOP200")
    if daily_info and top is not None:
        ledger, sample, refs = validate_daily(day, previous, top, daily_info, runtime)
        receipts["daily-update"] = {"business_date": day, "node": "daily-update", "status": daily_info[0],
                                    "objects": refs, **FLAGS}
        anchors.update(ledger=refs["PAR_LEDGER.json"]["sha256"], samples=refs["SAMPLE109.json"]["sha256"])
    else:
        missing.append("MISSING_SAME_DAY_VERIFIED_PAR_109")
    terminal = remote_node(runtime, remote, day, "evening-prepare")
    if terminal is not None:
        require(terminal["status"] == "COMPUTED" and not missing, "EVENING_REMOTE_TERMINAL_RECONCILE")
        require(set(terminal["objects"]) == ROLES["evening-prepare"], "EVENING_REMOTE_OBJECTS")
        assembly = json.loads(get_remote(runtime, remote, terminal, "INPUT.json"))
        html = get_remote(runtime, remote, terminal, "BOARD.html")
        require(assembly["business_date"] == day and assembly["slot"] == "18:30"
                and assembly["dot_required_complete"] is True
                and all(assembly["inputs"][node]["objects"][role]["sha256"] == anchors[key]
                        for node, role, key in (("a-top200", "TOP200.json", "top200"),
                                                ("daily-update", "PAR_LEDGER.json", "ledger"),
                                                ("daily-update", "SAMPLE109.json", "samples")))
                and f"V5 综合静态看板 · {day}".encode() in html, "EVENING_REMOTE_PINS")
    elif remote_node(runtime, remote, day, "a-top200") and remote_node(runtime, remote, day, "daily-update"):
        args = SimpleNamespace(isolated_par_sample=False, phase="evening", slot="18:30")
        original = runtime.main.dispatch(args, "evening-prepare", day, stage, run, "frozen-evening", None)
        refs = {x["role"]: x for x in original["remote_publish"][0]["files"]}
        assembly = json.loads(read_pin(run, refs["INPUT.json"]))
        html = read_pin(run, refs["BOARD.html"])
    else:
        assembly, html = render_local(day, runtime, receipts, top, ledger, sample, anchors)
    required = ("a-top200", "daily-update")
    excluded = [node["id"] for node in runtime.main.registry()
                if node["id"] not in (*required, "evening-prepare")]
    value = {**assembly, "dot_required": required, "dot_required_complete": not missing,
             "dot_unscheduled_nodes": excluded, "dot_missing_required": missing,
             "original_assembly_missing": list(assembly["missing"]), **FLAGS}
    board_proof = artifact(state, run.relative_to(state) / "BOARD.html", html)
    evidence = artifact(state, run.relative_to(state) / "INPUT.json", json_bytes(value))
    if missing:
        reason = " · ".join(missing)
        return {"status": "MISSING_UPSTREAM", "reason": reason, "diagnostic": board_proof,
                "evening_input": evidence, "current": backfill_failure(board, day, reason) if backfill
                else record_stale(board, day, reason)}
    proof = {"evening_input": evidence}
    current = board.current()
    if backfill and current["attempted_date"] > day:
        require(day >= current["data_date"], "BOARD_STALE_DATE_REGRESSION")
        good = {"data_date": day, "raw": board_proof, "origin": "ORIGINAL_V5_W11C_EVENING", "proof": proof}
        current = board.commit(good, current["attempted_date"], current["stale"], current["reason"])
    else:
        current = board.publish(day, board_proof, "ORIGINAL_V5_W11C_EVENING", proof)
    if terminal is not None:
        return {"status": "EVENING_ALREADY_REMOTE_VERIFIED", "pending_connector_nodes": [], "board": current["view"]}
    save_plan(state, day, "evening-prepare", {"INPUT.json": evidence, "BOARD.html": board_proof})
    return {"status": "EVENING_READY", "pending_connector_nodes": ["evening-prepare"], "board": current["view"]}


def scheduled(phase, intake, state, *, clock=today):
    now = clock()
    day = now.astimezone(BJT).strftime("%Y%m%d")
    run = None
    try:
        board = open_live_board(state)
    except HANDLED as exc:
        reason = brief(exc)
        return {**utc_result(day, phase, reason), "current": {"stale": True, "data_date": None,
                "attempted_date": day, "reason": reason, "view": None}}
    try:
        slot, deadline = admit_slot(phase, now)
        runtime = load_runtime(intake, state)
        previous, calendars = market_day(day, runtime, intake)
        attempts = state / "attempts"
        mkdir(attempts)
        run = Path(tempfile.mkdtemp(prefix=f"{day}-{phase}-", dir=attempts))
        if phase == "close":
            result = close_batch(intake, state, run, day, previous, deadline, runtime, clock)
            if result["status"] == "MISSING_UPSTREAM" and board.current()["last_success"]["data_date"] < day:
                result["current"] = record_stale(board, day, result["reason"])
        else:
            result = evening_batch(intake, state, run, day, previous, runtime, board)
        record = {"schema": "V5_DOT_RUN_V1", "phase": phase, "business_date": day,
                  "previous_trade_date": previous, "slot": slot, "calendars": calendars,
                  "actual_bjt": now.astimezone(BJT).isoformat(), "publication": "NOT_RUN", **result, **FLAGS}
        artifact(state, run.relative_to(state) / "RESULT.json", json_bytes(record))
        return record
    except HANDLED as exc:
        reason = brief(exc)
        record = {**utc_result(day, phase, reason), "current": record_stale(board, day, reason)}
        if run is not None:
            artifact(state, run.relative_to(state) / "RESULT.json", json_bytes(record))
        return record


def backfill_receipt_path(state, day):
    return state / "backfill" / day / "RESULT.json"


def load_backfill_receipt(state, day):
    path = backfill_receipt_path(state, day)
    if not path.exists() and not path.is_symlink():
        return None
    require(path.resolve() == path and path.is_file() and path.stat().st_size <= 16384, "BACKFILL_RECEIPT_PATH")
    record = json.loads(path.read_bytes())
    require(record.get("schema") == "V5_DOT_RUN_V1" and record.get("phase") == "backfill"
            and record.get("business_date") == day and record.get("publication") == "NOT_RUN"
            and all(record.get(key) is flag for key, flag in (FLAGS | BACKFILL_FLAGS).items())
            and set(record["plan_sha256"]) == set(record["pending_connector_nodes"])
            and set(record["plan_sha256"]) <= set(ROLES), "BACKFILL_RECEIPT_SCOPE")
    return record


def local_plan_sha(state, day, node):
    path = plan_path(state, day, node)
    require(path.resolve() == path and path.is_file(), "NO_PUBLISHABLE_PLAN")
    return digest(path.read_bytes())


def backfill_failure(board, day, reason):
    current = board.current()
    if current["data_date"] < day and current["attempted_date"] <= day:
        return record_stale(board, day, reason)
    return {key: current[key] for key in ("stale", "data_date", "attempted_date", "reason", "view")}


def backfill(intake, state, day, *, clock=today):
    record = utc_result(day, "backfill", None) | BACKFILL_FLAGS
    run = None
    board = current = None
    try:
        now = clock()
        require(now.utcoffset() is not None, "CLOCK_WITHOUT_OFFSET")
        now = now.astimezone(BJT)
        require(parse_day(day) <= now.date(), "BACKFILL_FUTURE_DATE")
        board = open_live_board(state)
        current = board.current()
        runtime = load_runtime(intake, state)
        previous, calendars = market_day(day, runtime, intake)
        require(day >= current["data_date"], "BOARD_STALE_DATE_REGRESSION")
        receipt_path = backfill_receipt_path(state, day)
        prior = load_backfill_receipt(state, day)
        if (prior and prior["status"] == "BACKFILL_READY" and current["data_date"] == day
                and prior["evening"]["board"] == current["view"]):
            for node, sha in prior["plan_sha256"].items():
                plan = load_plan(state, day, node)
                require(plan is not None and sha == digest(json_bytes(plan)), "BACKFILL_PLAN_SHA_MISMATCH")
            return prior
        mkdir(receipt_path.parent.parent)
        mkdir(receipt_path.parent)
        attempts = state / "attempts"
        mkdir(attempts)
        run = Path(tempfile.mkdtemp(prefix=f"{day}-backfill-", dir=attempts))
        record.update(actual_bjt=now.isoformat(), previous_trade_date=previous, calendars=calendars,
                      pending_connector_nodes=[], plan_sha256={})
        close = close_batch(intake, state, run, day, previous, None, runtime, clock,
                            backfill_cache=receipt_path.parent)
        record["close"] = close
        nodes = close["pending_connector_nodes"].copy()
        if close["status"] == "CLOSE_READY":
            evening = run / "evening"
            mkdir(evening)
            result = evening_batch(intake, state, evening, day, previous, runtime, board, backfill=True)
            record["evening"] = result
            if result["status"] in ("EVENING_READY", "EVENING_ALREADY_REMOTE_VERIFIED"):
                nodes.extend(result["pending_connector_nodes"])
                record.update(status="BACKFILL_READY", reason=None)
            else:
                record.update(status=result["status"], reason=result["reason"], current=result["current"])
        else:
            reason = close["reason"]
            status = "WAITING_INPUT" if reason.startswith("WAITING_INPUT_") else close["status"]
            record.update(status=status, reason=reason, evening={"status": "NOT_RUN"})
            record["current"] = backfill_failure(board, day, reason)
        record.update(pending_connector_nodes=nodes, plan_sha256={node: local_plan_sha(state, day, node)
                                                                  for node in nodes})
        atomic(receipt_path, json_bytes(record))
    except HANDLED as exc:
        reason = brief(exc)
        record.update(status="WAITING_INPUT" if reason.startswith("WAITING_INPUT_") else "BLOCKED", reason=reason)
        if run is not None and "close" not in record:
            record["current"] = backfill_failure(board, day, reason)
            record["evening"] = {"status": "NOT_RUN"}
    if run is not None:
        artifact(state, run.relative_to(state) / "RESULT.json", json_bytes(record))
    return record


def guard_publication(intake, state, day, node, evidence=None, *, allow_backfill=False, clock=today):
    selected = parse_day(day)

    def checked_clock():
        actual = clock()
        require(actual.utcoffset() is not None, "CLOCK_WITHOUT_OFFSET")
        local = actual.astimezone(BJT)
        require(selected == local.date() or (allow_backfill and selected < local.date()),
                "GUARD_NOT_ACTUAL_BJT_DAY")
        return local

    checked_clock()
    open_live_board(state)
    now = checked_clock()
    if selected == now.date():
        result = action(state, day, node, evidence, now=now)
        if result["status"] == "CREATE_ONCE":
            midnight = datetime.combine(selected + timedelta(days=1), time.min, tzinfo=BJT)
            expires = datetime.fromisoformat(result["expires_at"])
            result["expires_at"] = min(expires, midnight).isoformat()
        return result
    runtime = load_runtime(intake, state)
    market_day(day, runtime, intake)
    plan_sha = local_plan_sha(state, day, node)
    receipt = load_backfill_receipt(state, day)
    require(receipt is not None and node in receipt["plan_sha256"], "BACKFILL_VERIFIED_PLAN_REQUIRED")
    require(receipt["plan_sha256"][node] == plan_sha, "BACKFILL_PLAN_SHA_MISMATCH")
    now = checked_clock()
    require(selected < now.date(), "GUARD_NOT_ACTUAL_BJT_DAY")
    return action(state, day, node, evidence, now=now) | BACKFILL_FLAGS


def preflight(intake, state, day):
    runtime = load_runtime(intake, state)
    previous, calendars = market_day(day, runtime, intake)
    original = CONFIG["original_board"]
    read_pin(intake, original)
    return {"schema": "V5_DOT_PREFLIGHT_V1", "status": "PREFLIGHT_PASS", "business_date": day,
            "previous_trade_date": previous, "calendars": calendars, "slots_bjt": {
                "close": ["16:20", "16:50"], "evening": ["18:30"]},
            "seed_date": original["date"], "seed_sha256": original["sha256"],
            "frozen_members": runtime.proof["manifest_files"], "frozen_vendor_members": runtime.proof["vendor_files"],
            "actual_same_day_data": "NOT_RUN", "actual_same_day_par": "NOT_RUN",
            "dot_connector": "NOT_RUN", "missing_required_behavior": "FAIL_CLOSED_RETAIN_PINNED_LAST_GOOD",
            "publication": "NOT_RUN", **FLAGS}


def canary(intake, state, day, fixture):
    runtime = load_runtime(intake, state)
    previous, _ = market_day(day, runtime, intake)
    require(day in CONFIG["canary"], "HISTORICAL_CANARY_PIN_UNAVAILABLE")
    pin = {**CONFIG["canary"][day], "path": fixture.name}
    raw = read_pin(fixture.parent, pin)
    board = Board(state)
    seed(board, intake)
    run = Path(tempfile.mkdtemp(prefix=f"{day}-canary-", dir=state))
    ref = stage_g4(run, day, runtime, pin, raw)
    runtime.sources.immutable(run, "SAME_DAY_SOURCE_RECEIPT.json", json_bytes({"business_date": day, "g4": ref}))
    result = runtime.main.compute_close(None, "a-top200", day, run, run, "canary", None, None)
    info = {x["role"]: x for x in result["remote_publish"][0]["files"]}
    top, _, _, _ = validate_top(day, runtime, ("COMPUTED", info, lambda role: read_pin(run, info[role])))
    receipts = {"a-top200": {"business_date": day, "node": "a-top200", "status": "COMPUTED",
                              "objects": info, **FLAGS}}
    anchors = {"asset_map_sha256": CONFIG["asset_map"]["sha256"], "top200": info["TOP200.json"]["sha256"]}
    ledger = sample = None
    replay_status = "MISSING_UPSTREAM"
    if day == CONFIG["original_board"]["date"]:
        accepted = CONFIG["accepted_close"]
        files = runtime.driveio.manifested(read_pin(intake, accepted))
        require(json.loads(files["TOP200.json"]) == top, "HISTORICAL_TOP200_ARCHIVE_DIFF")
        rows = json.loads(gzip.decompress(files["PAR_LEDGER.json.gz"]))
        sample = json.loads(files["SAMPLE_109.json"])
        ledger = {"business_date": day, "scope": 5575, "rows": rows}
        anchors.update(ledger=digest(files["PAR_LEDGER.json.gz"]), samples=digest(files["SAMPLE_109.json"]))
        receipts["daily-update"] = {"business_date": day, "node": "daily-update", "status": "COMPUTED",
                                     "objects": {}, **FLAGS}
        replay_status = "PINNED_SAME_DAY_ARCHIVE_REPLAY"
    assembly, rendered = render_local(day, runtime, receipts, top, ledger, sample, anchors)
    html = artifact(state, run.relative_to(state) / "BOARD.html", rendered)
    current = record_stale(board, day, "HISTORICAL_CANARY · " + replay_status)
    result = {"status": "CANARY_PASS", "business_date": day, "previous_trade_date": previous,
              "source_observed_at": pin["observed_at"], "source_sha256": pin["sha256"],
              "top200_sha256": info["TOP200.json"]["sha256"], "top200_count": len(top["ranking"]),
              "ranked": top["ranked"], "scope": top["scope"], "unknown": len(top["unknown_symbols"]),
              "par": replay_status, "renderer": "FROZEN_W11C_W10_BOARD", "board": html,
              "original_assembly_missing": assembly["missing"], "current": current,
              "actual_same_day_data": "HISTORICAL_FIXTURE", "publication": "NOT_RUN", **FLAGS}
    artifact(state, run.relative_to(state) / "RESULT.json", json_bytes(result))
    return result


def cli():
    cli = ArgumentParser()
    cli.add_argument("--intake", type=Path, default=Path("intake"))
    cli.add_argument("--state", type=Path, default=Path("state"))
    modes = cli.add_subparsers(dest="mode", required=True)
    modes.add_parser("close")
    modes.add_parser("evening")
    modes.add_parser("backfill").add_argument("--date", required=True)
    modes.add_parser("init").add_argument("--first-install", required=True, action="store_true")
    modes.add_parser("preflight").add_argument("--date", required=True)
    fixture = modes.add_parser("canary")
    fixture.add_argument("--date", required=True)
    fixture.add_argument("--fixture", required=True, type=Path)
    guard = modes.add_parser("guard")
    guard.add_argument("--date", required=True)
    guard.add_argument("--node", required=True, choices=ROLES)
    guard.add_argument("--evidence", type=Path)
    guard.add_argument("--allow-backfill", action="store_true")
    args = cli.parse_args()
    try:
        state, intake = Path(os.path.abspath(args.state)), args.intake.resolve()
        require(state != intake and not state.is_relative_to(intake) and not intake.is_relative_to(state),
                "STATE_INTAKE_MUST_BE_SEPARATE")
        mkdir(state)
        with writer_lock(state):
            if args.mode in ("close", "evening"):
                result = scheduled(args.mode, intake, state)
            elif args.mode == "backfill":
                result = backfill(intake, state, args.date)
            elif args.mode == "init":
                result = initialize(intake, state)
            elif args.mode == "preflight":
                result = preflight(intake, state, args.date)
            elif args.mode == "canary":
                require(not (state / "plans").exists() and not (state / "DOT_OWNER.json").exists(),
                        "CANARY_REQUIRES_ISOLATED_STATE")
                result = canary(intake, state, args.date, Path(os.path.abspath(args.fixture)))
            else:
                evidence = Path(os.path.abspath(args.evidence)) if args.evidence else None
                result = guard_publication(intake, state, args.date, args.node, evidence,
                                           allow_backfill=args.allow_backfill)
    except HANDLED as exc:
        result = utc_result(getattr(args, "date", None), args.mode, brief(exc))
        if args.mode == "backfill":
            result.update(BACKFILL_FLAGS)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(cli())
