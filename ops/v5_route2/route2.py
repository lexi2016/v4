"""One-shot Mac-local runner for the frozen V5 close and evening rendering."""

from argparse import ArgumentParser
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import gzip
import importlib
import io
import json
import re
import sys
import tempfile
import zipfile

from local_state import (FLAGS, Board, artifact, atomic, digest, json_bytes, mkdir, read_pin,
                         require, sync_dir, writer_lock)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
INPUTS = ROOT / "inputs"
FROZEN = INPUTS / "frozen"
OUT = ROOT / "out"
BJT = ZoneInfo("Asia/Shanghai")
MANIFEST_SHA = "8014b6627cd53e027d0f4a91e0df5aece6cabb38593c6c107d9ae167e39ada4b"


def compact_day(value):
    require(re.fullmatch(r"[0-9]{8}", value), "BUSINESS_DATE")
    return date.fromisoformat(value).isoformat()


def load_runtime(cfg):
    release = read_pin(INPUTS, cfg["release"])
    manifest_path = FROZEN / "MANIFEST_SHA256.json"
    manifest = manifest_path.read_bytes()
    require(digest(manifest) == MANIFEST_SHA, "FROZEN_MANIFEST_SHA")
    refs = json.loads(manifest)["files"]
    names = {"MANIFEST_SHA256.json", *refs}
    require(FROZEN.resolve() == FROZEN and
            {p.relative_to(FROZEN).as_posix() for p in FROZEN.rglob("*") if not p.is_dir()} == names,
            "FROZEN_RELEASE_PATHS")
    with zipfile.ZipFile(io.BytesIO(release)) as package:
        require(len(package.namelist()) == len(names) and set(package.namelist()) == names
                and package.read("MANIFEST_SHA256.json") == manifest, "FROZEN_ARCHIVE_SCOPE")
        for name, pin in refs.items():
            staged = read_pin(FROZEN, {**pin, "path": name})
            require(staged == package.read(name), "FROZEN_ARCHIVE_MEMBER:" + name)
    vendors = {name: pin["sha256"] for name, pin in refs.items() if name.startswith("vendor/")}
    require(len(vendors) == 32, "VENDOR_SCOPE")
    original_map = read_pin(INPUTS, cfg["asset_map"])
    require(json.loads(original_map)["asset_count"] == 92 and json.loads(original_map)["denominator"] == 21,
            "FROZEN_MAP_SCOPE")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(FROZEN))
    mods = {}
    for name in ("main", "sources", "top200", "evening", "w10_board", "driveio", "markets"):
        module = importlib.import_module(name)
        require(Path(module.__file__) == FROZEN / (name + ".py"), "FROZEN_MODULE_SCOPE")
        mods[name] = module
    require(mods["main"].MAP_SHA == cfg["asset_map"]["sha256"], "ORIGINAL_MAP_PIN")
    evidence = {"release": cfg["release"], "asset_map": cfg["asset_map"],
                "frozen_manifest_sha256": MANIFEST_SHA, "manifest_files": len(refs), "vendor": vendors}
    return SimpleNamespace(**mods), evidence


def output(root, attempt, name, value):
    raw = value if isinstance(value, bytes) else json_bytes(value)
    return artifact(root, attempt.relative_to(root) / name, raw)


def archive(runtime, cfg):
    pin = cfg["accepted_close"]
    require((pin["sha256"], pin["bytes"]) == (runtime.main.D26_SHA, runtime.main.D26_BOARD_REF["bytes"]),
            "ACCEPTED_CLOSE_IDENTITY")
    raw = read_pin(INPUTS, pin)
    return raw, runtime.driveio.manifested(raw)


def close(day, case, root, attempt, runtime, cfg):
    runtime.markets.resolve(day, "close", "15:00", [day])
    g4 = case["g4"]
    # The frozen close implementation uses these same official-source and ranking gates.
    runtime.sources.inspect(INPUTS, day, "G4", g4)
    top = runtime.top200.rank_v2(runtime.sources.read_pin(INPUTS, g4, "G4"), day, g4["sha256"])
    refs = {"TOP200.json": output(root, attempt, "TOP200.json", top),
            "SOURCE.json": output(root, attempt, "SOURCE.json", {"business_date": day, "g4": g4})}
    result = {"business_date": day, "mode": case["mode"], "objects": refs, "g4": g4,
              "top200": {"count": len(top["ranking"]), "ranked": top["ranked"], "scope": top["scope"],
                         "unknown": len(top["unknown_symbols"])}, **FLAGS}
    if case["mode"] == "observed":
        result.update(status="MISSING_UPSTREAM", missing=case["missing"])
    else:
        _, files = archive(runtime, cfg)
        require(json.loads(files["TOP200.json"]) == top, "SEALED_TOP200_DIFFERS_FROM_REAL_G4")
        ledger = json.loads(gzip.decompress(files["PAR_LEDGER.json.gz"]))
        refs.update({
            "PAR_LEDGER.json": output(root, attempt, "PAR_LEDGER.json",
                                      {"business_date": day, "scope": 5575, "rows": ledger}),
            "SAMPLE109.json": output(root, attempt, "SAMPLE109.json", files["SAMPLE_109.json"]),
        })
        result.update(status="CLOSE_REPLAY_VERIFIED", archived_top200_identical=True,
                      par="PINNED_ARCHIVED_SAME_DATE", accepted_close=cfg["accepted_close"])
    atomic(root / "CLOSE.json", json_bytes(result))
    return result


def historical_observations(runtime, day):
    states, evidence = {}, {}
    for phase, pin in runtime.main.D26_STATE_READBACKS.items():
        path = INPUTS / f"D26_{phase}_RESULT.json"
        if path.exists():
            ref = {**pin, "path": path.name}
            raw = read_pin(INPUTS, ref)
            states[phase] = runtime.evening.session_state(day, phase, json.loads(raw))
            evidence[phase] = {**ref, "status": states[phase]["status"]}
    return states, evidence


def evening(day, case, root, attempt, runtime, cfg, board, frozen_proof):
    close_path = root / "CLOSE.json"
    require(close_path.exists(), "MISSING_CLOSE_HANDOFF")
    handoff = json.loads(close_path.read_bytes())
    replay = case["mode"] == "sealed_replay"
    expected = "CLOSE_REPLAY_VERIFIED" if replay else "MISSING_UPSTREAM"
    require(handoff.get("status") == expected and handoff.get("objects"), "MISSING_CLOSE_HANDOFF")
    require((handoff["business_date"], handoff["mode"], handoff["g4"]) == (day, case["mode"], case["g4"]),
            "CLOSE_HANDOFF_DATE_MODE_OR_SOURCE")
    objects = handoff["objects"]
    top = json.loads(read_pin(root, objects["TOP200.json"]))
    require(top["source_sha256"] == case["g4"]["sha256"], "CLOSE_TOP200_SOURCE_PIN")
    receipts = {"a-top200": dict(business_date=day, node="a-top200", status="COMPUTED",
                                 objects={"TOP200.json": objects["TOP200.json"]}, **FLAGS)}
    ledger = sample = None
    observations = {}
    archived_assembly = None
    anchors = {"asset_map_sha256": cfg["asset_map"]["sha256"], "top200": objects["TOP200.json"]["sha256"]}
    if replay:
        raw_archive, files = archive(runtime, cfg)
        states, observations = historical_observations(runtime, day)
        archived_assembly = runtime.evening.assemble(day, raw_archive, cfg["accepted_close"],
                                                      states.get("premarket"), states.get("intraday"))
        ledger = json.loads(read_pin(root, objects["PAR_LEDGER.json"]))
        sample = json.loads(read_pin(root, objects["SAMPLE109.json"]))
        require(top == json.loads(files["TOP200.json"])
                and ledger["rows"] == json.loads(gzip.decompress(files["PAR_LEDGER.json.gz"]))
                and sample == json.loads(files["SAMPLE_109.json"]), "EVENING_ARCHIVE_HANDOFF")
        receipts["daily-update"] = dict(business_date=day, node="daily-update", status="COMPUTED",
                                        objects={k: objects[k] for k in ("PAR_LEDGER.json", "SAMPLE109.json")},
                                        **FLAGS)
        anchors.update(ledger=objects["PAR_LEDGER.json"]["sha256"],
                       samples=objects["SAMPLE109.json"]["sha256"],
                       accepted_same_date_archive=cfg["accepted_close"]["sha256"])
    # Use the same assembly and HTML renderer as the deployed evening dispatch.
    assembly = runtime.evening.assemble_v3(day, receipts)
    slot = "19:00"
    assembly["slot"] = slot
    registry = runtime.main.registry()
    nodes = [{"id": node["id"], "title": node["title"], "window": node["window"],
              "status": receipts.get(node["id"], {}).get("status", "MISSING_UPSTREAM")}
             for node in registry]
    for node in ("us-close", "hk-continuous-close", "hk-auction-final"):
        if node not in assembly["inputs"]:
            assembly["inputs"][node] = {"status": "MISSING_UPSTREAM"}
            assembly["missing"].append(node)
    raw = runtime.w10_board.render(day, nodes, ledger, top, sample, anchors)
    proof = output(root, attempt, "BOARD.html", raw)
    supporting = {"original_evening_inputs": assembly, "archived_close_assembly": archived_assembly,
                  "pinned_phase_observations": observations, "close_objects": objects}
    support = output(root, attempt, "INPUT.json", supporting)
    if replay:
        current = board.publish(compact_day(day), proof, "FROZEN_W11C_RENDERED_D26_CLOSE_REPLAY",
                                {"evening_inputs": support, "original_runtime": frozen_proof})
        status = "ORIGINAL_V5_CLOSE_EVENING_REPLAY_VERIFIED"
    else:
        current = board.fail(compact_day(day), "MISSING_UPSTREAM · " + " · ".join(case["missing"]))
        status = "MISSING_UPSTREAM"
    return dict(business_date=day, status=status, board=proof, input=support, current=current,
                original_evening_status="MISSING_UPSTREAM" if assembly["missing"] else "PARTIAL",
                natural_verified_count=0, missing_nodes=assembly["missing"], **FLAGS)


def run(args):
    day = args.date or datetime.now(BJT).strftime("%Y%m%d")
    iso = compact_day(day)
    cfg_file = (HERE / "route2.json").read_bytes()
    cfg = json.loads(cfg_file)
    case = cfg["dates"].get(day)
    replay = case is not None and case["mode"] == "sealed_replay"
    root = OUT / ("replay" if replay else "observed")
    if args.action == "view":
        current = Board(root, writable=False).current()
        return {"status": "STALE" if current["stale"] else "AVAILABLE",
                "data_date": current["data_date"], "attempted_date": current["attempted_date"],
                "reason": current["reason"], "path": str(root / current["view"]["path"])}
    require(OUT.resolve() == OUT and OUT.is_dir(), "FIXED_ISOLATED_OUTPUT_REQUIRED")
    with writer_lock(OUT):
        mkdir(root)
        mkdir(root / "runs")
        board = Board(root)
        original_pin = cfg["original_board"]
        attempt = Path(tempfile.mkdtemp(prefix=day + "_" + args.action + "_", dir=root / "runs"))
        sync_dir(attempt.parent)
        started = datetime.now(timezone.utc).isoformat()
        steps = {}
        seed = None
        runs_close = args.action in ("close", "run")
        try:
            seed = board.seed(compact_day(original_pin["date"]), original_pin, original_pin["drive_id"],
                              lambda: read_pin(INPUTS, original_pin))
            if not replay:
                board.fail(iso, "正在验证同日输入")
            if runs_close:
                atomic(root / "CLOSE.json", json_bytes({"business_date": day, "status": "CLOSE_IN_PROGRESS"}))
            require(case is not None, "MISSING_UPSTREAM_DATE_UNCONFIGURED")
            runtime, frozen = load_runtime(cfg)
            frozen_proof = output(root, attempt, "FROZEN.json", frozen)
            if runs_close:
                steps["close"] = close(day, case, root, attempt, runtime, cfg)
                if steps["close"]["status"] == "MISSING_UPSTREAM" and args.action == "close":
                    board.fail(iso, "MISSING_UPSTREAM · " + " · ".join(case["missing"]))
            if args.action in ("evening", "run"):
                steps["evening"] = evening(day, case, root, attempt, runtime, cfg, board, frozen_proof)
            status = list(steps.values())[-1]["status"]
        except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
            status = "MISSING_UPSTREAM" if str(exc).startswith("MISSING_") else "BLOCKED"
            reason = str(exc)[:512]
            if runs_close and "close" not in steps:
                atomic(root / "CLOSE.json", json_bytes({"business_date": day, "status": status, "reason": reason}))
            if board.pointer.exists():
                board.fail(iso, status + " · " + reason)
            steps["failure"] = {"type": type(exc).__name__, "reason": reason}
        current = board.current() if board.pointer.exists() else None
        receipt = {"business_date": day, "status": status, "steps": steps, "started": started,
                   "finished": datetime.now(timezone.utc).isoformat(), "original": seed,
                   "current": current, "config_sha256": digest(cfg_file), **FLAGS}
        output(root, attempt, "RUN_RECEIPT.json", receipt)
        return {"status": status, "business_date": day, "receipt": str(attempt / "RUN_RECEIPT.json"),
                "data_date": (current or {}).get("data_date"), "stale": (current or {}).get("stale")}


def cli():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("close", "evening", "run", "view"))
    parser.add_argument("--date", help="Verified A-share business date, YYYYMMDD in Shanghai time")
    args = parser.parse_args()
    try:
        result = run(args)
    except (ValueError, OSError, KeyError) as exc:
        result = {"status": "BLOCKED", "reason": str(exc)[:512]}
    print(json.dumps(result, ensure_ascii=False))
    return {"BLOCKED": 2, "MISSING_UPSTREAM": 3}.get(result["status"], 0)


if __name__ == "__main__":
    raise SystemExit(cli())
