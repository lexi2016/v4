"""Official TDX metadata fallback inside the original daily A-share stage.

This path is explicitly TDX-convention QFQ, never labelled Futu-equivalent.
Unknown corporate-action categories retain their rows and block that symbol.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import struct
import urllib.request
import zipfile
from zoneinfo import ZoneInfo

from ops.research_panel_factor_cache import QfqGateError, _json, _source, canonical_sha, sha

OFFICIAL_URL = "http://www.tdx.com.cn/products/data/data/dbf/gbbq.zip"
PARSER_SHA = "e28fae76760b1247a960cab285aa357c2d263b3212e7cabfb3f1ebfcc127d6ba"


def _fetch() -> bytes:
    with urllib.request.urlopen(OFFICIAL_URL, timeout=30) as response:
        payload = response.read(32 * 1024 * 1024 + 1)
    if len(payload) > 32 * 1024 * 1024:
        raise QfqGateError("OFFICIAL_GBBQ_ARCHIVE_SIZE_LIMIT")
    return payload


def _save_bytes(path: Path, payload: bytes) -> None:
    # Only immutable content-addressed metadata files, never the existing TDX
    # terminal's files or any historical price panel.
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise QfqGateError(f"IMMUTABLE_TDX_SOURCE_CONFLICT:{path}")
        return
    temporary = path.with_suffix(path.suffix + ".pending")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(path)


def _capture_coverage_end(capture: dict) -> int:
    try:
        observed = datetime.fromisoformat(capture["observed_at"])
        if observed.tzinfo is None:
            raise ValueError("timezone missing")
        observed_date = int(observed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"))
        ceiling = capture.get("coverage_end_date", observed_date)
        if type(ceiling) is not int:
            raise ValueError("coverage date type")
        datetime.strptime(str(ceiling), "%Y%m%d")
        if ceiling > observed_date or ceiling < 19000101:
            raise ValueError("coverage outside capture date")
        return ceiling
    except (KeyError, ValueError, TypeError) as exc:
        raise QfqGateError("TDX_CAPTURE_COVERAGE_DATE_UNBOUND") from exc


def official_snapshot(root: Path, config: dict, *, fetch=None, target: int | None = None,
                      refresh_stale_capture: bool = False) -> tuple[Path, dict]:
    parser = _source(config["parser"], owner="official GBBQ parser")
    if config["parser"]["sha256"] != PARSER_SHA or config.get("source_url") != OFFICIAL_URL:
        raise QfqGateError("OFFICIAL_TDX_SOURCE_OR_PARSER_IDENTITY_CONFLICT")
    cached, captured = config.get("cached_capture"), None
    if cached:
        captured = json.loads(_source(cached, owner="original TDX capture receipt").read_text())
        if captured.get("source_url") != OFFICIAL_URL or captured.get("parser") != config["parser"]:
            raise QfqGateError("CACHED_TDX_CAPTURE_IDENTITY_CONFLICT")
        supported_end = _capture_coverage_end(captured)
        if target is not None and target > supported_end:
            if not refresh_stale_capture:
                raise QfqGateError(f"CACHED_TDX_CAPTURE_COVERAGE_INSUFFICIENT:{supported_end}<{target}")
            # Only the original online daily caller opts into its existing
            # official refresh route. Explicit offline replay never fetches.
            captured = None
        if captured is not None:
            if fetch is not None:
                raise QfqGateError("CACHED_TDX_CAPTURE_WITH_FETCH_CONFLICT")
            payload = _source(captured["archive"], owner="original TDX archive").read_bytes()
            observed_at = captured["observed_at"]
    if captured is None:
        observed_at = datetime.now(timezone.utc).isoformat()
        supported_end = _capture_coverage_end(dict(observed_at=observed_at))
        if target is not None and target > supported_end:
            raise QfqGateError(f"TDX_TARGET_AFTER_CURRENT_CAPTURE_DATE:{supported_end}<{target}")
        payload = (fetch or _fetch)()
    archive_sha = hashlib.sha256(payload).hexdigest()
    archive_path = root / "official_gbbq" / (archive_sha + ".zip")
    _save_bytes(archive_path, payload)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        files = [item for item in archive.infolist() if not item.is_dir() and Path(item.filename).name.lower() == "gbbq"]
        if len(files) != 1 or files[0].file_size > 32 * 1024 * 1024:
            raise QfqGateError("OFFICIAL_GBBQ_ARCHIVE_LAYOUT_INVALID")
        raw = archive.read(files[0])
    if len(raw) < 4 or len(raw) != 4 + struct.unpack("<I", raw[:4])[0] * 29:
        raise QfqGateError("OFFICIAL_GBBQ_RECORD_COUNT_OR_TRAILING_BYTES")
    raw_sha = hashlib.sha256(raw).hexdigest()
    if captured and (captured["raw"]["sha256"] != raw_sha
                     or _source(captured["raw"], owner="original TDX raw").read_bytes() != raw):
        raise QfqGateError("CACHED_TDX_RAW_ARCHIVE_CONFLICT")
    raw_path = root / "official_gbbq" / (raw_sha + ".gbbq")
    _save_bytes(raw_path, raw)
    captured = dict(source_url=OFFICIAL_URL, observed_at=observed_at, coverage_end_date=supported_end,
                    coverage_end_date_basis="BOUND_CAPTURE_DATE_CEILING; NOT_HISTORICAL_PUBLICATION_CERTIFICATION",
                    archive=dict(path=str(archive_path), sha256=sha(archive_path)),
                    raw=dict(path=str(raw_path), sha256=sha(raw_path)), parser=config["parser"],
                    scope="OFFICIAL_GBBQ_ALL_ROWS_CURRENT_CAPTURE_NOT_HISTORICAL_PIT")
    _json(root / "official_gbbq" / "capture_receipt.json", captured)
    return raw_path, captured


def build_fallback(root: Path, codes: dict[str, dict], target: int, *, fetch=None, parser_factory=None,
                   refresh_stale_capture: bool = False) -> dict:
    config_path = root / "qfq_tdx_official_source.json"
    if not config_path.is_file():
        raise QfqGateError(f"OFFICIAL_TDX_FALLBACK_CONFIG_MISSING:{config_path}")
    config = json.loads(config_path.read_text())
    policy_ref = config.get("category_policy_receipt")
    if not policy_ref:
        raise QfqGateError("TDX_CATEGORY_POLICY_UNCONFIRMED")
    policy_path = _source(policy_ref, owner="TDX category semantics")
    policy = json.loads(policy_path.read_text())
    if policy.get("policy_id") != "TDX_GBBQ_CATEGORY1_AFFINE_BJ_V1" or not policy.get("controller"):
        raise QfqGateError("TDX_CATEGORY_POLICY_NOT_ACCEPTED")
    categories = policy.get("category_policy", {})
    if categories.get("1") != "PRICE_ACTION_PER10_CASH_RIGHTS_BONUS_AFFINE":
        raise QfqGateError("TDX_CATEGORY1_SEMANTICS_MISSING")
    raw_path, captured = official_snapshot(root, config, fetch=fetch, target=target, refresh_stale_capture=refresh_stale_capture)
    cache_id = canonical_sha(dict(raw=captured["raw"], parser=captured["parser"], policy=policy_ref))
    parsed_path = root / "official_gbbq" / (cache_id + ".parquet")
    parsed_receipt = parsed_path.with_suffix(".receipt.json")
    if not parsed_path.exists():
        if parser_factory is None:
            spec = importlib.util.spec_from_file_location("qfq_official_gbbq_parser", config["parser"]["path"])
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            parser_factory = module.GbbqReader
        frame = parser_factory().get_df(str(raw_path))
        temporary = parsed_path.with_suffix(".pending")
        frame.to_parquet(temporary, index=False)
        temporary.replace(parsed_path)
        _json(parsed_receipt, dict(sha256=sha(parsed_path), cache_id=cache_id))
    else:
        if not parsed_receipt.is_file() or json.loads(parsed_receipt.read_text()).get("sha256") != sha(parsed_path):
            raise QfqGateError("TDX_DERIVED_CACHE_HASH_MISMATCH")
        import pandas as pd
        frame = pd.read_parquet(parsed_path)
    if len(frame) != struct.unpack("<I", raw_path.read_bytes()[:4])[0]:
        raise QfqGateError("TDX_PARSER_ROW_COUNT_MISMATCH")
    market = {0: "SZ", 1: "SH", 2: "BJ"}
    frame = frame.copy()
    frame["ts_code"] = frame["code"].astype(str).str.zfill(6) + "." + frame["market"].map(market).fillna("UNKNOWN")
    capture_receipt = root / "official_gbbq" / "capture_receipts" / (canonical_sha(captured) + ".json")
    if not capture_receipt.exists():
        _json(capture_receipt, captured)
    source_refs = [captured["raw"], captured["archive"], captured["parser"], policy_ref,
                   dict(path=str(capture_receipt), sha256=sha(capture_receipt))]
    symbols, gaps = {}, []
    for code, binding in codes.items():
        if not code.endswith(".BJ"):
            raise QfqGateError(f"TDX_FALLBACK_OUTSIDE_ACCEPTED_BJ_POLICY:{code}")
        all_symbol_rows = frame.loc[frame.ts_code.eq(code)].copy()
        compute_start = binding.get("compute_start_date", binding["history_start_date"])
        selected = all_symbol_rows.loc[all_symbol_rows.datetime.gt(compute_start) & all_symbol_rows.datetime.le(target)].copy()
        unknown = sorted({int(c) for c in selected.category if str(int(c)) not in categories})
        events = []
        if not unknown:
            for row in selected.itertuples():
                action = categories[str(int(row.category))]
                if action == "CAPITAL_SNAPSHOT_RETAINED_NOT_PRICE_ACTION_IN_THIS_CONVENTION":
                    continue
                if int(row.category) != 1 or action != "PRICE_ACTION_PER10_CASH_RIGHTS_BONUS_AFFINE":
                    unknown.append(int(row.category))
                    continue
                cash, rights_price, bonus, rights = [float(v) for v in (row.hongli_panqianliutong, row.peigujia_qianzongguben, row.songgu_qianzongguben, row.peigu_houzongguben)]
                if not all(math.isfinite(v) for v in (cash, rights_price, bonus, rights)):
                    raise QfqGateError(f"TDX_EVENT_TERMS_MISSING:{code}:{row.datetime}")
                denominator = 1 + (bonus + rights) / 10
                if denominator <= 0:
                    raise QfqGateError(f"TDX_EVENT_DENOMINATOR_INVALID:{code}:{row.datetime}")
                events.append(dict(ex_date=int(row.datetime), a=1 / denominator,
                                   b=(-cash / 10 + rights_price * rights / 10) / denominator, volume_a=denominator))
        dates = [e["ex_date"] for e in events]
        if len(set(dates)) != len(dates):
            unknown.append("MULTIPLE_PRICE_EVENTS_SAME_EX_DATE")
        raw_rows_path = root / "official_gbbq" / "symbol_rows" / (canonical_sha(dict(code=code, raw=captured["raw"], schema="ALL_SYMBOL_ROWS_V1")) + ".json")
        rows = json.loads(all_symbol_rows.to_json(orient="records", double_precision=15))
        if not raw_rows_path.exists():
            _json(raw_rows_path, dict(ts_code=code, rows=rows))
        if unknown:
            blocked = selected.loc[selected.category.isin([c for c in unknown if isinstance(c, int)]), ["datetime", "category"]]
            gaps.append(dict(ts_code=code, categories=unknown, relevant_rows=json.loads(blocked.to_json(orient="records")), compute_start_date=compute_start, raw_rows=str(raw_rows_path)))
        symbols[code] = dict(events=sorted(events, key=lambda e: e["ex_date"]), event_coverage_complete=not unknown,
                             unsupported_categories=unknown, source_files=source_refs + [dict(path=str(raw_rows_path), sha256=sha(raw_rows_path))],
                             conversion_receipt=policy_ref, price_convention="TDX_GBBQ_CATEGORY1_AFFINE_BJ_V1_NOT_FUTU_EQUIVALENT",
                             compute_start_date=compute_start,
                             history_coverage_start_date=compute_start, history_coverage_end_date=target,
                             coverage_basis="ALL_ORIGINAL_GBBQ_SYMBOL_ROWS_REPLAYED_FROM_BOUND_START; CURRENT_CAPTURE_NOT_HISTORICAL_PIT",
                             future_event_count=int(all_symbol_rows.datetime.gt(target).sum()),
                             pre_compute_window_event_count=int(all_symbol_rows.datetime.le(compute_start).sum()))
    output = dict(asof_date=target, observed_at=captured["observed_at"], symbols=symbols, gaps=gaps, historical_PIT=False)
    _json(root / "tdx_official_adjustment_fallback.json", output)
    return output
