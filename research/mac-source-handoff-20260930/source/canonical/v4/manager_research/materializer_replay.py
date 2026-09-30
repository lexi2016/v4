"""Fail-closed offline replay support for the existing 15:30 Manager materializer.

This module is test/activation tooling only.  It never creates market inputs and
never changes the production materializer CLI.  A replay reuses an already
persisted natural 15:30 snapshot/history witness and runs the exact pinned
materializer source in a sanitized child interpreter with producer/network
calls blocked.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping
from zoneinfo import ZoneInfo

HK = ZoneInfo("Asia/Hong_Kong")
SPEC_SCHEMA = "v4.manager_close_offline_replay_spec.v1"
RESULT_SCHEMA = "v4.manager_research.materializer_offline_replay.v1"
SEED_SCHEMA = "v4.manager_close_offline_replay_seed.v1"
SEED_BUNDLE_SCHEMA = "v4.manager_close_offline_replay_bundle.v1"
SEED_ORIGIN_EVIDENCE_SCHEMA = "v4.manager_close_offline_replay_origin_evidence.v1"
_FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
_REQUIRED_STATE_INPUTS = (
    "workbench_research/{date}/inputs/1530_futu_snapshot.json",
    "workbench_research/{date}/inputs/1530_futu_snapshot.json.receipt.json",
    "workbench_research/{date}/inputs/1530_rebound_history.json",
)
_PUBLISHED_OUTPUTS = (
    "workbench_research/{date}/1530.json",
    "workbench_research/{date}/1530.receipt.json",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _absolute_dir(value: str | Path, code: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path.resolve() != path or path.is_symlink() or not path.is_dir():
        raise ValueError(code)
    return path


def _absolute_file(value: str | Path, code: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path.resolve() != path or path.is_symlink() or not path.is_file():
        raise ValueError(code)
    return path


def _date(value: object) -> str:
    text = str(value or "")
    if not re.fullmatch(r"\d{8}", text):
        raise ValueError("REPLAY_TRADE_DATE_INVALID")
    datetime.strptime(text, "%Y%m%d")
    return text


def _clock(value: object, date: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError("REPLAY_CLOCK_INVALID") from exc
    if stamp.tzinfo is None:
        raise ValueError("REPLAY_CLOCK_INVALID")
    stamp = stamp.astimezone(HK)
    if stamp.strftime("%Y%m%d") != date or not (15, 30) <= (stamp.hour, stamp.minute) < (15, 32):
        raise ValueError("REPLAY_CLOCK_OUTSIDE_1530_WINDOW")
    return stamp


def _safe_rel(ref: str) -> Path:
    path = Path(ref)
    if not ref or path.is_absolute() or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise ValueError("REPLAY_RELATIVE_PATH_INVALID")
    return path


def build_replay_seed(source_state_root: str | Path, destination_root: str | Path, trade_date: str) -> dict:
    """Copy only immutable 15:30 input witnesses; never copy a published result."""
    date = _date(trade_date)
    source = _absolute_dir(source_state_root, "REPLAY_SOURCE_STATE_ROOT_INVALID")
    destination = Path(destination_root).expanduser()
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise ValueError("REPLAY_DESTINATION_ROOT_INVALID")
    if destination == source or source in destination.parents or destination in source.parents:
        raise ValueError("REPLAY_SOURCE_DESTINATION_OVERLAP")
    copied: dict[str, str] = {}
    destination.mkdir(parents=True, exist_ok=False)
    try:
        for template in _REQUIRED_STATE_INPUTS:
            rel = Path(template.format(date=date))
            src = source / rel
            if not src.is_file() or src.is_symlink():
                raise ValueError("REPLAY_REQUIRED_1530_INPUT_MISSING:" + rel.as_posix())
            raw = src.read_bytes()
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError("REPLAY_REQUIRED_1530_INPUT_TOO_LARGE")
            dst = destination / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(raw)
            copied[rel.as_posix()] = hashlib.sha256(raw).hexdigest()
        for template in _PUBLISHED_OUTPUTS:
            if (destination / template.format(date=date)).exists():
                raise ValueError("REPLAY_PUBLISHED_OUTPUT_COPIED")
        snap = json.loads((destination / _REQUIRED_STATE_INPUTS[0].format(date=date)).read_bytes())
        hist = json.loads((destination / _REQUIRED_STATE_INPUTS[2].format(date=date)).read_bytes())
        if snap.get("trade_date") != date or hist.get("trade_date") != date:
            raise ValueError("REPLAY_INPUT_DATE_MISMATCH")
        started = datetime.fromisoformat(str(snap.get("started_at") or "")).astimezone(HK)
        available = datetime.fromisoformat(str(snap.get("available_at") or "")).astimezone(HK)
        if (started.strftime("%Y%m%d") != date or available.strftime("%Y%m%d") != date
                or not (15,30) <= (started.hour,started.minute) < (15,32)
                or not started <= available or not (available.hour == 15 and available.minute < 32)):
            raise ValueError("REPLAY_SNAPSHOT_TIME_INVALID")
        return {"schema_version": SEED_SCHEMA, "status": "READY", "trade_date": date,
                "source_state_root": str(source), "seed_root": str(destination),
                "copied_inputs": copied, **_FLAGS}
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _canonical_dir(value: object, code: str) -> Path:
    text=str(value or "")
    path=Path(text)
    if (not text or not path.is_absolute() or str(path)!=text or path.resolve()!=path
            or path.is_symlink() or not path.is_dir()):
        raise ValueError(code)
    return path


def _origin_input_manifest(root: Path, trade_date: str) -> dict[str, str]:
    if root.is_symlink() or root.resolve()!=root or not root.is_dir():
        raise ValueError("REPLAY_ORIGIN_SOURCE_ROOT_INVALID")
    rows: dict[str,str]={}
    for template in _REQUIRED_STATE_INPUTS:
        rel=Path(template.format(date=trade_date))
        path=root/rel
        cursor=root
        for part in rel.parts:
            cursor=cursor/part
            if cursor.is_symlink():
                raise ValueError("REPLAY_ORIGIN_INPUT_SYMLINK:"+rel.as_posix())
        if not path.is_file():
            raise ValueError("REPLAY_ORIGIN_INPUT_MISSING:"+rel.as_posix())
        raw=path.read_bytes()
        if len(raw)>32*1024*1024:
            raise ValueError("REPLAY_ORIGIN_INPUT_TOO_LARGE:"+rel.as_posix())
        rows[rel.as_posix()]=hashlib.sha256(raw).hexdigest()
    snapshot=json.loads((root/_REQUIRED_STATE_INPUTS[0].format(date=trade_date)).read_bytes())
    history=json.loads((root/_REQUIRED_STATE_INPUTS[2].format(date=trade_date)).read_bytes())
    if (not isinstance(snapshot,Mapping) or not isinstance(history,Mapping)
            or snapshot.get("trade_date")!=trade_date or history.get("trade_date")!=trade_date):
        raise ValueError("REPLAY_ORIGIN_INPUT_DATE_MISMATCH")
    return rows


def _validate_seed_snapshot_window(root: Path, trade_date: str) -> None:
    snapshot=json.loads((root/_REQUIRED_STATE_INPUTS[0].format(date=trade_date)).read_bytes())
    if not isinstance(snapshot,Mapping) or snapshot.get("trade_date")!=trade_date:
        raise ValueError("REPLAY_ORIGIN_INPUT_DATE_MISMATCH")
    try:
        started=datetime.fromisoformat(str(snapshot.get("started_at") or ""))
        available=datetime.fromisoformat(str(snapshot.get("available_at") or ""))
    except ValueError as exc:
        raise ValueError("REPLAY_ORIGIN_SNAPSHOT_TIME_INVALID") from exc
    if started.tzinfo is None or available.tzinfo is None:
        raise ValueError("REPLAY_ORIGIN_SNAPSHOT_TIME_INVALID")
    started=started.astimezone(HK); available=available.astimezone(HK)
    if (started.strftime("%Y%m%d")!=trade_date or available.strftime("%Y%m%d")!=trade_date
            or not (15,30)<=(started.hour,started.minute)<(15,32)
            or not started<=available or not (available.hour==15 and available.minute<32)):
        raise ValueError("REPLAY_ORIGIN_SNAPSHOT_TIME_INVALID")


def _canonical_json_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(",",":")).encode("utf-8")).hexdigest()


def validate_replay_origin_bundle(receipt_path: str | Path, *, expected_seed_root: str | Path,
                                  expected_trade_date: str, expected_replay_spec_path: str | Path,
                                  expected_replay_spec_sha256: str,
                                  expected_source_state_root: str | Path | None=None) -> dict[str, Any]:
    """Verify the existing Task3.2 bundle's exact origin-to-seed input mapping."""
    receipt=Path(receipt_path)
    seed=_canonical_dir(expected_seed_root,"REPLAY_ORIGIN_SEED_ROOT_INVALID")
    date=_date(expected_trade_date)
    raw_spec_path=Path(expected_replay_spec_path)
    if (not raw_spec_path.is_absolute() or raw_spec_path.resolve()!=raw_spec_path
            or raw_spec_path.is_symlink() or not raw_spec_path.is_file()):
        raise ValueError("REPLAY_ORIGIN_SPEC_PATH_INVALID")
    spec_sha=str(expected_replay_spec_sha256 or "")
    if not re.fullmatch(r"[0-9a-f]{64}",spec_sha) or _sha(raw_spec_path)!=spec_sha:
        raise ValueError("REPLAY_ORIGIN_SPEC_SHA_MISMATCH")
    if (not receipt.is_absolute() or receipt.resolve()!=receipt or receipt.is_symlink()
            or not receipt.is_file()):
        raise ValueError("REPLAY_ORIGIN_RECEIPT_PATH_INVALID")
    try:
        bundle=json.loads(receipt.read_bytes())
    except (OSError,ValueError,TypeError) as exc:
        raise ValueError("REPLAY_ORIGIN_RECEIPT_INVALID") from exc
    expected_bundle_keys={"schema_version","status","seed","replay_spec","replay_spec_sha256",
        "production_allowed","buy_gate_updated","orders_sent"}
    if (not isinstance(bundle,Mapping) or set(bundle)!=expected_bundle_keys
            or bundle.get("schema_version")!=SEED_BUNDLE_SCHEMA or bundle.get("status")!="READY"
            or bundle.get("production_allowed") is not False or bundle.get("buy_gate_updated") is not False
            or bundle.get("orders_sent") is not False):
        raise ValueError("REPLAY_ORIGIN_BUNDLE_NOT_READY")
    seed_receipt=bundle.get("seed")
    expected_seed_keys={"schema_version","status","trade_date","source_state_root","seed_root",
        "copied_inputs","RESEARCH_ONLY","production_allowed","buy_gate_updated","orders_sent"}
    if (not isinstance(seed_receipt,Mapping) or set(seed_receipt)!=expected_seed_keys
            or seed_receipt.get("schema_version")!=SEED_SCHEMA or seed_receipt.get("status")!="READY"
            or seed_receipt.get("RESEARCH_ONLY") is not True
            or seed_receipt.get("production_allowed") is not False
            or seed_receipt.get("buy_gate_updated") is not False
            or seed_receipt.get("orders_sent") is not False
            or seed_receipt.get("trade_date")!=date):
        raise ValueError("REPLAY_ORIGIN_SEED_RECEIPT_INVALID")
    origin=_canonical_dir(seed_receipt.get("source_state_root"),"REPLAY_ORIGIN_SOURCE_ROOT_INVALID")
    recorded_seed=_canonical_dir(seed_receipt.get("seed_root"),"REPLAY_ORIGIN_SEED_ROOT_INVALID")
    if recorded_seed!=seed:
        raise ValueError("REPLAY_ORIGIN_SEED_ROOT_MISMATCH")
    if origin==seed or origin in seed.parents or seed in origin.parents:
        raise ValueError("REPLAY_ORIGIN_ROOTS_OVERLAP")
    if expected_source_state_root is not None:
        expected_origin=Path(expected_source_state_root)
        if (not expected_origin.is_absolute() or expected_origin.resolve()!=expected_origin
                or expected_origin.is_symlink() or origin!=expected_origin):
            raise ValueError("REPLAY_ORIGIN_SOURCE_ROOT_MISMATCH")
    expected_inputs={template.format(date=date) for template in _REQUIRED_STATE_INPUTS}
    copied=seed_receipt.get("copied_inputs")
    if (not isinstance(copied,Mapping) or set(copied)!=expected_inputs
            or any(not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{64}",sha)
                for sha in copied.values())):
        raise ValueError("REPLAY_ORIGIN_COPIED_INPUTS_INVALID")
    replay_spec_text=bundle.get("replay_spec")
    replay_spec=Path(str(replay_spec_text or ""))
    if (not replay_spec.is_absolute() or replay_spec.resolve()!=replay_spec or replay_spec.is_symlink()
            or replay_spec!=raw_spec_path or bundle.get("replay_spec_sha256")!=spec_sha):
        raise ValueError("REPLAY_ORIGIN_SPEC_BINDING_MISMATCH")
    try:
        spec=json.loads(raw_spec_path.read_bytes())
    except (OSError,ValueError,TypeError) as exc:
        raise ValueError("REPLAY_ORIGIN_SPEC_INVALID") from exc
    if not isinstance(spec,Mapping) or spec.get("trade_date")!=date:
        raise ValueError("REPLAY_ORIGIN_SPEC_DATE_MISMATCH")
    # Reuse the original replay contract to check all owner/app identities and
    # the exact seed state before the canary starts a child.
    normalized_spec=validate_replay_spec(spec,state_root=seed)
    _validate_seed_snapshot_window(seed,date)
    app=Path(normalized_spec["materializer_app_root"])
    if (origin==app or origin in app.parents or app in origin.parents
            or any(path==root or root in path.parents for path in (receipt,raw_spec_path)
                for root in (origin,seed,app))):
        raise ValueError("REPLAY_ORIGIN_RECEIPT_OR_SPEC_ROOT_INVALID")
    origin_inputs=_origin_input_manifest(origin,date)
    seed_manifest=_bounded_tree_manifest(seed)
    if dict(copied)!=origin_inputs:
        raise ValueError("REPLAY_ORIGIN_SOURCE_SHA_MISMATCH")
    if seed_manifest!=dict(copied):
        raise ValueError("REPLAY_ORIGIN_SEED_MANIFEST_MISMATCH")
    return {
        "schema_version":SEED_ORIGIN_EVIDENCE_SCHEMA,
        "bundle_receipt_path":str(receipt),
        "bundle_receipt_sha256":_sha(receipt),
        "bundle_payload":dict(bundle),
        "normalized_bundle_sha256":_canonical_json_sha(bundle),
        "trade_date":date,
        "source_state_root":str(origin),
        "replay_seed_root":str(seed),
        "replay_spec_path":str(raw_spec_path),
        "replay_spec_sha256":spec_sha,
        "copied_inputs":dict(copied),
        "origin_inputs_before":origin_inputs,
        "origin_inputs_after":origin_inputs,
        "seed_manifest_before":seed_manifest,
        "seed_manifest_after":seed_manifest,
    }


def validate_replay_origin_evidence(value: object, *, expected_source_state_root: str | Path,
                                    expected_replay_seed_root: str | Path,
                                    expected_trade_date: str) -> dict[str, Any]:
    """Independently check a persisted v7 origin/seed mapping artifact."""
    if not isinstance(value,Mapping) or value.get("schema_version")!=SEED_ORIGIN_EVIDENCE_SCHEMA:
        raise ValueError("REPLAY_ORIGIN_EVIDENCE_SCHEMA_INVALID")
    date=_date(expected_trade_date)
    source=_canonical_dir(value.get("source_state_root"),"REPLAY_ORIGIN_SOURCE_ROOT_INVALID")
    seed=_canonical_dir(value.get("replay_seed_root"),"REPLAY_ORIGIN_SEED_ROOT_INVALID")
    expected_source=Path(expected_source_state_root)
    expected_seed=Path(expected_replay_seed_root)
    if (value.get("trade_date")!=date or source!=expected_source or seed!=expected_seed
            or source==seed or source in seed.parents or seed in source.parents):
        raise ValueError("REPLAY_ORIGIN_EVIDENCE_ROOT_OR_DATE_MISMATCH")
    payload=value.get("bundle_payload")
    expected_bundle_keys={"schema_version","status","seed","replay_spec","replay_spec_sha256",
        "production_allowed","buy_gate_updated","orders_sent"}
    if (not isinstance(payload,Mapping) or set(payload)!=expected_bundle_keys
            or payload.get("schema_version")!=SEED_BUNDLE_SCHEMA
            or payload.get("status")!="READY"
            or payload.get("production_allowed") is not False
            or payload.get("buy_gate_updated") is not False
            or payload.get("orders_sent") is not False
            or _canonical_json_sha(payload)!=value.get("normalized_bundle_sha256")
            or not re.fullmatch(r"[0-9a-f]{64}",str(value.get("bundle_receipt_sha256") or ""))):
        raise ValueError("REPLAY_ORIGIN_EVIDENCE_BUNDLE_INVALID")
    bundle_path=Path(str(value.get("bundle_receipt_path") or ""))
    if (not bundle_path.is_absolute() or bundle_path.resolve()!=bundle_path or bundle_path.is_symlink()
            or not bundle_path.is_file() or source==bundle_path or source in bundle_path.parents
            or seed==bundle_path or seed in bundle_path.parents
            or _sha(bundle_path)!=value.get("bundle_receipt_sha256")):
        raise ValueError("REPLAY_ORIGIN_EVIDENCE_RECEIPT_PATH_INVALID")
    try:
        if json.loads(bundle_path.read_bytes())!=payload:
            raise ValueError("REPLAY_ORIGIN_EVIDENCE_RECEIPT_CONTENT_MISMATCH")
    except (OSError,ValueError,TypeError) as exc:
        if isinstance(exc,ValueError) and str(exc).startswith("REPLAY_ORIGIN_EVIDENCE_"):
            raise
        raise ValueError("REPLAY_ORIGIN_EVIDENCE_RECEIPT_INVALID") from exc
    seed_receipt=payload.get("seed")
    copied=value.get("copied_inputs")
    expected_inputs={template.format(date=date) for template in _REQUIRED_STATE_INPUTS}
    expected_seed_keys={"schema_version","status","trade_date","source_state_root","seed_root",
        "copied_inputs","RESEARCH_ONLY","production_allowed","buy_gate_updated","orders_sent"}
    if (not isinstance(seed_receipt,Mapping) or set(seed_receipt)!=expected_seed_keys
            or seed_receipt.get("schema_version")!=SEED_SCHEMA or seed_receipt.get("status")!="READY"
            or seed_receipt.get("RESEARCH_ONLY") is not True
            or seed_receipt.get("production_allowed") is not False
            or seed_receipt.get("buy_gate_updated") is not False
            or seed_receipt.get("orders_sent") is not False
            or seed_receipt.get("source_state_root")!=str(source)
            or seed_receipt.get("seed_root")!=str(seed) or seed_receipt.get("trade_date")!=date
            or not isinstance(copied,Mapping) or dict(copied)!=seed_receipt.get("copied_inputs")
            or set(copied)!=expected_inputs
            or any(not re.fullmatch(r"[0-9a-f]{64}",str(sha)) for sha in copied.values())):
        raise ValueError("REPLAY_ORIGIN_EVIDENCE_INPUT_MAPPING_INVALID")
    for key in ("origin_inputs_before","origin_inputs_after","seed_manifest_before","seed_manifest_after"):
        if value.get(key)!=dict(copied):
            raise ValueError("REPLAY_ORIGIN_EVIDENCE_UNCHANGED_INPUTS_INVALID")
    spec_path=Path(str(value.get("replay_spec_path") or ""))
    spec_sha=str(value.get("replay_spec_sha256") or "")
    if (not spec_path.is_absolute() or spec_path.resolve()!=spec_path
            or payload.get("replay_spec")!=str(spec_path)
            or payload.get("replay_spec_sha256")!=spec_sha
            or not re.fullmatch(r"[0-9a-f]{64}",spec_sha)
            or spec_path.is_symlink() or not spec_path.is_file() or _sha(spec_path)!=spec_sha):
        raise ValueError("REPLAY_ORIGIN_EVIDENCE_SPEC_BINDING_INVALID")
    try:
        spec=json.loads(spec_path.read_bytes())
    except (OSError,ValueError,TypeError) as exc:
        raise ValueError("REPLAY_ORIGIN_EVIDENCE_SPEC_INVALID") from exc
    if not isinstance(spec,Mapping) or spec.get("trade_date")!=date:
        raise ValueError("REPLAY_ORIGIN_EVIDENCE_SPEC_DATE_MISMATCH")
    app=Path(str(spec.get("materializer_app_root") or ""))
    if (not app.is_absolute() or app.resolve()!=app or app.is_symlink()
            or source==app or source in app.parents or app in source.parents
            or any(path==root or root in path.parents for path in (bundle_path,spec_path)
                for root in (source,seed,app))):
        raise ValueError("REPLAY_ORIGIN_EVIDENCE_SPEC_ROOT_INVALID")
    return dict(value)


def validate_replay_spec(value: Mapping[str, Any], *, state_root: str | Path | None = None) -> dict:
    if not isinstance(value, Mapping) or value.get("schema_version") != SPEC_SCHEMA:
        raise ValueError("REPLAY_SPEC_SCHEMA_INVALID")
    date = _date(value.get("trade_date"))
    stamp = _clock(value.get("clock_iso"), date)
    app = _absolute_dir(value.get("materializer_app_root"), "REPLAY_MATERIALIZER_APP_ROOT_INVALID")
    source = _absolute_file(app / "ops/materialize_manager_close_discovery.py", "REPLAY_MATERIALIZER_SOURCE_MISSING")
    expected_sha = str(value.get("materializer_source_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or _sha(source) != expected_sha:
        raise ValueError("REPLAY_MATERIALIZER_SOURCE_SHA_MISMATCH")
    roots = {}
    for key, code in (
        ("data_root", "REPLAY_DATA_ROOT_INVALID"),
        ("universe_root", "REPLAY_UNIVERSE_ROOT_INVALID"),
        ("news_owner_root", "REPLAY_NEWS_OWNER_ROOT_INVALID"),
        ("universe_owner_root", "REPLAY_UNIVERSE_OWNER_ROOT_INVALID"),
        ("rebound_authority_root", "REPLAY_REBOUND_AUTHORITY_ROOT_INVALID"),
    ):
        roots[key] = _absolute_dir(value.get(key), code)
    owner_sha = str(value.get("universe_owner_sha256") or "")
    owner_source = roots["universe_owner_root"] / "stage_center/hk_universe_preflight.py"
    if (not re.fullmatch(r"[0-9a-f]{64}", owner_sha) or not owner_source.is_file()
            or owner_source.is_symlink() or _sha(owner_source) != owner_sha):
        raise ValueError("REPLAY_UNIVERSE_OWNER_SHA_MISMATCH")
    if not (roots["news_owner_root"] / "ops/collect_hourly_research_input.py").is_file():
        raise ValueError("REPLAY_NEWS_OWNER_CLOSURE_MISSING")
    if state_root is not None:
        state = _absolute_dir(state_root, "REPLAY_STATE_ROOT_INVALID")
        for template in _REQUIRED_STATE_INPUTS:
            path = state / template.format(date=date)
            if not path.is_file() or path.is_symlink():
                raise ValueError("REPLAY_REQUIRED_1530_INPUT_MISSING:" + path.name)
        for template in _PUBLISHED_OUTPUTS:
            if (state / template.format(date=date)).exists():
                raise ValueError("REPLAY_PUBLISHED_OUTPUT_ALREADY_EXISTS")
    return {"schema_version": SPEC_SCHEMA, "trade_date": date, "clock_iso": stamp.isoformat(),
            "materializer_app_root": str(app), "materializer_source_sha256": expected_sha,
            **{k: str(v) for k,v in roots.items()}, "universe_owner_sha256": owner_sha, **_FLAGS}


def _bounded_tree_manifest(root: Path, *, relative: Path | None = None) -> dict[str, str]:
    base = root / relative if relative is not None else root
    if not base.exists():
        return {}
    if base.is_symlink():
        raise ValueError("REPLAY_INPUT_TREE_SYMLINK")
    rows: dict[str, str] = {}
    total = 0
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise ValueError("REPLAY_INPUT_TREE_SYMLINK")
        if not path.is_file():
            continue
        raw = path.read_bytes(); total += len(raw)
        if len(rows) >= 1024 or total > 128 * 1024 * 1024:
            raise ValueError("REPLAY_INPUT_TREE_BUDGET_EXCEEDED")
        rows[path.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
    return rows


def _news_input_identity(root: Path, date: str) -> dict[str, Any]:
    from ops.materialize_manager_close_discovery import _news_paths
    root=Path(root)
    paths,prior_date=_news_paths(root,date)
    if len(paths)>1024:raise ValueError("REPLAY_NEWS_INPUT_COUNT_BUDGET_EXCEEDED")
    files:dict[str,str]={};total=0
    for path in paths:
        rel=path.relative_to(root).as_posix()
        if path.is_symlink() or not path.is_file():
            files[rel]="MISSING_OR_SYMLINK"
            continue
        raw=path.read_bytes();total+=len(raw)
        if len(raw)>16*1024*1024 or total>128*1024*1024:
            raise ValueError("REPLAY_NEWS_INPUT_BYTE_BUDGET_EXCEEDED")
        files[rel]=hashlib.sha256(raw).hexdigest()
    return {"prior_session_date":prior_date,"files":files}


def _identity_file_sha(path: Path) -> str:
    if path.is_symlink():return "SYMLINK"
    if not path.is_file():return "MISSING"
    try:return _sha(path)
    except OSError:return "UNREADABLE"


def _input_identity(spec: Mapping[str, Any], state: Path) -> dict[str, Any]:
    date = spec["trade_date"]
    history_path=state/f"workbench_research/{date}/inputs/1530_rebound_history.json"
    try:history=json.loads(history_path.read_bytes()) if history_path.is_file() and not history_path.is_symlink() else {}
    except (OSError,ValueError,TypeError):history={}
    if not isinstance(history,Mapping):history={}
    rebound_root = Path(spec["rebound_authority_root"])
    rebound_refs = {"assets/hk_0_2/panel_latest.json", "assets/hk_security_master/latest.json"}
    for row in history.get("source_files") or []:
        if isinstance(row, Mapping) and isinstance(row.get("artifact_ref"), str):
            rebound_refs.add(_safe_rel(row["artifact_ref"]).as_posix())
    rebound: dict[str, str] = {}
    for ref in sorted(rebound_refs):
        path = rebound_root / _safe_rel(ref)
        rebound[ref] = _identity_file_sha(path)
    state_inputs={}
    for template in _REQUIRED_STATE_INPUTS:
        rel=template.format(date=date); state_inputs[rel]=_identity_file_sha(state/rel)
    owner = Path(spec["universe_owner_root"]) / "stage_center/hk_universe_preflight.py"
    news = Path(spec["news_owner_root"]) / "ops/collect_hourly_research_input.py"
    try:universe_tree=_bounded_tree_manifest(Path(spec["universe_root"]),relative=Path("universes")/date)
    except (OSError,ValueError):universe_tree={"__identity_error__":"UNAVAILABLE_OR_UNSAFE"}
    try:news_inputs=_news_input_identity(Path(spec["data_root"]),date)
    except (OSError,ValueError,TypeError):news_inputs={"identity_error":"UNAVAILABLE_OR_UNSAFE"}
    from v4.manager_research.activation_canary import _materializer_app_inventory
    try:app_sources=_materializer_app_inventory(
        Path(spec["materializer_app_root"]), tolerate_missing=True, include_worker_files=False,
    )
    except (OSError,ValueError):app_sources={"__identity_error__":"UNAVAILABLE_OR_UNSAFE"}
    return {
        "state_inputs": state_inputs,
        "universe_date_tree": universe_tree,
        "rebound_inputs": rebound,
        "news_inputs":news_inputs,
        "materializer_app_sources":app_sources,
        "universe_owner_source_sha256": _identity_file_sha(owner),
        "news_owner_source_sha256": _identity_file_sha(news),
        "materializer_source_sha256": spec["materializer_source_sha256"],
    }


_CHILD = r'''
import json, os, pathlib, socket, subprocess, sys
from datetime import datetime
from zoneinfo import ZoneInfo
cfg=json.load(open(sys.argv[1],'r',encoding='utf-8'))
counts={'snapshot_fetch_calls':0,'external_process_calls':0,'network_calls':0}
def forbid_process(*a,**k):
    counts['external_process_calls']+=1
    raise RuntimeError('OFFLINE_REPLAY_EXTERNAL_PROCESS_FORBIDDEN')
def forbid_connect(*a,**k):
    counts['network_calls']+=1
    raise RuntimeError('OFFLINE_REPLAY_NETWORK_FORBIDDEN')
subprocess.run=forbid_process
subprocess.Popen=forbid_process
socket.create_connection=forbid_connect
socket.socket.connect=forbid_connect
root=pathlib.Path(cfg['materializer_app_root'])
for p in (root/'upstreams',root/'upstreams'/'v3_shared_data',root):
    if str(p) not in sys.path: sys.path.insert(0,str(p))
import ops.materialize_manager_close_discovery as m
if pathlib.Path(m.__file__).resolve()!=root/'ops/materialize_manager_close_discovery.py':
    raise SystemExit('REPLAY_MATERIALIZER_IMPORT_ORIGIN_MISMATCH')
import hashlib
if hashlib.sha256(pathlib.Path(m.__file__).read_bytes()).hexdigest()!=cfg['materializer_source_sha256']:
    raise SystemExit('REPLAY_MATERIALIZER_SOURCE_SHA_MISMATCH')
stamp=datetime.fromisoformat(cfg['clock_iso'])
def clock(): return stamp
def fetch(*a,**k):
    counts['snapshot_fetch_calls']+=1
    raise RuntimeError('OFFLINE_REPLAY_SNAPSHOT_FETCH_FORBIDDEN')
try:
    result=m.materialize(data_root=pathlib.Path(cfg['data_root']),universe_root=pathlib.Path(cfg['universe_root']),
        futu_python=pathlib.Path(sys.executable),trade_date=cfg['trade_date'],manager_state_root=pathlib.Path(cfg['state_root']),
        news_owner_root=pathlib.Path(cfg['news_owner_root']),app_root=root,clock=clock,
        universe_owner_root=pathlib.Path(cfg['universe_owner_root']),universe_owner_sha256=cfg['universe_owner_sha256'],
        snapshot_fetcher=fetch,rebound_authority_root=pathlib.Path(cfg['rebound_authority_root']))
except Exception as exc:
    reason='OFFLINE_REPLAY_MATERIALIZER_EXCEPTION:'+type(exc).__name__
    if str(exc) in {'OFFLINE_REPLAY_EXTERNAL_PROCESS_FORBIDDEN','OFFLINE_REPLAY_NETWORK_FORBIDDEN',
                    'OFFLINE_REPLAY_SNAPSHOT_FETCH_FORBIDDEN'}:
        reason+=':'+str(exc)
    result={'status':'FAILED','reason':reason}
print('V4_OFFLINE_REPLAY_RESULT='+json.dumps({'result':result,**counts},ensure_ascii=False,sort_keys=True))
'''


def execute_offline_replay(spec: Mapping[str, Any], *, state_root: str | Path) -> dict:
    counters = {"snapshot_fetch_calls": 0, "external_process_calls": 0, "network_calls": 0}
    try:
        state = _absolute_dir(state_root, "REPLAY_STATE_ROOT_INVALID")
        normalized = validate_replay_spec(spec, state_root=state)
        before = _input_identity(normalized, state)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"schema_version": RESULT_SCHEMA, "status": "SAFE_REPLAY_FAILED",
            "failure_reason": type(exc).__name__ + ":" + str(exc),
            "materializer_result": {"status": "INPUT_MISSING", "reason": str(exc)},
            "input_unchanged": True, **counters, **_FLAGS}
    env = {"PATH": str(Path(sys.executable).parent), "PYTHONNOUSERSITE":"1", "PYTHONDONTWRITEBYTECODE":"1",
           "PRODUCTION_ALLOWED":"false", "BUY_GATE_UPDATED":"false", "ORDERS_SENT":"false", "LANG":"C", "LC_ALL":"C"}
    with tempfile.TemporaryDirectory(prefix="manager-materializer-replay-child-") as temp:
        cfg = dict(normalized, state_root=str(state))
        cfg_path = Path(temp) / "config.json"
        cfg_path.write_text(json.dumps(cfg, sort_keys=True), encoding="utf-8")
        completed = subprocess.run([sys.executable, "-B", "-c", _CHILD, str(cfg_path)],
            cwd=normalized["materializer_app_root"], env=env, text=True, capture_output=True, timeout=90, check=False)
    marker = "V4_OFFLINE_REPLAY_RESULT="
    payload = None
    for line in completed.stdout.splitlines():
        if line.startswith(marker):
            payload = json.loads(line[len(marker):])
    if not isinstance(payload, dict):
        payload = {"result":{"status":"FAILED","reason":"OFFLINE_REPLAY_CHILD_FAILED"},
                   "snapshot_fetch_calls":0,"external_process_calls":0,"network_calls":0}
    after = _input_identity(normalized, state)
    safe_inputs = before == after
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {"status":"FAILED"}
    no_external = all(int(payload.get(key, 0)) == 0 for key in ("snapshot_fetch_calls","external_process_calls","network_calls"))
    success = completed.returncode == 0 and result.get("status") == "MATERIALIZED" and safe_inputs and no_external
    return {
        "schema_version": RESULT_SCHEMA,
        "status": "SAFE_REPLAY_SUCCEEDED" if success else "SAFE_REPLAY_FAILED",
        "trade_date": normalized["trade_date"],
        "materializer_result": result,
        "child_returncode": completed.returncode,
        "stderr_tail": completed.stderr[-2000:],
        "snapshot_fetch_calls": int(payload.get("snapshot_fetch_calls",0)),
        "external_process_calls": int(payload.get("external_process_calls",0)),
        "network_calls": int(payload.get("network_calls",0)),
        "input_unchanged": safe_inputs,
        "input_identity_sha256": hashlib.sha256(json.dumps(before,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
        "input_identity_before":before,
        "input_identity_after":after,
        **_FLAGS,
    }
