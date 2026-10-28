"""Read-only discovery of historical dates that are eligible for the R4 offline 15:30 replay canary.

The scanner never runs the materializer, never calls a producer, and never writes
inside Manager/V35 source roots.  It reuses the R4 replay validators and the old
materializer's read-only universe-evidence reader.  READY means only
"ready to run the existing compatibility canary", never that the canary passed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Callable, Mapping

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DATE_RE = re.compile(r"^\d{8}$")
_REQUIRED = (
    "1530_futu_snapshot.json",
    "1530_futu_snapshot.json.receipt.json",
    "1530_rebound_history.json",
)


@dataclass(frozen=True)
class ScanConfig:
    state_root: Path
    universe_root: Path
    data_root: Path
    news_owner_root: Path
    universe_owner_root: Path
    universe_owner_sha256: str
    rebound_authority_root: Path
    materializer_app_root: Path
    materializer_source_sha256: str
    max_dates: int = 120


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular_dir(path: Path, code: str) -> Path:
    path = path.expanduser()
    if not path.is_absolute() or path.resolve() != path or path.is_symlink() or not path.is_dir():
        raise ValueError(code)
    return path


def _regular_file(path: Path, code: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(code)
    return path


def _load_replay_api() -> SimpleNamespace:
    from v4.manager_research import materializer_replay as replay
    worker_module = Path(__file__).resolve().parents[2] / "v4/manager_research/materializer_replay.py"
    if Path(replay.__file__).resolve() != worker_module:
        raise RuntimeError("REPLAY_API_WORKER_ORIGIN_MISMATCH")
    return SimpleNamespace(
        build_replay_seed=replay.build_replay_seed,
        validate_replay_spec=replay.validate_replay_spec,
        input_identity=replay._input_identity,
    )


def _discover_dates(state_root: Path, *, max_dates: int) -> list[str]:
    workbench = state_root / "workbench_research"
    if not workbench.is_dir() or workbench.is_symlink():
        return []
    dates: list[str] = []
    for child in workbench.iterdir():
        if child.is_symlink() or not child.is_dir() or not _DATE_RE.fullmatch(child.name):
            continue
        try:
            datetime.strptime(child.name, "%Y%m%d")
        except ValueError:
            continue
        dates.append(child.name)
    dates.sort(reverse=True)
    return dates[:max_dates]


def _triple_paths(config: ScanConfig, date: str) -> list[Path]:
    base = config.state_root / "workbench_research" / date / "inputs"
    return [base / name for name in _REQUIRED]


def _state_path_problem(state_root: Path, path: Path) -> str | None:
    try:
        relative = path.relative_to(state_root)
        if state_root.is_symlink() or state_root.resolve() != state_root:
            return "OUTSIDE_STATE_ROOT"
    except (OSError, ValueError, RuntimeError):
        return "OUTSIDE_STATE_ROOT"
    cursor = state_root
    for part in relative.parts:
        cursor = cursor / part
        try:
            if cursor.is_symlink():
                return "SYMLINK"
            resolved = cursor.resolve(strict=False)
        except (OSError, RuntimeError):
            return "UNSAFE_PATH"
        if resolved != cursor:
            return "SYMLINK"
        if resolved != state_root and state_root not in resolved.parents:
            return "OUTSIDE_STATE_ROOT"
    return None


def _unsafe_triple_paths(config: ScanConfig, date: str) -> list[tuple[str, str]]:
    unsafe = []
    for path in _triple_paths(config, date):
        problem = _state_path_problem(config.state_root, path)
        if problem is not None:
            unsafe.append((path.relative_to(config.state_root).as_posix(), problem))
    return unsafe


def _triple_manifest(config: ScanConfig, date: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for path in _triple_paths(config, date):
        rel = path.relative_to(config.state_root).as_posix()
        problem = _state_path_problem(config.state_root, path)
        if problem is not None:
            rows[rel] = problem
        elif not path.is_file():
            rows[rel] = "MISSING"
        else:
            try:
                if _state_path_problem(config.state_root, path) is not None:
                    rows[rel] = "UNSAFE_PATH"
                    continue
                raw = path.read_bytes()
                if len(raw) > 32 * 1024 * 1024:
                    rows[rel] = "TOO_LARGE"
                else:
                    rows[rel] = hashlib.sha256(raw).hexdigest()
            except OSError:
                rows[rel] = "UNREADABLE"
    return rows


def _missing_triple(config: ScanConfig, date: str) -> list[str]:
    missing: list[str] = []
    for path in _triple_paths(config, date):
        if _state_path_problem(config.state_root, path) is not None or not path.is_file():
            missing.append(path.name)
    return missing


def _identity_safe(identity: Mapping[str, Any]) -> bool:
    if not isinstance(identity, dict):
        return False
    state_inputs = identity.get("state_inputs")
    universe_tree = identity.get("universe_date_tree")
    rebound = identity.get("rebound_inputs")
    news = identity.get("news_inputs")
    app_sources = identity.get("materializer_app_sources")
    if not isinstance(state_inputs, Mapping) or not state_inputs:
        return False
    if not isinstance(universe_tree, Mapping) or not universe_tree or "__identity_error__" in universe_tree:
        return False
    if not isinstance(rebound, Mapping) or not rebound:
        return False
    if not isinstance(news, Mapping) or news.get("identity_error"):
        return False
    if not isinstance(news.get("files"), Mapping):
        return False
    if not isinstance(app_sources, Mapping) or "__identity_error__" in app_sources:
        return False
    try:
        from v4.manager_research.activation_canary import _materializer_input_identity_valid
        # Apply the R4 receipt's complete shape/path gate here; the scanner
        # compares two actual snapshots after Universe validation below.
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return _materializer_input_identity_valid({
            "input_unchanged": True,
            "input_identity_before": identity,
            "input_identity_after": identity,
            "input_identity_sha256": digest,
        })
    except (ImportError, AttributeError, TypeError, ValueError, OSError, RecursionError):
        return False


_UNIVERSE_CHILD = r'''
import json, pathlib, socket, subprocess, sys
from datetime import datetime
cfg=json.load(open(sys.argv[1], 'r', encoding='utf-8'))
counts={'network_calls':0,'external_process_calls':0,'producer_calls':0}
def deny_process(*a,**k):
    counts['external_process_calls']+=1
    raise RuntimeError('READ_ONLY_UNIVERSE_VALIDATOR_PROCESS_FORBIDDEN')
def deny_connect(*a,**k):
    counts['network_calls']+=1
    raise RuntimeError('READ_ONLY_UNIVERSE_VALIDATOR_NETWORK_FORBIDDEN')
subprocess.run=deny_process
subprocess.Popen=deny_process
socket.create_connection=deny_connect
socket.socket.connect=deny_connect
root=pathlib.Path(cfg['materializer_app_root'])
for p in (root/'upstreams', root/'upstreams'/'v3_shared_data', root):
    if str(p) not in sys.path: sys.path.insert(0,str(p))
try:
    from domains.manager_research_evidence import read_universe_evidence
    stamp=datetime.fromisoformat(cfg['clock_iso'])
    def clock(): return stamp
    evidence=read_universe_evidence(
        pathlib.Path(cfg['universe_root']), cfg['trade_date'],
        authority_owner_root=pathlib.Path(cfg['universe_owner_root']),
        authority_owner_sha256=cfg['universe_owner_sha256'], clock=clock)
    source=getattr(evidence,'source',{}) or {}
    codes=list(getattr(evidence,'codes',()) or ())
    if not codes or not isinstance(source,dict):
        raise RuntimeError('UNIVERSE_EVIDENCE_EMPTY')
    out={'status':'VERIFIED','run_id':source.get('run_id'),'sha256':source.get('sha256'),
         'available_at':source.get('available_at'),'code_count':len(codes),**counts}
except Exception as exc:
    out={'status':'CANNOT_CONFIRM','reason':type(exc).__name__+':'+str(exc),**counts}
print('V4_REPLAY_READY_UNIVERSE='+json.dumps(out,ensure_ascii=False,sort_keys=True))
'''


def validate_universe_authority(*, config: ScanConfig, date: str, clock_iso: str) -> dict[str, Any]:
    payload = {
        "materializer_app_root": str(config.materializer_app_root),
        "universe_root": str(config.universe_root),
        "universe_owner_root": str(config.universe_owner_root),
        "universe_owner_sha256": config.universe_owner_sha256,
        "trade_date": date,
        "clock_iso": clock_iso,
    }
    with tempfile.TemporaryDirectory(prefix="manager-universe-readonly-") as temp:
        cfg = Path(temp) / "config.json"
        cfg.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-B", "-c", _UNIVERSE_CHILD, str(cfg)],
            cwd=config.materializer_app_root,
            env={"PATH": str(Path(sys.executable).parent), "PYTHONNOUSERSITE":"1", "PYTHONDONTWRITEBYTECODE":"1", "LANG":"C", "LC_ALL":"C"},
            text=True, capture_output=True, timeout=30, check=False,
        )
    marker = "V4_REPLAY_READY_UNIVERSE="
    for line in completed.stdout.splitlines():
        if line.startswith(marker):
            try:
                value = json.loads(line[len(marker):])
            except json.JSONDecodeError:
                break
            if isinstance(value, dict):
                value["validator_returncode"] = completed.returncode
                return value
    return {
        "status":"CANNOT_CONFIRM",
        "reason":"UNIVERSE_VALIDATOR_NO_RECEIPT",
        "network_calls":0,
        "external_process_calls":0,
        "producer_calls":0,
        "validator_returncode":completed.returncode,
    }


def _spec(config: ScanConfig, date: str, clock_iso: str, data_root: Path) -> dict[str, Any]:
    return {
        "schema_version":"v4.manager_close_offline_replay_spec.v1",
        "trade_date":date,
        "clock_iso":clock_iso,
        "materializer_app_root":str(config.materializer_app_root),
        "materializer_source_sha256":config.materializer_source_sha256,
        "data_root":str(data_root),
        "universe_root":str(config.universe_root),
        "news_owner_root":str(config.news_owner_root),
        "universe_owner_root":str(config.universe_owner_root),
        "universe_owner_sha256":config.universe_owner_sha256,
        "rebound_authority_root":str(config.rebound_authority_root),
    }


def _next_command(config: ScanConfig, date: str) -> str:
    q = shlex.quote
    return " ".join([
        "python3.14", "-m", "ops.build_manager_materializer_replay_seed",
        "--source-state-root", q(str(config.state_root)),
        "--destination-root", "<isolated-replay-root>",
        "--trade-date", date,
        "--materializer-app-root", q(str(config.materializer_app_root)),
        "--materializer-sha256", config.materializer_source_sha256,
        "--universe-root", q(str(config.universe_root)),
        "--news-owner-root", q(str(config.news_owner_root)),
        "--universe-owner-root", q(str(config.universe_owner_root)),
        "--universe-owner-sha256", config.universe_owner_sha256,
        "--rebound-authority-root", q(str(config.rebound_authority_root)),
        "--receipt", "<isolated-replay-root>/seed-receipt.json",
    ])


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def safe_receipt_destination(path: str | Path, config: ScanConfig) -> Path:
    """Canonicalize an optional output and keep it disjoint from every input root."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if ".." in candidate.parts or not candidate.name:
        raise ValueError("SCAN_RECEIPT_PATH_INVALID")
    if candidate.is_symlink():
        raise ValueError("SCAN_RECEIPT_SYMLINK_FORBIDDEN")
    cursor = Path(candidate.anchor)
    for part in candidate.parts[1:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("SCAN_RECEIPT_SYMLINK_FORBIDDEN")
        if cursor.exists() and not cursor.is_dir():
            raise ValueError("SCAN_RECEIPT_PARENT_INVALID")
    try:
        canonical_parent = candidate.parent.resolve(strict=False)
    except (OSError, RuntimeError):
        raise ValueError("SCAN_RECEIPT_PATH_INVALID") from None
    destination = canonical_parent / candidate.name
    if destination.is_symlink():
        raise ValueError("SCAN_RECEIPT_SYMLINK_FORBIDDEN")
    protected_roots = (
        config.state_root,
        config.universe_root,
        config.data_root,
        config.news_owner_root,
        config.universe_owner_root,
        config.rebound_authority_root,
        config.materializer_app_root,
    )
    for value in protected_roots:
        root = Path(value).expanduser()
        if not root.is_absolute():
            root = Path.cwd() / root
        try:
            root = root.resolve(strict=False)
        except (OSError, RuntimeError):
            raise ValueError("SCAN_PROTECTED_ROOT_INVALID") from None
        if _paths_overlap(destination, root) or _paths_overlap(destination.parent, root):
            raise ValueError("SCAN_RECEIPT_PROTECTED_ROOT_FORBIDDEN")
    return destination


def scan_replay_ready_dates(
    config: ScanConfig,
    *,
    replay_api: Any | None = None,
    universe_validator: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config = ScanConfig(
        state_root=_regular_dir(Path(config.state_root), "SCAN_STATE_ROOT_INVALID"),
        universe_root=_regular_dir(Path(config.universe_root), "SCAN_UNIVERSE_ROOT_INVALID"),
        data_root=_regular_dir(Path(config.data_root), "SCAN_DATA_ROOT_INVALID"),
        news_owner_root=_regular_dir(Path(config.news_owner_root), "SCAN_NEWS_OWNER_ROOT_INVALID"),
        universe_owner_root=_regular_dir(Path(config.universe_owner_root), "SCAN_UNIVERSE_OWNER_ROOT_INVALID"),
        universe_owner_sha256=config.universe_owner_sha256,
        rebound_authority_root=_regular_dir(Path(config.rebound_authority_root), "SCAN_REBOUND_ROOT_INVALID"),
        materializer_app_root=_regular_dir(Path(config.materializer_app_root), "SCAN_MATERIALIZER_APP_ROOT_INVALID"),
        materializer_source_sha256=config.materializer_source_sha256,
        max_dates=int(config.max_dates),
    )
    owner_source = _regular_file(config.universe_owner_root / "stage_center/hk_universe_preflight.py", "SCAN_UNIVERSE_OWNER_SOURCE_MISSING")
    materializer_source = _regular_file(config.materializer_app_root / "ops/materialize_manager_close_discovery.py", "SCAN_MATERIALIZER_SOURCE_MISSING")
    if not _SHA_RE.fullmatch(config.universe_owner_sha256) or _sha(owner_source) != config.universe_owner_sha256:
        raise ValueError("SCAN_UNIVERSE_OWNER_SHA_MISMATCH")
    if not _SHA_RE.fullmatch(config.materializer_source_sha256) or _sha(materializer_source) != config.materializer_source_sha256:
        raise ValueError("SCAN_MATERIALIZER_SHA_MISMATCH")
    if config.max_dates < 1 or config.max_dates > 500:
        raise ValueError("SCAN_MAX_DATES_INVALID")
    api = replay_api or _load_replay_api()
    validator = universe_validator or validate_universe_authority
    rows: list[dict[str, Any]] = []
    ready: list[str] = []
    validation_subprocesses = 0
    for date in _discover_dates(config.state_root, max_dates=config.max_dates):
        unsafe = _unsafe_triple_paths(config, date)
        if unsafe:
            symlinked = [rel for rel, reason in unsafe if reason == "SYMLINK"]
            reason = "REPLAY_ORIGIN_INPUT_SYMLINK:" + symlinked[0] if symlinked else "REPLAY_ORIGIN_INPUT_PATH_UNSAFE"
            rows.append({"date":date,"status":"NOT_READY","reason":reason,"unsafe_paths":[rel for rel,_ in unsafe]})
            continue
        missing = _missing_triple(config, date)
        if missing:
            rows.append({"date":date,"status":"NOT_READY","reason":"REPLAY_REQUIRED_1530_INPUT_MISSING","missing":missing})
            continue
        source_before = _triple_manifest(config, date)
        try:
            with tempfile.TemporaryDirectory(prefix=f"manager-replay-ready-{date}-") as temp:
                root = Path(temp).resolve()
                seed = root / "state_seed"
                api.build_replay_seed(config.state_root, seed, date)
                snapshot = json.loads((seed / f"workbench_research/{date}/inputs/1530_futu_snapshot.json").read_bytes())
                clock_iso = str(snapshot.get("available_at") or "")
                spec = _spec(config, date, clock_iso, root / "data")
                (root / "data").mkdir()
                normalized = api.validate_replay_spec(spec, state_root=seed)
                identity_before = api.input_identity(normalized, seed)
                if not _identity_safe(identity_before):
                    rows.append({"date":date,"status":"NOT_READY","reason":"REPLAY_INPUT_IDENTITY_UNSAFE","source_unchanged":True})
                    continue
                universe = validator(config=config, date=date, clock_iso=clock_iso)
                validation_subprocesses += 1
                identity_after = api.input_identity(normalized, seed)
                source_after = _triple_manifest(config, date)
                source_unchanged = source_before == source_after and identity_before == identity_after
                if not source_unchanged:
                    rows.append({"date":date,"status":"NOT_READY","reason":"SOURCE_CHANGED_DURING_SCAN","source_unchanged":False,"universe":universe})
                    continue
                if universe.get("status") != "VERIFIED":
                    rows.append({"date":date,"status":"NOT_READY","reason":str(universe.get("reason") or "UNIVERSE_AUTHORITY_UNVERIFIED"),"source_unchanged":True,"universe":universe})
                    continue
                if any(int(universe.get(key, 0)) != 0 for key in ("network_calls","external_process_calls","producer_calls")):
                    rows.append({"date":date,"status":"NOT_READY","reason":"UNIVERSE_VALIDATOR_SIDE_EFFECT_ATTEMPTED","source_unchanged":True,"universe":universe})
                    continue
                row = {
                    "date":date,
                    "status":"READY_FOR_REPLAY_CANARY",
                    "reason":"ALL_EXISTING_REPLAY_INPUTS_AND_UNIVERSE_AUTHORITY_VERIFIED",
                    "source_unchanged":True,
                    "universe":universe,
                    "next_command":_next_command(config,date),
                }
                rows.append(row)
                ready.append(date)
        except Exception as exc:
            source_after = _triple_manifest(config, date)
            rows.append({
                "date":date,
                "status":"NOT_READY",
                "reason":type(exc).__name__+":"+str(exc),
                "source_unchanged":source_before == source_after,
            })
    return {
        "schema_version":"v4.manager_research.replay_ready_date_scan.v1",
        "scanner_mode":"READ_ONLY_DISCOVERY",
        "dates":rows,
        "ready_dates":ready,
        "ready_count":len(ready),
        "network_requests":0,
        "producer_calls":0,
        "canary_runs":0,
        "validation_subprocesses":validation_subprocesses,
        "production_allowed":False,
        "buy_gate_updated":False,
        "orders_sent":False,
    }
