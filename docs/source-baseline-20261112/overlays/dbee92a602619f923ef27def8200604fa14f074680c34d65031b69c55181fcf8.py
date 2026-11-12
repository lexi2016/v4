"""Date-scoped recovery from independently approved immutable original trios.

These are source-byte identities from the independently supplied local evidence,
NOT hashes asserted by a caller or evidence of historical algorithm equivalence.
There is deliberately no latest lookup, current bundle oracle, or generic import.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Mapping
from infrastructure.data_store import _canonical_bytes
from infrastructure.owned_io import SafeRoot

FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
SIGNAL, TARGET = "20260917", "20260918"
APPROVED = {
    "stage7": {
        "run_id": "20260917-a_share_1min_stage_1445_1500-6adb6908c89a5f29",
        "role": "A_SHARE_1MIN_STAGE_1445_1500", "trade_date": SIGNAL, "row_count": 185,
        "artifact.csv": "96a93eea934f4545f21943e559c9c5f120202d9c7fab11148facd4728b71fffb",
        "manifest.json": "7dfd71eb27837d51b95de7e080874662b1ca03348cddf62aeecc877cb91b6e9f",
        "receipt.json": "2f5703bd994870adc84736029430a76e4555745863aeeb76a5a09547bd292469",
    },
    "v192": {
        "run_id": "20260918-a-share-v192-premarket-pool-v3-2716d626c4e8",
        "role": "A_SHARE_V192_PREMARKET_POOL_V3", "trade_date": TARGET, "row_count": 91,
        "artifact.csv": "8f3edb703b7ebb58144259dfc5d30466e1a3d7239afc2173d47a9a8dc3d88c22",
        "manifest.json": "441a2b82f523a31d80d70e60812cb3f6a3c279bf0f6ac149ca1e46722bda1a9b",
        "receipt.json": "7bda77d140c0ad9b6db983677417cd6d8ef316feec866343c39b0b80ef4acd5f",
    },
}
FILES = ("artifact.csv", "manifest.json", "receipt.json")
MISSING = ["SZ.920275", "SZ.920699", "SZ.920045", "SZ.920438"]

# Date scope is source authority, not a weekday heuristic. Unknown dates need a
# separately reviewed source identity; self-hashing a caller CSV never admits it.
PREVIOUS_TRADING_DAY = {"20260915": "20260914", "20260916": "20260915", "20260917": "20260916",
                        "20260918": "20260917", "20260921": "20260918"}
APPROVED_BY_TARGET = {'20260916': {'stage7': {'run_id': '20260915-a_share_1min_stage_1445_1500-f78b645b4baf2738',
                         'role': 'A_SHARE_1MIN_STAGE_1445_1500',
                         'trade_date': '20260915',
                         'row_count': 209,
                         'artifact.csv': '4be2063235b6e74c29df84c7a06558684c5e81cc1451f5810b810e4baed81263',
                         'manifest.json': '3368658ab2363fff533bc7d49449ca13cb41066b8beeca325323c1275abeeb56',
                         'receipt.json': 'ab7e1c651a6e3f4a5e01ad2eedf6d6c7b4ea61985fa07480d60772a6d66d292b',
                         'requested_rows': 213,
                         'missing_symbols': ['SZ.920030', 'SZ.920275', 'SZ.920725', 'SZ.920058'],
                         'raw_status': 'PARTIAL_WITH_ROWS',
                         'original_temporal_cutoff_safe': False},
              'v192': {'run_id': '20260916-a-share-v192-premarket-pool-v3-acc26ecfee67',
                       'role': 'A_SHARE_V192_PREMARKET_POOL_V3',
                       'trade_date': '20260916',
                       'row_count': 20,
                       'artifact.csv': '407dcf94a8d7bd0391ff5bd4a89e888765a48a7635684b0d401fac72e8b52711',
                       'manifest.json': 'bb6064ba812b5ae631b087401a4a9ec76c6cd09f36db9e28947dd47f6f9c1722',
                       'receipt.json': 'a3594a1ff0c1fcf5c56f80da20a534ced45a285ecc866748f7da4d7c807bf8cb'}},
 '20260917': {'stage7': {'run_id': '20260916-a_share_1min_stage_1445_1500-f375afb1b0292c1e',
                         'role': 'A_SHARE_1MIN_STAGE_1445_1500',
                         'trade_date': '20260916',
                         'row_count': 53,
                         'artifact.csv': '90da0cde214a2a2af871d8b5adbbb24f623a7f45de1934b06df882f0ec6e421b',
                         'manifest.json': '139a4c46371bf6491787ee7b1d676b629f4246da2104e7b9d32075ba45505d0c',
                         'receipt.json': '61ac3be4e37194e79a9bcc3a4df14d15554e38b4d42493aa5682ab69853d6373',
                         'requested_rows': 54,
                         'missing_symbols': ['SZ.920125'],
                         'raw_status': 'PARTIAL_WITH_ROWS',
                         'original_temporal_cutoff_safe': False},
              'v192': {'run_id': '20260917-a-share-v192-premarket-pool-v3-a25430b0c6c2',
                       'role': 'A_SHARE_V192_PREMARKET_POOL_V3',
                       'trade_date': '20260917',
                       'row_count': 103,
                       'artifact.csv': 'ad27ee7be7e920ee5eef8e301a0632d12ddd5ca2e838f8caa2bc03fd082e40d7',
                       'manifest.json': '3461dd0583f5847ae784ae3e9fef56e78236b1dd43414bd3b181165c3ea6d398',
                       'receipt.json': 'c583b6c3782df28fddad1e7509aec2a8896a4bc777068e563430b9636403f892'}},
 '20260918': {'stage7': {'run_id': '20260917-a_share_1min_stage_1445_1500-6adb6908c89a5f29',
                         'role': 'A_SHARE_1MIN_STAGE_1445_1500',
                         'trade_date': '20260917',
                         'row_count': 185,
                         'artifact.csv': '96a93eea934f4545f21943e559c9c5f120202d9c7fab11148facd4728b71fffb',
                         'manifest.json': '7dfd71eb27837d51b95de7e080874662b1ca03348cddf62aeecc877cb91b6e9f',
                         'receipt.json': '2f5703bd994870adc84736029430a76e4555745863aeeb76a5a09547bd292469',
                         'requested_rows': 189,
                         'missing_symbols': ['SZ.920275', 'SZ.920699', 'SZ.920045', 'SZ.920438'],
                         'raw_status': 'PARTIAL_WITH_ROWS',
                         'original_temporal_cutoff_safe': False}},
 '20260921': {'stage7': {'run_id': '20260918-a_share_1min_stage_1445_1500-475d1009f7a669c3',
                         'role': 'A_SHARE_1MIN_STAGE_1445_1500',
                         'trade_date': '20260918',
                         'row_count': 206,
                         'artifact.csv': '1e6c7e3c0b82b408a516155ed0fd37e4824d2bc2c104205a4d17edcd2d665a93',
                         'manifest.json': '13ee26029fd2693d53383de7c2a711c269060a30db764ce7d367f3efe4767431',
                         'receipt.json': '1e5750cb53cdc636f914ac0d05c75d0ada5c3275164d84bbfabae0c34bdb50da',
                         'requested_rows': 212,
                         'missing_symbols': ['SZ.920438',
                                             'SZ.920275',
                                             'SZ.920670',
                                             'SZ.920045',
                                             'SZ.920060',
                                             'SZ.920699'],
                         'raw_status': 'PARTIAL_WITH_ROWS',
                         'original_temporal_cutoff_safe': False}}}
APPROVED_BY_TARGET["20260918"]["v192"] = APPROVED["v192"]
# R2 exact original has a BOM-prefixed trade_date column; the existing
# utf-8-sig reader verifies every row date and timestamp without relaxation.
# Missing aliases are preserved separately from the six unique missing
# securities used for coverage arithmetic.
APPROVED_BY_TARGET["20260915"] = {"stage7": {'run_id': '20260914-a_share_1min_stage_1445_1500-807bd35e18b67a87',
 'role': 'A_SHARE_1MIN_STAGE_1445_1500',
 'trade_date': '20260914',
 'row_count': 228,
 'artifact.csv': '972f18ae93ba144d55821925ec594891e97cd6db8bc4a88b39579f5d48d1bb4d',
 'manifest.json': '69deba6294e435543b3e489ecabbbe52b42f8fb92ef064388ee3f6cb2efb5680',
 'receipt.json': '6940e7a8e0b81f2ac04ae49b38c689e54ce1eb0a74e39067e5c0f97703721e0a',
 'requested_rows': 234,
 'missing_symbols': ['SZ.000660', 'SZ.920010', 'SZ.920088', 'SZ.920275', 'SZ.920125', 'SZ.920020'],
 'original_missing_symbols': ['SZ.000660',
                              'SZ.920010',
                              'SZ.920088',
                              'SZ.920275',
                              'SZ.920125',
                              'SZ.920020',
                              'A.000660',
                              'A.920010',
                              'A.920020',
                              'A.920088',
                              'A.920125',
                              'A.920275'],
 'raw_status': 'PARTIAL_WITH_ROWS',
 'original_temporal_cutoff_safe': False}}


def approved(kind: str, signal_date: str = SIGNAL, target_date: str = TARGET) -> dict[str, Any]:
    check_dates(signal_date, target_date)
    try:
        return APPROVED_BY_TARGET[target_date][kind]
    except KeyError as error:
        raise ValueError("EXACT_ORIGINAL_AUTHORITY_MISSING") from error

def require_external_original_sha(kind: str, signal_date: str, target_date: str,
                                  expected: Mapping[str, str] | None) -> None:
    a = approved(kind, signal_date, target_date)
    if expected is None:
        if (signal_date, target_date) != (SIGNAL, TARGET):
            raise ValueError("EXTERNAL_ORIGINAL_SHA_REQUIRED")
        return  # byte-compatible original 0918 command; pinned hashes still checked
    if set(expected) != set(FILES) or any(expected.get(name) != a[name] for name in FILES):
        raise ValueError("EXTERNAL_ORIGINAL_SHA_MISMATCH")

def original_sha_arguments(args) -> dict[str, str] | None:
    values = {name: getattr(args, "expected_original_" + name.split(".")[0] + "_sha256")
              for name in FILES}
    return values if any(value is not None for value in values.values()) else None

def check_dates(signal_date: str, target_date: str) -> None:
    if PREVIOUS_TRADING_DAY.get(target_date) != signal_date or signal_date is None:
        raise ValueError("EXACT_PREVIOUS_TRADING_DAY_REQUIRED")

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def original_relative(kind: str, signal_date: str = SIGNAL, target_date: str = TARGET) -> str:
    a = approved(kind, signal_date, target_date)
    return f"historical_pool_sources/{target_date}/{kind}/{a['run_id']}"

def verify_original(source_dir: Path, kind: str, *, signal_date: str = SIGNAL,
                    target_date: str = TARGET,
                    expected_original_sha256: Mapping[str, str] | None = None) -> dict[str, Any]:
    check_dates(signal_date, target_date)
    a = approved(kind, signal_date, target_date)
    if expected_original_sha256 is not None:
        require_external_original_sha(kind, signal_date, target_date, expected_original_sha256)
    root = Path(source_dir).absolute()  # do not resolve away symlinks
    reader = SafeRoot(root)
    blobs = {name: reader.read_bytes(name) for name in FILES}
    for name, data in blobs.items():
        if _sha(data) != a[name]:
            raise ValueError(f"{kind} approved original {name} SHA mismatch")
    manifest = json.loads(blobs["manifest.json"])
    receipt = json.loads(blobs["receipt.json"])
    rows = list(csv.DictReader(io.StringIO(blobs["artifact.csv"].decode("utf-8-sig"))))
    expected_relative = f"runs/{a['trade_date']}/{a['role']}/{a['run_id']}/artifact.csv"
    for obj in (manifest, receipt):
        for key in ("trade_date", "role", "run_id"):
            if key == "run_id" and kind == "v192" and obj is manifest:
                continue  # original manifest binds run via artifact_relative; receipt is explicit
            if obj.get(key) != a[key]:
                raise ValueError(f"{kind} original {key} mismatch")
        if obj.get("artifact_sha256") != a["artifact.csv"]:
            raise ValueError(f"{kind} original artifact reference mismatch")
        if any(obj.get(flag) is not False for flag in FLAGS):
            raise ValueError(f"{kind} original unsafe flags")
    if manifest.get("artifact_relative") != expected_relative:
        raise ValueError(f"{kind} original relative path mismatch")
    # raw_store hashed the Stage7 semantic manifest; V192 hashes physical bytes.
    manifest_reference = _sha(_canonical_bytes(manifest)) if kind == "stage7" else a["manifest.json"]
    if receipt.get("manifest_sha256") != manifest_reference:
        raise ValueError(f"{kind} original manifest reference mismatch")
    if len(rows) != a["row_count"] or manifest.get("row_count") != len(rows):
        raise ValueError(f"{kind} original row count mismatch")
    if kind == "stage7":
        if manifest.get("requested_rows") != a["requested_rows"] or manifest.get("missing_symbols") != a.get("original_missing_symbols", a["missing_symbols"]):
            raise ValueError("Stage7 original coverage mismatch")
        if manifest.get("status") != a["raw_status"] or manifest.get("temporal_cutoff_safe") is not a["original_temporal_cutoff_safe"]:
            raise ValueError("Stage7 original aggregate status mismatch")
        if len(rows) + len(a["missing_symbols"]) != a["requested_rows"]:
            raise ValueError("Stage7 original requested coverage mismatch")
        if "original_missing_symbols" in a:
            canonical_missing = {value[-6:] for value in a["original_missing_symbols"]}
            if (canonical_missing != {value[-6:] for value in a["missing_symbols"]}
                    or len(canonical_missing) != len(a["missing_symbols"])
                    or canonical_missing.intersection(row.get("code", "")[-6:] for row in rows)):
                raise ValueError("Stage7 original missing alias coverage mismatch")
        for row in rows:
            if row.get("trade_date") != signal_date or row.get("temporal_cutoff_safe") != "True":
                raise ValueError("Stage7 original row date/PIT mismatch")
            bar = row["bar_time"]
            if not "14:46:00" <= bar <= "14:59:00":
                raise ValueError("Stage7 original row outside approved window")
            if row["update_time"] != f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]} {bar}" or not row["window_start"].startswith(f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]} ") or not row["window_end"].startswith(f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]} "):
                raise ValueError("Stage7 original row timestamp mismatch")
            if not "14:46:00" <= row["window_start"][-8:] <= row["window_end"][-8:] <= bar <= "14:59:00":
                raise ValueError("Stage7 original row window cutoff mismatch")
    else:
        for row in rows:
            if row.get("signal_date") != signal_date or row.get("target_date") != target_date or row.get("bar_time") != "17:30":
                raise ValueError("V192 original row date/cutoff mismatch")
    codes = [row.get("code") if kind == "stage7" else row.get("stock_code") for row in rows]
    if not all(codes) or len(set(codes)) != len(rows):
        raise ValueError("original missing or duplicate code")
    return {"kind": kind, "signal_date": signal_date, "target_date": target_date, "authority": a, "manifest": manifest, "receipt": receipt, "rows": rows,
            "bytes": blobs, "paths": {name.split('.')[0]: str(root / name) for name in FILES},
            "manifest_reference_sha256": manifest_reference}

def archive_original(root: Path, source_dir: Path, kind: str, *, signal_date: str = SIGNAL,
                     target_date: str = TARGET, expected_original_sha256: Mapping[str, str] | None = None) -> dict[str, Any]:
    verified = verify_original(source_dir, kind, signal_date=signal_date, target_date=target_date,
                               expected_original_sha256=expected_original_sha256)
    owner = SafeRoot(root)
    relative = original_relative(kind, signal_date, target_date)
    for name, blob in verified["bytes"].items():
        path = f"{relative}/{name}"
        try:
            existing = owner.read_bytes(path)
        except FileNotFoundError:
            owner.write_bytes(path, blob)
        else:
            if existing != blob:
                raise ValueError("conflicting immutable historical original")
    return verify_original(Path(root) / relative, kind, signal_date=signal_date, target_date=target_date)

def coverage(signal_date: str = SIGNAL, target_date: str = TARGET) -> dict[str, Any]:
    a = approved("stage7", signal_date, target_date)
    return {"requested_rows": a["requested_rows"], "source_rows": a["row_count"],
            "missing_symbols": list(a["missing_symbols"]), "raw_status": a["raw_status"],
            "original_temporal_cutoff_safe": a["original_temporal_cutoff_safe"],
            "row_temporal_cutoff_safe": True}

def source_identity(verified: Mapping[str, Any]) -> dict[str, Any]:
    a = verified["authority"]
    return {"source_run_id": a["run_id"], "source_sha256": a["artifact.csv"],
            "source_artifact_sha256": a["artifact.csv"],
            "source_manifest_sha256": a["manifest.json"], "source_receipt_sha256": a["receipt.json"],
            "source_paths": {**verified["paths"], "current": ""}}

def validate_stage7_provenance(artifact: Mapping[str, Any]) -> None:
    """Partial retains every row in the exact approved raw subset, without additions."""
    signal_date, target_date = artifact.get("signal_date"), artifact.get("target_date")
    a = approved("stage7", signal_date, target_date)
    paths = artifact.get("source_paths") or {}
    original = verify_original(Path(str(paths.get("artifact", ""))).parent, "stage7", signal_date=signal_date, target_date=target_date)
    identity = source_identity(original)
    for key in ("source_run_id", "source_sha256", "source_artifact_sha256", "source_manifest_sha256", "source_receipt_sha256"):
        if artifact.get(key) != identity[key]:
            raise ValueError(f"Stage7 partial source authority mismatch: {key}")
    for name in ("artifact", "manifest", "receipt"):
        if str(paths.get(name)) != original["paths"][name]:
            raise ValueError("Stage7 partial source path mismatch")
    if artifact.get("coverage_evidence") != coverage(signal_date, target_date):
        raise ValueError("Stage7 partial coverage evidence mismatch")
    rows = artifact.get("rows")
    if not isinstance(rows, list) or len(rows) != a["row_count"]:
        raise ValueError("Stage7 partial lost or added original rows")
    for row, raw in zip(rows, original["rows"]):
        for key, value in raw.items():
            if key == "code":
                if str(row.get(key, "")).removeprefix("A.") != value[-6:]:
                    raise ValueError("Stage7 partial row code mismatch")
            elif row.get(key) != value:
                raise ValueError(f"Stage7 partial row source mismatch: {key}")

def v192_payload(root: Path, signal_date: str = SIGNAL, target_date: str = TARGET) -> dict[str, Any]:
    """Deterministic research projection; does not certify the historical producer."""
    from domains.preselection_materializer import _artifact, _normalize_a_csv_rows
    original = verify_original(Path(root) / original_relative("v192", signal_date, target_date), "v192",
                               signal_date=signal_date, target_date=target_date)
    a = original["authority"]
    rows = _normalize_a_csv_rows(Path(original["paths"]["artifact"]), "a_d1_premarket_pool", target_date)
    if len(rows) != a["row_count"]:
        raise ValueError("V192 normalization lost rows")
    for row in rows:
        # Numerical formula signals are retained as historical evidence, not recommendations.
        row.update(stage_selection_eligible=False, source_merge_role="SOURCE_ONLY", research_only=True)
        row["pool_score"] = float(row["premarket_pool_score"])
    payload = _artifact(trade_date=target_date, pool_id="a_d1_premarket_pool", display_name="A股 D-1 主预选池",
        market="A", status="PARTIAL_WITH_ROWS", producer_id="v192_original_research_recovery_v1",
        source_role="RAW_SOURCE", source_path=original["manifest"]["artifact_relative"],
        source_sha256=a["artifact.csv"], rows=rows,
        cannot_confirm=["HISTORICAL_PRODUCER_EQUIVALENCE_CANNOT_CONFIRM", "MISSING_HISTORICAL_ORACLE_BUNDLE_SOURCE_SHA256", "MISSING_HISTORICAL_ORACLE_BUNDLE_CONTRACT_VERSION"])
    payload.update(signal_date=signal_date, target_date=target_date, source_row_count=a["row_count"],
        source_run_id=a["run_id"], source_artifact_sha256=a["artifact.csv"],
        source_manifest_sha256=a["manifest.json"], source_receipt_sha256=a["receipt.json"],
        source_archive=original_relative("v192", signal_date, target_date), stage_selection_eligible=False, source_merge_role="SOURCE_ONLY",
        artifact_role=a["role"], historical_provenance={"original_trio": "VERIFIED_BYTES_AND_IDENTITY",
        "producer_equivalence": "CANNOT_CONFIRM", "current_bundle_used_as_historical_evidence": False,
        "original_manifest_provenance": original["manifest"].get("provenance", {})})
    return payload

def guard_v192_payload(root: Path, payload: Mapping[str, Any]) -> None:
    target = payload.get("trade_date")
    if target in APPROVED_BY_TARGET and "v192" in APPROVED_BY_TARGET[target] and payload.get("pool_id") == "a_d1_premarket_pool" and payload.get("rows"):
        signal = PREVIOUS_TRADING_DAY[target]
        if dict(payload) != v192_payload(root, signal, target):
            raise ValueError("V192 nonempty payload is not the bound original research projection")


def stage7_input(root: Path, original: Mapping[str, Any]) -> dict[str, Any]:
    """Use StageStore's existing supported enum; partial lives in scoped metadata."""
    a = original["authority"]
    signal_date, target_date = original["signal_date"], original["target_date"]
    rows = []
    for raw in original["rows"]:
        row = dict(raw)
        code = raw["code"][-6:]
        row.update(code=code, symbol=f"A.{code}", market="A", recommendation_status="WATCH_ONLY", **FLAGS)
        rows.append(row)
    c = coverage(signal_date, target_date)
    return {"schema_version": "v3_5.stage_input.v1", "trade_date": signal_date,
            "stage_id": "STAGE_1445_1500", "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
            "cutoff_reached": True, "market_status": {"A": "CANNOT_CONFIRM", "HK": "CANNOT_CONFIRM"},
            "rows": {"A": rows, "HK": []}, **FLAGS,
            "source_evidence": [{"path": f"{original_relative('stage7', signal_date, target_date)}/{name}", "sha256": a[name]} for name in FILES],
            "coverage_evidence": c, "source_status": "PARTIAL_WITH_ROWS",
            "cannot_confirm": list(original["manifest"]["cannot_confirm"]) + [f"STAGE7_MISSING_{len(c['missing_symbols'])}_OF_{c['requested_rows']}", "HK_EXACT_STAGE_INPUT_MISSING"],
            "source_summary": {"source_id": "pytdx_hq", "source_run_id": a["run_id"],
                               "quote_coverage": {"A_SHARE": {**c, "coverage_ratio": a["row_count"] / a["requested_rows"]}},
                               "original_manifest_reference_sha256": original["manifest_reference_sha256"]}}

def import_stage7_original(root: Path, source_dir: Path, *, signal_date: str = SIGNAL, target_date: str = TARGET) -> dict[str, Any]:
    from infrastructure.stage_store import StageStore
    original = archive_original(root, source_dir, "stage7", signal_date=signal_date, target_date=target_date)
    payload = stage7_input(root, original)
    result = StageStore(root).import_input(payload)  # no replace, no different-date fallback
    checked, digest = StageStore(root).read_input(signal_date, "STAGE_1445_1500")
    if checked != payload:
        raise ValueError("Stage7 import readback mismatch")
    return {"import": result, "payload": checked, "sha256": digest}

def verified_stage7_input(root: Path, signal_date: str = SIGNAL, target_date: str = TARGET) -> tuple[dict[str, Any], dict[str, Any], str]:
    from infrastructure.stage_store import StageStore
    original = verify_original(Path(root) / original_relative("stage7", signal_date, target_date), "stage7",
                               signal_date=signal_date, target_date=target_date)
    payload, digest = StageStore(root).read_input(signal_date, "STAGE_1445_1500")
    if payload != stage7_input(root, original):
        raise ValueError("Stage7 imported payload differs from approved source projection")
    return original, payload, digest

def native_stage7_payload(root: Path, lane_dir: Path, signal_date: str = SIGNAL, target_date: str = TARGET) -> dict[str, Any]:
    artifact = _native_stage7_projection(root, lane_dir, signal_date, target_date)
    validate_native_stage7(root, artifact)
    return artifact


def _native_stage7_projection(root: Path, lane_dir: Path, signal_date: str = SIGNAL, target_date: str = TARGET) -> dict[str, Any]:
    """Existing lane projection; caller must verify its source-derived documents."""
    from domains.preselection_materializer import build_stage7_review_pool
    original, _, _ = verified_stage7_input(root, signal_date, target_date)
    artifact = build_stage7_review_pool(Path(lane_dir) / "stage7.csv", Path(lane_dir) / "stage7.manifest.json",
                                      trade_date=target_date, signal_date=signal_date)
    a = original["authority"]
    artifact.update(signal_date=signal_date, target_date=target_date, source_run_id=a["run_id"],
        source_row_count=a["row_count"], source_artifact_sha256=a["artifact.csv"],
        source_manifest_sha256=a["manifest.json"], source_receipt_sha256=a["receipt.json"],
        source_archive=original_relative("stage7", signal_date, target_date), coverage_evidence=coverage(signal_date, target_date),
        stage_selection_eligible=True, source_merge_role="MAIN_STAGE_INPUT")
    return artifact

def validate_native_stage7(root: Path, artifact: Mapping[str, Any]) -> None:
    """A bounded native auxiliary lane may contribute; V192 remains excluded."""
    signal_date, target_date = artifact.get("signal_date"), artifact.get("target_date")
    original, _, _ = verified_stage7_input(root, signal_date, target_date)
    a = original["authority"]
    expected = {"trade_date": target_date, "signal_date": signal_date, "target_date": target_date,
        "pool_id": "a_d1_stage7_fenshi_review_pool", "source_role": "VERIFIED_D1_STAGE7_REPLAY",
        "producer_id": "v3_stage7_tail_replay_contract_v1", "status": "STAGE7_TAIL_POOL_READY_DATA_PARTIAL",
        "source_run_id": a["run_id"], "source_row_count": a["row_count"],
        "source_artifact_sha256": a["artifact.csv"], "source_manifest_sha256": a["manifest.json"],
        "source_receipt_sha256": a["receipt.json"], "source_archive": original_relative("stage7", signal_date, target_date),
        "coverage_evidence": coverage(signal_date, target_date), "stage_selection_eligible": True, "source_merge_role": "MAIN_STAGE_INPUT"}
    if any(artifact.get(k) != v for k, v in expected.items()):
        raise ValueError("native Stage7 source/partial identity mismatch")
    rows = artifact.get("rows")
    if not isinstance(rows, list) or len(rows) != a["row_count"]:
        raise ValueError("native Stage7 row count mismatch")
    if [r.get("symbol") for r in rows] != [f"A.{r['code'][-6:]}" for r in original["rows"]]:
        raise ValueError("native Stage7 rows do not match original order/codes")
    if not artifact.get("cannot_confirm"):
        raise ValueError("native Stage7 partial reasons were lost")

    # Codes/coverage alone do not bind scores, names, extra fields or evidence.
    # Reuse the existing deterministic transforms in read-only mode, then bind
    # the complete canonical projection, including every row and source SHA.
    from domains.d1_review_lane_producer import materialize_recovered_stage7_lane
    lane = materialize_recovered_stage7_lane(Path(root), signal_date=signal_date, target_date=target_date, verify_only=True)
    expected_projection = _native_stage7_projection(Path(root), Path(lane["lane_dir"]), signal_date, target_date)
    if _canonical_bytes(dict(artifact)) != _canonical_bytes(expected_projection):
        raise ValueError("native Stage7 recovery projection differs from verified original derivation")


def preflight_stage7_original(root: Path, source_dir: Path, expected_sha256: str, *,
                              signal_date: str = SIGNAL, target_date: str = TARGET) -> None:
    """Read-only preflight, not a cross-store transaction or a replacement API.

    The final pool owner still rechecks CAS under its own lock. Formal callers
    must exclude other writers for the complete multi-store operation.
    """
    from infrastructure.stage_store import StageStore
    from infrastructure.preselection_pool_store import PreselectionPoolStore, validate_pool_artifact
    if expected_sha256 != "ABSENT" and re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256)) is None:
        raise ValueError("Stage7 recovery CAS requires an observed SHA or ABSENT")
    original = verify_original(source_dir, "stage7", signal_date=signal_date, target_date=target_date)
    wanted_input = stage7_input(root, original)
    input_sha = _sha(_canonical_bytes(wanted_input))
    native = StageStore(root)
    relative = f"stage_inputs/{signal_date}/STAGE_1445_1500.json"
    receipt_path = f"receipts/{relative}"
    native_manifest = native._manifest()
    if not isinstance(native_manifest, dict):
        raise ValueError("StageInput manifest is invalid")
    committed_input = native_manifest.get(relative)
    if committed_input not in (None, input_sha):
        raise ValueError("StageInput conflict: existing committed input must not be replaced")
    expected_receipt = {"schema_version": "v3_import_receipt.v1", "payload_path": relative,
                        "source_sha256": input_sha, "trade_date": signal_date}
    existing_input = None
    for path, value in ((relative, wanted_input), (receipt_path, expected_receipt)):
        try:
            existing = native._read(path)
        except FileNotFoundError:
            if committed_input is not None:
                raise ValueError("StageInput committed evidence is missing")
            continue
        if _canonical_bytes(existing) != _canonical_bytes(value):
            raise ValueError("StageInput conflict: existing payload/receipt must not be replaced")
        if path == relative:
            existing_input = existing
        elif existing_input is None:
            raise ValueError("StageInput orphan receipt cannot be repaired by preflight")

    pool = "a_d1_stage7_fenshi_review_pool"
    store = PreselectionPoolStore(root)
    ap, rp = store._relative(target_date, pool)
    try:
        manifest = store._read(f"preselection_pools/{target_date}/manifest.json")
    except FileNotFoundError:
        manifest = {}
    if not isinstance(manifest, dict):
        raise ValueError("Stage7 pool manifest is invalid")
    committed = manifest.get(pool)
    if committed is None:
        if expected_sha256 != "ABSENT":
            raise ValueError("Stage7 recovery compare-and-swap conflict: pool is absent")
        # Resume only our exact interrupted first materialization, never a
        # foreign orphan; no files are written by this inspection.
        try:
            pending = store._read(ap)
        except FileNotFoundError:
            try:
                store._read(rp)
            except FileNotFoundError:
                return
            raise ValueError("Stage7 recovery orphan receipt")
        try:
            validate_native_stage7(root, pending)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError("untracked dirty recovery file cannot be overwritten") from error
        pending_receipt = store._receipt(trade_date=target_date, pool_id=pool, artifact_path=ap,
            artifact_sha256=_sha(_canonical_bytes(pending)), payload=pending)
        try:
            observed_receipt = store._read(rp)
        except FileNotFoundError:
            return  # existing owner completes this exact interrupted write
        if _canonical_bytes(observed_receipt) != _canonical_bytes(pending_receipt):
            raise ValueError("Stage7 recovery untracked receipt conflict")
        return
    if re.fullmatch(r"[0-9a-f]{64}", str(committed)) is None:
        raise ValueError("Stage7 recovery committed SHA is invalid")
    try:
        current = store.read_pool_snapshot(target_date, pool)["artifact"]
    except (OSError, ValueError, KeyError, TypeError):
        # Read, but do not restore, the existing manifest-committed revision.
        revision = f"preselection_revisions/{target_date}/{committed}.json"
        current = store._read(revision)
        if (_sha(_canonical_bytes(current)) != committed or
                validate_pool_artifact(current) != target_date or current.get("pool_id") != pool):
            raise ValueError("Stage7 recovery committed revision mismatch")
        expected = store._receipt(trade_date=target_date, pool_id=pool, artifact_path=ap,
                                  artifact_sha256=committed, payload=current)
        rr = store._read(revision.removesuffix(".json") + ".receipt.json")
        if rr != store._recovery_revision_receipt(target_date, pool, committed, current, expected):
            raise ValueError("Stage7 recovery committed revision receipt mismatch")
    if current.get("source_archive") == original_relative("stage7", signal_date, target_date):
        validate_native_stage7(root, current)  # same fully bound recovery is idempotent
        return
    if committed != expected_sha256:
        raise ValueError("Stage7 recovery compare-and-swap conflict")
    if not (current.get("source_role") == "EXPECTED_MISSING" and
            current.get("producer_id") == "graph_expected_missing_v1" and
            current.get("status") == "CANNOT_CONFIRM" and current.get("rows") == [] and
            current.get("market") == "A" and current.get("source_path") == "" and
            current.get("source_sha256") == _sha(b"") and current.get("cannot_confirm") and
            all(current.get(flag) is False for flag in FLAGS)):
        raise ValueError("Stage7 recovery cannot replace a non-placeholder pool")
