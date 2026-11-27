"""Durable state for one Mac writer and one local board view."""

from contextlib import closing, contextmanager
from hashlib import sha256
from html import escape
from pathlib import Path
import fcntl
import json
import os
import re
import sqlite3
import tempfile


FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False, "orders_sent": False,
         "buy_gate_updated": False, "natural_verified": False}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(raw):
    return sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
            + "\n").encode()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def mkdir(path):
    path.mkdir(exist_ok=True, mode=0o700)
    require(path.resolve() == path and path.is_dir(), "OUTPUT_DIRECTORY")
    sync_dir(path.parent)


def atomic(path, raw):
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def writer_lock(root):
    fd = os.open(root / "writer.lock", os.O_NOFOLLOW | os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("ALREADY_CLAIMED_LOCAL") from None
        yield
    finally:
        os.close(fd)


def read_pin(root, ref):
    path = root / ref["path"]
    require(path.resolve(strict=True) == path and path.is_relative_to(root)
            and path.is_file() and path.stat().st_size == ref["bytes"], "ARTIFACT_PATH_OR_SIZE")
    raw = path.read_bytes()
    require(len(raw) == ref["bytes"] and digest(raw) == ref["sha256"], "ARTIFACT_PIN_MISMATCH")
    return raw


def artifact(root, path, raw):
    destination = root / path
    require(destination.resolve() == destination and destination.is_relative_to(root), "ARTIFACT_PATH")
    if destination.exists():
        require(destination.read_bytes() == raw, "IMMUTABLE_CONFLICT")
    else:
        atomic(destination, raw)
    return {"path": str(path), "bytes": len(raw), "sha256": digest(raw)}


def annotate(raw, data_date, attempted, stale, reason):
    hits = list(re.finditer(rb"<body(?:\s[^>]*|)>", raw, flags=re.IGNORECASE))
    if not hits:  # The W11C renderer relies on the implicit HTML body.
        hits = list(re.finditer(rb"<main>", raw, flags=re.IGNORECASE))
    require(len(hits) == 1, "BOARD_BODY_IDENTITY")
    index = hits[0].end()
    style = "#7f1d1d" if stale else "#14354e"
    label = "旧数据 · STALE" if stale else "本机回放"
    banner = (
        f'<aside id="route2-state" role="status" style="position:sticky;top:0;z-index:10000;'
        f'padding:16px 24px;background:{style};color:white;font:700 17px system-ui">'
        f'{label}　数据日期 {escape(data_date)}　尝试日期 {escape(attempted)}'
        f'　{escape(reason)}</aside>'
    ).encode()
    return raw[:index] + banner + raw[index:]


class Board:
    """One atomic pointer publishes two already durable, SHA-pinned artifacts."""

    def __init__(self, root, *, writable=True):
        self.root = root
        self.pointer = root / "CURRENT.json"
        if writable:
            mkdir(root / "boards")

    def current(self):
        value = json.loads(self.pointer.read_bytes())
        read_pin(self.root, value["last_success"]["raw"])
        for ref in value["last_success"].get("proof", {}).values():
            read_pin(self.root, ref)
        read_pin(self.root, value["view"])
        return value

    def commit(self, good, attempted, stale, reason):
        raw = read_pin(self.root, good["raw"])
        for ref in good.get("proof", {}).values():
            read_pin(self.root, ref)
        shown = annotate(raw, good["data_date"], attempted, stale, reason)
        display = artifact(self.root, f"boards/view-{digest(shown)}.html", shown)
        current = dict(last_success=good, data_date=good["data_date"], attempted_date=attempted,
                       view=display, stale=stale, reason=reason, **FLAGS)
        atomic(self.pointer, json_bytes(current))
        return current

    def seed(self, data_date, pin, origin, bootstrap):
        ref = {"path": f"boards/original-{pin['sha256']}.html",
               "bytes": pin["bytes"], "sha256": pin["sha256"]}
        stored = self.root / ref["path"]
        if self.pointer.exists() or stored.exists() or stored.is_symlink():
            require(stored.exists(), "PRESERVED_ORIGINAL_MISSING")
            read_pin(self.root, ref)
        else:
            raw = bootstrap()
            require(len(raw) == ref["bytes"] and digest(raw) == ref["sha256"], "ORIGINAL_BOARD_PIN")
            artifact(self.root, ref["path"], raw)
        original = dict(data_date=data_date, raw=ref, origin=origin)
        if not self.pointer.exists():
            self.commit(original, data_date, False, "原看板备份")
        return original

    def fail(self, attempted, reason):
        return self.commit(self.current()["last_success"], attempted, True, reason)

    def publish(self, data_date, raw_ref, origin, proof):
        last = self.current()
        require(data_date >= last["data_date"], "BOARD_STALE_DATE_REGRESSION")
        return self.commit(dict(data_date=data_date, raw=raw_ref, origin=origin, proof=proof),
                           data_date, False, "同日原版快照 · 未发布到 Drive")


class UploadLedger:
    """Record an ambiguous attempt durably before crossing an injected request boundary."""

    def __init__(self, root):
        self.path = root / "upload-ledger.sqlite3"
        require(not self.path.is_symlink(), "UPLOAD_LEDGER_PATH")

    def _open(self):
        db = sqlite3.connect(self.path, isolation_level="IMMEDIATE")
        try:
            require(db.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",),
                    "UPLOAD_LEDGER_JOURNAL_MODE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA fullfsync=ON")
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                target TEXT NOT NULL, day TEXT NOT NULL, sha256 TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('UNKNOWN_UPLOAD','ACKNOWLEDGED')),
                readback TEXT,
                PRIMARY KEY (target, day, sha256)
            )""")
            sync_dir(self.path.parent)
            return db
        except BaseException:
            db.close()
            raise

    def attempt(self, target, day, payload, request):
        sha = digest(payload)
        require(isinstance(target, str) and bool(target) and re.fullmatch(r"[0-9]{8}", day),
                "UPLOAD_IDENTITY")
        with closing(self._open()) as db:
            db.execute("BEGIN IMMEDIATE")
            entries = db.execute("SELECT sha256, state FROM attempts WHERE target=? AND day=?",
                                 (target, day)).fetchall()
            if entries:
                db.rollback()
                if any(state == "UNKNOWN_UPLOAD" for _, state in entries):
                    return "UNKNOWN_UPLOAD"
                return ("ALREADY_ACKNOWLEDGED" if (sha, "ACKNOWLEDGED") in entries
                        else "DIFFERENT_PAYLOAD_ALREADY_ACKNOWLEDGED")
            with db:
                db.execute("INSERT INTO attempts VALUES (?, ?, ?, 'UNKNOWN_UPLOAD', NULL)",
                           (target, day, sha))
            sync_dir(self.path.parent)
            try:
                ack = request(target, day, sha, payload)
            except Exception:
                return "UNKNOWN_UPLOAD"
            if (not isinstance(ack, dict) or (ack.get("target"), ack.get("date"), ack.get("sha256"))
                    != (target, day, sha) or not isinstance(ack.get("id"), str) or not ack["id"]):
                return "UNKNOWN_UPLOAD"
            with db:
                db.execute("UPDATE attempts SET state='ACKNOWLEDGED', readback=? "
                           "WHERE target=? AND day=? AND sha256=? AND state='UNKNOWN_UPLOAD'",
                           (ack["id"], target, day, sha))
            return "ACKNOWLEDGED"
