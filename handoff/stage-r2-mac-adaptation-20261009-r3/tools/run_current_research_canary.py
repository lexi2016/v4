#!/usr/bin/env python3
"""Prepare a new research namespace; optionally invoke the original Stage owner."""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import runpy
import shutil
import stat
import subprocess
import sys
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("_run_canary_sources", Path(__file__).with_name("canary_sources.py"))
sources = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sources)
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
STAGES = frozenset({"STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945",
                    "STAGE_0945_1030", "STAGE_1300_1315", "STAGE_1445_1500"})
IGNORED = sources.IGNORED
HQ = "upstreams/v3_shared_data/scripts/live_acquisition/pytdx_hq.py"
SHARED_HQ = "scripts/live_acquisition/pytdx_hq.py"
PIN = "CURRENT_DAY_RESEARCH_PIN.json"
SHA = re.compile(r"[0-9a-f]{64}\Z")
RUNTIME_PATH_KEYS = ("candidate_acquisition_root", "raw_root", "selection_root", "receipt_root",
                     "v3_formal_root", "v3_research_root", "v4_research_data_root", "v4_morning_news_root",
                     "hk_d1_root", "hk_current_day_research_root", "preselection_source_root",
                     "hk_second_filter_root", "hk_full_universe_root", "a_auction_root", "hk_auction_root",
                     "hk_stage_replay_root", "a_research_panel_receipt_root", "shared_data_root", "python_path")
DEFAULT_TREE_POLICY = {"copy_roots": ["."], "optional_roots": [], "symlinks": {}, "sha256": None, "ignored": IGNORED}


class CanaryError(ValueError):
    pass


def _check(condition, code):
    if not condition:
        raise CanaryError(code)


def _path(value, *, directory=False):
    path = Path(value).expanduser().absolute()
    _check(".." not in path.parts, "PATH_PARENT_COMPONENT")
    _check(not any(part.is_symlink() for part in (path, *path.parents)), "SYMLINK_PATH_REJECTED")
    if directory:
        _check(path.is_dir(), "DIRECTORY_MISSING")
    return path


def _relative(value):
    _check(isinstance(value, str) and bool(value) and "\\" not in value and "\x00" not in value,
           "RELATIVE_PATH_INVALID")
    path = PurePosixPath(value)
    _check(not path.is_absolute() and str(path) == value and
           not any(part in {".", "..", *IGNORED} for part in path.parts), "RELATIVE_PATH_INVALID")
    return path


def _read(path):
    return sources.read_regular(_path(path))


def _digest(data):
    return sha256(data).hexdigest()


def _snapshot(root, policy=None, *, candidate=False):
    return sources.snapshot(root, policy or DEFAULT_TREE_POLICY, candidate=candidate)


def _tree_id(files):
    return sources.tree_id(files["entries"])


def _inside(path, root):
    return path == root or root in path.parents


def _same_snapshot(before, after):
    return all(before[key] == after[key] for key in ("entries", "links", "root_device", "root_inode"))


def _source_roots(app, provenance):
    roots = [app]
    if provenance:
        roots.append(Path(provenance["manifest"]["source_root"]))
    return roots


def _guard_runtime_paths(config, policy, app, provenance, *, environment=False):
    """Inspect path metadata before RunnerConfig.resolve; never read a legacy target."""
    quarantined = [row for row in policy["symlinks"].values() if row["action"] == "quarantine"]
    external = [Path(row["link_text"]) for row in quarantined]
    lexical = [root / row["relative_path"] for root in _source_roots(app, provenance) for row in quarantined]
    checked = []
    values = [(key, value) for key, value in config.items() if key in RUNTIME_PATH_KEYS and value]
    if environment:
        values += [("PYTHONPATH", value) for value in os.environ.get("PYTHONPATH", "").split(os.pathsep) if value]
        if os.environ.get("V3_SHARED_DATA_SOURCE_ROOT"):
            values.append(("V3_SHARED_DATA_SOURCE_ROOT", os.environ["V3_SHARED_DATA_SOURCE_ROOT"]))
    for key, value in values:
        _check(isinstance(value, str), "CONFIG_PATH_VALUE_INVALID:" + key)
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = app / path  # The original owner runs with cwd=app.
        path = Path(os.path.normpath(path))
        for attempt in range(41):
            _check(not any(_inside(path, target) for target in lexical)
                   and not any(_inside(path, target) or _inside(target, path) for target in external),
                   "QUARANTINED_RUNTIME_DEPENDENCY:" + key)
            changed = False
            for component in reversed((path, *path.parents)):
                if component.is_symlink():
                    text = os.readlink(component)
                    target = Path(text) if Path(text).is_absolute() else component.parent / text
                    path = Path(os.path.normpath(target / path.relative_to(component)))
                    changed = True
                    break
            if not changed:
                break
            _check(attempt < 40, "RUNTIME_DEPENDENCY_SYMLINK_LOOP:" + key)
        checked.append(key)
    return sorted(set(checked))


def _shared_root(value, app, policy, provenance):
    path = Path(value).expanduser().absolute()
    for root in _source_roots(app, provenance):
        for row in policy["symlinks"].values():
            if row["action"] == "preserve_internal" and path == root / row["relative_path"] and path.is_symlink():
                _path(path.parent, directory=True)
                _check(os.readlink(path) == row["link_text"], "SHARED_INTERNAL_LINK_CHANGED")
                target = Path(os.path.normpath(path.parent / row["link_text"]))
                _check(_inside(target, root), "SHARED_INTERNAL_LINK_ESCAPES_ROOT")
                return _path(target, directory=True)
    return _path(path, directory=True)


def _write_json(path, value):
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(content)
    path.chmod(0o600)


# A fresh process avoids importing a cached Stage package from another tree.
# No collector, selector, writer or store is reimplemented in this bridge.
OWNER = r'''
import inspect, json, sys
from datetime import datetime
from pathlib import Path
sys.dont_write_bytecode = True
app, config_path, day, stage, evaluated, result_path = sys.argv[1:]
sys.path.insert(0, app)
from stage_center import runner
if Path(runner.__file__).resolve() != Path(app) / "stage_center/runner.py":
    raise RuntimeError("OWNER_MODULE_PATH_MISMATCH")
payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
allowed = inspect.signature(runner.build_production_config).parameters
config = runner.build_production_config(**{key: value for key, value in payload.items() if key in allowed})
owner = runner.StageCenterRunner(config)
owner._execution_origin = "CURRENT_DAY_RESEARCH_REPLAY"
result = owner.tick(day, datetime.fromisoformat(evaluated), stage_id=stage,
                    historical_backfill=True, _skip_precapture=True)
with Path(result_path).open("x", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    stream.write("\n")
Path(result_path).chmod(0o600)
'''


def _pin(pin, input_root):
    _check(isinstance(pin, dict) and pin.get("schema_version") == "v4.hk_current_day_research_pin.v1"
           and pin.get("mode") == "CURRENT_DAY_RESEARCH_ONLY" and pin.get("market") == "HK_CONNECT"
           and pin.get("hk_connect_membership_status") == "CANNOT_CONFIRM"
           and pin.get("formal_d1_eligible") is False and pin.get("formal_pit") is False
           and all(pin.get(key) is False for key in FLAGS if key != "RESEARCH_ONLY"), "PIN_IDENTITY_INVALID")
    day, prior = pin.get("trade_date"), pin.get("universe_as_of")
    _check(isinstance(day, str) and isinstance(prior, str) and bool(re.fullmatch(r"\d{8}", day))
           and bool(re.fullmatch(r"\d{8}", prior)), "PIN_DATE_INVALID")
    datetime.strptime(day, "%Y%m%d"); datetime.strptime(prior, "%Y%m%d")
    captured = datetime.fromisoformat(pin["captured_at"])
    _check(captured.tzinfo is not None and captured.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d") == day
           and prior <= day and pin.get("stale_universe") is (prior < day), "PIN_DATE_INVALID")
    _check(type(pin.get("row_count")) is int and pin["row_count"] > 0, "PIN_ROW_COUNT_INVALID")
    expected = {"snapshot_rows_projected.json", "receipt.json", f"reference_codes_{prior}.json", "FINAL_RECEIPT.json"}
    files = pin.get("files")
    _check(isinstance(files, dict) and set(files) == expected, "PIN_FILES_INVALID")
    contents = {}
    for name, expected_sha in files.items():
        _check(isinstance(expected_sha, str) and bool(SHA.fullmatch(expected_sha)), "PIN_FILE_SHA_INVALID")
        contents[name] = _read(input_root / name)
        _check(_digest(contents[name]) == expected_sha, "HK_INPUT_SHA_MISMATCH:" + name)
    return contents


def _verify_owner(result, output, manifest):
    _check(isinstance(result, dict) and result.get("trade_date") == manifest["trade_date"]
           and result.get("stage_id") == manifest["stage_id"]
           and result.get("execution_origin") == "CURRENT_DAY_RESEARCH_REPLAY"
           and result.get("dispatch_mode") == "RECOVERY" and result.get("natural_verified") is False
           and all(result.get(key) is value for key, value in FLAGS.items()), "OWNER_REPLAY_IDENTITY_INVALID")
    namespace = result.get("namespace")
    _check(isinstance(namespace, dict), "OWNER_BACKFILL_NAMESPACE_MISSING")
    for key in ("raw_root", "selection_root", "receipt_root"):
        path = _path(namespace[key])
        _check(_inside(path, output), "OWNER_OUTPUT_OUTSIDE_CANARY")
        manifest["output_paths"][key] = str(path)
    receipt_root = Path(namespace["receipt_root"])
    receipt = receipt_root / manifest["trade_date"] / manifest["stage_id"] / "receipt.json"
    receipt_raw = _read(receipt)
    _check(json.loads(receipt_raw) == result, "OWNER_RECEIPT_RESULT_MISMATCH")
    history = result.get("receipt_history") or {}
    history_path = receipt_root / _relative(history.get("relative_path"))
    history_raw = _read(history_path)
    _check(_digest(history_raw) == history.get("sha256"), "OWNER_HISTORY_SHA_MISMATCH")
    manifest["output_paths"].update(owner_receipt=str(receipt), owner_history_receipt=str(history_path))
    manifest["owner_receipt_sha256"] = _digest(receipt_raw)
    manifest["owner_history_sha256"] = _digest(history_raw)
    markets = result.get("markets") or {}
    counts = {market: int((markets.get(market) or {}).get("selected_rows") or 0)
              for market in ("A_SHARE", "HK_CONNECT")}
    manifest["selected_rows"] = counts
    if counts["HK_CONNECT"]:
        binding = (result.get("selection_artifacts") or {}).get("HK_CONNECT")
        _check(isinstance(binding, dict) and binding.get("run_id") == markets["HK_CONNECT"].get("run_id"),
               "OWNER_SELECTION_BINDING_MISSING")
        for kind in ("artifact", "manifest", "receipt"):
            target = Path(namespace["selection_root"]) / _relative(binding[kind + "_relative"])
            _check(_digest(_read(target)) == binding[kind + "_bytes_sha256"], "OWNER_SELECTION_SHA_MISMATCH:" + kind)
        manifest["selection_run_id"] = binding["run_id"]
    manifest["owner_status"] = result.get("status")
    manifest["status"] = "RESEARCH_ROWS_WRITTEN" if counts["HK_CONNECT"] else "EXECUTED_NO_HK_SELECTION"


def run_canary(*, package, stage_app, config_path, hk_input, output_root, stage_id, execute=False):
    result = {"schema_version": "V4_CURRENT_DAY_RESEARCH_CANARY_RUN_V1", "status": "PREFLIGHT_FAILED",
              "executed": False, "execute_requested": bool(execute), "input_bytes_unchanged": None,
              "stage_id": stage_id, "errors": [], "manual_replay": True, "historical_backfill": True,
              "natural_verified": False, "execution_origin": "CURRENT_DAY_RESEARCH_REPLAY", **FLAGS}
    created = False
    try:
        _check(stage_id in STAGES, "SIX_MINUTE_STAGE_REQUIRED")
        package, app, source = (_path(path, directory=True) for path in (package, stage_app, hk_input))
        config_path, output = _path(config_path), _path(output_root)
        _check(not os.path.lexists(output) and output.parent.is_dir(), "OUTPUT_MUST_BE_NEW_WITH_EXISTING_PARENT")
        map_raw, pin_raw, config_raw = (_read(path) for path in (package / "SOURCE_MAP.json", package / PIN, config_path))
        mapping, pin, original_config = (json.loads(raw) for raw in (map_raw, pin_raw, config_raw))
        entries = mapping.get("files") if isinstance(mapping, dict) else None
        _check(isinstance(entries, list), "SOURCE_MAP_FILES_REQUIRED")
        app_policy = sources.load_policy(package, mapping, "stage", IGNORED)
        selected, guarded, afters = {}, {package / "SOURCE_MAP.json": _digest(map_raw),
                                       package / PIN: _digest(pin_raw), config_path: _digest(config_raw)}, {}
        if app_policy["sha256"] is not None:
            guarded[package / sources.POLICY] = app_policy["sha256"]
        for row in entries:
            _check(isinstance(row, dict), "SOURCE_MAP_ENTRY_INVALID")
            if row.get("group") != "stage":
                continue
            rel, after_rel = _relative(row.get("relative_path")), _relative(row.get("after_path"))
            _check(after_rel.parts[:2] == ("after", "stage") and str(rel) not in selected,
                   "SOURCE_MAP_STAGE_PATH_INVALID")
            expected, before = row.get("after_sha256"), row.get("accepted_before_sha256")
            _check(isinstance(expected, str) and bool(SHA.fullmatch(expected)) and isinstance(before, list)
                   and all(isinstance(value, str) and SHA.fullmatch(value) for value in before), "SOURCE_MAP_SHA_INVALID")
            afters[str(rel)] = _read(package / after_rel)
            _check(_digest(afters[str(rel)]) == expected, "PACKAGE_AFTER_SHA_MISMATCH:" + str(rel))
            _check(_digest(_read(app / rel)) == expected, "STAGE_APP_AFTER_SHA_MISMATCH:" + str(rel))
            guarded[package / after_rel] = guarded[app / rel] = expected
            selected[str(rel)] = row
        _check(HQ in selected and "stage_center/runner.py" in selected, "REQUIRED_STAGE_SOURCE_MAP_ENTRY_MISSING")
        app_before = _snapshot(app, app_policy, candidate=True)
        provenance = sources.verify_manifest(app, app_policy, _digest(map_raw), app_before)
        _check(app_policy["sha256"] is None or provenance is not None, "CANDIDATE_SOURCE_MANIFEST_REQUIRED")
        if provenance:
            guarded[app / sources.MANIFEST] = provenance["sha256"]
        contents = _pin(pin, source)
        guarded.update({source / name: _digest(raw) for name, raw in contents.items()})
        _check(isinstance(original_config, dict), "CONFIG_OBJECT_REQUIRED")
        for key in ("candidate_acquisition_root", "shared_data_root", "python_path"):
            _check(isinstance(original_config.get(key), str) and Path(original_config[key]).expanduser().is_absolute(),
                   "CONFIG_ABSOLUTE_PATH_REQUIRED:" + key)
        python = Path(original_config["python_path"]).expanduser()  # Keep the lexical venv symlink.
        _guard_runtime_paths({key: original_config[key] for key in ("shared_data_root", "python_path")},
                             app_policy, app, provenance)
        _check(python.is_file() and os.access(python, os.X_OK), "CONFIG_PYTHON_NOT_EXECUTABLE")
        shared = _shared_root(original_config["shared_data_root"], app, app_policy, provenance)
        _check(not any(_inside(output, root) for root in (package, app, source, shared)), "OUTPUT_INSIDE_READ_SOURCE")
        shared_before = _digest(_read(shared / SHARED_HQ))
        _check(shared_before in {*selected[HQ]["accepted_before_sha256"], selected[HQ]["after_sha256"]},
               "SHARED_HQ_SOURCE_SHA_MISMATCH")
        copy_shared = shared != app / "upstreams/v3_shared_data"
        _check(copy_shared or shared_before == selected[HQ]["after_sha256"], "CANDIDATE_SHARED_HQ_NOT_AFTER")
        tree_policies = {app: app_policy, source: DEFAULT_TREE_POLICY, shared: DEFAULT_TREE_POLICY}
        trees = {app: app_before, source: _snapshot(source), shared: _snapshot(shared)}
        prepared = dict(original_config)
        prepared.update(raw_root=str(output / "raw"), selection_root=str(output / "selection"),
                        receipt_root=str(output / "receipts"), hk_current_day_research_root=str(output / "hk_input"),
                        shared_data_root=str(output / "shared_data") if copy_shared else str(shared))
        checked_paths = _guard_runtime_paths(prepared, app_policy, app, provenance, environment=True)
        # Read the original immutable stage contract; no market client starts.
        contract = runpy.run_path(str(app / "stage_center/contracts.py"))
        cutoff = contract["STAGE_BY_ID"][stage_id].cutoff
        evaluated = datetime.strptime(pin["trade_date"] + " " + cutoff, "%Y%m%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        quarantined = (provenance["manifest"].get("quarantined_links", []) if provenance else
                       [{**row, "observed_in_original_source": None, "target_contents_read": False}
                        for row in app_policy["symlinks"].values() if row["action"] == "quarantine"])
        result.update(trade_date=pin["trade_date"], evaluated_at=evaluated.isoformat(), package=str(package),
                      stage_app=str(app), source_map_sha256=_digest(map_raw), pin_sha256=_digest(pin_raw),
                      canary_source_policy_sha256=app_policy["sha256"],
                      candidate_source_manifest_sha256=provenance["sha256"] if provenance else None,
                      source_dependency_boundary={"quarantined_links": quarantined,
                          "quarantined_links_present_in_candidate": False,
                          "configuration_and_environment_checked": True, "checked_path_keys": checked_paths,
                          "dynamic_dependency_status": "CANNOT_CONFIRM",
                          "dynamic_dependency_scope": "Shared modules, derived data paths and collector child processes are not proven by static source scans",
                          "configured_data_root_snapshot_scope": "APP_HK_PIN_AND_SHARED_ONLY_OTHER_DATA_ROOTS_NOT_SNAPSHOTTED"},
                      config_source_path=str(config_path), config_source_sha256=_digest(config_raw),
                      source_verification_scope="SOURCE_MAP_STAGE_MAPPED_FILES",
                      stage_sources=[{"relative_path": name, "actual_path": str(app / name),
                                      "package_after_path": str(package / row["after_path"]), "sha256": row["after_sha256"]}
                                     for name, row in selected.items()],
                      input_files=[{"actual_path": str(source / name), "sha256": _digest(raw)} for name, raw in contents.items()],
                      shared_source={"original_root": str(shared), "effective_root": prepared["shared_data_root"],
                                     "lexical_original_root": original_config["shared_data_root"],
                                     "original_hq_sha256": shared_before, "effective_hq_path": str(Path(prepared["shared_data_root"]) / SHARED_HQ),
                                     "effective_hq_sha256": selected[HQ]["after_sha256"], "copied": copy_shared,
                                     "permissions_restored": not copy_shared},
                      python_path=str(python),
                      source_tree_observations=[{"path": str(path), "files": sum(row["type"] == "file" for row in files["entries"].values()),
                                                "sha256": _tree_id(files), "scope": "BYTES_MODES_AND_DECLARED_LINK_IDENTITIES"}
                                               for path, files in trees.items()],
                      ignored_tree_names=sorted(IGNORED),
                      output_paths={"run_manifest": str(output / "run_manifest.json"), "config": str(output / "config.json"),
                                    "result": str(output / "result.json"), **{key: prepared[key] for key in ("raw_root", "selection_root", "receipt_root")}})
        _check(all(_digest(_read(path)) == expected for path, expected in guarded.items())
               and all(_same_snapshot(files, _snapshot(path, tree_policies[path], candidate=path == app))
                       for path, files in trees.items()), "INPUT_CHANGED_DURING_PREFLIGHT")
        output.mkdir(mode=0o700); created = True; result["status"] = "PREPARATION_FAILED"
        (output / "hk_input").mkdir(mode=0o700)
        for name, raw in {**contents, PIN: pin_raw}.items():
            target = output / "hk_input" / name
            with target.open("xb") as stream:
                stream.write(raw)
            target.chmod(0o600)
        if copy_shared:
            destination = output / "shared_data"
            sources.copy_tree(shared, destination, DEFAULT_TREE_POLICY)
            expected_shared = sources.copy_entries(trees[shared])
            _check(_snapshot(destination)["entries"] == expected_shared, "SHARED_COPY_CHANGED_DURING_COPY")
            sources.write_candidate(destination, SHARED_HQ, afters[HQ], expected_sha256=shared_before,
                                    mode=expected_shared[SHARED_HQ]["mode"])
            expected_shared[SHARED_HQ]["sha256"] = selected[HQ]["after_sha256"]
            result["shared_source"]["permissions_restored"] = _snapshot(destination)["entries"] == expected_shared
            _check(result["shared_source"]["permissions_restored"], "SHARED_COPY_BYTES_OR_PERMISSIONS_MISMATCH")
        _check(_digest(_read(Path(prepared["shared_data_root"]) / SHARED_HQ)) == selected[HQ]["after_sha256"],
               "EFFECTIVE_SHARED_HQ_AFTER_SHA_MISMATCH")
        _write_json(output / "config.json", prepared)
        result["status"] = "PREPARED"
        if execute:
            command = [str(python), "-B", "-c", OWNER, str(app), str(output / "config.json"), pin["trade_date"],
                       stage_id, evaluated.isoformat(), str(output / "result.json")]
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "RESEARCH_ONLY": "true",
                   "PYTHONPATH": os.pathsep.join(filter(None, (str(app), os.environ.get("PYTHONPATH", ""))))}
            result["status"] = "EXECUTION_FAILED"
            child = subprocess.run(command, cwd=app, env=env, capture_output=True, text=True)
            result["child_returncode"] = child.returncode
            _check(child.returncode == 0 and (output / "result.json").is_file(), "OWNER_INVOCATION_FAILED")
            result["executed"] = True
            _verify_owner(json.loads(_read(output / "result.json")), output, result)
        result["input_bytes_unchanged"] = (all(_digest(_read(path)) == expected for path, expected in guarded.items())
                                            and all(_same_snapshot(files, _snapshot(path, tree_policies[path], candidate=path == app))
                                                    for path, files in trees.items()))
        _check(result["input_bytes_unchanged"], "READ_INPUT_BYTES_CHANGED")
        if copy_shared:
            _check(_snapshot(output / "shared_data")["entries"] == expected_shared, "EFFECTIVE_SHARED_COPY_CHANGED")
    except (OSError, ValueError, TypeError, KeyError, shutil.Error) as error:
        result["errors"].append(str(error) if isinstance(error, ValueError) else "CANARY_ERROR:" + type(error).__name__)
        if created:
            result["status"] = "CANNOT_CONFIRM"
    if created:
        _write_json(output / "run_manifest.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--stage-app", required=True)
    parser.add_argument("--config", required=True, dest="config_path")
    parser.add_argument("--hk-input", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--stage-id", required=True, choices=sorted(STAGES))
    parser.add_argument("--execute", action="store_true")
    result = run_canary(**vars(parser.parse_args(argv)))
    keys = ("schema_version", "status", "trade_date", "stage_id", "evaluated_at", "executed",
            "input_bytes_unchanged", "output_paths", "selected_rows", "errors", *FLAGS)
    print(json.dumps({key: result[key] for key in keys if key in result}, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] in {"PREPARED", "RESEARCH_ROWS_WRITTEN"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
