"""Frozen ACT-072M execution, filesystem and model identities."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import os
import re
import sys
from pathlib import Path

from research.act070a.case_contract import case_digest, ensure_no_later_date, iso_day, json_bytes, require, strict_json

MODEL_ID = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit"
MODEL_REVISION = "46d4cf06a06ffc1a766c214174f9cbed2f45bcab"
WEIGHT_SHA256 = "636982419c940321ac0f7793dc9dc3575a4ee4843a6b167b2e8c3d3cd25dacf4"
WEIGHT_BYTES = 3073720461
SOURCE_ZIP_SHA256 = "1f0377b952ee951e4337ba6878c8dafac9c94ab232ed9d434e4cf411e28dcd86"
PROMPT_SHA256 = "f313ba13080ed6301776b8b68bd0cdccd153e0745443428cdf960db752496bad"
PROMPT_NAME = "FROZEN_PROMPT_ACT072S_V1_1.txt"
INPUT_LOCK_NAME = "FROZEN_INPUT_ACCESS_RECEIPT.json"
MODEL_RECEIPT_NAME = "MODEL_ASSET_RECEIPT.json"
RUNTIME_VERSION = "0.8.1"
MAX_TOKENS = 6144
SEED = 720
TEMPERATURE = 0
ATTACHMENTS = ("chart.png", "input.json", "act071a_b_output_schema_v1_1.json", "kb_rule_cards_v1_1.json")
SAFE_GUARDS = {"RESEARCH_ONLY": True, "S_FIT": 0, "B_FIT": 0, "PRODUCTION_ALLOWED": False}
CASE_ID_PATTERN = re.compile(r"T0[1-8]")
SAFE_EXECUTABLE = Path("/usr/bin/sandbox-exec")


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_object(path: Path) -> dict:
    data = strict_json(path.read_bytes())
    require(isinstance(data, dict), "INVALID_INPUT_LOCK", path.name)
    return data


def write_object(path: Path, data: dict) -> None:
    with path.open("xb") as stream:
        stream.write(json_bytes(data) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def regular_local(path: Path) -> Path:
    require(path.is_absolute() and path.resolve(strict=True) == path and path.is_file(),
            "NONLOCAL_OR_NONREGULAR_FILE", path.name)
    return path


def check_runtime(stage: Path) -> Path:
    require(stage.is_absolute() and stage.resolve(strict=True) == stage and stage.is_dir()
            and stage.name == "ACT072M_20261128", "INVALID_STAGE", str(stage))
    runtime = stage / ".venv" / "bin" / "python"
    require(sys.platform == "darwin" and Path(sys.executable).absolute() == runtime,
            "INCORRECT_RUNTIME", str(runtime))
    try:
        version = importlib.metadata.version("mlx-vlm")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError("frozen mlx-vlm runtime is not installed") from exc
    require(SAFE_EXECUTABLE.is_file() and version == RUNTIME_VERSION,
            "INCORRECT_RUNTIME", f"mlx-vlm=={RUNTIME_VERSION} and Apple sandbox-exec")
    return runtime


def check_model(stage: Path) -> tuple[Path, dict]:
    model = stage / ".local_model" / MODEL_REVISION
    require(model.is_dir() and model.resolve(strict=True) == model, "MODEL_NOT_LOCAL", str(model))
    files = sorted(model.iterdir())
    require(all(path.is_file() and path.resolve(strict=True) == path and path.suffix != ".py" for path in files),
            "UNFROZEN_MODEL_TREE", str(model))
    weights = model / "model.safetensors"
    actual_weights = [path for path in files if path.suffix in {".safetensors", ".npz", ".bin", ".pt", ".pth"}]
    require(actual_weights == [weights], "UNFROZEN_MODEL_TREE", "exactly the frozen safetensors")
    receipt_path = regular_local(stage / MODEL_RECEIPT_NAME)
    receipt_raw = receipt_path.read_bytes()
    receipt = strict_json(receipt_raw)
    require(isinstance(receipt, dict) and receipt.get("status") == "VERIFIED_DOWNLOAD"
            and receipt.get("model_id") == MODEL_ID and receipt.get("revision") == MODEL_REVISION
            and receipt.get("weights_sha256") == WEIGHT_SHA256 and receipt.get("local_model_path") == str(model)
            and receipt.get("network_inference_calls") == 0,
            "MODEL_RECEIPT_IDENTITY_MISMATCH", receipt_path.name)
    locked = receipt["files"]
    require(isinstance(locked, list) and all(isinstance(row, dict) for row in locked),
            "INVALID_MODEL_ASSET_MANIFEST", receipt_path.name)
    manifest_raw = json.dumps(locked, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    require(manifest_sha == receipt["manifest_sha256"] and [row["file"] for row in locked] == [path.name for path in files],
            "INVALID_MODEL_ASSET_MANIFEST", "asset SHA or exact sorted manifest names")
    for path, row in zip(files, locked, strict=True):
        require(row.get("publisher_sha_match") is True and type(row.get("bytes")) is int
                and path.stat().st_size == row["bytes"] and file_sha256(path) == row["sha256"],
                "MODEL_ASSET_HASH_MISMATCH", path.name)
    by_name = {row["file"]: row for row in locked}
    require(by_name[weights.name]["sha256"] == WEIGHT_SHA256 and by_name[weights.name]["bytes"] == WEIGHT_BYTES,
            "MODEL_WEIGHT_HASH_MISMATCH", weights.name)
    metadata_hashes = {name: row["sha256"] for name, row in by_name.items() if name != weights.name}
    for name in ("config.json", "tokenizer_config.json", "preprocessor_config.json"):
        require(name in metadata_hashes, "MODEL_METADATA_MISSING", name)
    return model, {"id": MODEL_ID, "revision": MODEL_REVISION, "weights_sha256": WEIGHT_SHA256,
                   "weights_bytes": WEIGHT_BYTES, "metadata_sha256": metadata_hashes,
                   "download_receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(), "asset_manifest_sha256": manifest_sha}


def check_case(stage: Path, case_dir: Path, input_lock: Path) -> dict:
    case_id = case_dir.name
    require(CASE_ID_PATTERN.fullmatch(case_id) and case_dir == stage / "frozen_A_case_inputs" / case_id
            and case_dir.resolve(strict=True) == case_dir, "UNAPPROVED_CASE_PATH", str(case_dir))
    require(input_lock == stage / INPUT_LOCK_NAME, "UNAPPROVED_INPUT_LOCK", str(input_lock))
    lock = read_object(regular_local(input_lock))
    require(lock.get("source_zip_sha256") == SOURCE_ZIP_SHA256
            and lock.get("historical_atlas_or_forward_source_opens") == 0,
            "UNAPPROVED_INPUT_LOCK", "ACT071B ZIP identity or safe input receipt")
    entry = lock["cases"][case_id]
    hashes = {}
    for name in ATTACHMENTS:
        path = regular_local(case_dir / name)
        hashes[name] = file_sha256(path)
        require(hashes[name] == entry["file_sha256"][name], "FROZEN_ATTACHMENT_HASH_MISMATCH", path.name)
    case = read_object(case_dir / "input.json")
    require(case["case_id"] == case_id and case["d"] == entry["d"] and case["scope"] == "FIRST_TEST"
            and case["schema_version"] == "ACT070A_CASE_INPUT_V1_1"
            and case["input_sha256"] == case_digest(case) == entry["input_sha256"],
            "FROZEN_CASE_IDENTITY_MISMATCH", case_id)
    require(case["chart"]["png"]["sha256"] == hashes["chart.png"]
            and case["schema_sha256"] == hashes[ATTACHMENTS[2]] and case["kb_sha256"] == hashes[ATTACHMENTS[3]],
            "FROZEN_CASE_IDENTITY_MISMATCH", "case binding to PNG, schema or KB")
    cutoff = iso_day(case["d"])
    require(iso_day(entry["max_reference_date"]) <= cutoff, "OUT_OF_D_REFERENCE", case_id)
    ensure_no_later_date(case, cutoff, case_id)
    prompt = regular_local(stage / PROMPT_NAME)
    require(file_sha256(prompt) == PROMPT_SHA256, "FROZEN_PROMPT_HASH_MISMATCH", prompt.name)
    return {"case_id": case_id, "d": case["d"], "input_sha256": case["input_sha256"],
            "attachment_sha256": hashes, "prompt_sha256": PROMPT_SHA256,
            "source_zip_sha256": SOURCE_ZIP_SHA256, "case_dir": str(case_dir), "prompt": str(prompt)}


def _filter(kind: str, path: Path) -> str:
    return f"({kind} {json.dumps(str(path), ensure_ascii=False)})"


def sandbox_profile(stage: Path, result_dir: Path, model_dir: Path, case: dict | None) -> str:
    """Preserve access to frameworks while excluding all other research artifact data."""
    allowed = [
        _filter("subpath", path) for path in (stage / ".venv", model_dir, result_dir)
    ]
    allowed.extend(_filter("literal", path) for path in (stage.parent, stage, model_dir.parent, result_dir.parent))
    if case:
        case_dir = Path(case["case_dir"])
        allowed.extend(_filter("literal", path) for path in (case_dir, case_dir.parent, Path(case["prompt"])))
        allowed.extend(_filter("literal", case_dir / name) for name in ATTACHMENTS)
    under_artifacts = _filter("subpath", stage.parent)
    write_root, write_result = _filter("subpath", stage.parent.parent), _filter("subpath", result_dir)
    exceptions = f"(require-any {' '.join(allowed)})"
    return (f"(version 1) (allow default) (deny network*) "
            f"(deny file-read* (require-all {under_artifacts} (require-not {exceptions}))) "
            f"(deny file-write* (require-all {write_root} (require-not {write_result})))")


def prove_network_denial() -> dict:
    checker = ctypes.CDLL(None).sandbox_check
    checker.restype = ctypes.c_int
    statuses = {name: checker(os.getpid(), name.encode("ascii"), 0) for name in ("network-outbound", "network-inbound")}
    require(all(value == 1 for value in statuses.values()), "NETWORK_SANDBOX_NOT_ENFORCED", str(statuses))
    return statuses
