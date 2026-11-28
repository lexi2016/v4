"""Verify signed inputs and project frozen DEV OHLCV without loading other stocks."""

from hashlib import file_digest, sha256
from csv import DictReader
from io import StringIO
from pathlib import Path
from zipfile import ZipFile

from ops.pft_act080_core.archive import MANIFEST_NAME, INDEX_ID, Chain, _verified_members, _verify
from ops.pft_act080_core.core import Bar, CONFIG, Provenance
from ops.pft_act081_kb.run import verify_p1b_runtime

from .calendar import DEV_END, ExchangeCalendar, SEAL_START, validate_purge
from .waves import JUNDA

STEP1_NAME = "PFT_V4_ACT082_STEP1_STRUCTURAL_EVIDENCE_SCHEMA_V1_1_20261128.md"
STEP2_NAME = "PFT_V4_ACT082_STEP2_ISOLATION_AND_BLIND_LABELING_SPEC_V1_2_20261128.md"
STEP1_SHA = "3ddcaec8328e7f4c6ade8adab34f70c9a74072e0e7954d8bb566642f92a9e568"
STEP2_SHA = "50349fc5071d46b3d5eea75f5ed90aec4804402db73f0d9994be237024a81bc9"
P1B_SHA = "c9f59877448d716a4bba44e45ef0226fe913bd0a6651ae92a69634696efc6701"
EXCLUSION_SHA = "512e28cbf1a1c04eb2893b225f9dcb1e873ed48da5d19af6920690249307e590"
VOL2_SHA = CONFIG["archive_sha256"]
VOL2_QFQ_ASOF = "2026-11-26"
VOL2_OWNER_REFERENCE_SHA = "2b1b320bd71354ef3e774f425e85efe440a47639b2ced3aa77f034cc4ab21c22"
BSE_LISTING_START = "2021-11-15"
DEV_OHLCV = ("open", "high", "low", "close", "volume")


def digest(path):
    with Path(path).open("rb") as f:
        return file_digest(f, "sha256").hexdigest()


def require_signed(path, expected, size=None):
    actual = digest(path)
    if actual != expected or (size is not None and Path(path).stat().st_size != size):
        raise ValueError(f"frozen source verification failed: {Path(path).name}")
    return actual


def verified_qfq_basis(owner_reference):
    reference_sha = require_signed(owner_reference, VOL2_OWNER_REFERENCE_SHA)
    source_ref = owner_reference.read_text(encoding="utf-8-sig")
    if VOL2_QFQ_ASOF not in source_ref or VOL2_SHA not in source_ref:
        raise ValueError("owner QFQ archive basis reference does not bind source")
    return {
        "PIT": "CANNOT_CONFIRM", "basis_extraction_date": VOL2_QFQ_ASOF,
        "exact_extraction_timestamp": None, "version_sha256": VOL2_SHA,
        "owner_basis_reference_sha256": reference_sha,
        "basis_status": "OWNER_CORROBORATED_QFQ_ARCHIVE_DAY",
    }


def verified_inputs(root, p1b, exclusion):
    refs = {
        "step1": require_signed(root / STEP1_NAME, STEP1_SHA, 12524),
        "step2": require_signed(root / STEP2_NAME, STEP2_SHA, 18867),
        "p1b": require_signed(p1b, P1B_SHA),
        "historic_72": require_signed(exclusion, EXCLUSION_SHA),
    }
    members, bound = verify_p1b_runtime(p1b)
    return {"input_sha256": refs, "p1b_verified_members": members, "p1b_import_bindings": bound}


def _member(archive, security):
    return archive.open(f"raw_42_chains/{security}.csv")


def _read_through(archive, security, end, *, parse_ohlcv):
    with _member(archive, security) as stream:
        header = stream.readline().decode("utf-8-sig").strip().split(",")
        if header[0] != "D" or len(header) != len(set(header)):
            raise ValueError("unexpected VOL2 source columns")
        offsets = [header.index(field) for field in DEV_OHLCV] if parse_ohlcv else []
        last = None
        for line in stream:
            day = line.split(b",", 1)[0].decode("ascii")
            if day > end:
                break
            if last is not None and day <= last:
                raise ValueError("VOL2 source dates are not strictly ascending")
            last = day
            if parse_ohlcv:
                fields = line.split(b",")
                if len(fields) != len(header):
                    raise ValueError("VOL2 source row arity")
                yield Bar(day, *(float(fields[index]) for index in offsets))
            else:
                # Calendar discovery projects only the first column, never market measurements.
                yield day


def load_dev(vol2, source_code_sha):
    """The exact frozen VOL2 is verified as bytes. Parse quote values only for DEV members/dates."""
    outer = require_signed(vol2, VOL2_SHA)
    with ZipFile(vol2) as archive:
        sums = _verified_members(archive)
        manifest = archive.read(MANIFEST_NAME)
        _verify(manifest, sums[MANIFEST_NAME], MANIFEST_NAME)
        rows = list(DictReader(StringIO(manifest.decode("utf-8-sig"))))
        roster = {row["security_id"]: row for row in rows}
        if len(rows) != 42 or len(roster) != 42 or not {INDEX_ID, JUNDA} <= set(roster):
            raise ValueError("unexpected frozen VOL2 roster")
        dates = tuple(_read_through(archive, INDEX_ID, SEAL_START, parse_ohlcv=False))
        cal_sha = sha256(("\n".join(dates) + "\n").encode()).hexdigest()
        calendars = {
            market: ExchangeCalendar(
                market, dates if market != "BJ" else tuple(x for x in dates if x >= BSE_LISTING_START), cal_sha,
            ) for market in ("SH", "SZ", "BJ")
        }
        purge = validate_purge(calendars)
        chains = []
        for security in sorted(set(roster) - {INDEX_ID, JUNDA}):
            member = f"raw_42_chains/{security}.csv"
            sha = sums[member]
            if sha != roster[security]["csv_sha256"]:
                raise ValueError("frozen manifest hash disagreement")
            bars = tuple(
                bar for bar in _read_through(archive, security, DEV_END, parse_ohlcv=True)
                if not security.endswith(".BJ") or bar.trade_date >= BSE_LISTING_START
            )
            chains.append(Chain(security, bars, Provenance(outer, sha, source_code_sha)))
    return chains, calendars, {
        "vol2_sha256": outer, "market_projection": "DEV_ONLY_FROZEN_VOL2",
        "calendar_date_projected_count": len(dates), "calendar_dates_sha256": cal_sha,
        "calendar_evidence": "FROZEN_SSE_INDEX_DATE_AXIS_AND_OFFICIAL_2025_CLOSURES",
        "dev_count": len(chains), "purge_sessions": len(purge),
        "actual_dev_market_last_accessed_day": max(chain.bars[-1].trade_date for chain in chains),
        "debug_ohlcv_reads": 0, "sealed_ohlcv_reads": 0, "historical_adjustment_pit": "CANNOT_CONFIRM",
        "qfq_extraction_basis": "OWNER_CORROBORATED_ARCHIVE_ASOF",
        "qfq_archive_asof": VOL2_QFQ_ASOF,
    }

