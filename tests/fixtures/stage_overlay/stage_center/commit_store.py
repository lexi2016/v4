"""Fail-closed commit and read gate for strict Stage generations.

The legacy RawStore/SelectionStore pointers remain unchanged. Strict dispatch
uses those stores only below one private generation, then exposes it through a
commit receipt plus an external terminal witness. Every strict reader enters
the same short, non-blocking lock before resolving that pair.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from stage_center.calendar import eligible_stage_markets
from stage_center.contracts import SAFETY_FLAGS, STAGE_BY_ID


DEADLINE_BUDGET_NS = 5_000_000_000
STRICT_PUBLICATION_MODE = "strict_commit_required"
RUNTIME_CONFIG_PATH = Path(__file__).resolve().parents[1] / "stage_center_tick_config.json"
_SHA256 = frozenset("0123456789abcdef")


class StageCommitError(ValueError):
    """A strict generation or its one visibility proof cannot be verified."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha_file(path: Path) -> str:
    value = _read_object(path)
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return sha256_bytes(encoded)


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _assert_no_symlink(path: Path, *, root: Path | None = None) -> None:
    absolute = Path(os.path.abspath(path))
    base = Path(os.path.abspath(root)) if root is not None else absolute.parent
    try:
        relative = absolute.relative_to(base)
    except ValueError as error:
        raise StageCommitError("PATH_OUTSIDE_TRUSTED_ROOT") from error
    cursor = base
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise StageCommitError(f"SYMLINK_PATH_REJECTED:{cursor}")


def _write_json_durable(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_symlink(path)
    encoded = (json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise StageCommitError(f"STRICT_PROOF_MISSING:{path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StageCommitError(f"STRICT_PROOF_INVALID:{path.name}") from error
    if not isinstance(value, dict):
        raise StageCommitError(f"STRICT_PROOF_INVALID:{path.name}")
    return value


def runtime_config() -> dict[str, Any]:
    """Load only packaged Stage policy/config; absence of the strict key is legacy."""
    try:
        payload = json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {"_config_error": f"STAGE_RUNTIME_CONFIG_INVALID:{type(error).__name__}"}
    return payload if isinstance(payload, dict) else {"_config_error": "STAGE_RUNTIME_CONFIG_INVALID:OBJECT_REQUIRED"}


def publication_mode(config: Mapping[str, Any] | None = None) -> str:
    payload = runtime_config() if config is None else dict(config)
    if payload.get("_config_error"):
        return "invalid"
    mode = payload.get("publication_mode")
    if mode in (None, "", "legacy"):
        return "legacy"
    return str(mode)


def configured_receipt_root(config: Mapping[str, Any] | None = None) -> Path:
    payload = runtime_config() if config is None else dict(config)
    value = payload.get("receipt_root")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise StageCommitError("STRICT_RECEIPT_ROOT_INVALID")
    return Path(value).expanduser()


def _validate_date_stage(trade_date: str, stage_id: str) -> None:
    if len(trade_date) != 8 or not trade_date.isdigit():
        raise StageCommitError("TRADE_DATE_INVALID")
    try:
        from datetime import datetime

        datetime.strptime(trade_date, "%Y%m%d")
    except ValueError as error:
        raise StageCommitError("TRADE_DATE_INVALID") from error
    if stage_id not in STAGE_BY_ID:
        raise StageCommitError("STAGE_ID_INVALID")


def _under(base: Path, path: Path) -> Path:
    base = Path(os.path.abspath(base))
    path = Path(os.path.abspath(path))
    try:
        relative = path.relative_to(base)
    except ValueError as error:
        raise StageCommitError("GENERATION_OUTSIDE_COMMIT_ROOT") from error
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise StageCommitError("GENERATION_PATH_INVALID")
    _assert_no_symlink(path, root=base)
    resolved_base = base.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_base):
        raise StageCommitError("GENERATION_PATH_ESCAPE")
    return relative


def _evidence_map(value: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if isinstance(value, (list, tuple)):
        for item in value:
            text = str(item)
            key, separator, field = text.partition("=")
            if separator and key and field:
                result[key] = field
    return result


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in _SHA256 for char in value)


def _validate_hk_d1_evidence(evidence: Mapping[str, str], trade_date: str) -> dict[str, Any]:
    pool_sha = evidence.get("hk_d1_json_sha256") or evidence.get("hk_d1_sha256")
    binding_sha = evidence.get("hk_d1_binding_sha256")
    membership = evidence.get("hk_d1_membership")
    if not _is_sha(pool_sha) or not _is_sha(binding_sha) or pool_sha != binding_sha:
        raise StageCommitError("HK_D1_BINDING_SHA_MISSING_OR_MISMATCHED")
    if membership != "exact_date_top100":
        raise StageCommitError("HK_D1_MEMBERSHIP_ROLE_INVALID")
    source_date = evidence.get("hk_d1_source_trade_date")
    signal_date = evidence.get("hk_d1_source_signal_date")
    manifest_sha = evidence.get("hk_d1_source_manifest_sha256")
    receipt_sha = evidence.get("hk_d1_source_receipt_sha256")
    if source_date or signal_date or manifest_sha or receipt_sha:
        if (
            not source_date or len(source_date) != 8 or not source_date.isdigit()
            or source_date >= trade_date
            or not signal_date or len(signal_date) != 8 or not signal_date.isdigit()
            or signal_date >= source_date
            or not _is_sha(manifest_sha) or not _is_sha(receipt_sha)
        ):
            raise StageCommitError("HK_PRIOR_D1_SOURCE_IDENTITY_INCOMPLETE")
    return {
        "binding_sha256": binding_sha,
        "pool_sha256": pool_sha,
        "membership": membership,
        "source_trade_date": source_date,
        "source_signal_date": signal_date,
        "source_manifest_sha256": manifest_sha,
        "source_receipt_sha256": receipt_sha,
        "source_path": evidence.get("hk_d1_json"),
    }


def _expected_markets(trade_date: str, stage_id: str) -> tuple[str, ...]:
    try:
        return eligible_stage_markets(STAGE_BY_ID[stage_id].markets, trade_date)
    except (KeyError, ValueError) as error:
        raise StageCommitError("STAGE_MARKET_CALENDAR_UNVERIFIED") from error


def _safety_is_false(payload: Mapping[str, Any]) -> bool:
    return all(payload.get(flag) is False for flag in SAFETY_FLAGS)


class StageCommitStore:
    """One commit receipt and one SHA-bound terminal witness per Stage slot."""

    def __init__(
        self,
        receipt_root: Path | str,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.root = Path(receipt_root).expanduser()
        if self.root.is_symlink():
            raise StageCommitError("RECEIPT_ROOT_SYMLINK")
        self.monotonic_ns = monotonic_ns

    def make_lock(self):
        from stage_center.runner import SlotLock

        return SlotLock(self.root / ".strict-commit-read.lock")

    def commit_path(self, trade_date: str, stage_id: str) -> Path:
        _validate_date_stage(trade_date, stage_id)
        return self.root / trade_date / stage_id / "strict_commit.json"

    def witness_path(self, trade_date: str, stage_id: str) -> Path:
        return self.root / trade_date / stage_id / "strict_commit_witness.json"

    def _generation(self, path: Path) -> tuple[Path, str]:
        base = self.root / ".stage_generations"
        relative = _under(base, path)
        return path, (Path(".stage_generations") / relative).as_posix()

    def _verify_generation(
        self,
        *,
        trade_date: str,
        stage_id: str,
        generation_root: Path,
        child_result: Mapping[str, Any],
    ) -> dict[str, Any]:
        from stage_center.raw_store import RawStore
        from stage_center.selection import SelectionStore

        _validate_date_stage(trade_date, stage_id)
        expected = _expected_markets(trade_date, stage_id)
        child_markets = child_result.get("markets")
        if (
            child_result.get("trade_date") != trade_date
            or child_result.get("stage_id") != stage_id
            or child_result.get("status") not in {"READY", "READY_EMPTY"}
            or child_result.get("write_performed") is not True
            or not _safety_is_false(child_result)
            or not isinstance(child_markets, Mapping)
            or tuple(sorted(child_markets)) != tuple(sorted(expected))
        ):
            raise StageCommitError("CHILD_RESULT_NOT_COMPLETE_READY")
        generation, generation_relative = self._generation(generation_root)
        raw_root = generation / "raw"
        selection_root = generation / "selection"
        raw = RawStore(raw_root)
        selection = SelectionStore(selection_root)
        bundle = raw.read_verified_bundle(trade_date, stage_id)
        bundle_receipt = bundle.get("receipt")
        if (
            not isinstance(bundle_receipt, Mapping)
            or bundle_receipt.get("status") != child_result.get("status")
            or set(bundle_receipt.get("markets", {})) != set(expected)
            or not _safety_is_false(bundle_receipt)
        ):
            raise StageCommitError("RAW_BUNDLE_NOT_COMPLETE_READY")
        bundle_path = raw_root / str(bundle.get("receipt_relative") or "")
        if not bundle_path.is_file() or bundle_path.is_symlink():
            raise StageCommitError("RAW_BUNDLE_RECEIPT_MISSING")
        bundle_info = {
            "bundle_id": bundle_receipt.get("bundle_id"),
            "receipt_relative": bundle.get("receipt_relative"),
            "receipt_sha256": sha256_file(bundle_path),
            "bundle_status": bundle_receipt.get("status"),
        }
        raw_market_entries = bundle_receipt["markets"]
        selection_latest = selection._latest()
        selection_entries = selection_latest.get("entries")
        if not isinstance(selection_entries, Mapping):
            raise StageCommitError("SELECTION_LATEST_INVALID")
        market_proofs: dict[str, dict[str, Any]] = {}
        market_envelopes: dict[str, dict[str, Any]] = {}
        hk_identity: dict[str, Any] | None = None
        for market in expected:
            raw_entry = raw_market_entries.get(market)
            child_lane = child_markets.get(market)
            key = f"{trade_date}/{stage_id}/{market}"
            selection_entry = selection_entries.get(key)
            if not isinstance(raw_entry, Mapping) or not isinstance(child_lane, Mapping) or not isinstance(selection_entry, Mapping):
                raise StageCommitError(f"MARKET_TRIO_MISSING:{market}")
            if (
                child_lane.get("status") != child_result.get("status")
                or child_lane.get("selection_status") != child_result.get("status")
                or any(selection_entry.get(flag) is not False for flag in SAFETY_FLAGS)
            ):
                raise StageCommitError(f"MARKET_STATUS_MISMATCH:{market}")
            envelope = selection.read_verified(trade_date, stage_id, market)
            market_envelopes[market] = envelope
            selection_verified = selection._verify_run(
                trade_date, stage_id, market, str(selection_entry.get("run_id") or "")
            )
            if (
                envelope.get("trade_date") != trade_date
                or envelope.get("stage_id") != stage_id
                or envelope.get("market") != market
                or envelope.get("raw_artifact_sha256") != raw_entry.get("artifact_sha256")
                or child_lane.get("selected_rows") != envelope.get("selected_rows")
                or not _safety_is_false(envelope)
            ):
                raise StageCommitError(f"SELECTION_RAW_BINDING_INVALID:{market}")
            selection_run_id = str(selection_entry.get("run_id") or "")
            selection_role = SelectionStore._role(stage_id, market)
            selection_prefix = selection_root / "selection_runs" / trade_date / selection_role / selection_run_id
            selection_receipt = selection_prefix / "receipt.json"
            selection_manifest = selection_prefix / "manifest.json"
            selection_artifact = selection_prefix / "artifact.csv"
            if not all(path.is_file() and not path.is_symlink() for path in (selection_receipt, selection_manifest, selection_artifact)):
                raise StageCommitError(f"SELECTION_TRIO_MISSING:{market}")
            if (
                selection_verified.get("receipt_sha256") != selection_entry.get("receipt_sha256")
                or selection_verified.get("manifest_sha256") != selection_entry.get("manifest_sha256")
                or sha256_file(selection_artifact) != selection_entry.get("artifact_sha256")
            ):
                raise StageCommitError(f"SELECTION_TRIO_SHA_MISMATCH:{market}")
            raw_run_id = str(raw_entry.get("run_id") or "")
            raw_relative = raw_entry.get("artifact_relative")
            if not isinstance(raw_relative, str):
                raise StageCommitError(f"RAW_ARTIFACT_PATH_MISSING:{market}")
            raw_artifact = _under(raw_root, raw_root / raw_relative)
            raw_prefix = raw_root / raw_artifact.parent
            raw_receipt = raw_prefix / "receipt.json"
            raw_manifest = raw_prefix / "manifest.json"
            raw_artifact_path = raw_root / raw_artifact
            if not all(path.is_file() and not path.is_symlink() for path in (raw_receipt, raw_manifest, raw_artifact_path)):
                raise StageCommitError(f"RAW_TRIO_MISSING:{market}")
            if (
                _canonical_json_sha_file(raw_receipt) != raw_entry.get("receipt_sha256")
                or _canonical_json_sha_file(raw_manifest) != raw_entry.get("manifest_sha256")
                or sha256_file(raw_artifact_path) != raw_entry.get("artifact_sha256")
            ):
                raise StageCommitError(f"RAW_TRIO_SHA_MISMATCH:{market}")
            market_proofs[market] = {
                "raw_run_id": raw_run_id,
                "raw_artifact_sha256": raw_entry.get("artifact_sha256"),
                "raw_manifest_sha256": raw_entry.get("manifest_sha256"),
                "raw_receipt_sha256": raw_entry.get("receipt_sha256"),
                "selection_run_id": selection_run_id,
                "selection_role": selection_role,
                "selection_status": envelope.get("selection_status"),
                "selected_rows": envelope.get("selected_rows"),
                "selection_artifact_sha256": selection_entry.get("artifact_sha256"),
                "selection_manifest_sha256": selection_entry.get("manifest_sha256"),
                "selection_receipt_sha256": selection_entry.get("receipt_sha256"),
            }
            if market == "HK_CONNECT":
                hk_identity = _validate_hk_d1_evidence(
                    _evidence_map(envelope.get("source_evidence")), trade_date
                )
        if "HK_CONNECT" in expected and hk_identity is None:
            raise StageCommitError("HK_D1_IDENTITY_MISSING")
        return {
            "generation_relative": generation_relative,
            "markets": list(expected),
            "market_proofs": market_proofs,
            "market_envelopes": market_envelopes,
            "bundle": bundle_info,
            "hk_d1_source_identity": hk_identity,
            "stage_status": child_result.get("status"),
        }

    def _paths(self, trade_date: str, stage_id: str) -> tuple[Path, Path]:
        return self.commit_path(trade_date, stage_id), self.witness_path(trade_date, stage_id)

    def _failure(self, trade_date: str, stage_id: str, reason: str) -> dict[str, Any]:
        commit_path, witness_path = self._paths(trade_date, stage_id)
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "reason": reason,
            "commit_receipt_path": str(commit_path),
            "witness_path": str(witness_path),
            "markets": {},
            "cannot_confirm": [reason],
            **SAFETY_FLAGS,
        }

    def commit_generation(
        self,
        *,
        trade_date: str,
        stage_id: str,
        generation_root: Path | str,
        child_result: Mapping[str, Any],
        entry_monotonic_ns: int,
        deadline_monotonic_ns: int,
        supervisor: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Verify private output, durably publish the receipt, then witness its SHA."""
        try:
            _validate_date_stage(trade_date, stage_id)
            if deadline_monotonic_ns != entry_monotonic_ns + DEADLINE_BUDGET_NS:
                raise StageCommitError("ABSOLUTE_DEADLINE_CONTRACT_MISMATCH")
            if self.monotonic_ns() > deadline_monotonic_ns:
                raise StageCommitError("DEADLINE_EXCEEDED_BEFORE_VALIDATION")
            verified = self._verify_generation(
                trade_date=trade_date, stage_id=stage_id,
                generation_root=Path(generation_root), child_result=child_result,
            )
            if self.monotonic_ns() > deadline_monotonic_ns:
                raise StageCommitError("DEADLINE_EXCEEDED_DURING_VALIDATION")
        except (OSError, TypeError, ValueError, KeyError) as error:
            return self._failure(trade_date, stage_id, str(error) or type(error).__name__)

        lock = self.make_lock()
        if not lock.acquire():
            return self._failure(trade_date, stage_id, "STRICT_COMMIT_LOCK_UNAVAILABLE")
        commit_path, witness_path = self._paths(trade_date, stage_id)
        try:
            if self.monotonic_ns() > deadline_monotonic_ns:
                raise StageCommitError("DEADLINE_EXCEEDED_WAITING_FOR_COMMIT_LOCK")
            commit_path.parent.mkdir(parents=True, exist_ok=True)
            _assert_no_symlink(commit_path, root=self.root)
            generation, generation_relative = self._generation(Path(generation_root))
            transaction_id = uuid4().hex
            receipt = {
                "schema_version": "stage_center.strict_commit.v1",
                "status": "READY_PENDING_TERMINAL_WITNESS",
                "transaction_id": transaction_id,
                "release_id": runtime_config().get("release_id"),
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": verified["markets"],
                "stage_status": verified["stage_status"],
                "generation_relative": generation_relative,
                "market_proofs": verified["market_proofs"],
                "bundle": verified["bundle"],
                "hk_d1_source_identity": verified["hk_d1_source_identity"],
                "entry_monotonic_ns": entry_monotonic_ns,
                "deadline_monotonic_ns": deadline_monotonic_ns,
                "deadline_budget_ns": DEADLINE_BUDGET_NS,
                "supervisor": dict(supervisor or {}),
                **SAFETY_FLAGS,
            }
            _write_json_durable(commit_path, receipt)
            readback_bytes = commit_path.read_bytes()
            readback = json.loads(readback_bytes.decode("utf-8"))
            if readback != receipt:
                raise StageCommitError("STRICT_COMMIT_READBACK_MISMATCH")
            commit_sha = sha256_bytes(readback_bytes)
            receipt_readback_ns = self.monotonic_ns()
            terminal_ns = self.monotonic_ns()
            elapsed_ns = terminal_ns - entry_monotonic_ns
            on_time = terminal_ns <= deadline_monotonic_ns
            witness = {
                "schema_version": "stage_center.strict_commit_witness.v1",
                "status": "COMMITTED" if on_time else "ABORTED",
                "witness_source": "STAGE_PARENT_AFTER_COMMIT_FSYNC_READBACK",
                "transaction_id": transaction_id,
                "trade_date": trade_date,
                "stage_id": stage_id,
                "commit_receipt_sha256": commit_sha,
                "receipt_readback_monotonic_ns": receipt_readback_ns,
                "terminal_monotonic_ns": terminal_ns,
                "entry_monotonic_ns": entry_monotonic_ns,
                "deadline_monotonic_ns": deadline_monotonic_ns,
                "deadline_budget_ns": DEADLINE_BUDGET_NS,
                "elapsed_ns": elapsed_ns,
                "deadline_verified": bool(on_time),
                "reason": None if on_time else "END_TO_END_5S_EXCEEDED",
                **SAFETY_FLAGS,
            }
            try:
                _write_json_durable(witness_path, witness)
            except Exception:
                try:
                    witness_path.unlink()
                    _fsync_dir(witness_path.parent)
                except OSError:
                    pass
                raise
            if not on_time:
                return self._failure(trade_date, stage_id, "END_TO_END_5S_EXCEEDED")
            stage_status = str(verified["stage_status"])
            return {
                "status": stage_status,
                "stage_status": stage_status,
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": verified["market_envelopes"],
                "transaction_id": transaction_id,
                "commit_receipt_sha256": commit_sha,
                "commit_receipt_path": str(commit_path),
                "witness_path": str(witness_path),
                "terminal_monotonic_ns": terminal_ns,
                "elapsed_ns": elapsed_ns,
                "deadline_verified": True,
                "write_performed": False,
                "cannot_confirm": [],
                **SAFETY_FLAGS,
            }
        except (OSError, TypeError, ValueError, KeyError) as error:
            try:
                witness_path.unlink()
                _fsync_dir(witness_path.parent)
            except OSError:
                pass
            return self._failure(trade_date, stage_id, str(error) or type(error).__name__)
        finally:
            lock.release()

    def _read_unlocked(
        self,
        trade_date: str,
        stage_id: str,
        markets: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        commit_path, witness_path = self._paths(trade_date, stage_id)
        try:
            _assert_no_symlink(commit_path, root=self.root)
            _assert_no_symlink(witness_path, root=self.root)
            receipt_bytes = commit_path.read_bytes()
            receipt = _read_object(commit_path)
            witness = _read_object(witness_path)
            commit_sha = sha256_bytes(receipt_bytes)
            if (
                receipt.get("schema_version") != "stage_center.strict_commit.v1"
                or receipt.get("status") != "READY_PENDING_TERMINAL_WITNESS"
                or receipt.get("trade_date") != trade_date
                or receipt.get("stage_id") != stage_id
                or receipt.get("stage_status") not in {"READY", "READY_EMPTY"}
                or not _safety_is_false(receipt)
            ):
                raise StageCommitError("STRICT_COMMIT_CONTRACT_INVALID")
            transaction_id = receipt.get("transaction_id")
            if (
                witness.get("schema_version") != "stage_center.strict_commit_witness.v1"
                or witness.get("status") != "COMMITTED"
                or witness.get("witness_source") != "STAGE_PARENT_AFTER_COMMIT_FSYNC_READBACK"
                or witness.get("commit_receipt_sha256") != commit_sha
                or witness.get("transaction_id") != transaction_id
                or witness.get("trade_date") != trade_date
                or witness.get("stage_id") != stage_id
                or witness.get("deadline_verified") is not True
                or not _safety_is_false(witness)
            ):
                raise StageCommitError("STRICT_TERMINAL_WITNESS_INVALID")
            entry_ns = receipt.get("entry_monotonic_ns")
            deadline_ns = receipt.get("deadline_monotonic_ns")
            terminal_ns = witness.get("terminal_monotonic_ns")
            readback_ns = witness.get("receipt_readback_monotonic_ns")
            elapsed_ns = witness.get("elapsed_ns")
            if (
                type(entry_ns) is not int or type(deadline_ns) is not int
                or type(terminal_ns) is not int or type(readback_ns) is not int
                or type(elapsed_ns) is not int
                or receipt.get("deadline_budget_ns") != DEADLINE_BUDGET_NS
                or witness.get("deadline_budget_ns") != DEADLINE_BUDGET_NS
                or deadline_ns != entry_ns + DEADLINE_BUDGET_NS
                or not entry_ns <= readback_ns <= terminal_ns <= deadline_ns
                or elapsed_ns != terminal_ns - entry_ns
            ):
                raise StageCommitError("STRICT_TERMINAL_TIME_INVALID")
            expected = tuple(receipt.get("markets") or ())
            if tuple(sorted(expected)) != tuple(sorted(_expected_markets(trade_date, stage_id))):
                raise StageCommitError("STRICT_MARKET_SET_INVALID")
            if markets is not None and tuple(sorted(markets)) != tuple(sorted(expected)):
                raise StageCommitError("STRICT_REQUEST_MARKET_SET_MISMATCH")
            base = self.root / ".stage_generations"
            generation = (self.root / str(receipt.get("generation_relative") or "")).absolute()
            relative = _under(base, generation)
            generation = base / relative
            verified = self._verify_generation(
                trade_date=trade_date,
                stage_id=stage_id,
                generation_root=generation,
                child_result={
                    "status": receipt.get("stage_status"),
                    "trade_date": trade_date,
                    "stage_id": stage_id,
                    "write_performed": True,
                    "markets": {
                        market: {
                            "status": receipt.get("stage_status"),
                            "selection_status": receipt.get("stage_status"),
                            "selected_rows": receipt.get("market_proofs", {}).get(market, {}).get("selected_rows"),
                        }
                        for market in expected
                    },
                    **SAFETY_FLAGS,
                },
            )
            if (
                verified.get("generation_relative") != receipt.get("generation_relative")
                or verified.get("market_proofs") != receipt.get("market_proofs")
                or verified.get("bundle") != receipt.get("bundle")
                or verified.get("hk_d1_source_identity") != receipt.get("hk_d1_source_identity")
            ):
                raise StageCommitError("STRICT_GENERATION_IDENTITY_CHANGED")
            from stage_center.selection import SelectionStore

            envelopes = {
                market: SelectionStore(generation / "selection").read_verified(trade_date, stage_id, market)
                for market in expected
            }
            stage_status = str(receipt.get("stage_status"))
            return {
                "status": stage_status,
                "stage_status": stage_status,
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": envelopes,
                "transaction_id": transaction_id,
                "commit_receipt_sha256": commit_sha,
                "commit_receipt_path": str(commit_path),
                "witness_path": str(witness_path),
                "terminal_monotonic_ns": terminal_ns,
                "elapsed_ns": elapsed_ns,
                "deadline_verified": True,
                "write_performed": False,
                "cannot_confirm": [],
                **SAFETY_FLAGS,
            }
        except (OSError, TypeError, ValueError, KeyError) as error:
            return self._failure(trade_date, stage_id, str(error) or type(error).__name__)

    def read_verified(
        self,
        trade_date: str,
        stage_id: str,
        markets: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        lock = self.make_lock()
        if not lock.acquire():
            return self._failure(trade_date, stage_id, "STRICT_COMMIT_LOCK_UNAVAILABLE")
        try:
            return self._read_unlocked(trade_date, stage_id, markets)
        finally:
            lock.release()

    def _candidate_paths(self) -> list[tuple[str, str, Path]]:
        candidates: list[tuple[str, str, Path]] = []
        if not self.root.is_dir() or self.root.is_symlink():
            return candidates
        try:
            dates = tuple(self.root.iterdir())
        except OSError:
            return candidates
        for date_dir in dates:
            if date_dir.is_symlink() or not date_dir.is_dir() or len(date_dir.name) != 8 or not date_dir.name.isdigit():
                continue
            try:
                stages = tuple(date_dir.iterdir())
            except OSError:
                continue
            for stage_dir in stages:
                path = stage_dir / "strict_commit.json"
                if stage_dir.is_symlink() or not stage_dir.is_dir() or stage_dir.name not in STAGE_BY_ID or not path.exists():
                    continue
                candidates.append((date_dir.name, stage_dir.name, path))
        return sorted(candidates)

    def catalog(self) -> dict[str, dict[str, Any]]:
        candidates = self._candidate_paths()
        by_date: dict[str, dict[str, Any]] = {}
        if not candidates:
            return by_date
        lock = self.make_lock()
        locked = lock.acquire()
        try:
            for trade_date, stage_id, _path in candidates:
                item = by_date.setdefault(
                    trade_date,
                    {"trade_date": trade_date, "status": "BLOCKED", "stage_ids": [],
                     "markets": [], "verified_markets": [], "expected_markets": {},
                     "missing_markets": [], "verified_entries": 0, "blocked_entries": 0,
                     "receipt_paths": [], "artifact_ids": [], "transaction_ids": [],
                     "cannot_confirm": []},
                )
                item["stage_ids"].append(stage_id)
                if not locked:
                    item["blocked_entries"] += 1
                    item["cannot_confirm"].append("STRICT_COMMIT_LOCK_UNAVAILABLE")
                    continue
                result = self._read_unlocked(trade_date, stage_id)
                item["expected_markets"][stage_id] = list(result.get("markets", {}).keys())
                if result.get("status") not in {"READY", "READY_EMPTY"}:
                    item["blocked_entries"] += 1
                    item["cannot_confirm"].extend(result.get("cannot_confirm") or ["STRICT_COMMIT_CANNOT_CONFIRM"])
                    continue
                item["verified_entries"] += len(result["markets"])
                item["verified_markets"].extend(result["markets"].keys())
                item["markets"].extend(result["markets"].keys())
                item["receipt_paths"].append(result["commit_receipt_path"])
                item["artifact_ids"].extend(str(value.get("artifact_id") or "") for value in result["markets"].values())
                item["transaction_ids"].append(result["transaction_id"])
            for item in by_date.values():
                if item["verified_entries"] == 0:
                    item["status"] = "BLOCKED"
                elif item["blocked_entries"] or item["cannot_confirm"]:
                    item["status"] = "PARTIAL"
                else:
                    item["status"] = "MATERIALIZED"
                for key in ("stage_ids", "markets", "verified_markets", "receipt_paths", "artifact_ids", "transaction_ids", "cannot_confirm"):
                    item[key] = sorted(set(item[key]))
                item["expected_markets"] = {
                    key: sorted(set(values)) for key, values in item["expected_markets"].items()
                }
            return dict(sorted(by_date.items()))
        finally:
            if locked:
                lock.release()


def read_strict_stage_selection(
    selection_root: Path | str,
    trade_date: str,
    stage_id: str,
    markets: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    """Return None only for legacy mode; strict errors never fall back to latest."""
    config = runtime_config()
    mode = publication_mode(config)
    if mode == "legacy":
        return None
    if mode != STRICT_PUBLICATION_MODE:
        return {
            "status": "CANNOT_CONFIRM", "stage_status": "CANNOT_CONFIRM",
            "trade_date": trade_date, "stage_id": stage_id, "markets": {},
            "cannot_confirm": ["STAGE_PUBLICATION_POLICY_INVALID"], **SAFETY_FLAGS,
        }
    try:
        configured_selection = Path(str(config.get("selection_root") or "")).expanduser().resolve()
        observed_selection = Path(selection_root).expanduser().resolve()
        if not configured_selection.is_absolute() or configured_selection != observed_selection:
            raise StageCommitError("STRICT_SELECTION_ROOT_MISMATCH")
        store = StageCommitStore(configured_receipt_root(config))
        result = store.read_verified(trade_date, stage_id)
        if markets is not None and result.get("status") in {"READY", "READY_EMPTY"}:
            requested = set(markets)
            if not requested.issubset(set(result.get("markets", {}))):
                raise StageCommitError("STRICT_REQUEST_MARKET_SET_MISMATCH")
            result["markets"] = {
                market: value for market, value in result["markets"].items()
                if market in requested
            }
        return result
    except (OSError, TypeError, ValueError) as error:
        return {
            "status": "CANNOT_CONFIRM", "stage_status": "CANNOT_CONFIRM",
            "trade_date": trade_date, "stage_id": stage_id, "markets": {},
            "cannot_confirm": [str(error) or type(error).__name__], **SAFETY_FLAGS,
        }


__all__ = [
    "DEADLINE_BUDGET_NS", "RUNTIME_CONFIG_PATH", "STRICT_PUBLICATION_MODE",
    "StageCommitError", "StageCommitStore", "configured_receipt_root",
    "publication_mode", "read_strict_stage_selection", "runtime_config",
    "sha256_file",
]
