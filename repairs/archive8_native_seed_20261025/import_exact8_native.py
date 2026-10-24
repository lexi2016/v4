"""Import eight accepted archive byte strings under the original publication lock.

Preparation only until a fresh controller-bound GO, independent integration
review, registered execution and stopped-writer receipt authorize this helper.
This helper never publishes panels, edits metadata, resumes services or computes
prices. The unchanged adopter owns the subsequent pair/five-metadata transaction.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

CODES = frozenset("601091 601123 603448 688801 688826 688835 688836 688837".split())
NATIVE = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/tdx/vipdoc/sh/lday")
FLAGS = dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(value):
    p = Path(value["path"])
    need(p.is_absolute() and p.is_file() and not p.is_symlink(), "REF_PATH")
    need(sha(p) == value["sha256"], "REF_SHA:" + str(p))
    return p


def sync_parent(path):
    fd = os.open(Path(path).parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def journal(path, record, initial=False):
    payload = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if initial:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(payload); f.flush(); os.fsync(f.fileno())
    else:
        temporary = path.with_name(path.name + ".owned-update")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(payload); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, path)
    sync_parent(path)


def cas(config):
    # Extra preflight uses small bytes and accepted stat continuity. The original
    # adopter still performs all of its unchanged full integrity checks.
    for item in config["pointer_CAS"] + config["metadata_CAS"]:
        p = Path(item["path"])
        need(not p.is_symlink() and p.read_bytes() == ref(item["before"]).read_bytes(), "CAS_BYTES:" + str(p))
    for item in config["panel_stat_CAS"]:
        s = Path(item["path"]).stat()
        need(dict(st_dev=s.st_dev, st_ino=s.st_ino, st_size=s.st_size, st_mtime_ns=s.st_mtime_ns) == item["stat_binding"], "CAS_PANEL_STAT")


def authorized(config_path, go_path, expected_go_sha, rollback=False):
    need(sha(go_path) == expected_go_sha, "EXTERNALLY_PINNED_ROOT_GO_SHA")
    config = json.loads(config_path.read_text()); go = json.loads(go_path.read_text())
    decision = "GO_EXACT8_NATIVE_SEED_ROLLBACK" if rollback else "GO_EXACT8_NATIVE_SEED_IMPORT"
    need(go.get("decision") == decision and go.get("authorized") is True, "FRESH_NATIVE_GO_REQUIRED")
    need(go.get("code_sha256") == sha(__file__) and go.get("config_sha256") == sha(config_path), "GO_SOURCE_BINDING")
    need(go.get("execution_id") == config["execution_id"] and go.get("safety_flags") == FLAGS, "GO_EXECUTION_FLAGS")
    for key in ("candidate_acceptance", "adoption_plan"):
        need(go[key] == config[key], "GO_SCOPE_REF:" + key)
        ref(config[key])
    # Review and stopped-writer refs belong to the fresh externally pinned GO;
    # putting a review's own digest into its reviewed config would create a
    # circular identity dependency.
    review = json.loads(ref(go["integration_review"]).read_text())
    need(review.get("decision") == "PASS_DEFAULT_CANDIDATE_ADOPTION_INTEGRATION", "INDEPENDENT_INTEGRATION_PASS_REQUIRED")
    need(review.get("plan_sha256") == config["adoption_plan"]["sha256"], "REVIEW_PLAN_BINDING")
    need(review.get("native_seed_config_sha256") == sha(config_path), "REVIEW_NATIVE_CONFIG_BINDING")
    need(review.get("native_seed_helper_sha256") == sha(__file__), "REVIEW_NATIVE_HELPER_BINDING")
    need(review.get("writer_id") != review.get("reviewer_id") and review.get("reviewer_id"), "INDEPENDENT_REVIEWER_REQUIRED")
    stopped = json.loads(ref(go["stopped_no_writer"]).read_text())
    need(stopped.get("status") == "STOPPED_NO_WRITER", "STOPPED_NO_WRITER_RECEIPT_REQUIRED")
    acceptance = json.loads(ref(config["candidate_acceptance"]).read_text())
    need(acceptance.get("verdict") == "REVIEWED/PASS_LOCAL_PANEL_HISTORY_CANDIDATE"
         and acceptance.get("candidate_generation") == config["generation_id"], "ACTUAL_CANDIDATE_PASS_REQUIRED")
    registry = Path(config["registry_path"])
    events = [json.loads(line) for line in registry.open()]
    for kind in ("RUN_STARTED", "CHECKPOINT"):
        identity = go["registry_events"][kind]
        matches = [e for e in events if e.get("event_sha256") == identity]
        need(len(matches) == 1, "EXACT_REGISTRY_EVENT_REQUIRED")
        e = matches[0]
        need(e.get("execution_id") == config["execution_id"] and e.get("event_type") == kind, "EVENT_EXECUTION")
        need(e.get("code_sha256") == sha(__file__) and e.get("config_sha256") == sha(config_path), "EVENT_SOURCE")
        body = {k: v for k, v in e.items() if k != "event_sha256"}
        need(hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest() == identity, "EVENT_CANONICAL_SHA")
    need(set(config["seeds"]) == CODES, "EXACT_EIGHT_ONLY")
    qpath = ref(config["publisher_source"])
    sys.path.insert(0, str(qpath.parents[1]))
    spec = importlib.util.spec_from_file_location("archive8_seed_original_qfq", qpath)
    q = importlib.util.module_from_spec(spec); sys.modules[spec.name] = q; spec.loader.exec_module(q)
    return config, q


def create_seeds(config, q):
    path = Path(config["journal_path"])
    need(path.parent.is_dir() and not path.exists(), "FRESH_JOURNAL_REQUIRED")
    created = []
    record = dict(status="PREPARED", execution_id=config["execution_id"], created=created,
                  candidate_generation=config["generation_id"], helper_sha256=sha(__file__), **FLAGS)
    with q.publication_lock(Path(config["data_root"])):
        cas(config)
        payloads = {}
        for code, item in config["seeds"].items():
            destination = NATIVE / ("sh" + code + ".day")
            need(item["destination"] == str(destination) and destination.parent.resolve() == NATIVE, "EXACT_NATIVE_PATH")
            need(not os.path.lexists(destination), "EXPECTED_ABSENT:" + str(destination))
            payload = ref(item["original_bytes"]).read_bytes()
            need(len(payload) == item["rows"] * 32 and item["last_date"] == 20261019, "EXACT_ACCEPTED_MEMBER_BOUNDARY")
            payloads[code] = payload
        need(sum(len(v) for v in payloads.values()) == 7072, "EXACT_221_RAW32_BYTES")
        journal(path, record, initial=True)
        try:
            for code in sorted(CODES):
                destination = NATIVE / ("sh" + code + ".day")
                temporary = destination.with_name(destination.name + "." + config["execution_id"] + ".owned-seed")
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(payloads[code]); f.flush(); os.fsync(f.fileno())
                need(temporary.read_bytes() == payloads[code], "TEMP_BYTE_READBACK")
                st = temporary.stat()
                item = dict(path=str(destination), temporary=str(temporary), st_dev=st.st_dev, st_ino=st.st_ino, st_size=st.st_size, sha256=hashlib.sha256(payloads[code]).hexdigest(), linked=False)
                created.append(item); journal(path, record)
                os.link(temporary, destination)  # Fails EEXIST; never replaces.
                item["linked"] = True; sync_parent(destination); journal(path, record)
                need(destination.stat().st_ino == st.st_ino and destination.read_bytes() == payloads[code], "NATIVE_BYTE_READBACK")
                temporary.unlink(); sync_parent(temporary)
            cas(config)
            record["status"] = "IMPORTED_SEEDS_ONLY_AWAITING_ORIGINAL_ADOPTION"
            journal(path, record)
        except BaseException:
            # No publisher/service has run inside this helper. Delete only our
            # own unchanged hardlinks, after checking the complete ownership set.
            record["status"] = "IMPORT_FAILED_ROLLBACK_REQUIRED"; journal(path, record)
            cas(config)
            owned = []
            preserved = []
            for item in created:
                for key in ("path", "temporary"):
                    p = Path(item[key])
                    if not os.path.lexists(p):
                        continue
                    if key == "path" and not item["linked"]:
                        # Equal inode/content does not prove who created this
                        # name. A competing link caused EEXIST, or success was
                        # not durably acknowledged before a crash. Preserve it.
                        preserved.append(str(p))
                        continue
                    s = p.lstat()
                    need(not p.is_symlink() and (s.st_dev, s.st_ino, s.st_size) == (item["st_dev"], item["st_ino"], item["st_size"]) and sha(p) == item["sha256"], "ROLLBACK_OWNERSHIP_CONFLICT:" + str(p))
                    owned.append(p)
            for p in owned:
                p.unlink(); sync_parent(p)
            record["status"] = "ROLLED_BACK_OWNED_IMPORT_ONLY"
            record["unowned_or_unacknowledged_destinations_preserved"] = preserved
            journal(path, record)
            raise
    return record


def rollback_import(config, q):
    """Explicit owned recovery only while original pair/metadata remain old.

    A committed candidate changes CAS, so this cannot remove its dependencies.
    An unknown third-party change prevents every deletion and preserves evidence.
    """
    path = Path(config["journal_path"])
    with q.publication_lock(Path(config["data_root"])):
        cas(config)
        record = json.loads(path.read_text())
        need(record.get("execution_id") == config["execution_id"]
             and record.get("candidate_generation") == config["generation_id"]
             and record.get("helper_sha256") == sha(__file__), "RECOVERY_JOURNAL_IDENTITY")
        owned = []
        preserved = []
        for item in record["created"]:
            p = Path(item["path"])
            need(p.parent == NATIVE and p.name[2:-4] in CODES, "RECOVERY_PATH_SCOPE")
            code = p.name[2:-4]
            need(item["sha256"] == config["seeds"][code]["original_bytes"]["sha256"], "RECOVERY_SOURCE_BINDING")
            expected_temp = p.with_name(p.name + "." + config["execution_id"] + ".owned-seed")
            need(item["temporary"] == str(expected_temp), "RECOVERY_TEMP_SCOPE")
            for candidate in (p, expected_temp):
                if not os.path.lexists(candidate):
                    continue
                if candidate == p and not item["linked"]:
                    preserved.append(str(candidate))
                    continue
                st = candidate.lstat()
                need(not candidate.is_symlink()
                     and (st.st_dev, st.st_ino, st.st_size) == (item["st_dev"], item["st_ino"], item["st_size"])
                     and sha(candidate) == item["sha256"], "RECOVERY_OWNERSHIP_CONFLICT")
                owned.append(candidate)
        for candidate in owned:
            candidate.unlink(); sync_parent(candidate)
        record["status"] = "ROLLED_BACK_OWNED_IMPORT_ONLY"
        record["unowned_or_unacknowledged_destinations_preserved"] = preserved
        journal(path, record)
        return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--go", required=True, type=Path)
    parser.add_argument("--go-sha256", required=True)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    config, original = authorized(args.config, args.go, args.go_sha256, args.rollback)
    action = rollback_import if args.rollback else create_seeds
    print(json.dumps(action(config, original), ensure_ascii=False, sort_keys=True))
