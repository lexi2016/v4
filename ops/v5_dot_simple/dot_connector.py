"""Dot connector evidence and the durable, exact-name publication guard."""
from datetime import datetime, timedelta, timezone
from hashlib import file_digest
from pathlib import Path
from uuid import uuid4
import json
import re

from dot_runtime import CONFIG, parse_day
from dot_state import FLAGS, atomic, digest, json_bytes, mkdir, read_pin, require

PARENT = CONFIG["parent"]
ROLES = {
    "a-top200": {"G4.zip", "SOURCE.json", "TOP200.json"},
    "daily-update": {"G4.zip", "GBBQ.zip", "SOURCE.json", "PAR_LEDGER.json", "FAILED_CLEAN.json",
                     "SUMMARY.json", "SAMPLE109.json", *(f"PAR_STATE_{i:02d}.zip" for i in range(1, 9))},
    "evening-prepare": {"INPUT.json", "BOARD.html"},
}
STATUSES = {"a-top200": "COMPUTED", "daily-update": "COMPUTED_ISOLATED", "evening-prepare": "COMPUTED"}
METADATA_FIELDS = "id,name,parents,trashed,size"


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    require(parsed.utcoffset() is not None, "CONNECTOR_CLOCK")
    return parsed


def object_name(day, node, role):
    parse_day(day)
    require(node in ROLES and (role in ROLES[node] or role == "RECEIPT.json"), "PLAN_ROLE")
    return f"V5_W11C_{day}_{node}_{role}"


def parse_metadata(row, name=None):
    require(isinstance(row, dict) and re.fullmatch(r"[A-Za-z0-9_-]+", row.get("id", ""))
            and row.get("parent_ids") == [PARENT] and row.get("trashed") is False
            and isinstance(row.get("name"), str) and (name is None or row["name"] == name)
            and type(row.get("file_size_bytes")) is int and row["file_size_bytes"] > 0,
            "CONNECTOR_METADATA")
    return row


def pinned_path(root, ref):
    path = root / ref["path"]
    require(path.resolve(strict=True) == path and path.is_relative_to(root) and path.is_file()
            and type(ref["bytes"]) is int and path.stat().st_size == ref["bytes"], "PIN_PATH_SIZE")
    with path.open("rb") as stream:
        actual = file_digest(stream, "sha256").hexdigest()
    require(actual == ref["sha256"], "PIN_SHA")
    return path


def stage_entry(root, row, name=None):
    meta = parse_metadata(row, name)
    require(meta.get("bytes") == meta["file_size_bytes"]
            and isinstance(meta.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", meta["sha256"]),
            "CONNECTOR_RAW_PIN")
    path = pinned_path(root, {**meta, "path": f"remote_{meta['id']}.raw"})
    return meta, path


def remote_inputs(root, day, runtime):
    """Read positive connector facts, never infer publication absence here."""
    path = root / "REMOTE_READBACKS.json"
    if not path.exists():
        return None
    require(path.resolve() == path and path.is_file(), "CONNECTOR_STAGE_PATH")
    stage = json.loads(path.read_bytes())
    require(stage.get("date") == day and isinstance(stage.get("entries"), list), "CONNECTOR_STAGE_DAY")
    ids, names = set(), set()
    for row in stage["entries"]:
        meta, _ = stage_entry(root, row)
        require(meta["name"] not in names and meta["id"] not in ids, "CONNECTOR_DUPLICATE_EXACT_NAME")
        names.add(meta["name"])
        ids.add(meta["id"])
    return runtime.driveio.staged_remote(root, day, generation=runtime.driveio.OBSERVATION_GENERATION)


def exact_query(name):
    return f"'{PARENT}' in parents and trashed = false and name = '{name}'"


def check_listing(proof, name, now):
    require(proof.get("schema") == "V5_DOT_CONNECTOR_LIST_V1"
            and proof.get("parent") == PARENT and proof.get("name") == name
            and proof.get("query") == exact_query(name) and proof.get("authenticated") is True,
            "CONNECTOR_LIST_SCOPE")
    start, end = timestamp(proof["requested_at"]), timestamp(proof["completed_at"])
    require(now - timedelta(seconds=60) <= start <= end <= now, "CONNECTOR_LIST_NOT_FRESH")
    pages = proof["pages"]
    require(isinstance(pages, list) and pages, "CONNECTOR_LIST_NO_PAGE")
    token, seen, rows = None, set(), []
    for index, page in enumerate(pages):
        require((index == 0 or token is not None) and page.get("request_page_token", "") == token
                and page.get("status") == "OK" and page.get("incomplete_search") is False
                and isinstance(page.get("files"), list),
                "CONNECTOR_LIST_INCOMPLETE")
        rows.extend(parse_metadata(row, name) for row in page["files"])
        token = page.get("next_page_token", "")
        require(token is None or isinstance(token, str) and bool(token) and token not in seen,
                "CONNECTOR_LIST_TOKEN")
        seen.add(token)
    require(token is None, "CONNECTOR_LIST_INCOMPLETE")
    require(len(rows) <= 1, "CONNECTOR_DUPLICATE_EXACT_NAME")
    return rows, start + timedelta(seconds=60)


def plan_path(state, day, node):
    parse_day(day)
    require(node in ROLES, "PLAN_NODE")
    return state / "plans" / day / f"{node}.json"


def load_plan(state, day, node):
    path = plan_path(state, day, node)
    if not path.exists():
        return None
    require(path.resolve() == path and path.is_file(), "PLAN_PATH")
    value = json.loads(path.read_bytes())
    require(value.get("schema") == "V5_DOT_PUBLISH_PLAN_V1" and value.get("node") == node
            and value.get("business_date") == day and value.get("status") == STATUSES[node]
            and set(value["objects"]) == ROLES[node]
            and all(value.get(key) == flag for key, flag in FLAGS.items()), "PLAN_SCOPE")
    for ref in value["objects"].values():
        pinned_path(state, ref)
    return value


def save_plan(state, day, node, objects):
    prior = load_plan(state, day, node)
    if prior is not None:
        require(prior["objects"] == objects, "LOCAL_PLAN_CONFLICT")
        return prior
    require(set(objects) == ROLES[node], "PLAN_OBJECT_ROLES")
    for ref in objects.values():
        pinned_path(state, ref)
    path = plan_path(state, day, node)
    mkdir(path.parent.parent)
    mkdir(path.parent)
    value = {"schema": "V5_DOT_PUBLISH_PLAN_V1", "business_date": day, "node": node,
             "status": STATUSES[node], "objects": objects, **FLAGS}
    atomic(path, json_bytes(value))
    return value


def create_journal(state):
    drive = state / "drive"
    require(not drive.exists() and not drive.is_symlink(), "DURABLE_DRIVE_JOURNAL_RESTORE_REQUIRED")
    mkdir(drive)
    journal_id = uuid4().hex
    raw = json_bytes({"schema": "V5_DOT_DRIVE_JOURNAL_V1", "journal_id": journal_id, "claims": {}})
    atomic(drive / "JOURNAL.json", raw)
    return journal_id, digest(raw)


def journal_file(state):
    marker, path = state / "DOT_OWNER.json", state / "drive" / "JOURNAL.json"
    require(marker.is_file() and marker.resolve() == marker and path.is_file() and path.resolve() == path,
            "DURABLE_DRIVE_JOURNAL_RESTORE_REQUIRED")
    raw = path.read_bytes()
    owner, journal = json.loads(marker.read_bytes()), json.loads(raw)
    require(journal.get("schema") == "V5_DOT_DRIVE_JOURNAL_V1"
            and isinstance(journal.get("claims"), dict)
            and isinstance(journal.get("journal_id"), str)
            and re.fullmatch(r"[a-f0-9]{32}", journal["journal_id"])
            and journal["journal_id"] == owner.get("journal_id")
            and digest(raw) == owner.get("journal_sha256"),
            "DURABLE_DRIVE_JOURNAL_RESTORE_REQUIRED")
    return path, journal


def persist_journal(state, path, journal):
    owner_path = state / "DOT_OWNER.json"
    owner = json.loads(owner_path.read_bytes())
    raw = json_bytes(journal)
    atomic(path, raw)
    atomic(owner_path, json_bytes({**owner, "journal_sha256": digest(raw)}))


def action(state, day, node, evidence=None, now=None):
    """Return one connector action. The Dot owner executes a create permit once."""
    now = now or datetime.now(timezone.utc)
    plan = load_plan(state, day, node)
    require(plan is not None, "NO_PUBLISHABLE_PLAN")
    plan_hash = digest(json_bytes(plan))
    journal_path, journal = journal_file(state)
    claims = journal["claims"]
    work = journal_path.parent / f"{day}_{node}"
    mkdir(work)
    refs = {}
    receipt_role = "RECEIPT.json"
    terminal_name = object_name(day, node, receipt_role)
    for role in (*sorted(plan["objects"]), receipt_role):
        name = object_name(day, node, role)
        if role == receipt_role:
            value = {"schema": "V5_W9D_REMOTE_RECEIPT_V1", "business_date": day, "node": node,
                     "status": plan["status"], "objects": refs, "natural_verified_count": 0, **FLAGS}
            raw = json_bytes(value)
            path = work / "terminal.payload"
            if path.exists():
                require(path.read_bytes() == raw, "TERMINAL_PAYLOAD_CONFLICT")
            else:
                atomic(path, raw)
            payload = {"path": path.relative_to(state).as_posix(), "bytes": len(raw), "sha256": digest(raw)}
        else:
            payload = plan["objects"][role]
        previous = claims.get(name)
        if previous is not None:
            require(previous["payload"] == payload and previous["plan_sha256"] == plan_hash
                    and previous["name"] == name, "REMOTE_JOURNAL_CONFLICT")
            if previous["status"] == "READBACK_VERIFIED":
                refs[role] = previous["readback"]
                continue
            require(previous["status"] == "ACK_UNKNOWN", "REMOTE_JOURNAL_STATUS")
        base = {"parent": PARENT, "name": name, "role": role, "business_date": day, "node": node,
                "payload": payload, "query": exact_query(name), "plan_sha256": plan_hash,
                "fields": METADATA_FIELDS, "node_receipt_name": terminal_name,
                "node_receipt_query": exact_query(terminal_name), **FLAGS}
        if evidence is None:
            return {"status": "LIST_EXACT", "local_claim": previous is not None, **base}
        require(evidence.resolve() == evidence and evidence.is_dir(), "CONNECTOR_EVIDENCE_DIRECTORY")
        proof_path = evidence / "LIST.json"
        require(proof_path.is_file() and proof_path.resolve() == proof_path, "CONNECTOR_LIST_PATH")
        proof = json.loads(proof_path.read_bytes())
        rows, expiry = check_listing(proof, name, now)
        observation = {**base, "list_sha256": digest(json_bytes(proof))}
        if rows:
            row = rows[0]
            raw_file = evidence / f"remote_{row['id']}.raw"
            if not raw_file.exists():
                return {"status": "READ_EXACT", "id": row["id"], **base}
            meta_path = evidence / f"metadata_{row['id']}.json"
            require(meta_path.is_file() and meta_path.resolve() == meta_path, "CONNECTOR_READBACK_METADATA")
            fetched = parse_metadata(json.loads(meta_path.read_bytes()), name)
            require(all(fetched[key] == row[key] for key in ("id", "name", "parent_ids", "trashed", "file_size_bytes")),
                    "CONNECTOR_LIST_GET_CONFLICT")
            require(fetched["file_size_bytes"] == payload["bytes"], "REMOTE_EXISTING_DIFFERENT_BYTES")
            pinned_path(evidence, {**payload, "path": raw_file.name})
            ref = {key: payload[key] for key in ("bytes", "sha256")} | {
                "id": row["id"], "name": name, "parent": PARENT, "verification": "RAW_REMOTE_IDENTICAL"}
            claims[name] = {**observation, "status": "READBACK_VERIFIED", "readback": ref}
            persist_journal(state, journal_path, journal)
            return {"status": "READBACK_VERIFIED", "readback": ref, **base}
        require(previous is None, "ACK_UNKNOWN_NO_RETRY")
        if role != receipt_role:
            node_path = evidence / "NODE_LIST.json"
            require(node_path.is_file() and node_path.resolve() == node_path, "NODE_RECEIPT_LIST_MISSING")
            node_proof = json.loads(node_path.read_bytes())
            node_rows, node_expiry = check_listing(node_proof, terminal_name, now)
            require(not node_rows, "EXISTING_NODE_RECEIPT_RECONCILE")
            observation["node_list_sha256"] = digest(json_bytes(node_proof))
            expiry = min(expiry, node_expiry)
        require(not any(evidence.glob("remote_*.raw")), "CONNECTOR_UNSCOPED_READBACK")
        claims[name] = {**observation, "status": "ACK_UNKNOWN", "claimed_at": now.isoformat()}
        persist_journal(state, journal_path, journal)
        return {"status": "CREATE_ONCE", "expires_at": expiry.isoformat(), **base}
    return {"status": "REMOTE_VERIFIED", "business_date": day, "node": node,
            "receipt": refs[receipt_role], **FLAGS}
