"""Read one explicitly approved research run without replacing Stage history.

The shipped binding pair is absent until candidate preparation verifies the
fixed R3 manifest and its transitive evidence. This module has no producer,
collector, scheduler, or persistence path. Selection and execution projections
remain the original R3 readers; a corrupt market cannot authenticate its rows.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Mapping, Sequence

from . import consumer as consumer_module
from . import execution_evidence as execution_module
from .consumer import StageSelectionConsumer, _bundle_artifact_id, _invalid_market_with_reason, _summary_status
from .execution_evidence import read_stage_execution


APPROVED_RESEARCH_RUN = {
    "trade_date": "20261009",
    "stage_id": "STAGE_0930_0935",
    "backfill_run_id": "85e29661ecd848fe9b8344ea59279e86",
    "run_manifest_sha256": "9b5df949141ed1533cb7a71e2c46bebe341bea663f5f966bda16225754e89857",
    "source_map_sha256": "3ec3e7774119bd106185c03be0b5c572b6fe2ca4148b93379d8b116a72994457",
    "candidate_source_manifest_sha256": "88ca1c64f6e80ec91feff01af2e7e9cf235bb16f91cacff400fede0f56430fa2",
    "selection_run_ids": {
        "A_SHARE": "run-2688466a1ae4464ba7237f0b",
        "HK_CONNECT": "run-cfbdc9b36a7308da178d193a",
    },
}
R3_READER_SHA256 = {
    "stage_center/consumer.py": "16f004edb60ab256993f02ec4df36caa5d2cb3aa55bff643834c3119ec86d207",
    "stage_center/execution_evidence.py": "1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b",
}
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}
SCHEMA = "stage_center.approved_research_read_binding.v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MARKETS = ("A_SHARE", "HK_CONNECT")
_READER_RELATIVE = "stage_center/research_read_binding.py"
_APP_RELATIVE = "apps/api/v35_api/app.py"
_MAX_BYTES = 8 * 1024 * 1024


class ResearchReadError(ValueError):
    """A fixed read binding or one of its shared trust anchors was refused."""


def _check(condition: bool, code: str) -> None:
    if not condition:
        raise ResearchReadError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(value: Path | str, *, directory: bool = False) -> Path:
    _check(isinstance(value, (str, Path)), "PATH_INVALID")
    path = Path(value).expanduser()
    _check(path.is_absolute() and ".." not in path.parts, "ABSOLUTE_PATH_REQUIRED")
    _check(not any(part.is_symlink() for part in (path, *path.parents)), "SYMLINK_PATH_REJECTED")
    if directory:
        _check(path.is_dir(), "DIRECTORY_UNAVAILABLE")
    return path


def _relative(value: Any) -> str:
    _check(isinstance(value, str) and bool(value) and "\\" not in value and "\x00" not in value,
           "RELATIVE_PATH_INVALID")
    path = PurePosixPath(value)
    _check(not path.is_absolute() and str(path) == value and
           not any(part in {".", ".."} for part in path.parts), "RELATIVE_PATH_INVALID")
    return value


def _read(path: Path | str) -> bytes:
    """Bounded regular-file read, rejecting every symlink component."""
    target = _path(path)
    try:
        observed = target.lstat()
        _check(stat.S_ISREG(observed.st_mode) and observed.st_size <= _MAX_BYTES, "REGULAR_FILE_REQUIRED")
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            opened = os.fstat(fd)
            _check(stat.S_ISREG(opened.st_mode) and
                   (opened.st_dev, opened.st_ino) == (observed.st_dev, observed.st_ino), "FILE_CHANGED_DURING_OPEN")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(_MAX_BYTES + 1)
            _check(len(raw) <= _MAX_BYTES, "FILE_TOO_LARGE")
            after = os.fstat(fd)
            _check((opened.st_size, opened.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
                   "FILE_CHANGED_DURING_READ")
        finally:
            os.close(fd)
        _path(target)
        final = target.lstat()
        _check((final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) ==
               (opened.st_dev, opened.st_ino, after.st_size, after.st_mtime_ns), "FILE_CHANGED_DURING_READ")
        return raw
    except OSError as error:
        raise ResearchReadError("FILE_UNAVAILABLE") from error


def _object(raw: bytes) -> dict[str, Any]:
    def unique(pairs):
        output = {}
        for key, value in pairs:
            _check(key not in output, "JSON_DUPLICATE_KEY")
            output[key] = value
        return output
    try:
        result = json.loads(raw, object_pairs_hook=unique,
                            parse_constant=lambda value: (_ for _ in ()).throw(ResearchReadError("JSON_NONFINITE")))
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, ResearchReadError):
            raise
        raise ResearchReadError("JSON_INVALID") from error
    _check(isinstance(result, dict), "JSON_OBJECT_REQUIRED")
    return result


def _safe_flags(value: Mapping[str, Any], code: str) -> None:
    _check(all(value.get(key) is expected for key, expected in FLAGS.items()), code)


def _module_observations() -> dict[str, tuple[Path, str]]:
    root = Path(__file__).absolute().parents[1]
    paths = {
        _READER_RELATIVE: Path(__file__).absolute(),
        "stage_center/consumer.py": Path(consumer_module.__file__).absolute(),
        "stage_center/execution_evidence.py": Path(execution_module.__file__).absolute(),
        _APP_RELATIVE: root / _APP_RELATIVE,
    }
    return {name: (path, _sha(_read(path))) for name, path in paths.items()}


# Record source observations when these particular reader modules are loaded;
# re-reading files later cannot silently bless different bytes or another root.
_LOADED_READER_SOURCES = _module_observations()


def _reader_sources(api_root: Path | str, expected_reader_sha256: str) -> dict[str, str]:
    root = _path(api_root, directory=True)
    _check(bool(_SHA.fullmatch(expected_reader_sha256 or "")), "READER_SOURCE_PIN_INVALID")
    expected = {**R3_READER_SHA256, _READER_RELATIVE: expected_reader_sha256,
                _APP_RELATIVE: _LOADED_READER_SOURCES[_APP_RELATIVE][1]}
    current = _module_observations()
    for name, required_sha in expected.items():
        path, loaded_sha = _LOADED_READER_SOURCES[name]
        _check(path == root / name and current[name] == (path, required_sha)
               and loaded_sha == required_sha, "READER_SOURCE_IDENTITY_MISMATCH:" + name)
    return expected


def _shared_contract(manifest_path: Path | str, history_root: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    approved = APPROVED_RESEARCH_RUN
    path, history = _path(manifest_path), _path(history_root, directory=True)
    raw = _read(path)
    _check(_sha(raw) == approved["run_manifest_sha256"], "RUN_MANIFEST_SHA_MISMATCH")
    manifest = _object(raw)
    _safe_flags(manifest, "MANIFEST_SAFETY_CONFLICT")
    _check(all(manifest.get(key) == value for key, value in {
        "schema_version": "V4_CURRENT_DAY_RESEARCH_CANARY_RUN_V1", "status": "RESEARCH_ROWS_WRITTEN",
        "trade_date": approved["trade_date"], "stage_id": approved["stage_id"],
        "execution_origin": "CURRENT_DAY_RESEARCH_REPLAY",
        "selection_run_id": approved["selection_run_ids"]["HK_CONNECT"],
        "source_map_sha256": approved["source_map_sha256"],
        "candidate_source_manifest_sha256": approved["candidate_source_manifest_sha256"],
    }.items()), "RUN_MANIFEST_IDENTITY_MISMATCH")
    _check(all(manifest.get(key) is True for key in
               ("executed", "execute_requested", "input_bytes_unchanged", "manual_replay", "historical_backfill"))
           and manifest.get("natural_verified") is False and manifest.get("errors") == []
           and manifest.get("selected_rows") == {market: 10 for market in _MARKETS}, "RUN_MANIFEST_RESEARCH_SCOPE_INVALID")
    paths = manifest.get("output_paths")
    _check(isinstance(paths, dict) and paths.get("run_manifest") == str(path), "RUN_MANIFEST_PATH_MISMATCH")
    base, backfill = path.parent, approved["backfill_run_id"]
    expected_roots = {name: base / role / "backfill" / backfill for name, role in
                      (("selection_root", "selection"), ("receipt_root", "receipts"), ("raw_root", "raw"))}
    for name, expected in expected_roots.items():
        _check(paths.get(name) == str(expected), "APPROVED_NAMESPACE_MISMATCH:" + name)
        _path(expected, directory=True)
    _check(history != base and history not in base.parents and base not in history.parents,
           "HISTORY_ROOT_OVERLAPS_RESEARCH_NAMESPACE")
    day, stage = approved["trade_date"], approved["stage_id"]
    receipt_path = expected_roots["receipt_root"] / day / stage / "receipt.json"
    _check(paths.get("owner_receipt") == str(receipt_path), "OWNER_RECEIPT_PATH_MISMATCH")
    owner_raw = _read(receipt_path)
    _check(_sha(owner_raw) == manifest.get("owner_receipt_sha256"), "OWNER_RECEIPT_SHA_MISMATCH")
    owner = _object(owner_raw)
    _safe_flags(owner, "OWNER_SAFETY_CONFLICT")
    _check(all(owner.get(key) == value for key, value in {
        "schema_version": "stage_center.runner.receipt.v1", "runner": "stage_center",
        "trade_date": day, "stage_id": stage, "mode": "BACKFILL", "backfill_run_id": backfill,
        "dispatch_mode": "RECOVERY", "due_status": "HISTORICAL_BACKFILL",
        "execution_origin": "CURRENT_DAY_RESEARCH_REPLAY",
        "namespace": {name: str(value) for name, value in expected_roots.items()},
    }.items()) and owner.get("natural_verified") is False and owner.get("write_performed") is True
           and owner.get("latest_updated") is False and owner.get("current_updated") is False,
           "OWNER_RESEARCH_IDENTITY_MISMATCH")
    history_ref = owner.get("receipt_history")
    _check(isinstance(history_ref, dict) and history_ref.get("sha256") == manifest.get("owner_history_sha256"),
           "OWNER_HISTORY_BINDING_MISMATCH")
    history_path = expected_roots["receipt_root"] / _relative(history_ref.get("relative_path"))
    _check(paths.get("owner_history_receipt") == str(history_path)
           and _sha(_read(history_path)) == manifest.get("owner_history_sha256"), "OWNER_HISTORY_SHA_MISMATCH")
    history_status, _ = execution_module._owner_history_binding(expected_roots["receipt_root"], owner, day, stage)
    _check(history_status == "OWNER_HISTORY_SHA_BOUND", "OWNER_HISTORY_IDENTITY_MISMATCH")
    source_map_path = _path(manifest.get("package"), directory=True) / "SOURCE_MAP.json"
    source_raw = _read(source_map_path)
    _check(_sha(source_raw) == approved["source_map_sha256"], "SOURCE_MAP_SHA_MISMATCH")
    mapping = _object(source_raw)
    rows = mapping.get("files")
    _check(isinstance(rows, list), "SOURCE_MAP_FILES_INVALID")
    required = {row["relative_path"]: row["after_sha256"] for row in rows
                if isinstance(row, dict) and row.get("group") == "stage"}
    stage_app = _path(manifest.get("stage_app"), directory=True)
    candidate_path = stage_app / "CANARY_SOURCE_MANIFEST.json"
    _check(_sha(_read(candidate_path)) == approved["candidate_source_manifest_sha256"], "CANDIDATE_SOURCE_MANIFEST_SHA_MISMATCH")
    sources = manifest.get("stage_sources")
    _check(isinstance(sources, list) and len(sources) == len(required)
           and {row.get("relative_path") for row in sources if isinstance(row, dict)} == set(required),
           "STAGE_SOURCE_SET_MISMATCH")
    source_bindings = []
    for row in sources:
        relative = _relative(row.get("relative_path"))
        actual = stage_app / relative
        _check(row.get("actual_path") == str(actual) and row.get("sha256") == required[relative]
               and _sha(_read(actual)) == required[relative], "STAGE_SOURCE_SHA_MISMATCH:" + relative)
        source_bindings.append({"relative_path": relative, "actual_path": str(actual), "sha256": required[relative]})
    declared = owner.get("selection_artifacts")
    _check(isinstance(declared, dict) and set(declared) == set(_MARKETS), "OWNER_MARKET_BINDINGS_INVALID")
    market_bindings = {}
    for market in _MARKETS:
        lane = declared[market]
        _check(isinstance(lane, dict) and lane.get("schema_version") == "stage_center.runner.selection_binding.v1"
               and lane.get("run_id") == approved["selection_run_ids"][market]
               and lane.get("selected_rows") == 10
               and all(key not in lane or lane[key] == value for key, value in
                       (("trade_date", day), ("stage_id", stage), ("market", market))),
               "OWNER_MARKET_IDENTITY_MISMATCH:" + market)
        market_bindings[market] = deepcopy(lane)
    document = {
        "schema_version": SCHEMA, "trade_date": day, "stage_id": stage, "backfill_run_id": backfill,
        "mode": "APPROVED_CURRENT_DAY_RESEARCH_READ_ONLY", "history_root": str(history),
        "manifest_path": str(path), "run_manifest_sha256": approved["run_manifest_sha256"],
        "selection_root": str(expected_roots["selection_root"]), "receipt_root": str(expected_roots["receipt_root"]),
        "owner_receipt_path": str(receipt_path), "owner_receipt_sha256": manifest["owner_receipt_sha256"],
        "owner_history_receipt_path": str(history_path), "owner_history_sha256": manifest["owner_history_sha256"],
        "source_map_path": str(source_map_path), "source_map_sha256": approved["source_map_sha256"],
        "candidate_source_manifest_path": str(candidate_path),
        "candidate_source_manifest_sha256": approved["candidate_source_manifest_sha256"],
        "stage_sources": sorted(source_bindings, key=lambda row: row["relative_path"]),
        "owner_runtime_source_identity": deepcopy(owner.get("runtime_source_identity")),
        "markets": market_bindings, "natural_verified": False, "execution_verified": False, **FLAGS,
    }
    return document, owner


def _verify_lane(consumer: StageSelectionConsumer, document: Mapping[str, Any], owner: Mapping[str, Any], market: str) -> None:
    day, stage = document["trade_date"], document["stage_id"]
    lane = document["markets"][market]
    original = (owner.get("markets") or {}).get(market)
    _check(isinstance(original, dict), "LANE_OWNER_MISSING")
    verified = consumer.store._verify_run(day, stage, market, lane["run_id"])
    envelope = verified["envelope"]
    # The original selection schema requires the three explicit false flags;
    # RESEARCH_ONLY is mandatory on the approved manifest/owner and response.
    _check(all(envelope.get(key) is False for key in FLAGS if key != "RESEARCH_ONLY")
           and ("RESEARCH_ONLY" not in envelope or envelope["RESEARCH_ONLY"] is True), "LANE_SAFETY_CONFLICT")
    _check(all(envelope.get(key) == lane.get(key) == original.get(key) for key in
               ("run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256", "selected_rows")),
           "LANE_IDENTITY_MISMATCH")
    binding = execution_module._selection_trio_binding(
        consumer.store, lane, original, {**envelope, "status": envelope["selection_status"],
                                      "_selection_store_verified": True}, day, stage, market, True)
    _check(binding.get("status") == "BOUND_TO_VERIFIED_SELECTION_TRIO", "LANE_TRIO_SHA_MISMATCH")
    entry = consumer.store._latest().get("entries", {}).get(consumer.store._key(day, stage, market))
    _check(isinstance(entry, dict) and all(entry.get(key) == value for key, value in {
        "run_id": lane["run_id"], "manifest_sha256": lane["manifest_canonical_sha256"],
        "receipt_sha256": lane["receipt_canonical_sha256"], "artifact_sha256": lane["artifact_bytes_sha256"],
    }.items()), "LANE_LATEST_IDENTITY_MISMATCH")


def build_research_read_binding(*, manifest_path: Path | str, history_root: Path | str,
                                api_after_root: Path | str) -> dict[str, Any]:
    """Return reviewed binding bytes' content; never write any source or state."""
    sources = _reader_sources(api_after_root, _LOADED_READER_SOURCES[_READER_RELATIVE][1])
    document, owner = _shared_contract(manifest_path, history_root)
    consumer = StageSelectionConsumer(document["selection_root"], execution_receipt_root=document["receipt_root"])
    for market in _MARKETS:
        _verify_lane(consumer, document, owner, market)
    # Detect shared anchors changing during the original reader's verification.
    repeated, _ = _shared_contract(manifest_path, history_root)
    _check(document == repeated, "EVIDENCE_CHANGED_DURING_PREPARATION")
    document["reader_sources"] = sources
    return document


class ApprovedResearchReadBinding:
    """Optional exact-date read routing; unrelated dates never inspect this tree."""

    def __init__(self, *, binding_path: Path | str, history_root: Path | str,
                 api_root: Path | str, expected_reader_sha256: str,
                 expected_binding_sha256: str | None = None, a_name_pool_root: Path | str | None = None):
        self.binding_path = Path(binding_path).expanduser()
        self.history_root = Path(history_root).expanduser()
        self.api_root = Path(api_root).expanduser()
        self.expected_reader_sha256 = expected_reader_sha256
        self.expected_binding_sha256 = expected_binding_sha256
        self.a_name_pool_root = a_name_pool_root

    def _binding(self) -> tuple[dict[str, Any], str] | None:
        path = _path(self.binding_path)
        sidecar = _path(path.with_suffix(".sha256"))
        exists, sidecar_exists = path.exists(), sidecar.exists()
        explicit = self.expected_binding_sha256
        if not exists and not sidecar_exists and explicit is None:
            return None
        _check(exists and (sidecar_exists or explicit is not None), "BINDING_PAIR_INCOMPLETE")
        if explicit is not None:
            _check(bool(_SHA.fullmatch(explicit)), "BINDING_SHA_PIN_INVALID")
        if sidecar_exists:
            raw_pin = _read(sidecar)
            _check(re.fullmatch(rb"[0-9a-f]{64}\n", raw_pin) is not None, "BINDING_SHA_SIDECAR_INVALID")
            sidecar_sha = raw_pin[:-1].decode("ascii")
            _check(explicit is None or explicit == sidecar_sha, "BINDING_SHA_PIN_CONFLICT")
            explicit = sidecar_sha
        raw = _read(path)
        _check(_sha(raw) == explicit, "BINDING_SHA_MISMATCH")
        return _object(raw), explicit

    def get(self, trade_date: str, stage_id: str, *, markets: Sequence[str] | None = None,
            backfill_run_id: str | None = None) -> dict[str, Any] | None:
        approved = APPROVED_RESEARCH_RUN
        if (trade_date, stage_id) != (approved["trade_date"], approved["stage_id"]):
            return None
        if backfill_run_id is not None and backfill_run_id != approved["backfill_run_id"]:
            return None
        requested = _MARKETS if markets is None else tuple(markets)
        if not requested or len(set(requested)) != len(requested) or any(market not in _MARKETS for market in requested):
            return None
        loaded = self._binding()
        if loaded is None:
            return None
        document, binding_sha = loaded
        _check(document.get("history_root") == str(_path(self.history_root, directory=True)), "HISTORY_ROOT_BINDING_MISMATCH")
        sources = _reader_sources(self.api_root, self.expected_reader_sha256)
        expected, owner = _shared_contract(document.get("manifest_path"), self.history_root)
        expected["reader_sources"] = sources
        _check(document == expected, "CONFIG_EVIDENCE_BINDING_MISMATCH")
        consumer = StageSelectionConsumer(document["selection_root"], a_name_pool_root=self.a_name_pool_root,
                                          execution_receipt_root=document["receipt_root"])
        payload = consumer.get(trade_date, stage_id, markets=requested)
        for market in requested:
            try:
                _verify_lane(consumer, document, owner, market)
                _check(payload["markets"][market].get("run_id") == document["markets"][market]["run_id"],
                       "LANE_PROJECTION_IDENTITY_MISMATCH")
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                payload["markets"][market] = _invalid_market_with_reason(market, "APPROVED_RESEARCH_SELECTION_IDENTITY_INVALID")
        payload["execution_evidence"] = read_stage_execution(
            Path(document["receipt_root"]), trade_date, stage_id, payload["markets"], selection_store=consumer.store)
        execution = payload["execution_evidence"]
        for key in ("markets", "selection_results", "selection_artifact_bindings"):
            execution[key] = {market: value for market, value in (execution.get(key) or {}).items() if market in requested}
        for market, lane in payload["markets"].items():
            lane.update(FLAGS)
            if not lane.get("run_id"):
                continue
            bound = document["markets"][market]
            lane.update(selection_mode="BACKFILL", backfill_run_id=approved["backfill_run_id"],
                        backfill_run_ids=[approved["backfill_run_id"]],
                        selection_manifest_sha256=bound["manifest_canonical_sha256"],
                        selection_receipt_sha256=bound["receipt_canonical_sha256"],
                        selection_artifact_sha256=bound["artifact_bytes_sha256"],
                        selection_manifest_receipt_verified=True, runner_receipt_verified=True,
                        runner_receipt_status="VERIFIED", runner_receipt_sha256=document["owner_receipt_sha256"],
                        research_read_binding={**deepcopy(bound), "runner_receipt_sha256": document["owner_receipt_sha256"],
                                               "owner_history_sha256": document["owner_history_sha256"],
                                               "run_manifest_sha256": document["run_manifest_sha256"]})
        repeated, _ = _shared_contract(document["manifest_path"], self.history_root)
        repeated["reader_sources"] = _reader_sources(self.api_root, self.expected_reader_sha256)
        _check(repeated == document and self._binding() == loaded, "EVIDENCE_CHANGED_DURING_READ")
        projected = list(payload["markets"].values())
        payload["status"] = _summary_status(projected)
        bundle = _bundle_artifact_id(trade_date, stage_id, projected)
        payload.update(artifact_id=bundle, bundle_artifact_id=bundle,
                       run_id=projected[0].get("run_id") if len(projected) == 1 else None,
                       backfill_run_id=approved["backfill_run_id"], mode="BACKFILL",
                       natural_verified=False, execution_verified=False, **FLAGS)
        payload["research_read_binding"] = {
            "schema_version": SCHEMA, "status": "EXACT_APPROVED_RESEARCH_BINDING_VERIFIED",
            "binding_sha256": binding_sha, "run_manifest_sha256": document["run_manifest_sha256"],
            "source_map_sha256": document["source_map_sha256"],
            "candidate_source_manifest_sha256": document["candidate_source_manifest_sha256"],
            "owner_receipt_sha256": document["owner_receipt_sha256"], "owner_history_sha256": document["owner_history_sha256"],
            "reader_sources": sources, "history_root_preserved": True,
            "history_root_contract": "UNCHANGED_CONFIGURED_SELECTION_ROOT",
            "research_root_contract": "EXACT_IMMUTABLE_MANIFEST_NAMESPACE",
            "execution_verified": False, "natural_verified": False,
        }
        return payload
