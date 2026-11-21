"""Verify dated V4 Top200 lineage. This tool performs no producer or control actions."""
import argparse
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
from urllib.request import HTTPRedirectHandler, build_opener

FLAGS = {"RESEARCH_ONLY":True,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}
WORKLOAD = "research_panel_daily_a"
MAIN_PLIST = Path.home()/"Library/LaunchAgents/com.lexi.v4.scheduler.plist"
MAIN_LAUNCHER_RELATIVE = "ops/launch_v4_macos_scheduler.sh"
MAIN_DAEMON_RELATIVE = "ops/run_v4_macos_scheduler_daemon.py"
MAIN_CACHE_PREFIX = "/dev/null/v4-main-r4-source-only-pycache"
MAIN_DAEMON_MODULE = "ops.run_v4_macos_scheduler_daemon"
QFQ_DIRECTORY_CONTRACT_RELATIVE = "ops/qfq_directory_contract.py"


def check(ok, reason):
    if not ok:
        raise ValueError(reason)


def hash_raw(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def read_stable(path):
    """Read an exact regular file once and bind the bytes to its stable stat."""
    path = Path(path)
    before = path.lstat()
    check(stat.S_ISREG(before.st_mode) and not path.is_symlink(), "REGULAR_FILE_REQUIRED:" + path.name)
    raw = path.read_bytes()
    after = path.lstat()
    check((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
          (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
          "FILE_CHANGED_DURING_READ:" + path.name)
    return json.loads(raw), hash_raw(raw), raw


def load(ref, exact_copy=None):
    path = exact_copy or Path(ref["path"])
    raw = path.read_bytes()
    check(hash_raw(raw)==ref["sha256"],"ARTIFACT_SHA_MISMATCH:"+path.name)
    return json.loads(raw)


def same_safety(obj):
    return all(obj.get(k) is v for k,v in FLAGS.items())


def no_production_permissions(obj):
    return all(obj.get(k) is False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))


def time(value):
    parsed=datetime.fromisoformat(value)
    check(parsed.utcoffset() is not None,"OFFSET_REQUIRED")
    return parsed


def ledger_hash(value):
    unhashed = {k:v for k,v in value.items() if k != "ledger_sha256"}
    return hash_raw(json.dumps(unhashed,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode())


def _stable_file_bytes(path, reason):
    path = Path(path)
    before = path.lstat()
    check(stat.S_ISREG(before.st_mode) and not path.is_symlink()
          and path.resolve(strict=True)==path, reason)
    raw = path.read_bytes()
    after = path.lstat()
    check((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) ==
          (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns), reason + "_CHANGED")
    return raw, after


def _launchctl_program_arguments(job):
    program_match = re.search(r"^\s*program = (.+?)\s*$", job, re.M)
    block = re.search(r"^\s*arguments = \{\s*\n(?P<body>.*?)^\s*\}\s*$", job, re.M | re.S)
    check(program_match is not None and block is not None, "LOADED_MAIN_LAUNCH_ARGUMENTS_REQUIRED")
    arguments = [line.strip() for line in block.group("body").splitlines() if line.strip()]
    return program_match.group(1), arguments


def _verify_manifest_app_file(manifest, app_root, relative_path):
    inventory = manifest.get("application_inventory")
    entries = inventory.get("entries") if isinstance(inventory, dict) else None
    check(isinstance(entries, list), "LOADED_MAIN_APPLICATION_INVENTORY_REQUIRED")
    matching = [item for item in entries if isinstance(item, dict) and item.get("path") == relative_path]
    check(len(matching) == 1, "LOADED_MAIN_APPLICATION_FILE_NOT_UNIQUE:" + relative_path)
    entry = matching[0]
    check(entry.get("kind") == "file" and isinstance(entry.get("sha256"), str)
          and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
          and type(entry.get("size")) is int and isinstance(entry.get("mode"), str),
          "LOADED_MAIN_APPLICATION_ENTRY_INVALID:" + relative_path)
    path = app_root / relative_path
    raw, info = _stable_file_bytes(path, "LOADED_MAIN_APPLICATION_FILE_INVALID:" + relative_path)
    check(hash_raw(raw) == entry["sha256"] and len(raw) == entry["size"]
          and format(stat.S_IMODE(info.st_mode), "04o") == entry["mode"],
          "LOADED_MAIN_APPLICATION_FILE_DRIFT:" + relative_path)
    return path


def _load_qfq_directory_contract(app_root, expected_sha256):
    app_root = Path(app_root)
    path = app_root / QFQ_DIRECTORY_CONTRACT_RELATIVE
    raw, _ = _stable_file_bytes(path, "LOADED_MAIN_QFQ_DIRECTORY_CONTRACT_INVALID")
    check(hash_raw(raw) == expected_sha256,
          "LOADED_MAIN_QFQ_DIRECTORY_CONTRACT_SHA_MISMATCH")
    name = "_v4_qfq_directory_contract_" + expected_sha256[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    check(spec is not None and spec.loader is not None,
          "LOADED_MAIN_QFQ_DIRECTORY_CONTRACT_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check(callable(getattr(module, "validate_qfq_generation_directory", None)),
          "LOADED_MAIN_QFQ_DIRECTORY_CONTRACT_INVALID")
    return module


def _check_daemon_command(command, executable):
    prefix = (str(executable) + " -X pycache_prefix=" + MAIN_CACHE_PREFIX
              + " -B -S -m " + MAIN_DAEMON_MODULE)
    return command == prefix or command.startswith(prefix + " ")


def loaded_identity(env,started):
    label="com.lexi.v4.scheduler"
    job=subprocess.run(["/bin/launchctl","print",f"gui/{os.getuid()}/{label}"],
                       check=True,capture_output=True,text=True,timeout=10).stdout
    def field(pattern):
        match=re.search(pattern,job,re.M)
        check(bool(match),"LOADED_MAIN_IDENTITY_REQUIRED")
        return match[1]
    root=field(r"^\s*working directory = (.+)$")
    path=field(r"^\s*path = (.+)$")
    manifest_sha=field(r"^\s*V4_RELEASE_MANIFEST_SHA256 => ([0-9a-f]{64})\s*$")
    manifest_path=field(r"^\s*V4_RELEASE_MANIFEST_PATH => (.+?)\s*$")
    release_id=field(r"^\s*V4_RELEASE_ID => (.+?)\s*$")
    daemon_mode=field(r"^\s*V4_DAEMON_MODE => (.+?)\s*$")
    loaded_root=field(r"^\s*V4_APP_ROOT => (.+?)\s*$")
    pid=field(r"^\s*pid = ([1-9][0-9]*)\s*$")
    app_root=Path(env["V4_APP_ROOT"])
    check(app_root.is_absolute() and app_root.resolve(strict=True)==app_root
          and root==str(app_root)==loaded_root and path==str(MAIN_PLIST)
          and daemon_mode==env.get("V4_DAEMON_MODE")=="persistent-minute"
          and release_id==env.get("V4_RELEASE_ID")
          and manifest_path==env.get("V4_RELEASE_MANIFEST_PATH")
          and manifest_sha==env["V4_RELEASE_MANIFEST_SHA256"],
          "LOADED_MAIN_MANIFEST_OR_WORKDIR_DRIFT")
    plist_raw,_=_stable_file_bytes(MAIN_PLIST,"MAIN_PLIST_INVALID")
    plist=plistlib.loads(plist_raw)
    expected_launcher=str(app_root/MAIN_LAUNCHER_RELATIVE)
    check(isinstance(plist,dict) and "Program" not in plist
          and plist.get("ProgramArguments")==["/bin/bash",expected_launcher],
          "MAIN_PLIST_LAUNCHER_ARGUMENTS_MISMATCH")
    program,loaded_arguments=_launchctl_program_arguments(job)
    check(program=="/bin/bash" and loaded_arguments==["/bin/bash",expected_launcher],
          "LOADED_MAIN_LAUNCHER_ARGUMENTS_MISMATCH")
    manifest_file=Path(manifest_path)
    check(manifest_file.is_absolute() and manifest_file.resolve(strict=True)==manifest_file,
          "LOADED_MAIN_MANIFEST_PATH_INVALID")
    manifest_raw,_=_stable_file_bytes(manifest_file,"LOADED_MAIN_MANIFEST_INVALID")
    check(hash_raw(manifest_raw)==manifest_sha,"LOADED_MAIN_MANIFEST_SHA_MISMATCH")
    manifest=json.loads(manifest_raw)
    check(isinstance(manifest,dict) and manifest.get("app_root")==str(app_root)
          and manifest.get("release_id")==release_id,
          "LOADED_MAIN_MANIFEST_RELEASE_BINDING_MISMATCH")
    _verify_manifest_app_file(manifest,app_root,MAIN_LAUNCHER_RELATIVE)
    _verify_manifest_app_file(manifest,app_root,MAIN_DAEMON_RELATIVE)
    qfq_contract_path = _verify_manifest_app_file(
        manifest, app_root, QFQ_DIRECTORY_CONTRACT_RELATIVE)
    proc=subprocess.run(["/bin/ps","-ww","-p",pid,"-o","lstart=","-o","command="],
                        check=True,capture_output=True,text=True,timeout=10,
                        env={**os.environ,"LC_ALL":"C"}).stdout.strip()
    check(len(proc)>25,"LOADED_MAIN_EXECUTOR_REQUIRED")
    start_text=" ".join(proc[:24].split())
    started_at=datetime.strptime(start_text,"%a %b %d %H:%M:%S %Y").astimezone()
    exe=str(Path(env["V4_RUNTIME_ROOT"])/"venvs/v4-mac/bin/python")
    command=proc[24:].strip()
    check(_check_daemon_command(command,exe) and started_at<=started,
          "LOADED_MAIN_EXECUTOR_OR_START_MISMATCH")
    return {"manifest_sha256":manifest_sha,"daemon_pid":int(pid),"daemon_started_at":started_at.isoformat(),
            "interpreter_sha256":sha(Path(exe)),"daemon_mode":daemon_mode,
            "app_root":str(app_root),
            "qfq_directory_contract_sha256":sha(qfq_contract_path)}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def _store_api_response(output, payload, env):
    """Store exact response bytes only in an explicit non-live evidence folder."""
    path = Path(output)
    check(path.is_absolute(), "API_RESPONSE_OUTPUT_MUST_BE_ABSOLUTE")
    parent = path.parent
    check(parent.is_dir() and parent.resolve(strict=True) == parent,
          "API_RESPONSE_OUTPUT_PARENT_MUST_EXIST_WITHOUT_SYMLINKS")
    check(path.name not in {"", ".", ".."} and not path.exists() and not path.is_symlink(),
          "API_RESPONSE_OUTPUT_MUST_BE_NEW")
    destination = parent / path.name
    roots = (
        "V4_A_SHARE_DAILY_PRODUCT_ROOT", "V4_RESEARCH_PANEL_RECEIPT_ROOT",
        "V4_RESEARCH_PANEL_A_TDX_ROOT", "V4_RESEARCH_PANEL_A_DATA_ROOT",
        "V4_RESEARCH_PANEL_A_RETURN_ROOT", "V4_DISPATCH_LEDGER_ROOT",
    )
    for key in roots:
        value = env.get(key)
        if not value:
            continue
        live = Path(value)
        if not live.is_absolute():
            continue
        live = live.resolve(strict=True)
        check(not destination.is_relative_to(live) and not live.is_relative_to(destination),
              "API_RESPONSE_OUTPUT_INSIDE_LIVE_ROOT:" + key)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        check(hash_raw(destination.read_bytes()) == hash_raw(payload),
              "API_RESPONSE_WRITE_SHA_MISMATCH")
    except BaseException:
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    return hash_raw(payload)


def fetch_api(date, response_output=None, env=None):
    url="http://127.0.0.1:8873/api/v4/research/a-share/top200-hit?date="+date
    with build_opener(NoRedirect).open(url,timeout=40) as response:
        check(response.status==200 and response.geturl()==url,"FORMAL_API_HTTP_OR_URL")
        payload=response.read(8*1024*1024+1)
    check(len(payload)<=8*1024*1024,"FORMAL_API_RESPONSE_TOO_LARGE")
    if response_output is not None:
        check(env is not None, "API_RESPONSE_ENVIRONMENT_REQUIRED")
        _store_api_response(response_output, payload, env)
    return json.loads(payload), hash_raw(payload)


def verify_api(date,env,publication=None, index_copy=None, event_copy=None, manual_proof=None,
               response_output=None):
    root=Path(env["V4_A_SHARE_DAILY_PRODUCT_ROOT"])/"daily_products/a_share"
    index=read(root/"index.json")
    numeric_ref=index["dates"][date]
    top_ref=index["top200"][date]
    numeric=load(numeric_ref)
    top=load(top_ref)
    generation=numeric["source_generation"]
    source=numeric["input_sha256"]
    check(all(re.fullmatch("[0-9a-f]{64}",value) for value in (generation,source)),"GENERATION_INPUT_IDENTITY")
    for item in (numeric,top):
        check(item.get("data_date")==date and item.get("source_generation")==generation
              and item.get("input_sha256")==source and same_safety(item),"EVENT_NUMERIC_TOP200_LINEAGE")
    check(top["numeric_manifest"]==numeric_ref and numeric.get("sample_only") is False,"EXACT_NUMERIC_TOP200_LINKAGE")
    if publication is not None:
        check(publication.get("status")=="PUBLISHED_TOP200","TOP200_ACTUAL_PUBLICATION_REQUIRED")
        check(same_safety(publication),"RESEARCH_BOUNDARY_PUBLICATION")
        # The same dispatch records later attempts by moving mutable index.json.
        # Read the exact staged originals when the publisher's refs have advanced.
        released_index=load(publication["index"],index_copy)
        check(released_index["dates"][date]==numeric_ref and released_index["top200"][date]==top_ref,
              "PUBLICATION_INDEX_NOT_SAME_DATE_REFS")
        event=load(publication["event"],event_copy)
        check(event.get("data_date")==date and event.get("source_generation")==generation
              and event.get("input_sha256")==source and same_safety(event)
              and event["manifest"]==numeric_ref and event["top200"]==top_ref
              and event["artifact"]==numeric["artifact"],"FORMAL_INDEX_EVENT_LINKAGE")
    if manual_proof is not None:
        check(manual_proof.get("manual_publication") is True and manual_proof.get("data_date")==date
              and manual_proof.get("generation")==generation and manual_proof.get("numeric_manifest")==numeric_ref
              and manual_proof.get("top200_artifact")==top_ref,"HISTORICAL_MANUAL_EVIDENCE_CONFLICT")
    symbols=[x["symbol"] for x in top["top200"]]
    check(top.get("top200_count")==len(symbols)==len(set(symbols))==200,"EXACT_200_DISTINCT_SYMBOLS")
    api,api_sha=fetch_api(date,response_output=response_output,env=env)
    check(api.get("requested_date")==date and api.get("selected_source_status")=="SAME_SNAPSHOT_RECONCILED"
          and same_safety(api["safety_flags"]),"FORMAL_API_EXACT_DATE_SOURCE")
    detail=api["detail_projection"]
    check(detail["source_generation"]==generation and detail["top200_artifact"]==top_ref
          and detail["numeric_manifest"]==numeric_ref,"FORMAL_API_EXACT_GENERATION")
    rows=[x for x in api["dates"] if x["date"]==date]
    check(len(rows)==1 and rows[0]["top200"]["top_count"]==200,"FORMAL_API_EXACT_COUNT")
    coverage=rows[0]["stage_coverage"]
    check(coverage["available"]==coverage["total"]==7 and coverage["missing_stages"]==[],"EXACT_7_OF_7_STAGES")
    current=read(root/"index.json")
    check(current["dates"][date]==numeric_ref and current["top200"][date]==top_ref,"FORMAL_INDEX_CHANGED_DURING_READ")
    return {"target_date":date,"http":200,"distinct_stocks":200,"stage_coverage":coverage,
            "source_status":"SAME_SNAPSHOT_RECONCILED","api_date_row_status":rows[0]["status"],
            "generation":generation,"input_sha256":source,"response_sha256":api_sha,
            "api_response_bytes_path":str(response_output) if response_output is not None else None,
            "api_response_file_sha256":api_sha if response_output is not None else None,
            "numeric_manifest_sha256":numeric_ref["sha256"],"top200_artifact_sha256":top_ref["sha256"],
            "completion_event_sha256":publication["event"]["sha256"] if publication else None}


def _valid_sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_qfq_registry_proof(qfq, official, env, date, directory_contract):
    check(isinstance(qfq, dict) and qfq.get("schema") == "v4.qfq_natural_execution.v2",
          "QFQ_NATURAL_EXECUTION_PROOF_REQUIRED")
    check(qfq.get("status") == "CLAIM_FINISHED_READY"
          and qfq.get("already_current") is False, "QFQ_FRESH_FINISHED_CLAIM_REQUIRED")
    task_key = qfq.get("task_key")
    attempt = qfq.get("attempt")
    token_sha = qfq.get("claim_token_sha256")
    check(_valid_sha(task_key) and type(attempt) is int and attempt > 0 and _valid_sha(token_sha),
          "QFQ_TASK_KEY_ATTEMPT_TOKEN_REQUIRED")
    check(qfq.get("target_date") == date, "QFQ_TASK_DATE_MISMATCH")
    refs = (qfq.get("candidate_receipt"), qfq.get("ready_receipt"))
    docs = []
    for ref in refs:
        check(isinstance(ref, dict) and isinstance(ref.get("path"), str)
              and Path(ref["path"]).is_absolute() and _valid_sha(ref.get("sha256")),
              "QFQ_OWNER_RECEIPT_REFERENCE_INVALID")
        document, observed_sha, _ = read_stable(Path(ref["path"]))
        check(observed_sha == ref["sha256"], "QFQ_OWNER_RECEIPT_SHA_MISMATCH")
        check(isinstance(document, dict), "QFQ_OWNER_RECEIPT_OBJECT_REQUIRED")
        docs.append(document)
    candidate, ready = docs
    policy_path_text = env.get("V4_RESEARCH_RETENTION_POLICY")
    policy_sha = env.get("V4_RESEARCH_RETENTION_POLICY_SHA256")
    check(isinstance(policy_path_text, str) and policy_path_text and _valid_sha(policy_sha),
          "QFQ_POLICY_BINDING_REQUIRED")
    policy_path = Path(policy_path_text)
    policy, observed_policy_sha, _ = read_stable(policy_path)
    check(observed_policy_sha == policy_sha, "QFQ_POLICY_SHA_MISMATCH")
    governance = policy.get("governance") if isinstance(policy, dict) else None
    registry_root_text = governance.get("registry_root") if isinstance(governance, dict) else None
    check(isinstance(registry_root_text, str) and Path(registry_root_text).is_absolute(),
          "QFQ_POLICY_REGISTRY_ROOT_REQUIRED")
    registry_root = Path(registry_root_text)
    check(registry_root.resolve(strict=True) == registry_root
          and qfq.get("registry_root") == registry_root_text, "QFQ_REGISTRY_ROOT_BINDING")
    registry_path = registry_root / "registry.json"
    state, _, _ = read_stable(registry_path)
    check(isinstance(state, dict) and state.get("schema") == "v4_storage_governance_v2"
          and state.get("pool_id") == governance.get("pool_id")
          and isinstance(state.get("tasks"), dict), "QFQ_REGISTRY_SCHEMA_OR_POOL")
    row = state["tasks"].get(task_key)
    check(isinstance(row, dict), "QFQ_TASK_ROW_MISSING")
    authority = official.get("formula", {}).get("authority", {})
    generation = authority.get("generation_id")
    source_sha = authority.get("source_sha256")
    policy_run_root = policy.get("run_root")
    check(isinstance(policy_run_root, str) and policy_run_root
          and qfq.get("return_root") == policy_run_root,
          "QFQ_RETURN_ROOT_POLICY_BINDING")
    try:
        return_root, run_dir = directory_contract.validate_qfq_generation_directory(
            qfq.get("return_root"), qfq.get("run_dir"), generation)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("QFQ_GENERATION_DIRECTORY_BINDING") from exc
    check(row.get("directory") == str(return_root),
          "QFQ_RETURN_ROOT_REGISTRY_ROW_MISMATCH")
    owner = qfq.get("claim_owner")
    check(isinstance(owner, dict) and type(owner.get("pid")) is int and owner.get("pid") > 0
          and isinstance(owner.get("started"), str) and bool(owner.get("started")),
          "QFQ_OWNER_IDENTITY_INVALID")
    token = row.get("token")
    check(isinstance(token, str) and re.fullmatch(r"[0-9a-f]{32}", token) is not None
          and hash_raw(token.encode("ascii")) == token_sha, "QFQ_CLAIM_TOKEN_SHA_MISMATCH")
    check(row.get("state") == "READY" and row.get("owner") == owner
          and type(row.get("attempts")) is int and row.get("attempts") == attempt
          and row.get("directory") == qfq.get("return_root")
          and row.get("qfq_identity", {}).get("key") == task_key
          and row.get("qfq_identity", {}).get("target") == int(date),
          "QFQ_TERMINAL_REGISTRY_ROW_MISMATCH")
    row_raw = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    check(hash_raw(row_raw) == qfq.get("registry_row_sha256"), "QFQ_REGISTRY_ROW_SHA_MISMATCH")

    check(candidate.get("status") in {"CANDIDATE_READY", "READY"}
          and ready.get("status") == "READY"
          and str(candidate.get("target_date")) == date
          and str(ready.get("target_date")) == date
          and same_safety(candidate) and same_safety(ready)
          and ready.get("selector_pointer_ready") is True
          and ready.get("backtest_pointer_ready") is True
          and candidate.get("run_dir") == ready.get("run_dir") == str(run_dir)
          and qfq.get("run_dir") == str(run_dir)
          and refs[0]["path"] == str(run_dir / "candidate_receipt.json")
          and refs[1]["path"] == str(run_dir / "stage_status.json")
          and candidate.get("generation_id") == ready.get("generation_id") == generation
          and candidate.get("input_sha256") == ready.get("input_sha256") == source_sha
          and qfq.get("generation_id") == generation
          and qfq.get("input_sha256") == source_sha,
          "QFQ_OWNER_RECEIPT_GENERATION_OR_INPUT_MISMATCH")
    check(isinstance(ready.get("candidates"), dict)
          and isinstance(ready.get("candidate_sha256"), dict)
          and set(ready["candidates"]) == {"selector", "backtest"}
          and set(ready["candidate_sha256"]) == {"selector", "backtest"},
          "QFQ_OWNER_RECEIPT_PAIR_REQUIRED")
    for role in ("selector", "backtest"):
        check(ready["candidates"][role] == official.get(role)
              and ready["candidate_sha256"][role] == official.get(role + "_sha256"),
              "QFQ_OWNER_RECEIPT_ARTIFACT_MISMATCH:" + role)
    summary = row.get("result")
    check(isinstance(summary, dict)
          and summary.get("schema") == "qfq_registry_owner_receipt_summary.v1"
          and summary.get("complete_owner_receipt") == refs[0]
          and summary.get("ready_owner_receipt") == refs[1]
          and summary.get("generation_id") == generation
          and summary.get("target_date") == int(date), "QFQ_REGISTRY_RESULT_RECEIPT_MISMATCH")
    artifacts = row.get("artifacts")
    check(isinstance(artifacts, list), "QFQ_REGISTRY_ARTIFACTS_MISSING")
    artifact_map = {item.get("path"): item.get("sha256") for item in artifacts if isinstance(item, dict)}
    check(artifact_map.get(official.get("selector")) == official.get("selector_sha256")
          and artifact_map.get(official.get("backtest")) == official.get("backtest_sha256"),
          "QFQ_REGISTRY_ARTIFACTS_MISMATCH")
    return {"task_key": task_key, "attempt": attempt, "registry_row_sha256": qfq["registry_row_sha256"],
            "claim_token_sha256": token_sha, "generation_id": generation, "input_sha256": source_sha,
            "owner_receipt_sha256": [refs[0]["sha256"], refs[1]["sha256"]]}


def _validate_natural_source(outcome, official, official_path, official_file_sha,
                             claim, work, claim_sha, work_sha, date, slot, run, env,
                             directory_contract):
    saved_ref = outcome.get("dated_source_receipt")
    check(isinstance(saved_ref, dict) and saved_ref.get("path") == str(official_path)
          and saved_ref.get("sha256") == official_file_sha,
          "DISPATCH_DATED_RECEIPT_RAW_SHA_BINDING")
    source_result = outcome.get("source_result")
    check(isinstance(source_result, dict), "NATURAL_SOURCE_RESULT_REQUIRED")
    context = source_result.get("natural_dispatch_context")
    expected_context = {
        "schema": "v4.natural_dispatch_context.v1", "mode": "LIVE",
        "business_date": date, "target_date": date, "slot": slot,
        "run_id": run, "workload_id": WORKLOAD, "dispatcher_pid": claim["pid"],
        "dispatch_claim_sha256": claim_sha, "workload_claim_sha256": work_sha,
        "dispatch_claim_created_at": claim.get("created_at"),
        "workload_claim_created_at": work.get("created_at"),
    }
    check(context == expected_context, "NATURAL_DISPATCH_CONTEXT_MISMATCH")
    lane_map = source_result.get("lanes")
    lane = lane_map.get("A") if isinstance(lane_map, dict) else None
    check(isinstance(lane, dict), "NATURAL_A_SOURCE_LANE_REQUIRED")
    official_sync = official.get("sync")
    official_formula = official.get("formula")
    check(isinstance(official_sync, dict) and isinstance(official_formula, dict),
          "NATURAL_DATED_SYNC_FORMULA_REQUIRED")
    lane_sync = lane.get("sync")
    lane_formula = lane.get("formula")
    check(isinstance(lane_sync, dict) and isinstance(lane_formula, dict)
          and lane_sync.get("provider_invocation") == official_sync.get("provider_invocation")
          and lane_formula.get("natural_execution") == official_formula.get("natural_execution"),
          "NATURAL_DISPATCH_AND_DATED_RECEIPT_PROOF_MISMATCH")
    provider = official_sync.get("provider_invocation")
    qfq = official_formula.get("natural_execution")
    check(isinstance(provider, dict)
          and provider.get("schema") == "v4.natural_source_provider_invocation.v1"
          and provider.get("provider_task_name") == "tdxpy_daily_vipdoc_sync_v1"
          and provider.get("provider_run_id") and isinstance(provider.get("provider_run_id"), str)
          and re.fullmatch(rf"{date}-[0-9a-f]{{16}}-[0-9]+", provider["provider_run_id"])
          and provider.get("target_date") == date and provider.get("status") == "PASS"
          and type(provider.get("exit_code")) is int and provider.get("exit_code") == 0
          and provider.get("dispatch") == context
          and type(provider.get("parent_dispatcher_pid")) is int
          and provider.get("parent_dispatcher_pid") == claim["pid"],
          "NATURAL_RAW_PROVIDER_INVOCATION_REQUIRED")
    producer = provider.get("producer_process")
    check(isinstance(producer, dict) and type(producer.get("pid")) is int and producer.get("pid") > 0
          and isinstance(producer.get("started"), str) and bool(producer.get("started")),
          "NATURAL_PROVIDER_PROCESS_IDENTITY_REQUIRED")
    check(outcome.get("migration_reuse") is False and type(outcome.get("migration_reuse")) is bool
          and outcome.get("provider_invoked") is True and type(outcome.get("provider_invoked")) is bool
          and outcome.get("source_recomputed") is True and type(outcome.get("source_recomputed")) is bool,
          "NATURAL_PRODUCER_FLAGS_MUST_BE_EXPLICIT_TRUE")
    qfq_result = _validate_qfq_registry_proof(qfq, official, env, date, directory_contract)
    check(qfq.get("dispatch") == context and qfq.get("provider_invocation") == provider
          and qfq.get("claim_owner") == producer
          and qfq.get("target_date") == date and qfq.get("already_current") is False,
          "NATURAL_QFQ_PRODUCER_BINDING_MISMATCH")
    return context, provider, qfq, qfq_result


def verify_natural(args,env):
    date,slot,run=args.date,args.slot,args.run_id
    check(isinstance(date,str) and re.fullmatch(r"[0-9]{8}",date)
          and isinstance(slot,str) and slot in {"1540","1610","1640"}
          and isinstance(run,str) and re.fullmatch(r"[0-9a-f]{32}",run),"RUN_SCOPE_REQUIRED")
    check(isinstance(args.release_id,str) and env.get("V4_RELEASE_ID")==args.release_id
          and env.get("V4_DAEMON_MODE")=="persistent-minute",
          "INSTALLED_MAIN_RELEASE_OR_DAEMON_UNBOUND")
    check(args.api_response_output is not None,"FORMAL_API_RAW_RESPONSE_OUTPUT_REQUIRED")
    ledger=Path(env["V4_DISPATCH_LEDGER_ROOT"])
    check(ledger.is_absolute() and ledger.resolve(strict=True)==ledger,"DISPATCH_LEDGER_ROOT_INVALID")
    suffix=Path("live")/date/slot
    dispatch_path=ledger/"receipts"/suffix/(run+".dispatch-receipt.json")
    dispatch, dispatch_file_sha, _ = read_stable(dispatch_path)
    check(dispatch.get("schema_version")=="v3_5.dispatch.v1"
          and dispatch.get("ledger_sha256")==ledger_hash(dispatch)
          and dispatch.get("run_id")==run and dispatch.get("release_id")==args.release_id
          and dispatch.get("status")=="SUCCEEDED"
          and dispatch.get("mode")=="LIVE"
          and type(dispatch.get("attempt")) is int and dispatch.get("attempt")>0
          and dispatch.get("business_date")==dispatch.get("target_date")==date
          and dispatch.get("slot")==slot
          and no_production_permissions(dispatch)
          and isinstance(dispatch.get("succeeded_workload_ids"),list)
          and isinstance(dispatch.get("invoked_workload_ids"),list)
          and WORKLOAD in dispatch["succeeded_workload_ids"]
          and WORKLOAD in dispatch["invoked_workload_ids"],
          "DISPATCH_NOT_A_DAILY_SUCCESS")
    claim, claim_sha, _ = read_stable(ledger/"claims"/suffix/"dispatch.claim.json")
    work, work_sha, _ = read_stable(ledger/"workloads"/suffix/(WORKLOAD+".workload-claim.json"))
    for item in (dispatch,claim,work):
        check(item.get("mode")=="LIVE" and item.get("business_date")==item.get("target_date")==date
              and item.get("slot")==slot and item.get("run_id")==run,
              "CLAIM_DISPATCH_DATE_OR_RUN")
    check(claim.get("schema_version")=="v3_5.dispatch_claim.v1"
          and work.get("schema_version")=="v3_5.workload_claim.v1", "CLAIM_SCHEMA_MISMATCH")
    pid=claim.get("pid")
    check(type(pid) is int and pid>0 and type(work.get("pid")) is int and work.get("pid")==pid
          and type(work.get("workload_id")) is str and work.get("workload_id")==WORKLOAD,
          "CLAIMS_EXECUTOR_MISMATCH")
    for item in (dispatch, claim, work):
        for identity_field in ("owner_id", "executor_id"):
            if identity_field in item:
                check(type(item[identity_field]) is str and bool(item[identity_field]),
                      "CLAIM_EXECUTOR_ID_TYPE_INVALID")
    observation_paths=sorted((ledger/"scheduler_observations"/suffix).glob("*.observation.json"))
    observed=[read_stable(p)[0] for p in observation_paths]
    relevant=[x for x in observed if type(x.get("pid")) is int and x.get("pid")==pid
              and x.get("lane")=="A_LONG" and x.get("schema_version")=="v4.scheduler_observation.v1"
              and x.get("slot")==slot and x.get("business_date")==date]
    for observation in relevant:
        for identity_field in ("owner_id", "executor_id"):
            if identity_field in observation:
                check(type(observation[identity_field]) is str and bool(observation[identity_field]),
                      "OBSERVATION_EXECUTOR_ID_TYPE_INVALID")
    starts=[x for x in relevant if x.get("status")=="RUNNING"]
    ends=[x for x in relevant if x.get("status")=="FINISHED"
          and type(x.get("return_code")) is int and x.get("return_code")==0
          and x.get("result_status")=="SUCCEEDED"]
    check(len(starts)==len(ends)==1,"NATURAL_DAEMON_RUN_AND_FINISH_REQUIRED")
    start,end=starts[0],ends[0]
    started=time(start["actual_started_at"])
    check(started.strftime("%Y%m%d")==date and started.utcoffset()==timedelta(hours=8)
          and time(start["planned_at"])<=started<=time(start["cutoff_at"])
          and end["actual_started_at"]==start["actual_started_at"]
          and started<=time(claim["created_at"])<=time(dispatch["finished_at"])<=time(end["observed_at"])
          and end.get("run_id")==run,
          "NATURAL_DAEMON_TIMELINE")
    loaded=loaded_identity(env,started)
    check(type(loaded.get("daemon_pid")) is int and loaded["daemon_pid"]>0
          and isinstance(loaded.get("daemon_started_at"),str)
          and loaded.get("daemon_mode")=="persistent-minute"
          and _valid_sha(loaded.get("manifest_sha256")), "LOADED_MAIN_DAEMON_IDENTITY_INCOMPLETE")
    check(time(loaded["daemon_started_at"])<=started, "LOADED_MAIN_STARTED_AFTER_SLOT")
    directory_contract = _load_qfq_directory_contract(
        loaded.get("app_root"), loaded.get("qfq_directory_contract_sha256"))
    for observation in (start,end):
        check(type(observation.get("daemon_pid")) is int
              and observation.get("daemon_pid")==loaded["daemon_pid"]
              and observation.get("daemon_started_at")==loaded["daemon_started_at"]
              and observation.get("release_manifest_sha256")==loaded["manifest_sha256"],
              "OBSERVED_DAEMON_MAIN_IDENTITY_MISMATCH")
    workload_results=dispatch.get("workload_results")
    check(isinstance(workload_results,list),"DISPATCH_WORKLOAD_RESULTS_REQUIRED")
    outcomes=[x for x in workload_results if isinstance(x,dict)
              and x.get("workload_id")==WORKLOAD and x.get("status")=="SUCCEEDED"]
    check(len(outcomes)==1,"ONE_A_DAILY_WORKLOAD_SUCCESS_REQUIRED")
    outcome=outcomes[0]
    check(outcome.get("lane")=="A" and outcome.get("target_date")==date
          and type(outcome.get("workload_id")) is str and outcome.get("workload_id")==WORKLOAD,
          "NATURAL_WORKLOAD_IDENTITY")
    official_path=Path(env["V4_RESEARCH_PANEL_RECEIPT_ROOT"])/("a-"+date+".json")
    official, official_file_sha, _ = read_stable(official_path)
    check(official.get("status")=="READY" and same_safety(official), "NATURAL_A_DATED_RECEIPT_NOT_READY")
    check(no_production_permissions(outcome), "NATURAL_DISPATCH_WORKLOAD_SAFETY_FLAGS")
    context, provider, qfq, qfq_summary = _validate_natural_source(
        outcome,official,official_path,official_file_sha,claim,work,claim_sha,work_sha,date,slot,run,env,
        directory_contract
    )
    summary=outcome["source_result"]["lanes"]["A"]
    check(str(official["target_date"])==date and str(summary["target_date"])==date and official["sha256"]==summary["sha256"],
          "A_DAILY_RECEIPT_NOT_FROM_THIS_DISPATCH")
    logical_sha = hash_raw(
        f"selector:{official['selector_sha256']}\nbacktest:{official['backtest_sha256']}\n".encode("ascii")
    )
    check(_valid_sha(official.get("selector_sha256")) and _valid_sha(official.get("backtest_sha256"))
          and official.get("sha256")==logical_sha,
          "A_DAILY_LOGICAL_SHA_CONTRACT_MISMATCH")
    for role in ("selector","backtest"):
        pointer=Path(env["V4_RESEARCH_PANEL_A_"+role.upper()+"_POINTER"])
        path=Path(official[role])
        check(pointer.read_text(encoding="utf-8-sig").strip()==str(path) and sha(path)==official[role+"_sha256"],
              "PAIRED_CURRENT_ANCHOR")
    derivative=outcome["daily_derivatives"]
    check(derivative.get("status")=="COMPLETE_DESCRIPTIVE_NONPIT" and derivative["data_date"]==date,
          "NATURAL_DERIVATIVE_COMPLETION_REQUIRED")
    recorded=load(derivative["attempt"])
    check(recorded=={k:v for k,v in derivative.items() if k!="attempt"},"DERIVATIVE_ATTEMPT_BINDING")
    result=verify_api(date,env,derivative["top200"],args.publication_index_copy,args.publication_event_copy,
                      response_output=args.api_response_output)
    authority=official["formula"]["authority"]
    check(derivative["source_generation"]==authority["generation_id"]==result["generation"]
          and authority["source_sha256"]==result["input_sha256"],"DISPATCH_PAIR_API_GENERATION_OR_INPUT")
    return {**result,"acceptance":"NATURAL_SCHEDULE_AND_API_VERIFIED","release_id":args.release_id,"loaded_main":loaded,
            "slot":slot,"dispatch_run_id":run,"dispatch_receipt_sha256":dispatch_file_sha,
            "dispatch_claim_sha256":claim_sha,"workload_claim_sha256":work_sha,
            "a_dated_receipt_file_sha256":official_file_sha,
            "a_daily_logical_sha256":official["sha256"],
            "qfq_task_key":qfq_summary["task_key"],"qfq_attempt":qfq_summary["attempt"],
            "qfq_token_sha256":qfq_summary["claim_token_sha256"],
            "qfq_registry_row_sha256":qfq_summary["registry_row_sha256"],
            "qfq_generation":qfq_summary["generation_id"],"qfq_input_sha256":qfq_summary["input_sha256"],
            "provider_run_id":provider["provider_run_id"],"natural_dispatch_context":context,
            "dated_attempt_sha256":derivative["attempt"]["sha256"]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date",required=True)
    m=p.add_mutually_exclusive_group(required=True)
    m.add_argument("--natural",action="store_true")
    m.add_argument("--manual-publication-evidence",type=Path)
    p.add_argument("--release-id")
    p.add_argument("--slot")
    p.add_argument("--run-id")
    p.add_argument("--publication-index-copy",type=Path)
    p.add_argument("--publication-event-copy",type=Path)
    p.add_argument("--api-response-output",type=Path,
                   help="absolute new file under an existing future evidence directory; outside every live root")
    a=p.parse_args()
    try:
        check(bool(re.fullmatch("[0-9]{8}",a.date)) and datetime.strptime(a.date,"%Y%m%d").strftime("%Y%m%d")==a.date,"DATE_REQUIRED")
        env=plistlib.loads(MAIN_PLIST.read_bytes())["EnvironmentVariables"]
        if a.natural:
            check(bool(a.release_id and a.run_id and a.slot and a.api_response_output),"NATURAL_SCOPE_REQUIRED")
            result=verify_natural(a,env)
        else:
            result={**verify_api(a.date,env,manual_proof=read(a.manual_publication_evidence)),
                    "acceptance":"FORMAL_API_MANUAL_PUBLICATION_READBACK","natural_schedule":"NOT_VERIFIED"}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,TypeError,KeyError,subprocess.SubprocessError) as exc:
        print(json.dumps({"acceptance":"CANNOT_CONFIRM","reason":str(exc)},ensure_ascii=False))
        return 1
    return 0


if __name__=="__main__":
    sys.exit(main())
