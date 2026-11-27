"""Durable state for one Dot writer and one local board view."""

from contextlib import contextmanager
from datetime import date
from hashlib import sha256
from html import escape
from pathlib import Path
import fcntl
import json
import os
import re
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
    label = "旧数据 · STALE" if stale else "已核验数据"
    banner = (
        f'<aside id="route2-state" role="status" style="position:sticky;top:0;z-index:10000;'
        f'padding:16px 24px;background:{style};color:white;font:700 17px system-ui">'
        f'{label}　数据日期 {escape(data_date)}　尝试日期 {escape(attempted)}'
        f'　{escape(reason)}</aside>'
    ).encode()
    return raw[:index] + banner + raw[index:]


class Board:
    """One atomic pointer publishes two already durable, SHA-pinned artifacts."""

    def __init__(self, root, *, writable=True, bind_pointer=False):
        self.root = root
        self.pointer = root / "CURRENT.json"
        self.owner = (root / "DOT_OWNER.json") if bind_pointer else None
        if writable:
            mkdir(root / "boards")

    def validated_raw(self, good):
        day = good["data_date"]
        require(re.fullmatch(r"[0-9]{8}", day) and date.fromisoformat(day), "BOARD_DATA_DATE")
        raw = read_pin(self.root, good["raw"])
        if good["origin"].startswith("PINNED_ORIGINAL_DRIVE:"):
            title = f"<h1>{date.fromisoformat(day).isoformat()} 综合看板与 PAR 面板</h1>".encode()
            require(not good.get("proof"), "SEED_BOARD_PROOF")
        else:
            require(good["origin"] == "ORIGINAL_V5_W11C_EVENING" and set(good["proof"]) == {"evening_input"},
                    "EVENING_BOARD_PROOF")
            proof = json.loads(read_pin(self.root, good["proof"]["evening_input"]))
            require(proof["business_date"] == day and proof["slot"] == "18:30"
                    and proof["dot_required_complete"] is True
                    and not proof["dot_missing_required"]
                    and all(proof.get(key) is flag for key, flag in FLAGS.items()), "EVENING_BOARD_DATE_OR_PROOF")
            title = f"<h1>V5 综合静态看板 · {day}</h1>".encode()
        require(raw.count(title) == 1, "BOARD_RAW_DATE")
        return raw

    def bound_view(self, good, attempted, stale, reason):
        require(re.fullmatch(r"[0-9]{8}", attempted) and date.fromisoformat(attempted)
                and attempted >= good["data_date"] and type(stale) is bool and (stale or attempted == good["data_date"])
                and isinstance(reason, str) and bool(reason.strip()), "BOARD_ATTEMPT_STATUS")
        return annotate(self.validated_raw(good), good["data_date"], attempted, stale, reason)

    def current(self):
        require(self.pointer.is_file() and self.pointer.resolve() == self.pointer, "BOARD_POINTER_PATH")
        payload = self.pointer.read_bytes()
        if self.owner is not None:
            owner = json.loads(self.owner.read_bytes())
            require(digest(payload) == owner["current_sha256"], "DURABLE_BOARD_POINTER_RESTORE_REQUIRED")
        value = json.loads(payload)
        good = value["last_success"]
        require(value["data_date"] == good["data_date"]
                and all(value.get(key) is flag for key, flag in FLAGS.items()), "BOARD_POINTER_DATE_OR_FLAGS")
        expected = self.bound_view(good, value["attempted_date"], value["stale"], value["reason"])
        require(read_pin(self.root, value["view"]) == expected, "BOARD_POINTER_VIEW")
        return value

    def commit(self, good, attempted, stale, reason):
        shown = self.bound_view(good, attempted, stale, reason)
        display = artifact(self.root, f"boards/view-{digest(shown)}.html", shown)
        current = dict(last_success=good, data_date=good["data_date"], attempted_date=attempted,
                       view=display, stale=stale, reason=reason, **FLAGS)
        payload = json_bytes(current)
        if self.owner is None:
            atomic(self.pointer, payload)
        else:
            owner = json.loads(self.owner.read_bytes())
            require(digest(self.pointer.read_bytes()) == owner["current_sha256"], "DURABLE_BOARD_POINTER_RESTORE_REQUIRED")
            atomic(self.pointer, payload)
            atomic(self.owner, json_bytes({**owner, "current_sha256": digest(payload)}))
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
                           data_date, False, "同日原版快照")


