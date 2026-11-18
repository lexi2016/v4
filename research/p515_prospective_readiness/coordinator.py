"""Fail-closed coordinator for the fixed P5.15 prospective validation design.

The live runner is intentionally inert unless a new externally hash-pinned
authorization, PRE_STUDY receipt, source seams, state adapter and Drive readback
are supplied.  Preparation never loads a model or invokes a scorer.  A separate
fixture callback can exercise only an opaque, non-probability placeholder.
"""
from __future__ import annotations

import csv
import base64
import fcntl
import hashlib
import inspect
import json
import math
import os
import sqlite3
import stat
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

from .drive_store import (
    DriveEvidenceError,
    DriveFileExpectation,
    GoogleDriveReadbackStore,
    VerifiedDriveReceipt,
    sha256_bytes,
    verify_google_drive_readback,
)


STUDY_ID = "P515_A7_CLIP16_FORWARD_20261123_V1"
FIXTURE_ID = "SYNTHETIC_FIXTURE_ONLY"
BEIJING = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
PRE_STUDY_DEADLINE = datetime(2026, 11, 20, 20, 0, tzinfo=BEIJING)
LATEST_PB15 = date(2026, 12, 29)
FIXED_READOUT = datetime(2026, 12, 30, 20, 0, tzinfo=BEIJING)
EARLIEST_K3 = date(2026, 11, 27)
STUDY_START = date(2026, 11, 23)
STUDY_END = date(2026, 12, 11)
INPUT_DEADLINE = time(21, 30)
OUTPUT_DEADLINE = time(23, 30)
MODEL_BATCH_LIMIT = 15
PAIRED_OUTPUT_ROW_LIMIT = 6000
UNIQUE_PB_LIMIT = 3000
MAX_POOL_ROWS = 200

FEATURE_NAMES = (
    "pb_stratum_is_pb2plus",
    "pb_ordinal_exact",
    "event_age_k",
    "k1_close_to_wave_high_pct",
    "k2_close_to_wave_high_pct",
    "k3_close_to_wave_high_pct",
    "k1_low_to_wave_high_pct",
    "k2_low_to_wave_high_pct",
    "k3_low_to_wave_high_pct",
    "k1_vol_over_fixed_attack_mean",
    "k2_vol_over_fixed_attack_mean",
    "k3_vol_over_fixed_attack_mean",
    "d_vol_over_expanding_wave_mean",
    "fixed_attack_window_bars",
    "d_close_to_root_low_pct",
    "d_close_above_bbi",
    "d_close_above_ma5",
    "same_parent_prior_matured_pb_count",
    "days_since_last_same_parent_restart",
    "missing_prior_same_parent_restart_indicator",
)
BINARY_FEATURE_INDICES = (0, 15, 16, 19)
NUMERIC_FEATURE_INDICES = tuple(i for i in range(20) if i not in BINARY_FEATURE_INDICES)

DISPOSITIONS = (
    "OUTSIDE_SH_SZ_A",
    "INVALID_OR_MISSING_D_BAR",
    "STATE_ANCHOR_UNKNOWN",
    "NO_AT_RISK_K3",
    "DUPLICATE_PB",
    "KNOWN_EXPOSURE_OR_CONTINUATION",
    "EXPOSURE_BIRTH_UNCONFIRMED",
    "QFQ_BASIS_CONFLICT",
    "MISSING_OR_NONFINITE_FEATURE",
    "ELIGIBLE",
)

REQUIRED_IDENTITY_KEYS = (
    "coordinator_module_sha256",
    "contract_sha256",
    "calendar_sha256",
    "exposure_ledger_sha256",
    "top200_parser_sha256",
    "v4_reader_sha256",
    "wiring_module_sha256",
    "source_evidence_verifier_sha256",
    "r2_rules_sha256",
    "r2_state_adapter_sha256",
    "r2_anchor_catalog_sha256",
    "feature_map_sha256",
    "feature_builder_sha256",
    "model_sha256",
    "scaler_sha256",
    "params_sha256",
    "drive_store_sha256",
    "drive_transport_sha256",
    "predictor_bridge_sha256",
    "v1_assets_loader_sha256",
    "non_overwrite_guard_sha256",
)


class CoordinatorError(RuntimeError):
    """Coordinator refused an invalid or unsafe transition."""


class NoGoError(CoordinatorError):
    """Required new authorization or evidence is absent or invalid."""


class DuplicateAttempt(CoordinatorError):
    """The fixed study/date slot has already been reserved."""


class BudgetExceeded(CoordinatorError):
    """Persistent study-wide budget would be exceeded."""


class EvidenceError(CoordinatorError):
    """The submitted source, state, exposure, or Drive evidence is invalid."""


def _hex_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceError("value is not canonical-JSON serializable") from exc


def _parse_json_object(raw: bytes, label: str) -> Mapping[str, Any]:
    def pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError(f"duplicate key in {label}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be a JSON object")
    return value


def _as_date(value: str | date, label: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise EvidenceError(f"{label} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceError(f"{label} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise EvidenceError(f"{label} must use canonical YYYY-MM-DD")
    return parsed


def _aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EvidenceError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def fixed_d_dates() -> tuple[date, ...]:
    # Exactly the 15 common-market sessions from the accepted proposed schedule.
    return tuple(date.fromisoformat(d) for d in (
        "2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27",
        "2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03", "2026-12-04",
        "2026-12-07", "2026-12-08", "2026-12-09", "2026-12-10", "2026-12-11",
    ))


def compact_d(value: str | date) -> str:
    return _as_date(value, "D").strftime("%Y%m%d")


def _local_datetime(d: date, t: time) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second, tzinfo=BEIJING)


@dataclass(frozen=True)
class RuntimePins:
    """Hash lock loaded from the accepted, externally published PRE_STUDY."""

    grant_sha256: str
    pre_study_sha256: str
    grant_file_id: str
    pre_study_file_id: str
    parent_id: str
    identity_sha256: Mapping[str, str]
    grant_name: str
    pre_study_name: str
    output_root: str
    grant_version: str | None = None
    pre_study_version: str | None = None
    evidence_mime_type: str = "application/json"

    def __post_init__(self) -> None:
        if not _hex_sha(self.grant_sha256) or not _hex_sha(self.pre_study_sha256):
            raise NoGoError("grant and PRE_STUDY require externally pinned SHA256")
        if not all((self.grant_file_id, self.pre_study_file_id, self.parent_id,
                    self.grant_name, self.pre_study_name, self.output_root)):
            raise NoGoError("grant/PRE_STUDY IDs, names, parent and fixed output root must be pinned")
        if set(self.identity_sha256) != set(REQUIRED_IDENTITY_KEYS):
            missing = sorted(set(REQUIRED_IDENTITY_KEYS) - set(self.identity_sha256))
            extra = sorted(set(self.identity_sha256) - set(REQUIRED_IDENTITY_KEYS))
            raise NoGoError(f"identity lock has missing={missing}, extra={extra}")
        if any(not _hex_sha(value) for value in self.identity_sha256.values()):
            raise NoGoError("all implementation/data/model identities must be full SHA256")

    @property
    def identity_lock_sha256(self) -> str:
        return sha256_bytes(_canonical_json(dict(sorted(self.identity_sha256.items()))))


@dataclass(frozen=True)
class AuthorizationBundle:
    grant_bytes: bytes
    pre_study_bytes: bytes


@dataclass(frozen=True)
class VerifiedAuthorization:
    bundle: AuthorizationBundle
    grant_receipt: VerifiedDriveReceipt
    pre_study_receipt: VerifiedDriveReceipt
    verified_at: datetime
    _coordinator_token: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class PoolRow:
    rank: int
    ts_code: str
    market: str
    instrument_type: str
    source_trade_date: str
    bar_values: tuple[float, float, float, float, float] | None
    features: tuple[float, ...] | None
    bar_trade_date: str | None = None


@dataclass(frozen=True)
class StateEvidence:
    """Raw, per-security anchor/checkpoint bytes for a hash-bound R2 proof."""

    anchor_receipt_bytes: bytes | None
    checkpoint_bytes: bytes | None


@dataclass(frozen=True)
class DailyPoolInput:
    D: str
    captured_at: datetime
    top200_body: bytes
    rows: tuple[PoolRow, ...]
    reader_evidence: bytes
    source_generation: str
    generation_manifest_sha256: str
    source_input_sha256: str
    state_evidence_by_security: Mapping[str, StateEvidence] = field(default_factory=dict)
    synthetic_fixture: bool = False


@dataclass(frozen=True)
class SourceProof:
    D: str
    top200_body_sha256: str
    source_generation: str
    generation_manifest_sha256: str
    source_input_sha256: str
    top200_roster: tuple[tuple[int, str, str], ...]
    reader_query_start: str
    reader_query_end: str
    reader_max_trade_date: str | None
    reader_manifest_sha256: str
    reader_evidence_sha256: str
    reader_projection_sha256: str
    canonical_matrix_sha256: str
    canonical_keys_sha256: str
    reader_code_sha256: str
    top200_code_sha256: str
    source_evidence_verifier_sha256: str
    source_observed_at: datetime
    price_basis: str
    volume_basis: str
    proof_sha256: str
    qfq_basis_conflicts: tuple[str, ...] = ()


class SourceProofVerifier(Protocol):
    def verify(self, daily_input: DailyPoolInput, canonical_matrix_sha256: str,
               canonical_keys_sha256: str, row_projection_sha256: str) -> SourceProof: ...


@dataclass(frozen=True)
class StateProof:
    ts_code: str
    D: str
    status: str
    mother_key: str | None
    pb_id: str | None
    origin_date: str | None
    stage: str | None
    pullback_sessions: int | None
    terminal_on_D: bool | None
    prior_pb_terminal_date: str | None
    adapter_sha256: str
    anchor_receipt_sha256: str | None
    checkpoint_sha256: str | None
    proof_sha256: str


class StateProofVerifier(Protocol):
    def verify(self, daily_input: DailyPoolInput, rows: Sequence[PoolRow],
               pins: RuntimePins | None) -> Mapping[str, StateProof]: ...


@dataclass(frozen=True)
class SourceValidation:
    proof: SourceProof
    canonical_matrix_sha256: str
    canonical_keys_sha256: str
    row_projection_sha256: str


@dataclass(frozen=True)
class RowDisposition:
    rank: int
    ts_code: str
    disposition: str
    mother_key: str | None = None
    pb_id: str | None = None
    event_key: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PreparedDay:
    study_id: str
    D: str
    attempt_id: str
    input_sha256: str
    canonical_matrix_sha256: str
    canonical_keys_sha256: str
    eligible_count: int
    paired_output_rows: int
    dispositions: tuple[RowDisposition, ...]
    input_manifest_bytes: bytes
    reservation_path: str
    fixture_only: bool
    authorization_receipts: Mapping[str, VerifiedDriveReceipt] = field(default_factory=dict)
    input_receipt: VerifiedDriveReceipt | None = None


@dataclass(frozen=True)
class FixtureInvocation:
    fixture_id: str
    D: str
    callback_nonce: str
    marker: str = "NO_MARKET_NO_MODEL_NO_PROBABILITY"


FIXTURE_AUTHORIZATION_BYTES = (
    b'{"fixture_id":"SYNTHETIC_FIXTURE_ONLY","scope":"PLACEHOLDER_WIRING_ONLY",'
    b'"model_calls_allowed":false,"probabilities_allowed":false,"schema":"P515_FIXTURE_AUTH_V1"}'
)
FIXTURE_AUTHORIZATION_SHA256 = sha256_bytes(FIXTURE_AUTHORIZATION_BYTES)


@dataclass(frozen=True)
class ExposureIndex:
    sha256: str
    known_pb: frozenset[tuple[str, str]]
    known_mothers: frozenset[tuple[str, str]]
    unknown_crosswalk_by_security: frozenset[str]

    @classmethod
    def from_csv_bytes(cls, raw: bytes) -> "ExposureIndex":
        digest = sha256_bytes(raw)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise EvidenceError("exposure ledger is not UTF-8") from exc
        rows = list(csv.DictReader(text.splitlines()))
        required = {
            "security", "original_event_or_sample_key", "R2_mother_key",
            "R2_event_exact", "policy",
        }
        if not rows or not required.issubset(rows[0]):
            raise EvidenceError("exposure ledger schema is incomplete")
        pb: set[tuple[str, str]] = set()
        mothers: set[tuple[str, str]] = set()
        unknown: set[str] = set()
        for row in rows:
            security = row.get("security", "").strip()
            if row.get("R2_event_exact") == "YES":
                key = row.get("original_event_or_sample_key", "").strip()
                if key:
                    pb.add((security, key))
                mother = row.get("R2_mother_key", "").strip()
                if mother:
                    mothers.add((security, mother))
            elif row.get("R2_event_exact") == "UNKNOWN_CROSSWALK":
                if security:
                    unknown.add(security)
        return cls(digest, frozenset(pb), frozenset(mothers), frozenset(unknown))


class _CoordinatorStore:
    """SQLite reservation ledger plus durable, append-only JSONL audit log."""

    def __init__(self, study_root: Path, identity: Mapping[str, Any], guard_module: Any | None = None):
        self.root = study_root
        self.guard_module = guard_module
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise NoGoError("study root cannot be a symlink")
        self.db_path = self.root / "coordinator.sqlite3"
        self.log_path = self.root / "EXECUTION.jsonl"
        self.lock_path = self.root / "COORDINATOR.lock"
        self._initialize(identity)

    def _file_lock(self):
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self, identity: Mapping[str, Any]) -> None:
        lockfd = self._file_lock()
        try:
            marker = self.root / "ROOT_BINDING.json"
            expected = _canonical_json(identity) + b"\n"
            if not marker.exists():
                fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(expected)
                    stream.flush()
                    os.fsync(stream.fileno())
            else:
                if marker.read_bytes() != expected:
                    raise NoGoError("fixed output root is already bound to another study/config")
            with closing(self._db()) as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS root_identity (
                        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                        identity_json BLOB NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS attempts (
                        D TEXT PRIMARY KEY,
                        attempt_id TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL,
                        eligible_count INTEGER NOT NULL,
                        output_rows INTEGER NOT NULL,
                        input_sha256 TEXT NOT NULL,
                        matrix_sha256 TEXT NOT NULL,
                        keys_sha256 TEXT NOT NULL,
                        reserved_at TEXT NOT NULL,
                        input_file_id TEXT,
                        input_version TEXT,
                        input_readback_at TEXT,
                        finished_at TEXT,
                        error_code TEXT,
                        output_sha256 TEXT,
                        output_file_id TEXT,
                        output_version TEXT,
                        output_readback_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS pb_keys (
                        pb_identity TEXT PRIMARY KEY,
                        D TEXT NOT NULL REFERENCES attempts(D)
                    );
                    CREATE TABLE IF NOT EXISTS mother_events (
                        mother_identity TEXT NOT NULL,
                        pb_ordinal INTEGER NOT NULL,
                        terminal_date TEXT,
                        D TEXT NOT NULL REFERENCES attempts(D),
                        PRIMARY KEY(mother_identity, pb_ordinal)
                    );
                    CREATE TABLE IF NOT EXISTS audit_events (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        D TEXT,
                        event TEXT NOT NULL,
                        payload_json BLOB NOT NULL,
                        line_sha256 TEXT NOT NULL
                    );
                    CREATE TRIGGER IF NOT EXISTS audit_no_update
                    BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'append-only audit'); END;
                    CREATE TRIGGER IF NOT EXISTS audit_no_delete
                    BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'append-only audit'); END;
                """)
                conn.execute("BEGIN IMMEDIATE")
                old = conn.execute("SELECT identity_json FROM root_identity WHERE singleton=1").fetchone()
                if old is None:
                    conn.execute("INSERT INTO root_identity VALUES (1, ?)", (expected,))
                elif bytes(old["identity_json"]) != expected:
                    raise NoGoError("SQLite root identity differs from fixed root binding")
                conn.execute("COMMIT")
            self._check_log_consistency()
        finally:
            fcntl.flock(lockfd, fcntl.LOCK_UN)
            os.close(lockfd)

    def _check_log_consistency(self) -> None:
        with closing(self._db()) as conn:
            expected = [str(row["line_sha256"]) for row in conn.execute(
                "SELECT line_sha256 FROM audit_events ORDER BY seq"
            ).fetchall()]
        if not self.log_path.exists():
            if expected:
                raise NoGoError("append-only log missing while database has events")
            return
        actual_lines = self.log_path.read_bytes().splitlines(keepends=True)
        actual = []
        for line in actual_lines:
            if not line.endswith(b"\n"):
                raise NoGoError("append-only log ends with a partial record")
            actual.append(sha256_bytes(line))
        if actual != expected:
            raise NoGoError("append-only log/database diverged; fixed root is quarantined")

    def append_event(self, event: str, D: str | None, payload: Mapping[str, Any], *, created_at: datetime) -> None:
        lockfd = self._file_lock()
        try:
            line_obj = {
                "created_at": created_at.astimezone(UTC).isoformat(),
                "D": D,
                "event": event,
                "payload": payload,
            }
            line = _canonical_json(line_obj) + b"\n"
            line_hash = sha256_bytes(line)
            fd = os.open(self.log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(fd, "ab", closefd=False) as stream:
                    stream.write(line)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(fd)
            with closing(self._db()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO audit_events(created_at,D,event,payload_json,line_sha256) VALUES(?,?,?,?,?)",
                    (line_obj["created_at"], D, event, _canonical_json(payload), line_hash),
                )
                conn.execute("COMMIT")
            self._check_log_consistency()
        finally:
            fcntl.flock(lockfd, fcntl.LOCK_UN)
            os.close(lockfd)

    def reserve(
        self, *, D: str, attempt_id: str, eligible_count: int, output_rows: int,
        input_sha256: str, matrix_sha256: str, keys_sha256: str,
        event_records: Sequence[tuple[str, str, int, str | None]], created_at: datetime,
        input_receipt: VerifiedDriveReceipt | None = None,
    ) -> None:
        day_dir = self.root / D
        if not day_dir.is_dir():
            raise NoGoError("D intent lock must exist before budget reservation")
        marker = day_dir / "ATTEMPT.lock"
        try:
            stream_context = self.guard_module.open_exclusive_binary(marker) if self.guard_module else self._exclusive_binary(marker)
        except FileExistsError as exc:
            raise DuplicateAttempt("D attempt has already been reserved") from exc
        with stream_context as stream:
            stream.write(_canonical_json({"attempt_id": attempt_id, "D": D}) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        with closing(self._db()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(output_rows),0) AS r, COALESCE(SUM(eligible_count),0) AS p FROM attempts").fetchone()
            if rows["n"] >= MODEL_BATCH_LIMIT:
                conn.execute("ROLLBACK")
                raise BudgetExceeded("15 daily attempts already reserved")
            if rows["r"] + output_rows > PAIRED_OUTPUT_ROW_LIMIT:
                conn.execute("ROLLBACK")
                raise BudgetExceeded("6000 paired output rows would be exceeded")
            if rows["p"] + eligible_count > UNIQUE_PB_LIMIT:
                conn.execute("ROLLBACK")
                raise BudgetExceeded("3000 unique PB limit would be exceeded")
            try:
                conn.execute(
                    "INSERT INTO attempts(D,attempt_id,status,eligible_count,output_rows,input_sha256,matrix_sha256,keys_sha256,reserved_at,input_file_id,input_version,input_readback_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (D, attempt_id, "RESERVED", eligible_count, output_rows, input_sha256,
                     matrix_sha256, keys_sha256, created_at.astimezone(UTC).isoformat(),
                     input_receipt.file_id if input_receipt else None,
                     input_receipt.version_token if input_receipt else None,
                     input_receipt.observed_at.isoformat() if input_receipt else None),
                )
                for pb_identity, mother_identity, ordinal, terminal_date in event_records:
                    conn.execute("INSERT INTO pb_keys(pb_identity,D) VALUES(?,?)", (pb_identity, D))
                    conn.execute(
                        "INSERT INTO mother_events(mother_identity,pb_ordinal,terminal_date,D) VALUES(?,?,?,?)",
                        (mother_identity, ordinal, terminal_date, D),
                    )
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise DuplicateAttempt("daily date, PB, or mother ordinal already reserved") from exc
            conn.execute("COMMIT")
        self.append_event("DAY_RESERVED", D, {
            "attempt_id": attempt_id,
            "eligible_count": eligible_count,
            "paired_output_rows": output_rows,
            "input_sha256": input_sha256,
            "matrix_sha256": matrix_sha256,
            "keys_sha256": keys_sha256,
            "input_file_id": input_receipt.file_id if input_receipt else None,
            "input_version": input_receipt.version_token if input_receipt else None,
            "input_readback_at": input_receipt.observed_at.isoformat() if input_receipt else None,
        }, created_at=created_at)

    def claim_intent(self, D: str, intent_id: str, *, created_at: datetime) -> Path:
        """Prevent concurrent/repeated input upload attempts for a fixed D."""
        day_dir = self.root / D
        try:
            day_dir.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError as exc:
            raise DuplicateAttempt("fixed D intent already exists; no upload retry") from exc
        try:
            stream_context = self.guard_module.open_exclusive_binary(day_dir / "INTENT.lock") if self.guard_module else self._exclusive_binary(day_dir / "INTENT.lock")
        except FileExistsError as exc:
            raise DuplicateAttempt("D input seal intent already exists; no retry") from exc
        with stream_context as stream:
            stream.write(_canonical_json({"intent_id": intent_id, "D": D}) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.append_event("INPUT_SEAL_INTENT", D, {"intent_id": intent_id}, created_at=created_at)
        return day_dir

    @staticmethod
    def _exclusive_binary(path: Path):
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        return os.fdopen(fd, "wb")

    def append_intent_failure(self, D: str, *, error_code: str, at: datetime) -> None:
        self.append_event("SEAL_MISSED", D, {"error_code": error_code}, created_at=at)

    def update_status(self, D: str, status: str, *, error_code: str | None = None,
                      output_sha256: str | None = None, receipt: VerifiedDriveReceipt | None = None,
                      at: datetime) -> None:
        with closing(self._db()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT status FROM attempts WHERE D=?", (D,)).fetchone()
            if existing is None:
                conn.execute("ROLLBACK")
                raise NoGoError("attempt reservation not found")
            if existing["status"] not in ("RESERVED", "CALL_STARTED"):
                conn.execute("ROLLBACK")
                raise NoGoError("attempt has already reached a terminal state")
            conn.execute(
                "UPDATE attempts SET status=?, finished_at=?, error_code=?, output_sha256=?, output_file_id=?, output_version=?, output_readback_at=? WHERE D=?",
                (status, at.astimezone(UTC).isoformat(), error_code, output_sha256,
                 receipt.file_id if receipt else None,
                 receipt.version_token if receipt else None,
                 receipt.observed_at.isoformat() if receipt else None, D),
            )
            conn.execute("COMMIT")
        self.append_event(status, D, {
            "error_code": error_code,
            "output_sha256": output_sha256,
            "output_file_id": receipt.file_id if receipt else None,
            "output_version": receipt.version_token if receipt else None,
            "output_readback_at": receipt.observed_at.isoformat() if receipt else None,
        }, created_at=at)

    def begin_model_call(self, D: str, *, at: datetime) -> None:
        with closing(self._db()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute("UPDATE attempts SET status='CALL_STARTED' WHERE D=? AND status='RESERVED'", (D,)).rowcount
            if changed != 1:
                conn.execute("ROLLBACK")
                raise NoGoError("attempt cannot be called twice")
            conn.execute("COMMIT")
        self.append_event("PREDICTOR_CALLBACK_INVOKED", D, {"callback_invocation_count": 1}, created_at=at)

    def begin_fixture_callback(self, D: str, *, at: datetime) -> None:
        with closing(self._db()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute("UPDATE attempts SET status='CALL_STARTED' WHERE D=? AND status='RESERVED'", (D,)).rowcount
            if changed != 1:
                conn.execute("ROLLBACK")
                raise NoGoError("fixture callback reservation cannot be consumed twice")
            conn.execute("COMMIT")
        self.append_event("FIXTURE_CALLBACK_START", D, {"model_api_calls": 0, "probability_rows": 0}, created_at=at)

    def acquire_model_run_lock(self) -> int:
        fd = os.open(self.root / "MODEL_CALL.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise NoGoError("another cross-process model batch is active") from exc
        return fd

    def day_events(self, D: str) -> list[Mapping[str, Any]]:
        with closing(self._db()) as conn:
            rows = conn.execute(
                "SELECT created_at,event,payload_json FROM audit_events WHERE D=? ORDER BY seq", (D,)
            ).fetchall()
        return [{
            "created_at": row["created_at"],
            "D": D,
            "event": row["event"],
            "payload": json.loads(bytes(row["payload_json"]).decode("utf-8")),
        } for row in rows]

    def original_authorization_event(self) -> tuple[datetime, Mapping[str, Any]] | None:
        with closing(self._db()) as conn:
            row = conn.execute(
                "SELECT created_at,payload_json FROM audit_events "
                "WHERE D IS NULL AND event='STUDY_AUTHORIZATION_VERIFIED' ORDER BY seq LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        try:
            created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            payload = json.loads(bytes(row["payload_json"]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NoGoError("persisted original authorization event is malformed") from exc
        if created.tzinfo is None or not isinstance(payload, dict):
            raise NoGoError("persisted original authorization event lacks time/payload")
        return created.astimezone(UTC), payload

    def attempt(self, D: str) -> sqlite3.Row | None:
        conn = self._db()
        try:
            return conn.execute("SELECT * FROM attempts WHERE D=?", (D,)).fetchone()
        finally:
            conn.close()

    def totals(self) -> tuple[int, int, int]:
        conn = self._db()
        try:
            row = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(output_rows),0) r, COALESCE(SUM(eligible_count),0) p FROM attempts").fetchone()
            return int(row["n"]), int(row["r"]), int(row["p"])
        finally:
            conn.close()

    def execution_counts(self) -> Mapping[str, int]:
        with closing(self._db()) as conn:
            return {
                "daily_reservations": int(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]),
                "paired_output_rows_reserved": int(conn.execute("SELECT COALESCE(SUM(output_rows),0) FROM attempts").fetchone()[0]),
                "unique_pb_reserved": int(conn.execute("SELECT COALESCE(SUM(eligible_count),0) FROM attempts").fetchone()[0]),
                "model_api_predict_calls": int(conn.execute("SELECT COUNT(*) FROM audit_events WHERE event='MODEL_CALL_START'").fetchone()[0]),
                "fixture_callbacks": int(conn.execute("SELECT COUNT(*) FROM audit_events WHERE event='FIXTURE_CALLBACK_START'").fetchone()[0]),
                "input_seal_intents": int(conn.execute("SELECT COUNT(*) FROM audit_events WHERE event='INPUT_SEAL_INTENT'").fetchone()[0]),
                "seal_missed": int(conn.execute("SELECT COUNT(*) FROM audit_events WHERE event='SEAL_MISSED'").fetchone()[0]),
            }


def canonical_matrix_and_keys(rows: Sequence[PoolRow]) -> tuple[bytes, str, str, str]:
    eligible_values = []
    keys = []
    projection = []
    for row in sorted(rows, key=lambda r: r.rank):
        key = {"rank": row.rank, "ts_code": row.ts_code}
        keys.append(key)
        bar = [float(x) for x in row.bar_values] if row.bar_values is not None else None
        features = [float(x) for x in row.features] if row.features is not None else None
        projection.append({**key, "market": row.market, "instrument_type": row.instrument_type,
                          "source_trade_date": row.source_trade_date,
                          "bar_trade_date": row.bar_trade_date,
                          "bar_values": bar, "features": features})
        if features is not None:
            eligible_values.append({**key, "features": features})
    matrix_bytes = _canonical_json({"columns": FEATURE_NAMES, "rows": eligible_values})
    keys_bytes = _canonical_json(keys)
    projection_bytes = _canonical_json(projection)
    return matrix_bytes, sha256_bytes(matrix_bytes), sha256_bytes(keys_bytes), sha256_bytes(projection_bytes)


def _source_proof_payload(proof: SourceProof) -> Mapping[str, Any]:
    return {
        "D": proof.D,
        "top200_body_sha256": proof.top200_body_sha256,
        "source_generation": proof.source_generation,
        "generation_manifest_sha256": proof.generation_manifest_sha256,
        "source_input_sha256": proof.source_input_sha256,
        "top200_roster": list(proof.top200_roster),
        "reader_query_start": proof.reader_query_start,
        "reader_query_end": proof.reader_query_end,
        "reader_max_trade_date": proof.reader_max_trade_date,
        "reader_manifest_sha256": proof.reader_manifest_sha256,
        "reader_evidence_sha256": proof.reader_evidence_sha256,
        "reader_projection_sha256": proof.reader_projection_sha256,
        "canonical_matrix_sha256": proof.canonical_matrix_sha256,
        "canonical_keys_sha256": proof.canonical_keys_sha256,
        "reader_code_sha256": proof.reader_code_sha256,
        "top200_code_sha256": proof.top200_code_sha256,
        "source_evidence_verifier_sha256": proof.source_evidence_verifier_sha256,
        "source_observed_at": _aware(proof.source_observed_at, "source observed at").isoformat(),
        "price_basis": proof.price_basis,
        "volume_basis": proof.volume_basis,
        "qfq_basis_conflicts": list(proof.qfq_basis_conflicts),
    }


def _state_proof_payload(proof: StateProof) -> Mapping[str, Any]:
    return {
        "ts_code": proof.ts_code,
        "D": proof.D,
        "status": proof.status,
        "mother_key": proof.mother_key,
        "pb_id": proof.pb_id,
        "origin_date": proof.origin_date,
        "stage": proof.stage,
        "pullback_sessions": proof.pullback_sessions,
        "terminal_on_D": proof.terminal_on_D,
        "prior_pb_terminal_date": proof.prior_pb_terminal_date,
        "adapter_sha256": proof.adapter_sha256,
        "anchor_receipt_sha256": proof.anchor_receipt_sha256,
        "checkpoint_sha256": proof.checkpoint_sha256,
    }


def compute_state_proof_sha256(proof: StateProof) -> str:
    return sha256_bytes(_canonical_json(_state_proof_payload(proof)))


def _module_sha256(obj: Any) -> str | None:
    try:
        if inspect.ismodule(obj):
            path = getattr(obj, "__file__", None)
        elif inspect.isfunction(obj) or inspect.ismethod(obj):
            path = inspect.getsourcefile(obj)
        else:
            path = inspect.getsourcefile(obj.__class__)
        if not path:
            return None
        return sha256_bytes(Path(path).read_bytes())
    except (OSError, TypeError):
        return None


class ReadinessCoordinator:
    """Prepare fixed D batches and enforce persistent, fail-closed study rules."""

    def __init__(
        self,
        output_root: str | Path,
        *,
        pins: RuntimePins | None = None,
        source_verifier: SourceProofVerifier | None = None,
        state_verifier: StateProofVerifier | None = None,
        exposure_ledger_bytes: bytes | None = None,
        r2_anchor_catalog_bytes: bytes | None = None,
        identity_evidence_bytes: Mapping[str, bytes] | None = None,
        drive_store: Any | None = None,
        v1_assets: Any | None = None,
        guard_module: Any | None = None,
        fixture_only: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(BEIJING),
    ):
        self.fixture_only = fixture_only
        if fixture_only and pins is not None:
            raise NoGoError("fixture mode cannot carry real execution pins")
        self.pins = pins
        self.source_verifier = source_verifier
        self.state_verifier = state_verifier
        self.drive_store = drive_store
        self.v1_assets = v1_assets
        self.guard_module = v1_assets.load_guard() if v1_assets is not None else guard_module
        self.clock = clock
        self.anchor_catalog_sha256 = sha256_bytes(r2_anchor_catalog_bytes) if r2_anchor_catalog_bytes else None
        self.identity_evidence_bytes = dict(identity_evidence_bytes or {})
        evidence_pin_names = {
            "contract": "contract_sha256",
            "calendar": "calendar_sha256",
            "feature_map": "feature_map_sha256",
            "feature_builder": "feature_builder_sha256",
            "r2_rules": "r2_rules_sha256",
            "source_evidence_verifier": "source_evidence_verifier_sha256",
        }
        if pins is not None:
            for evidence_name, identity_name in evidence_pin_names.items():
                raw = self.identity_evidence_bytes.get(evidence_name)
                if not isinstance(raw, bytes) or sha256_bytes(raw) != pins.identity_sha256[identity_name]:
                    raise NoGoError(f"{evidence_name} evidence bytes are missing or differ from the PRE_STUDY pin")
        if pins is not None and self.anchor_catalog_sha256 != pins.identity_sha256["r2_anchor_catalog_sha256"]:
            raise NoGoError("independently pinned R2 anchor catalog bytes are unavailable or mismatched")
        if pins is not None and exposure_ledger_bytes is not None:
            exposure = ExposureIndex.from_csv_bytes(exposure_ledger_bytes)
            if exposure.sha256 != pins.identity_sha256["exposure_ledger_sha256"]:
                raise NoGoError("exposure ledger SHA does not match frozen identity lock")
            self.exposure_index = exposure
        else:
            self.exposure_index = None
        self.study_id = FIXTURE_ID if fixture_only else STUDY_ID
        self.output_root = Path(output_root).expanduser().resolve(strict=False)
        if pins is not None:
            pinned_root = Path(pins.output_root).expanduser().resolve(strict=False)
            if str(self.output_root) != str(pinned_root):
                raise NoGoError("output root differs from the externally pinned PRE_STUDY path")
        self.study_root = self.output_root / self.study_id
        if not fixture_only and pins is None:
            # The store may be opened for inspection, but no live D can be prepared.
            identity = {"study_id": STUDY_ID, "mode": "REAL_NO_GO", "pins": None}
        elif fixture_only:
            identity = {"study_id": FIXTURE_ID, "mode": "SYNTHETIC_FIXTURE_ONLY", "schema": 1}
        else:
            identity = {
                "study_id": STUDY_ID,
                "mode": "REAL",
                "output_root": str(self.output_root),
                "identity_lock_sha256": pins.identity_lock_sha256,
                "grant_sha256": pins.grant_sha256,
                "pre_study_sha256": pins.pre_study_sha256,
            }
        self.store = None if not fixture_only and pins is None else _CoordinatorStore(self.study_root, identity, guard_module)
        self._prepared: dict[str, PreparedDay] = {}
        self._gate_token = object()
        self._verified_authorization: VerifiedAuthorization | None = None

    def _now(self) -> datetime:
        return _aware(self.clock(), "coordinator clock")

    def _validate_day_clock(self, daily: DailyPoolInput, *, phase: str = "input") -> tuple[date, datetime, datetime]:
        d = _as_date(daily.D, "D")
        if d not in fixed_d_dates():
            raise NoGoError("D is outside the frozen 15-session roster")
        captured = _aware(daily.captured_at, "D capture time")
        input_deadline = _local_datetime(d, INPUT_DEADLINE).astimezone(UTC)
        start_time = _local_datetime(d, time(15, 0)).astimezone(UTC)
        now = self._now()
        if captured < start_time or captured > input_deadline:
            raise NoGoError("D-only input must be captured after 15:00 and by 21:30 Asia/Shanghai")
        if captured > now:
            raise NoGoError("D capture timestamp is in the future relative to coordinator clock")
        if phase == "input" and now > input_deadline:
            raise NoGoError("21:30 input deadline passed; no late start")
        output_deadline = _local_datetime(d, OUTPUT_DEADLINE).astimezone(UTC)
        if phase == "output" and now > output_deadline:
            raise NoGoError("23:30 output/readback deadline passed; no late execution")
        if phase not in ("input", "output"):
            raise ValueError("unknown coordinator phase")
        if self._now().astimezone(BEIJING).date() < d:
            raise NoGoError("future D cannot be executed before that trading date")
        return d, captured, input_deadline if phase == "input" else output_deadline

    def _validate_identity_lock(self) -> None:
        if self.pins is None:
            raise NoGoError("live execution is NO_GO: no externally hash-pinned grant/PRE_STUDY identities")
        actual_coordinator_sha = sha256_bytes(Path(__file__).read_bytes())
        if actual_coordinator_sha != self.pins.identity_sha256["coordinator_module_sha256"]:
            raise NoGoError("coordinator code SHA differs from pinned PRE_STUDY")
        if self.source_verifier is None or self.state_verifier is None:
            raise NoGoError("live execution is NO_GO: source and R2 state verifiers are not wired")
        source_sha = _module_sha256(self.source_verifier)
        state_sha = _module_sha256(self.state_verifier)
        if source_sha != self.pins.identity_sha256["wiring_module_sha256"] or state_sha != source_sha:
            raise NoGoError("source/state wiring module SHA is not externally pinned")
        if self.anchor_catalog_sha256 != self.pins.identity_sha256["r2_anchor_catalog_sha256"]:
            raise NoGoError("R2 anchor policy/catalog bytes are not independently pinned")
        if type(self.drive_store) is not GoogleDriveReadbackStore or _module_sha256(self.drive_store) != self.pins.identity_sha256["drive_store_sha256"]:
            raise NoGoError("trusted Drive readback store is not wired/hash-pinned")
        transport_sha = _module_sha256(getattr(self.drive_store, "_transport", None))
        if transport_sha != self.pins.identity_sha256["drive_transport_sha256"]:
            raise NoGoError("Drive v3 transport implementation SHA is not pinned")
        if self.v1_assets is None:
            raise NoGoError("original frozen V1 source assets are not loaded")
        future_assets = __import__("research.p515_prospective_readiness.future_assets", fromlist=["V1SourceAssets"])
        if type(self.v1_assets) is not future_assets.V1SourceAssets:
            raise NoGoError("only the exact V1SourceAssets loader can supply the frozen guard/inference")
        if _module_sha256(self.v1_assets) != self.pins.identity_sha256["v1_assets_loader_sha256"]:
            raise NoGoError("V1SourceAssets loader code SHA is not pinned")
        if sha256_bytes(self.v1_assets.guard_code) != self.pins.identity_sha256["non_overwrite_guard_sha256"]:
            raise NoGoError("original frozen V2 guard bytes differ from the PRE_STUDY pin")
        if sha256_bytes(self.v1_assets.inference_code) != self.pins.identity_sha256["predictor_bridge_sha256"]:
            raise NoGoError("original frozen inference bytes differ from the PRE_STUDY pin")
        constants = {
            "model_sha256": future_assets.MODEL_SHA256,
            "scaler_sha256": future_assets.SCALER_SHA256,
            "params_sha256": future_assets.PARAMS_SHA256,
        }
        if any(constants[key] != self.pins.identity_sha256[key] for key in constants):
            raise NoGoError("frozen model/scaler/parameter constants differ from PRE_STUDY")
        if self.exposure_index is None:
            raise NoGoError("live execution is NO_GO: exact frozen exposure ledger is not loaded")

    def _validate_authorization_payload(self, authorization: AuthorizationBundle) -> tuple[Mapping[str, Any], Mapping[str, Any], datetime]:
        assert self.pins is not None
        if sha256_bytes(authorization.grant_bytes) != self.pins.grant_sha256:
            raise NoGoError("authorization grant bytes do not match externally pinned SHA")
        if sha256_bytes(authorization.pre_study_bytes) != self.pins.pre_study_sha256:
            raise NoGoError("PRE_STUDY bytes do not match externally pinned SHA")
        grant = _parse_json_object(authorization.grant_bytes, "authorization grant")
        pre = _parse_json_object(authorization.pre_study_bytes, "PRE_STUDY")
        expected_identity = dict(self.pins.identity_sha256)
        fixed = {
            "study_id": STUDY_ID,
            "scope": "P515_PROSPECTIVE_VALIDATION",
            "authorization": "AUTHORIZED",
            "D_start": STUDY_START.isoformat(),
            "D_end": STUDY_END.isoformat(),
            "D_dates": [value.isoformat() for value in fixed_d_dates()],
            "earliest_K3": EARLIEST_K3.isoformat(),
            "latest_PB15": LATEST_PB15.isoformat(),
            "fixed_readout": FIXED_READOUT.isoformat(),
            "pre_study_deadline": PRE_STUDY_DEADLINE.isoformat(),
            "output_root": str(self.output_root),
            "input_deadline": "21:30 Asia/Shanghai",
            "output_readback_deadline": "23:30 Asia/Shanghai",
            "max_batches": MODEL_BATCH_LIMIT,
            "max_paired_output_rows": PAIRED_OUTPUT_ROW_LIMIT,
            "max_unique_pb": UNIQUE_PB_LIMIT,
        }
        for key, expected in fixed.items():
            if grant.get(key) != expected:
                raise NoGoError(f"authorization grant does not explicitly bind {key}")
        if grant.get("identity_pins") != expected_identity:
            raise NoGoError("authorization grant identity pins differ from the externally locked values")
        if pre.get("study_id") != STUDY_ID or pre.get("artifact") != "PRE_STUDY":
            raise NoGoError("PRE_STUDY artifact identity mismatch")
        if pre.get("grant_sha256") != self.pins.grant_sha256 or pre.get("output_root") != str(self.output_root):
            raise NoGoError("PRE_STUDY must bind the exact grant and fixed output root")
        if pre.get("identity_pins") != expected_identity:
            raise NoGoError("PRE_STUDY identity pins differ from the externally locked values")
        for key, expected in fixed.items():
            if key in ("scope", "authorization"):
                continue
            if pre.get(key) != expected:
                raise NoGoError(f"PRE_STUDY does not explicitly bind {key}")
        try:
            issued_at = datetime.fromisoformat(str(grant["issued_at"]).replace("Z", "+00:00"))
            expires_at = datetime.fromisoformat(str(grant["expires_at"]).replace("Z", "+00:00"))
            sealed_at = datetime.fromisoformat(str(pre["sealed_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise NoGoError("authorization/PRE_STUDY must include valid timestamps") from exc
        if any(value.tzinfo is None for value in (issued_at, expires_at, sealed_at)):
            raise NoGoError("authorization/PRE_STUDY timestamps must include timezone")
        cutoff_utc = PRE_STUDY_DEADLINE.astimezone(UTC)
        if issued_at.astimezone(UTC) > cutoff_utc or sealed_at.astimezone(UTC) > cutoff_utc:
            raise NoGoError("authorization and PRE_STUDY must be frozen by 2026-11-20 20:00 Asia/Shanghai")
        now = self._now()
        if now >= expires_at.astimezone(UTC):
            raise NoGoError("authorization has expired")
        return grant, pre, expires_at.astimezone(UTC)

    def _verify_pinned_drive_file(
        self, *, file_id: str, name: str, raw: bytes, sha256: str,
        expected_version: str | None,
    ) -> VerifiedDriveReceipt:
        assert self.pins is not None and isinstance(self.drive_store, GoogleDriveReadbackStore)
        now = self._now()
        expectation = DriveFileExpectation(
            file_id=file_id,
            name=name,
            parent_id=self.pins.parent_id,
            mime_type=self.pins.evidence_mime_type,
            sha256=sha256,
            size_bytes=len(raw),
            expected_version=expected_version,
            created_not_after=PRE_STUDY_DEADLINE,
            modified_not_after=PRE_STUDY_DEADLINE,
        )
        try:
            receipt = self.drive_store.verify(file_id, expectation)
        except DriveEvidenceError as exc:
            raise NoGoError(f"live Drive authorization readback failed: {exc}") from exc
        if receipt.observed_at > self._now():
            raise NoGoError("Drive verification clock is ahead of the coordinator")
        return receipt

    def authorize_study(self, authorization: AuthorizationBundle) -> VerifiedAuthorization:
        """Read back grant/PRE_STUDY from real Drive before any D input is accepted."""
        self._validate_identity_lock()
        assert self.pins is not None and self.store is not None
        now = self._now()
        late_restore = now > PRE_STUDY_DEADLINE.astimezone(UTC)
        original_authorization = None
        if late_restore:
            original_authorization = self.store.original_authorization_event()
            if original_authorization is None:
                raise NoGoError("PRE_STUDY deadline passed without a persisted pre-deadline external readback; no late start")
            original_at, original_payload = original_authorization
            if original_at > PRE_STUDY_DEADLINE.astimezone(UTC):
                raise NoGoError("persisted authorization readback was not before the PRE_STUDY deadline")
            for field in ("grant", "pre_study"):
                raw_receipt = original_payload.get(field)
                if not isinstance(raw_receipt, dict) or raw_receipt.get("observed_at") is None:
                    raise NoGoError("persisted pre-deadline authorization receipt is incomplete")
                try:
                    receipt_time = datetime.fromisoformat(str(raw_receipt["observed_at"]).replace("Z", "+00:00"))
                except ValueError as exc:
                    raise NoGoError("persisted pre-deadline Drive receipt time is invalid") from exc
                if receipt_time.tzinfo is None or receipt_time.astimezone(UTC) > PRE_STUDY_DEADLINE.astimezone(UTC):
                    raise NoGoError("original Drive receipt was not read back before the PRE_STUDY deadline")
        _, _, expires_at = self._validate_authorization_payload(authorization)
        grant_receipt = self._verify_pinned_drive_file(
            file_id=self.pins.grant_file_id,
            name=self.pins.grant_name,
            raw=authorization.grant_bytes,
            sha256=self.pins.grant_sha256,
            expected_version=self.pins.grant_version,
        )
        pre_receipt = self._verify_pinned_drive_file(
            file_id=self.pins.pre_study_file_id,
            name=self.pins.pre_study_name,
            raw=authorization.pre_study_bytes,
            sha256=self.pins.pre_study_sha256,
            expected_version=self.pins.pre_study_version,
        )
        verified_at = self._now()
        if grant_receipt.observed_at > verified_at or pre_receipt.observed_at > verified_at:
            raise NoGoError("Drive verification clock is ahead of the coordinator")
        if verified_at >= expires_at:
            raise NoGoError("authorization expired during Drive readback")
        if not late_restore and verified_at > PRE_STUDY_DEADLINE.astimezone(UTC):
            raise NoGoError("the original PRE_STUDY Drive readback completed after its hard deadline")
        if late_restore:
            assert original_authorization is not None
            _, original_payload = original_authorization
            if (self._receipt_identity(grant_receipt) != self._receipt_identity_from_payload(original_payload["grant"])
                    or self._receipt_identity(pre_receipt) != self._receipt_identity_from_payload(original_payload["pre_study"])):
                raise NoGoError("restored Drive grant/PRE_STUDY differs from the original pre-deadline receipt")
        gate = VerifiedAuthorization(authorization, grant_receipt, pre_receipt, verified_at, self._gate_token)
        self._verified_authorization = gate
        self.store.append_event("STUDY_AUTHORIZATION_RESTORED" if late_restore else "STUDY_AUTHORIZATION_VERIFIED", None, {
            "grant": self._receipt_payload(grant_receipt),
            "pre_study": self._receipt_payload(pre_receipt),
            "grant_sha256": self.pins.grant_sha256,
            "pre_study_sha256": self.pins.pre_study_sha256,
            "identity_lock_sha256": self.pins.identity_lock_sha256,
        }, created_at=verified_at)
        return gate

    @staticmethod
    def _receipt_identity_from_payload(payload: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            payload.get("file_id"), payload.get("name"), tuple(payload.get("parent_ids", ())),
            payload.get("mime_type"), payload.get("version_token"), payload.get("version_source"),
            payload.get("size_bytes"), payload.get("sha256"),
            datetime.fromisoformat(str(payload["created_time"]).replace("Z", "+00:00")).astimezone(UTC),
            datetime.fromisoformat(str(payload["modified_time"]).replace("Z", "+00:00")).astimezone(UTC),
        )

    def _require_preverified_authorization(
        self, authorization: VerifiedAuthorization | None, *, before: datetime,
    ) -> VerifiedAuthorization:
        if (authorization is None or authorization is not self._verified_authorization
                or authorization._coordinator_token is not self._gate_token):
            raise NoGoError("authorization/PRE_STUDY must be freshly verified through authorize_study first")
        if authorization.verified_at >= before:
            raise NoGoError("authorization/PRE_STUDY Drive readback must precede D input capture")
        _, _, expires_at = self._validate_authorization_payload(authorization.bundle)
        if self._now() >= expires_at:
            raise NoGoError("authorization has expired")
        return authorization

    @staticmethod
    def _receipt_identity(receipt: VerifiedDriveReceipt) -> tuple[Any, ...]:
        return (
            receipt.file_id, receipt.name, receipt.parent_ids, receipt.mime_type,
            receipt.version_token, receipt.version_source, receipt.size_bytes,
            receipt.sha256, receipt.created_time, receipt.modified_time,
        )

    def _refresh_authorization(self, gate: VerifiedAuthorization) -> tuple[VerifiedDriveReceipt, VerifiedDriveReceipt]:
        assert self.pins is not None
        _, _, expires_at = self._validate_authorization_payload(gate.bundle)
        if self._now() >= expires_at:
            raise NoGoError("authorization has expired")
        current_grant = self._verify_pinned_drive_file(
            file_id=self.pins.grant_file_id, name=self.pins.grant_name,
            raw=gate.bundle.grant_bytes, sha256=self.pins.grant_sha256,
            expected_version=self.pins.grant_version,
        )
        current_pre = self._verify_pinned_drive_file(
            file_id=self.pins.pre_study_file_id, name=self.pins.pre_study_name,
            raw=gate.bundle.pre_study_bytes, sha256=self.pins.pre_study_sha256,
            expected_version=self.pins.pre_study_version,
        )
        if (self._receipt_identity(current_grant) != self._receipt_identity(gate.grant_receipt)
                or self._receipt_identity(current_pre) != self._receipt_identity(gate.pre_study_receipt)):
            raise NoGoError("externally pinned authorization/PRE_STUDY Drive version changed")
        return current_grant, current_pre

    def _refresh_input_receipt(self, prepared: PreparedDay) -> VerifiedDriveReceipt:
        assert self.pins is not None and isinstance(self.drive_store, GoogleDriveReadbackStore)
        original = prepared.input_receipt
        if original is None:
            raise NoGoError("input Drive receipt is not persisted")
        input_deadline = _local_datetime(date.fromisoformat(f"{prepared.D[:4]}-{prepared.D[4:6]}-{prepared.D[6:8]}"), INPUT_DEADLINE)
        expectation = DriveFileExpectation(
            file_id=original.file_id,
            name=f"P515_{prepared.D}_D_ONLY_INPUT.json",
            parent_id=self.pins.parent_id,
            mime_type=self.pins.evidence_mime_type,
            sha256=prepared.input_sha256,
            size_bytes=len(prepared.input_manifest_bytes),
            expected_version=original.version_token,
            created_not_after=input_deadline,
            modified_not_after=input_deadline,
        )
        current = self.drive_store.verify(original.file_id, expectation)
        if current.observed_at > self._now():
            raise NoGoError("input Drive verification clock is ahead of the coordinator")
        if self._receipt_identity(current) != self._receipt_identity(original):
            raise NoGoError("pre-score D-only input file ID/version/bytes/parent changed after seal")
        return current

    def _validate_source(self, daily: DailyPoolInput) -> SourceValidation:
        d = _as_date(daily.D, "D")
        if not isinstance(daily.top200_body, bytes) or not daily.top200_body:
            raise EvidenceError("raw Top200 response body bytes are required")
        if not isinstance(daily.reader_evidence, bytes) or not daily.reader_evidence:
            raise EvidenceError("raw Reader evidence bytes are required")
        if len(daily.rows) != MAX_POOL_ROWS:
            raise EvidenceError("Top200 pool must contain exactly 200 rows")
        ranks = [row.rank for row in daily.rows]
        codes = [row.ts_code for row in daily.rows]
        if sorted(ranks) != list(range(1, MAX_POOL_ROWS + 1)) or len(set(ranks)) != MAX_POOL_ROWS:
            raise EvidenceError("Top200 ranks must be exactly 1..200")
        if len(set(codes)) != MAX_POOL_ROWS or any(not code for code in codes):
            raise EvidenceError("Top200 securities must be 200 unique non-empty codes")
        if not daily.source_generation or not _hex_sha(daily.generation_manifest_sha256) or not _hex_sha(daily.source_input_sha256):
            raise EvidenceError("source generation, manifest SHA, and input SHA are required")
        if self.source_verifier is None:
            raise NoGoError("Top200/Reader source verifier not wired")
        matrix_bytes, matrix_sha, keys_sha, projection_sha = canonical_matrix_and_keys(daily.rows)
        proof = self.source_verifier.verify(daily, matrix_sha, keys_sha, projection_sha)
        if not isinstance(proof, SourceProof):
            raise EvidenceError("source verifier must return SourceProof")
        if proof.proof_sha256 != sha256_bytes(_canonical_json(_source_proof_payload(proof))):
            raise EvidenceError("source proof digest mismatch")
        expected_roster = tuple(
            (row.rank, row.ts_code, row.source_trade_date)
            for row in sorted(daily.rows, key=lambda r: r.rank)
        )
        if proof.D != compact_d(d) or proof.top200_roster != expected_roster:
            raise EvidenceError("source proof roster/D differs from the complete input rows")
        if proof.top200_body_sha256 != sha256_bytes(daily.top200_body):
            raise EvidenceError("Top200 proof does not bind the actual response bytes")
        if proof.reader_evidence_sha256 != sha256_bytes(daily.reader_evidence):
            raise EvidenceError("Reader proof does not bind the actual Reader evidence bytes")
        if proof.source_generation != daily.source_generation:
            raise EvidenceError("Top200 and Reader source generation mismatch")
        if proof.generation_manifest_sha256 != daily.generation_manifest_sha256 or proof.source_input_sha256 != daily.source_input_sha256:
            raise EvidenceError("generation or source input identity mismatch")
        if proof.reader_projection_sha256 != projection_sha or proof.canonical_matrix_sha256 != matrix_sha or proof.canonical_keys_sha256 != keys_sha:
            raise EvidenceError("Reader projection, canonical feature matrix, or key hash mismatch")
        if proof.reader_manifest_sha256 != daily.generation_manifest_sha256:
            raise EvidenceError("Reader manifest differs from the bound D generation")
        if _as_date(proof.reader_query_end, "reader query end") != d:
            raise EvidenceError("Reader query must end exactly on D")
        if _as_date(proof.reader_query_start, "reader query start") > d:
            raise EvidenceError("Reader query starts after D")
        if proof.reader_max_trade_date is not None and _as_date(proof.reader_max_trade_date, "reader max trade date") > d:
            raise EvidenceError("Reader projection contains post-D rows")
        if proof.reader_max_trade_date is None and any(row.bar_values is not None for row in daily.rows):
            raise EvidenceError("empty Reader projection cannot contain D bar values")
        if any(_as_date(row.source_trade_date, "source trade date") != d for row in daily.rows):
            raise EvidenceError("Top200 roster source date differs from D")
        if proof.price_basis != "QFQ_ASOF" or proof.volume_basis != "QFQ_EVENT_VOLUME":
            raise EvidenceError("D price/volume adjustment basis is unbound at the source level")
        if len(set(proof.qfq_basis_conflicts)) != len(proof.qfq_basis_conflicts) or not set(proof.qfq_basis_conflicts).issubset(set(codes)):
            raise EvidenceError("per-security QFQ conflict list is malformed or outside Top200")
        if self.pins is not None:
            identities = self.pins.identity_sha256
            if proof.reader_code_sha256 != identities["v4_reader_sha256"]:
                raise EvidenceError("Reader implementation SHA differs from PRE_STUDY pin")
            if proof.top200_code_sha256 != identities["top200_parser_sha256"]:
                raise EvidenceError("Top200 producer/parser SHA differs from PRE_STUDY pin")
            if proof.source_evidence_verifier_sha256 != identities["source_evidence_verifier_sha256"]:
                raise EvidenceError("raw Top200/Reader evidence verifier SHA differs from PRE_STUDY pin")
            if _module_sha256(self.source_verifier) != identities["wiring_module_sha256"]:
                raise EvidenceError("source wiring module SHA differs from PRE_STUDY pin")
        observed = _aware(proof.source_observed_at, "source observed at")
        captured = _aware(daily.captured_at, "D capture time")
        if observed > captured:
            raise EvidenceError("source observation timestamp is later than the captured D input")
        return SourceValidation(proof, matrix_sha, keys_sha, projection_sha)

    def _validate_state(self, daily: DailyPoolInput) -> tuple[Mapping[str, StateProof], Mapping[str, StateEvidence]]:
        if self.state_verifier is None:
            raise NoGoError("R2 state adapter not wired")
        if self.pins is not None and _module_sha256(self.state_verifier) != self.pins.identity_sha256["wiring_module_sha256"]:
            raise NoGoError("R2 state wiring module bytes differ from PRE_STUDY pin")
        verified = self.state_verifier.verify(daily, daily.rows, self.pins)
        if isinstance(verified, tuple) and len(verified) == 2:
            proofs, evidence_by_security = verified
        else:
            proofs, evidence_by_security = verified, daily.state_evidence_by_security
        if not isinstance(proofs, Mapping):
            raise EvidenceError("R2 state verifier must return per-security StateProof mapping")
        if set(proofs) != {row.ts_code for row in daily.rows}:
            raise EvidenceError("R2 state proof must cover all 200 roster securities")
        for code, proof in proofs.items():
            if not isinstance(proof, StateProof) or proof.ts_code != code or proof.D != compact_d(daily.D):
                raise EvidenceError("R2 state proof key/D mismatch")
            if proof.status not in ("PROVEN", "UNKNOWN"):
                raise EvidenceError("R2 state status must be PROVEN or UNKNOWN")
            if proof.status == "PROVEN":
                evidence = evidence_by_security.get(code)
                if evidence is None or not evidence.anchor_receipt_bytes or not evidence.checkpoint_bytes:
                    raise EvidenceError("PROVEN state lacks raw per-security anchor/checkpoint bytes")
                if not _hex_sha(proof.anchor_receipt_sha256) or sha256_bytes(evidence.anchor_receipt_bytes) != proof.anchor_receipt_sha256:
                    raise EvidenceError("per-security anchor receipt bytes do not match the state proof")
                if not _hex_sha(proof.checkpoint_sha256) or sha256_bytes(evidence.checkpoint_bytes) != proof.checkpoint_sha256:
                    raise EvidenceError("per-security checkpoint bytes do not match the state proof")
                if self.pins is not None and proof.adapter_sha256 != self.pins.identity_sha256["r2_state_adapter_sha256"]:
                    raise EvidenceError("candidate proof R2 adapter SHA mismatch")
                if proof.proof_sha256 != compute_state_proof_sha256(proof):
                    raise EvidenceError("R2 state proof content hash mismatch")
        return proofs, evidence_by_security

    @staticmethod
    def _valid_bar(row: PoolRow, d: date) -> bool:
        if row.bar_trade_date != d.isoformat() or row.bar_values is None or len(row.bar_values) != 5:
            return False
        try:
            o, h, l, c, v = (float(x) for x in row.bar_values)
        except (TypeError, ValueError):
            return False
        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
            return False
        if min(o, h, l, c, v) <= 0 or h < max(o, c, l) or l > min(o, c):
            return False
        return True

    @staticmethod
    def _valid_features(features: tuple[float, ...] | None) -> bool:
        if features is None or len(features) != len(FEATURE_NAMES):
            return False
        try:
            values = tuple(float(x) for x in features)
        except (TypeError, ValueError):
            return False
        if not all(math.isfinite(x) for x in values):
            return False
        return all(values[i] in (0.0, 1.0) for i in BINARY_FEATURE_INDICES)

    @staticmethod
    def _valid_origin_binding(row: PoolRow, proof: StateProof) -> bool:
        try:
            origin = _as_date(proof.origin_date, "R2 origin date")
        except EvidenceError:
            return False
        expected_mother = f"P5146_EVENT_RULE_R2:{row.ts_code}:{origin:%Y%m%d}"
        if proof.mother_key != expected_mother or not proof.pb_id:
            return False
        prefix = expected_mother + ":PB"
        if not proof.pb_id.startswith(prefix):
            return False
        suffix = proof.pb_id[len(prefix):]
        return suffix.isdecimal() and int(suffix) > 0

    def _dispositions(
        self, daily: DailyPoolInput, proofs: Mapping[str, StateProof], qfq_conflicts: frozenset[str] = frozenset(),
    ) -> tuple[tuple[RowDisposition, ...], tuple[tuple[str, str, int, str | None], ...]]:
        d = _as_date(daily.D, "D")
        result: list[RowDisposition] = []
        events: list[tuple[str, str, int, str | None]] = []
        seen_pb: set[tuple[str, str]] = set()
        seen_mother: set[tuple[str, str]] = set()
        for row in sorted(daily.rows, key=lambda r: r.rank):
            disposition: str
            reason: str | None = None
            proof = proofs[row.ts_code]
            mother: str | None = None
            pb_id: str | None = None
            event_key: str | None = None
            if row.market not in ("SH", "SZ") or row.instrument_type != "COMMON_A":
                disposition = "OUTSIDE_SH_SZ_A"
            elif not self._valid_bar(row, d):
                disposition = "INVALID_OR_MISSING_D_BAR"
            elif proof.status != "PROVEN":
                disposition = "STATE_ANCHOR_UNKNOWN"
            elif proof.stage != "SAME_EVENT_PULLBACK" or proof.pullback_sessions != 3 or proof.terminal_on_D is not False:
                disposition = "NO_AT_RISK_K3"
            elif d < EARLIEST_K3:
                disposition = "NO_AT_RISK_K3"
            elif not proof.mother_key or not proof.pb_id or not proof.origin_date:
                disposition = "STATE_ANCHOR_UNKNOWN"
                reason = "state proof omitted event identity"
            else:
                mother, pb_id = proof.mother_key, proof.pb_id
                mother_id = (row.ts_code, mother)
                pb_identity = (row.ts_code, pb_id)
                if (self.exposure_index and pb_identity in self.exposure_index.known_pb) or pb_identity in seen_pb:
                    disposition = "DUPLICATE_PB"
                elif self.exposure_index and mother_id in self.exposure_index.known_mothers:
                    disposition = "KNOWN_EXPOSURE_OR_CONTINUATION"
                elif not self._valid_origin_binding(row, proof):
                    disposition = "EXPOSURE_BIRTH_UNCONFIRMED"
                elif _as_date(proof.origin_date, "R2 origin date") <= date(2026, 11, 20):
                    disposition = "EXPOSURE_BIRTH_UNCONFIRMED"
                elif not (STUDY_START <= _as_date(proof.origin_date, "R2 origin date") <= d <= STUDY_END):
                    disposition = "EXPOSURE_BIRTH_UNCONFIRMED"
                elif not self._valid_origin_binding(row, proof):
                    disposition = "STATE_ANCHOR_UNKNOWN"
                    reason = "PB key does not bind the R2 mother"
                else:
                    try:
                        ordinal = int(pb_id.rsplit(":PB", 1)[1])
                    except (ValueError, IndexError):
                        ordinal = 0
                    if ordinal <= 0:
                        disposition = "STATE_ANCHOR_UNKNOWN"
                        reason = "PB ordinal is invalid"
                    elif ordinal > 1 and not self._prior_terminal_before(proof.prior_pb_terminal_date, d):
                        disposition = "KNOWN_EXPOSURE_OR_CONTINUATION"
                    elif row.ts_code in qfq_conflicts:
                        disposition = "QFQ_BASIS_CONFLICT"
                    elif proof.status == "PROVEN" and not self._valid_features(row.features):
                        disposition = "MISSING_OR_NONFINITE_FEATURE"
                    else:
                        disposition = "ELIGIBLE"
                        event_key = f"{self.pins.identity_sha256['r2_rules_sha256'] if self.pins else 'FIXTURE_R2'}:{row.ts_code}:{pb_id}:{compact_d(d)}"
                        seen_pb.add(pb_identity)
                        seen_mother.add(mother_id)
                        events.append((
                            f"{row.ts_code}|{pb_id}",
                            f"{row.ts_code}|{mother}",
                            ordinal,
                            None,
                        ))
                        # Unknown historical crosswalks require a proved new mother
                        # origin and a hash-bound R2 state proof; unresolved rows stay
                        # visible in the population ledger and do not become negatives.
                        if self.exposure_index and row.ts_code in self.exposure_index.unknown_crosswalk_by_security:
                            reason = "new R2 mother origin after PRE_STUDY; historical crosswalk remains incomplete"
            result.append(RowDisposition(row.rank, row.ts_code, disposition, mother, pb_id, event_key, reason))
        return tuple(result), tuple(events)

    @staticmethod
    def _prior_terminal_before(value: str | None, d: date) -> bool:
        if value is None:
            return False
        try:
            return _as_date(value, "prior PB terminal date") < d
        except EvidenceError:
            return False

    def _make_manifest(
        self, daily: DailyPoolInput, source: SourceValidation,
        dispositions: Sequence[RowDisposition], state_proofs: Mapping[str, StateProof],
        state_evidence: Mapping[str, StateEvidence],
        authorization_receipts: Mapping[str, VerifiedDriveReceipt] | None = None,
    ) -> bytes:
        rows_by_code = {row.ts_code: row for row in daily.rows}
        eligible = [item for item in dispositions if item.disposition == "ELIGIBLE"]
        evidence_entries = []
        for item in sorted(eligible, key=lambda value: value.rank):
            evidence = state_evidence.get(item.ts_code)
            if evidence is None or not evidence.anchor_receipt_bytes or not evidence.checkpoint_bytes:
                raise EvidenceError("eligible row lacks raw R2 anchor/checkpoint evidence")
            proof = state_proofs[item.ts_code]
            if (sha256_bytes(evidence.anchor_receipt_bytes) != proof.anchor_receipt_sha256
                    or sha256_bytes(evidence.checkpoint_bytes) != proof.checkpoint_sha256):
                raise EvidenceError("eligible R2 state evidence changed before manifest construction")
            evidence_entries.append({
                "rank": item.rank,
                "ts_code": item.ts_code,
                "anchor_receipt_sha256": proof.anchor_receipt_sha256,
                "anchor_receipt_bytes_b64": base64.b64encode(evidence.anchor_receipt_bytes).decode("ascii"),
                "checkpoint_sha256": proof.checkpoint_sha256,
                "checkpoint_bytes_b64": base64.b64encode(evidence.checkpoint_bytes).decode("ascii"),
            })
        state_evidence_bytes = _canonical_json({
            "schema": "P515_ELIGIBLE_R2_STATE_EVIDENCE_V1",
            "D": compact_d(daily.D),
            "evidence": evidence_entries,
        }) + b"\n"
        payload = {
            "schema": "P515_DAILY_INPUT_MANIFEST_V1",
            "study_id": self.study_id,
            "D": compact_d(daily.D),
            "captured_at": _aware(daily.captured_at, "D capture time").isoformat(),
            "top200_body_sha256": sha256_bytes(daily.top200_body),
            "reader_evidence_sha256": sha256_bytes(daily.reader_evidence),
            "source_generation": source.proof.source_generation,
            "generation_manifest_sha256": source.proof.generation_manifest_sha256,
            "source_input_sha256": source.proof.source_input_sha256,
            "canonical_matrix_sha256": source.canonical_matrix_sha256,
            "canonical_keys_sha256": source.canonical_keys_sha256,
            "row_projection_sha256": source.row_projection_sha256,
            "reader_manifest_sha256": source.proof.reader_manifest_sha256,
            "reader_query_start": source.proof.reader_query_start,
            "reader_query_end": source.proof.reader_query_end,
            "reader_max_trade_date": source.proof.reader_max_trade_date,
            "source_observed_at": _aware(source.proof.source_observed_at, "source observed at").isoformat(),
            "price_basis": source.proof.price_basis,
            "volume_basis": source.proof.volume_basis,
            "qfq_basis_conflicts": list(source.proof.qfq_basis_conflicts),
            "source_proof_sha256": source.proof.proof_sha256,
            "reader_code_sha256": source.proof.reader_code_sha256,
            "top200_code_sha256": source.proof.top200_code_sha256,
            "source_evidence_verifier_sha256": source.proof.source_evidence_verifier_sha256,
            "eligible_state_evidence_sha256": sha256_bytes(state_evidence_bytes),
            "eligible_state_evidence_size_bytes": len(state_evidence_bytes),
            # The base64 form is lossless: decoding each value recovers the
            # original receipt/checkpoint bytes whose SHA is bound above. The
            # exact canonical sidecar is also written with O_EXCL/fsync below.
            "eligible_state_evidence": evidence_entries,
            "identity_lock_sha256": self.pins.identity_lock_sha256 if self.pins else "SYNTHETIC_FIXTURE_ONLY",
            "authorization_receipts": {
                key: {
                    "file_id": value.file_id,
                    "name": value.name,
                    "parent_ids": list(value.parent_ids),
                    "version_token": value.version_token,
                    "version_source": value.version_source,
                    "sha256": value.sha256,
                    "size_bytes": value.size_bytes,
                    "created_time": value.created_time.isoformat(),
                    "modified_time": value.modified_time.isoformat(),
                    "observed_at": value.observed_at.isoformat(),
                }
                for key, value in sorted((authorization_receipts or {}).items())
            },
            "roster_disposition": [
                {
                    "rank": item.rank,
                    "ts_code": item.ts_code,
                    "disposition": item.disposition,
                    "reason": item.reason,
                    "mother_key": item.mother_key,
                    "pb_id": item.pb_id,
                    "event_key": item.event_key,
                    "bar_values": rows_by_code[item.ts_code].bar_values,
                    "features": rows_by_code[item.ts_code].features,
                    "state_proof_sha256": state_proofs[item.ts_code].proof_sha256,
                    "anchor_receipt_sha256": state_proofs[item.ts_code].anchor_receipt_sha256,
                    "checkpoint_sha256": state_proofs[item.ts_code].checkpoint_sha256,
                }
                for item in dispositions
            ],
        }
        return _canonical_json(payload) + b"\n"

    def _reserve_prepared(
        self, daily: DailyPoolInput, source: SourceValidation,
        dispositions: tuple[RowDisposition, ...], event_records: Sequence[tuple[str, str, int, str | None]],
        manifest: bytes, *, authorization_receipts: Mapping[str, VerifiedDriveReceipt],
        input_receipt: VerifiedDriveReceipt | None,
    ) -> PreparedDay:
        if self.store is None:
            raise NoGoError("coordinator persistence is disabled until real authorization is pinned")
        eligible_count = sum(item.disposition == "ELIGIBLE" for item in dispositions)
        output_rows = 2 * eligible_count
        input_sha = sha256_bytes(manifest)
        day = compact_d(daily.D)
        attempt_id = sha256_bytes(_canonical_json({"study_id": self.study_id, "D": day, "input_sha256": input_sha}))
        now = self._now()
        self.store.reserve(
            D=day,
            attempt_id=attempt_id,
            eligible_count=eligible_count,
            output_rows=output_rows,
            input_sha256=input_sha,
            matrix_sha256=source.canonical_matrix_sha256,
            keys_sha256=source.canonical_keys_sha256,
            event_records=event_records,
            created_at=now,
            input_receipt=input_receipt,
        )
        day_dir = self.study_root / day
        if input_receipt is not None:
            self._write_new(day_dir / "INPUT_DRIVE_RECEIPT.json", _canonical_json(self._receipt_payload(input_receipt)) + b"\n")
        prepared = PreparedDay(
            study_id=self.study_id,
            D=day,
            attempt_id=attempt_id,
            input_sha256=input_sha,
            canonical_matrix_sha256=source.canonical_matrix_sha256,
            canonical_keys_sha256=source.canonical_keys_sha256,
            eligible_count=eligible_count,
            paired_output_rows=output_rows,
            dispositions=dispositions,
            input_manifest_bytes=manifest,
            reservation_path=str(day_dir),
            fixture_only=self.fixture_only,
            authorization_receipts=dict(authorization_receipts),
            input_receipt=input_receipt,
        )
        self._prepared[day] = prepared
        return prepared

    @staticmethod
    def _receipt_payload(receipt: VerifiedDriveReceipt) -> Mapping[str, Any]:
        return {
            "file_id": receipt.file_id,
            "name": receipt.name,
            "parent_ids": list(receipt.parent_ids),
            "mime_type": receipt.mime_type,
            "version_token": receipt.version_token,
            "version_source": receipt.version_source,
            "size_bytes": receipt.size_bytes,
            "sha256": receipt.sha256,
            "created_time": receipt.created_time.isoformat(),
            "modified_time": receipt.modified_time.isoformat(),
            "observed_at": receipt.observed_at.isoformat(),
        }

    def _write_new(self, path: Path, raw: bytes) -> None:
        stream_context = self.guard_module.open_exclusive_binary(path) if self.guard_module else _CoordinatorStore._exclusive_binary(path)
        with stream_context as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def _validate_created_receipt(
        self, receipt: VerifiedDriveReceipt, *, name: str, raw: bytes,
        deadline: datetime, not_before: datetime,
    ) -> None:
        if not isinstance(receipt, VerifiedDriveReceipt):
            raise EvidenceError("Drive store must return its bracketed verified receipt")
        assert self.pins is not None
        if (receipt.name != name or receipt.parent_ids != (self.pins.parent_id,)
                or receipt.mime_type != self.pins.evidence_mime_type
                or receipt.size_bytes != len(raw) or receipt.sha256 != sha256_bytes(raw)
                or not receipt.version_token):
            raise EvidenceError("Drive receipt identity/size/version/raw-byte mismatch")
        deadline_utc = deadline.astimezone(UTC)
        if (receipt.created_time > deadline_utc or receipt.modified_time > deadline_utc
                or receipt.observed_at > deadline_utc):
            raise EvidenceError("Drive create/modify/readback missed the fixed deadline")
        if receipt.observed_at < not_before.astimezone(UTC):
            raise EvidenceError("Drive readback predates the source capture")

    def _prepare_local_files(self, daily: DailyPoolInput, manifest: bytes) -> str:
        if self.store is None:
            raise NoGoError("coordinator persistence is disabled")
        day = compact_d(daily.D)
        intent_id = sha256_bytes(_canonical_json({
            "study_id": self.study_id, "D": day, "input_sha256": sha256_bytes(manifest),
        }))
        day_dir = self.store.claim_intent(day, intent_id, created_at=self._now())
        # Keep only this bounded D Top200 response, its exact Reader projection,
        # and the derived input manifest. No panel snapshot is materialized.
        payload = _parse_json_object(manifest.rstrip(b"\n"), "D-only input manifest")
        evidence_entries = payload.get("eligible_state_evidence")
        if not isinstance(evidence_entries, list):
            raise EvidenceError("D-only manifest has no eligible state evidence list")
        state_evidence_bytes = _canonical_json({
            "schema": "P515_ELIGIBLE_R2_STATE_EVIDENCE_V1",
            "D": compact_d(daily.D),
            "evidence": evidence_entries,
        }) + b"\n"
        if (sha256_bytes(state_evidence_bytes) != payload.get("eligible_state_evidence_sha256")
                or len(state_evidence_bytes) != payload.get("eligible_state_evidence_size_bytes")):
            raise EvidenceError("eligible state evidence sidecar differs from manifest binding")
        self._write_new(day_dir / "TOP200_RAW.bin", daily.top200_body)
        self._write_new(day_dir / "READER_EVIDENCE.bin", daily.reader_evidence)
        self._write_new(day_dir / "ELIGIBLE_R2_STATE_EVIDENCE.json", state_evidence_bytes)
        self._write_new(day_dir / "INPUT_MANIFEST.json", manifest)
        return intent_id

    def prepare_day(
        self,
        daily: DailyPoolInput,
        *,
        authorization: VerifiedAuthorization | None = None,
    ) -> PreparedDay:
        """Validate, seal and reserve one D. Never loads or invokes a predictor."""
        if self.fixture_only:
            if not daily.synthetic_fixture:
                raise NoGoError("fixture coordinator accepts only explicitly synthetic input")
        else:
            if daily.synthetic_fixture:
                raise NoGoError("synthetic fixture input cannot enter the live study")
            self._validate_identity_lock()
        d, captured_at, input_deadline = self._validate_day_clock(daily, phase="input")
        auth_receipts: dict[str, VerifiedDriveReceipt] = {}
        if not self.fixture_only:
            if authorization is None:
                raise NoGoError("new pinned authorization/PRE_STUDY must be verified before D input")
            gate = self._require_preverified_authorization(authorization, before=captured_at)
            auth_receipts = {"grant": gate.grant_receipt, "pre_study": gate.pre_study_receipt}
        source = self._validate_source(daily)
        state_proofs, state_evidence = self._validate_state(daily)
        dispositions, event_records = self._dispositions(
            daily, state_proofs, frozenset(source.proof.qfq_basis_conflicts)
        )
        manifest = self._make_manifest(daily, source, dispositions, state_proofs, state_evidence, auth_receipts)
        if self.store is None:
            raise NoGoError("coordinator persistence is disabled")
        self._prepare_local_files(daily, manifest)
        input_receipt = None
        if not self.fixture_only:
            assert self.pins is not None and isinstance(self.drive_store, GoogleDriveReadbackStore)
            name = f"P515_{compact_d(d)}_D_ONLY_INPUT.json"
            try:
                input_receipt = self.drive_store.create_once_and_verify(
                    name=name,
                    parent_id=self.pins.parent_id,
                    mime_type=self.pins.evidence_mime_type,
                    content=manifest,
                    expected_readback_deadline=input_deadline,
                    expected_created_not_after=input_deadline,
                    expected_modified_not_after=input_deadline,
                )
                self._validate_created_receipt(
                    input_receipt, name=name, raw=manifest,
                    deadline=input_deadline, not_before=captured_at,
                )
            except Exception as exc:
                self.store.append_intent_failure(compact_d(d), error_code=type(exc).__name__, at=self._now())
                raise
        return self._reserve_prepared(
            daily, source, dispositions, event_records, manifest,
            authorization_receipts=auth_receipts,
            input_receipt=input_receipt,
        )

    def execute_fixture_placeholder(
        self,
        prepared: PreparedDay,
        *,
        authorization_bytes: bytes,
        callback: Callable[[FixtureInvocation], Any],
    ) -> str:
        """Exercise only a synthetic callback; it cannot return probability rows."""
        if self.store is None or not self.fixture_only or not prepared.fixture_only or prepared.study_id != FIXTURE_ID:
            raise NoGoError("placeholder callback is restricted to a separate synthetic root")
        if authorization_bytes != FIXTURE_AUTHORIZATION_BYTES or sha256_bytes(authorization_bytes) != FIXTURE_AUTHORIZATION_SHA256:
            raise NoGoError("immutable fixture authorization does not match")
        row = self.store.attempt(prepared.D)
        if row is None or row["status"] != "RESERVED":
            raise NoGoError("fixture daily reservation is absent or already used")
        if prepared.eligible_count != 0 or prepared.paired_output_rows != 0:
            raise NoGoError("fixture placeholder must contain zero eligible rows")
        nonce = sha256_bytes(_canonical_json({"D": prepared.D, "input_sha256": prepared.input_sha256, "fixture": FIXTURE_ID}))
        invocation = FixtureInvocation(FIXTURE_ID, prepared.D, nonce)
        self.store.begin_fixture_callback(prepared.D, at=self._now())
        try:
            result = callback(invocation)
            if result != {"fixture_id": FIXTURE_ID, "status": "PLACEHOLDER_ONLY", "probability_rows": 0}:
                raise NoGoError("fixture callback must return the exact non-model placeholder marker")
            self.store.update_status(prepared.D, "FIXTURE_CALLBACK_PASS", at=self._now())
        except Exception as exc:
            self.store.update_status(prepared.D, "FIXTURE_CALLBACK_FAILED", error_code=type(exc).__name__, at=self._now())
            raise
        return "PLACEHOLDER_CALLBACK_PASS__MODEL_API_0__PROBABILITIES_0"

    def execute_reserved(
        self,
        prepared: PreparedDay,
        *,
        authorization: VerifiedAuthorization,
        predictor: Any,
        daily: DailyPoolInput,
    ) -> VerifiedDriveReceipt | None:
        """One future U/C call after hash-pinned grants, source, R2, seal, and budget.

        No predictor is loaded from this method unless all real gates have
        passed. Every call or seal failure after reservation consumes that D.
        """
        if self.fixture_only or self.store is None:
            raise NoGoError("fixture or default NO_GO coordinator cannot invoke a real model")
        self._validate_identity_lock()
        if prepared.fixture_only or prepared.study_id != STUDY_ID or daily.synthetic_fixture:
            raise NoGoError("fixture/preparation bytes cannot be promoted to a real run")
        d, captured_at, output_deadline = self._validate_day_clock(daily, phase="output")
        if compact_d(d) != prepared.D or not prepared.input_sha256 or prepared.input_receipt is None:
            raise NoGoError("reserved input identity/D/Drive receipt is missing")
        gate = self._require_preverified_authorization(authorization, before=captured_at)
        if (prepared.authorization_receipts.get("grant") is not gate.grant_receipt
                or prepared.authorization_receipts.get("pre_study") is not gate.pre_study_receipt):
            raise NoGoError("prepared input is bound to another authorization receipt")
        self._refresh_authorization(gate)
        current_source = self._validate_source(daily)
        state_proofs, state_evidence = self._validate_state(daily)
        dispositions, _ = self._dispositions(
            daily, state_proofs, frozenset(current_source.proof.qfq_basis_conflicts)
        )
        manifest = self._make_manifest(
            daily, current_source, dispositions, state_proofs, state_evidence,
            prepared.authorization_receipts
        )
        if sha256_bytes(manifest) != prepared.input_sha256:
            raise NoGoError("D-only input changed after durable Drive readback")
        if sum(item.disposition == "ELIGIBLE" for item in dispositions) != prepared.eligible_count:
            raise NoGoError("eligible event count changed after reservation")
        stored = self.store.attempt(prepared.D)
        if stored is None or stored["status"] != "RESERVED" or stored["attempt_id"] != prepared.attempt_id:
            raise NoGoError("reserved attempt is missing or already consumed")
        if (stored["input_file_id"] != prepared.input_receipt.file_id
                or stored["input_version"] != prepared.input_receipt.version_token
                or stored["input_readback_at"] != prepared.input_receipt.observed_at.isoformat()):
            raise NoGoError("persisted input Drive receipt differs from the prepared artifact")
        if prepared.eligible_count == 0:
            self.store.update_status(prepared.D, "EMPTY_DAY_NO_MODEL_CALL", at=self._now())
            return None

        self._refresh_input_receipt(prepared)

        future_assets = __import__("research.p515_prospective_readiness.future_assets", fromlist=["FrozenV1Predictor"])
        if type(predictor) is not future_assets.FrozenV1Predictor:
            raise NoGoError("only the exact FrozenV1Predictor bridge can be invoked")
        if predictor.sources is not self.v1_assets or _module_sha256(predictor) != self.pins.identity_sha256["v1_assets_loader_sha256"]:
            raise NoGoError("predictor bridge source assets/module do not match the frozen identity lock")
        if _aware(self._now(), "coordinator clock") > output_deadline.astimezone(UTC):
            raise NoGoError("23:30 output deadline passed before predictor invocation")
        try:
            model_lock_fd = self.store.acquire_model_run_lock()
        except NoGoError:
            self.store.update_status(prepared.D, "MODEL_LOCK_BUSY", error_code="CONCURRENT_MODEL_BATCH", at=self._now())
            raise
        call_state = {"started": False, "finished": False, "returned": False, "error": False}

        def append_call(event: Mapping[str, Any]) -> None:
            if not isinstance(event, Mapping) or event.get("event") not in (
                "MODEL_CALL_START", "MODEL_CALL_RETURN", "MODEL_CALL_ERROR"
            ):
                raise EvidenceError("frozen V1 predictor emitted an unrecognized call-log event")
            event_name = str(event["event"])
            if event_name == "MODEL_CALL_START":
                if call_state["started"]:
                    raise NoGoError("per-D model API budget permits one batch only")
                requested = event.get("requested_rows")
                if type(requested) is not int or requested != prepared.paired_output_rows:
                    raise EvidenceError("V1 model call row count differs from paired reservation")
                call_state["started"] = True
            else:
                if not call_state["started"] or call_state["finished"]:
                    raise NoGoError("V1 API completion event has no unique start")
                if event_name == "MODEL_CALL_RETURN":
                    returned = event.get("successful_rows")
                    if type(returned) is not int or returned != prepared.paired_output_rows:
                        raise EvidenceError("V1 model return row count differs from paired reservation")
                    call_state["returned"] = True
                else:
                    call_state["error"] = True
                call_state["finished"] = True
            self.store.append_event(event_name, prepared.D, dict(event), created_at=self._now())

        try:
            self.store.begin_model_call(prepared.D, at=self._now())
            eligible_codes = {item.ts_code for item in dispositions if item.disposition == "ELIGIBLE"}
            eligible_rows = tuple(sorted((row for row in daily.rows if row.ts_code in eligible_codes), key=lambda row: row.rank))
            raw_response = predictor(daily, eligible_rows, append_call=append_call)
            if not call_state["started"] or not call_state["finished"] or not call_state["returned"] or call_state["error"]:
                raise EvidenceError("V1 predictor returned without one complete predict_proba call")
            if len(raw_response) != prepared.paired_output_rows or not isinstance(raw_response, (list, tuple)):
                raise EvidenceError("V1 predictor must return exactly 2N paired rows")
            by_code = {item.ts_code: item for item in dispositions if item.disposition == "ELIGIBLE"}
            ordered = [
                (row.rank, row.ts_code, arm)
                for arm in ("U", "C") for row in eligible_rows
            ]
            output_rows = []
            for returned, expected in zip(raw_response, ordered, strict=True):
                if not isinstance(returned, Mapping) or set(returned) != {"rank", "ts_code", "arm", "probability"}:
                    raise EvidenceError("V1 predictor row must contain exactly rank/code/arm/probability")
                rank, code, arm = expected
                if type(returned["rank"]) is not int or (returned["rank"], returned["ts_code"], returned["arm"]) != expected:
                    raise EvidenceError("U/C output is not in frozen arm/rank/event order")
                try:
                    probability = float(returned["probability"])
                except (TypeError, ValueError) as exc:
                    raise EvidenceError("V1 probability is not numeric") from exc
                if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                    raise EvidenceError("V1 probability is nonfinite or outside [0,1]")
                disposition = by_code[code]
                output_rows.append({
                    "rank": rank,
                    "ts_code": code,
                    "arm": arm,
                    "probability": probability,
                    "event_key": disposition.event_key,
                    "mother_key": disposition.mother_key,
                    "pb_id": disposition.pb_id,
                })
            output_name = f"P515_{prepared.D}_U_C_OUTPUT.json"
            self.store.append_event("OUTPUT_SEAL_INTENT", prepared.D, {
                "output_name": output_name,
                "output_deadline": output_deadline.isoformat(),
                "expected_paired_rows": len(output_rows),
            }, created_at=self._now())
            day_events = self.store.day_events(prepared.D)
            output_bytes = _canonical_json({
                "schema": "P515_PAIRED_OUTPUT_V1",
                "study_id": STUDY_ID,
                "D": prepared.D,
                "attempt_id": prepared.attempt_id,
                "input_sha256": prepared.input_sha256,
                "canonical_matrix_sha256": prepared.canonical_matrix_sha256,
                "canonical_keys_sha256": prepared.canonical_keys_sha256,
                "input_drive_receipt": self._receipt_payload(prepared.input_receipt),
                "authorization_drive_receipts": {
                    key: self._receipt_payload(value)
                    for key, value in sorted(prepared.authorization_receipts.items())
                },
                "execution_counters_before_output_readback": self.execution_counts(),
                "D_execution_events_through_output_intent": day_events,
                "paired_rows": output_rows,
            }) + b"\n"
            self._write_new(Path(prepared.reservation_path) / "OUTPUT_RAW.bin", output_bytes)
            self._write_new(Path(prepared.reservation_path) / "DAY_EXECUTION.json", _canonical_json(day_events) + b"\n")
            assert isinstance(self.drive_store, GoogleDriveReadbackStore) and self.pins is not None
            receipt = self.drive_store.create_once_and_verify(
                name=output_name,
                parent_id=self.pins.parent_id,
                mime_type=self.pins.evidence_mime_type,
                content=output_bytes,
                expected_readback_deadline=output_deadline,
                expected_created_not_after=output_deadline,
                expected_modified_not_after=output_deadline,
            )
            self._validate_created_receipt(
                receipt, name=output_name, raw=output_bytes,
                deadline=output_deadline, not_before=captured_at,
            )
            self.store.update_status(
                prepared.D, "OUTPUT_READBACK_PASS", output_sha256=receipt.sha256,
                receipt=receipt, at=self._now(),
            )
            return receipt
        except Exception as exc:
            self.store.update_status(
                prepared.D, "CALL_OR_SEAL_FAILED", error_code=type(exc).__name__, at=self._now()
            )
            raise
        finally:
            fcntl.flock(model_lock_fd, fcntl.LOCK_UN)
            os.close(model_lock_fd)

    def budget_counts(self) -> tuple[int, int, int]:
        """Return persisted (daily attempts, paired output rows, unique PB count)."""
        return self.store.totals() if self.store is not None else (0, 0, 0)

    def execution_counts(self) -> Mapping[str, int]:
        if self.store is None:
            return {
                "daily_reservations": 0,
                "paired_output_rows_reserved": 0,
                "unique_pb_reserved": 0,
                "model_api_predict_calls": 0,
                "fixture_callbacks": 0,
                "input_seal_intents": 0,
                "seal_missed": 0,
            }
        return self.store.execution_counts()


__all__ = [
    "AuthorizationBundle", "BINARY_FEATURE_INDICES", "BudgetExceeded", "CoordinatorError",
    "DailyPoolInput", "DISPOSITIONS", "DuplicateAttempt", "EARLIEST_K3", "EvidenceError",
    "ExposureIndex", "FEATURE_NAMES", "FIXED_READOUT", "FIXTURE_AUTHORIZATION_BYTES",
    "FIXTURE_AUTHORIZATION_SHA256", "FIXTURE_ID", "FixtureInvocation", "INPUT_DEADLINE",
    "LATEST_PB15", "MODEL_BATCH_LIMIT", "NUMERIC_FEATURE_INDICES", "NoGoError",
    "OUTPUT_DEADLINE", "PAIRED_OUTPUT_ROW_LIMIT", "PRE_STUDY_DEADLINE", "PoolRow",
    "PreparedDay", "REQUIRED_IDENTITY_KEYS", "ReadinessCoordinator", "RuntimePins",
    "STUDY_END", "STUDY_ID", "STUDY_START", "SourceProof", "SourceProofVerifier",
    "StateProof", "StateProofVerifier", "UNIQUE_PB_LIMIT", "canonical_matrix_and_keys",
    "compact_d", "compute_state_proof_sha256", "fixed_d_dates",
]
