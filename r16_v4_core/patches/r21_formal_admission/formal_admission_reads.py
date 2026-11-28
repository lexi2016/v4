"""Read-only runtime identity and formal stage/scheduler admission for r21."""
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from starlette.responses import JSONResponse

from v4_core.runner.cache_lanes import STAGE7_ROLE, read_stage7
from v4_core.runner.evidence import EvidenceError, mapping, symbol
from v4_core.runner.main_windows import (
    _raw_cutoff_verified, _read_raw, _read_selection, observe_stage_receipt,
)
from v4_core.runner.schedule import MAIN_STAGES
from v4_core.runner.slots import SIX_SLOT_DEFS
from .seven_p0_reads import SAFETY, STAGES, TOP200_ROUTE

BUILD = "/api/v4/runtime-graph/frontend-build"
TASKS = "/api/v4/tasks/status"
STAGE = "/api/v4/workbench/stage"
REVIEW = "/api/v4/review"
TRACK = "r21_isolated_readonly_18874"
FROZEN_SOURCE = "e202bf8680a6de6d0867be879a76c0c2dbf84e1b96012e9da24c947a5488dd96"
SHANGHAI = ZoneInfo("Asia/Shanghai")
SHA = re.compile(r"[0-9a-f]{64}")
SLOT_IDS = tuple(SIX_SLOT_DEFS)
STAGE_TIMES = {stage.stage_id: window for window, stage in MAIN_STAGES.items() if stage.stage_id in STAGES}
SOURCE_EXECUTION_FILES = (
    "run_readonly_trial.py", "v4_core_pure_r21_20261127.zip", "source/v4_core/api/app.py",
    "content_projection/read_overlay.py", "content_projection/seven_p0_reads.py",
    "content_projection/formal_admission_reads.py", "content_projection/workbench_parity.py",
    "content_projection/read_preselection.py", "content_projection/read_scheduled_lane.py",
)
EVIDENCE_ONLY_DATES = frozenset({"2026-11-26", "2026-11-27"})
STAGE_OWNER = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage")
OBSERVATION_REFS = {
    "2026-11-27": {
        "slot_3_intraday_stage": (
            "evidence/content-20261127-input/STAGE_D27_VERIFIED_PROJECTION.json",
            "da402f7d253b88468d07fe0f421e84acf62eb7b59c2e4c2aa13dffff0d0dd764",
            "ISOLATED_OBSERVATION_READBACK",
        ),
        "slot_4_a_share_daily": (
            "daily_e2e_20261127/scheduled_jobs/2026-11-27/220256170963-41081-e1dxa6a9/attempt_receipt.json",
            "d97fb60d107775e577f9263ea2b9904bbbfb1fb9a9e1fe1db2e927a1e10ee85b",
            "OFF_WINDOW_ISOLATED_REPLAY",
        ),
        "slot_6_review_and_maint": (
            "daily_e2e_20261127/R21_D27_2115_REVIEW_VERIFIED.json",
            "8e7a1f8d920aa6a69a9fb172914bad7d62bb1262fb3f2ebb9c054d7c27d4d100",
            "MANUAL_ISOLATED_REVIEW",
        ),
    }
}

REPLAY_STDOUT_SHA256 = "82386ac727a85e75fa84644289e7f0964920ec61c1b40a734cf5c1e35a486842"
REPLAY_SLOT1_SHA256 = "70dd0cb68ef16ed6a41609ba9822c9e81424a66b7eac973d050a44aeaa60b7d8"
REPLAY_REGISTRATIONS = {
    "research": ("R21_RESEARCH_SCHEDULE_ACTIVE_FINAL.json",
                 "ffb991033912a7dcc500314cf37a55c96017de0be09b52508439669b27fe496b"),
    "daily": ("R21_DAILY_SCHEDULE_ACTIVE_FINAL.json",
              "cdd423d0c7843f8f61536426b2c52f704668c9f49d9d691114b79b526ba18245"),
}


def digest(raw):
    return sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def read_member(root, relative, limit=4 * 1024 * 1024):
    path = root / relative
    if Path(relative).is_absolute() or not path.is_relative_to(root) or path.resolve(strict=True) != path:
        raise ValueError("R21_BINDING_PATH_INVALID")
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("R21_BINDING_NOT_BOUNDED_REGULAR_FILE")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("R21_BINDING_FILE_SIZE_CONFLICT")
    return raw


def hash_bound(root, relative, expected):
    raw = read_member(root, relative)
    if not isinstance(expected, str) or not SHA.fullmatch(expected) or digest(raw) != expected:
        raise ValueError("R21_BINDING_SHA256_MISMATCH")
    return raw


def exact_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _actual_process(root):
    modules = {name: getattr(sys.modules.get(name), "__file__", "") for name in (
        "v4_core.api.app", "content_projection.read_overlay", "content_projection.formal_admission_reads",
    )}
    argv = Path(sys.argv[0]).resolve()
    return argv == root / "run_readonly_trial.py" and modules == {
        "v4_core.api.app": str(root / "source/v4_core/api/app.py"),
        "content_projection.read_overlay": str(root / "content_projection/read_overlay.py"),
        "content_projection.formal_admission_reads": str(root / "content_projection/formal_admission_reads.py"),
    }


class RuntimeIdentity:
    def __init__(self, root):
        self.root = root
        self.started_pid = os.getpid()
        self.manifest = None
        self.manifest_sha256 = None
        if not _actual_process(root):
            return
        try:
            raw = read_member(root, "content_projection/formal_admission_manifest.json", 16_384)
            manifest = json.loads(raw)
            self._verify(manifest)
        except (OSError, ValueError, KeyError, TypeError):
            return
        self.manifest = manifest
        self.manifest_sha256 = digest(raw)

    def _verify(self, manifest):
        if manifest["schema"] != "v4.r21.isolated_runtime_manifest.v1" or manifest["track"] != TRACK:
            raise ValueError("R21_WRONG_RUNTIME_MANIFEST")
        api = manifest["api_files"]
        if set(api) != set(SOURCE_EXECUTION_FILES) or api["v4_core_pure_r21_20261127.zip"] != FROZEN_SOURCE:
            raise ValueError("R21_EXECUTION_FILE_SET_CONFLICT")
        for relative, expected in api.items():
            hash_bound(self.root, relative, expected)
        frontend = manifest["frontend"]
        entry = frontend["script_path"]
        if not re.fullmatch(r"/assets/main-r21-formal-[0-9a-f]{12}\.js", entry):
            raise ValueError("R21_FRONTEND_SCRIPT_INVALID")
        html = hash_bound(self.root, "frontend/dist/index.html", frontend["index_sha256"])
        scripts = re.findall(rb'<script type="module" crossorigin src="([^"]+)"></script>', html)
        if scripts != [entry.encode()]:
            raise ValueError("R21_FRONTEND_INDEX_SCRIPT_MISMATCH")
        hash_bound(self.root, "frontend/dist" + entry, frontend["bundle_sha256"])
        if frontend["bundle_sha256"][:12] not in entry:
            raise ValueError("R21_FRONTEND_DIGEST_NAME_CONFLICT")

    def payload(self):
        common = {"schema_version": "v4.r21.isolated_runtime_identity.v1", "track": TRACK,
                  "production_switch": "NO_GO", "natural_verified": False, **SAFETY}
        if not self.manifest or os.getpid() != self.started_pid or not _actual_process(self.root):
            return {**common, "status": "CANNOT_CONFIRM", "reason": "R21_RUNTIME_PROCESS_NOT_BOUND"}
        try:
            current = read_member(self.root, "content_projection/formal_admission_manifest.json", 16_384)
            if digest(current) != self.manifest_sha256:
                raise ValueError("R21_RUNTIME_MANIFEST_CHANGED")
            self._verify(self.manifest)
        except (OSError, ValueError, KeyError, TypeError):
            return {**common, "status": "CANNOT_CONFIRM", "reason": "R21_RUNTIME_BYTES_CHANGED"}
        api_sha = digest(canonical(self.manifest["api_files"]))
        return {
            **common, "status": "VERIFIED", **self.manifest["frontend"],
            "api_manifest_sha256": api_sha, "api_release_id": "r21-18874-" + self.manifest_sha256[:12],
            "source_archive_sha256": FROZEN_SOURCE, "release_manifest_sha256": self.manifest_sha256,
            "pid": self.started_pid, "process_status": "SERVING_ISOLATED_REQUEST",
        }

    def runtime(self):
        identity = self.payload()
        verified = identity["status"] == "VERIFIED"
        return {
            "application": "V4", "status": "MANIFEST_EXECUTION_FILES_VERIFIED" if verified else "CANNOT_CONFIRM",
            "release_id": identity.get("api_release_id", ""), "process_status": identity.get("process_status", "CANNOT_CONFIRM"),
            "release_manifest_sha256": identity.get("release_manifest_sha256"), "pid": identity.get("pid"),
            "track": TRACK, "natural_verified": False, **SAFETY,
        }


def stage_evidence(owner_root, day, stage):
    hour, minute = STAGE_TIMES[stage]
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=SHANGHAI)
    iso = day.isoformat()
    evidence = {"stage_id": stage, "trade_date": iso, "market": "A", "status": "CANNOT_CONFIRM",
                "owner_receipt_verified": False, "formal_row_count": None, "observation_row_count": None}
    try:
        receipt, owner = observe_stage_receipt(owner_root, start, stage, start + timedelta(minutes=3))
        evidence.update(owner_receipt_verified=True, owner_receipt_sha256=receipt.sha256,
                        owner_status=owner.get("status"), owner_recorded_at=owner["recorded_at"])
        market = mapping(owner.get("selection_artifacts"), "STAGE_OWNER_SELECTION_INDEX_MISSING")
        selected, selection = _read_selection(owner_root, iso, stage, "A", mapping(
            market.get("A_SHARE"), "STAGE_OWNER_A_SELECTION_UNBOUND",
        ))
        evidence.update(owner_selection_status=selection.get("status"), source_status=selection.get("source_status"),
                        selection_artifact_sha256=selection["artifact"]["sha256"],
                        selection_manifest_sha256=selection["manifest"]["sha256"],
                        selection_receipt_sha256=selection["receipt"]["sha256"],
                        run_id=selection["run_id"], observation_row_count=len(selected))
        if selection.get("status") != "READY" or selection.get("source_status") != "READY":
            return {**evidence, "gap": "A_SELECTION_SOURCE_NOT_FORMAL_READY"}, set()
        raw, source = _read_raw(owner_root, iso, stage, "A", selection["raw_artifact_sha256"])
        if not (
            selected and source["source_status"] == source["status"] == "READY"
            and type(source["requested_rows"]) is int and source["requested_rows"] == selection["source_rows"] == len(raw)
            and _raw_cutoff_verified(raw, source, iso, stage, "A")
        ):
            return {**evidence, "gap": "A_SOURCE_CUTOFF_OR_FULL_COVERAGE_UNVERIFIED"}, set()
        source_symbols = {symbol(row.get("code"), "A") for row in raw}
        selected_symbols = {row["symbol"] for row in selected}
        if not selected_symbols <= source_symbols:
            return {**evidence, "gap": "A_SELECTION_NOT_IN_BOUND_SOURCE"}, set()
        return {**evidence, "status": "READY", "gap": None, "formal_row_count": len(selected_symbols),
                "raw_artifact_sha256": source["artifact"]["sha256"]}, selected_symbols
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
        gap = str(error).split(":", 1)[0] if isinstance(error, EvidenceError) else "A_STAGE_ARTIFACT_READ_FAILED"
        return {**evidence, "gap": gap}, set()


def formal_stage7(data, source, target=None):
    result = {
        "required_role": STAGE7_ROLE, "status": "CANNOT_CONFIRM", "signal_date": source.isoformat(),
        "target_date": target.isoformat() if target else None, "row_count": None,
        "stage_selection_eligible": False, "source_merge_role": "SOURCE_ONLY", **SAFETY,
    }
    try:
        binding, _ = read_stage7(data, source.isoformat(), target.isoformat() if target else None)
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
        gap = str(error).split(":", 1)[0] if isinstance(error, EvidenceError) else "STAGE7_SOURCE_READ_FAILED"
        return {**result, "gap": gap}
    # The native reader seals the raw inputs independently of the selection list.
    return {**result, "status": "READY", "gap": None,
            **{key: binding[key] for key in (
                "row_count", "target_date", "run_id", "registry_sha256", "manifest_canonical_sha256",
                "formal_rows_sha256", "source_identity",
            )}}


def _percent(value, total):
    return 100 * value / total if value is not None and total else None


def stage_projection(value, owner_root, data, day):
    if not value.get("dates"):
        return value
    entry = value["dates"][0]
    evidence, memberships = {}, {}
    for stage in STAGES:
        evidence[stage], members = stage_evidence(owner_root, day, stage)
        if evidence[stage]["status"] == "READY":
            memberships[stage] = members
    union = set().union(*memberships.values())
    hits = 0
    for stock in entry["stocks"]:
        stock["stage_memberships"] = [stage for stage, rows in memberships.items() if stock["code"] in rows]
        stock["stage_coverage_known"] = bool(memberships)
        hits += bool(stock["stage_memberships"])
    has_formal = bool(memberships)
    for stage, result in evidence.items():
        stage_members = memberships.get(stage)
        result.update(row_count=result["formal_row_count"], unique_codes=result["formal_row_count"],
                      hit_count=sum(stock["code"] in stage_members for stock in entry["stocks"]) if stage_members else None)
    top_count = len(entry["stocks"])
    entry.update(
        stage_coverage={"available": len(memberships), "total": len(STAGES),
                        "missing_stages": [stage for stage in STAGES if stage not in memberships],
                        "observed_owner_receipts": sum(item["owner_receipt_verified"] for item in evidence.values()),
                        "observed_stage_rows": sum(bool(item["observation_row_count"]) for item in evidence.values())},
        seven_stage={"status": "READY" if len(memberships) == len(STAGES) else "PARTIAL" if has_formal else "CANNOT_CONFIRM",
                     "selected_count": len(union) if has_formal else None, "hit_count": hits if has_formal else None,
                     "top200_coverage_pct": _percent(hits if has_formal else None, top_count),
                     "selection_hit_rate_pct": _percent(hits if has_formal else None, len(union)),
                     "stages": evidence},
        stage7_formal_review=formal_stage7(data, day),
    )
    return value


def observations_for_day(root, day):
    observations = {}
    for slot, (relative, expected, scope) in OBSERVATION_REFS.get(day.isoformat(), {}).items():
        try:
            value = json.loads(hash_bound(root, relative, expected))
            if any(value.get(key) is not False for key in SAFETY if key != "RESEARCH_ONLY") and slot != SLOT_IDS[2]:
                continue
            if slot == SLOT_IDS[2]:
                valid = value.get("trade_date") == day.strftime("%Y%m%d") and value.get("natural_verified") is False
            elif slot == SLOT_IDS[3]:
                valid = value.get("source_date") == day.isoformat() and value.get("official_natural_run") is False
            else:
                review = value.get("isolated_manual", {})
                valid = (review.get("natural_verified") is False
                         and value.get("native_2115", {}).get("trade_date") == day.strftime("%Y%m%d"))
            if valid:
                observations[slot] = {"scope": scope, "source_sha256": expected, "source_relative": relative,
                                      "natural_verified": False}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return observations


def _valid_replay(value, day):
    return (
        value.get("trade_date") == day.isoformat() and value.get("execution_mode") == "BACKFILL"
        and value.get("natural_window_evidence") is False and value.get("pit_evidence") is False
        and all(value.get(key) is flag for key, flag in SAFETY.items())
    )


def historical_replay(locator, day):
    empty = {"status": "CANNOT_CONFIRM", "windows": [], "slot_coverage": 0, "natural_verified": False}
    if day.isoformat() != "2026-11-27" or not locator:
        return empty
    try:
        root = Path(locator["root"])
        if root.resolve(strict=True) != root:
            raise ValueError("R21_REPLAY_ROOT_UNBOUND")
        cli = json.loads(hash_bound(root, "D27_BACKFILL_STDOUT.json", REPLAY_STDOUT_SHA256))
        slot1 = json.loads(hash_bound(root, "D27_SLOT1.json", REPLAY_SLOT1_SHA256))
        if not (_valid_replay(cli, day) and _valid_replay(slot1, day)
                and cli["slot_id"] == "all" and slot1["slot_id"] == SLOT_IDS[0]
                and slot1["windows"] == [] and slot1["reason"] == "NO_BOUND_R17_SCHEDULED_WINDOW"):
            raise ValueError("R21_REPLAY_SUMMARY_UNBOUND")
        receipts = []
        for window in cli["windows"]:
            slot, clock = window["slot_id"], window["window"]
            scheduled = datetime.fromisoformat(window["scheduled_for"]).astimezone(SHANGHAI)
            relative = f'backfill/{day.isoformat()}/receipts/daily_windows/{day.isoformat()}_{clock.replace(":", "")}.jsonl'
            if not (_valid_replay(window, day) and slot in SLOT_IDS[1:]
                    and scheduled.date() == day and scheduled.strftime("%H:%M") == clock
                    and window["backfill_ref"] == relative):
                raise ValueError("R21_REPLAY_WINDOW_UNBOUND")
            history = read_member(root, "owner-home/" + relative, 512 * 1024)
            if not any(json.loads(line) == window for line in history.splitlines() if line):
                raise ValueError("R21_BACKFILL_SAVED_RECEIPT_CONFLICT")
            receipts.append({"slot_id": slot, "window": clock, "schedule_status": window["schedule_status"],
                             "record_sha256": digest(canonical(window)), "receipt_relative": relative,
                             "natural_verified": False})
        if len({item["window"] for item in receipts}) != len(receipts):
            raise ValueError("R21_REPLAY_WINDOW_DUPLICATE")
    except (OSError, ValueError, KeyError, TypeError):
        return empty
    return {
        **empty, "status": "HISTORICAL_REPLAY_READBACK", "summary_sha256": REPLAY_STDOUT_SHA256,
        "slot_1_gap_sha256": REPLAY_SLOT1_SHA256, "slot_coverage": len({item["slot_id"] for item in receipts}),
        "windows": receipts,
    }


def replay_registrations(root):
    bindings = []
    for key, (file, expected) in REPLAY_REGISTRATIONS.items():
        try:
            value = json.loads(hash_bound(root, "evidence/" + file, expected))
            if value["status"] == "LOADED_REVIEWED" and value["run_at_load"] is False:
                bindings.append({"lane": key, "label": value["label"], "calendar": value["calendar"],
                                 "registration_receipt_sha256": expected, "observed_at": value["observed_at"],
                                 "scope": "ISOLATED_REPLAY_REGISTRATION_READBACK", "natural_verified": False})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return bindings


class FormalAdmissionReads:
    def __init__(self, data, previous, owner_root=STAGE_OWNER):
        self.data = data
        self.previous = previous
        self.owner_root = owner_root
        self.identity = RuntimeIdentity(data.parent.parent)

    def tasks(self, value, day):
        slots = value.get("timeline_nodes")
        if not isinstance(slots, list) or [row.get("slot_id") for row in slots] != list(SLOT_IDS):
            return value
        observations = observations_for_day(self.identity.root, day)
        locator = (self.identity.manifest or {}).get("historical_replay")
        historical = historical_replay(locator, day)
        registration = replay_registrations(self.identity.root)
        projected = [
            {
                "slot_id": row["slot_id"], "schedule_time": row.get("schedule_time"),
                "saved_slot_record": bool(row.get("execution_ref")),
                "source_receipt_status": "CANNOT_CONFIRM", "natural_verified": False,
                "isolated_replay_observation": observations.get(row["slot_id"]),
                "historical_window_count": sum(item["slot_id"] == row["slot_id"] for item in historical["windows"]),
                "gap": "FROZEN_PREOPEN_DISPATCH_WINDOW_UNBOUND" if row["slot_id"] == SLOT_IDS[0]
                else "NO_ADMITTED_NATURAL_SLOT_RECEIPT",
            }
            for row in slots
        ]
        existing = value.get("scheduler_observation", {})
        observation = {
            **existing, "natural_verified": False, "natural_verified_count": 0, "six_slot_evidence": projected,
            "isolated_observation_count": len(observations), "historical_replay": historical,
            "isolated_replay_registrations": registration,
            "message": (f'{existing.get("receipt_count", 0)}/6 同日槽位保存记录 · 自然执行待核 · '
                        f'历史回放 {len(historical["windows"])} 个时点，覆盖 {historical["slot_coverage"]}/6 槽位 · '
                        '07:00 正式任务调度入口未绑定'),
        }
        return {**value, "scheduler_observation": observation,
                "cannot_confirm": [*value.get("cannot_confirm", []), "SLOT1_FORMAL_DISPATCH_WINDOW_UNBOUND"]}

    def stage7(self, value, requested, source):
        if not isinstance(value, dict) or value.get("stage_id") != STAGES[-1]:
            return value
        return {**value, "stage7_formal_review": formal_stage7(self.data, source, requested if source != requested else None)}

    def review(self, value, day):
        return {**value, "stage7_formal_review": formal_stage7(self.data, day)}

    def native_transform(self, path, query):
        if path == TASKS and set(query) <= {"date"} and len(query.get("date", [])) <= 1:
            def tasks(value):
                day = exact_date(value.get("business_date"))
                return self.tasks(value, day) if day else value
            return tasks
        if path == STAGE and query.get("stage") == [STAGES[-1]] and query.get("market") in (None, ["A"], ["A_SHARE"]):
            if len(query.get("date", [])) == 1 and len(query.get("source_date", [])) <= 1:
                target = exact_date(query["date"][0])
                source = exact_date(query.get("source_date", query["date"])[0])
                if target and source and source <= target:
                    return lambda value: self.stage7(value, target, source)
        if path == REVIEW and set(query) == {"date"} and len(query["date"]) == 1:
            day = exact_date(query["date"][0])
            if day:
                return lambda value: self.review(value, day)
        return None

    def resolve(self, path, query):
        value = None
        if path == BUILD and not query:
            value = self.identity.payload()
        elif path == TOP200_ROUTE and set(query) == {"date"} and len(query["date"]) == 1:
            requested = query["date"][0]
            day = exact_date(requested)
            if day and day.isoformat() in EVIDENCE_ONLY_DATES:
                value = self.previous.top200(requested)
                if value is not None:
                    value = stage_projection(value, self.owner_root, self.data, day)
        return JSONResponse(value, headers={"Cache-Control": "no-store"}) if value is not None else None
