"""Validate and prepare a portable, identical P5.15 train/development package.

This tool validates a proposed normalized contract. A formal common manifest and
its separately approved SHA are still required before processing real samples.
It never fits an estimator or reads files outside the manifest bundle.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, time, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile
from zoneinfo import ZoneInfo


SCHEMA = "p515-common-training/1"
TASK_SCHEMA = "p515-common-training/2"
KEY = ("stable_security_id", "observation_date", "event_id")
OBSERVATION_KEY = KEY[:2]
IDENTITY_FIELDS = (
    "root_anchor_id", "wave_id", "event_start_date", "label_maturity_date",
    "label_source_sha256",
    "feature_evidence_sha256", "label_confidence", "PIT_status",
    "feature_available_at", "decision_at",
)
FOLD_FIELDS = ("sample_id", "comparison_group_id", "fold_id", "partition")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{8}$")
SECURITY_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
PLACEHOLDERS = {"", "UNKNOWN", "NONE", "UNRESOLVED", "NULL", "N/A"}
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
RAW_COLUMNS = ("trade_date", "open", "high", "low", "close", "volume", "amount")
RAW_PRICE_BASIS = "RAW_UNADJUSTED"
STATUS_CERTIFIED = {
    "security_identity_status": "VERIFIED",
    "raw_bar_integrity_status": "VERIFIED",
    "exchange_calendar_status": "VERIFIED_DATED",
    "suspension_status": "VERIFIED_DATED",
    "corporate_action_pit_status": "VERIFIED_DATED",
    "sector_pit_status": "VERIFIED_DATED",
}
PREPARATION_STATUS = {
    "security_identity_status": "SOURCE_KEY_BOUND_HISTORICAL_MASTER_UNKNOWN",
    "raw_bar_integrity_status": "EXACT_RAW_SOURCE_VERIFIED",
}
TASK_FIELDS = (
    "sample_id", "exposure_status", "event_identity_status", *STATUS_CERTIFIED,
    "price_basis", "raw_prefix_sha256", "raw_prefix_row_count", "raw_prefix_max_date",
    "volume_unit", "amount_unit",
    "observation_evidence_sha256", "raw_root_anchor_id", "raw_root_anchor_date",
    "attack_start_date", "attack_end_date", "pullback_start_date", "pullback_end_date",
    "support_role", "event_lineage_sha256", "same_role_history_sha256", "sector_membership_sha256",
)
TASK_EVIDENCE_TYPES = {
    "raw_prefix", "observation_certification", "event_lineage",
    "same_role_history", "sector_membership",
}
OBSERVATION_EVIDENCE_FIELDS = (
    "sample_id", *OBSERVATION_KEY, *(field for field in STATUS_CERTIFIED if field != "sector_pit_status"),
    "raw_prefix_sha256", "price_basis", "volume_unit", "amount_unit", "feature_available_at",
)
EVENT_EVIDENCE_FIELDS = (
    "sample_id", "stable_security_id", "event_id", "event_identity_status", "event_start_date",
    "raw_root_anchor_id", "raw_root_anchor_date", "wave_id", "attack_start_date", "attack_end_date",
    "pullback_start_date", "pullback_end_date", "support_role",
)
JUDGMENT_FIELDS = (
    "sample_id", "comparison_group_id", *OBSERVATION_KEY, "target_name", "target_value",
    "label_maturity_date", "judge_a", "judge_b", "judge_a_value", "judge_b_value", "arbitrator",
    "resolution_status",
)
HISTORY_FIELDS = (
    "sample_id", "stable_security_id", "current_raw_root_anchor_id", "history_event_id",
    "history_raw_root_anchor_id", "history_role", "history_maturity_date", "available_at",
)
SECTOR_FIELDS = (
    "sample_id", "stable_security_id", "industry_id", "classification_version",
    "effective_from_date", "effective_to_date", "published_at", "available_at",
)
FEATURE_EVIDENCE_FIELDS = ("sample_id", "comparison_group_id", *OBSERVATION_KEY, "feature_values_sha256", "available_at")
TASK_EXPORT_FIELDS = (
    "event_identity_status", *STATUS_CERTIFIED, "exposure_status", "price_basis",
    "raw_prefix_sha256", "raw_prefix_row_count", "raw_prefix_max_date", "volume_unit", "amount_unit",
    "observation_evidence_sha256", "label_maturity_date", "label_source_sha256",
    "feature_evidence_sha256", "label_confidence", "feature_available_at", "decision_at",
)
SHANGHAI = ZoneInfo("Asia/Shanghai")

PRICE = ["bar_return_pct", "bar_range_pct", "volume_over_prior20_mean", "amount_over_prior20_mean"]
STRUCTURE = [
    "root_body_position", "attack_gain_pct", "attack_duration_sessions",
    "true_pullback_age_sessions", "current_true_pullback_depth_pct",
    "pullback_over_attack_volume", "distance_to_root_low_pct", "close_reclaimed_root_low",
]
# H1 compares candle geometry available on D, including controls without an event.
H1_STRUCTURE = ["bar_body_fraction", "bar_upper_wick_fraction", "bar_lower_wick_fraction", "bar_close_location"]
MARKET = ["market_relative_return_1d", "market_breadth_1d"]
SECTOR = [
    f"sector_loo_{field}_{window}d"
    for field in ("return", "breadth", "amount_change") for window in (1, 5, 20)
] + ["sector_loo_relative_return_5d", "leader_relative_return_5d", "target_minus_leader_return_5d"]
PERSONALITY = [
    "same_role_history_event_n", "own_depth_median_shrunk_pct", "own_duration_median_shrunk",
    "own_volume_ratio_shrunk", "own_support_failure_rate_shrunk",
]
PHASES = [
    "BUILDUP_STRUCTURE_CANDIDATE", "IGNITION", "ADVANCE", "TREND_CONSOLIDATION",
    "HIGH_LEVEL_RISK", "DISTRIBUTION_RISK_CANDIDATE", "STRUCTURE_FAILURE",
]
SUPPORT = ["SUPPORT_HELD", "STRUCTURE_FAILURE"]
EXCLUSION_CODES = [
    "UNKNOWN_LABEL", "PARTIAL_LABEL", "NOT_MATURE", "FUTURE_INFO", "ANCHOR_UNRESOLVED",
    "PIT_UNVERIFIED", "FEATURE_MISSING", "SPLIT_PURGED", "OUTSIDE_WINDOW",
    "DUPLICATE_OR_OVERLAP", "NOT_ELIGIBLE_FOR_TASK", "OTHER_POLICY",
]
FEATURE_TYPES = {
    "close_reclaimed_root_low": "binary_0_1",
    "attack_duration_sessions": "nonnegative_integer",
    "true_pullback_age_sessions": "nonnegative_integer",
    "same_role_history_event_n": "nonnegative_integer",
}


def expected_groups(task_specific=False):
    return {
        "H1_PHASE": {
            "target": "phase_label", "target_kind": "classification", "classes": PHASES,
            "variants": {"A_PRICE": PRICE, "A_STRUCTURE": PRICE + (H1_STRUCTURE if task_specific else STRUCTURE)},
            "metrics": ["macro_f1", "recall_by_class", "confusion_matrix"],
        },
        "H2_DEPTH": {
            "target": "terminal_pullback_depth_pct", "target_kind": "regression", "classes": [],
            "variants": {"B_DEPTH_PRICE": PRICE, "B_DEPTH_STRUCTURE": PRICE + STRUCTURE},
            "metrics": ["mae_percentage_points", "rmse_percentage_points"],
        },
        "H2_TIME": {
            "target": "sessions_to_pullback_outcome", "target_kind": "regression", "classes": [],
            "variants": {"B_TIME_PRICE": PRICE, "B_TIME_STRUCTURE": PRICE + STRUCTURE},
            "metrics": ["mae_sessions", "rmse_sessions"],
        },
        "H2_SUPPORT": {
            "target": "support_label", "target_kind": "classification", "classes": SUPPORT,
            "variants": {"B_SUPPORT_PRICE": PRICE, "B_SUPPORT_STRUCTURE": PRICE + STRUCTURE},
            "metrics": ["macro_f1", "recall_by_class", "confusion_matrix", "structure_failure_miss_rate"],
        },
        "H3_SUPPORT": {
            "target": "support_label", "target_kind": "classification", "classes": SUPPORT,
            "variants": {
                "C_MARKET": MARKET,
                "C_MARKET_SECTOR": MARKET + SECTOR,
                "C_MARKET_PERSONALITY": MARKET + PERSONALITY,
                "C_ALL": MARKET + SECTOR + PERSONALITY,
            },
            "metrics": ["macro_f1", "recall_by_class", "matched_date_delta", "history_count_strata"],
        },
        "H4_SUPPORT": {
            "target": "support_label", "target_kind": "classification", "classes": SUPPORT,
            "variants": {"D_MARKET": MARKET, "D_SECTOR": MARKET + SECTOR},
            "metrics": ["macro_f1", "recall_by_class", "matched_date_delta", "sector_missingness"],
        },
    }


def sample_columns(task_specific):
    identities = set(KEY + IDENTITY_FIELDS) | {"label_source", "phase_label", "pullback_label"}
    if task_specific:
        identities = (identities - {"PIT_status"}) | set(TASK_FIELDS)
    groups = expected_groups(task_specific).values()
    targets = {group["target"] for group in groups}
    features = {field for group in groups for variant in group["variants"].values() for field in variant}
    return sorted(identities | targets | features)


def canonical_sha(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return digest_bytes(encoded)


def contract_hashes(task_specific=False):
    groups = expected_groups(task_specific)
    admission = ({
        "observation_key": OBSERVATION_KEY,
        "hypothesis_specific": True,
        "required_statuses": STATUS_CERTIFIED,
        "unknown_statuses": "retained_for_review_preparation_excluded_from_assigned_required_supervised_folds",
        "structural_controls": "H1 NO_REAL_EVENT and blank event_id; no fake roots",
        "exposure": "EXPOSED_DEV cannot enter FROZEN_SUPERVISED train or development assignments",
        "raw_prefix": "bound bytes, RAW_UNADJUSTED, exact security, ordered OHLCVA through D close",
        "H2": "certified raw root and real wave with separated attack and pullback dates and support role",
        "H3": "H2 and certified distinct prior events with same support role available by D; sector PIT for sector ablation",
        "H4": "H2 and historical industry classification, effective date interval, published_at and available_at",
    } if task_specific else {"admitted_pit_status": "VERIFIED_DATED"})
    return {
        "label_contract_sha256": canonical_sha({
            "phase_classes": PHASES,
            "pullback_outcomes": ["SUCCESS", "FAILURE", "NOT_STARTED", "UNKNOWN", "CENSORED"],
            "support_classes": SUPPORT,
            "admitted_confidence": "VERIFIED",
            **admission,
            "training_maturity": "label_maturity_date < first_development_observation_date",
            "development_maturity": "label_maturity_date <= development_label_cutoff",
            "event_timing": ("event_start_date <= D where event exists; D <= label_maturity_date"
                             if task_specific else "event_start_date <= observation_date <= label_maturity_date"),
            "unknown_and_censored": "excluded_from_target_fits",
        }),
        "feature_contract_sha256": canonical_sha({
            "groups": {name: spec["variants"] for name, spec in groups.items()},
            "feature_types": {name: FEATURE_TYPES.get(name, "finite_number")
                              for name in sorted({field for spec in groups.values()
                                                  for feature_set in spec["variants"].values()
                                                  for field in feature_set})},
            "missing_policy": "complete_common_support_across_all_variants_in_comparison_group",
            **({"H1": "D-only percent close-to-prior-close and range-to-open; D-to-prior20 RAW "
                      "volume and amount; D candle-body, wick and close-location fractions; "
                      "zero range maps to (0,0,0,0.5)"} if task_specific else {}),
        }),
        "evaluation_contract_sha256": canonical_sha({
            "groups": {name: spec["metrics"] for name, spec in groups.items()},
            "oof": "only_when_each_prediction_is_generated_by_a_model_excluding_that_sample",
            "development": "explicit_manifest_fold_membership",
            "same_package_sha_for_all_algorithms": True,
            **({"trading_cost_contract": "NO_RETURN_EVALUATION"} if task_specific else {}),
        }),
        "exclusion_policy_sha256": canonical_sha({
            "schema": "p515-exclusion-policy/1",
            "allowed_reason_codes": EXCLUSION_CODES,
            "unknown_partial_unmatured_future_pit_missing_feature_overlap_and_out_of_window_are_not_admitted": True,
            "one_assignment_or_one_exclusion_per_candidate_group": True,
        }),
    }


def digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_date(value: str, field: str) -> date:
    if not DATE_RE.fullmatch(value or ""):
        raise ValueError(f"{field} must use YYYYMMDD")
    return datetime.strptime(value, "%Y%m%d").date()


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp with timezone") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field} must include an explicit timezone")
    return result


def relative_bundle_file(root: Path, name: str) -> Path:
    candidate = Path(name)
    if candidate.is_absolute() or not name or ".." in candidate.parts:
        raise ValueError(f"Bundle paths must be relative and stay inside the bundle: {name!r}")
    resolved_root = root.resolve(strict=True)
    resolved = (root / candidate).resolve(strict=True)
    if resolved_root not in resolved.parents:
        raise ValueError(f"Bundle path escapes its root: {name!r}")
    if (root / candidate).is_symlink():
        raise ValueError(f"Symlinks are not accepted in the common bundle: {name!r}")
    return resolved


def read_csv(path: Path):
    return read_csv_bytes(path.read_bytes())


def key_for(row):
    return tuple((row.get(field) or "").strip() for field in KEY)


def sample_id(row):
    identity = "\0".join(key_for(row)).encode("utf-8")
    return digest_bytes(identity)


def validate_sha(value, name):
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def is_identifier(value):
    return isinstance(value, str) and bool(SAFE_ID_RE.fullmatch(value)) and ".." not in value and value.upper() not in PLACEHOLDERS


def synthetic_marker(value):
    return "SYNTHETIC" in str(value).upper()


def numeric_value(raw, field):
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    return value


def read_raw_prefix(raw, row, observation):
    header, bars = read_csv_bytes(raw)
    if set(header) != {*RAW_COLUMNS, "ts_code"} or not bars:
        raise ValueError("RAW prefix must contain only security, trade date and OHLCVA")
    if row["price_basis"] != RAW_PRICE_BASIS:
        raise ValueError("D-only prefix requires RAW_UNADJUSTED price basis")
    if not row["raw_prefix_row_count"].isascii() or not row["raw_prefix_row_count"].isdigit() or int(row["raw_prefix_row_count"]) != len(bars):
        raise ValueError("RAW prefix row count differs from the sample declaration")
    dates = []
    values = []
    for bar in bars:
        if bar["ts_code"] != row["stable_security_id"]:
            raise ValueError("RAW prefix security identity conflict")
        bar_date = parse_date(bar["trade_date"], "RAW prefix trade_date")
        if bar_date > observation:
            raise ValueError("RAW prefix includes a bar after D")
        if dates and bar_date <= dates[-1]:
            raise ValueError("RAW prefix trading dates must strictly increase")
        dates.append(bar_date)
        opened, high, low, closed, volume, amount = (
            numeric_value(bar[field], f"RAW prefix {field}") for field in RAW_COLUMNS[1:]
        )
        if not (0 < low <= min(opened, closed) <= max(opened, closed) <= high) or volume < 0 or amount < 0:
            raise ValueError("RAW prefix violates OHLCVA integrity")
        values.append((opened, high, low, closed, volume, amount))
    if dates[-1] != observation or parse_date(row["raw_prefix_max_date"], "raw_prefix_max_date") != observation:
        raise ValueError("RAW prefix must end at the declared observation date")
    return dates, values


def h1_features_from_raw(values):
    if len(values) < 21:
        raise ValueError("H1 PRICE requires at least 20 prior RAW bars")
    opened, high, low, closed, volume, amount = values[-1]
    prior = values[-21:-1]
    prior_mean_volume = sum(bar[4] for bar in prior) / 20
    prior_mean_amount = sum(bar[5] for bar in prior) / 20
    if prior_mean_volume <= 0 or prior_mean_amount <= 0:
        raise ValueError("H1 PRICE requires positive prior mean RAW volume and amount")
    bar_range = high - low
    expected = [
        100 * (closed / values[-2][3] - 1),
        100 * bar_range / opened,
        volume / prior_mean_volume,
        amount / prior_mean_amount,
    ]
    expected.extend([
        abs(closed - opened) / bar_range,
        (high - max(opened, closed)) / bar_range,
        (min(opened, closed) - low) / bar_range,
        (closed - low) / bar_range,
    ] if bar_range else [0.0, 0.0, 0.0, 0.5])
    return dict(zip(PRICE + H1_STRUCTURE, expected))


def group_key(row, task_specific):
    return row["sample_id"] if task_specific else sample_id(row)


class TaskEvidence:
    """Read and bind R1.3 evidence to exact sample, group and source fields."""

    def __init__(self, paths, plan_author):
        self.paths = paths
        self.plan_author = plan_author.casefold()
        self.prefix_cache = {}
        self.table_cache = {}

    def content(self, kind, digest):
        if digest not in self.paths[kind]:
            raise ValueError(f"Sample lacks hash-bound {kind} evidence")
        path = self.paths[kind][digest]
        raw = path.read_bytes()
        if digest_bytes(raw) != digest:
            raise ValueError(f"{kind} evidence changed after manifest validation")
        return raw

    def table(self, kind, digest, fields, key_fields):
        cache_key = (kind, digest)
        if cache_key not in self.table_cache:
            header, rows = read_csv_bytes(self.content(kind, digest))
            if set(header) != set(fields):
                raise ValueError(f"Invalid {kind} evidence CSV columns")
            lookup = {}
            for evidence in rows:
                key = tuple(evidence[field] for field in key_fields)
                lookup.setdefault(key, []).append(evidence)
            self.table_cache[cache_key] = lookup
        return self.table_cache[cache_key]

    def exact_binding(self, kind, digest, fields, row, additional_fields=()):
        table = self.table(kind, digest, (*fields, *additional_fields), ("sample_id",))
        records = table.get((row["sample_id"],), [])
        if len(records) != 1 or any(records[0][field] != row[field] for field in fields):
            raise ValueError(f"Missing, duplicate or mismatched sample-bound {kind} record")
        return records[0]

    def verify_raw_prefix(self, row, observation):
        sid = row["sample_id"]
        if sid not in self.prefix_cache:
            raw = self.content("raw_prefix", row["raw_prefix_sha256"])
            self.prefix_cache[sid] = read_raw_prefix(raw, row, observation)
        return self.prefix_cache[sid]

    def verify_observation(self, row, observation):
        for field, expected in STATUS_CERTIFIED.items():
            if field != "sector_pit_status" and row[field] != expected:
                raise ValueError(f"{field} must be {expected} for a frozen supervised sample")
        if not is_identifier(row["volume_unit"]) or not is_identifier(row["amount_unit"]):
            raise ValueError("RAW volume and amount units must be explicitly certified")
        self.exact_binding(
            "observation_certification", row["observation_evidence_sha256"], OBSERVATION_EVIDENCE_FIELDS, row,
        )
        return self.verify_raw_prefix(row, observation)

    def verify_judgment(self, row, group_name, group):
        table = self.table(
            "independent_label_adjudication", row["label_source_sha256"], JUDGMENT_FIELDS,
            ("sample_id", "comparison_group_id"),
        )
        matches = table.get((row["sample_id"], group_name), [])
        if len(matches) != 1:
            raise ValueError("No unique sample/group independent adjudication")
        judgment = matches[0]
        target = group["target"]
        if any(judgment[field] != row[field] for field in (*OBSERVATION_KEY, "label_maturity_date")):
            raise ValueError("Independent adjudication identity or maturity conflicts with the sample")
        judges = judgment["judge_a"].casefold(), judgment["judge_b"].casefold()
        if (not all(is_identifier(value) for value in judges) or judges[0] == judges[1]
                or self.plan_author in judges):
            raise ValueError("Adjudication requires two distinct independent judges")
        if (judgment["target_name"] != target or judgment["target_value"] != row[target]
                or not judgment["judge_a_value"].strip() or not judgment["judge_b_value"].strip()
                or any(judgment[field].strip().upper() in PLACEHOLDERS for field in ("judge_a_value", "judge_b_value"))):
            raise ValueError("Adjudicated target value conflicts with the sample")
        if judgment["judge_a_value"] == judgment["judge_b_value"]:
            if judgment["resolution_status"] != "AGREED" or judgment["judge_a_value"] != row[target]:
                raise ValueError("Agreed judgments must match the resolved target")
        else:
            arbitrator = judgment["arbitrator"].casefold()
            if (judgment["resolution_status"] != "ARBITRATED" or not is_identifier(arbitrator)
                    or arbitrator in {*judges, self.plan_author}):
                raise ValueError("Conflicting judgments require an independent arbitrator")

    def verify_event(self, row, observation, maturity, decision, dates, h1=False):
        if row["event_identity_status"] == "NO_REAL_EVENT":
            if not h1:
                raise ValueError("H2/H3/H4 require a certified raw root and actual wave")
            return
        if row["event_identity_status"] != "CERTIFIED_REAL_EVENT" or not is_identifier(row["event_id"]):
            raise ValueError("An assigned event identity must be certified or explicitly NO_REAL_EVENT")
        if not h1 and not all(is_identifier(row[field]) for field in ("raw_root_anchor_id", "wave_id", "support_role")):
            raise ValueError("H2/H3/H4 require a certified raw root, actual wave and traceable support role")
        evidence_fields = EVENT_EVIDENCE_FIELDS[:5] if h1 else EVENT_EVIDENCE_FIELDS
        lineage = self.exact_binding(
            "event_lineage", row["event_lineage_sha256"], evidence_fields, row, ("identity_available_at",),
        )
        event_start = parse_date(row["event_start_date"], "event_start_date")
        if event_start > observation or parse_timestamp(lineage["identity_available_at"], "event identity available_at") > decision:
            raise ValueError("Event identity is outside its D cutoff")
        if h1:
            return
        if row["root_anchor_id"].upper() not in PLACEHOLDERS and row["root_anchor_id"] != row["raw_root_anchor_id"]:
            raise ValueError("Generic root anchor conflicts with the authenticated raw root")
        raw_root, attack_start, attack_end, pullback_start, pullback_end = (
            parse_date(row[field], field) for field in (
                "raw_root_anchor_date", "attack_start_date", "attack_end_date", "pullback_start_date", "pullback_end_date",
            )
        )
        if not (event_start <= attack_start <= raw_root <= attack_end < pullback_start <= observation <= pullback_end <= maturity):
            raise ValueError("H2 attack/root/pullback timing conflicts with D or label maturity")
        if not {raw_root, attack_start, attack_end, pullback_start}.issubset(dates):
            raise ValueError("H2 RAW prefix does not contain its pre-D lifecycle boundaries")

    def verify_history(self, row, observation, decision):
        table = self.table("same_role_history", row["same_role_history_sha256"], HISTORY_FIELDS, ("sample_id",))
        entries = table.get((row["sample_id"],), [])
        count = numeric_value(row["same_role_history_event_n"], "same_role_history_event_n")
        if not entries or len(entries) != count:
            raise ValueError("H3 requires certified same-role history for each counted event")
        events = set()
        roots = set()
        for entry in entries:
            event = entry["history_event_id"].casefold()
            root = entry["history_raw_root_anchor_id"].casefold()
            maturity = parse_date(entry["history_maturity_date"], "history_maturity_date")
            available = parse_timestamp(entry["available_at"], "history available_at")
            if (entry["stable_security_id"] != row["stable_security_id"] or entry["history_role"] != row["support_role"]
                    or entry["current_raw_root_anchor_id"] != row["raw_root_anchor_id"]
                    or not is_identifier(event) or not is_identifier(root) or event in events or root in roots
                    or event == row["event_id"].casefold() or root == row["raw_root_anchor_id"].casefold()
                    or maturity >= observation or maturity > available.astimezone(SHANGHAI).date()
                    or available > decision):
                raise ValueError("H3 same-role history lineage, maturity or available_at is invalid")
            events.add(event)
            roots.add(root)

    def verify_sector(self, row, observation, decision):
        if row["sector_pit_status"] != STATUS_CERTIFIED["sector_pit_status"]:
            raise ValueError("sector_pit_status must be VERIFIED_DATED for a sector comparison")
        table = self.table("sector_membership", row["sector_membership_sha256"], SECTOR_FIELDS, ("sample_id",))
        entries = table.get((row["sample_id"],), [])
        if len(entries) != 1:
            raise ValueError("Missing or duplicate same-sample historical sector membership")
        entry = entries[0]
        start = parse_date(entry["effective_from_date"], "industry effective_from_date")
        end = parse_date(entry["effective_to_date"], "industry effective_to_date") if entry["effective_to_date"] else date.max
        published = parse_timestamp(entry["published_at"], "industry published_at")
        available = parse_timestamp(entry["available_at"], "industry available_at")
        if (entry["stable_security_id"] != row["stable_security_id"]
                or not is_identifier(entry["industry_id"]) or not is_identifier(entry["classification_version"])
                or not start <= observation <= end or not published <= available <= decision):
            raise ValueError("Sector membership version or PIT publication/availability is invalid")

    def verify_features(self, row, group_name, features, feature_at):
        table = self.table(
            "historical_pit_and_features", row["feature_evidence_sha256"], FEATURE_EVIDENCE_FIELDS,
            ("sample_id", "comparison_group_id"),
        )
        entries = table.get((row["sample_id"], group_name), [])
        if len(entries) != 1:
            raise ValueError("Missing or duplicate sample/group PIT feature certification")
        entry = entries[0]
        if (any(entry[key] != row[key] for key in OBSERVATION_KEY)
                or entry["feature_values_sha256"] != canonical_sha({field: row[field] for field in sorted(features)})
                or parse_timestamp(entry["available_at"], "feature certification available_at") != feature_at):
            raise ValueError("PIT feature certification does not bind the exact sample values and available_at")


def validate_manifest(manifest_path: Path, approved_manifest_sha256: str, *, allow_synthetic=False):
    manifest_path = manifest_path.resolve(strict=True)
    root = manifest_path.parent
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = digest_bytes(manifest_bytes)
    validate_sha(approved_manifest_sha256, "approved manifest SHA")
    if manifest_sha != approved_manifest_sha256:
        raise ValueError("Approved manifest SHA does not match the exact manifest bytes")
    manifest = json.loads(manifest_bytes)
    task_specific = manifest.get("schema") == TASK_SCHEMA
    if manifest.get("schema") not in {SCHEMA, TASK_SCHEMA} or manifest.get("market") != "A_SHARE":
        raise ValueError("Unsupported schema or market; expected p515-common-training/1 or /2 A_SHARE")
    if manifest.get("fit_authorized") is not False:
        raise ValueError("The common intake manifest must explicitly set fit_authorized=false")
    if manifest.get("sealed_test_material_present") is not False:
        raise ValueError("Sealed test material cannot be present in a common intake bundle")
    if task_specific:
        scope = manifest.get("input_scope")
        if scope not in {"FROZEN_SUPERVISED", "ADJUDICATION_PREPARATION", "SYNTHETIC_ONLY"}:
            raise ValueError("R1.3 input_scope must declare the intended intake boundary")
        if scope == "SYNTHETIC_ONLY" and allow_synthetic is not True:
            raise ValueError("SYNTHETIC_ONLY is confined to the synthetic harness")
        if manifest.get("trading_cost_contract") != "NO_RETURN_EVALUATION":
            raise ValueError("R1.3 compares classification/regression, without trading return or fee evaluation")

    provenance = manifest.get("provenance", {})
    plan_author = str(provenance.get("plan_author", "")).strip()
    reviewer = str(provenance.get("independent_reviewer", "")).strip()
    is_preparation = task_specific and scope == "ADJUDICATION_PREPARATION"
    if not plan_author or (not is_preparation and not reviewer) or plan_author.casefold() == reviewer.casefold():
        raise ValueError("Manifest must record distinct plan author and independent reviewer roles")
    if task_specific and scope == "FROZEN_SUPERVISED" and any(
        synthetic_marker(value) for value in (manifest.get("dataset_id"), plan_author, reviewer)
    ):
        raise ValueError("FROZEN_SUPERVISED cannot use known synthetic identities")
    for field in ("label_contract_sha256", "feature_contract_sha256", "evaluation_contract_sha256",
                  "exclusion_policy_sha256", "exclusion_ledger_sha256"):
        validate_sha(manifest.get(field), field)
    expected_contracts = contract_hashes(task_specific)
    if any(manifest[field] != expected for field, expected in expected_contracts.items()):
        raise ValueError("A label, feature, evaluation or exclusion policy SHA differs from the local contract")

    frozen = parse_timestamp(manifest.get("frozen_at_utc"), "frozen_at_utc")
    if frozen.utcoffset().total_seconds() != 0:
        raise ValueError("frozen_at_utc must use UTC")
    if is_preparation:
        if any(manifest.get(field) is not None for field in ("windows", "pit_cutoff_date", "development_label_cutoff")):
            raise ValueError("Adjudication preparation cannot declare frozen supervised windows or cutoffs")
    else:
        pit_cutoff = parse_date(manifest.get("pit_cutoff_date"), "pit_cutoff_date")
        label_cutoff = parse_date(manifest.get("development_label_cutoff"), "development_label_cutoff")
        windows = manifest.get("windows", {})
        train_start = parse_date(windows.get("train_start"), "windows.train_start")
        train_end = parse_date(windows.get("train_end"), "windows.train_end")
        dev_start = parse_date(windows.get("development_start"), "windows.development_start")
        dev_end = parse_date(windows.get("development_end"), "windows.development_end")
        if not train_start <= train_end < dev_start <= dev_end <= pit_cutoff:
            raise ValueError("Train, development and PIT windows must be ordered and non-overlapping")
        if label_cutoff < dev_end:
            raise ValueError("Development label maturity cutoff must be on or after the development window")

    groups = manifest.get("groups")
    expected = expected_groups(task_specific)
    if not isinstance(groups, dict) or set(groups) != set(expected):
        raise ValueError("Manifest must define exactly the six H1/H2/H3/H4 comparison groups")
    for group_name, group_spec in expected.items():
        if groups[group_name] != group_spec:
            raise ValueError(f"Feature, target or metric contract differs for {group_name}")

    evidence_rows = manifest.get("evidence")
    if not isinstance(evidence_rows, list):
        raise ValueError("Manifest must bind same-bundle label and PIT evidence")
    evidence_kinds = {"independent_label_adjudication", "historical_pit_and_features"}
    if task_specific:
        evidence_kinds |= TASK_EVIDENCE_TYPES
    evidence_paths = {kind: {} for kind in evidence_kinds}
    seen_evidence_hashes = set()
    for item in evidence_rows:
        kind = item.get("kind")
        if kind not in evidence_paths:
            raise ValueError("Evidence kind is outside the common training contract")
        owner = str(item.get("owner", "")).strip()
        reviewed_by = str(item.get("reviewed_by", "")).strip()
        evidence_path = relative_bundle_file(root, item.get("path", ""))
        expected_sha = item.get("sha256", "")
        validate_sha(expected_sha, f"evidence[{kind}].sha256")
        if not owner or digest_file(evidence_path) != expected_sha:
            raise ValueError("Evidence must be same-bundle hash-bound, independently owned and reviewed after freeze")
        if is_preparation:
            if kind != "raw_prefix" or item.get("status") != "SOURCE_SHA_VERIFIED":
                raise ValueError("Preparation evidence permits only exact SOURCE_SHA_VERIFIED RAW objects")
        else:
            reviewed_at = parse_timestamp(item.get("reviewed_at_utc"), f"evidence[{kind}].reviewed_at_utc")
            if (not reviewed_by or owner.casefold() in {plan_author.casefold(), reviewer.casefold()}
                    or reviewed_by.casefold() != reviewer.casefold() or reviewed_at <= frozen):
                raise ValueError("Evidence must be same-bundle hash-bound, independently owned and reviewed after freeze")
        if expected_sha in evidence_paths[kind] or (task_specific and expected_sha in seen_evidence_hashes):
            raise ValueError("Repeated evidence SHA is not allowed")
        evidence_paths[kind][expected_sha] = evidence_path
        seen_evidence_hashes.add(expected_sha)
    evidence_hashes = {kind: set(paths) for kind, paths in evidence_paths.items()}
    if not task_specific and any(not values for values in evidence_hashes.values()):
        raise ValueError("Both independent label adjudication and historical PIT/feature evidence are required")
    if evidence_hashes["independent_label_adjudication"] & evidence_hashes["historical_pit_and_features"]:
        raise ValueError("Label and feature certification must refer to distinct evidence bytes")

    files = manifest.get("files", {})
    if set(files) != {"samples", "fold_assignments", "exclusions"}:
        raise ValueError("Bundle must bind samples, fold_assignments and local exclusions CSV files")
    loaded = {}
    for name, entry in files.items():
        path = relative_bundle_file(root, entry.get("path", ""))
        expected_sha = entry.get("sha256", "")
        validate_sha(expected_sha, f"files.{name}.sha256")
        raw = path.read_bytes()
        if digest_bytes(raw) != expected_sha:
            raise ValueError(f"{name} SHA mismatch")
        header, rows = read_csv_bytes(raw)
        if len(rows) != entry.get("row_count"):
            raise ValueError(f"{name} row count differs from the manifest")
        loaded[name] = (path, header, rows, expected_sha)

    sample_header, sample_rows = loaded["samples"][1:3]
    required_sample_header = set(sample_columns(task_specific))
    if not required_sample_header.issubset(sample_header):
        missing = sorted(required_sample_header - set(sample_header))
        raise ValueError(f"samples.csv is missing contracted columns: {missing}")
    if set(sample_header) != required_sample_header:
        raise ValueError("samples.csv includes fields outside the common contract allowlist")

    samples_by_id = {}
    natural_keys = set()
    for row in sample_rows:
        fields = OBSERVATION_KEY if task_specific else KEY
        key = tuple(row[field] for field in fields)
        if any(not value for value in key) or not SECURITY_RE.fullmatch(key[0]):
            raise ValueError("Every sample row must carry a stable six-digit A-share key and required identity fields")
        if any(row[field] != row[field].strip() for field in fields):
            raise ValueError("Security, date and event key values cannot contain surrounding whitespace")
        identity_text = (row["event_id"], row.get("root_anchor_id", ""), row.get("wave_id", ""))
        if task_specific:
            if scope == "FROZEN_SUPERVISED" and any(synthetic_marker(value) for value in (sid, row["label_source"])):
                raise ValueError("FROZEN_SUPERVISED cannot use known synthetic sample or label IDs")
            identity_text += (row["raw_root_anchor_id"], row["support_role"])
        invalid_identity = (any(value.upper() not in PLACEHOLDERS and not is_identifier(value) for value in identity_text)
                            if task_specific else
                            any(value != value.strip() or re.match(r"^[=+@-]", value) or "/" in value or "\\" in value
                                or "://" in value or ".." in value for value in identity_text))
        if invalid_identity:
            raise ValueError("Event/root/wave IDs must be canonical identifiers without path or formula syntax")
        parse_date(key[1], "observation_date")
        if key in natural_keys:
            raise ValueError("Duplicate natural sample key in samples.csv")
        natural_keys.add(key)
        sid = group_key(row, task_specific)
        if not is_identifier(sid) or sid in samples_by_id:
            raise ValueError("Samples must have a unique opaque sample_id")
        if task_specific:
            if row["exposure_status"] not in {"EXPOSED_DEV", "UNEXPOSED", "UNKNOWN"}:
                raise ValueError("Invalid sample exposure_status")
            for field, expected_status in STATUS_CERTIFIED.items():
                accepted = {expected_status, "UNKNOWN", "CONFLICT", "NOT_APPLICABLE"}
                if is_preparation and field in PREPARATION_STATUS:
                    accepted.add(PREPARATION_STATUS[field])
                if row[field] not in accepted:
                    raise ValueError(f"Invalid {field} value")
            if row["event_identity_status"] not in {"NO_REAL_EVENT", "CERTIFIED_REAL_EVENT", "UNKNOWN"}:
                raise ValueError("Invalid event_identity_status")
            if row["event_identity_status"] == "NO_REAL_EVENT":
                no_event_fields = (*EVENT_EVIDENCE_FIELDS[4:], "root_anchor_id", "event_lineage_sha256")
                if row["event_id"] or any(row[field].upper() not in PLACEHOLDERS for field in no_event_fields):
                    raise ValueError("H1 NO_REAL_EVENT requires blank event_id and no invented event lineage")
        samples_by_id[sid] = row

    fold_header, fold_rows = loaded["fold_assignments"][1:3]
    if set(fold_header) != set(FOLD_FIELDS):
        raise ValueError("fold_assignments.csv must contain only sample_id, group, fold and partition")
    memberships = {}
    fold_cohorts = {}
    for row in fold_rows:
        group_name = row["comparison_group_id"]
        fold_id = row["fold_id"]
        partition = row["partition"]
        if group_name not in expected or not re.fullmatch(r"F[1-9]\d*", fold_id or "") or partition not in {"train", "dev"}:
            raise ValueError("Invalid comparison group, fold ID or partition")
        sid = row["sample_id"]
        if sid not in samples_by_id:
            raise ValueError("Fold assignment references a sample absent from samples.csv")
        membership_key = (group_name, fold_id, sid)
        if membership_key in memberships:
            raise ValueError("Duplicate group/fold/sample assignment")
        memberships[membership_key] = partition
        fold_cohorts.setdefault((group_name, fold_id, partition), []).append(samples_by_id[sid])

    group_folds = {(group, fold) for group, fold, _ in fold_cohorts}
    if not group_folds and sample_rows and not task_specific:
        raise ValueError("Candidate samples require explicit memberships or exclusion reasons")
    if is_preparation and group_folds:
        raise ValueError("Adjudication preparation cannot carry train/development assignments")
    if task_specific and not group_folds and not is_preparation:
        raise ValueError("Frozen supervised intake requires explicit train/development assignments")
    task_evidence = TaskEvidence(evidence_paths, plan_author) if task_specific else None
    if is_preparation:
        for row in sample_rows:
            if any(row[field] not in {STATUS_CERTIFIED[field], status} for field, status in PREPARATION_STATUS.items()):
                raise ValueError("H1 preparation requires verified security identity and RAW integrity")
            if row["label_confidence"] not in {"UNKNOWN", "NOT_VERIFIED", "PENDING"} or any(
                row[target["target"]].upper() not in PLACEHOLDERS for target in expected.values()
            ):
                raise ValueError("Adjudication preparation must not carry resolved target labels")
            task_evidence.verify_raw_prefix(row, parse_date(row["observation_date"], "observation_date"))
    for group_name in expected:
        fold_ids = sorted({fold for group, fold in group_folds if group == group_name}, key=lambda value: int(value[1:]))
        if fold_ids and fold_ids != [f"F{index}" for index in range(1, len(fold_ids) + 1)]:
            raise ValueError(f"Fold IDs for {group_name} must be ordered and contiguous from F1")
        previous_dev_end = None
        prior_dev_ids = set()
        prior_dev_events = set()
        prior_dev_roots = set()
        for fold_id in fold_ids:
            dev_ids = {sid for (group, fold, sid), role in memberships.items()
                       if group == group_name and fold == fold_id and role == "dev"}
            if prior_dev_ids & dev_ids:
                raise ValueError(f"A development sample is repeated across folds for {group_name}")
            prior_dev_ids |= dev_ids
            dev_rows = fold_cohorts.get((group_name, fold_id, "dev"), [])
            if not dev_rows:
                raise ValueError(f"Each {group_name}/{fold_id} needs development rows")
            if task_specific:
                dev_events = {(row["stable_security_id"], row["event_id"].casefold()) for row in dev_rows
                              if is_identifier(row["event_id"])}
                dev_roots = {(row["stable_security_id"], row["raw_root_anchor_id"].casefold()) for row in dev_rows
                             if is_identifier(row["raw_root_anchor_id"])}
                if prior_dev_events & dev_events or prior_dev_roots & dev_roots:
                    raise ValueError("Same-security event or raw root reused across development folds")
                prior_dev_events.update(dev_events)
                prior_dev_roots.update(dev_roots)
            current_start = min(parse_date(row["observation_date"], "observation_date") for row in dev_rows)
            current_end = max(parse_date(row["observation_date"], "observation_date") for row in dev_rows)
            if previous_dev_end is not None and current_start <= previous_dev_end:
                raise ValueError(f"Development folds for {group_name} must have strictly ordered dates")
            previous_dev_end = current_end
    for group_name, fold_id in group_folds:
        train_rows = fold_cohorts.get((group_name, fold_id, "train"), [])
        dev_rows = fold_cohorts.get((group_name, fold_id, "dev"), [])
        if not train_rows or not dev_rows:
            raise ValueError(f"Each {group_name}/{fold_id} needs both train and development rows")
        dev_dates = [parse_date(row["observation_date"], "observation_date") for row in dev_rows]
        first_dev_date = min(dev_dates)
        root_field = "raw_root_anchor_id" if task_specific else "root_anchor_id"
        train_security_roots = {(row["stable_security_id"].casefold(), row[root_field].casefold()) for row in train_rows
                                if row[root_field].upper() not in PLACEHOLDERS}
        train_security_events = {(row["stable_security_id"].casefold(), row["event_id"].casefold()) for row in train_rows
                                 if row["event_id"].upper() not in PLACEHOLDERS}
        dev_security_roots = {(row["stable_security_id"].casefold(), row[root_field].casefold()) for row in dev_rows
                              if row[root_field].upper() not in PLACEHOLDERS}
        dev_security_events = {(row["stable_security_id"].casefold(), row["event_id"].casefold()) for row in dev_rows
                               if row["event_id"].upper() not in PLACEHOLDERS}
        if train_security_roots & dev_security_roots or train_security_events & dev_security_events:
            raise ValueError(f"Same-security root/event overlap in {group_name}/{fold_id}")
        dev_start_by_security = {}
        for row in dev_rows:
            security = row["stable_security_id"]
            event_start = (parse_date(row["observation_date"], "observation_date")
                           if task_specific and row["event_identity_status"] == "NO_REAL_EVENT"
                           else parse_date(row["event_start_date"], "event_start_date"))
            dev_start_by_security[security] = min(dev_start_by_security.get(security, event_start), event_start)
        for role, role_rows in (("train", train_rows), ("dev", dev_rows)):
            for row in role_rows:
                group = expected[group_name]
                obs_date = parse_date(row["observation_date"], "observation_date")
                maturity = parse_date(row["label_maturity_date"], "label_maturity_date")
                event_start = (obs_date if task_specific and row["event_identity_status"] == "NO_REAL_EVENT"
                               else parse_date(row["event_start_date"], "event_start_date"))
                if row["label_confidence"] != "VERIFIED":
                    raise ValueError(f"Only independently VERIFIED labels may be assigned to {group_name}/{fold_id}")
                if task_specific:
                    if row["exposure_status"] != "UNEXPOSED":
                        raise ValueError("EXPOSED_DEV and unknown exposure cannot enter frozen supervised folds")
                else:
                    if row["PIT_status"] != "VERIFIED_DATED":
                        raise ValueError(f"Only PIT-verified legacy rows may be assigned to {group_name}/{fold_id}")
                    if row["root_anchor_id"].upper() in PLACEHOLDERS or row["wave_id"].upper() in PLACEHOLDERS:
                        raise ValueError(f"Root and wave identities must be resolved for {group_name}/{fold_id}")
                if not row["label_source"].strip():
                    raise ValueError("An admitted row must carry label_source")
                if row["label_source_sha256"] not in evidence_hashes["independent_label_adjudication"]:
                    raise ValueError("Label source SHA is not an exact same-bundle adjudication evidence SHA")
                if ((not task_specific or group_name != "H1_PHASE")
                        and row["feature_evidence_sha256"] not in evidence_hashes["historical_pit_and_features"]):
                    raise ValueError("Feature evidence SHA is not an exact same-bundle PIT evidence SHA")
                if event_start > obs_date or maturity < obs_date or obs_date > pit_cutoff or maturity > label_cutoff:
                    raise ValueError("Event, label-maturity or PIT date is outside the common data contract")
                if role == "train":
                    if not (train_start <= obs_date <= train_end) or not maturity < first_dev_date:
                        raise ValueError(f"Training sample is outside its window or matures too late for {group_name}/{fold_id}")
                    dev_event_start = dev_start_by_security.get(row["stable_security_id"])
                    if dev_event_start and maturity >= dev_event_start:
                        raise ValueError("Training label interval overlaps a same-security development event")
                elif not (dev_start <= obs_date <= dev_end):
                    raise ValueError("Development sample is outside the frozen development window")

                feature_at = parse_timestamp(row["feature_available_at"], "feature_available_at")
                decision_at = parse_timestamp(row["decision_at"], "decision_at")
                if feature_at > decision_at or decision_at.astimezone(SHANGHAI).date() != obs_date:
                    raise ValueError("Feature availability must precede the decision on its D date")
                if task_specific:
                    if feature_at.astimezone(SHANGHAI).replace(tzinfo=None) < datetime.combine(obs_date, time(15)):
                        raise ValueError("D-close RAW features cannot be available before D close")
                    dates, values = task_evidence.verify_observation(row, obs_date)
                    task_evidence.verify_event(row, obs_date, maturity, decision_at, dates, h1=group_name == "H1_PHASE")
                    task_evidence.verify_judgment(row, group_name, group)
                    if group_name == "H1_PHASE":
                        for field, expected_feature in h1_features_from_raw(values).items():
                            if not math.isclose(numeric_value(row[field], field), expected_feature,
                                                rel_tol=1e-9, abs_tol=1e-9):
                                raise ValueError(f"H1 feature {field} does not match the D-only RAW derivation")
                    if group_name == "H3_SUPPORT":
                        task_evidence.verify_history(row, obs_date, decision_at)
                    if group_name in {"H3_SUPPORT", "H4_SUPPORT"}:
                        task_evidence.verify_sector(row, obs_date, decision_at)

                target_value = (row.get(group["target"]) or "").strip()
                if not target_value or target_value.upper() in PLACEHOLDERS:
                    raise ValueError(f"UNKNOWN/empty labels cannot enter {group_name}/{fold_id}")
                if group["target_kind"] == "classification":
                    if target_value not in group["classes"]:
                        raise ValueError(f"Target is outside the frozen class mapping for {group_name}")
                    if group_name != "H1_PHASE" and row["pullback_label"] not in {"SUCCESS", "FAILURE"}:
                        raise ValueError("Pullback tasks require a resolved SUCCESS or FAILURE label")
                else:
                    try:
                        value = float(target_value)
                    except ValueError as error:
                        raise ValueError(f"Regression target must be numeric for {group_name}") from error
                    if not math.isfinite(value) or value < 0:
                        raise ValueError(f"Regression target must be finite and nonnegative for {group_name}")
                    if group["target"].startswith("sessions_") and not value.is_integer():
                        raise ValueError("Session-count target must be an integer")
                    if row["pullback_label"] not in {"SUCCESS", "FAILURE"}:
                        raise ValueError("Pullback regression tasks require a resolved SUCCESS or FAILURE label")
                group_features = {name for fs in group["variants"].values() for name in fs}
                for feature in group_features:
                    try:
                        value = float(row[feature])
                    except (TypeError, ValueError) as error:
                        raise ValueError(f"Common comparison support has a missing/non-numeric feature {feature}") from error
                    if not math.isfinite(value):
                        raise ValueError(f"Common comparison support has a non-finite feature {feature}")
                    feature_type = FEATURE_TYPES.get(feature)
                    if feature_type == "binary_0_1" and value not in {0.0, 1.0}:
                        raise ValueError(f"Feature {feature} must be encoded as 0 or 1")
                    if feature_type == "nonnegative_integer" and (value < 0 or not value.is_integer()):
                        raise ValueError(f"Feature {feature} must be a nonnegative integer")
                if task_specific and group_name != "H1_PHASE":
                    task_evidence.verify_features(row, group_name, group_features, feature_at)

    assigned = {(group, sid) for group, _, sid in memberships}
    exclusion_header, exclusion_rows = loaded["exclusions"][1:3]
    if set(exclusion_header) != {"sample_id", "comparison_group_id", "exclusion_reason_code"}:
        raise ValueError("exclusions.csv must carry only sample_id, comparison_group_id and a reason code")
    excluded = set()
    exclusion_counts = {}
    for row in exclusion_rows:
        pair = (row["comparison_group_id"], row["sample_id"])
        if pair[0] not in expected or pair[1] not in samples_by_id:
            raise ValueError("Exclusion row references an unknown group or sample")
        if row["exclusion_reason_code"] not in EXCLUSION_CODES:
            raise ValueError("Exclusion reason must use a frozen reason code")
        if pair in excluded or pair in assigned:
            raise ValueError("A group/sample pair cannot be duplicated or both assigned and excluded")
        excluded.add(pair)
        exclusion_counts[row["exclusion_reason_code"]] = exclusion_counts.get(row["exclusion_reason_code"], 0) + 1
    expected_pairs = {(group_name, sid) for group_name in expected for sid in samples_by_id}
    if assigned | excluded != expected_pairs or assigned & excluded:
        raise ValueError("Every candidate/group pair needs exactly one train/dev assignment or exclusion reason")
    if manifest.get("exclusion_ledger_sha256") != loaded["exclusions"][3]:
        raise ValueError("Exclusion ledger SHA must bind the same-bundle exclusions.csv bytes")
    if manifest.get("exclusion_summary") != {"row_count": len(exclusion_rows), "by_reason": exclusion_counts}:
        raise ValueError("Exclusion summary must match the complete same-bundle reason-code ledger")
    group_counts = {group_name: {} for group_name in expected}
    for group_name, fold_id in sorted(group_folds):
        train_rows = fold_cohorts[(group_name, fold_id, "train")]
        dev_rows = fold_cohorts[(group_name, fold_id, "dev")]
        group_counts.setdefault(group_name, {})[fold_id] = {
            "train_rows": len(train_rows), "train_securities": len({r["stable_security_id"] for r in train_rows}),
            "train_events": len({(r["stable_security_id"], r["event_id"]) for r in train_rows
                                 if r["event_id"].upper() not in PLACEHOLDERS}),
            "train_dates": len({r["observation_date"] for r in train_rows}),
            "development_rows": len(dev_rows), "development_securities": len({r["stable_security_id"] for r in dev_rows}),
            "development_events": len({(r["stable_security_id"], r["event_id"]) for r in dev_rows
                                       if r["event_id"].upper() not in PLACEHOLDERS}),
            "development_dates": len({r["observation_date"] for r in dev_rows}),
            **({
                "train_eventless_rows": sum(r["event_id"].upper() in PLACEHOLDERS for r in train_rows),
                "development_eventless_rows": sum(r["event_id"].upper() in PLACEHOLDERS for r in dev_rows),
            } if task_specific else {}),
        }

    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha,
        "files": loaded,
        "samples_by_id": samples_by_id,
        "memberships": memberships,
        "group_counts": group_counts,
        "assigned": assigned,
        "candidate_rows": len(sample_rows),
        "assigned_group_sample_count": len(assigned),
        "excluded_group_sample_count": len(excluded),
        "exclusion_counts": exclusion_counts,
        "evidence_hashes": evidence_hashes,
    }


def csv_bytes(header, rows):
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=header, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def safe_export_payload(bundle, *, allow_synthetic=False):
    source = bundle["manifest"]
    task_specific = source["schema"] == TASK_SCHEMA
    if task_specific and source["input_scope"] != "FROZEN_SUPERVISED":
        if source["input_scope"] != "SYNTHETIC_ONLY" or allow_synthetic is not True:
            raise ValueError("Portable supervised export requires a frozen supervised bundle")
    dataset_id = str(source.get("dataset_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", dataset_id) or dataset_id in {".", ".."}:
        raise ValueError("dataset_id must be a short identifier without paths or free text")
    samples_by_id = bundle["samples_by_id"]
    memberships = bundle["memberships"]
    groups = source["groups"]
    export_files = {}
    exported_folds = []
    for (group_name, fold_id, sid), partition in sorted(memberships.items()):
        exported_folds.append({
            "sample_id": sid, "comparison_group_id": group_name,
            "fold_id": fold_id, "partition": partition,
        })
    for group_name in sorted(groups):
        spec = groups[group_name]
        group_features = sorted({feature for feature_set in spec["variants"].values() for feature in feature_set})
        group_sids = sorted({sid for group, sid in bundle["assigned"] if group == group_name})
        keys = KEY + IDENTITY_FIELDS
        if task_specific:
            keys = OBSERVATION_KEY + TASK_EXPORT_FIELDS
            if group_name != "H1_PHASE":
                keys += tuple(field for field in EVENT_EVIDENCE_FIELDS[2:] if field != "pullback_end_date")
                keys += ("event_lineage_sha256",)
            if group_name == "H3_SUPPORT":
                keys += ("same_role_history_sha256",)
            if group_name in {"H3_SUPPORT", "H4_SUPPORT"}:
                keys += ("sector_membership_sha256",)
            keys = tuple(dict.fromkeys(keys))
        header = ["sample_id", "comparison_group_id", *keys, spec["target"], *group_features]
        rows = []
        for sid in group_sids:
            row = samples_by_id[sid]
            result = {"sample_id": sid, "comparison_group_id": group_name}
            result.update({field: row[field] for field in keys})
            result[spec["target"]] = row[spec["target"]]
            result.update({feature: row[feature] for feature in group_features})
            rows.append(result)
        file_name = f"COMMON_SAMPLES_{group_name}.csv"
        export_files[file_name] = csv_bytes(header, rows)
    fold_bytes = csv_bytes(list(FOLD_FIELDS), exported_folds)
    output_manifest = {
        "schema": "p515-gemini-export/2" if task_specific else "p515-gemini-export/1",
        "dataset_id": dataset_id,
        "market": "A_SHARE",
        "source_manifest_sha256": bundle["manifest_sha256"],
        "common_package_contract_sha256": canonical_sha(source),
        "label_contract_sha256": source["label_contract_sha256"],
        "feature_contract_sha256": source["feature_contract_sha256"],
        "evaluation_contract_sha256": source["evaluation_contract_sha256"],
        "exclusion_policy_sha256": source["exclusion_policy_sha256"],
        "exclusion_ledger_sha256": source["exclusion_ledger_sha256"],
        "windows": source["windows"],
        "pit_cutoff_date": source["pit_cutoff_date"],
        "development_label_cutoff": source["development_label_cutoff"],
        "groups": source["groups"],
        "candidate_row_count": bundle["candidate_rows"],
        "assigned_group_sample_count": bundle["assigned_group_sample_count"],
        "excluded_group_sample_count": bundle["excluded_group_sample_count"],
        "exclusion_counts": bundle["exclusion_counts"],
        "group_fold_counts": bundle["group_counts"],
        "training_rows_only": True,
        "development_rows_only": True,
        "sealed_test_rows_included": False,
        "raw_evidence_files_included": False,
        "approval_files_included": False,
        "local_paths_or_credentials_included": False,
        "fit_count": 0,
        "preprocessing_fit_count": 0,
        "calibration_fit_count": 0,
        "prediction_calls": 0,
        "oof_status": "NOT_PRODUCED_NO_FIT",
        **({
            "input_scope": source["input_scope"],
            "trading_cost_contract": source["trading_cost_contract"],
            "algorithm_inputs": "Use only features listed for the selected comparison group and variant.",
        } if task_specific else {}),
        "files": {name: {"sha256": digest_bytes(content), "row_count": len(read_csv_bytes(content)[1])}
                  for name, content in export_files.items()},
    }
    output_manifest["files"]["COMMON_FOLD_ASSIGNMENTS.csv"] = {
        "sha256": digest_bytes(fold_bytes), "row_count": len(exported_folds),
    }
    manifest_bytes = (json.dumps(output_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    export_files["COMMON_FOLD_ASSIGNMENTS.csv"] = fold_bytes
    export_files["GEMINI_EXPORT_MANIFEST.json"] = manifest_bytes
    return export_files, output_manifest


def read_csv_bytes(content: bytes):
    from io import StringIO

    reader = csv.DictReader(StringIO(content.decode("utf-8-sig"), newline=""))
    header, rows = reader.fieldnames, list(reader)
    if not header or len(set(header)) != len(header):
        raise ValueError("CSV evidence has missing or duplicated headers")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("CSV evidence row width differs from the header")
    return header, rows


def write_export(bundle, output_dir: Path, *, allow_synthetic=False):
    output_dir = output_dir.absolute()
    if output_dir.exists():
        raise FileExistsError(f"Export destination already exists: {output_dir}")
    parent = output_dir.parent
    if not parent.is_dir():
        raise FileNotFoundError(f"Export parent must already exist: {parent}")
    files, summary = safe_export_payload(bundle, allow_synthetic=allow_synthetic)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=parent))
    try:
        for name, content in files.items():
            (temp_dir / name).write_bytes(content)
        zip_path = temp_dir / "P515_GEMINI_COMMON_TRAIN_DEV.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, content in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content)
        receipt = {
            "status": "PREPARED_LOCAL_ONLY_NOT_DELIVERED",
            "zip_sha256": digest_file(zip_path),
            "zip_bytes": zip_path.stat().st_size,
            "manifest_sha256": bundle["manifest_sha256"],
            "fit_count": 0,
            "prediction_calls": 0,
            "destination": str(output_dir),
        }
        (temp_dir / "EXPORT_RECEIPT.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temp_dir, output_dir)
        return receipt
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def build_synthetic_fixture(root: Path):
    """Build a non-market, non-fit fixture for exercising the intake and export gates."""
    root.mkdir(parents=True, exist_ok=False)
    expected = expected_groups()
    evidence = []
    evidence_sha = {}
    for kind, label in (("independent_label_adjudication", b"synthetic-only label adjudication"),
                        ("historical_pit_and_features", b"synthetic-only historical PIT evidence")):
        path = root / ("evidence_label.txt" if kind.startswith("independent_label") else "evidence_pit.txt")
        path.write_bytes(label)
        value = digest_file(path)
        evidence.append({
            "kind": kind, "path": path.name, "sha256": value,
            "owner": "Synthetic label adjudicator" if kind.startswith("independent_label") else "Synthetic PIT evidence owner",
            "reviewed_by": "Synthetic independent reviewer",
            "reviewed_at_utc": "2026-11-13T00:05:00Z",
        })
        evidence_sha[kind] = value

    features = sorted({field for group in expected.values() for variant in group["variants"].values() for field in variant})
    headers = list(dict.fromkeys(list(KEY) + list(IDENTITY_FIELDS) + [
        "event_start_date", "label_maturity_date", "label_source", "label_confidence",
        "PIT_status", "feature_available_at", "decision_at", "phase_label", "pullback_label",
    ] + [group["target"] for group in expected.values()] + features))
    rows = []
    folds = []
    for group_index, (group_name, group) in enumerate(expected.items()):
        for role, security, obs, event, maturity in (
            ("train", f"{group_index+1:06d}.SZ", "20260102", f"EVT_T_{group_index}", "20260105"),
            ("dev", f"{group_index+20:06d}.SH", "20260202", f"EVT_D_{group_index}", "20260205"),
        ):
            row = {field: "" for field in headers}
            row.update({
                "stable_security_id": security, "observation_date": obs, "event_id": event,
                "root_anchor_id": f"ROOT_{group_index}_{role}", "wave_id": f"WAVE_{group_index}_{role}",
                "event_start_date": obs, "label_maturity_date": maturity,
                "phase_label": "IGNITION" if role == "train" else "ADVANCE",
                "pullback_label": "SUCCESS" if role == "train" else "FAILURE",
                "label_source": "synthetic adjudication fixture",
                "label_source_sha256": evidence_sha["independent_label_adjudication"],
                "feature_evidence_sha256": evidence_sha["historical_pit_and_features"],
                "label_confidence": "VERIFIED", "PIT_status": "VERIFIED_DATED",
                "feature_available_at": f"{obs[:4]}-{obs[4:6]}-{obs[6:]}T14:00:00+08:00",
                "decision_at": f"{obs[:4]}-{obs[4:6]}-{obs[6:]}T15:00:00+08:00",
                "terminal_pullback_depth_pct": "1.25" if role == "train" else "2.5",
                "sessions_to_pullback_outcome": "3" if role == "train" else "5",
                "support_label": "SUPPORT_HELD" if role == "train" else "STRUCTURE_FAILURE",
            })
            for feature_index, feature in enumerate(features, start=1):
                feature_type = FEATURE_TYPES.get(feature)
                if feature_type == "binary_0_1":
                    row[feature] = "1"
                elif feature_type == "nonnegative_integer":
                    row[feature] = str(group_index + 1)
                else:
                    row[feature] = str((group_index + 1) * (feature_index + 1) / 10)
            rows.append(row)
            folds.append({"sample_id": sample_id(row), "comparison_group_id": group_name,
                          "fold_id": "F1", "partition": role})

    # This unassigned row carries a synthetic sentinel and must be filtered from the export.
    sentinel = dict(rows[0])
    sentinel.update({"stable_security_id": "000099.BJ", "observation_date": "20260203",
                     "event_id": "EXCLUDED_CANDIDATE", "phase_label": "EXCLUDED_SENTINEL",
                     "root_anchor_id": "UNKNOWN", "wave_id": "UNKNOWN", "label_confidence": "UNKNOWN"})
    rows.append(sentinel)

    sample_bytes = csv_bytes(headers, rows)
    fold_bytes = csv_bytes(list(FOLD_FIELDS), folds)
    admitted = {(row["comparison_group_id"], row["sample_id"]) for row in folds}
    exclusions = []
    for row in rows:
        sid = sample_id(row)
        for group_name in expected:
            pair = (group_name, sid)
            if pair not in admitted:
                reason = "UNKNOWN_LABEL" if row is sentinel else "NOT_ELIGIBLE_FOR_TASK"
                exclusions.append({"sample_id": sid, "comparison_group_id": group_name,
                                   "exclusion_reason_code": reason})
    exclusion_bytes = csv_bytes(["sample_id", "comparison_group_id", "exclusion_reason_code"], exclusions)
    (root / "samples.csv").write_bytes(sample_bytes)
    (root / "fold_assignments.csv").write_bytes(fold_bytes)
    (root / "exclusions.csv").write_bytes(exclusion_bytes)
    exclusion_counts = {}
    for row in exclusions:
        code = row["exclusion_reason_code"]
        exclusion_counts[code] = exclusion_counts.get(code, 0) + 1
    hashes = contract_hashes()
    manifest = {
        "schema": SCHEMA, "dataset_id": "SYNTHETIC_FIXTURE_ONLY", "market": "A_SHARE",
        "fit_authorized": False, "sealed_test_material_present": False,
        "frozen_at_utc": "2026-11-13T00:00:00Z",
        "pit_cutoff_date": "20260210", "development_label_cutoff": "20260210",
        "windows": {"train_start": "20260101", "train_end": "20260131",
                    "development_start": "20260201", "development_end": "20260209"},
        "provenance": {"plan_author": "Synthetic planner", "independent_reviewer": "Synthetic independent reviewer"},
        **hashes, "exclusion_ledger_sha256": digest_bytes(exclusion_bytes),
        "exclusion_summary": {"row_count": len(exclusions), "by_reason": exclusion_counts},
        "evidence": evidence,
        "files": {
            "samples": {"path": "samples.csv", "sha256": digest_bytes(sample_bytes), "row_count": len(rows)},
            "fold_assignments": {"path": "fold_assignments.csv", "sha256": digest_bytes(fold_bytes), "row_count": len(folds)},
            "exclusions": {"path": "exclusions.csv", "sha256": digest_bytes(exclusion_bytes), "row_count": len(exclusions)},
        },
        "groups": expected,
    }
    manifest_path = root / "COMMON_TRAINING_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path, digest_file(manifest_path)


def self_test():
    with tempfile.TemporaryDirectory(prefix="p515-common-synthetic-") as temp:
        root = Path(temp)
        fixture_dir = root / "fixture"
        manifest_path, manifest_sha = build_synthetic_fixture(fixture_dir)
        bundle = validate_manifest(manifest_path, manifest_sha)
        if bundle["candidate_rows"] != 13 or bundle["assigned_group_sample_count"] != 12:
            raise AssertionError("Synthetic admission counts did not match expected train/dev membership")
        output = root / "export"
        receipt = write_export(bundle, output)
        zip_path = output / "P515_GEMINI_COMMON_TRAIN_DEV.zip"
        with zipfile.ZipFile(zip_path) as archive:
            names = sorted(archive.namelist())
            expected_names = sorted([f"COMMON_SAMPLES_{group}.csv" for group in expected_groups()]
                                    + ["COMMON_FOLD_ASSIGNMENTS.csv", "GEMINI_EXPORT_MANIFEST.json"])
            if names != expected_names:
                raise AssertionError("Gemini export contains an unexpected file")
            payload = b"".join(archive.read(name) for name in names)
            if (b"EXCLUDED_SENTINEL" in payload or b"evidence_label.txt" in payload
                    or b"Synthetic independent reviewer" in payload or b"approval.json" in payload):
                raise AssertionError("An excluded label, evidence path or approval detail leaked into the export")
            for group_name, group in expected_groups().items():
                header, rows = read_csv_bytes(archive.read(f"COMMON_SAMPLES_{group_name}.csv"))
                target = group["target"]
                if target not in header or any(
                    other["target"] in header for other_name, other in expected_groups().items()
                    if other_name != group_name and other["target"] != target
                ):
                    raise AssertionError(f"Cross-target label column leaked into {group_name}")
                if "label_source" in header or any(row["comparison_group_id"] != group_name for row in rows):
                    raise AssertionError(f"Unexpected source text or group rows in {group_name}")
        if receipt["fit_count"] or receipt["prediction_calls"] or digest_file(zip_path) != receipt["zip_sha256"]:
            raise AssertionError("Export receipt must be no-fit and carry the actual ZIP SHA")

        wrong_manifest_sha_rejected = False
        try:
            validate_manifest(manifest_path, "0" * 64)
        except ValueError:
            wrong_manifest_sha_rejected = True
        if not wrong_manifest_sha_rejected:
            raise AssertionError("Wrong approved manifest SHA was accepted")

        unsafe_dataset_bundle = dict(bundle)
        unsafe_dataset_bundle["manifest"] = {**bundle["manifest"], "dataset_id": "file:///Users/private/data.csv"}
        unsafe_dataset_rejected = False
        try:
            safe_export_payload(unsafe_dataset_bundle)
        except ValueError as error:
            unsafe_dataset_rejected = "dataset_id" in str(error)
        if not unsafe_dataset_rejected:
            raise AssertionError("Path-bearing dataset_id was accepted for export")

        def rejected_variant(name, mutate, expected_error):
            test_dir = root / name
            shutil.copytree(fixture_dir, test_dir)
            test_manifest_path = test_dir / "COMMON_TRAINING_MANIFEST.json"
            test_manifest = json.loads(test_manifest_path.read_text(encoding="utf-8"))
            changed_files = mutate(test_dir, test_manifest)
            for file_key in changed_files:
                file_path = test_dir / test_manifest["files"][file_key]["path"]
                _, rows = read_csv(file_path)
                test_manifest["files"][file_key].update(sha256=digest_file(file_path), row_count=len(rows))
                if file_key == "exclusions":
                    test_manifest["exclusion_ledger_sha256"] = digest_file(file_path)
                    reason_counts = {}
                    for row in rows:
                        reason = row["exclusion_reason_code"]
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1
                    test_manifest["exclusion_summary"] = {"row_count": len(rows), "by_reason": reason_counts}
            test_manifest_path.write_text(json.dumps(test_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8")
            try:
                validate_manifest(test_manifest_path, digest_file(test_manifest_path))
            except ValueError as error:
                if expected_error not in str(error):
                    raise AssertionError(f"{name} rejected for an unexpected reason: {error}") from error
                return
            raise AssertionError(f"{name} passed a required fail-closed check")

        def duplicate_assignment(test_dir, test_manifest):
            path = test_dir / test_manifest["files"]["fold_assignments"]["path"]
            header, rows = read_csv(path)
            rows.append(dict(rows[0]))
            path.write_bytes(csv_bytes(header, rows))
            return {"fold_assignments"}

        def early_maturity(test_dir, test_manifest):
            path = test_dir / test_manifest["files"]["samples"]["path"]
            header, rows = read_csv(path)
            next(row for row in rows if row["stable_security_id"] == "000001.SZ")["label_maturity_date"] = "20260101"
            path.write_bytes(csv_bytes(header, rows))
            return {"samples"}

        def overlapping_root(test_dir, test_manifest):
            sample_path = test_dir / test_manifest["files"]["samples"]["path"]
            header, rows = read_csv(sample_path)
            train = next(row for row in rows if row["stable_security_id"] == "000001.SZ")
            dev = next(row for row in rows if row["stable_security_id"] == "000020.SH")
            old_sid = sample_id(dev)
            dev["stable_security_id"] = train["stable_security_id"]
            dev["root_anchor_id"] = train["root_anchor_id"]
            new_sid = sample_id(dev)
            sample_path.write_bytes(csv_bytes(header, rows))
            changed = {"samples"}
            for file_key in ("fold_assignments", "exclusions"):
                path = test_dir / test_manifest["files"][file_key]["path"]
                fields, entries = read_csv(path)
                for entry in entries:
                    if entry["sample_id"] == old_sid:
                        entry["sample_id"] = new_sid
                path.write_bytes(csv_bytes(fields, entries))
                changed.add(file_key)
            return changed

        def repeated_development(test_dir, test_manifest):
            path = test_dir / test_manifest["files"]["fold_assignments"]["path"]
            header, rows = read_csv(path)
            dev = next(row for row in rows if row["comparison_group_id"] == "H1_PHASE" and row["partition"] == "dev")
            train = next(row for row in rows if row["comparison_group_id"] == "H1_PHASE" and row["partition"] == "train")
            rows.extend([
                {**train, "fold_id": "F2"},
                {**dev, "fold_id": "F2"},
            ])
            path.write_bytes(csv_bytes(header, rows))
            return {"fold_assignments"}

        def corrupt_evidence(test_dir, test_manifest):
            path = test_dir / "evidence_label.txt"
            path.write_text("altered synthetic evidence", encoding="utf-8")
            return set()

        def path_event_id(test_dir, test_manifest):
            sample_path = test_dir / test_manifest["files"]["samples"]["path"]
            header, rows = read_csv(sample_path)
            row = next(row for row in rows if row["stable_security_id"] == "000001.SZ")
            old_sid = sample_id(row)
            row["event_id"] = "file:///Users/private/events.csv"
            new_sid = sample_id(row)
            sample_path.write_bytes(csv_bytes(header, rows))
            changed = {"samples"}
            for file_key in ("fold_assignments", "exclusions"):
                path = test_dir / test_manifest["files"][file_key]["path"]
                fields, entries = read_csv(path)
                for entry in entries:
                    if entry["sample_id"] == old_sid:
                        entry["sample_id"] = new_sid
                path.write_bytes(csv_bytes(fields, entries))
                changed.add(file_key)
            return changed

        rejected_variant("duplicate_assignment", duplicate_assignment, "Duplicate group/fold/sample assignment")
        rejected_variant("early_maturity", early_maturity, "Event, label-maturity or PIT date")
        rejected_variant("overlapping_root", overlapping_root, "Same-security root/event overlap")
        rejected_variant("repeated_dev", repeated_development, "development sample is repeated across folds")
        rejected_variant("corrupt_evidence", corrupt_evidence, "Evidence must be same-bundle hash-bound")
        rejected_variant("path_event_id", path_event_id, "Event/root/wave IDs must be canonical")
        return {
            "status": "PASS_SYNTHETIC_INTAKE_EXPORT_ONLY",
            "fixture": "synthetic only, no market rows or labels",
            "candidate_rows": 13,
            "assigned_group_sample_count": 12,
            "excluded_group_sample_count": 66,
            "comparison_groups": 6,
            "zip_sha256": receipt["zip_sha256"],
            "fit_count": 0,
            "prediction_calls": 0,
            "checks": ["exact_manifest_SHA", "same_bundle_evidence_SHA", "train_dev_identity_and_PIT",
                       "maturity_after_observation", "same_security_root_event_overlap",
                       "no_duplicate_development_membership", "label_and_feature_contract",
                       "group_specific_single_target_exports", "excluded_candidate_filter",
                       "no_paths_in_identifiers_or_dataset_id", "local_only_portable_export",
                       "duplicate_fold_rejection", "corrupt_evidence_rejection"],
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--manifest", type=Path, required=True)
    validate_parser.add_argument("--approved-manifest-sha256", required=True)
    export_parser = sub.add_parser("export-gemini")
    export_parser.add_argument("--manifest", type=Path, required=True)
    export_parser.add_argument("--approved-manifest-sha256", required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    sub.add_parser("self-test", help="run synthetic intake/export checks without estimator fits")
    args = parser.parse_args(argv)
    if args.command == "self-test":
        result = self_test()
    else:
        bundle = validate_manifest(args.manifest, args.approved_manifest_sha256)
        if args.command == "validate":
            result = {
                "status": "VALIDATED_FOR_LOCAL_RESEARCH_INTAKE",
                "manifest_sha256": bundle["manifest_sha256"],
                "candidate_rows": bundle["candidate_rows"],
                "assigned_group_sample_count": bundle["assigned_group_sample_count"],
                "group_fold_counts": bundle["group_counts"],
                "fit_count": 0, "prediction_calls": 0,
            }
        else:
            result = write_export(bundle, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
