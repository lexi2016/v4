"""Immutable input bindings and durable exact-byte execution gates."""

import csv
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time_ns

from ops.pft_act080_core.core import FEATURE_NAMES


ROOT = Path(__file__).parent
METHOD_PATH = ROOT / "method.json"
METHOD = json.loads(METHOD_PATH.read_bytes())
CHARTER = "PFT_V4_ACT080_CHARTER_AND_PREREG_V1_0_20261127.md"
ADDENDUM = "PFT_V4_ACT080_P2_ADDENDUM_V1_0_20261127.md"
P1B = "ACT080_P1B_DETERMINISTIC_BASE_BUNDLE_20261127.zip"
EXCLUSIONS = "ACT080_P2_72CASE_OOT_EXCLUSION_MANIFEST.csv"
SIGNED = {
    CHARTER: "e5efc5c233569098867eaa563aed5aef4c3509779156447a3d495b2a42e55c65",
    ADDENDUM: "ae488a068d508987007ace578d0ffd9f4e897eec79be37bca48c271190e5b41f",
    EXCLUSIONS: "512e28cbf1a1c04eb2893b225f9dcb1e873ed48da5d19af6920690249307e590",
    P1B: "c9f59877448d716a4bba44e45ef0226fe913bd0a6651ae92a69634696efc6701",
}
POLICY = "ACT080_P2_CONTROLLER_PRE_REPLAY_LOCK.json"
POLICY_SHA = "1e6b76cf4199c7c62fc5aaf0b2f202876d784caf44c606292bd1eec1964203a8"
VOL2_SHA = "56b9799e839e7846313543a9ade387c083a6b7dcfc9a155031d861157b278034"
BASELINE_SHA = "2cda12c17c02abdfbff5555a53250510e28a8ef3de0e90f916d0adfc72f20d06"
BASELINE_MEMBER = "PFT_V4_ACT077A_UNIFIED_RADAR_V2_1_FROZEN_2020_2026.csv"
BASELINE_MEMBER_SHA = "222e92f99dd02899027d1e2909ef19acd9943ca0842e038e1746550b8f926132"
FEATURE_SETS = {
    "FEAT_BASE_19": FEATURE_NAMES,
    "FEAT_PLUS_ANCHOR_KB": FEATURE_NAMES + (
        "anchor_age_sessions", "anchor_breakout", "anchor_reversal", "anchor_violent", "anchor_funding_activity",
    ),
}
PREP_FILES = ("__init__.py", "contracts.py", "method.json", "outcomes.py", "prep.py", "sources.py")
JUNDA = METHOD["holdout_stock"]


def digest(path):
    with Path(path).open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def verify(path, expected):
    observed = digest(path)
    if observed != expected:
        raise ValueError(f"SHA-256 mismatch: {Path(path).name} {observed}")
    return observed


def verify_signed(run_root):
    return {name: verify(run_root / name, expected) for name, expected in {**SIGNED, POLICY: POLICY_SHA}.items()}


def source_inventory(prep_only=False):
    names = PREP_FILES if prep_only else sorted(
        path.name for path in ROOT.iterdir() if path.suffix == ".py" or path.name == METHOD_PATH.name
    )
    return {name: digest(ROOT / name) for name in names}


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_bytes(path, data):
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    sync_directory(path.parent)


def json_bytes(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def write_json(path, data):
    _replace_bytes(path, json_bytes(data))


def write_csv(path, rows, fields=None):
    rows = list(rows)
    if fields is None:
        fields = tuple(dict.fromkeys(key for row in rows for key in row))
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    if temporary.stat().st_size > 9_500_000:
        raise ValueError(f"CSV exceeds 9,500,000 bytes: {path.name}")
    temporary.replace(path)
    sync_directory(path.parent)


def read_json(path):
    return json.loads(Path(path).read_bytes())


def claim(path, **values):
    info = {"claimed_ns": time_ns(), "pid": os.getpid(), **values}
    with path.open("xb") as handle:
        handle.write(json_bytes(info))
        handle.flush()
        os.fsync(handle.fileno())
    sync_directory(path.parent)
    return info


def seal(path, payload, **metadata):
    entries = {name: digest(payload / name) for name in sorted(
        file.relative_to(payload).as_posix() for file in payload.rglob("*") if file.is_file()
    )}
    write_json(path, {"files": entries, **metadata})
    return digest(path)


def verify_payload(path, payload, expected=None):
    if expected is not None:
        verify(path, expected)
    locked = read_json(path)
    current = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
    if current != set(locked["files"]):
        raise ValueError(f"sealed payload membership mismatch in {payload.name}")
    for name, sha in locked["files"].items():
        verify(payload / name, sha)
    return locked
