"""Fail-closed lifecycle of the existing A-share producer's derived artifacts.

No collectors, formula changes, permanent deletion, or independent scheduling.
An explicit policy supplies consumer pins and byte budgets; absent policy is off.
Only READY runs can supply move candidates. Unknown dependencies remain in place.
"""
from __future__ import annotations

import argparse
import ast
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import uuid
from typing import Any

SCHEMA = "v4_research_storage_retention_v1"
ROLES = {"selector", "backtest"}
RUN = re.compile(r"qfq_[0-9a-f]{20}")
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
CHECKPOINT_IDENTITY_KEYS = ("input_sha256", "driver_sha256", "formula_sha256", "adapter_sha256",
    "input_adapter_sha256", "factor_cache_sha256", "tdx_adapter_sha256", "field_contract_sha256",
    "user_formula_sha256", "turnover_input_sha256")
CERTIFIED_QFQ_OWNER = "05e8aa7aa19c1ae998481360d80fb99a39498ffd31c5945caedd5c791daa1fad"
CONSUMER_SCOPES = {"api", "main", "stage", "typed_end", "history_recovery", "model_frozen"}


class RetentionError(RuntimeError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def safe_path(value: str | Path, *, exists: bool = True) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise RetentionError(f"UNSAFE_PATH:{path}")
    for item in [path, *path.parents]:
        if item.is_symlink():
            raise RetentionError(f"SYMLINK_PATH:{item}")
    if exists and not path.exists():
        raise RetentionError(f"MISSING_PATH:{path}")
    return path


def under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def overlap(left: Path, right: Path) -> bool:
    return under(left, right) or under(right, left)


def stamp(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RetentionError(f"NONREGULAR_OR_ALIAS:{path}")
    return dict(device=info.st_dev, inode=info.st_ino, size=info.st_size,
                mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)


def read_json(path: Path, *, max_bytes: int = 192 * 1024**2) -> Any:
    safe_path(path)
    before = stamp(path)
    if before["size"] > max_bytes:
        raise RetentionError(f"METADATA_BUDGET:{path}")
    value = json.loads(path.read_bytes())
    if stamp(path) != before:
        raise RetentionError(f"METADATA_CHANGED:{path}")
    return value


def files(path: Path):
    safe_path(path)
    if path.is_file():
        stamp(path)
        yield path
        return
    if not path.is_dir():
        raise RetentionError(f"NONREGULAR:{path}")
    for base, dirs, names in os.walk(path, followlinks=False):
        for name in dirs:
            safe_path(Path(base) / name)
        for name in sorted(names):
            item = Path(base) / name
            safe_path(item)
            stamp(item)
            yield item


def logical_bytes(path: Path) -> int:
    return sum(stamp(item)["size"] for item in files(path))


def quarantine_state(policy: dict, *, measure: bool = True) -> dict:
    """Known-absent legacy Desktop destination is valid only for no-delete mode.

    Never recreate a user-deleted directory. Permission errors, wrong types and
    path escapes are errors, not measured zeroes. Validate an existing ancestor.
    """
    path = safe_path(policy["quarantine_root"], exists=False)
    try:
        info = path.stat()
    except FileNotFoundError:
        if not policy.get("dry_run", True) or policy.get("auto_gc_enabled", False):
            raise RetentionError("MISSING_QUARANTINE_OUTSIDE_NONDELETING_DRYRUN")
        ancestor = path.parent
        while True:
            try:
                info = ancestor.stat()
                break
            except FileNotFoundError:
                if ancestor == ancestor.parent:
                    raise RetentionError("QUARANTINE_EXISTING_ANCESTOR_UNKNOWN")
                ancestor = ancestor.parent
        if not stat.S_ISDIR(info.st_mode) or info.st_dev != Path(policy["data_root"]).stat().st_dev:
            raise RetentionError("QUARANTINE_ANCESTOR_TYPE_OR_POOL")
        return dict(status="KNOWN_ABSENT_NONDELETING_DRYRUN", bytes=0, path=str(path), ancestor=str(ancestor))
    if not stat.S_ISDIR(info.st_mode):
        raise RetentionError("QUARANTINE_NOT_DIRECTORY")
    return dict(status="EXISTS", bytes=logical_bytes(path) if measure else None, path=str(path))


def load_policy(path: Path, *, data_root: Path | None = None,
                run_root: Path | None = None, pointers: dict | None = None,
                expected_sha256: str | None = None) -> dict:
    if expected_sha256 is not None and digest(safe_path(path)) != expected_sha256:
        raise RetentionError("POLICY_HASH_BINDING_FAILED")
    policy = read_json(path)
    if policy.get("schema") != SCHEMA or policy.get("keep_completed") != 2:
        raise RetentionError("POLICY_SCHEMA_OR_KEEP_COMPLETED")
    for key in ("data_root", "run_root"):
        safe_path(policy[key])
    quarantine_state(policy, measure=False)
    for key in ("pointers", "formal_roots"):
        if set(policy[key]) != ROLES:
            raise RetentionError(f"POLICY_ROLES:{key}")
        for value in policy[key].values():
            safe_path(value)
    data, runs, quarantine = (Path(policy[key]) for key in ("data_root", "run_root", "quarantine_root"))
    if quarantine.parent.name != "待删除文件夹" or quarantine.parent.parent.name != "Desktop":
        raise RetentionError("QUARANTINE_MUST_BE_DEDICATED_DESKTOP_CHILD")
    if (overlap(data, runs) or overlap(quarantine, data) or overlap(quarantine, runs)
            or any(not under(Path(value), data) for value in policy["formal_roots"].values())):
        raise RetentionError("POLICY_ROOT_OVERLAP")
    for expected, actual, label in ((data_root, data, "data_root"), (run_root, runs, "run_root")):
        if expected is not None and Path(expected) != actual:
            raise RetentionError(f"POLICY_OWNER_MISMATCH:{label}")
    if pointers is not None and {key: str(value) for key, value in pointers.items()} != policy["pointers"]:
        raise RetentionError("POLICY_OWNER_MISMATCH:pointers")
    for key in ("max_managed_bytes", "max_quarantine_bytes", "reserve_bytes", "minimum_build_bytes"):
        if type(policy.get(key)) is not int or policy[key] <= 0:
            raise RetentionError(f"POLICY_BYTE_BUDGET:{key}")
    # Pins must describe the reviewed active consumer inventory, not an inferred
    # search result. An empty inventory cannot authorize reclamation.
    if not policy.get("managed_pin_inventory"):
        raise RetentionError("CONSUMER_INVENTORY_REQUIRED")
    ref = policy["managed_pin_inventory"]
    if not re.fullmatch("[0-9a-f]{64}", ref.get("sha256", "")):
        raise RetentionError("PIN_SHA_REQUIRED")
    safe_path(ref["path"])
    for mapping in policy.get("formal_relocations", []):
        original = safe_path(mapping["original_path"], exists=False)
        archived = safe_path(mapping["archived_path"], exists=False)
        if (original.exists() or not under(archived, data)
                or archived.name != original.name
                or not any(under(original, Path(root)) for root in policy["formal_roots"].values())
                or any(under(archived, Path(root)) for root in policy["formal_roots"].values())):
            raise RetentionError("RELOCATION_SCOPE_CONFLICT")
        proof = mapping["manifest"]
        if digest(safe_path(proof["path"])) != proof["sha256"]:
            raise RetentionError("RELOCATION_MANIFEST_CHANGED")
    if policy.get("future_reclamation"):
        ref = policy["activation"]
        activation = read_json(safe_path(ref["path"]))
        if (digest(Path(ref["path"])) != ref["sha256"]
                or activation.get("schema") != "v4_research_storage_activation_v1"
                or activation.get("activation_id") != policy.get("activation_id")
                or activation.get("authority") != "FUTURE_CREATED_SUCCESSFUL_UNPINNED_DERIVED_ONLY"):
            raise RetentionError("FUTURE_RECLAMATION_AUTHORITY_UNBOUND")
    return policy


@contextmanager
def owner_lock(policy: dict, *, publication: bool = False):
    root = Path(policy["data_root"]) / "runtime/cache/data_layer_daily_formula_increment_update_v1"
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("qfq_publish.lock" if publication else "qfq_retention.lock")
    safe_path(path, exists=False)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RetentionError("OWNER_ALREADY_ACTIVE") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def pointer_state(policy: dict) -> dict:
    result = {}
    for role, value in policy["pointers"].items():
        path = safe_path(value)
        target = safe_path(path.read_text(encoding="utf-8-sig").strip())
        if not under(target, Path(policy["formal_roots"][role])):
            raise RetentionError("POINTER_OUTSIDE_FORMAL_ROOT")
        result[role] = dict(path=str(path), text=path.read_text(encoding="utf-8-sig"),
                            target=str(target), target_stat=stamp(target))
    return result






def inventory(policy: dict) -> tuple[list[dict], list[dict], dict]:
    ready, unknown, watched = [], [], {}
    for run in sorted(Path(policy["run_root"]).iterdir()):
        if not RUN.fullmatch(run.name):
            continue
        try:
            safe_path(run)
            status_path = run / "stage_status.json"
            status = read_json(status_path)
            watched[str(status_path)] = dict(sha256=digest(status_path), stat=stamp(status_path))
            if status.get("status") != "READY" or any(run.glob("*.lock")):
                unknown.append(dict(path=str(run), reason="UNFINISHED_OR_LOCKED"))
                continue
            receipt_path = run / "candidate_receipt.json"
            receipt = read_json(receipt_path)
            watched[str(receipt_path)] = dict(sha256=digest(receipt_path), stat=stamp(receipt_path))
            if (receipt.get("generation_id") != status.get("generation_id")
                    or status.get("run_dir") != str(run)
                    or receipt.get("candidates") != status.get("candidates")
                    or receipt.get("candidate_sha256") != status.get("candidate_sha256")
                    or set(status.get("candidates", {})) != ROLES
                    or set(status.get("candidate_sha256", {})) != ROLES
                    or status.get("selector_pointer_ready") is not True
                    or status.get("backtest_pointer_ready") is not True
                    or any(status.get(key) != expected for key, expected in FLAGS.items())):
                raise RetentionError("READY_RECEIPT_CONFLICT")
            for role, value in status["candidates"].items():
                path = safe_path(value, exists=False)
                if not under(path, Path(policy["formal_roots"][role])):
                    raise RetentionError("FORMAL_PATH_ESCAPE")
            ready.append(dict(run=run, status=status, receipt=receipt))
        except (OSError, ValueError, TypeError, KeyError, RetentionError) as exc:
            unknown.append(dict(path=str(run), reason=str(exc)))
    return ready, unknown, watched


def _ownership_root(policy: dict) -> Path:
    return Path(policy["run_root"]) / "storage_retention_ownership"


def begin_creation(policy: dict) -> Path | None:
    """Persist absence evidence BEFORE the existing producer creates anything.

    A failed reservation is never a successful ownership claim. Grandfathered
    directories, even if renamed/reused or given a newer mtime, cannot qualify.
    """
    if not policy.get("future_reclamation"):
        return None
    owned = _ownership_root(policy)
    if owned.exists() and logical_bytes(owned) >= 64 * 1024**2:
        raise RetentionError("OWNERSHIP_EVIDENCE_BUDGET_NO_DELETION")
    roots = [policy["run_root"], *policy["formal_roots"].values()]
    existing = {root: sorted(item.name for item in safe_path(root).iterdir()) for root in roots}
    path = _ownership_root(policy) / "reservations" / (uuid.uuid4().hex + ".json")
    atomic_json(path, dict(schema="v4_research_storage_creation_reservation_v1",
        policy_sha256=canonical(policy), activation=policy["activation"], existing=existing,
        pointers=pointer_state(policy), **FLAGS))
    return path


def reconstruction_runtime() -> dict:
    return dict(python=sys.version, executable=sys.executable,
                packages={name: importlib.metadata.version(name) for name in ("numpy", "pandas", "pyarrow")})


def _reconstruction_descriptor(status: dict, kwargs: dict) -> dict:
    identity = {key: status[key] for key in CHECKPOINT_IDENTITY_KEYS}
    owner = Path(__file__).with_name("research_panel_qfq.py")
    refs = {
        "driver_sha256": Path(kwargs["driver_path"]), "formula_sha256": Path(kwargs["formula_path"]),
        "field_contract_sha256": Path(kwargs["contract_csv"]), "adapter_sha256": owner,
        "input_adapter_sha256": owner.with_name("research_panel_adjustment_inputs.py"),
        "factor_cache_sha256": owner.with_name("research_panel_factor_cache.py"),
        "tdx_adapter_sha256": owner.with_name("research_panel_tdx_adjustment_inputs.py"),
    }
    if identity["adapter_sha256"] != CERTIFIED_QFQ_OWNER:
        raise RetentionError("RECONSTRUCTION_OWNER_SEMANTICS_UNKNOWN")
    for key, path in refs.items():
        _checked_file(path, identity[key])
    return dict(schema="v4_qfq_checkpoint_reconstruction_inputs_v1", identity=identity,
        snapshot=status["adjustment_snapshot"],
        code_refs={key: dict(path=str(path), sha256=identity[key]) for key, path in refs.items()},
        runtime=reconstruction_runtime())


def register_creation(policy: dict, reservation_path: Path | None, result: dict,
                      rebuild_kwargs: dict | None = None) -> None:
    if reservation_path is None or result.get("status") != "READY" or result.get("already_current"):
        return
    reservation = read_json(reservation_path)
    if reservation["policy_sha256"] != canonical(policy):
        raise RetentionError("CREATION_POLICY_CHANGED")
    run = safe_path(result["run_dir"])
    status_path = run / "stage_status.json"
    status = read_json(status_path)
    if (run.parent != Path(policy["run_root"]) or not RUN.fullmatch(run.name)
            or run.name in reservation["existing"][policy["run_root"]]
            or status.get("status") != "READY"
            or status.get("generation_id") != result.get("generation_id")
            or set(status.get("candidates", {}).values()) != {item["target"] for item in pointer_state(policy).values()}):
        raise RetentionError("CREATION_RUN_NOT_PROVEN_NEW_AND_COMMITTED")
    owned = []
    for name in ("symbol_checkpoints", "current_selector_buckets", "current_backtest_buckets"):
        path = run / name
        if path.exists():
            safe_path(path)
            owned.append(str(path))
    for role, value in status["candidates"].items():
        path = safe_path(value)
        root = path.parent if role == "selector" else path.parent.parent
        if (root.parent != Path(policy["formal_roots"][role])
                or root.name in reservation["existing"][policy["formal_roots"][role]]):
            raise RetentionError("CREATION_FORMAL_NOT_PROVEN_NEW")
        owned.append(str(root))
    claims = _ownership_root(policy) / "completed"
    claim = claims / (run.name + ".json")
    if claim.exists():
        raise RetentionError("CREATION_CLAIM_ALREADY_EXISTS")
    try:
        reconstruction = _reconstruction_descriptor(status, rebuild_kwargs or {})
    except (KeyError, ValueError, OSError, TypeError, RetentionError) as exc:
        reconstruction = dict(status="UNKNOWN", reason=str(exc))
    atomic_json(claim, dict(schema="v4_research_storage_future_ownership_v1",
        reservation=dict(path=str(reservation_path), sha256=digest(reservation_path)),
        policy_sha256=canonical(policy), activation=policy["activation"], run=str(run),
        generation_id=status["generation_id"], owned=owned,
        checkpoint_reconstruction=reconstruction,
        candidate_sha256=status["candidate_sha256"],
        directories={path: dict(device=Path(path).stat().st_dev, inode=Path(path).stat().st_ino) for path in owned},
        **FLAGS))


def future_owned(policy: dict, action: dict, status: dict) -> tuple[bool, dict]:
    if not policy.get("future_reclamation"):
        return False, {}
    run = Path(action["run"])
    claim = _ownership_root(policy) / "completed" / (run.name + ".json")
    if not claim.is_file():
        return False, {}
    value = read_json(claim)
    reservation_path = safe_path(value["reservation"]["path"])
    reservation = read_json(reservation_path)
    source = Path(action["source"])
    expected = value.get("directories", {}).get(str(source))
    if (value.get("schema") != "v4_research_storage_future_ownership_v1"
            or value.get("policy_sha256") != canonical(policy)
            or value.get("activation") != policy["activation"]
            or value.get("generation_id") != status["generation_id"]
            or value.get("candidate_sha256") != status["candidate_sha256"]
            or digest(reservation_path) != value["reservation"]["sha256"]
            or reservation.get("policy_sha256") != canonical(policy)
            or run.name in reservation["existing"][policy["run_root"]]
            or str(source) not in value.get("owned", []) or not expected
            or source.stat().st_dev != expected["device"] or source.stat().st_ino != expected["inode"]):
        raise RetentionError("FUTURE_OWNERSHIP_NOT_PROVEN")
    return True, {str(claim): dict(sha256=digest(claim), stat=stamp(claim)),
                  str(reservation_path): dict(sha256=digest(reservation_path), stat=stamp(reservation_path))}


def _checked_file(path: Path, expected: str, verified: dict | None = None) -> dict:
    before = stamp(safe_path(path))
    cached = (verified or {}).get(str(path), {})
    actual = cached.get("sha256") if cached.get("stat") == before else None
    if not isinstance(actual, str) or not re.fullmatch("[0-9a-f]{64}", actual):
        actual = digest(path)
    if verified is not None:
        verified[str(path)] = dict(sha256=actual, stat=before)
    if actual != expected or stamp(path) != before:
        raise RetentionError(f"SOURCE_HASH_DRIFT:{path}")
    return dict(path=str(path), sha256=actual, stat=before)


def _tree_record(root: Path, expected: dict[str, str] | None = None, *, verified: dict | None = None) -> dict:
    records = []
    for path in files(root):
        if path.name.endswith((".pending", ".lock")):
            raise RetentionError(f"PENDING_OR_LOCKED:{path}")
        if expected is not None and str(path) not in expected:
            raise RetentionError(f"UNRECEIPTED_FILE:{path}")
        records.append(_checked_file(path, expected[str(path)], verified) if expected is not None
                       else _checked_file(path, digest(path)))
    if not records or expected is not None and {item["path"] for item in records} != set(expected):
        raise RetentionError(f"INCOMPLETE_ARTIFACT:{root}")
    return dict(source=str(root), files=records, bytes=sum(item["stat"]["size"] for item in records))


def checkpoint_reconstruction_certificate(policy: dict, action: dict, status: dict,
                                          verified: dict) -> tuple[dict, dict]:
    """Verify the pure checkpoint's original machine inputs, without computing.

    This is deliberately NOT a formal-panel reconstruction certificate: formal
    merge retains legacy/static baseline context beyond these pure raw inputs.
    Only direct refs consumed by the frozen checkpoint owner enter this proof;
    original_ref audit subpaths are not replay inputs.
    """
    run = Path(action["run"])
    claim_path = _ownership_root(policy) / "completed" / (run.name + ".json")
    claim = read_json(claim_path)
    descriptor = claim.get("checkpoint_reconstruction", {})
    identity = {key: status[key] for key in CHECKPOINT_IDENTITY_KEYS}
    if (descriptor.get("schema") != "v4_qfq_checkpoint_reconstruction_inputs_v1"
            or descriptor.get("identity") != identity
            or identity["adapter_sha256"] != CERTIFIED_QFQ_OWNER
            or descriptor.get("runtime") != reconstruction_runtime()
            or descriptor.get("snapshot") != status.get("adjustment_snapshot")):
        raise RetentionError("CHECKPOINT_RECONSTRUCTION_DESCRIPTOR_UNKNOWN")
    evidence = {}
    def verify(ref):
        if not isinstance(ref, dict) or not re.fullmatch("[0-9a-f]{64}", ref.get("sha256", "")):
            raise RetentionError("RECONSTRUCTION_EXACT_REF_REQUIRED")
        path = safe_path(ref["path"])
        record = _checked_file(path, ref["sha256"], verified)
        evidence[str(path)] = dict(sha256=record["sha256"], stat=record["stat"])
        return path
    snapshot_path = verify(descriptor["snapshot"])
    if snapshot_path != run / "adjustment_input_snapshot.json":
        raise RetentionError("CHECKPOINT_ORIGINAL_SNAPSHOT_PATH_CONFLICT")
    snapshot = read_json(snapshot_path)
    if (canonical(snapshot) != identity["input_sha256"]
            or snapshot.get("asof_date") != status.get("asof_date", status.get("target_date"))
            or not isinstance(snapshot.get("symbols"), dict) or not snapshot["symbols"]
            or not isinstance(snapshot.get("source_files"), list) or not snapshot["source_files"]):
        raise RetentionError("CHECKPOINT_ORIGINAL_SNAPSHOT_IDENTITY_CONFLICT")
    expected_code_keys = {"driver_sha256", "formula_sha256", "field_contract_sha256", "adapter_sha256",
                          "input_adapter_sha256", "factor_cache_sha256", "tdx_adapter_sha256"}
    if set(descriptor.get("code_refs", {})) != expected_code_keys:
        raise RetentionError("CHECKPOINT_CODE_CLOSURE_MISSING")
    for key, ref in descriptor["code_refs"].items():
        if ref.get("sha256") != identity[key]:
            raise RetentionError("CHECKPOINT_CODE_IDENTITY_CONFLICT")
        verify(ref)
    owner_source = Path(descriptor["code_refs"]["adapter_sha256"]["path"])
    literals = {}
    for node in ast.parse(owner_source.read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in {"DRIVER_SHA", "FORMULA_SHA", "USER_FORMULA_SHA"}:
                literals[node.targets[0].id] = ast.literal_eval(node.value)
    if any(literals.get(name) != identity[key] for name, key in (
            ("DRIVER_SHA", "driver_sha256"), ("FORMULA_SHA", "formula_sha256"),
            ("USER_FORMULA_SHA", "user_formula_sha256"))):
        raise RetentionError("CHECKPOINT_PINNED_AUTHORITY_CONSTANT_CONFLICT")
    refs = list(snapshot["source_files"])
    for code, item in snapshot["symbols"].items():
        if not isinstance(item.get("raw_files"), list) or not item["raw_files"]:
            raise RetentionError("CHECKPOINT_RAW_INPUT_CLOSURE_MISSING")
        for ref in item["raw_files"]:
            raw_path = Path(ref["path"])
            if (ref.get("sha256", "") not in raw_path.name
                    and not ("native_archive_members" in raw_path.parts
                             and re.fullmatch("[0-9a-f]{64}", raw_path.parent.name))):
                raise RetentionError("CHECKPOINT_RAW_IMMUTABLE_ADDRESS_UNKNOWN")
            refs.append(ref)
            if "native_update_receipt" in ref:
                refs.append(ref["native_update_receipt"])
    unique, total = {}, 0
    for ref in refs:
        path = safe_path(ref["path"])
        if str(path) in unique and unique[str(path)]["sha256"] != ref["sha256"]:
            raise RetentionError("CHECKPOINT_SOURCE_HASH_CONFLICT")
        if str(path) in unique:
            continue
        # Replay inputs must remain outside every artifact tree this mechanism
        # can move/reclaim. Runtime native cache bytes and original archives stay.
        if (under(path, Path(policy["run_root"])) or under(path, Path(policy["quarantine_root"]))
                or any(under(path, Path(root)) for root in policy["formal_roots"].values())):
            raise RetentionError("CHECKPOINT_REPLAY_INPUT_IS_MANAGED_ARTIFACT")
        total += stamp(path)["size"]
        if len(unique) >= 50000 or total > policy.get("max_reconstruction_source_bytes", 32 * 1024**3):
            raise RetentionError("CHECKPOINT_RECONSTRUCTION_SOURCE_BUDGET_UNKNOWN")
        unique[str(path)] = ref
    for ref in unique.values():
        verify(ref)
    # No formula execution or table scan: only the footer's computation ID plus
    # already SHA-verified Parquet and original per-symbol receipt identity.
    import pyarrow.parquet as pq
    fingerprints = {}
    for item in action["files"]:
        path = Path(item["path"])
        if path.suffix != ".parquet":
            continue
        code = path.stem
        if code not in snapshot["symbols"]:
            raise RetentionError("CHECKPOINT_SYMBOL_NOT_IN_ORIGINAL_SNAPSHOT")
        expected = canonical(dict(code=code, item=snapshot["symbols"][code], **identity))
        receipt = read_json(path.with_suffix(".receipt.json"))
        metadata = pq.read_metadata(path).metadata or {}
        footer = json.loads(metadata.get(b"a_share_qfq_contract_v1", b"{}"))
        if receipt.get("checkpoint_id") != expected or receipt.get("sha256") != item["sha256"] or footer.get("checkpoint_id") != expected:
            raise RetentionError("CHECKPOINT_ORIGINAL_FINGERPRINT_CONFLICT")
        fingerprints[code] = expected
    if not fingerprints:
        raise RetentionError("CHECKPOINT_FINGERPRINT_COVERAGE_EMPTY")
    certificate = dict(schema="v4_qfq_checkpoint_reconstruction_certificate_v1", status="PASS_SOURCE_CLOSURE",
        snapshot=descriptor["snapshot"], identity=identity, runtime=descriptor["runtime"],
        source_count=len(unique), source_bytes=total, checkpoint_count=len(fingerprints),
        checkpoint_fingerprints_sha256=canonical(fingerprints), input_evidence_sha256=canonical(evidence),
        semantics="PURE_SYMBOL_COMPUTATION_INPUTS_NO_BASELINE_PANEL_DEPENDENCY", **FLAGS)
    return certificate, evidence


def reclamation_classification(policy: dict, action: dict, status: dict, verified: dict) -> tuple[str, dict, dict]:
    owned, evidence = future_owned(policy, action, status)
    if not owned:
        return "QUARANTINE_EXISTING", dict(status="GRANDFATHERED_NO_PURGE"), evidence
    source = Path(action["source"])
    if source.name in {"current_selector_buckets", "current_backtest_buckets"}:
        return "RECLAIM_FUTURE", dict(status="PASS_REBUILDABLE_ARROW_TEMP", source_sha256=status["baseline_panel_sha256"]), evidence
    if source.name == "symbol_checkpoints":
        try:
            certificate, inputs = checkpoint_reconstruction_certificate(policy, action, status, verified)
            return "RECLAIM_FUTURE", certificate, {**evidence, **inputs}
        except (OSError, ValueError, KeyError, TypeError, RetentionError) as exc:
            return "QUARANTINE_FUTURE_UNPROVEN", dict(status="UNKNOWN_CHECKPOINT_RECONSTRUCTION", reason=str(exc)), evidence
    return "QUARANTINE_FUTURE_UNPROVEN", dict(status="UNKNOWN_FORMAL_RECONSTRUCTION",
        reason="Formal merge requires exact retained legacy/static baseline context; no approved reconstruction proof"), evidence


def managed_runtime_projection(policy: dict, ready: list, unknown: list, keep: list,
                               relocated: dict, active_recovery_refs: list | None = None) -> tuple[set[Path], dict, dict]:
    """Project ONLY reviewed managed pins and actual frozen owner runtime seams.

    Source bindings are freshness-watch leaves, not recursive audit graphs.
    Root/controller attests registered consumer scope; this is not a claim that
    arbitrary offline files/processes across the machine have been discovered.
    """
    protected, evidence, watched_refs, visited = set(), {}, {}, set()
    def pin(value):
        original = safe_path(value, exists=False)
        path = safe_path(relocated.get(str(original), str(original)))
        protected.update((original, path))
        return path
    def watch(ref):
        if not isinstance(ref, dict) or not re.fullmatch("[0-9a-f]{64}", ref.get("sha256", "")):
            raise RetentionError("TYPED_RUNTIME_EXACT_REF_REQUIRED")
        path = pin(ref["path"])
        if str(path) in watched_refs and watched_refs[str(path)] != ref["sha256"]:
            raise RetentionError("TYPED_RUNTIME_REFERENCE_HASH_CONFLICT")
        if str(path) not in watched_refs:
            record = _checked_file(path, ref["sha256"])
            evidence[str(path)] = dict(sha256=record["sha256"], stat=record["stat"])
            watched_refs[str(path)] = ref["sha256"]
        return path
    def pin_ref(ref):
        if not isinstance(ref, dict) or not re.fullmatch("[0-9a-f]{64}", ref.get("sha256", "")):
            raise RetentionError("TYPED_RUNTIME_EXACT_REF_REQUIRED")
        return pin(ref["path"])
    inventory_ref = policy["managed_pin_inventory"]
    inventory_path = watch(inventory_ref)
    inventory_value = read_json(inventory_path)
    scopes = inventory_value.get("consumer_scopes", {})
    if (inventory_value.get("schema") != "v4_research_managed_pin_inventory_v1"
            or inventory_value.get("status") != "COMPLETE_REVIEWED"
            or set(scopes) != CONSUMER_SCOPES
            or any(value not in {"PINNED", "REVIEWED_NO_MANAGED_PINS"} for value in scopes.values())
            or not isinstance(inventory_value.get("pins"), list)
            or not inventory_value.get("source_bindings")
            or not Path(inventory_value.get("expected_main_app_root", "")).is_absolute()):
        raise RetentionError("MANAGED_PIN_SCOPE_INCOMPLETE_OR_UNKNOWN")
    for ref in inventory_value["source_bindings"]:
        watch(ref)
    def runtime(ref, usage="active_input"):
        if usage not in {"active_input", "historical_pin"}:
            raise RetentionError("RUNTIME_REFERENCE_USAGE_UNKNOWN")
        path = watch(ref)
        if (path, usage) in visited:
            return
        if len(visited) >= 256:
            raise RetentionError("TYPED_RUNTIME_DOCUMENT_BUDGET_UNKNOWN")
        visited.add((path, usage))
        value = read_json(path)
        schema = value.get("schema")
        leaf = watch if usage == "active_input" else pin_ref
        if schema == "qfq_original_checkpoint_recovery_v1":
            run = pin(value["source_run"])
            if (not RUN.fullmatch(run.name) or not isinstance(value.get("chunks"), dict)
                    or not isinstance(value.get("source_identity"), dict)
                    or not isinstance(value.get("retry_original_quarantined"), list)):
                raise RetentionError("CHECKPOINT_RECOVERY_RUNTIME_SHAPE_UNKNOWN")
            leaf(value["original_snapshot"])
            leaf(value["source_core"])
            for code, item in value["chunks"].items():
                if (not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code)
                        or Path(item["artifact"]["path"]) != run / "symbol_checkpoints" / (code + ".parquet")
                        or Path(item["receipt"]["path"]) != run / "symbol_checkpoints" / (code + ".receipt.json")):
                    raise RetentionError("CHECKPOINT_RECOVERY_RUNTIME_MAPPING_UNKNOWN")
                leaf(item["artifact"])
                leaf(item["receipt"])
            for key in ("tail_delta", "same_asof_source_repair"):
                if value.get(key) is not None:
                    runtime(value[key], usage)
        elif schema in {"qfq_native_tail_delta_v1", "qfq_native_tail_delta_v2",
                        "qfq_archive_only_history_additions_v1", "qfq_same_asof_source_repair_v1"}:
            if set(value.get("baseline_roles", {})) != ROLES:
                raise RetentionError("RUNTIME_BASELINE_ROLE_SHAPE_UNKNOWN")
            for ref in value["baseline_roles"].values():
                leaf(ref)
            for key in ("baseline_snapshot", "baseline_receipt", "baseline_core"):
                if key in value:
                    leaf(value[key])
        elif schema == "qfq_shared_history_extension_v1":
            if set(value.get("roles", {})) != ROLES:
                raise RetentionError("HISTORY_ROLE_SHAPE_UNKNOWN")
            for binding in value["roles"].values():
                leaf(binding["panel"])
                for ref in binding["sidecars"]:
                    leaf(ref)
            history(value)
        else:
            raise RetentionError(f"RUNTIME_SCHEMA_UNKNOWN:{schema}:{path}")
    def history(value):
        if not isinstance(value, dict) or any(key not in value for key in ("source_config", "source_policy", "archive_refs", "accepted_evidence")):
            raise RetentionError("HISTORY_RETENTION_RUNTIME_SHAPE_UNKNOWN")
        if not isinstance(value["archive_refs"], list) or not isinstance(value["accepted_evidence"], list):
            raise RetentionError("HISTORY_RETENTION_REFERENCE_LIST_UNKNOWN")
        for ref in [value["source_config"], value["source_policy"], *value["archive_refs"], *value["accepted_evidence"]]:
            watch(ref)  # accepted_history_retention _source only; no JSON recursion.
    for item in inventory_value["pins"]:
        if item.get("kind") == "managed_path":
            pin(item["path"])
        elif item.get("kind") == "checkpoint_recovery":
            runtime(item, item.get("usage", "active_input"))
        else:
            raise RetentionError("MANAGED_PIN_KIND_UNKNOWN")
    runtime_statuses = keep + [dict(run=Path(x["path"]), status=read_json(Path(x["path"]) / "stage_status.json")) for x in unknown]
    for item in runtime_statuses:
        status = item["status"]
        for key, value in status.items():
            if value is not None and "recovery" in key and key not in {"checkpoint_recovery", "same_asof_checkpoint_recovery"}:
                raise RetentionError(f"RUNTIME_RECOVERY_FIELD_UNKNOWN:{key}")
        if status.get("checkpoint_recovery") is not None:
            runtime(status["checkpoint_recovery"], "historical_pin")
        summary = status.get("same_asof_checkpoint_recovery")
        if summary is not None:
            if not isinstance(summary, dict) or "binding_ref" not in summary or "source_run" not in summary:
                raise RetentionError("SAME_ASOF_RECOVERY_SUMMARY_UNKNOWN")
            pin(summary["source_run"])
            runtime(summary["binding_ref"], "historical_pin")
            recovery_value = read_json(Path(summary["binding_ref"]["path"]))
            if recovery_value.get("schema") != "qfq_original_checkpoint_recovery_v1" or recovery_value.get("source_run") != summary["source_run"]:
                raise RetentionError("SAME_ASOF_RECOVERY_SOURCE_RUN_CONFLICT")
    for ref in active_recovery_refs or []:
        runtime(ref, "active_input")
    for item in runtime_statuses:
        status = item["status"]
        if status.get("history_retention_binding") is not None:
            history(status["history_retention_binding"])
        for key in ("tail_delta", "archive_additions", "history_extension"):
            if status.get(key) is not None:
                runtime(status[key], "historical_pin")
        same = status.get("same_asof_source_repair")
        if same is not None:
            if not isinstance(same, dict) or same.get("schema") != "qfq_same_asof_source_repair_v1" or "binding_ref" not in same:
                raise RetentionError("SAME_ASOF_RUNTIME_SUMMARY_UNKNOWN")
            runtime(same["binding_ref"], "historical_pin")
    journal = Path(policy["data_root"]) / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json"
    if journal.exists():
        value = read_json(journal)
        if (set(value) != {"after", "before_base64", "pointers", "status"}
                or value["pointers"] != policy["pointers"] or set(value["after"]) != ROLES or set(value["before_base64"]) != ROLES):
            raise RetentionError("PUBLICATION_JOURNAL_RUNTIME_SHAPE_UNKNOWN")
        if value["status"] == "PREPARED":
            raise RetentionError("PUBLICATION_RECOVERY_PENDING")
        if value["status"] not in {"COMMITTED", "ROLLED_BACK", "ROLLED_BACK_AFTER_INTERRUPTION"}:
            raise RetentionError("PUBLICATION_JOURNAL_STATUS_UNKNOWN")
        watch(dict(path=str(journal), sha256=digest(journal)))
        for role in ROLES:
            text = value["after"][role]
            if not text.endswith("\n") or text.count("\n") != 1:
                raise RetentionError("PUBLICATION_POINTER_TEXT_UNKNOWN")
            pin(text[:-1])
            pin(base64.b64decode(value["before_base64"][role], validate=True).decode("utf-8-sig").strip())
    return protected, evidence, inventory_value


def plan(policy: dict, *, active_recovery_refs: list | None = None) -> dict:
    pointers = pointer_state(policy)
    ready, unknown, watched = inventory(policy)
    targets = {item["target"] for item in pointers.values()}
    current = [item for item in ready if set(item["status"]["candidates"].values()) == targets]
    if len(current) != 1:
        raise RetentionError("CURRENT_PAIR_NOT_ONE_READY_GENERATION")
    current = current[0]
    # The immediate baseline SHA pair identifies rollback, not timestamps.
    baseline = current["status"]["baseline_panel_sha256"]
    rollback = [item for item in ready if item["status"]["candidate_sha256"] == baseline]
    if len(rollback) != 1:
        raise RetentionError("ROLLBACK_PAIR_UNKNOWN_OR_AMBIGUOUS")
    keep = [current, rollback[0]]
    relocated = {item["original_path"]: item["archived_path"] for item in policy.get("formal_relocations", [])}
    keep_runs = {item["run"] for item in keep}
    protected, graph, pin_inventory = managed_runtime_projection(policy, ready, unknown, keep, relocated, active_recovery_refs)
    for mapping in policy.get("formal_relocations", []):
        original, archived = Path(mapping["original_path"]), Path(mapping["archived_path"])
        if any(overlap(original, pin) for pin in protected):
            protected.add(archived)
        proof = Path(mapping["manifest"]["path"])
        graph[str(proof)] = dict(sha256=mapping["manifest"]["sha256"], stat=stamp(proof))
    protected.update(Path(item["path"]) for item in unknown)
    for item in keep:
        protected.add(item["run"] / "symbol_checkpoints")
        protected.update(Path(value) for value in item["status"]["candidates"].values())
    # Existing formal sources can verify old spool source hashes. Never accept
    # an old SHA merely because a receipt once named the same path.
    sources = {}
    for item in ready:
        for role, value in item["status"]["candidates"].items():
            path = Path(relocated.get(value, value))
            if path.is_file():
                sources.setdefault(item["status"]["candidate_sha256"][role], []).append(path)
    # Reuse full source hashes only for the exact same file identity, including
    # ctime. Conflicts are cached too; unchanged quarantined/unknown history is
    # not rehashed in full every daily invocation.
    cache_path = Path(policy["run_root"]) / "storage_retention_source_verifications.json"
    source_verifications = {}
    if cache_path.exists():
        cached = read_json(cache_path)
        if cached.get("schema") == SCHEMA and cached.get("policy_sha256") == canonical(policy):
            source_verifications = cached.get("sources", {})
    verified_sources, actions = {}, []
    for item in ready:
        run, status = item["run"], item["status"]
        kept = run in keep_runs
        if not kept and any(overlap(run, path) for path in protected):
            continue
        staged = []
        try:
            for role in sorted(ROLES):
                spool = run / f"current_{role}_buckets"
                if not spool.exists():
                    continue
                if kept:
                    owned, _ = future_owned(policy, dict(run=str(run), source=str(spool)), status)
                    if not owned or any(overlap(spool, pin) for pin in protected):
                        continue
                receipt = read_json(spool / "receipt.json")
                source_sha = receipt["source_sha256"]
                if receipt.get("row_copy") != "ARROW_V1" or source_sha != status["baseline_panel_sha256"][role]:
                    raise RetentionError("SPOOL_SOURCE_RECEIPT_CONFLICT")
                if source_sha not in verified_sources:
                    choices = sources.get(source_sha, [])
                    if len(choices) != 1:
                        raise RetentionError("SPOOL_SOURCE_UNKNOWN_OR_AMBIGUOUS")
                    verified_sources[source_sha] = _checked_file(choices[0], source_sha, source_verifications)
                expected = {value["path"]: value["sha256"] for value in receipt["files"].values()}
                if not expected or any(Path(value).parent != spool for value in expected):
                    raise RetentionError("SPOOL_PATH_ESCAPE")
                expected[str(spool / "receipt.json")] = digest(spool / "receipt.json")
                staged.append(_tree_record(spool, expected))
            checkpoints = run / "symbol_checkpoints"
            if not kept and checkpoints.exists():
                expected = {}
                for path in checkpoints.glob("*.receipt.json"):
                    receipt = read_json(path)
                    artifact = path.with_name(path.name.removesuffix(".receipt.json") + ".parquet")
                    expected[str(path)], expected[str(artifact)] = digest(path), receipt["sha256"]
                staged.append(_tree_record(checkpoints, expected))
            for role, value in status["candidates"].items():
                if kept:
                    continue
                path = Path(relocated.get(value, value))
                if not path.exists():
                    # Missing old names are not authority to move renamed
                    # legacy archives. Those require a separate proven map.
                    continue
                root = path.parent if role == "selector" else path.parent.parent
                if root == Path(policy["formal_roots"][role]) or any(overlap(root, pin) for pin in protected):
                    continue
                staged.append(_tree_record(root, {str(path): status["candidate_sha256"][role]}, verified=source_verifications))
            run_actions, ownership_evidence = [], {}
            for action in staged:
                source = Path(action["source"])
                if any(overlap(source, pin) for pin in protected):
                    continue
                action["run"] = str(run)
                action["kind"] = "DERIVED_READY_ARTIFACT"
                disposition, reconstruction, proof = reclamation_classification(policy, action, status, source_verifications)
                action["disposition"], action["reconstruction"] = disposition, reconstruction
                ownership_evidence.update(proof)
                run_actions.append(action)
            watched.update(ownership_evidence)
            actions.extend(run_actions)
        except (OSError, ValueError, KeyError, TypeError, RetentionError) as exc:
            # A source conflict preserves the ENTIRE run, including both spools.
            unknown.append(dict(path=str(run), reason=str(exc)))
    evidence = {**watched, **graph}
    for value in verified_sources.values():
        evidence[value["path"]] = dict(sha256=value["sha256"], stat=value["stat"])
    # A reconstruction source remains at its original path throughout this
    # transaction, including interrupted/resumed apply. A later plan can move
    # it once there are no remaining spools depending on that verification.
    actions = [action for action in actions if not any(
        under(Path(value["path"]), Path(action["source"])) for value in verified_sources.values())]
    result = dict(schema=SCHEMA, policy_sha256=canonical(policy), pointers=pointers,
                  protected=sorted(map(str, protected)), evidence=evidence,
                  run_names=sorted(path.name for path in Path(policy["run_root"]).iterdir() if RUN.fullmatch(path.name)),
                  source_verifications=source_verifications, preserved_unknown=unknown,
                  consumer_scope_attestations=pin_inventory["consumer_scopes"],
                  actions=actions, move_bytes=sum(item["bytes"] for item in actions),
                  auto_gc_enabled=False, dry_run=True, gc_execution_status="BLOCKED_UNREGISTERED_READER_COORDINATION", **FLAGS)
    result["plan_id"] = canonical(result)
    return result


def _recheck(policy: dict, proposal: dict) -> None:
    if proposal["policy_sha256"] != canonical(policy) or proposal["pointers"] != pointer_state(policy):
        raise RetentionError("PLAN_POLICY_OR_POINTER_CHANGED")
    names = sorted(path.name for path in Path(policy["run_root"]).iterdir() if RUN.fullmatch(path.name))
    if proposal["run_names"] != names:
        raise RetentionError("RUN_INVENTORY_CHANGED")
    for value, expected in proposal["evidence"].items():
        path = safe_path(value)
        if stamp(path) != expected["stat"] or digest(path) != expected["sha256"]:
            raise RetentionError(f"PLAN_EVIDENCE_CHANGED:{path}")


def apply(policy: dict, proposal: dict) -> dict:
    """Nondeleting candidate validation; no rename/unlink under dry-run.

    Legacy future_reclamation is creation provenance, never GC authorization.
    Actual Reader/reference coordination has not been integrated. Even an
    explicit switch cannot enable mutation until that separate contract exists.
    """
    identity = dict(proposal)
    plan_id = identity.pop("plan_id")
    if canonical(identity) != plan_id:
        raise RetentionError("PLAN_DIGEST_CONFLICT")
    _recheck(policy, proposal)
    if policy.get("auto_gc_enabled", False) and not policy.get("dry_run", True):
        raise RetentionError("GC_BLOCKED_UNREGISTERED_READER_COORDINATION")
    return dict(status="DRY_RUN_NO_DATA_MUTATION", plan_id=plan_id,
                candidate_count=len(proposal["actions"]),
                candidate_bytes=proposal["move_bytes"], moved_bytes=0,
                reclaimed_logical_bytes=0, freed_bytes=0,
                auto_gc_enabled=False, dry_run=True,
                blocker="UNREGISTERED_READER_COORDINATION_AND_POLICY_AUTHORIZATION")


def growth_guard(policy: dict, *, already_current: bool) -> dict:
    if already_current:
        return dict(status="REUSE_NO_NEW_BUILD_RESERVATION")
    state = pointer_state(policy)
    pair_bytes = sum(item["target_stat"]["size"] for item in state.values())
    # Full pair output + Arrow bucket copies + computed symbol shards, with
    # headroom. This is a conservative estimate, not a filesystem allocation cap.
    predicted = max(policy["minimum_build_bytes"], math.ceil(pair_bytes * 3.5))
    quarantine = quarantine_state(policy)
    quarantine_bytes = quarantine["bytes"]
    managed_bytes = logical_bytes(Path(policy["run_root"])) + sum(logical_bytes(Path(path)) for path in policy["formal_roots"].values())
    free = shutil.disk_usage(policy["data_root"]).free
    if free - predicted < policy["reserve_bytes"]:
        raise RetentionError(f"NEW_BUILD_SPACE_BUDGET:free={free}:predicted={predicted}:reserve={policy['reserve_bytes']}")
    if managed_bytes + quarantine_bytes + predicted > policy["max_managed_bytes"]:
        raise RetentionError("NEW_BUILD_MANAGED_BUDGET_NO_PERMANENT_DELETE")
    if quarantine_bytes >= policy["max_quarantine_bytes"]:
        raise RetentionError("NEW_BUILD_QUARANTINE_BUDGET_NO_PERMANENT_DELETE")
    return dict(status="NEW_BUILD_BUDGET_RESERVED", predicted_bytes=predicted, free_bytes=free,
                managed_bytes=managed_bytes, quarantine_bytes=quarantine_bytes, quarantine_status=quarantine["status"])


def run_with_retention(rebuild, *, data_root: Path, return_root: Path, pointers: dict,
                       target: int, ready_check, **kwargs) -> dict:
    configured = os.environ.get("V4_RESEARCH_RETENTION_POLICY")
    expected_sha = os.environ.get("V4_RESEARCH_RETENTION_POLICY_SHA256")
    if not configured and not expected_sha:
        return rebuild(data_root=data_root, return_root=return_root, pointers=pointers, target=target, **kwargs)
    if not configured or not expected_sha:
        raise RetentionError("POLICY_PATH_AND_SHA_REQUIRED")
    policy = load_policy(Path(configured), data_root=data_root, run_root=return_root, pointers=pointers,
                         expected_sha256=expected_sha)
    pin_inventory = read_json(Path(policy["managed_pin_inventory"]["path"]))
    if digest(Path(policy["managed_pin_inventory"]["path"])) != policy["managed_pin_inventory"]["sha256"]:
        raise RetentionError("MANAGED_PIN_INVENTORY_HASH_DRIFT")
    if pin_inventory.get("expected_main_app_root") != str(Path(__file__).resolve().parents[1]):
        raise RetentionError("MAIN_APP_ROOT_BINDING_FAILED")
    with owner_lock(policy):
        with owner_lock(policy, publication=True):
            from ops.research_storage_governance import configuration, verified_qfq_current, governed_qfq
            governed = configuration(policy) is not None
            reuse = bool(ready_check())
            if governed and reuse:
                from ops import research_panel_qfq
                current = verified_qfq_current(research_panel_qfq, policy, target, kwargs)
                if current is not None:
                    # Existing results stay safely readable even when the pool
                    # registry or disk admission is unavailable. No producer runs.
                    current["storage_retention"] = dict(reservation=dict(status="VERIFIED_REUSE_NO_WRITES"),
                        outcome=dict(status="DRY_RUN_NO_DATA_MUTATION"))
                    return current
                raise RetentionError("READY_COMPUTE_IDENTITY_RECONCILIATION_REQUIRED_NO_AUTOMATIC_REBUILD")
            reservation = growth_guard(policy, already_current=reuse)
            creation = begin_creation(policy) if not reuse else None
        # The original owner retains its publication lock and all source gates.
        if governed:
            result = governed_qfq(rebuild, policy, reservation, data_root=data_root,
                return_root=return_root, pointers=pointers, target=target, **kwargs)
        else:
            result = rebuild(data_root=data_root, return_root=return_root, pointers=pointers, target=target, **kwargs)
        if result.get("status") != "READY":
            return result
        try:
            with owner_lock(policy, publication=True):
                register_creation(policy, creation, result, kwargs)
                active_refs = [kwargs["checkpoint_resume"]] if kwargs.get("checkpoint_resume") is not None else []
                proposal = plan(policy, active_recovery_refs=active_refs)
                atomic_json(Path(return_root) / "storage_retention_source_verifications.json",
                    dict(schema=SCHEMA, policy_sha256=canonical(policy), sources=proposal["source_verifications"]))
                outcome = apply(policy, proposal) if proposal["actions"] else dict(status="NO_ELIGIBLE_ARTIFACTS")
        except (RetentionError, OSError, ValueError, KeyError, TypeError) as exc:
            # A committed research pair remains READY; retain diagnostics rather
            # than converting successful publication into FAILED/recomputation.
            outcome = dict(status="PRESERVED_UNKNOWN", error=str(exc))
        result["storage_retention"] = dict(reservation=reservation, outcome=outcome)
        try:
            atomic_json(Path(return_root) / "storage_retention_last.json", result["storage_retention"])
        except OSError as exc:
            result["storage_retention"]["receipt_write_error"] = str(exc)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--plan", required=True, type=Path, help="Saved plan output (dry run) or input (--apply)")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    policy = load_policy(args.policy, expected_sha256=args.policy_sha256)
    safe_path(args.plan, exists=args.apply)
    if args.plan.suffix != ".json" or any(under(args.plan, Path(policy[key]))
            for key in ("data_root", "run_root", "quarantine_root")):
        raise RetentionError("PLAN_OUTPUT_MUST_BE_EXTERNAL_AUDIT_JSON")
    with owner_lock(policy), owner_lock(policy, publication=True):
        if args.apply:
            print(json.dumps(apply(policy, read_json(args.plan)), ensure_ascii=False))
        else:
            proposal = plan(policy)
            atomic_json(args.plan, proposal)
            print(json.dumps(dict(plan_id=proposal["plan_id"], actions=len(proposal["actions"]), move_bytes=proposal["move_bytes"], preserved_unknown=proposal["preserved_unknown"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
