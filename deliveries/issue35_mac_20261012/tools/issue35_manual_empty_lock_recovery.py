#!/usr/bin/env python3
"""One-time preservation of the exact empty Issue35 legacy owner lock.

The production CLI has no path overrides. It is deliberately pinned to the
single empty inode in the phase4 receipt and moves that inode to a unique
same-directory name. It never removes a file or edits the canonical lock
protocol. The parameterized core exists only so focused tests can use temp
directories; do not call it with production paths except through main().
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
from dataclasses import dataclass
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple


TASK_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/"
    "V4_ISSUE35_AUTOCONTINUE_MAC_20261011_R1"
)
RECEIPT_ROOT = TASK_ROOT / "E/receipts/phase4-issue35-target13/empty-lock-recovery"
OPERATION_RECEIPT = RECEIPT_ROOT / "manual-preservation-operation-r1.json"

LOCK_PATH = Path("/Users/lexi/Library/LaunchAgents/.com.lexi.v35.api-only.release.lock")
QUARANTINE_PATH = Path(
    "/Users/lexi/Library/LaunchAgents/"
    ".com.lexi.v35.api-only.release.lock.issue35-preserved-empty-20261012-r1"
)
MUTEX_PATH = Path("/Users/lexi/Library/LaunchAgents/.com.lexi.v35.api-only.release.lock.mutex")
API_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")

LOCK_PREIMAGE = {
    "dev": 16777232,
    "ino": 39451362,
    "mode": 0o600,
    "uid": 501,
    "gid": 20,
    "nlink": 1,
    "size": 0,
    "mtime_ns": 1791596148749688590,
    "ctime_ns": 1791596148749723139,
}
MUTEX_PREIMAGE = {
    "dev": 16777232,
    "ino": 38685666,
    "mode": 0o600,
    "uid": 501,
    "gid": 20,
    "nlink": 1,
    "size": 0,
    "mtime_ns": 1791556131958878784,
    "ctime_ns": 1791556131958902409,
}
PARENT_PREIMAGE = {
    "dev": 16777232,
    "ino": 403963,
    "mode": 0o700,
    "uid": 501,
    "gid": 20,
}
LIVE_PLIST_SHAS = {
    str(API_PLIST): "978a36400a1c2ea4ae058e53baadc1c706c956e65d1c0ac76a3163dc42696d76",
    str(SCHEDULER_PLIST): "5b6e208750e5f6287975857456ae0aabea57d6f5b9d4fecaecf619be17b75413",
}
CONFIRMATION = "ISSUE35_PRESERVE_EMPTY_LOCK_20261012_39451362"
EXPECTED_FAILED_PAIR_ARGV = [
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python",
    "-B",
    str(TASK_ROOT / "E/tools/issue35_phase4_pair_publication_adapter_r3_noop.py"),
    "execute",
    "--pair-dir",
    str(TASK_ROOT / "E/staged_config/phase4-issue35-target13-pair-r3-noop"),
    "--confirm",
    "ISSUE35_PAIR_20261013_1144a05dd3a03aa7",
]

# Pin the evidence that establishes this exact recovery case, the normal lock
# implementation, and the immediately pending R3 publication identity.
PINNED_FILES = {
    TASK_ROOT / "E/PHASE4_EMPTY_LOCK_RECOVERY_SCOPE.md":
        "6625e862be58863666f7cf3cfb4721010edc896e0ebb589356ec39d8057fc545",
    TASK_ROOT / "E/receipts/phase4-issue35-target13/shared-lock-empty-preimage.json":
        "965fc37984e594a990c9abb574af69d94c1419839baeb0fa44a2c4d3a0509d59",
    TASK_ROOT / "E/receipts/phase4-issue35-target13/parent-pair-execute-command.json":
        "e0e691f1505f8716f1c29f9cb562014dda4dd500bac57326c629f338c4b1fbde",
    TASK_ROOT / "E/receipts/phase4-issue35-target13/parent-pair-execute.stderr.txt":
        "3cd7b31e325161bb1ba14a1ddbf6e366df4a7ab56ed0b230a4ef1b57037a46ac",
    TASK_ROOT / "E/receipts/phase4-issue35-target13/parent-pair-execute.stdout.json":
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    TASK_ROOT / "E/receipts/phase4-issue35-target13/pair-env-rootcause.json":
        "358d22cd6408d0a5b3e041d02c3e439e9d3fe6e40abdb8e9d70815c9f312c1e9",
    TASK_ROOT / "E/tools/issue35_phase4_pair_publication_adapter_r3_noop.py":
        "7971552107f2da3365af208a766cbc39822c7164ab911610138e9273a6b65b9e",
    TASK_ROOT / "E/staged_config/phase4-issue35-target13-pair-r3-noop/pair-plan.json":
        "22e333259076f1512199e8e391aece50780a17e3aaccc33ff64b5936fa62fdb0",
    TASK_ROOT / "E/staged_config/phase4-issue35-target13-pair-r3-noop/pair-plan.template.json":
        "61825a2e102864dcc09937d33b4f937e49f9ab77fc50f31fa3cef928c0dcb875",
    TASK_ROOT / "E/receipts/plan_canary_runs/20261013/execution-02/plan-canary.json":
        "4cfe936e7e52611544a95b6bccd692bb1cf47f823d3c5c91f0c9bbc09497ea63",
    TASK_ROOT / "E/staged_config/phase4-issue35-target13-enabled-r4b/activation-stage-receipt.json":
        "9cde2d4163ba7e88b8e14e249c508c1407a981b0640b91fac5ab34215d349363",
    TASK_ROOT / "E/receipts/phase4-issue35-target13/empty-lock-recovery/writer-preflight.json":
        "3e311bf4ebcdeff0a330eacf6ef8a9e334172a8927e2256a5880d2aa3c09ae7a",
    Path("/Users/lexi/Desktop/学习/v4_app/infrastructure/interprocess_lock.py"):
        "9b0cb80a1fe1bcbdebb3936134c8f0bad258c9c9236356022551ff7753351df0",
    Path("/Users/lexi/Desktop/学习/v4_app/infrastructure/owned_io.py"):
        "9a74731287ca7c9667643557d4ae42f63453a025665ba28f5b65fdbff7d54ee0",
    Path("/Users/lexi/Desktop/学习/v4_app/ops/api_release_integration.py"):
        "718dfd1ba18facfb4204e30c557a330bc3a6a45b1636a18ff95a76263e697c9c",
}

RENAME_EXCL = 0x00000004
KNOWN_WRITER_SCRIPT_MARKERS = (
    "issue35_phase4_pair_publication_adapter_r3_noop.py",
    "issue35_phase4_pair_publication_adapter_r2_final.py",
    "api_only_cutover_issue32_r4.py",
    "publish_daily_chain_source.py",
    "prepare_api_only_cutover.py",
)


class RecoveryBlocked(RuntimeError):
    """A fixed guard failed; no fallback or age-based recovery is permitted."""


class PreservationReceiptWriteError(RuntimeError):
    """The inode move completed, but its completion receipt could not be saved."""


class PreservationStateUncertain(RuntimeError):
    """A post-rename check failed; inspect both paths and never retry blindly."""


@dataclass(frozen=True)
class LockProfile:
    owner_path: Path
    target_path: Path
    mutex_path: Path
    owner_preimage: Dict[str, int]
    mutex_preimage: Dict[str, int]
    parent_preimage: Dict[str, int]
    live_plists: Dict[str, str]
    receipt_path: Path


PRODUCTION_PROFILE = LockProfile(
    owner_path=LOCK_PATH,
    target_path=QUARANTINE_PATH,
    mutex_path=MUTEX_PATH,
    owner_preimage=LOCK_PREIMAGE,
    mutex_preimage=MUTEX_PREIMAGE,
    parent_preimage=PARENT_PREIMAGE,
    live_plists=LIVE_PLIST_SHAS,
    receipt_path=OPERATION_RECEIPT,
)


def _stat_fields(meta: os.stat_result) -> Dict[str, int]:
    return {
        "dev": int(meta.st_dev),
        "ino": int(meta.st_ino),
        "mode": int(stat.S_IMODE(meta.st_mode)),
        "uid": int(meta.st_uid),
        "gid": int(meta.st_gid),
        "nlink": int(meta.st_nlink),
        "size": int(meta.st_size),
        "mtime_ns": int(meta.st_mtime_ns),
        "ctime_ns": int(meta.st_ctime_ns),
    }


def _open_directory(path: Path) -> int:
    """Open an absolute directory by components without following symlinks."""
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
        raise RecoveryBlocked("DIRECTORY_PATH_INVALID")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise RecoveryBlocked("NOFOLLOW_DIRECTORY_OPEN_UNAVAILABLE")
    fd = os.open("/", os.O_RDONLY | directory | nofollow)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except Exception:
        os.close(fd)
        raise


def _read_file_nofollow(path: Path, *, max_bytes: int = 128 * 1024 * 1024) -> Tuple[bytes, os.stat_result]:
    parent_fd = _open_directory(path.parent)
    try:
        fd = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise RecoveryBlocked("PINNED_INPUT_NOT_REGULAR")
            if before.st_size > max_bytes:
                raise RecoveryBlocked("PINNED_INPUT_TOO_LARGE")
            chunks = []
            remaining = max_bytes + 1
            while remaining:
                block = os.read(fd, min(1024 * 1024, remaining))
                if not block:
                    break
                chunks.append(block)
                remaining -= len(block)
            raw = b"".join(chunks)
            after = os.fstat(fd)
            if len(raw) > max_bytes:
                raise RecoveryBlocked("PINNED_INPUT_TOO_LARGE")
            if _stat_fields(before) != _stat_fields(after):
                raise RecoveryBlocked("PINNED_INPUT_CHANGED_DURING_READ")
            return raw, after
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _sha256_file(path: Path) -> str:
    raw, _ = _read_file_nofollow(path)
    return hashlib.sha256(raw).hexdigest()


def _assert_exact_file_sha(path: Path, expected_sha: str) -> None:
    actual = _sha256_file(path)
    if actual != expected_sha:
        raise RecoveryBlocked("PINNED_FILE_SHA_MISMATCH:" + str(path))


def _verify_static_evidence() -> Dict[str, str]:
    hashes = {}
    for path, expected in PINNED_FILES.items():
        _assert_exact_file_sha(path, expected)
        hashes[str(path)] = expected

    preimage_path = TASK_ROOT / "E/receipts/phase4-issue35-target13/shared-lock-empty-preimage.json"
    preimage = json.loads(_read_file_nofollow(preimage_path)[0].decode("utf-8"))
    if (
        preimage.get("path") != str(LOCK_PATH)
        or preimage.get("mutex_path") != str(MUTEX_PATH)
        or preimage.get("sha256") != hashlib.sha256(b"").hexdigest()
        or preimage.get("bytes") != 0
        or preimage.get("stat") != {
            "dev": LOCK_PREIMAGE["dev"],
            "ino": LOCK_PREIMAGE["ino"],
            "mode": LOCK_PREIMAGE["mode"],
            "uid": LOCK_PREIMAGE["uid"],
            "gid": LOCK_PREIMAGE["gid"],
            "mtime_ns": LOCK_PREIMAGE["mtime_ns"],
            "ctime_ns": LOCK_PREIMAGE["ctime_ns"],
        }
        or preimage.get("live_plist_sha256") != {
            "com.lexi.v35.api-only.plist": LIVE_PLIST_SHAS[str(API_PLIST)],
            "com.lexi.v35.scheduler.plist": LIVE_PLIST_SHAS[str(SCHEDULER_PLIST)],
        }
        or preimage.get("lsof") != {"returncode": 1, "stdout": "", "stderr": ""}
    ):
        raise RecoveryBlocked("LOCK_PREIMAGE_RECEIPT_MISMATCH")

    failed_command_path = TASK_ROOT / "E/receipts/phase4-issue35-target13/parent-pair-execute-command.json"
    failed_command = json.loads(_read_file_nofollow(failed_command_path)[0].decode("utf-8"))
    if failed_command.get("returncode") != 2 or failed_command.get("argv") != EXPECTED_FAILED_PAIR_ARGV:
        raise RecoveryBlocked("FAILED_PARENT_COMMAND_RECEIPT_MISMATCH")

    failed_stderr = TASK_ROOT / "E/receipts/phase4-issue35-target13/parent-pair-execute.stderr.txt"
    stderr_raw = _read_file_nofollow(failed_stderr)[0]
    if hashlib.sha256(stderr_raw).hexdigest() != "3cd7b31e325161bb1ba14a1ddbf6e366df4a7ab56ed0b230a4ef1b57037a46ac":
        raise RecoveryBlocked("FAILED_PARENT_ERROR_RECEIPT_MISMATCH")
    if json.loads(stderr_raw.decode("utf-8")).get("error") != "ValueError:API_RELEASE_SHARED_LOCK_BUSY":
        raise RecoveryBlocked("FAILED_PARENT_ERROR_NOT_LOCK_BUSY")

    pair_operation = TASK_ROOT / "E/receipts/phase4-issue35-target13/pair-execute-operation.json"
    try:
        parent_fd = _open_directory(pair_operation.parent)
        try:
            os.stat(pair_operation.name, dir_fd=parent_fd, follow_symlinks=False)
        finally:
            os.close(parent_fd)
    except FileNotFoundError:
        pass
    else:
        raise RecoveryBlocked("PAIR_OPERATION_RECEIPT_ALREADY_EXISTS")
    return hashes


def _stat_matches(meta: os.stat_result, expected: Dict[str, int], *, include_times: bool = True) -> bool:
    actual = _stat_fields(meta)
    fields = ("dev", "ino", "mode", "uid", "gid", "nlink", "size")
    if include_times:
        fields += ("mtime_ns", "ctime_ns")
    return all(actual.get(key) == expected.get(key) for key in fields)


def _assert_parent(meta: os.stat_result, expected: Dict[str, int]) -> None:
    actual = _stat_fields(meta)
    for key, value in expected.items():
        if actual.get(key) != value:
            raise RecoveryBlocked("LOCK_PARENT_IDENTITY_MISMATCH")
    if not stat.S_ISDIR(meta.st_mode):
        raise RecoveryBlocked("LOCK_PARENT_NOT_DIRECTORY")


def _stat_at(parent_fd: int, name: str) -> os.stat_result:
    return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)


def _read_open_fd(fd: int, max_bytes: int = 8192) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    blocks = []
    left = max_bytes + 1
    while left:
        block = os.read(fd, min(4096, left))
        if not block:
            break
        blocks.append(block)
        left -= len(block)
    raw = b"".join(blocks)
    if len(raw) > max_bytes:
        raise RecoveryBlocked("LOCK_OWNER_TOO_LARGE")
    return raw


def _check_live_plists(plists: Dict[str, str]) -> Dict[str, str]:
    observed = {}
    for path_text, expected in plists.items():
        path = Path(path_text)
        raw, meta = _read_file_nofollow(path, max_bytes=16 * 1024 * 1024)
        if not stat.S_ISREG(meta.st_mode):
            raise RecoveryBlocked("LIVE_PLIST_NOT_REGULAR")
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise RecoveryBlocked("LIVE_PLIST_PREIMAGE_MISMATCH:" + path_text)
        observed[path_text] = actual
    return observed


def _default_lsof_probe(path: Path, current_pid: int) -> Set[int]:
    result = subprocess.run(
        ["/usr/sbin/lsof", "-nP", "-t", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RecoveryBlocked("LSOF_UNAVAILABLE_OR_NO_SELF_HOLDER")
    pids = set()
    for line in result.stdout.splitlines():
        if not line.isdigit():
            raise RecoveryBlocked("LSOF_OUTPUT_UNPARSEABLE")
        pids.add(int(line))
    if current_pid not in pids:
        raise RecoveryBlocked("LSOF_DID_NOT_CONFIRM_HELPER_DESCRIPTOR")
    return pids


def _default_process_snapshot() -> List[str]:
    result = subprocess.run(
        ["/bin/ps", "-ww", "-axo", "pid=,command="],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RecoveryBlocked("PROCESS_TABLE_UNAVAILABLE")
    return result.stdout.splitlines()


def _active_writer_lines(lines: Iterable[str]) -> List[str]:
    blocked = []
    for line in lines:
        try:
            fields = shlex.split(line.strip())
        except ValueError:
            raise RecoveryBlocked("PROCESS_TABLE_OUTPUT_UNPARSEABLE")
        if not fields:
            continue
        argv = fields[1:] if fields[0].isdigit() else fields
        scripts = {Path(arg).name for arg in argv if arg.endswith(".py")}
        if scripts.intersection(KNOWN_WRITER_SCRIPT_MARKERS):
            blocked.append(line)
            continue
        for script in ("run_daily_chain_canary.py", "issue35_phase4_canary.py"):
            if script in scripts and "--execute" in argv:
                blocked.append(line)
                break
        if line in blocked:
            continue
        for script in ("prepare_daily_chain_activation.py", "issue35_phase4_prepare.py"):
            if script in scripts and "--stage-enabled" in argv:
                blocked.append(line)
                break
        if line in blocked:
            continue
    return blocked


def _rename_exclusive_same_directory(parent_fd: int, source_name: str, target_name: str) -> None:
    if sys.platform != "darwin":
        raise RecoveryBlocked("EXCLUSIVE_RENAME_PLATFORM_UNSUPPORTED")
    libc_name = ctypes.util.find_library("c")
    libc = ctypes.CDLL(libc_name or None, use_errno=True)
    try:
        renameatx_np = libc.renameatx_np
    except AttributeError:
        raise RecoveryBlocked("RENAMEATX_NP_UNAVAILABLE")
    renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameatx_np.restype = ctypes.c_int
    result = renameatx_np(
        parent_fd,
        os.fsencode(source_name),
        parent_fd,
        os.fsencode(target_name),
        RENAME_EXCL,
    )
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise RecoveryBlocked("QUARANTINE_DESTINATION_RACE")
        raise OSError(error, os.strerror(error), target_name)


def _write_json_exclusive_at(parent_fd: int, name: str, raw: bytes) -> str:
    try:
        fd = os.open(
            name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        try:
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise RecoveryBlocked("RECEIPT_WRITE_SHORT")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent_fd)
        return hashlib.sha256(raw).hexdigest()
    except FileExistsError:
        raise RecoveryBlocked("OPERATION_RECEIPT_ALREADY_EXISTS")


def preserve_exact_lock(
    profile: LockProfile,
    *,
    lsof_probe: Callable[[Path, int], Set[int]] = _default_lsof_probe,
    process_snapshot: Callable[[], Sequence[str]] = _default_process_snapshot,
    before_rename: Optional[Callable[[], None]] = None,
    rename_fn: Callable[[int, str, str], None] = _rename_exclusive_same_directory,
    pre_rename_guard: Optional[Callable[[], None]] = None,
    receipt_extra: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Preserve the exact pinned empty inode; parameterized for temp-only tests."""
    if profile.owner_path.parent != profile.target_path.parent or profile.owner_path.parent != profile.mutex_path.parent:
        raise RecoveryBlocked("LOCK_PATHS_NOT_SAME_PARENT")
    if profile.owner_path.name == profile.target_path.name:
        raise RecoveryBlocked("QUARANTINE_NAME_INVALID")

    parent_fd = _open_directory(profile.owner_path.parent)
    receipt_parent_fd = _open_directory(profile.receipt_path.parent)
    mutex_fd = owner_fd = -1
    renamed = False
    try:
        parent_before = os.fstat(parent_fd)
        _assert_parent(parent_before, profile.parent_preimage)
        receipt_parent_before = os.fstat(receipt_parent_fd)
        if not stat.S_ISDIR(receipt_parent_before.st_mode):
            raise RecoveryBlocked("OPERATION_RECEIPT_PARENT_NOT_DIRECTORY")

        # No O_CREAT: if the persistent canonical mutex disappeared, do not
        # silently create a second lock inode.
        mutex_fd = os.open(
            profile.mutex_path.name,
            os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        mutex_meta = os.fstat(mutex_fd)
        if not stat.S_ISREG(mutex_meta.st_mode) or not _stat_matches(mutex_meta, profile.mutex_preimage):
            raise RecoveryBlocked("CANONICAL_MUTEX_PREIMAGE_MISMATCH")
        try:
            fcntl.flock(mutex_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RecoveryBlocked("CANONICAL_MUTEX_BUSY")
        except OSError as exc:
            raise RecoveryBlocked("CANONICAL_MUTEX_LOCK_ERROR:" + str(exc.errno))

        if not _stat_matches(os.fstat(mutex_fd), profile.mutex_preimage):
            raise RecoveryBlocked("CANONICAL_MUTEX_CHANGED_AFTER_LOCK")
        mutex_path_meta = _stat_at(parent_fd, profile.mutex_path.name)
        if (mutex_path_meta.st_dev, mutex_path_meta.st_ino) != (mutex_meta.st_dev, mutex_meta.st_ino):
            raise RecoveryBlocked("CANONICAL_MUTEX_PATH_REPLACED")

        try:
            os.stat(profile.target_path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RecoveryBlocked("QUARANTINE_DESTINATION_OCCUPIED")

        try:
            os.stat(profile.receipt_path.name, dir_fd=receipt_parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RecoveryBlocked("OPERATION_RECEIPT_ALREADY_EXISTS")

        owner_fd = os.open(
            profile.owner_path.name,
            os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        owner_meta = os.fstat(owner_fd)
        if not stat.S_ISREG(owner_meta.st_mode) or not _stat_matches(owner_meta, profile.owner_preimage):
            raise RecoveryBlocked("LEGACY_OWNER_PREIMAGE_MISMATCH")
        try:
            fcntl.flock(owner_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RecoveryBlocked("LEGACY_OWNER_FLOCK_BUSY")
        except OSError as exc:
            raise RecoveryBlocked("LEGACY_OWNER_FLOCK_ERROR:" + str(exc.errno))
        if _read_open_fd(owner_fd) != b"":
            raise RecoveryBlocked("LEGACY_OWNER_NOT_EMPTY")
        if (owner_meta.st_dev, owner_meta.st_ino) != (LOCK_PREIMAGE["dev"], LOCK_PREIMAGE["ino"]) and (
            profile.owner_preimage == LOCK_PREIMAGE
        ):
            raise RecoveryBlocked("LEGACY_OWNER_INODE_MISMATCH")

        live_before = _check_live_plists(profile.live_plists)
        own_pid = os.getpid()
        open_pids = lsof_probe(profile.owner_path, own_pid)
        if open_pids != {own_pid}:
            raise RecoveryBlocked("LEGACY_OWNER_HAS_OTHER_OR_UNKNOWN_HOLDER")
        blocked = _active_writer_lines(process_snapshot())
        if blocked:
            raise RecoveryBlocked("ACTIVE_PUBLICATION_WRITER:" + blocked[0][:300])

        # Recheck each path against the held descriptors just before the
        # exclusive rename. flock serializes compliant API publishers; these
        # checks catch legacy holders, changed inputs, and path replacement.
        parent_now = os.fstat(parent_fd)
        _assert_parent(parent_now, profile.parent_preimage)
        if not _stat_matches(os.fstat(mutex_fd), profile.mutex_preimage):
            raise RecoveryBlocked("CANONICAL_MUTEX_CHANGED_BEFORE_RENAME")
        if (owner_meta.st_dev, owner_meta.st_ino) != (
            os.fstat(owner_fd).st_dev,
            os.fstat(owner_fd).st_ino,
        ):
            raise RecoveryBlocked("LEGACY_OWNER_DESCRIPTOR_CHANGED")
        if not _stat_matches(os.fstat(owner_fd), profile.owner_preimage):
            raise RecoveryBlocked("LEGACY_OWNER_CHANGED_BEFORE_RENAME")
        owner_path_meta = _stat_at(parent_fd, profile.owner_path.name)
        if (owner_path_meta.st_dev, owner_path_meta.st_ino) != (owner_meta.st_dev, owner_meta.st_ino):
            raise RecoveryBlocked("LEGACY_OWNER_PATH_REPLACED")
        if _read_open_fd(owner_fd) != b"":
            raise RecoveryBlocked("LEGACY_OWNER_CONTENT_CHANGED")
        live_after = _check_live_plists(profile.live_plists)
        if live_after != live_before:
            raise RecoveryBlocked("LIVE_PLIST_CHANGED_DURING_RECOVERY")
        current_parent_fd = _open_directory(profile.owner_path.parent)
        try:
            current_parent_meta = os.fstat(current_parent_fd)
            if (current_parent_meta.st_dev, current_parent_meta.st_ino) != (
                parent_before.st_dev,
                parent_before.st_ino,
            ):
                raise RecoveryBlocked("LOCK_PARENT_PATH_REPLACED")
        finally:
            os.close(current_parent_fd)
        current_receipt_parent_fd = _open_directory(profile.receipt_path.parent)
        try:
            current_receipt_parent = os.fstat(current_receipt_parent_fd)
            if (current_receipt_parent.st_dev, current_receipt_parent.st_ino) != (
                receipt_parent_before.st_dev,
                receipt_parent_before.st_ino,
            ):
                raise RecoveryBlocked("OPERATION_RECEIPT_PARENT_PATH_REPLACED")
        finally:
            os.close(current_receipt_parent_fd)
        mutex_path_meta = _stat_at(parent_fd, profile.mutex_path.name)
        if (mutex_path_meta.st_dev, mutex_path_meta.st_ino) != (mutex_meta.st_dev, mutex_meta.st_ino):
            raise RecoveryBlocked("CANONICAL_MUTEX_PATH_REPLACED")
        try:
            os.stat(profile.target_path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RecoveryBlocked("QUARANTINE_DESTINATION_OCCUPIED")

        if before_rename is not None:
            before_rename()
        if pre_rename_guard is not None:
            pre_rename_guard()
        # Repeat the namespace and mutable-preimage checks after the test
        # seam and immediately before the kernel's no-overwrite rename.
        final_parent_fd = _open_directory(profile.owner_path.parent)
        try:
            final_parent = os.fstat(final_parent_fd)
            if (final_parent.st_dev, final_parent.st_ino) != (parent_before.st_dev, parent_before.st_ino):
                raise RecoveryBlocked("LOCK_PARENT_PATH_REPLACED")
        finally:
            os.close(final_parent_fd)
        final_receipt_parent_fd = _open_directory(profile.receipt_path.parent)
        try:
            final_receipt_parent = os.fstat(final_receipt_parent_fd)
            if (final_receipt_parent.st_dev, final_receipt_parent.st_ino) != (
                receipt_parent_before.st_dev,
                receipt_parent_before.st_ino,
            ):
                raise RecoveryBlocked("OPERATION_RECEIPT_PARENT_PATH_REPLACED")
        finally:
            os.close(final_receipt_parent_fd)
        if not _stat_matches(os.fstat(mutex_fd), profile.mutex_preimage):
            raise RecoveryBlocked("CANONICAL_MUTEX_CHANGED_BEFORE_RENAME")
        if not _stat_matches(os.fstat(owner_fd), profile.owner_preimage):
            raise RecoveryBlocked("LEGACY_OWNER_CHANGED_BEFORE_RENAME")
        final_owner_path_meta = _stat_at(parent_fd, profile.owner_path.name)
        if (final_owner_path_meta.st_dev, final_owner_path_meta.st_ino) != (
            owner_meta.st_dev,
            owner_meta.st_ino,
        ):
            raise RecoveryBlocked("LEGACY_OWNER_PATH_REPLACED")
        final_mutex_path_meta = _stat_at(parent_fd, profile.mutex_path.name)
        if (final_mutex_path_meta.st_dev, final_mutex_path_meta.st_ino) != (
            mutex_meta.st_dev,
            mutex_meta.st_ino,
        ):
            raise RecoveryBlocked("CANONICAL_MUTEX_PATH_REPLACED")
        if _read_open_fd(owner_fd) != b"":
            raise RecoveryBlocked("LEGACY_OWNER_CONTENT_CHANGED")
        if _check_live_plists(profile.live_plists) != live_before:
            raise RecoveryBlocked("LIVE_PLIST_CHANGED_DURING_RECOVERY")
        try:
            os.stat(profile.target_path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RecoveryBlocked("QUARANTINE_DESTINATION_OCCUPIED")
        final_open_pids = lsof_probe(profile.owner_path, own_pid)
        if final_open_pids != {own_pid}:
            raise RecoveryBlocked("LEGACY_OWNER_HAS_OTHER_OR_UNKNOWN_HOLDER")
        final_blocked = _active_writer_lines(process_snapshot())
        if final_blocked:
            raise RecoveryBlocked("ACTIVE_PUBLICATION_WRITER:" + final_blocked[0][:300])
        rename_fn(parent_fd, profile.owner_path.name, profile.target_path.name)
        renamed = True
        # Check the moved name is still the exact open inode and preserve its
        # bytes, permissions and ownership. ctime is allowed to reflect rename.
        try:
            moved_meta = _stat_at(parent_fd, profile.target_path.name)
        except FileNotFoundError:
            raise RecoveryBlocked("QUARANTINE_TARGET_MISSING_AFTER_RENAME")
        if not stat.S_ISREG(moved_meta.st_mode):
            raise RecoveryBlocked("QUARANTINE_TARGET_NOT_REGULAR")
        moved_expected = dict(profile.owner_preimage)
        moved_expected.pop("ctime_ns", None)
        moved_stat = _stat_fields(moved_meta)
        if any(
            moved_stat.get(key) != moved_expected.get(key)
            for key in ("dev", "ino", "mode", "uid", "gid", "nlink", "size", "mtime_ns")
        ):
            raise RecoveryBlocked("QUARANTINE_TARGET_IDENTITY_CHANGED")
        if (moved_meta.st_dev, moved_meta.st_ino) != (owner_meta.st_dev, owner_meta.st_ino):
            raise RecoveryBlocked("QUARANTINE_TARGET_INODE_CHANGED")
        if _read_open_fd(owner_fd) != b"":
            raise RecoveryBlocked("QUARANTINE_TARGET_BYTES_CHANGED")
        try:
            os.stat(profile.owner_path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RecoveryBlocked("LEGACY_OWNER_PATH_REMAINS")
        final_parent_fd = _open_directory(profile.owner_path.parent)
        try:
            final_parent = os.fstat(final_parent_fd)
            if (final_parent.st_dev, final_parent.st_ino) != (parent_before.st_dev, parent_before.st_ino):
                raise RecoveryBlocked("LOCK_PARENT_PATH_REPLACED_AFTER_RENAME")
        finally:
            os.close(final_parent_fd)
        os.fsync(parent_fd)

        receipt: Dict[str, object] = {
            "schema_version": "issue35_manual_empty_lock_preservation.v1",
            "status": "PRESERVED_EXACT_EMPTY_LEGACY_OWNER_INODE",
            "owner_path": str(profile.owner_path),
            "quarantine_path": str(profile.target_path),
            "mutex_path": str(profile.mutex_path),
            "confirmation_token": CONFIRMATION if profile == PRODUCTION_PROFILE else "TEMP_TEST_ONLY",
            "before_owner_stat": _stat_fields(owner_meta),
            "after_quarantine_stat": _stat_fields(moved_meta),
            "owner_bytes_sha256": hashlib.sha256(b"").hexdigest(),
            "owner_bytes": 0,
            "live_plist_preimage_sha256": live_before,
            "open_holder_pids_while_helper_descriptor_open": sorted(open_pids),
            "final_open_holder_pids": sorted(final_open_pids),
            "active_publication_writer_lines": [],
            "canonical_mutex_nonblocking_flock": "PASS",
            "legacy_owner_nonblocking_flock": "PASS",
            "exclusive_same_parent_rename": "renameatx_np(RENAME_EXCL)",
            "directory_fsync": "PASS",
            "canonical_lock_protocol_changed": False,
            "owner_file_deleted": False,
            "started_by_writer": "issue35_manual_empty_lock_recovery.py",
        }
        if receipt_extra:
            receipt.update(receipt_extra)
        receipt["operation_receipt_path"] = str(profile.receipt_path)
        receipt_bytes = (json.dumps(receipt, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        try:
            receipt_sha = _write_json_exclusive_at(receipt_parent_fd, profile.receipt_path.name, receipt_bytes)
        except Exception as exc:
            raise PreservationReceiptWriteError(
                "PRESERVATION_ALREADY_OCCURRED_RECEIPT_WRITE_FAILED:" + type(exc).__name__
            )
        receipt["_operation_receipt_file_sha256"] = receipt_sha
        return receipt
    except PreservationReceiptWriteError:
        raise
    except Exception as exc:
        if renamed:
            raise PreservationStateUncertain(
                "PRESERVATION_RENAME_RETURNED_SUCCESS_POSTCHECK_FAILED_NO_RETRY:"
                + type(exc).__name__
                + ":"
                + str(exc)
            ) from exc
        raise
    finally:
        if owner_fd >= 0:
            try:
                fcntl.flock(owner_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(owner_fd)
        if mutex_fd >= 0:
            try:
                fcntl.flock(mutex_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(mutex_fd)
        os.close(receipt_parent_fd)
        os.close(parent_fd)


def _production_inspect() -> Dict[str, object]:
    if sys.platform != "darwin":
        raise RecoveryBlocked("MACOS_REQUIRED")
    if os.geteuid() != LOCK_PREIMAGE["uid"] or os.getegid() != LOCK_PREIMAGE["gid"]:
        raise RecoveryBlocked("EXPECTED_USER_OR_GROUP_MISMATCH")
    hashes = _verify_static_evidence()
    parent_fd = _open_directory(LOCK_PATH.parent)
    try:
        parent_meta = os.fstat(parent_fd)
        _assert_parent(parent_meta, PARENT_PREIMAGE)
        owner_meta = _stat_at(parent_fd, LOCK_PATH.name)
        mutex_meta = _stat_at(parent_fd, MUTEX_PATH.name)
        if not stat.S_ISREG(owner_meta.st_mode) or not _stat_matches(owner_meta, LOCK_PREIMAGE):
            raise RecoveryBlocked("LEGACY_OWNER_PREIMAGE_MISMATCH")
        if not stat.S_ISREG(mutex_meta.st_mode) or not _stat_matches(mutex_meta, MUTEX_PREIMAGE):
            raise RecoveryBlocked("CANONICAL_MUTEX_PREIMAGE_MISMATCH")
        owner_fd = os.open(LOCK_PATH.name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        try:
            if _read_open_fd(owner_fd) != b"":
                raise RecoveryBlocked("LEGACY_OWNER_NOT_EMPTY")
        finally:
            os.close(owner_fd)
        try:
            _stat_at(parent_fd, QUARANTINE_PATH.name)
        except FileNotFoundError:
            pass
        else:
            raise RecoveryBlocked("QUARANTINE_DESTINATION_OCCUPIED")
    finally:
        os.close(parent_fd)
    live = _check_live_plists(LIVE_PLIST_SHAS)
    return {
        "status": "READY_FOR_PARENT_OWNED_MANUAL_PRESERVATION_REVIEW",
        "lock_path": str(LOCK_PATH),
        "quarantine_path": str(QUARANTINE_PATH),
        "lock_preimage_sha256": hashlib.sha256(b"").hexdigest(),
        "lock_stat": _stat_fields(owner_meta),
        "mutex_stat": _stat_fields(mutex_meta),
        "live_plist_sha256": live,
        "pinned_evidence_sha256": hashes,
        "preservation_executed": False,
    }


def _production_preserve() -> Dict[str, object]:
    if sys.platform != "darwin":
        raise RecoveryBlocked("MACOS_REQUIRED")
    if os.geteuid() != LOCK_PREIMAGE["uid"] or os.getegid() != LOCK_PREIMAGE["gid"]:
        raise RecoveryBlocked("EXPECTED_USER_OR_GROUP_MISMATCH")
    evidence_hashes = _verify_static_evidence()
    # Pin dynamic preimages before entering the mutation core.
    _production_inspect()
    exact_argv = [
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python",
        "-B",
        str(Path(__file__)),
        "preserve",
        "--confirm",
        CONFIRMATION,
    ]
    return preserve_exact_lock(
        PRODUCTION_PROFILE,
        pre_rename_guard=_verify_static_evidence,
        receipt_extra={
            "pinned_evidence_sha256": evidence_hashes,
            "exact_parent_argv": exact_argv,
        },
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("inspect", "preserve"), default="inspect")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            if args.confirm is not None:
                raise RecoveryBlocked("INSPECT_DOES_NOT_ACCEPT_CONFIRMATION")
            result = _production_inspect()
        else:
            if args.confirm != CONFIRMATION:
                raise RecoveryBlocked("EXACT_CONFIRMATION_REQUIRED")
            result = _production_preserve()
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
        return 0
    except PreservationReceiptWriteError as exc:
        print(
            json.dumps(
                {
                    "status": "PRESERVATION_ALREADY_OCCURRED_RECEIPT_WRITE_FAILED_NO_RETRY",
                    "error": type(exc).__name__ + ":" + str(exc),
                    "inspect_owner_and_quarantine_paths_manually": True,
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3
    except PreservationStateUncertain as exc:
        print(
            json.dumps(
                {
                    "status": "PRESERVATION_STATE_UNCERTAIN_NO_RETRY",
                    "error": type(exc).__name__ + ":" + str(exc),
                    "inspect_owner_and_quarantine_paths_manually": True,
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 4
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED_NO_FALLBACK",
                    "error": type(exc).__name__ + ":" + str(exc),
                    "manual_review_required": True,
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
