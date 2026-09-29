"""Run old materializer/new announcement commands only in isolated copied state.

The tool never accepts a live destination as a command target. Commands use the
literal ``{state_root}`` token, replaced with a per-scenario sandbox. It runs
single-writer, concurrent, and interruption/recovery scenarios and compares
actual changed namespaces. It never edits a LaunchAgent or live state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

from v4.manager_research.activation_canary import (
    evaluate_recovery,
    evaluate_writer_namespaces,
    write_canary_sandbox_identity,
)


def manifest(root: Path, *, symlink_error: str="CANARY_SCENARIO_SYMLINK_UNSUPPORTED") -> dict[str, str]:
    result: dict[str, str] = {}
    if not root.exists():
        return result
    if root.is_symlink() or root.resolve()!=root:
        raise ValueError(symlink_error+":.")
    symlinks=sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_symlink())
    if symlinks:
        raise ValueError(symlink_error+":"+",".join(symlinks[:8]))
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def manifest_sha(value: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def changed(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {key for key in set(before) | set(after) if before.get(key) != after.get(key)}


def _command(raw: str, root: Path, source: Path, app: Path, role: str) -> tuple[list[str], dict]:
    value = json.loads(raw)
    if not isinstance(value, list) or not value or any(not isinstance(x, str) for x in value):
        raise ValueError("CANARY_COMMAND_JSON_INVALID")
    token_positions=[index for index,part in enumerate(value) if "{state_root}" in part]
    if (len(token_positions)!=1 or value[token_positions[0]]!="{state_root}"
            or token_positions[0]==0 or value[token_positions[0]-1]!="--state-root"
            or value.count("--state-root")!=1):
        raise ValueError("CANARY_COMMAND_STATE_ROOT_BINDING_INVALID")
    forbidden_roots={"--universe-only","--universe-root","--universe-owner-root","--data-root",
        "--futu-python","--news-owner-root","--rebound-authority-root"}
    for part in value:
        option=part.split("=",1)[0]
        if option in forbidden_roots:
            raise ValueError("CANARY_EXTERNAL_OWNER_INPUT_NOT_ISOLATED:"+option)
        if any(secret in part.lower() for secret in ("password","token","secret","api-key","authorization")):
            raise ValueError("CANARY_COMMAND_CREDENTIAL_ARGUMENT_FORBIDDEN")
    executable=Path(value[0]).expanduser()
    if (not executable.is_absolute() or not executable.is_file()
            or "python" not in executable.name.lower()):
        raise ValueError("CANARY_COMMAND_MUST_USE_EXACT_PYTHON_EXECUTABLE")
    index=1
    while index<len(value) and value[index] in {"-B","-I","-s","-S","-E","-u"}:
        index+=1
    if index>=len(value):
        raise ValueError("CANARY_COMMAND_ENTRYPOINT_MISSING")
    if value[index]=="-m":
        if index+1>=len(value) or not value[index+1] or value[index+1].startswith("-"):
            raise ValueError("CANARY_COMMAND_MODULE_INVALID")
        module=value[index+1]
        if not all(part.isidentifier() for part in module.split(".")):
            raise ValueError("CANARY_COMMAND_MODULE_INVALID")
        entrypoint=app.joinpath(*module.split(".")).with_suffix(".py")
        entrypoint_name=module
        entrypoint_kind="module"
    else:
        script=Path(value[index]).expanduser()
        if (not script.is_absolute() or script.resolve()!=script or script.is_symlink()
                or script.suffix!=".py" or not script.is_file()):
            raise ValueError("CANARY_COMMAND_ENTRYPOINT_INVALID")
        entrypoint=script.resolve()
        entrypoint_name=script.name
        entrypoint_kind="script"
    expected={"announcement":"ops.run_manager_announcement_owner_canary",
        "materializer":"ops.run_manager_materializer_offline_replay"}.get(role)
    if expected is None:
        raise ValueError("CANARY_COMMAND_ROLE_INVALID")
    if role=="announcement":
        expected_path=(app/"ops/run_manager_announcement_owner_canary.py").resolve()
        if (entrypoint.resolve()!=expected_path or
                (entrypoint_kind=="module" and entrypoint_name!=expected) or
                (entrypoint_kind=="script" and entrypoint.name!="run_manager_announcement_owner_canary.py")):
            raise ValueError("CANARY_ANNOUNCEMENT_OWNER_IDENTITY_UNVERIFIED")
        if value.count("--security-master-root")!=1:
            raise ValueError("CANARY_SECURITY_MASTER_READ_ROOT_REQUIRED")
        security_index=value.index("--security-master-root")+1
        security_master=value[security_index] if security_index<len(value) and not value[security_index].startswith("-") else ""
        if not security_master or not Path(security_master).expanduser().is_absolute():
            raise ValueError("CANARY_SECURITY_MASTER_READ_ROOT_REQUIRED")
        raw_security_path=Path(security_master).expanduser()
        security_path=raw_security_path.resolve()
        if raw_security_path!=security_path:
            raise ValueError("CANARY_SECURITY_MASTER_READ_ROOT_INVALID")
        if not security_path.is_dir() or security_path==source or source in security_path.parents:
            raise ValueError("CANARY_SECURITY_MASTER_READ_ROOT_INVALID")
        for flag,placeholder in (("--sandbox-identity","{sandbox_identity}"),("--receipt","{receipt}")):
            if value.count(flag)!=1:
                raise ValueError("CANARY_COMMAND_SANDBOX_BINDING_INVALID")
            index=value.index(flag)+1
            if index>=len(value) or value[index]!=placeholder:
                raise ValueError("CANARY_COMMAND_SANDBOX_BINDING_INVALID")
    else:
        expected_path=(app/"ops/run_manager_materializer_offline_replay.py").resolve()
        if (entrypoint.resolve()!=expected_path or
                (entrypoint_kind=="module" and entrypoint_name!=expected) or
                (entrypoint_kind=="script" and entrypoint.name!="run_manager_materializer_offline_replay.py")
                or not entrypoint.is_file()):
            if ((entrypoint_kind=="module" and entrypoint_name=="ops.materialize_manager_close_discovery")
                    or (entrypoint_kind=="script" and entrypoint.name=="materialize_manager_close_discovery.py")):
                raise ValueError("CANARY_MATERIALIZER_OFFLINE_REPLAY_REQUIRED")
            raise ValueError("CANARY_MATERIALIZER_OWNER_IDENTITY_UNVERIFIED")
        for flag,placeholder in (("--sandbox-identity","{sandbox_identity}"),("--receipt","{receipt}")):
            if value.count(flag)!=1:
                raise ValueError("CANARY_COMMAND_SANDBOX_BINDING_INVALID")
            flag_index=value.index(flag)+1
            if flag_index>=len(value) or value[flag_index]!=placeholder:
                raise ValueError("CANARY_COMMAND_SANDBOX_BINDING_INVALID")
        if value.count("--replay-spec")!=1 or value.count("--replay-spec-sha256")!=1:
            raise ValueError("CANARY_MATERIALIZER_REPLAY_SPEC_REQUIRED")
        spec_index=value.index("--replay-spec")+1
        sha_index=value.index("--replay-spec-sha256")+1
        replay_spec=Path(value[spec_index]).expanduser() if spec_index<len(value) else Path()
        replay_sha=value[sha_index] if sha_index<len(value) else ""
        if (not replay_spec.is_absolute() or replay_spec.resolve()!=replay_spec or replay_spec.is_symlink()
                or not replay_spec.is_file() or not re.fullmatch(r"[0-9a-f]{64}",replay_sha)
                or hashlib.sha256(replay_spec.read_bytes()).hexdigest()!=replay_sha):
            raise ValueError("CANARY_MATERIALIZER_REPLAY_SPEC_INVALID")
    if not entrypoint.is_file() or entrypoint.resolve()!=entrypoint or entrypoint.is_symlink():
        raise ValueError("CANARY_COMMAND_ENTRYPOINT_INVALID")
    for flag in ("--trade-date",):
        if value.count(flag)!=1:
            raise ValueError("CANARY_COMMAND_DATE_BINDING_INVALID")
        date=value[value.index(flag)+1] if value.index(flag)+1<len(value) else ""
        if len(date)!=8 or not date.isdigit():
            raise ValueError("CANARY_COMMAND_DATE_BINDING_INVALID")
    for part in value:
        candidate=part.partition("=")[2] if part.startswith("-") and "=" in part else part
        if not candidate.startswith(("/","~")):
            continue
        try:
            target=Path(candidate).expanduser().resolve()
        except OSError:
            continue
        if target==source or source in target.parents:
            raise ValueError("CANARY_COMMAND_TARGETS_SOURCE_STATE")
    resolved_executable=executable.resolve()
    try:
        executable_sha=hashlib.sha256(resolved_executable.read_bytes()).hexdigest()
        entrypoint_sha=hashlib.sha256(entrypoint.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("CANARY_COMMAND_IDENTITY_UNREADABLE") from exc
    identity={"role":role,"argv_template":value,
        "argv_sha256":hashlib.sha256(_json_bytes(value)).hexdigest(),
        "executable_path":str(executable),"executable_resolved":str(resolved_executable),
        "executable_sha256":executable_sha,"entrypoint_kind":entrypoint_kind,
        "entrypoint_name":expected if role in {"announcement","materializer"} else entrypoint_name,"entrypoint_path":str(entrypoint),
        "entrypoint_sha256":entrypoint_sha}
    if role=="materializer":
        identity["replay_spec_path"]=str(replay_spec)
        identity["replay_spec_sha256"]=replay_sha
    rendered = [x.replace("{state_root}", str(root)) for x in value]
    return rendered,identity


def _env() -> dict[str, str]:
    allowed={"PATH":os.defpath,"PYTHONNOUSERSITE":"1","PYTHONDONTWRITEBYTECODE":"1",
        "PRODUCTION_ALLOWED":"false","BUY_GATE_UPDATED":"false","ORDERS_SENT":"false",
        "TMPDIR":str(Path(tempfile.gettempdir()).resolve()),
        "LANG":"C","LC_ALL":"C"}
    return allowed


def _terminate_group(proc: subprocess.Popen[str], sig: int) -> None:
    try:
        os.killpg(proc.pid,sig)
    except ProcessLookupError:
        pass


def _result(proc: subprocess.Popen[str], timeout: float) -> dict:
    try:
        out, err = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        _terminate_group(proc,signal.SIGTERM)
        try:
            out, err = proc.communicate(timeout=min(2.0, timeout))
        except subprocess.TimeoutExpired:
            _terminate_group(proc,signal.SIGKILL)
            out, err = proc.communicate()
        timed_out = True
    return {
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "stdout_tail": (out or "")[-4000:],
        "stderr_tail": (err or "")[-4000:],
    }


def _run(argv: list[str], cwd: Path, timeout: float) -> dict:
    proc = subprocess.Popen(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_env(),start_new_session=True)
    return _result(proc, timeout)


def _copy_seed(seed: Path, destination: Path) -> None:
    # A preserved symlink would let a child writer escape the per-scenario
    # tree and mutate its original target. Refuse such inputs before any
    # writer is launched; copytree also dereferences as a second line of
    # defense if a symlink appears after this check.
    if any(path.is_symlink() for path in seed.rglob("*")):
        raise ValueError("CANARY_SOURCE_STATE_SYMLINK_UNSUPPORTED")
    shutil.copytree(seed, destination, symlinks=False)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode("utf-8")


def _store_invocation_evidence(artifact_root: Path, prepared_announcement: list[dict],
                               prepared_materializer: list[dict], results: dict,
                               recovery: dict, trade_date: str, interrupted_attempt_raw: bytes) -> dict:
    from infrastructure.owned_io import SafeRoot
    result_by_id={
        "announcement":results["announcement"][0],"materializer":results["materializer"][0],
        "concurrent-announcement":results["concurrent"][0],"concurrent-materializer":results["concurrent"][1],
        "recovery-interrupted":recovery["interrupted_result"],
        "recovery-after-interrupt":recovery["announcement_result"],
        "recovery-materializer":recovery["materializer_result"],
    }
    rows=[]
    for role,prepared in (("announcement",prepared_announcement),("materializer",prepared_materializer)):
        for row in prepared:
            invocation_id=row["invocation_id"]
            identity_path=Path(row["identity_path"]);started_path=identity_path.with_name(identity_path.name+".started")
            owner_receipt=Path(row["owner_receipt_path"])
            identity_raw=SafeRoot(identity_path.parent).read_bytes(identity_path.name,max_bytes=1024*1024)
            started_raw=SafeRoot(started_path.parent).read_bytes(started_path.name,max_bytes=1024*1024)
            folder=Path("invocations")/invocation_id
            destination=artifact_root/folder;destination.mkdir(parents=True,exist_ok=False)
            identity_rel=(folder/"identity.json").as_posix();started_rel=(folder/"started.json").as_posix()
            (artifact_root/identity_rel).write_bytes(identity_raw);(artifact_root/started_rel).write_bytes(started_raw)
            item={"invocation_id":invocation_id,"role":role,"data_root":row["data_root"],
                "identity_path":row["identity_path"],"owner_receipt_path":row["owner_receipt_path"],
                "run_id":row["run_id"],"argv_sha256":row["argv_sha256"],
                "identity_file":identity_rel,"identity_sha256":hashlib.sha256(identity_raw).hexdigest(),
                "started_file":started_rel,"started_sha256":hashlib.sha256(started_raw).hexdigest(),
                "result_sha256":hashlib.sha256(json.dumps(result_by_id[invocation_id],ensure_ascii=False,
                    sort_keys=True,indent=2).encode()).hexdigest()}
            if owner_receipt.is_file() and not owner_receipt.is_symlink():
                owner_raw=SafeRoot(owner_receipt.parent).read_bytes(owner_receipt.name,max_bytes=8*1024*1024)
                owner_rel=(folder/"owner_receipt.json").as_posix()
                (artifact_root/owner_rel).write_bytes(owner_raw)
                item["owner_receipt_file"]=owner_rel
                item["owner_receipt_sha256"]=hashlib.sha256(owner_raw).hexdigest()
            elif invocation_id!="recovery-interrupted":
                raise ValueError("CANARY_CHILD_RECEIPT_MISSING:"+invocation_id)
            else:
                item["owner_receipt_file"]=None;item["owner_receipt_sha256"]=None
            if invocation_id=="recovery-interrupted":
                attempt_path=Path(row["data_root"])/"workspace_announcement_runs"/trade_date/"latest.json"
                attempt_rel=(folder/"owner_attempt.json").as_posix()
                if not interrupted_attempt_raw or attempt_path.is_symlink():
                    raise ValueError("CANARY_INTERRUPTED_OWNER_ATTEMPT_MISSING")
                (artifact_root/attempt_rel).write_bytes(interrupted_attempt_raw)
                item["owner_attempt_file"]=attempt_rel
                item["owner_attempt_sha256"]=hashlib.sha256(interrupted_attempt_raw).hexdigest()
                item["owner_attempt_source_path"]=str(attempt_path)
            else:
                item["owner_attempt_file"]=None;item["owner_attempt_sha256"]=None
                item["owner_attempt_source_path"]=None
            rows.append(item)
    if set(result_by_id)!={row["invocation_id"] for row in rows}:
        raise ValueError("CANARY_INVOCATION_EVIDENCE_SET_MISMATCH")
    return {"schema_version":"v4.manager_research.canary_invocation_evidence.v1",
        "capture_status":"COMPLETE","invocations":rows}


def _render_command(template: list[str], root: Path, *, sandbox_identity: Path | None = None,
                    receipt: Path | None = None) -> list[str]:
    replacements = {"{state_root}": str(root)}
    for placeholder, value in (("{sandbox_identity}", sandbox_identity), ("{receipt}", receipt)):
        count = sum(part.count(placeholder) for part in template)
        if count:
            if count != 1 or value is None:
                raise ValueError("CANARY_COMMAND_SANDBOX_BINDING_INVALID")
            replacements[placeholder] = str(value)
        elif value is not None:
            raise ValueError("CANARY_COMMAND_SANDBOX_BINDING_INVALID")
    rendered = [part for part in template]
    for placeholder, value in replacements.items():
        rendered = [part.replace(placeholder, value) for part in rendered]
    if any("{state_root}" in part or "{sandbox_identity}" in part or "{receipt}" in part
           for part in rendered):
        raise ValueError("CANARY_COMMAND_PLACEHOLDER_UNRESOLVED")
    return rendered


def _prepare_announcement_invocation(template: list[str], *, sandbox_root: Path,
                                     data_root: Path, app: Path, invocation_id: str) -> tuple[list[str], Path, Path, dict]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", invocation_id):
        raise ValueError("CANARY_INVOCATION_ID_INVALID")
    if data_root.parent != sandbox_root or sandbox_root.resolve() != sandbox_root:
        raise ValueError("CANARY_SANDBOX_SCENARIO_ROOT_INVALID")
    if template.count("--security-master-root") != 1:
        raise ValueError("CANARY_SECURITY_MASTER_READ_ROOT_REQUIRED")
    master_index = template.index("--security-master-root") + 1
    if master_index >= len(template) or template[master_index].startswith("-"):
        raise ValueError("CANARY_SECURITY_MASTER_READ_ROOT_REQUIRED")
    security_master = Path(template[master_index]).expanduser().resolve()
    identity_path = sandbox_root / "identities" / f"{invocation_id}.json"
    receipt_path = sandbox_root / "receipts" / f"{invocation_id}.json"
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = _render_command(template, data_root, sandbox_identity=identity_path, receipt=receipt_path)
    identity = write_canary_sandbox_identity(
        identity_path,
        "announcement",
        data_root=data_root,
        receipt_path=receipt_path,
        app_root=app,
        security_master_root=security_master,
        argv=rendered,
    )
    return rendered, identity_path, receipt_path, identity


def _prepare_materializer_invocation(template: list[str], *, sandbox_root: Path,
                                     data_root: Path, app: Path, invocation_id: str) -> tuple[list[str], Path, Path, dict]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", invocation_id):
        raise ValueError("CANARY_INVOCATION_ID_INVALID")
    if data_root.parent != sandbox_root or sandbox_root.resolve() != sandbox_root:
        raise ValueError("CANARY_SANDBOX_SCENARIO_ROOT_INVALID")
    identity_path = sandbox_root / "identities" / f"{invocation_id}.json"
    receipt_path = sandbox_root / "receipts" / f"{invocation_id}.json"
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = _render_command(template, data_root, sandbox_identity=identity_path, receipt=receipt_path)
    identity = write_canary_sandbox_identity(
        identity_path, "materializer", data_root=data_root, receipt_path=receipt_path,
        app_root=app, argv=rendered,
    )
    return rendered, identity_path, receipt_path, identity


def _announcement_recovery_witness(root: Path, date: str, prior: dict | None) -> dict:
    from v4.manager_research.workspace import validate_attempt
    path = root / "workspace_announcement_runs" / date / "latest.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("CANARY_ANNOUNCEMENT_RECOVERY_ATTEMPT_MISSING")
    try:
        current = validate_attempt(json.loads(path.read_bytes()), date)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("CANARY_ANNOUNCEMENT_RECOVERY_ATTEMPT_INVALID") from exc
    row = {"run_id": current["run_id"], "state": current["state"],
           "execution_kind": current["execution_kind"], "started_at": current["started_at"]}
    if prior is None:
        if current["state"] != "RUNNING":
            raise ValueError("CANARY_ANNOUNCEMENT_INTERRUPTED_ATTEMPT_NOT_RUNNING")
        return {"schema_version":"v4.manager_research.announcement_recovery_witness.v1",
                "target_trade_date":date,"interrupted":row}
    interrupted = prior.get("interrupted") if isinstance(prior, dict) else None
    if not isinstance(interrupted, dict) or interrupted.get("state") != "RUNNING":
        raise ValueError("CANARY_ANNOUNCEMENT_RECOVERY_WITNESS_INVALID")
    if current["state"] != "PARTIAL" or current["run_id"] == interrupted.get("run_id"):
        raise ValueError("CANARY_ANNOUNCEMENT_RECOVERY_ATTEMPT_NOT_PARTIAL_NEW_RUN")
    return {"schema_version":"v4.manager_research.announcement_recovery_witness.v1",
            "target_trade_date":date,"interrupted":interrupted,"recovered":row}


def _inside(path: Path, root: Path) -> bool:
    return path==root or root in path.parents


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-state-root", required=True)
    parser.add_argument("--seed-origin-receipt")
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--announcement-command-json", required=True)
    parser.add_argument("--materializer-command-json", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--interrupt-after-seconds", type=float, default=5.0)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0 or not 0 < args.interrupt_after_seconds < args.timeout_seconds:
        raise ValueError("CANARY_TIMEOUT_CONFIGURATION_INVALID")

    replay_seed_root = Path(args.source_state_root).expanduser()
    app = Path(args.app_root).expanduser().resolve()
    receipt = Path(args.receipt).expanduser().resolve()
    if (not replay_seed_root.is_absolute() or replay_seed_root.resolve()!=replay_seed_root
            or replay_seed_root.is_symlink() or not replay_seed_root.is_dir() or not app.is_dir()):
        raise ValueError("CANARY_SOURCE_OR_APP_ROOT_MISSING")
    if replay_seed_root==app or replay_seed_root in app.parents or app in replay_seed_root.parents:
        raise ValueError("CANARY_SOURCE_AND_APP_ROOTS_OVERLAP")
    canary_tool=Path(__file__).resolve()
    expected_canary_tool=app/"ops/run_manager_state_compatibility_canary.py"
    if (canary_tool!=expected_canary_tool or not canary_tool.is_file() or canary_tool.is_symlink()):
        raise ValueError("CANARY_TOOL_IDENTITY_MISMATCH")
    canary_tool_sha256=hashlib.sha256(canary_tool.read_bytes()).hexdigest()
    artifact_root=Path(str(receipt)+".evidence").resolve()
    if any(_inside(path,root) for path in (receipt,artifact_root) for root in (replay_seed_root,app)):
        raise ValueError("CANARY_RECEIPT_MUST_BE_OUTSIDE_SOURCE_AND_APP_ROOT")
    if receipt.exists() or artifact_root.exists():
        raise ValueError("CANARY_OUTPUT_ALREADY_EXISTS")

    # Validate both command identities before copying source data or starting a
    # process. The production 15:30 CLI is only exercised through its pinned
    # offline replay wrapper; direct owner commands are rejected by _command.
    command_probe=Path(tempfile.gettempdir())/"manager-canary-state-root-probe"
    _,announcement_identity=_command(args.announcement_command_json,command_probe,replay_seed_root,app,"announcement")
    _,materializer_identity=_command(args.materializer_command_json,command_probe,replay_seed_root,app,"materializer")
    announcement_date=announcement_identity["argv_template"][announcement_identity["argv_template"].index("--trade-date")+1]
    materializer_date=materializer_identity["argv_template"][materializer_identity["argv_template"].index("--trade-date")+1]
    if announcement_date!=materializer_date:
        raise ValueError("CANARY_COMMAND_SESSION_MISMATCH")
    if not args.seed_origin_receipt:
        raise ValueError("CANARY_SEED_ORIGIN_RECEIPT_REQUIRED")
    from v4.manager_research.materializer_replay import (
        _origin_input_manifest,
        validate_replay_origin_bundle,
    )
    origin = validate_replay_origin_bundle(
        args.seed_origin_receipt,
        expected_seed_root=replay_seed_root,
        expected_trade_date=announcement_date,
        expected_replay_spec_path=materializer_identity["replay_spec_path"],
        expected_replay_spec_sha256=materializer_identity["replay_spec_sha256"],
    )
    source=Path(origin["source_state_root"])
    if (source==app or source in app.parents or app in source.parents
            or source==replay_seed_root or source in replay_seed_root.parents
            or replay_seed_root in source.parents):
        raise ValueError("CANARY_SOURCE_AND_APP_ROOTS_OVERLAP")
    bundle_path=Path(origin["bundle_receipt_path"])
    if any(_inside(path,root) for path in (receipt,artifact_root,bundle_path)
            for root in (source,replay_seed_root,app)):
        raise ValueError("CANARY_RECEIPT_MUST_BE_OUTSIDE_SOURCE_AND_APP_ROOT")
    # Repeat path-target checks against the true manager root as well as the
    # replay seed; neither child command may address either source tree.
    _,announcement_identity=_command(args.announcement_command_json,command_probe,source,app,"announcement")
    _,materializer_identity=_command(args.materializer_command_json,command_probe,source,app,"materializer")
    command_identity={"announcement":announcement_identity,"materializer":materializer_identity}

    announcement_template=json.loads(args.announcement_command_json)
    materializer_template=json.loads(args.materializer_command_json)
    prepared_announcement_invocations: list[dict] = []
    prepared_materializer_invocations: list[dict] = []

    from infrastructure.scheduling.manager_announcement_supervisor import binding_inventory
    app_inventory_before=binding_inventory(app)

    source_before = origin["origin_inputs_before"]
    seed_before = origin["seed_manifest_before"]
    with tempfile.TemporaryDirectory(prefix="manager-state-canary-") as td:
        base = Path(td).resolve()
        base_sandbox_root = base

        def prepare_announcement(root: Path, invocation_id: str) -> list[str]:
            rendered, identity_path, owner_receipt_path, identity = _prepare_announcement_invocation(
                announcement_template,
                sandbox_root=base_sandbox_root,
                data_root=root,
                app=app,
                invocation_id=invocation_id,
            )
            prepared_announcement_invocations.append({
                "invocation_id": invocation_id,
                "data_root": str(root),
                "identity_path": str(identity_path),
                "owner_receipt_path": str(owner_receipt_path),
                "run_id": identity["run_id"],
                "argv_sha256": identity["argv_sha256"],
            })
            return rendered

        def prepare_materializer(root: Path, invocation_id: str) -> list[str]:
            rendered, identity_path, owner_receipt_path, identity = _prepare_materializer_invocation(
                materializer_template, sandbox_root=base_sandbox_root, data_root=root, app=app,
                invocation_id=invocation_id)
            prepared_materializer_invocations.append({
                "invocation_id": invocation_id, "data_root": str(root),
                "identity_path": str(identity_path), "owner_receipt_path": str(owner_receipt_path),
                "run_id": identity["run_id"], "argv_sha256": identity["argv_sha256"],
            })
            return rendered

        seed = base / "seed"
        _copy_seed(replay_seed_root, seed)
        source_after_seed = _origin_input_manifest(source,announcement_date)
        seed_manifest = manifest(seed)
        if source_before != source_after_seed or seed_manifest != seed_before:
            raise RuntimeError("CANARY_LIVE_SOURCE_CHANGED_DURING_SEED")

        results: dict[str, list[dict]] = {}
        writes: dict[str, list[str]] = {}
        scenario_manifests: dict[str, dict] = {}
        for name in ("announcement", "materializer", "concurrent"):
            root = base / name
            _copy_seed(seed, root)
            before = manifest(root)
            ann_result=[];mat_result=[]
            if name == "announcement":
                ann = prepare_announcement(root, "announcement")
                ann_result=[_run(ann, app, args.timeout_seconds)]
            elif name == "materializer":
                mat = prepare_materializer(root, "materializer")
                mat_result=[_run(mat, app, args.timeout_seconds)]
            else:
                ann = prepare_announcement(root, "concurrent-announcement")
                mat = prepare_materializer(root, "concurrent-materializer")
                p1 = subprocess.Popen(ann, cwd=app, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env(),start_new_session=True)
                p2 = subprocess.Popen(mat, cwd=app, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env(),start_new_session=True)
                ann_result=[_result(p1, args.timeout_seconds)]
                mat_result=[_result(p2, args.timeout_seconds)]
            results[name]=ann_result+mat_result
            after=manifest(root)
            writes[name] = sorted(changed(before, after))
            scenario_manifests[name]={"before":before,"after":after}

        decision = evaluate_writer_namespaces(
            announcement_paths=writes["announcement"],
            materializer_paths=writes["materializer"],
            concurrent_paths=writes["concurrent"],
        )
        if any(item["returncode"] != 0 or item["timed_out"] for group in results.values() for item in group):
            decision["status"] = "STOP"
            decision.setdefault("gaps", []).append("CANARY_COMMAND_FAILED_OR_TIMED_OUT")

        recovery_root = base / "recovery"
        _copy_seed(seed, recovery_root)
        recovery_before = manifest(recovery_root)
        ann_interrupted = prepare_announcement(recovery_root, "recovery-interrupted")
        interrupted = subprocess.Popen(
            ann_interrupted, cwd=app, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env(),start_new_session=True
        )
        wait_deadline=time.monotonic()+args.interrupt_after_seconds
        pre_interrupt_change_observed=False
        pre_interrupt_manifest=recovery_before
        while time.monotonic() < wait_deadline and interrupted.poll() is None:
            current=manifest(recovery_root)
            if changed(recovery_before,current):
                pre_interrupt_change_observed=True
                pre_interrupt_manifest=current
                break
            time.sleep(0.01)
        interruption_observed = interrupted.poll() is None
        if interruption_observed:
            _terminate_group(interrupted,signal.SIGTERM)
        interrupted_result = _result(interrupted, min(2.0, args.timeout_seconds))
        interrupted_witness = _announcement_recovery_witness(recovery_root, announcement_date, None)
        interrupted_attempt_path=recovery_root/"workspace_announcement_runs"/announcement_date/"latest.json"
        if interrupted_attempt_path.is_symlink() or not interrupted_attempt_path.is_file():
            raise ValueError("CANARY_INTERRUPTED_OWNER_ATTEMPT_MISSING")
        interrupted_attempt_raw=interrupted_attempt_path.read_bytes()
        ann_recovery = prepare_announcement(recovery_root, "recovery-after-interrupt")
        mat_recovery = prepare_materializer(recovery_root, "recovery-materializer")
        recovery_announcement = _run(ann_recovery, app, args.timeout_seconds)
        recovery_materializer = _run(mat_recovery, app, args.timeout_seconds)
        recovery_witness = _announcement_recovery_witness(recovery_root, announcement_date, interrupted_witness)
        recovery_paths = sorted(changed(recovery_before, manifest(recovery_root)))
        recovery_after=manifest(recovery_root)
        recovery_decision = evaluate_recovery(
            interruption_observed=interruption_observed,
            announcement_returncode=recovery_announcement["returncode"],
            materializer_returncode=recovery_materializer["returncode"],
            recovery_paths=recovery_paths,
            allowed_paths=set(writes["announcement"]) | set(writes["materializer"]),
            pre_interrupt_change_observed=pre_interrupt_change_observed,
            owner_transaction_state=recovery_witness,
        )
        if recovery_announcement["timed_out"] or recovery_materializer["timed_out"]:
            recovery_decision["status"] = "STOP"
            recovery_decision.setdefault("gaps", []).append("RECOVERY_COMMAND_TIMED_OUT")

        try:
            source_final=_origin_input_manifest(source,announcement_date)
        except (OSError,ValueError,TypeError):
            source_final={"__origin_input_error__":"UNAVAILABLE_OR_UNSAFE"}
        try:
            seed_final=manifest(replay_seed_root,symlink_error="CANARY_SOURCE_STATE_SYMLINK_UNSUPPORTED")
        except (OSError,ValueError,TypeError):
            seed_final={"__seed_input_error__":"UNAVAILABLE_OR_UNSAFE"}
        source_unchanged=(source_final==source_before==origin["copied_inputs"]
            and seed_manifest==seed_before==seed_final==origin["copied_inputs"])
        app_inventory_after=binding_inventory(app)
        try:
            command_sources_unchanged=all(
                hashlib.sha256(Path(value["entrypoint_path"]).read_bytes()).hexdigest()==value["entrypoint_sha256"]
                for value in command_identity.values())
            canary_tool_unchanged=(hashlib.sha256(canary_tool.read_bytes()).hexdigest()==canary_tool_sha256)
        except OSError:
            command_sources_unchanged=False
            canary_tool_unchanged=False
        app_unchanged=app_inventory_after==app_inventory_before and command_sources_unchanged and canary_tool_unchanged
        seed_sha = manifest_sha(seed_manifest)
        scenario_manifests["recovery"]={"before":recovery_before,"pre_interrupt":pre_interrupt_manifest,"after":recovery_after}
        origin_evidence={**origin,
            "origin_inputs_before":source_before,"origin_inputs_after":source_final,
            "seed_manifest_before":seed_before,"seed_manifest_after":seed_final}
        artifacts={
            "seed_manifest.json":seed_manifest,
            "source_manifests.json":{"before":source_before,"after":source_final},
            "seed_origin.json":origin_evidence,
            "app_inventory.json":{"before":app_inventory_before,"after":app_inventory_after},
            "command_identity.json":command_identity,
            "announcement.json":scenario_manifests["announcement"],
            "materializer.json":scenario_manifests["materializer"],
            "concurrent.json":scenario_manifests["concurrent"],
            "recovery.json":scenario_manifests["recovery"],
            "announcement_recovery_witness.json":recovery_witness,
        }
        artifact_root.mkdir(parents=True,exist_ok=False)
        invocation_recovery={"interruption_observed":interruption_observed,
            "pre_interrupt_change_observed":pre_interrupt_change_observed,
            "interrupted_result":interrupted_result,"announcement_result":recovery_announcement,
            "materializer_result":recovery_materializer}
        try:
            invocation_evidence=_store_invocation_evidence(artifact_root,prepared_announcement_invocations,
                prepared_materializer_invocations,results,invocation_recovery,announcement_date,interrupted_attempt_raw)
        except (OSError,ValueError,TypeError,KeyError,IndexError) as exc:
            shutil.rmtree(artifact_root/"invocations",ignore_errors=True)
            decision["status"]="STOP"
            decision.setdefault("gaps",[]).append("CANARY_INVOCATION_EVIDENCE_CAPTURE_FAILED")
            invocation_evidence={"schema_version":"v4.manager_research.canary_invocation_evidence.v1",
                "capture_status":"FAILED","failure":"CANARY_INVOCATION_EVIDENCE_CAPTURE_FAILED",
                "detail":type(exc).__name__,"invocations":[]}
        artifacts["invocation_evidence.json"]=invocation_evidence
        artifact_sha={}
        for name,value in artifacts.items():
            raw=_json_bytes(value)
            (artifact_root/name).write_bytes(raw)
            artifact_sha[name]=hashlib.sha256(raw).hexdigest()
        final = {
            "schema_version": "v4.manager_research.shared_root_canary.v7",
            "decision": decision,
            "writes": writes,
            "results": results,
            "recovery": {
                "interruption_observed": interruption_observed,
                "pre_interrupt_change_observed": pre_interrupt_change_observed,
                "owner_transaction_state": recovery_witness,
                "interrupted_result": interrupted_result,
                "announcement_result": recovery_announcement,
                "materializer_result": recovery_materializer,
                "pre_interrupt_changed_paths": sorted(changed(recovery_before,pre_interrupt_manifest)),
                "writes": recovery_paths,
                "decision": recovery_decision,
            },
            "seed_manifest_sha256": seed_sha,
            "source_manifest_before_sha256": manifest_sha(source_before),
            "source_manifest_after_sha256": manifest_sha(source_final),
            "source_unchanged": source_unchanged,
            "source_state_root":str(source),
            "replay_seed_root":str(replay_seed_root),
            "seed_origin_receipt_path":origin["bundle_receipt_path"],
            "seed_origin_receipt_sha256":origin["bundle_receipt_sha256"],
            "app_root":str(app),
            "canary_tool_sha256":canary_tool_sha256,
            "app_inventory_sha256_before":manifest_sha(app_inventory_before),
            "app_inventory_sha256_after":manifest_sha(app_inventory_after),
            "app_unchanged":app_unchanged,
            "scenario_evidence_root":str(artifact_root),
            "scenario_artifacts_sha256":artifact_sha,
            "command_identity":command_identity,
            "prepared_announcement_invocations":prepared_announcement_invocations,
            "prepared_materializer_invocations":prepared_materializer_invocations,
            "materializer_mode":"OFFLINE_EXACT_INPUT_REPLAY",
            "environment_policy":"SANITIZED_V2",
            "environment_keys":sorted(_env()),
            "environment_values":_env(),
            "simulated": False,
            "natural_run_verified": False,
            "activation_scope":"WRITER_COMPATIBILITY_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if not source_unchanged:
            final["decision"]["status"] = "STOP"
            final["decision"].setdefault("gaps", []).append("CANARY_SOURCE_MUTATED")
        if not app_unchanged:
            final["decision"]["status"] = "STOP"
            final["decision"].setdefault("gaps", []).append("CANARY_APP_OR_COMMAND_SOURCE_MUTATED")
        if recovery_decision["status"] != "PASS":
            final["decision"]["status"] = "STOP"
            final["decision"].setdefault("gaps", []).append("RECOVERY_GATE_FAILED")
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_bytes(_json_bytes(final))
        print(json.dumps(final, ensure_ascii=False, sort_keys=True))
        return 0 if final["decision"]["status"] == "PASS" and source_unchanged and app_unchanged else 2


if __name__ == "__main__":
    raise SystemExit(main())
