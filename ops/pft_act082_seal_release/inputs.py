"""Bind release inputs and only project the authorized cutoff data."""

import csv
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import re
from zipfile import ZipFile

from ops.pft_act080_core.archive import INDEX_ID, MANIFEST_NAME, _verified_members, _verify
from ops.pft_act082_step2a.pipeline import QFQ, VAULT_B, require_prepared_source
from ops.pft_act082_step2a.sources import VOL2_SHA, digest, require_signed
from ops.pft_act082_step2a.waves import JUNDA

CUTOFF = 20250930
HISTORY_START = 20250701
GENERATION = "ef7f12caa2f67a4a4f26d775d99735b5a9d2845d919087a689d99df6b6322329"
GENERATION_SHA = "d1c10c325ebb8de4c3519499c8f75f7de06cb8f5e9bfda328855d3f807cbc16e"
SNAPSHOT_SHA = "0a91ad3d06898a78de9f26d87e833b2b75fc75b76399d2e64ef5bc2ba2fcc49d"
READER_SHA = "b73cb6e3164b81a77620c431229f1e77184d8be18a82a2b598961a05b0637cb6"
PANELS = {
    "backtest": "4e2d2595cc770636c9e55014536e061c5f32ccb03d80ba3685f359e977454ee1",
    "selector": "6a57596b59787b4ee740c012e78e893b53724009eeaa4c452dc13daec2981383",
}
CROSSWALK_SHA = "d784dc18e6b24607c56166ff178d85d9a61d31fbc452d36fecc656d5a988253f"
EXPOSURE_SHA = "43838adcd849b9c2150f2db7fb2de499be41209a160ac890e0d66a9c7275f20f"
COVERAGE_SHA = "f408854330434f180e38257ba1c1eff98d2ff1244e30c6b87e3575a149b62204"
PRIOR_READYNESS_SHA = "f719ea2e733d83df9926b4d36bf6515be4d3f95de4e85b56bb1eed522020cab9"
DEV_FRAME_SHA = "d9bcbe0d1b67b3afef2f1db4986aef5af20345b8dd0b21ba2ce76c243fc9f64c"
DEV_SOURCE_SHA = "b8faa684e1aee6bed6a68dbd25aa4c91e6997525441435752cb182a882ec8480"
QUOTE_COLUMNS = ("trade_date", "ts_code", "close")
F10_COLUMNS = ("trade_date", "ts_code", "market_type", "finance_source_date",
               "market_cap_yi", "tdx_finance_industry_code")
STOCK_CODE = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)")


def stock_id(value):
    if not isinstance(value, str) or not STOCK_CODE.fullmatch(value.strip().upper()):
        raise ValueError("invalid or ambiguous stock identifier")
    return value.strip().upper()


def load_aliases(path):
    require_signed(path, CROSSWALK_SHA)
    result = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            old, new = (row[name].strip() for name in ("old_ts_code", "new_ts_code"))
            if not old or not new:
                continue
            old, new = stock_id(old), stock_id(new)
            if not old.endswith(".BJ") or not new.endswith(".BJ"):
                raise ValueError("unexpected exchange on canonical alias binding")
            for code in (old, new):
                prior = result.setdefault(code, new)
                if prior != new:
                    raise ValueError("ambiguous canonical alias binding")
    if not result:
        raise ValueError("missing pinned canonical alias bindings")
    return result


def load_exposures(stage_root):
    owner = stage_root / "sources_admin"
    source, coverage = (owner / "EXPOSURE_UNION_MANIFEST.csv", owner / "EXPOSURE_SOURCE_COVERAGE.json")
    require_signed(owner / "SEALED_SOURCE_READINESS.json", PRIOR_READYNESS_SHA)
    require_signed(source, EXPOSURE_SHA)
    require_signed(coverage, COVERAGE_SHA)
    proof = json.loads(coverage.read_bytes())
    if proof.get("manifest_sha256") != EXPOSURE_SHA or proof.get("known_exposed_securities") != 1179:
        raise ValueError("input exposure coverage binding failed")
    records = 0
    literal = set()
    with source.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            literal.add(stock_id(row["security_id"]))
            records += 1
    if len(literal) != 1179 or records != proof.get("known_evidence_rows") or JUNDA not in literal:
        raise ValueError("known exposure roster changed")
    # The operator authorized this precise known roster, not historical completeness.
    return literal, records


def load_mothers(vol2):
    require_signed(vol2, VOL2_SHA)
    with ZipFile(vol2) as archive:
        sums = _verified_members(archive)
        manifest = archive.read(MANIFEST_NAME)
        _verify(manifest, sums[MANIFEST_NAME], MANIFEST_NAME)
    rows = list(csv.DictReader(manifest.decode("utf-8-sig").splitlines()))
    securities = {stock_id(row["security_id"]) for row in rows}
    if len(rows) != 42 or len(securities) != 42 or not {INDEX_ID, JUNDA} <= securities:
        raise ValueError("frozen mother roster mismatch")
    return securities - {INDEX_ID, JUNDA}


def verify_dev_lock(stage_root):
    private = stage_root / "dev_corrected" / VAULT_B
    seal = json.loads((private / "PRE_RENDER_LOCK.json").read_bytes())
    if require_prepared_source(seal) != DEV_SOURCE_SHA:
        raise ValueError("DEV prepared source evidence not reusable")
    require_signed(private / "SAMPLING_FRAME_MANIFEST.csv", DEV_FRAME_SHA)
    if seal["sha256"] != DEV_FRAME_SHA or seal["qfq_basis_sha256"] != digest(private / QFQ):
        raise ValueError("validated DEV lock changed")
    return DEV_FRAME_SHA


def frozen_reader(reader_file):
    require_signed(reader_file, READER_SHA)
    spec = spec_from_file_location("_act082_pinned_logical_reader", reader_file)
    if spec is None or spec.loader is None:
        raise ValueError("pinned logical reader cannot load")
    runtime = module_from_spec(spec)
    spec.loader.exec_module(runtime)
    return runtime.parquet


def verify_generation(generation_dir):
    candidate = generation_dir / "candidate_receipt.json"
    meta = json.loads((generation_dir / "meta.json").read_bytes())
    require_signed(candidate, GENERATION_SHA)
    receipt = json.loads(candidate.read_bytes())
    basis = {
        "price_basis": "QFQ_ASOF", "amount_basis": "RAW_TURNOVER",
        "volume_basis": "QFQ_EVENT_VOLUME", "asof_date": 20261127,
    }
    if any(doc.get("generation_id") != GENERATION or doc.get("asof_date") != basis["asof_date"]
           or doc.get("market_basis", {}).get("A") != basis or doc.get("logical_reader_sha256") != READER_SHA
           for doc in (receipt, meta)):
        raise ValueError("frozen V4 generation contract changed")
    snapshot = receipt["adjustment_snapshot"]
    if snapshot["sha256"] != SNAPSHOT_SHA:
        raise ValueError("unexpected factor snapshot binding")
    require_signed(Path(snapshot["path"]), SNAPSHOT_SHA)
    bound_paths = {name: Path(meta[name]) for name in PANELS}
    for kind, path in bound_paths.items():
        require_signed(path, PANELS[kind])
    return bound_paths, basis


def read_at_cutoff(reader, path, *, kind, earliest, latest, symbols=()):
    if not (HISTORY_START <= earliest <= latest <= CUTOFF):
        raise ValueError("quote read outside authorized cutoff range")
    if kind == "quote":
        fields = QUOTE_COLUMNS
        bound = [("trade_date", ">=", earliest), ("trade_date", "<=", latest)]
    elif kind == "f10":
        fields = F10_COLUMNS
        bound = [("trade_date", ">=", str(earliest)), ("trade_date", "<=", str(latest))]
    else:
        raise ValueError("unknown authorized V4 projection")
    if symbols:
        bound.append(("ts_code", "in", sorted({stock_id(token) for token in symbols})))
    table = reader.read_table(path, columns=list(fields), filters=bound)
    if set(table.column_names) != set(fields):
        raise ValueError("logical reader returned an unapproved column")
    rows = table.to_pylist()
    if any(not earliest <= int(row["trade_date"]) <= latest for row in rows):
        raise ValueError("logical reader returned a disallowed quote date")
    return rows, int(table.nbytes)
