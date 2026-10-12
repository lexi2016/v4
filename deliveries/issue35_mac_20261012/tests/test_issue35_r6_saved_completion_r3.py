"""Pure regressions for the authentic nested R4b receipt-pin preimage."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest


TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(TOOLS))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R2 = _load_module(
    "issue35_r6_saved_completion_r2_pure_regression",
    TOOLS / "phase6-r6/complete_issue35_r6_saved_canary_r2.py",
)
R3 = _load_module(
    "issue35_r6_saved_completion_r3_pure_regression",
    TOOLS / "phase6-r6/complete_issue35_r6_saved_canary_r3.py",
)
CANARY = R3.CANARY
COMMON = R3.common
PREIMAGE_PATH = R3.TASK_ROOT / R3.SOURCE_DIR_REL / "state-preimage.json"
PREIMAGE_SHA256 = "1f37c32b04a35821dcce645e580fd85f7c52b19ee749c9d41cfc50d9c0b0bfd9"
PREIMAGE_BYTES = 7146
REF_FIELDS = (
    "r4b_state_preimage_path", "r4b_state_preimage_sha256",
    "r4b_canary_path", "r4b_canary_sha256",
    "contract_review_path", "contract_review_sha256",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _authentic_preimage() -> dict[str, Any]:
    before = PREIMAGE_PATH.lstat()
    raw = PREIMAGE_PATH.read_bytes()
    after = PREIMAGE_PATH.lstat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    )
    assert len(raw) == PREIMAGE_BYTES
    assert _sha(raw) == PREIMAGE_SHA256
    value = json.loads(raw)
    assert isinstance(value, dict)
    return value


def _authoritative_receipt_pins(preimage: dict[str, Any]) -> dict[str, Any]:
    """Build the snapshot's comparison pins from the frozen R6 contract constants."""
    static = CANARY._R6_CURRENT13_ACCEPTANCE
    pins: dict[str, Any] = {
        key: (str(static[key]) if key.endswith("_path") else static[key])
        for key in REF_FIELDS
    }
    for path_key, sha_key in (
        ("r4b_state_preimage_path", "r4b_state_preimage_sha256"),
        ("r4b_canary_path", "r4b_canary_sha256"),
        ("contract_review_path", "contract_review_sha256"),
    ):
        raw = Path(pins[path_key]).read_bytes()
        assert _sha(raw) == pins[sha_key]
    pins["archived"] = static["archived"]
    pins["current"] = static["current"]
    # The snapshot function validates the map's exact key set and equality.
    # This is immutable preimage data; no live manager state is read here.
    pins["protected_dates_sha256"] = preimage["protected_dates_sha256"]
    return pins


def _snapshot(preimage: dict[str, Any]) -> dict[str, Any]:
    return R3._r4b_state_snapshot(
        preimage, _authoritative_receipt_pins(preimage),
        Path(R3.PINS["state_root"]), R3.PINS,
    )


def test_authentic_preimage_reproduces_r2_rejection_and_r3_acceptance():
    preimage = _authentic_preimage()
    assert "r4b_two_generation_receipt_pins" not in preimage
    prior = preimage["prior_target_owner_state"]
    assert isinstance(prior, dict)
    nested = prior["r4b_two_generation_receipt_pins"]
    assert tuple(sorted(nested)) == tuple(sorted(REF_FIELDS))

    static = CANARY._R6_CURRENT13_ACCEPTANCE
    expected_refs = {
        key: (str(static[key]) if key.endswith("_path") else static[key])
        for key in REF_FIELDS
    }
    assert nested == expected_refs

    with pytest.raises(ValueError, match="R6_SAVED_PREIMAGE_R4B_RECEIPT_PINS_MISMATCH"):
        R2._r4b_state_snapshot(
            preimage, _authoritative_receipt_pins(preimage),
            Path(R2.PINS["state_root"]), R2.PINS,
        )

    snapshot = _snapshot(preimage)
    assert snapshot["r4b_two_generation_receipt_pins"] == nested


@pytest.mark.parametrize("field", REF_FIELDS)
@pytest.mark.parametrize("mutation", ("missing", "mismatch"))
def test_each_nested_static_reference_field_rejects_missing_or_changed(field: str, mutation: str):
    preimage = copy.deepcopy(_authentic_preimage())
    nested = preimage["prior_target_owner_state"]["r4b_two_generation_receipt_pins"]
    if mutation == "missing":
        del nested[field]
    else:
        nested[field] = "f" * 64 if field.endswith("_sha256") else nested[field] + ".changed"
    with pytest.raises(ValueError, match="R6_SAVED_PREIMAGE_R4B_RECEIPT_PINS_MISMATCH"):
        _snapshot(preimage)


def test_canary_record_serializes_the_authentic_nested_r4b_receipt_pins():
    preimage = _authentic_preimage()
    nested = preimage["prior_target_owner_state"]["r4b_two_generation_receipt_pins"]
    attempt = {
        "run_id": R3.PINS["fresh"]["run_id"],
        "sha256": R3.PINS["fresh"]["attempt_sha256"],
        "state": R3.PINS["fresh"]["state"],
        "owner": COMMON.OWNER,
        "execution_kind": "MANUAL_REFRESH",
        "input_identity": R3.PINS["fresh"]["input_identity"],
        "finished_at": "2026-10-12T06:03:14.195417+08:00",
    }
    release = {
        "app_root": R3.PINS["app_root"],
        "owner_inventory_sha256": R3.PINS["owner_source_inventory_sha256"],
        "manifest_path": R3.TASK_ROOT / "integrated_release" / R3.RELEASE_ID / "release-manifest.json",
        "manifest": {"candidate": {"release_id": R3.RELEASE_ID}},
        "manifest_sha256": R3.PINS["release_manifest_sha256"],
        "application_inventory_sha256": R3.PINS["application_inventory_sha256"],
        "binding_files": {},
    }
    raw_ref = {
        "method": "GET", "url": "https://example.invalid/fixture",
        "response_path": "/fixture/readback.response.bin",
        "response_sha256": "a" * 64, "response_bytes": 1,
        "evidence_path": "/fixture/readback.http-evidence.json",
        "evidence_sha256": "b" * 64, "evidence_bytes": 2,
    }
    verified = {
        "release": release,
        "attempt": attempt,
        "source_preimage": preimage,
        "state_check": {"expected_durable_paths": ["synthetic-path"]},
        "refresh_raw_ref": {**raw_ref, "method": "POST"},
        "readback_raw_ref": raw_ref,
        "failure_sha256": "c" * 64,
        "source_preimage_sha256": PREIMAGE_SHA256,
        "source_dir": R3.TASK_ROOT / R3.SOURCE_DIR_REL,
        "state_root": Path(R3.PINS["state_root"]),
        "current_clock_local": "2026-10-12T06:20:00+08:00",
        "run_id": attempt["run_id"],
        "product_sha256": R3.PINS["fresh"]["product_sha256"],
        "input_identity": attempt["input_identity"],
        "attempt_state": attempt["state"],
        "timestamp_proof": {},
    }
    record = R3._canary_record(verified, Path("/unused"), {}, R3.PINS)
    serialized = json.loads(R3._json_bytes(record))
    assert serialized["state_preimage"]["r4b_receipt_pins"] == nested
    assert serialized["state_preimage"]["two_generation_state_files"] == (
        preimage["prior_target_owner_state"]["files"]
    )


def test_r3_source_pin_and_base_r2_source_are_exact():
    r2_path = TOOLS / "phase6-r6/complete_issue35_r6_saved_canary_r2.py"
    assert _sha(r2_path.read_bytes()) == (
        "048fc95accfc64a15976471ecc4628afba413937d08d435046057368e25d0d5c"
    )
    R3._verify_source_pins()
