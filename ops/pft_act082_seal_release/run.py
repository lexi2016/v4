"""Seal the authorized 40+10 identity split without revealing or opening it."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from datetime import date
from errno import EACCES, EPERM
from math import isfinite, log
from pathlib import Path
from statistics import stdev
from time import monotonic, process_time
import json
import os
import resource
import stat

from ops.pft_act082_step2a.evidence import canonical_json
from ops.pft_act082_step2a.sources import digest, require_signed
from ops.pft_act082_step2a.vault import audit_access, require_private_directory, seal_mapping, select_sealed, write_new

from .inputs import (
    COVERAGE_SHA, CROSSWALK_SHA, CUTOFF, EXPOSURE_SHA, GENERATION, GENERATION_SHA, HISTORY_START, PANELS,
    READER_SHA, SNAPSHOT_SHA, frozen_reader, load_aliases, load_exposures, load_mothers, read_at_cutoff,
    stock_id, verify_dev_lock, verify_generation,
)

VOLATILITY_OBSERVATIONS = 21
SIZE_SOURCE = "LOCAL_F10_SNAPSHOT"
EXPOSURE_SOURCE = "USER_AUTHORIZED_KNOWN_EXPOSURES_1179"


def iso_date(value):
    item = str(value)
    if len(item) != 8 or not item.isdecimal():
        raise ValueError("noncanonical input date")
    return date.fromisoformat(f"{item[:4]}-{item[4:6]}-{item[6:]}").isoformat()


def _metadata(row):
    if row["market_type"] not in ("A_SHARE", "BJ"):
        raise ValueError("non-A-share row in frozen selector")
    industry, size, source = (row[key] for key in (
        "tdx_finance_industry_code", "market_cap_yi", "finance_source_date",
    ))
    if not industry or size is None or source is None:
        return None
    if not isinstance(industry, str) or not isinstance(size, (float, int)) or not isfinite(size) or size <= 0:
        return None
    if not isinstance(source, (float, int)) or not isfinite(source) or int(source) != source:
        return None
    source = int(source)
    iso_date(source)
    return industry.strip(), float(size), source


def canon(aliases, token):
    raw = stock_id(token)
    return aliases.get(raw, raw)


def _eligible_metadata(rows, aliases):
    by_issuer = {}
    for row in rows:
        raw = stock_id(row["ts_code"])
        canonical = canon(aliases, raw)
        observed = int(row["trade_date"])
        if not HISTORY_START <= observed <= CUTOFF:
            raise ValueError("uncut F10 carrier row")
        profile = _metadata(row)
        if not profile:
            continue
        # Latest cutoff carrier, then canonical alias. Metadata dates can be
        # after cutoff only because the owner explicitly authorized this exception.
        priority = observed, raw == canonical, raw
        if canonical not in by_issuer or priority > by_issuer[canonical][0]:
            by_issuer[canonical] = priority, profile
    return by_issuer


def quote_profiles(rows, aliases, universe):
    by_issuer = defaultdict(dict)
    alias_duplicates = 0
    for row in rows:
        observed = int(row["trade_date"])
        if not HISTORY_START <= observed <= CUTOFF:
            raise ValueError("uncut market price reached volatility")
        raw = stock_id(row["ts_code"])
        security = canon(aliases, raw)
        if security not in universe:
            continue
        close = row["close"]
        if not isinstance(close, (float, int)) or not isfinite(close) or close <= 0:
            continue
        priority = raw == security, raw
        existing = by_issuer[security].get(observed)
        if existing:
            alias_duplicates += 1
        if existing is None or priority > existing[0]:
            by_issuer[security][observed] = priority, close
    result = {}
    for security, points in by_issuer.items():
        recent = sorted(points)[-VOLATILITY_OBSERVATIONS:]
        if len(recent) != VOLATILITY_OBSERVATIONS:
            continue
        prices = [points[time][1] for time in recent]
        log_returns = [log(right) - log(left) for left, right in zip(prices, prices[1:])]
        volatility = stdev(log_returns)
        if volatility > 0 and isfinite(volatility):
            result[security] = recent[-1], volatility
    return result, alias_duplicates


def _profiles(metadata, quote, *, required_day=None):
    result = {}
    for security, (priority, fields) in metadata.items():
        if security not in quote:
            continue
        observed, vol = quote[security]
        if required_day is not None and observed != required_day:
            continue
        if observed < priority[0]:
            continue
        industry, market_cap, source = fields
        result[security] = {
            "security_id": security, "industry": industry, "market_cap": market_cap, "volatility": vol,
            "asof": iso_date(observed), "f10_source_date": iso_date(source),
        }
    return result


def append_truncation_denial(path):
    """Exercise the same-length truncation system call so data cannot be lost."""
    if not path.lstat().st_flags & stat.UF_APPEND:
        raise PermissionError("OS append-only flag not effective")
    original = digest(path)
    length = path.stat().st_size
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
    try:
        try:
            os.ftruncate(fd, length)
        except OSError as exc:
            if exc.errno not in (EPERM, EACCES):
                raise
            reason = exc.errno
        else:
            raise PermissionError("OS append-only truncation was not denied")
    finally:
        os.close(fd)
    if path.stat().st_size != length or digest(path) != original:
        raise ValueError("append-only test was not nondestructive")
    return {"os_append_only": True, "truncation_denied": True, "errno": reason, "audit_unchanged": True}


def release(stage_root, generation_dir, reader_file, crosswalk, vol2, private_key_dir, *, authorized):
    started, cpu_started = monotonic(), process_time()
    if authorized is not True:
        raise ValueError("explicit known-exposure and local F10 authorization required")
    stage_root, private_key_dir = stage_root.resolve(strict=True), private_key_dir.absolute()
    if (stage_root in private_key_dir.parents or private_key_dir == stage_root or
            private_key_dir.exists() or private_key_dir.parent.resolve() != private_key_dir.parent):
        raise PermissionError("fresh external local-private key directory required")
    output = stage_root / "final_seal_work"
    if output.exists():
        raise FileExistsError("real SEALED operation already started")
    frame_sha = verify_dev_lock(stage_root)
    aliases = load_aliases(crosswalk)
    literal, exposure_rows = load_exposures(stage_root)
    canonical_exclusion = {canon(aliases, raw) for raw in literal}
    expanded = literal | canonical_exclusion | {raw for raw, issuer in aliases.items() if issuer in canonical_exclusion}
    dev_issuers = {canon(aliases, raw) for raw in load_mothers(vol2)}
    if len(dev_issuers) != 40 or not dev_issuers <= canonical_exclusion:
        raise ValueError("real DEV canonical profile binding changed")
    reader = frozen_reader(reader_file)
    paths, quote_basis = verify_generation(generation_dir)
    cutoff_f10, f10_bytes = read_at_cutoff(
        reader, paths["selector"], kind="f10", earliest=CUTOFF, latest=CUTOFF,
    )
    metadata = _eligible_metadata(cutoff_f10, aliases)
    raw_nonmissing = sum(_metadata(row) is not None for row in cutoff_f10)
    if len(cutoff_f10) != 5621 or raw_nonmissing != 5394:
        raise ValueError("local F10 cutoff coverage differs from approved frozen version")
    fallback_dev, fallback_bytes = {}, 0
    need = dev_issuers - set(metadata)
    if need:
        symbols = need | {raw for raw, issuer in aliases.items() if issuer in need}
        fallback_rows, fallback_bytes = read_at_cutoff(
            reader, paths["selector"], kind="f10", earliest=HISTORY_START, latest=CUTOFF, symbols=symbols,
        )
        fallback_dev = {s: profile for s, profile in _eligible_metadata(fallback_rows, aliases).items() if s in need}
    universe = set(metadata) | set(fallback_dev)
    market_symbols = universe | {raw for raw, issuer in aliases.items() if issuer in universe}
    quote_rows, quote_bytes = read_at_cutoff(
        reader, paths["backtest"], kind="quote", earliest=HISTORY_START, latest=CUTOFF, symbols=market_symbols,
    )
    prices_read = len(quote_rows)
    latest_price = max(int(row["trade_date"]) for row in quote_rows)
    quotes, quote_duplicates = quote_profiles(quote_rows, aliases, universe)
    del quote_rows
    profiles = _profiles(metadata, quotes, required_day=CUTOFF)
    all_dev = _profiles({**metadata, **fallback_dev}, quotes)
    if not dev_issuers <= set(all_dev):
        raise ValueError("real frozen 40-stock DEV reference unavailable in authorized F10 and pre-cut volatility")
    references = [all_dev[s] for s in sorted(dev_issuers)]
    date_keys = [entry["f10_source_date"] for entry in profiles.values()]
    if not date_keys:
        raise ValueError("no profile cohort under authorized exception")
    available = sorted(set(profiles) - canonical_exclusion)
    if len(available) < 50:
        raise ValueError("insufficient unexposed eligible issuers")
    for name, path in paths.items():
        require_signed(path, PANELS[name])
    require_signed(reader_file, READER_SHA)
    input_wall = monotonic() - started

    output = require_private_directory(output)
    write_new(output / "ONE_SHOT_SELECTION_INTENT.json", canonical_json({
        "generation": GENERATION, "known_exposure_manifest_sha256": EXPOSURE_SHA,
        "exposure_scope": EXPOSURE_SOURCE, "strat_source": SIZE_SOURCE, "feature_cutoff": iso_date(CUTOFF),
        "selected_tickers_can_appear_only_inside_aes_ciphertext": True,
    }))
    selection = select_sealed(
        [profiles[s] for s in sorted(profiles)], references, expanded,
    )
    chosen = {row["security_id"] for row in selection["rows"]}
    strata = Counter(row["stratum"] for row in selection["rows"])
    if strata != {"MAIN": 40, "HETEROGENEOUS": 10} or len(chosen) != 50 or (
        chosen & literal or {canon(aliases, s) for s in chosen} & canonical_exclusion
    ):
        raise ValueError("literal or canonical exposure conflict")
    # The mapping never enters telemetry or a plaintext disk file.
    selection.update(strat_source=SIZE_SOURCE, exposure_scope=EXPOSURE_SOURCE, PIT="CANNOT_CONFIRM")
    for item in selection["rows"]:
        item["f10_source_date"] = profiles[item["security_id"]]["f10_source_date"]
    private_key_dir = require_private_directory(private_key_dir)
    local = output / "SEALED_OOT_V2"
    private_key = private_key_dir / "SEALED_OOT_V2_MAPPING.key"
    sealed = seal_mapping(selection, local, private_key)
    del selection
    log = local / "ACCESS_AUDIT.jsonl"
    disposition = append_truncation_denial(log)
    audit = audit_access(log)
    cipher = local / "SEALED_OOT_V2_MAPPING.aesgcm"
    if digest(cipher) != sealed["ciphertext_sha256"] or cipher.stat().st_size != sealed["ciphertext_bytes"]:
        raise ValueError("real sealed ciphertext byte verification failed")
    modes = {"directory": "0700", "ciphertext": "0600", "audit": "0600", "local_key": "0600"}
    expected = ((local, 0o700), (cipher, 0o600), (log, 0o600), (private_key, 0o600))
    if any(stat.S_IMODE(path.lstat().st_mode) != mode for path, mode in expected):
        raise ValueError("SEALED physical access isolation failed")
    write_new(private_key_dir / "USER_ONLY_KEY_RECEIPT.json", canonical_json({
        key: sealed[key] for key in ("key_path", "key_sha256_fingerprint", "ciphertext_sha256", "cipher")
    }))
    result = {
        "status": "ACT082_STAGE2A_REAL_SEALED_AUTHORIZED_EXCEPTIONS",
        "exposure_scope": EXPOSURE_SOURCE, "known_exposure_literal_codes": len(literal),
        "known_exposure_canonical_issuers": len(canonical_exclusion), "known_exposure_expanded_codes": len(expanded),
        "known_exposure_evidence_rows": exposure_rows, "historical_exposure_completeness_certified": False,
        "exposure_manifest_sha256": EXPOSURE_SHA, "exposure_source_coverage_sha256": COVERAGE_SHA,
        "alias_crosswalk_sha256": CROSSWALK_SHA, "literal_exposure_intersection": 0,
        "canonical_exposure_intersection": 0, "strat_source": SIZE_SOURCE,
        "allowed_f10_fields": ["market_cap_yi", "tdx_finance_industry_code"],
        "archived_f10_source_date_min": min(date_keys), "archived_f10_source_date_max": max(date_keys),
        "f10_precut_attested": False, "f10_missing_cutoff_rows_skipped": len(cutoff_f10) - raw_nonmissing,
        "f10_complete_cutoff_raw_codes": raw_nonmissing, "frozen_selector_cutoff_rows": len(cutoff_f10),
        "canonical_f10_profile_count": len(metadata), "canonical_complete_profile_count": len(profiles),
        "eligible_unexposed_issuers": len(available), "dev_reference_universe_count": len(references),
        "dev_reference_earlier_f10_carriers_used": len(fallback_dev),
        "volatility_method": "SAMPLE_SD_20_LOG_RETURNS_OF_LATEST_21_VALID_STOCK_CLOSES",
        "volatility_carrier_start": iso_date(HISTORY_START), "quote_query_upper_bound": iso_date(CUTOFF),
        "latest_price_date_returned": iso_date(latest_price), "postcutoff_price_rows_returned": 0,
        "projected_quote_rows_returned": prices_read, "same_issuer_same_session_alias_rows_collapsed": quote_duplicates,
        "generation_id": GENERATION, "generation_manifest_sha256": GENERATION_SHA,
        "adjustment_snapshot_sha256": SNAPSHOT_SHA, "logical_reader_sha256": READER_SHA,
        "logical_descriptor_sha256": PANELS, "quote_basis": quote_basis, "dev_frame_sha256": frame_sha,
        "selected_strata_counts": dict(strata), "selected_total": 50, "seal_evaluation_D_min": "2025-11-13",
        "cipher": sealed["cipher"], "ciphertext_sha256": sealed["ciphertext_sha256"],
        "ciphertext_bytes": sealed["ciphertext_bytes"], "storage_modes": modes,
        "separate_external_local_key_custody": True,
        "key_custody_scope": "SEPARATE_MODE_RESTRICTED_LOCAL_DIRECTORY", **audit, **disposition,
        "sealed_png_count": sealed["sealed_png_count"], "human_identity_view_count": 0, "oot_return_stat_runs": 0,
        "PIT": "CANNOT_CONFIRM", "FIT": 0, "training": 0, "tuning": 0, "NO_GO": True,
        "logical_cpu_count": os.cpu_count(), "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "arrow_projected_bytes": f10_bytes + fallback_bytes + quote_bytes,
        "input_wall_seconds": round(input_wall, 6), "wall_seconds": round(monotonic() - started, 6),
        "process_cpu_seconds": round(process_time() - cpu_started, 6),
    }
    write_new(output / "SEALED_ACCEPTANCE.json", canonical_json(result))
    return result


def main():
    parser = ArgumentParser(description=__doc__)
    for name in ("stage-root", "generation-dir", "reader-file", "crosswalk", "vol2", "private-key-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--apply-user-authorized-known-exposure-and-local-f10-exceptions", action="store_true")
    args = parser.parse_args()
    result = release(
        args.stage_root, args.generation_dir, args.reader_file, args.crosswalk, args.vol2, args.private_key_dir,
        authorized=args.apply_user_authorized_known_exposure_and_local_f10_exceptions,
    )
    print(json.dumps({key: result[key] for key in (
        "status", "selected_strata_counts", "selected_total", "ciphertext_sha256", "ciphertext_bytes",
        "OOT_OPEN_COUNT", "wall_seconds",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
