"""Verify source bytes and project only the phase-authorized columns and rows."""

from collections import Counter
import csv
from hashlib import file_digest
from io import TextIOWrapper
from math import isfinite
import re
from zipfile import ZipFile

from .contracts import FEATURE_SETS, JUNDA, METHOD, ROOT, VOL2_SHA, verify
from .outcomes import pricing_outcomes


def validate_bundle(archive):
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("P1B duplicate ZIP paths")
    sums = {}
    for row in archive.read("SHA256SUMS.txt").decode("ascii").splitlines():
        digest_line, member = row.split("  ", 1)
        if member in sums or not re.fullmatch("[0-9a-f]{64}", digest_line):
            raise ValueError("P1B invalid SHA256SUMS")
        sums[member] = digest_line
    if set(names) != set(sums) | {"SHA256SUMS.txt"}:
        raise ValueError("P1B SHA membership mismatch")
    for member, expected in sums.items():
        with archive.open(member) as data:
            if file_digest(data, "sha256").hexdigest() != expected:
                raise ValueError(f"P1B member SHA mismatch: {member}")
        if member.startswith("ops/pft_act080_core/") and member.endswith((".py", "/config.json")):
            local = ROOT.parent.parent / member
            verify(local, expected)
    return len(sums)


def _project(archive, prefix):
    members = sorted(n for n in archive.namelist() if n.startswith(prefix) and n.endswith(".csv"))
    if not members:
        raise ValueError(f"missing ZIP CSV members: {prefix}")
    for member in members:
        with archive.open(member) as stream:
            head = stream.readline().rstrip(b"\r\n").decode("ascii").split(",")
            columns = {key: i for i, key in enumerate(head)}
            if len(columns) != len(head):
                raise ValueError(f"duplicate header columns in {member}")
            for raw in stream:
                cells = raw.rstrip(b"\r\n").split(b",")
                if len(cells) != len(head) or b'"' in raw:
                    raise ValueError(f"unexpected quoted or malformed row: {member}")
                yield columns, cells


def _ascii(columns, row, key):
    return row[columns[key]].decode("ascii")


def _eligible_identity_rows(archive, development_only):
    splits = {}
    for fields, row in _project(archive, "data/TIME_SPLITS_"):
        stock = _ascii(fields, row, "security_id")
        if development_only and stock == JUNDA:
            continue
        fold = _ascii(fields, row, "assigned_fold")
        if development_only and fold not in ("TRAIN", "VAL"):
            continue
        cid = _ascii(fields, row, "candidate_event_id")
        if cid in splits:
            raise ValueError("duplicate time-split row")
        splits[cid] = (fold or "EXCLUDED", _ascii(fields, row, "structure_episode_id"))
    for fields, row in _project(archive, "data/ACCEPTED_"):
        stock = _ascii(fields, row, "security_id")
        if development_only and stock == JUNDA:
            continue
        cid = _ascii(fields, row, "candidate_event_id")
        if cid not in splits:
            if development_only:
                continue
            raise ValueError(f"missing time-split ID {cid}")
        fold, episode = splits[cid]
        if _ascii(fields, row, "accepted_role") != "FIRST":
            continue
        if episode != _ascii(fields, row, "structure_episode_id"):
            raise ValueError(f"episode/split mismatch {cid}")
        day = _ascii(fields, row, "trade_date")
        if development_only and not (
            (fold == "TRAIN" and day < METHOD["val_start"])
            or (fold == "VAL" and METHOD["val_start"] <= day < METHOD["oot_start"])
        ):
            raise ValueError("development split has an invalid timeline")
        yield {
            "candidate_event_id": cid, "security_id": stock, "D": day,
            "structure_episode_id": episode, "fold": fold,
            "session_idx": int(_ascii(fields, row, "session_idx")),
            "key_k_date": _ascii(fields, row, "key_k_date"),
            "qualification_arm": _ascii(fields, row, "qualification_arm"),
            "anchor_types": _ascii(fields, row, "anchor_types"), "role": "FIRST",
        }


def first_rows(archive, development_only):
    rows = list(_eligible_identity_rows(archive, development_only))
    for field in ("candidate_event_id", "structure_episode_id"):
        if len({r[field] for r in rows}) != len(rows):
            raise ValueError(f"duplicate FIRST {field}")
    return rows


def _feature(value, is_bool):
    if not value:
        return None
    if is_bool:
        if value not in (b"True", b"False"):
            raise ValueError(f"invalid indicator bytes {value!r}")
        return int(value == b"True")
    result = float(value)
    if not isfinite(result):
        raise ValueError("nonfinite source feature")
    return result


def load_features(archive, requested):
    wanted = {r["candidate_event_id"]: r for r in requested}
    result = {}
    feature_names = FEATURE_SETS["FEAT_PLUS_ANCHOR_KB"]
    for fields, row in _project(archive, "data/D_ONLY_FEATURES_"):
        key = _ascii(fields, row, "candidate_event_id")
        if key not in wanted:
            continue
        event = wanted[key]
        if (
            key in result or _ascii(fields, row, "security_id") != event["security_id"]
            or _ascii(fields, row, "trade_date") != event["D"]
            or _ascii(fields, row, "structure_episode_id") != event["structure_episode_id"]
            or _ascii(fields, row, "accepted_role") != "FIRST"
            or _ascii(fields, row, "accepted_flag") != "True"
        ):
            raise ValueError(f"feature/identity disagreement {key}")
        result[key] = [_feature(row[fields[name]], name.startswith("anchor_") and name != "anchor_age_sessions") for name in feature_names]
    if set(result) != set(wanted):
        raise ValueError("feature whitelist projection does not cover authorized IDs")
    return [result[r["candidate_event_id"]] for r in requested]


def load_prices(path, development_only):
    verify(path, VOL2_SHA)
    cutoff = METHOD["oot_start"].encode("ascii") if development_only else None
    prices = {}
    with ZipFile(path) as archive:
        sums = dict(reversed(line.split("  ", 1)) for line in archive.read("SHA256SUMS.txt").decode("ascii").splitlines())
        with archive.open("RAW_42_CHAINS_VERIFIED_MANIFEST.csv") as stream:
            manifest = tuple(csv.DictReader(TextIOWrapper(stream, encoding="utf-8-sig")))
        for meta in manifest:
            stock = meta["security_id"]
            if stock == "000001.SH" or (development_only and stock == JUNDA):
                continue
            name = f"raw_42_chains/{stock}.csv"
            with archive.open(name) as stream:
                if file_digest(stream, "sha256").hexdigest() != sums[name] or sums[name] != meta["csv_sha256"]:
                    raise ValueError(f"invalid price member {stock}")
            dates, opened, closed, lows = [], [], [], []
            with archive.open(name) as stream:
                cols = stream.readline().decode("utf-8-sig").strip().split(",")
                d_i, o_i, c_i, l_i = (cols.index(key) for key in ("D", "open", "close", "low"))
                for line in stream:
                    parts = line.rstrip(b"\r\n").split(b",")
                    day = parts[d_i]
                    if cutoff is not None and day >= cutoff:
                        break
                    dates.append(day.decode("ascii"))
                    vals = tuple(float(parts[i]) for i in (o_i, c_i, l_i))
                    if not all(isfinite(v) for v in vals):
                        raise ValueError(f"nonfinite price {stock} {day!r}")
                    for dst, value in zip((opened, closed, lows), vals, strict=True):
                        dst.append(value)
            if dates != sorted(set(dates)):
                raise ValueError(f"invalid observed stock dates {stock}")
            if not development_only and len(dates) != int(meta["rows_full"]):
                raise ValueError(f"incomplete full observed stock days {stock}")
            prices[stock] = (dates, opened, closed, lows)
    if len(prices) != (40 if development_only else 41):
        raise ValueError("unexpected price universe size")
    return prices


def attach_prices(events, prices, pricing):
    for row in events:
        dates, opened, closed, lows = prices[row["security_id"]]
        idx = row["session_idx"]
        if not 0 <= idx < len(dates) or dates[idx] != row["D"]:
            raise ValueError(f"row does not align to observed stock ordinal: {row['candidate_event_id']}")
        end = {"TRAIN": METHOD["val_start"], "VAL": METHOD["oot_start"]}.get(row["fold"]) if pricing else None
        row.update(pricing_outcomes((dates, opened, closed, lows), idx, end))
