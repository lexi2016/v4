"""Read and bind the frozen VOL2 observed-bar archive without extraction."""

import csv
from dataclasses import dataclass
from hashlib import file_digest, sha256
from io import StringIO
from pathlib import Path
import re
from zipfile import ZipFile

from .core import Bar, CONFIG, Provenance


MANIFEST_NAME = "RAW_42_CHAINS_VERIFIED_MANIFEST.csv"
SUMS_NAME = "SHA256SUMS.txt"
INDEX_ID = "000001.SH"


@dataclass(frozen=True, slots=True)
class Chain:
    security_id: str
    bars: tuple[Bar, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class Archive:
    chains: list[Chain]
    evidence: dict


def _reader(data):
    return csv.DictReader(StringIO(data.decode("utf-8-sig"), newline=""))


def _chain_bars(security, data):
    reader = _reader(data)
    required = {"D", "open", "high", "low", "close", "volume"}
    fields = reader.fieldnames or []
    if len(fields) != len(set(fields)) or not required.issubset(fields):
        raise ValueError(f"{security}: invalid VOL2 header")
    bars = []
    for row in reader:
        try:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("invalid CSV row width")
            bar = Bar(row["D"], *(float(row[key]) for key in ("open", "high", "low", "close", "volume")))
            if bars and bar.trade_date <= bars[-1].trade_date:
                raise ValueError("repeated or out-of-order trade_date")
            bars.append(bar)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{security}: row {reader.line_num}: {exc}") from exc
    return tuple(bars)


def source_code_sha256():
    """Stable relative-path-to-byte binding for importable production modules."""
    root = Path(__file__).parent
    digest = sha256()
    for path in sorted(root.glob("*.py")):
        data = path.read_bytes()
        digest.update(f"{path.name}:{len(data)}\n".encode("ascii"))
        digest.update(data)
    return digest.hexdigest()


def _verified_members(archive):
    names = archive.namelist()
    if len(set(names)) != len(names):
        raise ValueError("duplicate ZIP members")
    sums = {}
    for line in archive.read(SUMS_NAME).decode("ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_./]+)", line)
        if not match or match[2] in sums:
            raise ValueError("invalid/duplicate internal SHA record")
        sums[match[2]] = match[1]
    if set(names) != {SUMS_NAME, *sums} or MANIFEST_NAME not in sums:
        raise ValueError("internal ZIP checksum manifest does not cover the payload")
    return sums


def _verify(data, digest, member):
    if sha256(data).hexdigest() != digest:
        raise ValueError(f"member SHA mismatch: {member}")


def read_archive(path):
    path = Path(path)
    code_sha = source_code_sha256()
    with path.open("rb") as raw:
        archive_sha = file_digest(raw, "sha256").hexdigest()
        if archive_sha != CONFIG["archive_sha256"]:
            raise ValueError(f"VOL2 archive SHA mismatch: {archive_sha}")
        raw.seek(0)
        with ZipFile(raw) as archive:
            sums = _verified_members(archive)
            manifest = archive.read(MANIFEST_NAME)
            _verify(manifest, sums[MANIFEST_NAME], MANIFEST_NAME)
            rows = list(_reader(manifest))
            securities = {row["security_id"] for row in rows}
            if len(rows) != 42 or len(securities) != 42 or INDEX_ID not in securities:
                raise ValueError("VOL2 expected 41 distinct stocks and one index")
            expected = {f"raw_42_chains/{security}.csv" for security in securities}
            if set(sums) != {MANIFEST_NAME, *expected}:
                raise ValueError("VOL2 chain roster/member discrepancy")
            chains = []
            for row in sorted(rows, key=lambda item: item["security_id"]):
                security = row["security_id"]
                if not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", security):
                    raise ValueError(f"invalid security_id {security!r}")
                member = f"raw_42_chains/{security}.csv"
                data = archive.read(member)
                chain_sha = sums[member]
                if len(data) != int(row["csv_bytes"]) or chain_sha != row["csv_sha256"]:
                    raise ValueError(f"VOL2 manifest disagreement: {member}")
                _verify(data, chain_sha, member)
                bars = _chain_bars(security, data)
                if (
                    len(bars) != int(row["rows_full"]) or not bars
                    or bars[0].trade_date != row["first_D"] or bars[-1].trade_date != row["last_D"]
                    or sum(bar.trade_date <= "2026-11-20" for bar in bars) != int(row["rows_le_20261120"])
                ):
                    raise ValueError(f"VOL2 date/row manifest disagreement: {member}")
                if security != INDEX_ID:
                    chains.append(Chain(security, bars, Provenance(archive_sha, chain_sha, code_sha)))
            evidence = {
                "archive_sha256": archive_sha,
                "archive_bytes": path.stat().st_size,
                "zip_members": len(archive.infolist()),
                "verified_member_hashes": len(sums),
                "manifest_sha256": sums[MANIFEST_NAME],
                "excluded_index": INDEX_ID,
                "logical_uncompressed_zip_bytes_read": sum(item.file_size for item in archive.infolist()),
                "code_sha256": code_sha,
            }
    return Archive(chains, evidence)
