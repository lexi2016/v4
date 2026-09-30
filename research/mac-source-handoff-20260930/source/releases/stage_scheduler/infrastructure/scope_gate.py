"""Fail-closed exact-scope write gate for the isolated owner-gate candidate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import re
from typing import Any, Iterable, Mapping


PERMIT_SCHEMA = "v4.preselection.exact_scope.v1"
GATE_SCHEMA = "v4.preselection.gate.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_POOL_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
_WILDCARDS = frozenset("*?[]")
_PERMIT_FIELDS = frozenset(
    {
        "schema_version",
        "decision_id",
        "owner_id",
        "source_release_sha256",
        "target_release_sha256",
        "source_root",
        "target_root",
        "keys",
        "business_key_set_sha256",
    }
)
_GATE_FIELDS = frozenset({"schema_version", "permit_sha256", "revision", "state"})


class GateConfigurationError(RuntimeError):
    """The configured scope permit or durable gate is missing or invalid."""


class GateCASConflict(GateConfigurationError):
    """A gate revision changed since the caller read it."""


class StoreWriteFenced(GateConfigurationError):
    """The exact date/pool is durably fenced for store writes."""


@dataclass(frozen=True)
class StoreGateContext:
    """Explicit caller-bound identity and an independent permit-byte trust anchor.

    This is a control-protocol identity.  It does not assert that the supplied
    owner, root, or release values are authoritative outside this candidate.
    """

    control_dir: Path
    expected_permit_sha256: str
    expected_owner_id: str
    expected_release_sha256: str
    expected_root: Path


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateConfigurationError("duplicate JSON field")
        result[key] = value
    return result


def _decode_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateConfigurationError(f"invalid {label} JSON") from error
    if not isinstance(value, dict):
        raise GateConfigurationError(f"invalid {label} object")
    return value


def _exact_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise GateConfigurationError(f"invalid {label}")
    if any(char in value for char in _WILDCARDS) or "\x00" in value:
        raise GateConfigurationError(f"non-exact {label}")
    return value


def _sha_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GateConfigurationError(f"invalid {label}")
    return value


def _absolute_root(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or any(char in value for char in _WILDCARDS)
    ):
        raise GateConfigurationError(f"invalid {label}")
    path = Path(value)
    if not path.is_absolute() or os.path.normpath(value) != value:
        raise GateConfigurationError(f"non-canonical {label}")
    return value


def _check_root_directory(path_text: str, label: str) -> None:
    path = Path(path_text)
    try:
        if path.resolve(strict=True) != path:
            raise GateConfigurationError(f"symlinked {label}")
        info = path.lstat()
    except OSError as error:
        raise GateConfigurationError(f"unavailable {label}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise GateConfigurationError(f"invalid {label}")


def _business_key_set_sha256(keys: list[dict[str, str]]) -> str:
    ordered = sorted(
        keys,
        key=lambda item: (item["business_key"], item["trade_date"], item["pool_id"]),
    )
    return hashlib.sha256(canonical_bytes(ordered)).hexdigest()


def _validate_permit(
    permit: Mapping[str, Any],
    *,
    expected_owner_id: str,
    expected_release_sha256: str,
    expected_root: str,
    pool_ids: Iterable[str],
) -> tuple[dict[tuple[str, str], frozenset[str]], str]:
    if set(permit) != _PERMIT_FIELDS:
        raise GateConfigurationError("permit fields do not match the exact schema")
    if permit.get("schema_version") != PERMIT_SCHEMA:
        raise GateConfigurationError("unsupported permit schema")
    _exact_text(permit.get("decision_id"), "decision id")
    owner_id = _exact_text(permit.get("owner_id"), "owner id")
    if owner_id != expected_owner_id:
        raise GateConfigurationError("permit owner identity mismatch")

    source_release = _sha_text(permit.get("source_release_sha256"), "source release SHA")
    target_release = _sha_text(permit.get("target_release_sha256"), "target release SHA")
    source_root = _absolute_root(permit.get("source_root"), "source root")
    target_root = _absolute_root(permit.get("target_root"), "target root")
    if source_root == target_root:
        raise GateConfigurationError("source and target roots must be distinct")
    _check_root_directory(source_root, "source root")
    _check_root_directory(target_root, "target root")
    source_match = expected_root == source_root and expected_release_sha256 == source_release
    target_match = expected_root == target_root and expected_release_sha256 == target_release
    if source_match == target_match or not (source_match or target_match):
        raise GateConfigurationError("store root/release identity mismatch")

    allowed_pools = frozenset(pool_ids)
    raw_keys = permit.get("keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise GateConfigurationError("empty exact scope")
    keys: list[dict[str, str]] = []
    unique_keys: set[tuple[str, str, str]] = set()
    scoped_pools: dict[tuple[str, str], set[str]] = {}
    for raw in raw_keys:
        if not isinstance(raw, dict) or set(raw) != {"business_key", "trade_date", "pool_id"}:
            raise GateConfigurationError("invalid exact key fields")
        business_key = _exact_text(raw.get("business_key"), "business key")
        trade_date = raw.get("trade_date")
        if not isinstance(trade_date, str) or len(trade_date) != 8 or not trade_date.isdigit():
            raise GateConfigurationError("invalid exact trade date")
        try:
            datetime.strptime(trade_date, "%Y%m%d")
        except ValueError as error:
            raise GateConfigurationError("invalid exact trade date") from error
        pool_id = raw.get("pool_id")
        if not isinstance(pool_id, str) or _POOL_ID.fullmatch(pool_id) is None or pool_id not in allowed_pools:
            raise GateConfigurationError("invalid or unknown exact pool")
        identity = (business_key, trade_date, pool_id)
        if identity in unique_keys:
            raise GateConfigurationError("duplicate exact key")
        unique_keys.add(identity)
        keys.append({"business_key": business_key, "trade_date": trade_date, "pool_id": pool_id})
        scoped_pools.setdefault((trade_date, pool_id), set()).add(business_key)
    expected_keyset_sha = _business_key_set_sha256(keys)
    actual_keyset_sha = _sha_text(permit.get("business_key_set_sha256"), "business key-set SHA")
    if actual_keyset_sha != expected_keyset_sha:
        raise GateConfigurationError("business key-set SHA mismatch")
    return {key: frozenset(values) for key, values in scoped_pools.items()}, actual_keyset_sha


def _open_control_directory(control_dir: Path) -> int:
    if not isinstance(control_dir, Path) or not control_dir.is_absolute():
        raise GateConfigurationError("control directory must be an absolute Path")
    if any(char in str(control_dir) for char in _WILDCARDS):
        raise GateConfigurationError("control directory must be an exact path")
    try:
        if control_dir.resolve(strict=True) != control_dir:
            raise GateConfigurationError("symlinked control directory")
        before = control_dir.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise GateConfigurationError("invalid control directory")
        fd = os.open(
            str(control_dir),
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except GateConfigurationError:
        raise
    except OSError as error:
        raise GateConfigurationError("unavailable control directory") from error
    after = os.fstat(fd)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        os.close(fd)
        raise GateConfigurationError("control directory changed while opening")
    return fd


def _read_regular_at(directory_fd: int, name: str, *, missing_ok: bool = False) -> bytes | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise GateConfigurationError(f"missing control file: {name}")
    except OSError as error:
        raise GateConfigurationError(f"cannot open control file: {name}") from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise GateConfigurationError(f"control file is not regular: {name}")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > 4 * 1024 * 1024:
                raise GateConfigurationError(f"control file is too large: {name}")
            chunks.append(block)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _load_permit_at(
    directory_fd: int,
    context: StoreGateContext,
    store_root: Path,
    pool_ids: Iterable[str],
) -> tuple[dict[tuple[str, str], frozenset[str]], str]:
    expected_permit_sha = _sha_text(context.expected_permit_sha256, "permit trust-anchor SHA")
    owner_id = _exact_text(context.expected_owner_id, "expected owner id")
    expected_release = _sha_text(context.expected_release_sha256, "expected release SHA")
    expected_root = _absolute_root(str(context.expected_root), "expected root")
    actual_root = _absolute_root(str(store_root), "store root")
    if expected_root != actual_root:
        raise GateConfigurationError("configured root does not match store root")
    _check_root_directory(expected_root, "store root")
    permit_bytes = _read_regular_at(directory_fd, "permit.json")
    assert permit_bytes is not None
    if hashlib.sha256(permit_bytes).hexdigest() != expected_permit_sha:
        raise GateConfigurationError("permit does not match independent trust anchor")
    permit = _decode_object(permit_bytes, "permit")
    scope, keyset_sha = _validate_permit(
        permit,
        expected_owner_id=owner_id,
        expected_release_sha256=expected_release,
        expected_root=expected_root,
        pool_ids=pool_ids,
    )
    return scope, keyset_sha


def _parse_gate(data: bytes, expected_permit_sha: str) -> dict[str, Any]:
    gate = _decode_object(data, "gate")
    if set(gate) != _GATE_FIELDS or gate.get("schema_version") != GATE_SCHEMA:
        raise GateConfigurationError("gate fields do not match the exact schema")
    if gate.get("permit_sha256") != expected_permit_sha:
        raise GateConfigurationError("gate permit identity mismatch")
    revision = gate.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise GateConfigurationError("invalid gate revision")
    if gate.get("state") not in {"FENCED", "OPEN"}:
        raise GateConfigurationError("invalid gate state")
    return gate


def _load_gate_at(directory_fd: int, expected_permit_sha: str) -> dict[str, Any]:
    gate_bytes = _read_regular_at(directory_fd, "gate.json")
    assert gate_bytes is not None
    return _parse_gate(gate_bytes, expected_permit_sha)


def _lock_control(directory_fd: int) -> int:
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open("control.lock", flags, 0o600, dir_fd=directory_fd)
    except OSError as error:
        raise GateConfigurationError("cannot open control lock") from error
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise GateConfigurationError("control lock is not regular")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError as error:
        os.close(fd)
        raise GateConfigurationError("cannot acquire control lock") from error
    return fd


def _unlock_control(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _atomic_write_gate(directory_fd: int, gate: Mapping[str, Any]) -> None:
    name = f".gate.json.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    try:
        try:
            data = canonical_bytes(gate)
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise GateConfigurationError("short write while updating gate")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(name, "gate.json", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def update_gate_state(
    context: StoreGateContext,
    *,
    store_root: Path,
    pool_ids: Iterable[str],
    expected_revision: int,
    state: str,
) -> dict[str, Any]:
    """CAS-update the durable gate; caller must hold the store's existing lock."""

    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
        raise GateCASConflict("invalid expected gate revision")
    if state not in {"FENCED", "OPEN"}:
        raise GateConfigurationError("gate state must be FENCED or OPEN")
    directory_fd = _open_control_directory(context.control_dir)
    lock_fd = -1
    try:
        _load_permit_at(directory_fd, context, store_root, pool_ids)
        lock_fd = _lock_control(directory_fd)
        permit_sha = context.expected_permit_sha256
        current_bytes = _read_regular_at(directory_fd, "gate.json", missing_ok=True)
        if current_bytes is None:
            current_revision = 0
        else:
            current_revision = _parse_gate(current_bytes, permit_sha)["revision"]
        if current_revision != expected_revision:
            raise GateCASConflict("gate revision compare-and-swap conflict")
        updated = {
            "schema_version": GATE_SCHEMA,
            "permit_sha256": permit_sha,
            "revision": current_revision + 1,
            "state": state,
        }
        _atomic_write_gate(directory_fd, updated)
        return updated
    finally:
        if lock_fd >= 0:
            _unlock_control(lock_fd)
        os.close(directory_fd)


def assert_write_allowed(
    context: StoreGateContext | None,
    *,
    store_root: Path,
    trade_date: str,
    pool_id: str,
    pool_ids: Iterable[str],
) -> None:
    """Validate full identity on every enabled call and enforce exact pool/date fences."""

    if context is None:
        return
    directory_fd = _open_control_directory(context.control_dir)
    try:
        scope, _ = _load_permit_at(directory_fd, context, store_root, pool_ids)
        gate = _load_gate_at(directory_fd, context.expected_permit_sha256)
        if (trade_date, pool_id) in scope and gate["state"] == "FENCED":
            raise StoreWriteFenced(f"preselection pool fenced: {trade_date}/{pool_id}")
    finally:
        os.close(directory_fd)
