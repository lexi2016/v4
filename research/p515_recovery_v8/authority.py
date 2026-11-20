"""Single service authority for atomic grant consumption and unit transactions.

The authority anchor and database live in the supervised server account. Workers
only see the Unix socket and a read-only client anchor. Copying a worker ledger
never creates a second authority or an offline execution path.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import sqlite3
import threading
from urllib.parse import quote
import uuid

from .validation import (
    BASELINE_COUNTS, OFFICIAL, RUN_A, SYNTHETIC, UNIT_REQUIREMENTS,
    Rejected, canonical, digest, identity_digest, now, object_digest, read_json,
    require, rows_digest, timestamp, verify_authorization, verify_outputs, verify_prepared,
)

MODES = ("CHECK_ONLY", "SYNTHETIC_EXECUTION", "AUTHORIZED_EXECUTION")
TERMINAL = {"COMMITTED", "FAILED_ERROR", "INTERRUPTED_UNKNOWN", "CORRUPTED", "BLOCKED"}
ACTIVE = {"CREATED", "AUTHORIZED", "RESERVED", "STARTED", "EXECUTING", "OUTPUT_STAGED", "OUTPUT_VERIFIED"}
FAULTS = {None, "after_start_crash", "second_row_identity", "missing_output", "corrupt_output",
          "wrong_sha", "wrong_model_identity", "missing_model_weights", "before_commit_crash",
          "after_commit_disconnect"}


def store_fingerprint(connection, authority_id):
    contents = {}
    for table, ordering in (("metadata", "key"), ("transactions", "transaction_id"),
                            ("events", "sequence"), ("starts", "transaction_id,stage"),
                            ("stub_calls", "sequence")):
        cursor = connection.execute("SELECT * FROM " + table + " ORDER BY " + ordering)
        columns = [entry[0] for entry in cursor.description]
        contents[table] = [dict(zip(columns, tuple(row))) for row in cursor]
    latest = contents["events"][-1] if contents["events"] else None
    return {"schema": "P515_V8_DURABLE_FENCE_V1", "authority_id": authority_id,
            "database_content_sha256": object_digest(contents),
            "event_sequence": latest["sequence"] if latest else 0,
            "event_head_sha256": latest["sha256"] if latest else "0" * 64}


def write_once(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        # fdopen owns the descriptor on all successful constructions.
        pass
    fsync_directory(path.parent)
    require(path.read_bytes() == raw, "WRITE_READBACK_MISMATCH")
    return {"bytes": len(raw), "sha256": digest(raw)}


def fsync_directory(path: Path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def initialize_authority(root: Path, prepared_path: Path, trust: dict, *,
                         domain: str = SYNTHETIC, test_fault: str | None = None) -> Path:
    """Explicit administrator install. Never called by worker RPC or normal CLI."""
    require(domain in (SYNTHETIC, OFFICIAL) and test_fault in FAULTS, "INSTALL_CONFIGURATION_INVALID")
    require(test_fault is None or domain == SYNTHETIC, "SYNTHETIC_FAULT_FORBIDDEN_IN_OFFICIAL")
    prepared_path = prepared_path.resolve()
    prepared, prepared_sha = verify_prepared(prepared_path, domain)
    require(bool(trust), "DEPLOYMENT_TRUST_ROOT_REQUIRED")
    for key_id, key in trust.items():
        require(bool(key_id) and key.get("domain") == domain and bool(key.get("issuer")) and
                bool(key.get("subject")) and len(bytes.fromhex(key.get("public_key_hex", ""))) == 32,
                "DEPLOYMENT_TRUST_ROOT_INVALID")
    if domain == OFFICIAL:
        # Official installation re-derives actual data and lineage. A worker's
        # prepared JSON, including an invented baseline, cannot install itself.
        from .official_inputs import prepare_official
        require(isinstance(prepared.get("official_config"), dict), "OFFICIAL_ADMIN_SOURCE_CONFIG_REQUIRED")
        checked = prepare_official(prepared["official_config"])
        require(checked == prepared, "OFFICIAL_PREPARATION_REDERIVATION_MISMATCH")
    root = root.parent.resolve() / root.name
    require(not root.exists(), "AUTHORITY_ALREADY_EXISTS_OR_UNTRUSTED_DIRECTORY")
    root.mkdir(mode=0o700, parents=False)
    database = root / "ledger.sqlite"
    authority_id = "authority-v8-" + uuid.uuid4().hex
    connection = sqlite3.connect(database)
    try:
        connection.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE transactions (
                transaction_id TEXT PRIMARY KEY, authorization_id TEXT NOT NULL UNIQUE,
                unit TEXT NOT NULL UNIQUE, state TEXT NOT NULL,
                grant_sha256 TEXT NOT NULL, lease_sha256 TEXT NOT NULL,
                requirements TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, expires_at TEXT NOT NULL, manifest TEXT
            );
            CREATE TABLE events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT,
                state TEXT NOT NULL, event TEXT NOT NULL, time TEXT NOT NULL,
                payload TEXT NOT NULL, previous_sha256 TEXT NOT NULL, sha256 TEXT NOT NULL
            );
            CREATE TABLE starts (
                transaction_id TEXT NOT NULL, stage TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(transaction_id, stage),
                FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id)
            );
            CREATE TABLE stub_calls (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT NOT NULL,
                kind TEXT NOT NULL, time TEXT NOT NULL
            );
        """)
        values = {
            "authority_id": authority_id, "run_a": RUN_A, "scope": domain,
            "prepared_sha256": prepared_sha, "baseline": prepared["baseline"],
            "trust_sha256": object_digest(trust), "store_uuid": uuid.uuid4().hex,
        }
        for key, value in values.items():
            connection.execute("INSERT INTO metadata VALUES (?,?)", (key, json.dumps(value, sort_keys=True)))
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    os.chmod(database, 0o600)
    database_stat, root_stat = database.stat(), root.stat()
    fence = root.parent / (root.name + ".durable-fence.json")
    connection = sqlite3.connect(database)
    try:
        initial_fence = store_fingerprint(connection, authority_id)
    finally:
        connection.close()
    write_once(fence, canonical(initial_fence))
    fence_stat = fence.stat()
    anchor = {
        "schema": "P515_V8_AUTHORITY_ANCHOR_V1", "authority_id": authority_id,
        "execution_identity_sha256": RUN_A, "scope": domain, "root": str(root),
        "database": str(database), "database_inode": database_stat.st_ino, "database_device": database_stat.st_dev,
        "root_inode": root_stat.st_ino, "root_device": root_stat.st_dev,
        "socket": str(root / "authority.sock"), "server_uid": os.getuid(), "store_uuid": values["store_uuid"],
        "prepared_path": str(prepared_path), "prepared_sha256": prepared_sha,
        "fence": str(fence), "fence_inode": fence_stat.st_ino, "fence_device": fence_stat.st_dev,
        "trust": trust, "trust_sha256": object_digest(trust), "test_fault": test_fault,
    }
    write_once(root / "anchor.json", canonical(anchor))
    write_once(root / "authority.lock", b"")
    fsync_directory(root)
    return root / "anchor.json"


class Authority:
    """Server-side application. Never accepts unverified input/factory contexts."""

    def __init__(self, anchor_path: Path):
        require(anchor_path.is_file() and not anchor_path.is_symlink(), "AUTHORITY_ANCHOR_UNAVAILABLE")
        self.anchor_path = anchor_path.resolve()
        self.anchor = read_json(self.anchor_path)
        self.root = Path(self.anchor["root"])
        self.database = Path(self.anchor["database"])
        self._audit_lock = threading.Lock()
        self._verify_mount()
        self._lock_fd = os.open(self.root / "authority.lock", os.O_RDWR)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self._lock_fd)
            raise Rejected("AUTHORITY_INSTANCE_ALREADY_RUNNING") from exc
        try:
            with self.db() as connection:
                values = {r["key"]: json.loads(r["value"]) for r in connection.execute("SELECT * FROM metadata")}
                for key in ("authority_id", "prepared_sha256", "store_uuid", "scope", "trust_sha256"):
                    require(values[key] == self.anchor[key], "AUTHORITY_STORE_IDENTITY_MISMATCH")
                require(values["run_a"] == RUN_A and self.anchor["execution_identity_sha256"] == RUN_A,
                        "RUN_A_IDENTITY_REQUIRED")
                require(values["baseline"]["counts"] == BASELINE_COUNTS, "CANONICAL_BASELINE_MISMATCH")
                self.baseline = values["baseline"]
                self._verify_chain(connection)
                pending = list(connection.execute("SELECT transaction_id FROM transactions WHERE state NOT IN (?,?,?,?,?)",
                                                  tuple(sorted(TERMINAL))))
                for row in pending:
                    self._transition(connection, row["transaction_id"], "INTERRUPTED_UNKNOWN", "SERVER_RESTART_UNKNOWN")
        except BaseException:
            self.close()
            raise

    def _verify_mount(self):
        require(self.root.is_dir() and not self.root.is_symlink() and
                self.database.is_file() and not self.database.is_symlink(), "AUTHORITY_STORAGE_MISSING")
        require(self.anchor_path.parent == self.root and self.root.resolve() == self.root, "AUTHORITY_ANCHOR_RELOCATED")
        ds, rs = self.database.stat(), self.root.stat()
        require((ds.st_ino, ds.st_dev) == (self.anchor["database_inode"], self.anchor["database_device"]) and
                (rs.st_ino, rs.st_dev) == (self.anchor["root_inode"], self.anchor["root_device"]),
                "PHYSICAL_STORE_COPY_OR_REPLACEMENT_REJECTED")
        require(object_digest(self.anchor["trust"]) == self.anchor["trust_sha256"], "TRUST_ANCHOR_CHANGED")
        fence = Path(self.anchor["fence"])
        require(fence.is_file() and not fence.is_symlink() and
                (fence.stat().st_ino, fence.stat().st_dev) ==
                (self.anchor["fence_inode"], self.anchor["fence_device"]), "DURABLE_FENCE_MISSING_OR_REPLACED")
        require(self.anchor.get("test_fault") is None or self.anchor["scope"] == SYNTHETIC,
                "OFFICIAL_TEST_SWITCH_REJECTED")

    @contextmanager
    def db(self):
        self._verify_mount()
        connection = sqlite3.connect("file:" + quote(str(self.database)) + "?mode=rw", uri=True, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE")
        try:
            before = store_fingerprint(connection, self.anchor["authority_id"])
            require(read_json(Path(self.anchor["fence"])) == before, "LEDGER_ROLLBACK_OR_UNKNOWN_COMMIT_FENCED")
            yield connection
            after = store_fingerprint(connection, self.anchor["authority_id"])
            if after != before:
                # The independently retained fence is advanced before the SQL
                # commit. A crash between these durable operations blocks
                # recovery instead of resurrecting already consumed capacity.
                fence = Path(self.anchor["fence"])
                fd = os.open(fence, os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "wb") as handle:
                    handle.write(canonical(after))
                    handle.flush()
                    os.fsync(handle.fileno())
                fsync_directory(fence.parent)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close(self):
        if getattr(self, "_lock_fd", None) is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None

    def _verify_chain(self, connection):
        previous = "0" * 64
        for row in connection.execute("SELECT * FROM events ORDER BY sequence"):
            data = {key: row[key] for key in ("transaction_id", "state", "event", "time")}
            data["payload"] = json.loads(row["payload"])
            require(row["previous_sha256"] == previous and
                    row["sha256"] == digest(previous.encode() + canonical(data)), "LEDGER_EVENT_CHAIN_CORRUPTED")
            previous = row["sha256"]

    def _event(self, connection, transaction_id, state, event, payload=None):
        latest = connection.execute("SELECT sha256 FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
        previous = latest["sha256"] if latest else "0" * 64
        data = {"transaction_id": transaction_id, "state": state, "event": event,
                "time": now().isoformat(), "payload": payload or {}}
        checksum = digest(previous.encode() + canonical(data))
        connection.execute("INSERT INTO events(transaction_id,state,event,time,payload,previous_sha256,sha256) VALUES (?,?,?,?,?,?,?)",
                           (transaction_id, state, event, data["time"], json.dumps(data["payload"], sort_keys=True),
                            previous, checksum))

    def _transition(self, connection, transaction_id, state, event, payload=None):
        require(state in ACTIVE | TERMINAL, "UNKNOWN_TRANSACTION_STATE")
        cursor = connection.execute("UPDATE transactions SET state=?,updated_at=? WHERE transaction_id=?",
                                    (state, now().isoformat(), transaction_id))
        require(cursor.rowcount == 1, "TRANSACTION_UNKNOWN")
        self._event(connection, transaction_id, state, event, payload)

    def _prepared(self):
        prepared, checksum = verify_prepared(Path(self.anchor["prepared_path"]), self.anchor["scope"])
        require(checksum == self.anchor["prepared_sha256"], "PREPARED_SNAPSHOT_CHANGED")
        require(prepared["baseline"] == self.baseline, "ORIGINAL_A_BASELINE_CHANGED")
        return prepared

    def _counts(self, connection):
        counts = {k: self.baseline["counts"][k] for k in ("preprocessing_fit", "model_fit", "model_api")}
        for row in connection.execute("SELECT requirements FROM transactions"):
            for key, value in json.loads(row["requirements"]).items():
                counts[key] += value
        return counts

    def check(self):
        prepared = self._prepared()
        with self.db() as connection:
            self._verify_chain(connection)
            counts = self._counts(connection)
        return {"state": "CHECK_ONLY", "authority_id": self.anchor["authority_id"],
                "execution_identity_sha256": RUN_A, "scope": self.anchor["scope"], "counts": counts,
                "prepared_sha256": self.anchor["prepared_sha256"],
                "identity_sha256": identity_digest(prepared), "rows_sha256": rows_digest(prepared),
                "trace": ["INPUTS_VERIFIED", "FULL_FOLDS_VERIFIED", "ORIGINAL_RUN_A_VERIFIED", "AUTHORITY_VERIFIED"]}

    def reserve(self, *, unit: str, envelope: dict, prelaunch_b64: str, mode: str):
        require(mode in MODES and mode != "CHECK_ONLY", "EXECUTION_MODE_REQUIRED")
        prepared = self._prepared()
        expected_scope = SYNTHETIC if mode == "SYNTHETIC_EXECUTION" else OFFICIAL
        require(self.anchor["scope"] == expected_scope, "MODE_AUTHORITY_DOMAIN_MISMATCH")
        try:
            import base64
            package = base64.b64decode(prelaunch_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise Rejected("PRELAUNCH_BASE64_INVALID") from exc
        grant = verify_authorization(envelope, self.anchor["trust"], prepared, self.anchor["prepared_sha256"],
                                     self.anchor["authority_id"], unit, package, self.anchor["scope"])
        # Both modes reach the complete validation boundary. The concrete future
        # backend is fenced at every real API and cannot be unlocked by a grant.
        if mode == "AUTHORIZED_EXECUTION":
            from .execution import RealExecutionHardGuard
            RealExecutionHardGuard.assert_zero_fit_release()
        require(unit in UNIT_REQUIREMENTS, "UNKNOWN_UNIT")
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            sealed = json.loads(archive.read("manifest.json"))
        effective_expiry = min(timestamp(grant["expires_at"]), timestamp(sealed["expires_at"])).isoformat()
        requirements = UNIT_REQUIREMENTS[unit]
        txid = uuid.uuid4().hex
        lease = secrets.token_hex(32)
        with self.db() as connection:
            self._verify_chain(connection)
            existing = connection.execute("SELECT transaction_id,state FROM transactions WHERE authorization_id=? OR unit=?",
                                          (grant["authorization_id"], unit)).fetchone()
            require(existing is None, "AUTHORIZATION_OR_UNIT_ALREADY_CONSUMED")
            if unit == "FINAL_DEV":
                self._verify_final_prerequisites(connection, prepared)
            counts = self._counts(connection)
            require(all(counts[k] + v <= grant["budget_caps"][k] for k, v in requirements.items()),
                    "WHOLE_UNIT_BUDGET_EXCEEDED_ZERO_CALLS")
            when = now().isoformat()
            connection.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (txid, grant["authorization_id"], unit, "CREATED", object_digest(envelope),
                                digest(lease.encode()), json.dumps(requirements, sort_keys=True), when, when,
                                effective_expiry, None))
            self._event(connection, txid, "CREATED", "TRANSACTION_CREATED", {"unit": unit})
            self._transition(connection, txid, "AUTHORIZED", "SIGNATURE_AND_PRELAUNCH_VERIFIED",
                             {"authorization_id": grant["authorization_id"], "prelaunch_sha256": digest(package)})
            self._transition(connection, txid, "RESERVED", "ENTIRE_UNIT_BUDGET_RESERVED",
                             {"before": counts, "requirements": requirements, "caps": grant["budget_caps"]})
        return {"authority_id": self.anchor["authority_id"], "transaction_id": txid,
                "authorization_id": grant["authorization_id"], "state": "RESERVED", "lease_token": lease,
                "trace": ["INPUTS_VERIFIED", "ORIGINAL_RUN_A_VERIFIED", "AUTHORITY_VERIFIED",
                          "AUTH_SIGNATURE_VERIFIED", "PRELAUNCH_CONTENT_VERIFIED", "WHOLE_BUDGET_RESERVED"]}

    def _verify_final_prerequisites(self, connection, prepared):
        historical = self.baseline.get("historical_units", {})
        for unit, rows in (("F2", 9503), ("F3", 5250)):
            item = historical.get(unit, {})
            require(item.get("state") == "COMMITTED" and item.get("identity") == RUN_A and
                    item.get("rows") == rows and bool(item.get("sha256")), "FINAL_DEV_HISTORICAL_PREREQUISITE_MISSING")
        previous = connection.execute("SELECT * FROM transactions WHERE unit='F1_RETRY'").fetchone()
        require(previous is not None and previous["state"] == "COMMITTED", "FINAL_DEV_F1_NOT_COMMITTED")
        self._verify_committed(previous, prepared)

    def _verify_committed(self, transaction, prepared):
        expected = json.loads(transaction["manifest"])
        directory = self.root / "outputs" / transaction["transaction_id"]
        found = verify_outputs(directory, prepared, transaction["unit"], transaction["transaction_id"],
                               self.anchor["authority_id"])
        require(found == expected, "COMMITTED_OUTPUT_CORRUPTED")
        manifest_path = self.root / "commits" / (transaction["transaction_id"] + ".json")
        require(manifest_path.is_file() and manifest_path.read_bytes() == canonical(expected),
                "COMMIT_MANIFEST_CORRUPTED")
        return expected

    def _lease_transaction(self, connection, transaction_id, lease_token):
        require(isinstance(transaction_id, str) and isinstance(lease_token, str), "TRANSACTION_LEASE_REQUIRED")
        row = connection.execute("SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
        require(row is not None and secrets.compare_digest(row["lease_sha256"], digest(lease_token.encode())),
                "INVALID_TRANSACTION_LEASE")
        return row

    def execute(self, *, transaction_id: str, lease_token: str):
        prepared = self._prepared()
        expired = False
        with self.db() as connection:
            transaction = self._lease_transaction(connection, transaction_id, lease_token)
            if transaction["state"] == "COMMITTED":
                manifest = self._verify_committed(transaction, prepared)
                return {"authority_id": self.anchor["authority_id"], "transaction_id": transaction_id,
                        "state": "COMMITTED", "reused_readonly": True, "manifest": manifest}
            require(transaction["state"] == "RESERVED", "TRANSACTION_NONRETRYABLE_STATE")
            if now() >= timestamp(transaction["expires_at"]):
                self._transition(connection, transaction_id, "BLOCKED", "AUTH_OR_PRELAUNCH_EXPIRED_BEFORE_START")
                expired = True
            else:
                if self.anchor["scope"] == OFFICIAL:
                    from .execution import RealExecutionHardGuard
                    RealExecutionHardGuard.assert_zero_fit_release()
                if transaction["unit"] == "FINAL_DEV":
                    self._verify_final_prerequisites(connection, prepared)
                self._transition(connection, transaction_id, "STARTED", "UNIT_START")
        require(not expired, "AUTH_OR_PRELAUNCH_EXPIRED_BEFORE_START")
        try:
            from .execution import run_staged_unit
            return run_staged_unit(self, transaction_id)
        except Exception as exc:
            with self.db() as connection:
                current = connection.execute("SELECT state FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
                if current["state"] != "COMMITTED":
                    code = "CORRUPTED" if isinstance(exc, Rejected) and "OUTPUT" in str(exc) else "FAILED_ERROR"
                    self._transition(connection, transaction_id, code, "UNIT_FAILED_NO_AUTO_RETRY",
                                     {"error": str(exc), "error_type": type(exc).__name__})
            raise

    def start_stage(self, transaction_id: str, stage: str):
        with self.db() as connection:
            tx = connection.execute("SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
            require(tx is not None and tx["state"] in ("STARTED", "EXECUTING"), "STAGE_NOT_ADMITTED")
            require(now() < timestamp(tx["expires_at"]), "AUTH_OR_PRELAUNCH_EXPIRED_BEFORE_STAGE_START")
            require(stage in ("preprocessing_fit", "model_fit", "model_api") and
                    UNIT_REQUIREMENTS[tx["unit"]][stage] == 1, "STAGE_FORBIDDEN")
            previous = {r["stage"] for r in connection.execute("SELECT stage FROM starts WHERE transaction_id=?", (transaction_id,))}
            require(stage not in previous, "STAGE_ALREADY_STARTED_NO_RETRY")
            expected = {"preprocessing_fit": set(), "model_fit": {"preprocessing_fit"},
                        "model_api": {"preprocessing_fit", "model_fit"}}[stage]
            require(previous == expected, "STAGE_ORDER_INVALID")
            connection.execute("INSERT INTO starts VALUES (?,?,?)", (transaction_id, stage, now().isoformat()))
            self._transition(connection, transaction_id, "EXECUTING", "SYNTHETIC_STAGE_START",
                             {"stage": stage, "scope": SYNTHETIC})
        if self.anchor["test_fault"] == "after_start_crash":
            os._exit(71)

    def record_stub(self, transaction_id, kind):
        with self.db() as connection:
            connection.execute("INSERT INTO stub_calls(transaction_id,kind,time) VALUES (?,?,?)",
                               (transaction_id, kind, now().isoformat()))
            self._event(connection, transaction_id, "EXECUTING", "STUB_RETURN", {"kind": kind, "scope": SYNTHETIC})

    def stage_output(self, transaction_id):
        with self.db() as connection:
            self._transition(connection, transaction_id, "OUTPUT_STAGED", "OUTPUT_FILES_FSYNCED")

    def commit_output(self, transaction_id, expected_files):
        prepared = self._prepared()
        with self.db() as connection:
            transaction = connection.execute("SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
            require(transaction is not None and transaction["state"] == "OUTPUT_STAGED", "OUTPUT_STATE_NOT_STAGED")
            unit = transaction["unit"]
        directory = self.root / "outputs" / transaction_id
        manifest = verify_outputs(directory, prepared, unit, transaction_id, self.anchor["authority_id"])
        require(manifest["files"] == expected_files, "OUTPUT_RECORDED_SHA_OR_SIZE_MISMATCH")
        with self.db() as connection:
            tx = connection.execute("SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
            require(tx is not None and tx["state"] == "OUTPUT_STAGED", "OUTPUT_STATE_NOT_STAGED")
            require({r["stage"] for r in connection.execute("SELECT stage FROM starts WHERE transaction_id=?", (transaction_id,))} ==
                    {k for k, v in UNIT_REQUIREMENTS[unit].items() if v}, "STAGE_RECEIPTS_INCOMPLETE")
            self._transition(connection, transaction_id, "OUTPUT_VERIFIED", "FULL_OUTPUT_CONTENT_VERIFIED",
                             {"manifest_sha256": object_digest(manifest)})
        write_once(self.root / "commits" / (transaction_id + ".json"), canonical(manifest))
        if self.anchor["test_fault"] == "before_commit_crash":
            os._exit(72)
        with self.db() as connection:
            tx = connection.execute("SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
            require(tx["state"] == "OUTPUT_VERIFIED", "TRANSACTION_NO_LONGER_COMMITTABLE")
            # Recheck after the persisted file/manifest window and before the one
            # transaction that publishes both manifest identity and COMMITTED.
            require(verify_outputs(directory, prepared, unit, transaction_id, self.anchor["authority_id"]) == manifest,
                    "OUTPUT_CHANGED_BEFORE_COMMIT")
            connection.execute("UPDATE transactions SET manifest=? WHERE transaction_id=?",
                               (json.dumps(manifest, sort_keys=True), transaction_id))
            self._transition(connection, transaction_id, "COMMITTED", "COMMIT_MANIFEST_AND_COMPLETION_ATOMIC",
                             {"manifest_sha256": object_digest(manifest)})
        return {"authority_id": self.anchor["authority_id"], "transaction_id": transaction_id,
                "state": "COMMITTED", "manifest": manifest, "reused_readonly": False}

    def query(self, *, transaction_id=None, authorization_id=None):
        require(bool(transaction_id) != bool(authorization_id), "EXACTLY_ONE_QUERY_ID_REQUIRED")
        prepared = self._prepared()
        with self.db() as connection:
            self._verify_chain(connection)
            key, value = ("transaction_id", transaction_id) if transaction_id else ("authorization_id", authorization_id)
            transaction = connection.execute("SELECT * FROM transactions WHERE " + key + "=?", (value,)).fetchone()
            require(transaction is not None, "TRANSACTION_UNKNOWN")
            manifest = None
            if transaction["state"] == "COMMITTED":
                try:
                    manifest = self._verify_committed(transaction, prepared)
                except Rejected as exc:
                    self._transition(connection, transaction["transaction_id"], "CORRUPTED",
                                     "COMMITTED_OUTPUT_LATER_CORRUPTED", {"error": str(exc)})
                    return {"authority_id": self.anchor["authority_id"], "transaction_id": transaction["transaction_id"],
                            "state": "CORRUPTED", "reason": str(exc)}
            return {"authority_id": self.anchor["authority_id"], "transaction_id": transaction["transaction_id"],
                    "authorization_id": transaction["authorization_id"], "unit": transaction["unit"],
                    "state": transaction["state"], "manifest": manifest}

    def status(self):
        with self.db() as connection:
            self._verify_chain(connection)
            events = [dict(r) for r in connection.execute("SELECT * FROM events ORDER BY sequence")]
            transactions = [{k: r[k] for k in ("transaction_id", "authorization_id", "unit", "state", "requirements")}
                            for r in connection.execute("SELECT * FROM transactions ORDER BY created_at")]
            calls = {r["kind"]: r["n"] for r in connection.execute("SELECT kind,COUNT(*) AS n FROM stub_calls GROUP BY kind")}
            starts = [dict(r) for r in connection.execute("SELECT * FROM starts ORDER BY created_at")]
            counts = self._counts(connection)
        return {"authority_id": self.anchor["authority_id"], "scope": self.anchor["scope"],
                "execution_identity_sha256": RUN_A, "counts": counts, "transactions": transactions,
                "events": events, "starts": starts, "stub_calls": calls,
                "durable_fence": read_json(Path(self.anchor["fence"])),
                "real_counts": {"model_fit": 0, "preprocessing_fit": 0, "model_api": 0,
                                "new_probability": 0, "predict": 0, "deserialization": 0, "formal_start": 0}}

    def request(self, request):
        require(isinstance(request, dict) and "op" in request, "RPC_OBJECT_REQUIRED")
        operation = request["op"]
        allowed = {"check": self.check, "reserve": self.reserve, "execute": self.execute,
                   "query": self.query, "status": self.status}
        require(operation in allowed, "REMOTE_MUTATION_FORBIDDEN")
        return allowed[operation](**{k: v for k, v in request.items() if k != "op"})

    def audit_request(self, request, response):
        def redact(value):
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()
                        if key not in ("lease_token", "signature", "private_key", "secret")}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value
        with self._audit_lock:
            record = {"time": now().isoformat(), "scope": self.anchor["scope"], "pid": os.getpid(),
                      "op": request.get("op") if isinstance(request, dict) else None,
                      "authorization_id": (request.get("envelope") or {}).get("payload", {}).get("authorization_id"),
                      "response": redact(response)}
            with (self.root / "requests.jsonl").open("a") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        request = {}
        try:
            raw = self.rfile.readline(100 * 1024 * 1024 + 1)
            require(raw.endswith(b"\n") and len(raw) <= 100 * 1024 * 1024, "RPC_REQUEST_TOO_LARGE_OR_INCOMPLETE")
            request = json.loads(raw)
            result = self.server.authority.request(request)
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        self.server.authority.audit_request(request, response.get("result", response))
        if (self.server.authority.anchor["test_fault"] == "after_commit_disconnect" and response.get("ok") and
                request.get("op") == "execute" and response["result"]["state"] == "COMMITTED"):
            return
        try:
            self.wfile.write(canonical(response) + b"\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # Result already lives in authority state. Transport errors never
            # restart or repeat an operation.
            return


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    block_on_close = True


def serve(anchor_path: Path):
    authority = Authority(anchor_path)
    endpoint = Path(authority.anchor["socket"])
    require(not endpoint.is_symlink(), "SOCKET_SYMLINK_REJECTED")
    if endpoint.exists():
        require(endpoint.is_socket(), "SOCKET_PATH_NOT_SOCKET")
        endpoint.unlink()
    try:
        with _Server(str(endpoint), _Handler) as server:
            server.authority = authority
            os.chmod(endpoint, 0o600)
            server.serve_forever(poll_interval=0.1)
    finally:
        authority.close()
        if endpoint.exists() and endpoint.is_socket():
            endpoint.unlink()


class AuthorityClient:
    """RPC-only client. It has no local budget or model execution fallback."""

    def __init__(self, anchor_path: Path, timeout: float = 30):
        self.anchor = read_json(anchor_path)
        self.timeout = timeout
        require(self.anchor.get("schema") == "P515_V8_AUTHORITY_ANCHOR_V1" and
                self.anchor.get("execution_identity_sha256") == RUN_A, "CLIENT_ANCHOR_INVALID")

    def request(self, op: str, **kwargs):
        endpoint = Path(self.anchor["socket"])
        require(endpoint.exists() and endpoint.is_socket() and not endpoint.is_symlink() and
                endpoint.stat().st_uid == self.anchor["server_uid"], "AUTHORITY_UNAVAILABLE_NO_OFFLINE_EXECUTION")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout)
                connection.connect(str(endpoint))
                connection.sendall(canonical({"op": op, **kwargs}) + b"\n")
                reader = connection.makefile("rb")
                response = reader.readline(100 * 1024 * 1024 + 1)
                require(response.endswith(b"\n"), "AUTHORITY_RESULT_UNKNOWN_QUERY_ONLY_NO_RETRY")
                envelope = json.loads(response)
        except (ConnectionError, OSError, json.JSONDecodeError) as exc:
            raise Rejected("AUTHORITY_RESULT_UNKNOWN_QUERY_ONLY_NO_RETRY") from exc
        require(envelope.get("ok") is True, envelope.get("error", "AUTHORITY_REJECTED"))
        result = envelope["result"]
        require(result.get("authority_id") == self.anchor["authority_id"], "AUTHORITY_RESPONSE_IDENTITY_MISMATCH")
        return result
