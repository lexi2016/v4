"""Read sealed holdouts only from the exclusive post-claim stage."""

from bisect import bisect_left
from collections import defaultdict
import csv
from hashlib import sha256
from io import TextIOWrapper
from types import SimpleNamespace
from zipfile import ZipFile

from ops.pft_act080_core.split import split_evidence

from .contracts import BASELINE_MEMBER, BASELINE_MEMBER_SHA, BASELINE_SHA, JUNDA, METHOD, verify
from .sources import _ascii, _project


JUNDA_CASES = (
    ("#04", "2021-03-22", "DOWNGRADE"), ("#06", "2021-02-23", "DOWNGRADE"),
    ("#31", "2025-02-26", "DOWNGRADE"), ("#15", "2024-09-24", "RECALL"),
    ("#32", "2023-06-02", "RECALL"), ("#34", "2022-11-01", "RECALL"),
    ("#39", "2020-11-24", "RECALL"),
)


def _ordinal(prices, stock, day):
    if stock not in prices:
        raise ValueError(f"unknown sealed holdout security {stock}")
    dates = prices[stock][0]
    ordinal = bisect_left(dates, day)
    if ordinal == len(dates) or dates[ordinal] != day:
        raise ValueError(f"missing exact observed ordinal for {stock}/{day}")
    return ordinal


def parse_exclusions(path, prices):
    index = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 72 or len({r["sample_id"] for r in rows}) != 72 or sum(r["episode_period"] == "OOT" for r in rows) != 23:
        raise ValueError("invalid 72-case exclusion identity count")
    for row in rows:
        stock, day = row["security_id"], row["first_trigger_D"]
        if int(row["exclusion_window_trading_days"]) != METHOD["window_sessions"]:
            raise ValueError("signed manifest window differs from frozen method")
        index[stock].append((row["sample_id"], day, _ordinal(prices, stock, day)))
    return index


def screen(events, references, policy):
    clean, proof = [], []
    window, horizon = METHOD["window_sessions"], METHOD["horizon_sessions"]
    for event in events:
        ordinal = event["session_idx"]
        matching = []
        for sample, day, sample_idx in references.get(event["security_id"], ()):
            delta = ordinal - sample_idx
            overlap_start = max(ordinal, sample_idx) + 1
            overlap_end = min(ordinal, sample_idx) + horizon
            overlap = overlap_start <= overlap_end
            vicinity = abs(delta) <= window
            if vicinity or overlap:
                reasons = ("D_PLUS_MINUS_10" if vicinity else "", "HOLDING_WINDOW_OVERLAP" if overlap else "")
                matching.append({
                    "policy": policy, "candidate_event_id": event["candidate_event_id"],
                    "structure_episode_id": event["structure_episode_id"], "security_id": event["security_id"],
                    "event_D": event["D"], "event_session_idx": ordinal, "sample_id": sample, "sample_D": day,
                    "sample_session_idx": sample_idx, "signed_session_gap": delta,
                    "exclusion_reason": "|".join(s for s in reasons if s), "holding_overlap": overlap,
                    "overlap_start_session_idx": overlap_start if overlap else None,
                    "overlap_end_session_idx": overlap_end if overlap else None,
                })
        if matching:
            proof.extend(matching)
        else:
            clean.append(event)
    if len(clean) + len({r["candidate_event_id"] for r in proof}) != len(events):
        raise ValueError(f"{policy}: exclusion lack of row conservation")
    return clean, proof


def legacy_rows(path, prices):
    verify(path, BASELINE_SHA)
    records = []
    with ZipFile(path) as archive:
        raw = archive.read(BASELINE_MEMBER)
        if sha256(raw).hexdigest() != BASELINE_MEMBER_SHA:
            raise ValueError("legacy comparator member SHA-256 mismatch")
        from io import BytesIO

        reader = csv.DictReader(TextIOWrapper(BytesIO(raw), encoding="utf-8-sig"))
        fields = ("security_id", "D", "structure_episode_id", "kb_anchor_date", "visual_tier")
        if not set(fields).issubset(reader.fieldnames or []):
            raise ValueError("legacy comparator lacks exact identity/tier fields")
        for cells in reader:
            stock, day, episode, anchor, tier = (cells[field] for field in fields)
            key = sha256(f"LEGACY_V21_COMPARATOR|{stock}|{episode}|{day}".encode()).hexdigest()
            if anchor > day or not episode:
                raise ValueError("legacy identity/anchor chronology invalid")
            records.append({
                "candidate_event_id": key, "security_id": stock, "D": day, "trade_date": day,
                "structure_episode_id": episode, "key_k_date": anchor, "session_idx": _ordinal(prices, stock, day),
                "legacy_tier": tier, "legacy_A": tier == METHOD["frozen_baseline_a_tier"],
            })
    by_stock, groups = defaultdict(list), set()
    for row in sorted(records, key=lambda r: (r["security_id"], r["D"], r["structure_episode_id"])):
        group = row["security_id"], row["structure_episode_id"]
        row["role"] = "REPEAT" if group in groups else "FIRST"
        groups.add(group)
        by_stock[row["security_id"]].append(row)
    if len(groups) != 2361:
        raise ValueError(f"legacy reference unexpected independent episode count {len(groups)}")
    for stock, rows in by_stock.items():
        dates = [SimpleNamespace(trade_date=d) for d in prices[stock][0]]
        flags, _ = split_evidence(dates, rows)
        for row, split in zip(rows, flags, strict=True):
            row["fold"] = split["assigned_fold"] or "EXCLUDED"
    return records


def junda_exact_D_ledger(archive):
    requested = {day for _, day, _ in JUNDA_CASES}
    exact = defaultdict(list)
    for fields, row in _project(archive, "data/RAW_CANDIDATES_"):
        if _ascii(fields, row, "security_id") != JUNDA:
            continue
        day = _ascii(fields, row, "trade_date")
        if day not in requested:
            continue
        exact[day].append({
            "key": _ascii(fields, row, "candidate_event_id"), "arm": _ascii(fields, row, "qualification_arm"),
            "role": _ascii(fields, row, "accepted_role"), "reject_reason": _ascii(fields, row, "reject_reason"),
        })
    return exact
