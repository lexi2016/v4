"""Export one already-frozen P5.15 RAW control batch without fitting a model."""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

from p515_adjudication_inputs import (
    BAR_COLUMNS,
    DAY_RECORD,
    RAW_PRICE_BASIS,
    csv_rows,
    write_csv,
)


SOURCE_POLICY = "ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2"
ARCHIVE_SHA = "generation_declared_raw_archive_sha256"
NATIVE_SHA = "generation_declared_raw_native_sha256"
GENERATION = "e7bbaf7dd6859c690953e9fad9822d3ff8c30c55bbefe3dc2d1592e4ad0f6638"
RECEIPT_SHA = "77567664cb53016cabe9f6f08146e46608189fe5f76f893e1956385688f340e2"
CALENDAR_SHA = "cd9f936b643da7ebca37a760fe41676b7758d477a9a06fa37e575c6b5b3c672d"
ROUTE = "NATIVE_NON_BUY_WITH_ARCHIVE_NON_CONF"
EXPOSURE = "RESEARCH_SCREENED_NOT_SEALED"
WINDOW = 120
MARKETS = {"SH", "SZ", "BJ"}
SECURITY = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
DAY_HEADER = struct.Struct("<I")
DEFICIENCY_FIELDS = (
    "market", "observation_date", "stable_security_id", "judgment_sample_id",
    "kind", "status", "detail",
)
JUDGE_FIELDS = (
    "sample_id", "observation_date", "input_prefix_file", "raw_prefix_sha256", "chart_file", "chart_sha256",
    "bar_count", "history_status", "price_basis", "volume_unit", "amount_unit", "exposure_status",
    "exchange_calendar_status", "suspension_status", "corporate_action_pit_status",
)


class CannotExport(ValueError):
    """One frozen observation is unusable as a D-only RAW prefix."""


def checksum(data: bytes) -> str:
    return sha256(data).hexdigest()


def verified_bytes(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if checksum(data) != expected:
        raise ValueError(f"Source SHA mismatch for {path.name}")
    return data


def checked_day(value: str) -> int:
    if len(value) != 8 or not value.isascii() or not value.isdecimal():
        raise ValueError(f"Invalid YYYYMMDD date {value!r}")
    date(int(value[:4]), int(value[4:6]), int(value[6:]))
    return int(value)


@dataclass(frozen=True)
class RawFile:
    role: str
    sha256: str
    path: Path
    data: bytes
    days: tuple[int, ...]

    def prefix_index(self, cutoff: int) -> dict[int, int]:
        stop = bisect_right(self.days, cutoff)
        return {day: index for index, day in enumerate(self.days[:stop])}

    def decode(self, index: int, security: str) -> dict[str, str | int]:
        day, opening, high, low, close, amount, volume, _ = DAY_RECORD.unpack_from(
            self.data, index * DAY_RECORD.size,
        )
        if (min(opening, high, low, close) <= 0
                or high < max(opening, low, close)
                or low > min(opening, high, close)
                or not isfinite(amount) or amount < 0):
            raise CannotExport(f"INVALID_RAW_BAR:{day}")
        prices = [f"{price // 100}.{price % 100:02d}" for price in (opening, high, low, close)]
        return dict(zip(BAR_COLUMNS, (security, str(day), *prices, volume, repr(amount))))


class BoundRawSource:
    def __init__(self, owner: Path, calendar: Path):
        self.owner = owner
        raw_receipt = verified_bytes(owner, RECEIPT_SHA)
        receipt = json.loads(raw_receipt)
        if receipt["generation_id"] != GENERATION or receipt["status"] != "CANDIDATE_READY":
            raise ValueError("Frozen owner receipt generation mismatch")
        snapshot = receipt["adjustment_snapshot"]
        if snapshot["sha256"] != receipt["snapshot_file_sha256"]:
            raise ValueError("Owner snapshot SHA conflict")
        self.snapshot = json.loads(verified_bytes(Path(snapshot["path"]), snapshot["sha256"]))
        self.snapshot_sha = snapshot["sha256"]
        if self.snapshot["asof_date"] != receipt["asof_date"]:
            raise ValueError("Owner snapshot target date mismatch")
        self.calendar = json.loads(verified_bytes(calendar, CALENDAR_SHA))
        self.cal_days = {
            market: tuple(checked_day(str(value)) for value in self.calendar[market])
            for market in MARKETS
        }
        self.cal_sets = {market: set(days) for market, days in self.cal_days.items()}
        if any(days != tuple(sorted(set(days))) for days in self.cal_days.values()):
            raise ValueError("Bound exchange calendar is unordered or duplicated")
        self.loaded: dict[str, dict[str, RawFile]] = {}

    def files_for(self, row: dict[str, str]) -> tuple[dict[str, RawFile], dict]:
        security = row["stable_security_id"]
        item = self.snapshot["symbols"].get(security)
        if not item or item.get("raw_resolution") != SOURCE_POLICY:
            raise CannotExport("MISSING_TYPED_RAW_SOURCE_BINDING")

        refs = item["raw_files"]
        observed = {ref["source_role"]: ref for ref in refs}
        expected_refs = {role: row[field] for role, field in (("archive", ARCHIVE_SHA), ("native", NATIVE_SHA))}
        if len(observed) != len(refs) or set(observed) != {"archive", "native"}:
            raise CannotExport("UNSUPPORTED_RAW_SOURCE_ROLE_SET")
        if any(
            not DIGEST.fullmatch(expected_refs[role]) or expected_refs[role] != ref["sha256"]
            or ref.get("from_date_exclusive") is not None
            for role, ref in observed.items()
        ):
            raise CannotExport("FROZEN_RAW_LINEAGE_CONFLICT")

        if security not in self.loaded:
            loaded = {}
            for role, ref in observed.items():
                path = Path(ref["path"])
                if not path.is_absolute():
                    raise CannotExport(f"INVALID_RAW_SOURCE_PATH:{role}")
                # The generation's content-addressed .day is authoritative. A duplicate
                # local path is usable only if it has the exact same byte SHA.
                locations = [path]
                original = ref.get("original_ref", {})
                current_native = original.get("current_native", {})
                alternatives = [original, current_native]
                locations.extend(
                    Path(alt["path"]) for alt in alternatives
                    if alt.get("sha256") == ref["sha256"] and alt.get("kind") != "archive_member"
                    and alt.get("path") and Path(alt["path"]).is_absolute()
                )
                missing_detail = "UNAVAILABLE"
                for location in dict.fromkeys(locations):
                    try:
                        raw = location.read_bytes()
                    except OSError:
                        continue
                    if checksum(raw) != ref["sha256"]:
                        missing_detail = "SHA_MISMATCH"
                        continue
                    path = location
                    break
                else:
                    raise CannotExport(f"RAW_SOURCE_{missing_detail}:{role}")
                if not raw or len(raw) % DAY_RECORD.size:
                    raise CannotExport(f"RAW_RECORD_ALIGNMENT:{role}")
                days = tuple(
                    DAY_HEADER.unpack_from(raw, offset)[0]
                    for offset in range(0, len(raw), DAY_RECORD.size)
                )
                if days != tuple(sorted(set(days))):
                    raise CannotExport(f"UNORDERED_OR_DUPLICATE_SOURCE_DATES:{role}")
                loaded[role] = RawFile(role, ref["sha256"], path, raw, days)
            self.loaded[security] = loaded
        return self.loaded[security], item

    def prefix(self, row: dict[str, str]) -> tuple[list[dict], dict]:
        security, market, d = row["stable_security_id"], row["exchange"], row["observation_date"]
        cutoff = checked_day(d)
        if (not SECURITY.fullmatch(security) or market != security[-2:]
                or row["panel_generation_id"] != GENERATION
                or row["security_identity_status"] != "PANEL_NATIVE_EXCHANGE_AND_SUFFIX_CONCORDANT"):
            raise CannotExport("SECURITY_IDENTITY_CONFLICT")
        if cutoff not in self.cal_sets[market]:
            raise CannotExport("D_NOT_IN_BOUND_EXCHANGE_CALENDAR")

        raw, symbol = self.files_for(row)
        index = {}
        for role in ("native", "archive"):
            origin = raw[role]
            index.update({day: (origin, position) for day, position in origin.prefix_index(cutoff).items()})
        if cutoff not in index:
            raise CannotExport("NO_BOUND_RAW_BAR_AT_D")
        days = sorted(index)[-WINDOW:]
        if any(day not in self.cal_sets[market] for day in days):
            raise CannotExport("RAW_PREFIX_DATE_OUTSIDE_BOUND_EXCHANGE_CALENDAR")
        used = Counter()
        bars = []
        for day in days:
            raw_file, position = index[day]
            bars.append(raw_file.decode(position, security))
            used[raw_file.role] += 1
        first = days[0]
        expected = {day for day in self.cal_days[market] if first <= day <= cutoff}
        event_days = sorted({
            int(event["ex_date"]) for event in symbol.get("events", ())
            if first <= int(event["ex_date"]) <= cutoff
        })
        details = {
            "security_identity_status": "SOURCE_KEY_BOUND_HISTORICAL_MASTER_UNKNOWN",
            "raw_bar_integrity_status": "EXACT_OWNER_SOURCE_SHA_AND_D_PREFIX_VERIFIED",
            "exchange_calendar_status": "ALL_PREFIX_DATES_MATCH_BOUND_EXCHANGE_SESSIONS",
            "exchange_calendar_sha256": CALENDAR_SHA,
            "missing_calendar_sessions_in_prefix": len(expected - set(days)),
            "missing_calendar_session_dates": "|".join(map(str, sorted(expected - set(days)))),
            "suspension_status": "UNKNOWN_NOT_INDEPENDENTLY_BOUND",
            "D_volume_activity_status": (
                "POSITIVE_RECORDED_ACTIVITY" if int(bars[-1]["volume"]) > 0 else "ZERO_RECORDED_VOLUME"
            ),
            "corporate_action_pit_status": "UNKNOWN_PUBLICATION_AND_AVAILABILITY_UNVERIFIED",
            "corporate_action_snapshot_ex_dates": "|".join(map(str, event_days)),
            "corporate_action_snapshot_sha256": self.snapshot_sha,
            "price_basis": RAW_PRICE_BASIS,
            "price_unit": "TDX_PRICE_INTEGER_DIV_100_CNY_PER_SHARE",
            "volume_unit": "TDX_RAW_UNSIGNED_INTEGER_NO_MULTIPLIER",
            "amount_unit": "TDX_RAW_TURNOVER_FLOAT_SCALE_NOT_INDEPENDENTLY_CERTIFIED",
            "raw_archive_file_sha256": raw["archive"].sha256,
            "raw_native_file_sha256": raw["native"].sha256,
            "raw_archive_file": str(raw["archive"].path),
            "raw_native_file": str(raw["native"].path),
            "archive_rows_used": used["archive"], "native_rows_used": used["native"],
            "prefix_start": str(first), "prefix_end": d, "bar_count": len(days),
            "history_status": "FULL_120_OBSERVED_BARS" if len(days) == WINDOW else "SHORT_OBSERVED_HISTORY",
        }
        return bars, details


def frozen_inputs(directory: Path, expected_freeze_sha: str) -> tuple[dict, list[dict], list[dict]]:
    freeze_name = "SAMPLE_SELECTION_FREEZE.json"
    freeze = json.loads(verified_bytes(directory / freeze_name, expected_freeze_sha))
    checks = {}
    for line in (directory / "SHA256SUMS_PRE_RAW_FREEZE.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if name in checks or Path(name).name != name or not DIGEST.fullmatch(digest):
            raise ValueError("Invalid freeze checksums")
        checks[name] = digest
    if checks.get(freeze_name) != expected_freeze_sha or freeze["status"] != "FROZEN_BEFORE_RAW_PRICE_ROWS_OPENED":
        raise ValueError("Frozen selection authority mismatch")

    frozen_files = freeze["output_files"]
    verified = {
        role: csv_rows(verified_bytes(directory / name, checks[name]))[1]
        for role, name in frozen_files.items()
    }
    all_rows = verified["all_ranked"]
    primary = [row for row in all_rows if row["frozen_selection_status"] == "PRIMARY_SELECTED"]
    reserves = [row for row in all_rows if row["frozen_selection_status"] == "FROZEN_REPLACEMENT_ORDER"]
    if primary != verified["primary"] or reserves != verified["reserves"] or len(all_rows) != 2325:
        raise ValueError("The frozen candidate list and rank export disagree")
    if Counter(row["exchange"] for row in primary) != {market: 30 for market in MARKETS}:
        raise ValueError("Frozen primary cohort must contain 30 observations per exchange")
    keys = {(row["stable_security_id"], row["observation_date"]) for row in all_rows}
    if len(keys) != len(all_rows) or len({row["sample_id"] for row in all_rows}) != len(all_rows):
        raise ValueError("Duplicate observation key or frame ID in frozen cohort")
    if any(
        row["research_sample_role"] != ROUTE or row["exact_key_in_prior_exposure_manifest"] != "FALSE"
        or row["freeze_input_state"] != "METADATA_ONLY_RAW_NOT_OPENED"
        for row in all_rows
    ):
        raise ValueError("An ineligible or previously exposed observation appeared in the frozen cohort")
    return freeze, primary, reserves


def evidence_issue(row: dict, judgment_id: str, kind: str, status: str, detail: str = "") -> dict:
    return dict(zip(DEFICIENCY_FIELDS, (
        row["exchange"], row["observation_date"], row["stable_security_id"], judgment_id, kind, status, detail,
    )))


def sha_of_file(path: Path) -> str:
    return checksum(path.read_bytes())


def write_table(path: Path, tables: list[dict], default: tuple[str, ...] = ()) -> None:
    fields = dict.fromkeys(key for row in tables for key in row)
    write_csv(path, tuple(fields) or default, tables)


def run_batch(args, workspace: Path) -> dict:
    freeze, primary, reserves = frozen_inputs(args.freeze_directory, args.freeze_sha256)
    judge = workspace / "D_ONLY_INPUTS"
    (judge / "bars").mkdir(parents=True)
    (judge / "charts").mkdir()
    source = BoundRawSource(args.owner_receipt, args.exchange_calendar)
    previous_manifest_rows = [
        row for source_ref in freeze["prior_exposure_manifests"]
        for row in csv_rows(verified_bytes(Path(source_ref["path"]), source_ref["sha256"]))[1]
    ]
    old_keys = {(row["stable_security_id"], row["observation_date"]) for row in previous_manifest_rows}
    candidate_keys = {(row["stable_security_id"], row["observation_date"]) for row in primary + reserves}
    if candidate_keys & old_keys:
        raise ValueError("Frozen cohort intersects the previously exposed exact observations")
    old_securities = {security for security, _ in old_keys}
    manifest, audit, exceptions, judge_manifest, exposure = [], [], [], [], []
    used_judge_ids: set[str] = set()

    def attempt(row: dict, slot: dict, previous_attempt: dict | None = None) -> bool:
        is_replacement = previous_attempt is not None
        frame_id = row["sample_id"]
        attempt_record = {
            "attempt_order": len(audit) + 1, "original_frame_sample_id": frame_id,
            "primary_frame_sample_id": slot["sample_id"], "primary_slot_in_stratum": slot["primary_slot"],
            "replaces_failed_frame_sample_id": previous_attempt["original_frame_sample_id"] if is_replacement else "",
            "replacement_trigger": previous_attempt["failure_reason"] if is_replacement else "",
            "stable_security_id": row["stable_security_id"], "observation_date": row["observation_date"],
            "market": row["exchange"], "proxy_category": row["proxy_category"],
            "frozen_selection_status": row["frozen_selection_status"],
            "freeze_stratum": row["freeze_stratum"],
            "freeze_rank_within_stratum": row["freeze_rank_within_stratum"],
            "freeze_stratum_population_n": row["freeze_stratum_population_n"],
            "freeze_stratum_primary_quota_n": row["freeze_stratum_primary_quota_n"],
            "conditional_replacement_order": row["conditional_replacement_order"],
            "p1_stage1_nominal_inclusion_probability": row["p1_stage1_nominal_inclusion_probability"],
            "p2_stage2_nominal_inclusion_probability": row["p2_stage2_nominal_inclusion_probability"],
            "combined_nominal_inclusion_probability": row["combined_nominal_inclusion_probability"],
            "realized_inclusion_probability_status": (
                "NOT_ESTIMATED_ADAPTIVE_FAILURE_DEPENDENT" if is_replacement else "NOMINAL_PRIMARY_DESIGN_ONLY"
            ),
        }
        panel_fields = {
            "generation_declared_raw_archive_sha256": row[ARCHIVE_SHA],
            "generation_declared_raw_native_sha256": row[NATIVE_SHA],
            "selector_sha256": row["panel_selector_sha256"],
            "panel_generation_id": GENERATION,
            "owner_receipt_sha256": RECEIPT_SHA,
            "freeze_sha256": args.freeze_sha256,
            "preexisting_exact_exposure": "FALSE",
            "same_security_prior_window_exposure": (
                "TRUE" if row["stable_security_id"] in old_securities else "FALSE"
            ),
            "prior_exposure_dates_same_security": row["prior_exposure_dates_same_security"],
        }
        try:
            bars, details = source.prefix(row)
        except CannotExport as error:
            failed = {
                **attempt_record, "judgment_sample_id": "", "attempt_status": "RAW_EXPORT_FAILED",
                "failure_reason": str(error), "slot_status": "PENDING_REPLACEMENT",
            }
            audit.append(failed)
            manifest.append({
                **failed, **panel_fields, "label_status": "UNKNOWN_NO_ADJUDICATION", "fit_eligible": "FALSE",
            })
            exceptions.append(evidence_issue(row, "", "RAW_EXPORT", "FAILED", str(error)))
            return False

        # Keep the supplied frame's link solely in management-side tables.
        judge_id = "H1-" + checksum(f"{args.freeze_sha256}|judgment|{frame_id}".encode())[:32]
        if judge_id in used_judge_ids:
            raise ValueError("Duplicate opaque review ID")
        used_judge_ids.add(judge_id)
        relative = f"bars/{judge_id}.csv"
        chart = f"charts/{judge_id}.png"
        path = judge / relative
        write_csv(path, BAR_COLUMNS, bars)
        _, saved = csv_rows(path.read_bytes())
        if any(
            {key: str(value) for key, value in expected.items()} != actual
            for expected, actual in zip(bars, saved, strict=True)
        ):
            raise ValueError("Exported CSV differs from selected RAW values")
        raw_sha = sha_of_file(path)

        packet = {
            "sample_id": judge_id, "observation_date": row["observation_date"],
            "input_prefix_file": relative, "raw_prefix_sha256": raw_sha, "chart_file": chart,
            "chart_sha256": "", "bar_count": details["bar_count"], "history_status": details["history_status"],
            "price_basis": details["price_basis"], "volume_unit": details["volume_unit"],
            "amount_unit": details["amount_unit"], "exposure_status": EXPOSURE,
            "exchange_calendar_status": details["exchange_calendar_status"],
            "suspension_status": details["suspension_status"],
            "corporate_action_pit_status": details["corporate_action_pit_status"],
        }
        judge_manifest.append(packet)
        done = {
            **attempt_record, "judgment_sample_id": judge_id, "attempt_status": "RAW_EXPORTED",
            "failure_reason": "", "slot_status": "FILLED_FROM_RESERVE" if is_replacement else "FILLED_BY_PRIMARY",
        }
        audit.append(done)
        manifest.append({
            **done, **panel_fields, **details,
            "raw_prefix_sha256": raw_sha, "raw_prefix_file": f"D_ONLY_INPUTS/{relative}",
            "chart_sha256": "", "chart_file": f"D_ONLY_INPUTS/{chart}",
            "label_status": "UNKNOWN_NO_ADJUDICATION", "fit_eligible": "FALSE",
        })
        exposure.append({
            "judgment_sample_id": judge_id, "original_frame_sample_id": frame_id,
            "market": row["exchange"], "stable_security_id": row["stable_security_id"],
            "observation_date": row["observation_date"], "raw_prefix_sha256": raw_sha,
            "preexisting_exact_exposure": "FALSE", "same_security_prior_window_exposure": panel_fields["same_security_prior_window_exposure"],
            "prior_exposure_dates_same_security": row["prior_exposure_dates_same_security"],
            "exposure_status": EXPOSURE, "exposure_basis": "OBSERVATION_ALREADY_SCREENED_IN_R1_3_SAMPLING_FRAME",
            "sealed_blind_eligible": "FALSE", "fit_eligible": "FALSE",
        })
        exceptions.extend((
            evidence_issue(row, judge_id, "SECURITY_HISTORICAL_MASTER", details["security_identity_status"]),
            evidence_issue(row, judge_id, "SUSPENSION", details["suspension_status"]),
            evidence_issue(row, judge_id, "CORPORATE_ACTION_PIT", details["corporate_action_pit_status"],
                           details["corporate_action_snapshot_ex_dates"]),
            evidence_issue(row, judge_id, "TURNOVER_UNIT", details["amount_unit"]),
        ))
        if details["history_status"] == "SHORT_OBSERVED_HISTORY":
            exceptions.append(evidence_issue(row, judge_id, "OBSERVED_HISTORY", "SHORT_OBSERVED_HISTORY",
                                             str(details["bar_count"])))
        if details["missing_calendar_sessions_in_prefix"]:
            exceptions.append(evidence_issue(row, judge_id, "CALENDAR_GAPS", "PRESERVED_AS_OBSERVED",
                                             details["missing_calendar_session_dates"]))
        return True

    failed_primaries = []
    for row in primary:
        if not attempt(row, row):
            failed_primaries.append((row, audit[-1]))

    ordered_reserves = defaultdict(list)
    for row in reserves:
        ordered_reserves[row["freeze_stratum"]].append(row)
    reserve_queues = {
        stratum: iter(sorted(rows, key=lambda row: int(row["conditional_replacement_order"])))
        for stratum, rows in ordered_reserves.items()
    }

    filled_by_replacement = set()
    for slot, prior in failed_primaries:
        for replacement in reserve_queues.get(slot["freeze_stratum"], ()):
            if attempt(replacement, slot, prior):
                filled_by_replacement.add(slot["sample_id"])
                break
            prior = audit[-1]
    failed_slots = {row["sample_id"] for row, _ in failed_primaries} - filled_by_replacement
    for row in audit + manifest:
        if row["attempt_status"] == "RAW_EXPORT_FAILED":
            row["slot_status"] = (
                "RESERVE_EXHAUSTED" if row["primary_frame_sample_id"] in failed_slots else "REPLACED_BY_FROZEN_RESERVE"
            )

    # Write the pre-render attempt trail before the chart subprocess reads
    # already-cut input files only. A render failure is not a sampling trigger.
    write_table(workspace / "SAMPLING_AND_REPLACEMENT_AUDIT.csv", audit)
    write_csv(judge / "INPUT_MANIFEST.csv", JUDGE_FIELDS, judge_manifest)
    subprocess.run([
        str(args.chart_python), str(Path(__file__).with_name("p515_adjudication_inputs.py").resolve()),
        "--render", str((judge / "INPUT_MANIFEST.csv").resolve()),
    ], check=True)

    chart_sha = {}
    for row in judge_manifest:
        png = (judge / row["chart_file"]).read_bytes()
        if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) < 10_000:
            raise ValueError(f"Invalid chart for {row['sample_id']}")
        row["chart_sha256"] = checksum(png)
        chart_sha[row["sample_id"]] = row["chart_sha256"]
    for row in manifest:
        if row["attempt_status"] == "RAW_EXPORTED":
            row["chart_sha256"] = chart_sha[row["judgment_sample_id"]]
    write_csv(judge / "INPUT_MANIFEST.csv", JUDGE_FIELDS, judge_manifest)

    contract = args.freeze_directory / "H1_RESEARCH_LABEL_CONTRACT_R1_3_ADDENDUM.json"
    shutil.copyfile(contract, judge / contract.name)
    template_header, template_rows = csv_rows(
        (args.freeze_directory / "H1_JUDGMENT_WORKSHEET_SCHEMA.csv").read_bytes(),
    )
    if template_rows or not {"sample_id", "raw_prefix_sha256"}.issubset(template_header):
        raise ValueError("Unexpected independent judgment template schema")
    # Packet filenames and row order reveal no primary/reserve identity or strata.
    worksheet_rows = [
        {"sample_id": row["sample_id"], "raw_prefix_sha256": row["raw_prefix_sha256"]}
        for row in sorted(judge_manifest, key=lambda entry: entry["sample_id"])
    ]
    for letter in ("A", "B"):
        write_csv(judge / f"INDEPENDENT_JUDGMENT_{letter}.csv", template_header, worksheet_rows)
    (judge / "README.md").write_text(
        "# P5.15 H1 D-only 判卷输入\n\n"
        "按不透明编号对照 INPUT_MANIFEST.csv、bars/ 和 charts/。证券代码保留在 RAW CSV 原始观测列，"
        "日期截至每条 D 收盘。CSV 涵盖最近最多 120 根已观测日线，不补齐休市或缺失。"
        "价格为 TDX 原始整数除 100，量和成交额保留源值。成交额独立尺度、停牌与公司行动可得时点仍待确认。\n\n"
        "两位判卷者分别填写 A、B 工作表，按合同填写七个已知类之一或 UNKNOWN 及拒判原因。"
        "普通反弹和无明显攻击等反例如不属七类，另填反例标签。此前已经过研究筛查，所有条目维持 "
        "RESEARCH_SCREENED_NOT_SEALED，判卷结果须复核。\n",
        encoding="utf-8",
    )
    # Sort the public manifest by its opaque ID, independent of the frozen draw order.
    write_csv(judge / "INPUT_MANIFEST.csv", JUDGE_FIELDS, sorted(judge_manifest, key=lambda row: row["sample_id"]))
    write_table(workspace / "RAW_CONTROL_BATCH_MANIFEST.csv", manifest)
    write_table(workspace / "DATA_QUALITY_EXCEPTIONS.csv", exceptions, DEFICIENCY_FIELDS)
    security_frequency = Counter(row["stable_security_id"] for row in exposure)
    for row in exposure:
        row["new_batch_obs_n_same_security"] = security_frequency[row["stable_security_id"]]
        row["same_security_repeated_in_this_batch"] = (
            "TRUE" if security_frequency[row["stable_security_id"]] > 1 else "FALSE"
        )
    write_table(workspace / "EXPOSURE_LEDGER.csv", exposure, (
        "judgment_sample_id", "original_frame_sample_id", "stable_security_id", "observation_date",
        "market", "raw_prefix_sha256", "exposure_status",
    ))
    by_market = Counter(row["market"] for row in exposure)
    success = len(judge_manifest)
    real_report = {
        "status": "COMPLETE" if success == len(primary) else "PARTIAL_RESERVE_EXHAUSTED",
        "source_frame_sha256": freeze["source_frame"]["sha256"],
        "selection_freeze_sha256": args.freeze_sha256, "owner_receipt_sha256": RECEIPT_SHA,
        "owner_snapshot_sha256": source.snapshot_sha, "exchange_calendar_sha256": CALENDAR_SHA,
        "primary_target": len(primary), "complete": success, "unfilled_slots": len(failed_slots),
        "primary_failed": len(failed_primaries), "replacement_attempts": len(audit) - len(primary),
        "filled_by_replacement": len(filled_by_replacement),
        "complete_by_market": dict(sorted(by_market.items())),
        "distinct_securities_exported": len(security_frequency),
        "securities_with_multiple_exported_observations": sum(n > 1 for n in security_frequency.values()),
        "failure_reasons": dict(sorted(Counter(row["failure_reason"] for row in audit if row["failure_reason"]).items())),
        "raw_bars_exported": sum(int(row["bar_count"]) for row in judge_manifest),
        "short_history": sum(row["history_status"] == "SHORT_OBSERVED_HISTORY" for row in judge_manifest),
        "windows_with_calendar_gaps": sum(row["kind"] == "CALENDAR_GAPS" for row in exceptions),
        "suspension_unverified": success, "corporate_action_pit_unverified": success,
        "turnover_unit_unverified": success, "prior_h1_windows": freeze["prior_exposure_manifests"][0]["rows"],
        "prior_sup_raw_windows": freeze["prior_exposure_manifests"][1]["rows"],
        "prior_exact_observation_overlap": len(previous_manifest_rows) - len(old_keys),
        "prior_unique_observations": len(old_keys), "new_exact_observation_overlap": 0,
        "unique_cumulative_observations": len(old_keys) + success,
        "new_same_security_prior_exposure": sum(row["same_security_prior_window_exposure"] == "TRUE" for row in exposure),
        "sealed": 0, "verified_training_rows": 0, "real_fit": 0, "real_prediction": 0,
        "synthetic_fit": 0, "synthetic_prediction": 0, "T2_recalculated": 0,
        "raw_source_policy": SOURCE_POLICY, "only_ohlcva_values_decoded_on_or_before_d": True,
    }
    (workspace / "RAW_CONTROL_EXPORT_RECEIPT.json").write_text(
        json.dumps(real_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return real_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("freeze-directory", "owner-receipt", "exchange-calendar", "chart-python", "output"):
        parser.add_argument("--" + field, required=True, type=Path)
    parser.add_argument("--freeze-sha256", required=True)
    args = parser.parse_args()
    outputs = (
        "RAW_CONTROL_BATCH_MANIFEST.csv", "SAMPLING_AND_REPLACEMENT_AUDIT.csv", "D_ONLY_INPUTS",
        "DATA_QUALITY_EXCEPTIONS.csv", "EXPOSURE_LEDGER.csv", "RAW_CONTROL_EXPORT_RECEIPT.json",
    )
    if not args.output.is_dir() or any((args.output / name).exists() for name in outputs):
        raise ValueError("Exporter requires an existing output directory and unused output names")

    with TemporaryDirectory(prefix="p515_raw_control_", dir=args.output) as staged:
        directory = Path(staged)
        report = run_batch(args, directory)
        for name in outputs:
            (directory / name).rename(args.output / name)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
