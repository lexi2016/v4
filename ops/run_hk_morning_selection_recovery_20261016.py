"""Build four read-only HK morning observation projections from frozen selections.

The helper preserves each existing 10-row selection and writes a separate,
market-scoped SelectionStore backfill tree under a caller-supplied new output
directory. It never reruns a selector and refuses output inside live state.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


TRADE_DATE = "20261016"
MARKET = "HK_CONNECT"
ALGORITHM_ID = "V3_STAGE_SELECTION_V1"
ALGORITHM_SHA256 = "f2991c472b17742acfd3adb81458ff13826f99dfb7b8a223ad8d6a5dfbbd1a1e"
D1_POOL_SHA256 = "78646320d1140bb574b6aee66c9bd6b51f57ca0797fd96e4f2775e245a57efd8"
D1_SOURCE_SHA256 = "d80b386c9b503a7a5d3b6aa5acba9f6c92cc0912b653cffffe112dd515bb4501"
D1_CODE_SET_SHA256 = "6620030da48d806d7210e3c586420899204ec35ee71f52a99d5709dcf86ec427"
RECOVERY_CONTRACT = "HK_MORNING_SELECTION_REPROJECTION_R1"
SHANGHAI = ZoneInfo("Asia/Shanghai")

DEFAULT_STATE_ROOT = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.lexi.v4.local"
    / "state"
)
DEFAULT_SELECTION_ROOT = DEFAULT_STATE_ROOT / "stage" / "selection"
DEFAULT_RAW_ROOT = DEFAULT_STATE_ROOT / "stage" / "raw"
DEFAULT_CAPTURE_ROOT = DEFAULT_RAW_ROOT / ".futu_minute_captures" / TRADE_DATE
DEFAULT_D1_POOL = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.lexi.v35.local"
    / "state"
    / "data"
    / "preselection_pools"
    / TRADE_DATE
    / "hkconnect_d1_top100.json"
)


@dataclass(frozen=True)
class StagePin:
    stage_id: str
    cutoff_time: str
    backfill_run_id: str
    original_run_id: str
    original_artifact_id: str
    original_selection_artifact_sha256: str
    original_selection_manifest_sha256: str
    original_selection_receipt_sha256: str
    original_selection_manifest_canonical_sha256: str
    original_selection_receipt_canonical_sha256: str
    original_raw_artifact_sha256: str
    original_raw_run_id: str
    capture_sha256: str
    captured_at: str
    capture_row_count: int = 100_000
    raw_row_count: int = 100


STAGE_PINS: tuple[StagePin, ...] = (
    StagePin(
        stage_id="STAGE_0930_0935",
        cutoff_time="09:35:00",
        backfill_run_id="hk-morning-20261016-stage-0930-v1",
        original_run_id="run-e8a2024a09a9c2f5f2e94312",
        original_artifact_id="selection-e8a2024a09a9c2f5f2e94312",
        original_selection_artifact_sha256="64da4a35c08c0fd194b751d14ee681c4e192e64542054440d7b357166207d0e2",
        original_selection_manifest_sha256="54aac5fb2b2831237ed5c14d1f45f00b964ec4cc858f4bfe8e1aa42484b7fa24",
        original_selection_receipt_sha256="52fa36083252ad2d7aba2283955c4f25b85ab65af3aaebedbf06bbcfacfaf906",
        original_selection_manifest_canonical_sha256="831b93b360bd61e1bf65f9704844e5a32ef98f7af2e5bd12dd0494eaaa0fb85d",
        original_selection_receipt_canonical_sha256="5be67f93b87e7c262f5b840e7a51d343c341720ed277bc86b366c53823fb0792",
        original_raw_artifact_sha256="1c850296885d7516151ea658f81ef1afd3706047664005f3568de86a4acad777",
        original_raw_run_id="20261016-hk_connect_1min_stage_0930_0935-984f3a295bdb2417",
        capture_sha256="afc2307361ca7a6bd10a51b5f75ef3c57b353ef9bad14669da7f4eb7faf88450",
        captured_at="2026-10-16T09:36:10.835354+08:00",
    ),
    StagePin(
        stage_id="STAGE_0935_0940",
        cutoff_time="09:40:00",
        backfill_run_id="hk-morning-20261016-stage-0935-v1",
        original_run_id="run-ccc20f037cc139b83f8a3f7c",
        original_artifact_id="selection-ccc20f037cc139b83f8a3f7c",
        original_selection_artifact_sha256="ed05e2eb54592992be63aa9bb842e10443fa4c9b2bacda1d989bd52898f1a09b",
        original_selection_manifest_sha256="6086dd03a7dbc75b24390203fb7f35c1c3e07c65f2d7acf34aae021854d9304c",
        original_selection_receipt_sha256="f45788594e44a74c131ce6941035356154e66af055ba9491e9631d6c65f23c0e",
        original_selection_manifest_canonical_sha256="b9a099fb646ee9654f1200906cb2558e37bc7ba87ec40e6ab7e5cd25e6211b7c",
        original_selection_receipt_canonical_sha256="9d8444d33e119193521aab0d43901e8a181603d13f2433c750dda87d20602783",
        original_raw_artifact_sha256="a71b46e70063bfa2c9665eec341680cd88d6c9bc6bb358cb9966a999702ee26c",
        original_raw_run_id="20261016-hk_connect_1min_stage_0935_0940-d2b2130bc620bd62",
        capture_sha256="e35d17873ff5ac915f02e6fc8bbb2ad15cfdd613af2cc19d9e772ea590abd139",
        captured_at="2026-10-16T09:41:11.584264+08:00",
    ),
    StagePin(
        stage_id="STAGE_0940_0945",
        cutoff_time="09:45:00",
        backfill_run_id="hk-morning-20261016-stage-0940-v1",
        original_run_id="run-9f5dbc39a836451324721acf",
        original_artifact_id="selection-9f5dbc39a836451324721acf",
        original_selection_artifact_sha256="c4e4720a38ea2de6d2bb0b40ca6a0356289cab33825890f6329056567dedb950",
        original_selection_manifest_sha256="7efbafda8b9291e060a5b47773fba7fa253ff979385d379112977c92ff390050",
        original_selection_receipt_sha256="04c1db64ee75bc7c96b710c901577c8a78becc76bc54783bd677395bb19ac717",
        original_selection_manifest_canonical_sha256="d27bcf81f1622bb85a5033c01986688d98e38a3a6c82eda2a977a95fdaaf2d23",
        original_selection_receipt_canonical_sha256="e0564cc51f362e19f3de119c6c62376f37623e4773f6689321170df02e10c743",
        original_raw_artifact_sha256="6c273dcd40a7de66a10c523b9345171565d866c64c6c33b6c39c713ea7914655",
        original_raw_run_id="20261016-hk_connect_1min_stage_0940_0945-27998c3cd82d4aa7",
        capture_sha256="92c01a1ed5b2b8656c30849b6be32acd169f1fdfecd1158257bdab12e5fec548",
        captured_at="2026-10-16T09:46:10.473217+08:00",
    ),
    StagePin(
        stage_id="STAGE_0945_1030",
        cutoff_time="10:30:00",
        backfill_run_id="hk-morning-20261016-stage-0945-v1",
        original_run_id="run-181ddc8bd8047a502234b698",
        original_artifact_id="selection-181ddc8bd8047a502234b698",
        original_selection_artifact_sha256="0e8ecec964d6b9827dd07eba568c3c9318e3ee622abbd7801a6b50daa67c903b",
        original_selection_manifest_sha256="b1c55eac9c1f4feaf8dc0aac0b0e69da2cfbbcb71e8076f36a65d6879d4b0381",
        original_selection_receipt_sha256="5d9a868faf5ac8133e49c10e79374a3add7caec135fe6e74200b4e7e18008c84",
        original_selection_manifest_canonical_sha256="e3214b8e79cc32c249f7970cf2b221f6150c33c8df225bfe421a61454975593a",
        original_selection_receipt_canonical_sha256="b5af283cebd60428599247c2e3f5d954fae530b477e1be10e2d7f8e12beb0612",
        original_raw_artifact_sha256="c7e8bfcae1e969874e8291e58b7cbcebddd0ac1c9a38435257b45ccaed1ab794",
        original_raw_run_id="20261016-hk_connect_1min_stage_0945_1030-c760b373e31e95ad",
        capture_sha256="7e9bb43a1f8b089e29ff42f14d191c6ad722146ac74264092f63512c5a9628f9",
        captured_at="2026-10-16T10:31:08.122599+08:00",
    ),
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _evidence_values(items: Sequence[Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in items:
        if not isinstance(item, str):
            continue
        key, separator, value = item.partition("=")
        if separator:
            result.setdefault(key, []).append(value)
    return result


def _code_set_sha256(codes: Sequence[str]) -> str:
    return _sha256_bytes(_canonical_bytes(sorted(set(codes))))


def _stage_cutoff(pin: StagePin) -> datetime:
    return datetime.fromisoformat(f"2026-10-16T{pin.cutoff_time}+08:00").astimezone(SHANGHAI)


def _load_original_selection(selection_root: Path, pin: StagePin) -> tuple[dict[str, Any], dict[str, Any]]:
    from stage_center.selection import SelectionStore

    store = SelectionStore(selection_root)
    key = store._key(TRADE_DATE, pin.stage_id, MARKET)
    entry = store._latest().get("entries", {}).get(key)
    if not isinstance(entry, Mapping) or entry.get("run_id") != pin.original_run_id:
        raise ValueError(f"original selection latest identity changed for {pin.stage_id}")
    verified = store._verify_run(TRADE_DATE, pin.stage_id, MARKET, pin.original_run_id)
    if any(
        verified.get(field) != expected
        for field, expected in (
            ("run_id", pin.original_run_id),
            ("artifact_sha256", pin.original_selection_artifact_sha256),
        )
    ):
        raise ValueError(f"original selection run verification changed for {pin.stage_id}")
    if (
        entry.get("artifact_sha256") != verified.get("artifact_sha256")
        or entry.get("manifest_sha256") != pin.original_selection_manifest_canonical_sha256
        or entry.get("receipt_sha256") != pin.original_selection_receipt_canonical_sha256
        or verified.get("manifest_sha256") != pin.original_selection_manifest_canonical_sha256
        or verified.get("receipt_sha256") != pin.original_selection_receipt_canonical_sha256
    ):
        raise ValueError(f"original selection latest pointer mismatch for {pin.stage_id}")
    run_dir = store.runs_root / TRADE_DATE / store._role(pin.stage_id, MARKET) / pin.original_run_id
    if (
        _sha256_file(run_dir / "manifest.json") != pin.original_selection_manifest_sha256
        or _sha256_file(run_dir / "receipt.json") != pin.original_selection_receipt_sha256
    ):
        raise ValueError(f"original selection manifest or receipt file SHA changed for {pin.stage_id}")
    envelope = verified.get("envelope")
    if not isinstance(envelope, dict):
        raise ValueError(f"original selection envelope is unavailable for {pin.stage_id}")
    if envelope.get("artifact_id") != pin.original_artifact_id:
        raise ValueError(f"original selection artifact identity changed for {pin.stage_id}")
    rows = envelope.get("rows")
    if (
        envelope.get("trade_date") != TRADE_DATE
        or envelope.get("stage_id") != pin.stage_id
        or envelope.get("market") != MARKET
        or envelope.get("algorithm_id") != ALGORITHM_ID
        or envelope.get("algorithm_sha256") != ALGORITHM_SHA256
        or envelope.get("raw_artifact_sha256") != pin.original_raw_artifact_sha256
        or envelope.get("source_status") != "CANNOT_CONFIRM"
        or envelope.get("selection_status") != "PARTIAL_WITH_ROWS"
        or envelope.get("cannot_confirm") != ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
        or envelope.get("requested_rows") != 100
        or envelope.get("source_rows") != 100
        or envelope.get("selected_rows") != 10
        or envelope.get("missing_symbols") != []
        or not isinstance(rows, list)
        or len(rows) != 10
    ):
        raise ValueError(f"original selection semantics changed for {pin.stage_id}")
    seen_codes: set[str] = set()
    seen_ranks: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"original selection row is invalid for {pin.stage_id}")
        code = str(row.get("code") or "")
        rank = row.get("rank")
        if (
            not code
            or code in seen_codes
            or isinstance(rank, bool)
            or not isinstance(rank, int)
            or rank <= 0
            or rank in seen_ranks
            or row.get("formal_eligible") is not False
            or row.get("action_level") != "NO_BUY"
            or row.get("trade_status") not in {"NO_TRADE", "WATCH_ONLY"}
            or row.get("status") != row.get("trade_status")
            or row.get("source_mode") != "HK_CONNECT_FOUR_LANE"
        ):
            raise ValueError(f"original row safety/identity changed for {pin.stage_id}")
        seen_codes.add(code)
        seen_ranks.add(rank)
    original_evidence = envelope.get("source_evidence")
    if not isinstance(original_evidence, list) or any(not isinstance(item, str) for item in original_evidence):
        raise ValueError(f"original source evidence is invalid for {pin.stage_id}")
    values = _evidence_values(original_evidence)
    required_original_markers = {
        "futu_capture_sha256": pin.capture_sha256,
        "futu_captured_at": pin.captured_at,
        "active_snapshot_codes_sha256": D1_CODE_SET_SHA256,
        "active_snapshot_expected_pool_artifact_sha256": D1_POOL_SHA256,
        "hk_d1_sha256": D1_POOL_SHA256,
        "hk_d1_source_sha256": D1_SOURCE_SHA256,
    }
    if any(values.get(key) != [expected] for key, expected in required_original_markers.items()):
        raise ValueError(f"original source evidence pins changed for {pin.stage_id}")
    if "HK_ACTIVE_SNAPSHOT_UNAVAILABLE" not in original_evidence:
        raise ValueError(f"original failure reason disappeared for {pin.stage_id}")
    return envelope, verified


def _validate_d1_pool(d1_pool_path: Path, expected_codes: set[str]) -> dict[str, Any]:
    raw = d1_pool_path.read_bytes()
    if _sha256_bytes(raw) != D1_POOL_SHA256:
        raise ValueError("exact 2026-10-16 HK D1 Top100 file SHA changed")
    pool = json.loads(raw.decode("utf-8"))
    if (
        not isinstance(pool, dict)
        or pool.get("trade_date") != TRADE_DATE
        or pool.get("target_date") != TRADE_DATE
        or pool.get("signal_date") != "20261015"
        or pool.get("market") != "HK"
        or pool.get("pool_id") != "hkconnect_d1_top100"
        or pool.get("status") != "STRICT_0_2_READY"
        or pool.get("stage_selection_eligible") is not True
        or pool.get("source_row_count") != 100
        or pool.get("source_sha256") != D1_SOURCE_SHA256
        or pool.get("source_artifact_sha256") != D1_SOURCE_SHA256
    ):
        raise ValueError("exact 2026-10-16 HK D1 Top100 metadata changed")
    rows = pool.get("rows")
    if not isinstance(rows, list) or len(rows) != 100:
        raise ValueError("exact 2026-10-16 HK D1 Top100 rows changed")
    codes = [str(row.get("code_norm") or row.get("code") or "").upper() for row in rows if isinstance(row, dict)]
    if (
        len(codes) != 100
        or len(set(codes)) != 100
        or set(codes) != expected_codes
        or _code_set_sha256(codes) != D1_CODE_SET_SHA256
    ):
        raise ValueError("exact 2026-10-16 HK D1 Top100 code set changed")
    return {"sha256": D1_POOL_SHA256, "source_sha256": D1_SOURCE_SHA256, "code_set_sha256": D1_CODE_SET_SHA256}


def _raw_codes(raw_root: Path, pin: StagePin) -> dict[str, Any]:
    from stage_center.raw_store import RawStore

    raw_dir = (
        raw_root
        / "runs"
        / TRADE_DATE
        / f"HK_CONNECT_1MIN_{pin.stage_id}"
        / pin.original_raw_run_id
    )
    manifest_path = raw_dir / "manifest.json"
    receipt_path = raw_dir / "receipt.json"
    manifest = _read_json(manifest_path)
    receipt = _read_json(receipt_path)
    if (
        manifest.get("trade_date") != TRADE_DATE
        or manifest.get("stage_id") != pin.stage_id
        or manifest.get("market") != MARKET
        or manifest.get("run_id") != pin.original_raw_run_id
        or manifest.get("artifact_sha256") != pin.original_raw_artifact_sha256
        or manifest.get("source_rows") != pin.raw_row_count
        or manifest.get("requested_rows") != 100
        or manifest.get("source_status") != "READY"
        or receipt.get("manifest_sha256") != _sha256_bytes(_canonical_bytes(manifest))
        or receipt.get("artifact_sha256") != pin.original_raw_artifact_sha256
    ):
        raise ValueError(f"original raw artifact identity changed for {pin.stage_id}")
    artifact_relative = str(manifest.get("artifact_relative") or "")
    artifact_path = (raw_root / artifact_relative).resolve(strict=True)
    if raw_root.resolve(strict=True) not in artifact_path.parents or _sha256_file(artifact_path) != pin.original_raw_artifact_sha256:
        raise ValueError(f"original raw artifact bytes changed for {pin.stage_id}")
    codes: list[str] = []
    with artifact_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            codes.append(str(row.get("code") or "").strip().upper())
    if len(codes) != pin.raw_row_count or len(set(codes)) != pin.raw_row_count or any(not code for code in codes):
        raise ValueError(f"original raw artifact code list changed for {pin.stage_id}")
    checked = RawStore(raw_root).verify_run(TRADE_DATE, pin.stage_id, MARKET, pin.original_raw_run_id)
    if checked.get("artifact_sha256") != pin.original_raw_artifact_sha256:
        raise ValueError(f"RawStore verification changed for {pin.stage_id}")
    return {
        "codes": set(codes),
        "raw_run_id": pin.original_raw_run_id,
        "raw_manifest_sha256": _sha256_file(manifest_path),
        "raw_receipt_sha256": _sha256_file(receipt_path),
        "raw_artifact_sha256": pin.original_raw_artifact_sha256,
    }


def _validate_capture(capture_root: Path, pin: StagePin, expected_codes: set[str]) -> dict[str, Any]:
    capture_path = capture_root / pin.stage_id / f"{pin.capture_sha256}.json"
    if _sha256_file(capture_path) != pin.capture_sha256:
        raise ValueError(f"pinned Futu capture SHA changed for {pin.stage_id}")
    capture = _read_json(capture_path)
    codes = capture.get("codes")
    rows = capture.get("rows")
    if (
        capture.get("trade_date") != TRADE_DATE
        or capture.get("stage_id") != pin.stage_id
        or capture.get("market") != MARKET
        or capture.get("adjustment") != "NONE"
        or capture.get("captured_at") != pin.captured_at
        or capture.get("errors") != []
        or capture.get("no_data_codes") != []
        or not isinstance(codes, list)
        or len(codes) != 100
        or any(not isinstance(code, str) for code in codes)
        or len(set(codes)) != 100
        or set(codes) != expected_codes
        or _code_set_sha256(codes) != D1_CODE_SET_SHA256
        or not isinstance(rows, list)
        or len(rows) != pin.capture_row_count
    ):
        raise ValueError(f"pinned Futu capture content changed for {pin.stage_id}")
    captured_at = datetime.fromisoformat(pin.captured_at)
    if captured_at.tzinfo is None or captured_at.astimezone(SHANGHAI) <= _stage_cutoff(pin):
        raise ValueError(f"capture is not after the target stage cutoff for {pin.stage_id}")
    return {
        "capture_path": str(capture_path),
        "capture_sha256": pin.capture_sha256,
        "captured_at": pin.captured_at,
        "stage_cutoff_at": _stage_cutoff(pin).isoformat(),
        "capture_after_target_cutoff": True,
        "capture_row_count": len(rows),
        "code_set_sha256": D1_CODE_SET_SHA256,
    }


def _recovery_evidence(pin: StagePin, raw: Mapping[str, Any], capture: Mapping[str, Any]) -> list[str]:
    return [
        "recovery_mode=HISTORICAL_BACKFILL",
        "due_status=HISTORICAL_BACKFILL",
        "HISTORICAL_BACKFILL",
        "selection_mode=BACKFILL",
        "observation_status=OBSERVATION_UNVERIFIED",
        f"observation_contract={RECOVERY_CONTRACT}",
        "historical_capture_after_target_cutoff=true",
        "historical_temporal_cutoff_safe=false",
        "historical_formal_stage_eligibility=CANNOT_CONFIRM",
        "historical_natural_time_capture=CANNOT_CONFIRM",
        "historical_pit_safe=false",
        "historical_orderbook=CANNOT_CONFIRM",
        "recovery_original_failure=HK_ACTIVE_SNAPSHOT_UNAVAILABLE",
        f"recovery_original_selection_run_id={pin.original_run_id}",
        f"recovery_original_selection_artifact_sha256={pin.original_selection_artifact_sha256}",
        f"recovery_original_selection_manifest_sha256={pin.original_selection_manifest_sha256}",
        f"recovery_original_selection_receipt_sha256={pin.original_selection_receipt_sha256}",
        f"recovery_original_raw_artifact_sha256={pin.original_raw_artifact_sha256}",
        f"recovery_original_raw_run_id={raw['raw_run_id']}",
        f"recovery_original_raw_manifest_sha256={raw['raw_manifest_sha256']}",
        f"recovery_original_raw_receipt_sha256={raw['raw_receipt_sha256']}",
        f"recovery_futu_capture_sha256={pin.capture_sha256}",
        f"recovery_futu_captured_at={pin.captured_at}",
        f"recovery_stage_cutoff_at={capture['stage_cutoff_at']}",
        f"recovery_hk_d1_pool_sha256={D1_POOL_SHA256}",
        f"recovery_hk_d1_source_sha256={D1_SOURCE_SHA256}",
        f"recovery_hk_d1_code_set_sha256={D1_CODE_SET_SHA256}",
        "production_allowed=false",
        "buy_gate_updated=false",
        "orders_sent=false",
    ]


def _runner_receipt(pin: StagePin, envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "stage_center.runner.receipt.v1",
        "runner": "stage_center",
        "mode": "BACKFILL",
        "backfill_run_id": pin.backfill_run_id,
        "due_status": "HISTORICAL_BACKFILL",
        "trade_date": TRADE_DATE,
        "stage_id": pin.stage_id,
        "latest_updated": False,
        "current_updated": False,
        "write_performed": True,
        "markets": {
            MARKET: {
                "run_id": envelope["run_id"],
                "artifact_id": envelope["artifact_id"],
                "raw_artifact_sha256": envelope["raw_artifact_sha256"],
                "selection_status": envelope["selection_status"],
            }
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def build_recovery(
    *,
    output_root: Path,
    selection_root: Path = DEFAULT_SELECTION_ROOT,
    raw_root: Path = DEFAULT_RAW_ROOT,
    capture_root: Path = DEFAULT_CAPTURE_ROOT,
    d1_pool_path: Path = DEFAULT_D1_POOL,
    pins: Sequence[StagePin] = STAGE_PINS,
    active_state_root: Path = DEFAULT_STATE_ROOT,
) -> dict[str, Any]:
    """Write a verified, inactive observation backfill projection and receipt."""
    from stage_center.selection import SelectionStore

    output_root = output_root.expanduser().resolve(strict=False)
    selection_root = selection_root.expanduser().resolve(strict=True)
    raw_root = raw_root.expanduser().resolve(strict=True)
    capture_root = capture_root.expanduser().resolve(strict=True)
    d1_pool_path = d1_pool_path.expanduser().resolve(strict=True)
    active_state_root = active_state_root.expanduser().resolve(strict=False)
    if output_root.exists():
        raise ValueError("output_root must be a new directory")
    if output_root == active_state_root or active_state_root in output_root.parents:
        raise ValueError("recovery output cannot be inside active runtime state")
    for protected in (selection_root, raw_root, capture_root, d1_pool_path):
        if output_root == protected or output_root in protected.parents:
            raise ValueError("recovery output cannot contain or replace a pinned source")
    if len(pins) != 4 or {pin.stage_id for pin in pins} != {pin.stage_id for pin in STAGE_PINS}:
        raise ValueError("the frozen four-stage scope is required")

    # Validate every read-only source before creating any output bytes.
    inputs: list[dict[str, Any]] = []
    d1_codes: set[str] | None = None
    d1_validation: dict[str, Any] | None = None
    for pin in pins:
        original, original_verified = _load_original_selection(selection_root, pin)
        raw = _raw_codes(raw_root, pin)
        if d1_codes is None:
            d1_json = _read_json(d1_pool_path)
            d1_rows = d1_json.get("rows")
            if not isinstance(d1_rows, list):
                raise ValueError("exact HK D1 pool rows are unavailable")
            d1_codes = {
                str(row.get("code_norm") or row.get("code") or "").upper()
                for row in d1_rows
                if isinstance(row, dict)
            }
            d1_validation = _validate_d1_pool(d1_pool_path, d1_codes)
        if raw["codes"] != d1_codes:
            raise ValueError(f"original raw code set differs from frozen D1 pool for {pin.stage_id}")
        capture = _validate_capture(capture_root, pin, raw["codes"])
        inputs.append(
            {
                "pin": pin,
                "original": original,
                "original_verified": original_verified,
                "raw": raw,
                "capture": capture,
            }
        )

    output_root.mkdir(parents=True, exist_ok=False)
    result_stages: dict[str, Any] = {}
    for item in inputs:
        pin: StagePin = item["pin"]
        original: dict[str, Any] = item["original"]
        original_verified: dict[str, Any] = item["original_verified"]
        raw: dict[str, Any] = item["raw"]
        capture: dict[str, Any] = item["capture"]
        markers = _recovery_evidence(pin, raw, capture)
        evidence = list(dict.fromkeys([*original["source_evidence"], *markers]))
        envelope = {
            **original,
            # The existing selection rows, raw source, score, run identity,
            # timestamp fields, and original failure reason are copied as-is.
            "source_status": "CANNOT_CONFIRM",
            "selection_status": "PARTIAL_WITH_ROWS",
            "source_evidence": evidence,
            "cannot_confirm": list(original["cannot_confirm"]),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        selection_store_root = output_root / "selection" / "backfill" / pin.backfill_run_id
        published = SelectionStore(selection_store_root).publish(envelope, market=MARKET)
        if (
            published.get("run_id") != pin.original_run_id
            or published.get("artifact_id") != pin.original_artifact_id
            or published.get("raw_artifact_sha256") != pin.original_raw_artifact_sha256
        ):
            raise RuntimeError(f"recovery selection identity changed for {pin.stage_id}")
        store = SelectionStore(selection_store_root)
        verified = store._verify_run(TRADE_DATE, pin.stage_id, MARKET, pin.original_run_id)
        if verified.get("artifact_sha256") != pin.original_selection_artifact_sha256:
            raise RuntimeError(f"recovery changed immutable selection rows for {pin.stage_id}")
        if verified.get("envelope", {}).get("rows") != original.get("rows"):
            raise RuntimeError(f"recovery changed selection rows for {pin.stage_id}")

        runner_receipt_path = (
            output_root
            / "receipts"
            / "backfill"
            / pin.backfill_run_id
            / TRADE_DATE
            / pin.stage_id
            / "receipt.json"
        )
        runner_receipt = _runner_receipt(pin, published)
        _write_json(runner_receipt_path, runner_receipt)
        runner_receipt_sha256 = _sha256_file(runner_receipt_path)
        latest = store._latest().get("entries", {}).get(store._key(TRADE_DATE, pin.stage_id, MARKET))
        if not isinstance(latest, Mapping):
            raise RuntimeError(f"recovery SelectionStore latest pointer missing for {pin.stage_id}")

        required = list(markers)
        result_stages[pin.stage_id] = {
            "date": TRADE_DATE,
            "stage_id": pin.stage_id,
            "market": MARKET,
            "backfill_run_id": pin.backfill_run_id,
            "selection_run_id": published["run_id"],
            "artifact_id": published["artifact_id"],
            "raw_artifact_sha256": published["raw_artifact_sha256"],
            "algorithm_id": ALGORITHM_ID,
            "algorithm_sha256": ALGORITHM_SHA256,
            "selection_status": "PARTIAL_WITH_ROWS",
            "source_status": "CANNOT_CONFIRM",
            "selected_rows": 10,
            "source_rows": 100,
            "requested_rows": 100,
            "missing_rows": 0,
            "missing_codes": [],
            "cannot_confirm_count": len(envelope["cannot_confirm"]),
            "selection_manifest_sha256": latest["manifest_sha256"],
            "selection_receipt_sha256": latest["receipt_sha256"],
            "selection_artifact_sha256": latest["artifact_sha256"],
            "runner_receipt_sha256": runner_receipt_sha256,
            "source_evidence_sha256": _sha256_bytes("\n".join(evidence).encode("utf-8")),
            "required_evidence": required,
            "original": {
                **asdict(pin),
                "original_selection_identity_verified": True,
                "original_raw_identity_verified": True,
                "d1_pool": d1_validation,
                "capture": capture,
                "raw": {key: value for key, value in raw.items() if key != "codes"},
                "original_selection_manifest_file_sha256": pin.original_selection_manifest_sha256,
                "original_selection_receipt_file_sha256": pin.original_selection_receipt_sha256,
                "original_selection_manifest_canonical_sha256": original_verified["manifest_sha256"],
                "original_selection_receipt_canonical_sha256": original_verified["receipt_sha256"],
                "original_selection_artifact_sha256": original_verified["artifact_sha256"],
            },
        }

    receipt = {
        "schema_version": "hk_morning_selection_recovery.v1",
        "trade_date": TRADE_DATE,
        "market": MARKET,
        "status": "OBSERVATION_UNVERIFIED",
        "source_status": "CANNOT_CONFIRM",
        "selection_status": "PARTIAL_WITH_ROWS",
        "selected_rows_per_stage": 10,
        "stage_count": len(result_stages),
        "temporal_cutoff_safe": False,
        "formal_eligible": False,
        "natural_verified": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "selection_root": str(output_root / "selection"),
        "runner_receipt_root": str(output_root / "receipts"),
        "stages": result_stages,
    }
    receipt_path = output_root / "recovery_receipt.json"
    _write_json(receipt_path, receipt)
    receipt["recovery_receipt_sha256"] = _sha256_file(receipt_path)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--selection-root", type=Path, default=DEFAULT_SELECTION_ROOT)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--capture-root", type=Path, default=DEFAULT_CAPTURE_ROOT)
    parser.add_argument("--d1-pool", type=Path, default=DEFAULT_D1_POOL)
    args = parser.parse_args(argv)
    try:
        result = build_recovery(
            output_root=args.output_root,
            selection_root=args.selection_root,
            raw_root=args.raw_root,
            capture_root=args.capture_root,
            d1_pool_path=args.d1_pool,
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
