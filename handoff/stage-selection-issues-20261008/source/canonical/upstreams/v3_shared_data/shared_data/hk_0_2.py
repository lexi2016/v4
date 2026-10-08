"""Frozen HK Connect 0.2 D-1 Top100 producer and verified consumer.

The implementation below is a direct, path-neutral migration of the accepted
V3 ``tdx_vipdoc_71_day`` feature and ``prob_active`` scoring contract.  V3
files are accepted only by the explicit one-time asset importer.  Normal
materialization reads assets owned by this shared store and never imports V3.
"""
from __future__ import annotations

import base64
import binascii
import csv
import json
import math
import os
import platform
import shutil
import struct
import tempfile
from datetime import datetime
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from .allowlist import AllowlistRegistry, SourceSpec
from .consumer import VerifiedRun, read_verified_latest
from .hashing import canonical_bytes, sha256_file
from .paths import resolve_under, validate_date
from .store import SafeRootStore, StoreError


HK_0_2_ROLE = "HK_CONNECT_D1_TOP100_0_2"
HK_0_2_STAGE_ID = "D1_PREMARKET"
HK_0_2_MODEL_SHA256 = "3b0d5d5239342439cabf25b30012365a64d78839bc3cd4d90bad7be6ff4aaa07"
HK_0_2_MODEL_TRAINED_THROUGH = "20260716"
HK_0_2_PYTHON_VERSION = "3.13.12"
HK_0_2_SKLEARN_VERSION = "1.9.0"
HK_0_2_JOBLIB_VERSION = "1.5.3"
HK_0_2_ORACLE_SHA256S = {
    "daily_features": "6604c499f7b3dbbed4b8493c6574c1f2ca6af52125cfe9f7d5f740cf01c94228",
    "proxy_prob_active": "6248bc44d77500185d9eae88fe575ed0dfe617f6f4e6649e3f6e82aa8f65fc5f",
}
_MODEL_NAMES = ("extra_trees", "hgb_depth6", "logit", "random_forest")
_WINDOWS = (1, 2, 3, 5, 10, 20, 40, 60, 120)
_VIPDOC_DAY_STRUCT = struct.Struct("<IfffffII")
_MAX_CROSS_DAY_CLOSE_RATIO = 1.5
_MAX_PRE_CLOSE_GAP_CALENDAR_DAYS = 14


def _capture_date_shanghai(value: Any) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise StoreError("HK 0.2 security-master capture time is invalid") from error
    if parsed.tzinfo is None:
        raise StoreError("HK 0.2 security-master capture time must include a timezone")
    return parsed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


_CAPTURE_AT_PROVENANCE_PREFIX = "b64url."


def _encode_capture_at_provenance(value: Any) -> str:
    """Preserve the exact capture timestamp in a path-neutral token.

    Provenance values are deliberately forbidden from containing path
    separators and colons.  ISO timestamps contain colons, so encode their
    original UTF-8 bytes with URL-safe Base64 before placing them in a
    ``SourceSpec``.  The original timestamp remains recoverable without
    changing its precision, offset, or spelling.
    """

    text = str(value or "").strip()
    if not text:
        raise StoreError("HK 0.2 security-master capture time is invalid")
    _capture_date_shanghai(text)
    encoded = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
    token = f"{_CAPTURE_AT_PROVENANCE_PREFIX}{encoded}"
    if any(character in token for character in (":", "/", "\\")):
        raise StoreError("HK 0.2 capture-time provenance token is not path-neutral")
    return token


def _decode_capture_at_provenance(value: Any) -> str:
    """Decode new capture-time tokens while accepting legacy raw timestamps."""

    text = str(value or "").strip()
    if not text.startswith(_CAPTURE_AT_PROVENANCE_PREFIX):
        # Older receipts stored the timestamp as plain text.  Keep those
        # readable even though new writes must satisfy SourceSpec's neutral
        # provenance contract.
        return text
    encoded = text[len(_CAPTURE_AT_PROVENANCE_PREFIX) :]
    try:
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise StoreError("HK 0.2 security-master capture provenance is invalid") from error
    _capture_date_shanghai(decoded)
    return decoded

_OUTPUT_FIELDS = (
    "trade_date", "bar_time", "rank", "code", "code_norm", "ts_code", "name",
    "signal_date", "target_date", "selected_strategy", "weekly_tuning_selected_strategy",
    "pool_version", "freeze_status", "recommendation_status", "trade_status_contract",
    "production_allowed", "lane", "score_fixed_4model_old_weight", "score_prob_active",
    "score_equal_4model", "score_prob_memory", "score_prob_crash_reflow",
    "score_hgb_depth6", "score_extra_trees", "score_random_forest", "score_logit",
    "hybrid_score", "memory_score", "active_score", "crash_reflow_score",
    "oversold_score", "pct_chg", "d1_snapshot_close_hkd", "d1_snapshot_prev_close_hkd",
    "intraday_high_pct", "amplitude_pct", "amount", "amount_ratio_20d", "ret_5d",
    "ret_20d", "ret_60d", "dd_from_60d_high", "close_pos_60d",
    "recent_top20_count_20d", "last_top20_days_ago", "candidate_pool_time",
    "data_cutoff", "research_only", "cannot_confirm", "pct_chg_original_vipdoc",
    "pct_chg_source", "pct_chg_diff_pct", "d1_freshness_status",
    "d1_freshness_source", "d1_close_hkd", "d1_prev_close_hkd",
)


@dataclass(frozen=True)
class FrozenHK02Assets:
    root: Path
    panel_path: Path
    panel_manifest: dict[str, Any]
    model_path: Path
    model_manifest: dict[str, Any]
    name_dictionary_path: Path | None


@dataclass(frozen=True)
class HistoricalHK02ResearchAsset:
    """A checksum-bound historical daily-bar asset for research readers.

    ``FrozenHK02Assets`` is the live/D-1 panel contract and intentionally
    remains unchanged.  This separate value object is only for an explicitly
    supplied historical parquet plus its source manifest.  It keeps the
    source bytes immutable while allowing a V4 research consumer to record the
    source identity before deriving a calendar-indexed view.
    """

    source_path: Path
    source_manifest_path: Path
    source_sha256: str
    source_manifest: dict[str, Any]
    frame: Any


@dataclass(frozen=True)
class VerifiedHK02Pool:
    run: VerifiedRun
    rows: tuple[dict[str, str], ...]


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "MISSING"


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(handle, "wb") as output, open(source, "rb") as input_file:
            shutil.copyfileobj(input_file, output, length=1 << 20)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(f"invalid HK 0.2 json: {path.name}: {error}") from error
    if not isinstance(value, Mapping):
        raise StoreError(f"HK 0.2 json is not an object: {path.name}")
    return dict(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write(path, canonical_bytes(dict(payload)))


def load_historical_hk_0_2_research_asset(
    source_path: Path | str,
    *,
    source_manifest_path: Path | str | None = None,
    expected_sha256: str | None = None,
) -> HistoricalHK02ResearchAsset:
    """Read one source-backed historical daily-bar parquet for research.

    The live ``load_frozen_hk_0_2_assets`` reader validates the sparse panel
    pointer and the frozen model bundle.  Historical prefix research has a
    different, explicit input contract, so it uses this narrow reader instead
    of changing daily materialization.  The reader verifies the source file
    bytes, the package manifest safety flags and the exact source schema; it
    does not fill missing bars, infer a market calendar, or read labels.

    ``expected_sha256`` is required by callers that want a frozen source
    identity.  It is optional for small unit fixtures so the schema and
    uniqueness checks can still be exercised without a hard-coded digest.
    """

    import pandas as pd

    source = Path(source_path)
    if not source.is_file():
        raise StoreError(f"historical HK 0.2 source is missing: {source}")
    source_sha256 = sha256_file(source)
    if expected_sha256 is not None and source_sha256 != str(expected_sha256).strip().lower():
        raise StoreError("historical HK 0.2 source checksum mismatch")

    manifest_path = (
        Path(source_manifest_path)
        if source_manifest_path is not None
        else source.parent.parent / "manifest.json"
    )
    if not manifest_path.is_file():
        raise StoreError("historical HK 0.2 source manifest is missing")
    manifest = _read_json(manifest_path)
    if manifest.get("status") not in {"PARTIAL", "ACCEPTED_RESEARCH_DELIVERY", "READY"}:
        raise StoreError("historical HK 0.2 source manifest status is not research-readable")
    safety = manifest.get("safety")
    if not isinstance(safety, Mapping):
        raise StoreError("historical HK 0.2 source safety manifest is missing")
    if (
        safety.get("research_only") is not True
        or safety.get("production_allowed") is not False
        or safety.get("buy_gate_updated") is not False
        or safety.get("orders_sent") is not False
    ):
        raise StoreError("historical HK 0.2 source safety flags are unsafe")

    required = ("code", "date", "open", "high", "low", "close", "trade", "amount")
    try:
        frame = pd.read_parquet(source, columns=list(required))
    except (OSError, ValueError, ImportError) as error:
        raise StoreError(f"cannot read historical HK 0.2 parquet: {error}") from error
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise StoreError("historical HK 0.2 source schema missing: " + ",".join(missing))
    frame = frame[list(required)].copy()
    frame["code"] = frame["code"].astype(str).str.strip().str.upper()
    parsed_dates = pd.to_datetime(frame["date"], errors="coerce")
    if parsed_dates.isna().any():
        raise StoreError("historical HK 0.2 source contains invalid dates")
    frame["date"] = parsed_dates.dt.strftime("%Y-%m-%d")
    if frame[["code", "date"]].duplicated(keep=False).any():
        raise StoreError("historical HK 0.2 source contains duplicate code/date rows")
    if frame["code"].eq("").any():
        raise StoreError("historical HK 0.2 source contains empty codes")
    frame = frame.sort_values(["code", "date"], kind="mergesort").reset_index(drop=True)
    return HistoricalHK02ResearchAsset(
        source_path=source,
        source_manifest_path=manifest_path,
        source_sha256=source_sha256,
        source_manifest=manifest,
        frame=frame,
    )


# Explicit alias used by research-only callers; keep the live reader name
# above separate so existing daily code cannot accidentally consume history.
read_historical_hk_0_2_research_asset = load_historical_hk_0_2_research_asset


def _validate_model_manifest(manifest: Mapping[str, Any], bundle_path: Path) -> None:
    expected = {
        "schema_version": "hkconnect_d1_model_bundle.v1",
        "trained_through": HK_0_2_MODEL_TRAINED_THROUGH,
        "feature_count": 155,
        "model_names": list(_MODEL_NAMES),
        "bundle_file": "models.joblib",
        "bundle_sha256": HK_0_2_MODEL_SHA256,
        "python_version": HK_0_2_PYTHON_VERSION,
        "sklearn_version": HK_0_2_SKLEARN_VERSION,
        "joblib_version": HK_0_2_JOBLIB_VERSION,
        "primary_strategy": "prob_active",
        "research_only": True,
        "production_allowed": False,
    }
    for key, value in expected.items():
        actual = manifest.get(key)
        if key == "model_names":
            actual = sorted(actual or [])
        if actual != value:
            raise StoreError(f"HK 0.2 frozen model manifest mismatch: {key}")
    features = list(manifest.get("feature_columns") or [])
    if len(features) != 155 or len(set(features)) != 155:
        raise StoreError("HK 0.2 frozen feature contract mismatch")
    if not bundle_path.is_file() or sha256_file(bundle_path) != HK_0_2_MODEL_SHA256:
        raise StoreError("HK 0.2 frozen model bundle checksum mismatch")


def import_frozen_hk_0_2_assets(
    asset_root: Path | str,
    *,
    panel_path: Path | str,
    model_manifest_path: Path | str,
    model_bundle_path: Path | str,
    expected_panel_sha256: str,
    name_dictionary_path: Path | str | None = None,
) -> FrozenHK02Assets:
    """One-time explicit import; persisted metadata is path-neutral."""
    asset_root = Path(asset_root)
    panel_path = Path(panel_path)
    model_manifest_path = Path(model_manifest_path)
    model_bundle_path = Path(model_bundle_path)
    if not panel_path.is_file() or sha256_file(panel_path) != expected_panel_sha256.lower():
        raise StoreError("HK 0.2 seed panel checksum mismatch")
    model_manifest = _read_json(model_manifest_path)
    _validate_model_manifest(model_manifest, model_bundle_path)

    import pandas as pd

    panel = pd.read_parquet(panel_path, columns=["trade_date_compact", "code_norm"])
    if panel.empty:
        raise StoreError("HK 0.2 seed panel is empty")
    panel_max_date = str(panel["trade_date_compact"].astype(str).max())
    panel_rows = int(len(panel))
    panel_codes = int(panel["code_norm"].astype(str).nunique())

    model_dir = asset_root / "model" / HK_0_2_MODEL_TRAINED_THROUGH
    panel_dir = asset_root / "panels" / f"{panel_max_date}-{expected_panel_sha256[:12].lower()}"
    destination_model = model_dir / "models.joblib"
    destination_panel = panel_dir / "hkconnect_vipdoc_daily_panel.parquet"
    for source, destination in ((model_bundle_path, destination_model), (panel_path, destination_panel)):
        if destination.exists():
            if sha256_file(destination) != sha256_file(source):
                raise StoreError(f"HK 0.2 immutable asset conflict: {destination.name}")
        else:
            _atomic_copy(source, destination)

    stored_model_manifest = {
        key: value for key, value in model_manifest.items() if key not in {"bundle_path", "created_at"}
    }
    stored_model_manifest.update(
        {
            "asset_schema_version": "v3_shared_data.hk_0_2_model_asset.v1",
            "bundle_relative": f"model/{HK_0_2_MODEL_TRAINED_THROUGH}/models.joblib",
            "oracle_sha256s": dict(HK_0_2_ORACLE_SHA256S),
        }
    )
    stored_panel_manifest = {
        "asset_schema_version": "v3_shared_data.hk_0_2_panel_asset.v1",
        "source_contract": "tdx_vipdoc_71_day+verified_zero_trade_repairs",
        "panel_relative": f"panels/{panel_dir.name}/hkconnect_vipdoc_daily_panel.parquet",
        "panel_sha256": expected_panel_sha256.lower(),
        "panel_rows": panel_rows,
        "panel_code_count": panel_codes,
        "panel_max_date": panel_max_date,
        "research_only": True,
        "production_allowed": False,
    }
    _write_json(model_dir / "manifest.json", stored_model_manifest)
    _write_json(panel_dir / "manifest.json", stored_panel_manifest)
    _write_json(asset_root / "model_latest.json", {"manifest_relative": f"model/{HK_0_2_MODEL_TRAINED_THROUGH}/manifest.json"})
    _write_json(asset_root / "panel_latest.json", {"manifest_relative": f"panels/{panel_dir.name}/manifest.json"})
    if name_dictionary_path is not None:
        import_hk_0_2_name_dictionary(asset_root, name_dictionary_path)
    return load_frozen_hk_0_2_assets(asset_root)


def import_hk_0_2_name_dictionary(asset_root: Path | str, source_path: Path | str) -> dict[str, Any]:
    """Import only the code/name columns used by the frozen V3 name fill."""
    import pandas as pd

    asset_root, source_path = Path(asset_root), Path(source_path)
    if not source_path.is_file():
        raise StoreError("HK 0.2 name dictionary missing")
    frame = pd.read_csv(source_path, encoding="utf-8-sig")
    if not {"code", "name"}.issubset(frame.columns):
        raise StoreError("HK 0.2 name dictionary fields missing")
    frame = frame[["code", "name"]].copy()
    frame["code"] = frame["code"].map(_normalize_code)
    frame["name"] = frame["name"].fillna("").astype(str).str.strip()
    frame = frame[frame["code"].ne("") & frame["name"].ne("")].drop_duplicates("code", keep="last").sort_values("code")
    destination = asset_root / "names" / "hk_name_dictionary.csv"
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(temporary, index=False, encoding="utf-8-sig", lineterminator="\n")
    os.replace(temporary, destination)
    manifest = {
        "asset_schema_version": "v3_shared_data.hk_0_2_name_dictionary.v1",
        "dictionary_relative": "names/hk_name_dictionary.csv",
        "dictionary_sha256": sha256_file(destination),
        "row_count": int(len(frame)),
        "research_only": True,
        "production_allowed": False,
    }
    _write_json(asset_root / "names" / "manifest.json", manifest)
    _write_json(asset_root / "name_latest.json", {"manifest_relative": "names/manifest.json"})
    return manifest


def compose_historical_hk_0_2_seed(
    *,
    base_panel_path: Path | str,
    prior_signal_panel_root: Path | str,
    signal_date: str,
    destination: Path | str,
) -> dict[str, Any]:
    """Reproduce V3's one-time historical panel overlay into a standalone seed.

    This function is intentionally import-only.  Daily materialization never
    calls it and therefore never reads the V3 workbench.
    """
    import pandas as pd

    signal_date = validate_date(signal_date)
    base_panel_path = Path(base_panel_path)
    prior_signal_panel_root = Path(prior_signal_panel_root)
    destination = Path(destination)
    if not base_panel_path.is_file() or not prior_signal_panel_root.is_dir():
        raise StoreError("HK 0.2 historical seed inputs are missing")
    parts = [pd.read_parquet(base_panel_path)]
    included_sha256s: list[str] = []
    for path in sorted(prior_signal_panel_root.glob("*_hkconnect_d1_pool/hkconnect_d1_close_panel_*.parquet")):
        frame = pd.read_parquet(path)
        if "trade_date_compact" not in frame.columns:
            continue
        dates = sorted(str(value) for value in frame["trade_date_compact"].dropna().unique())
        if dates and max(dates) <= signal_date:
            parts.append(frame)
            included_sha256s.append(sha256_file(path))
    panel = pd.concat(parts, ignore_index=True)
    panel["trade_date_compact"] = panel["trade_date_compact"].astype(str)
    panel["code_norm"] = panel["code_norm"].map(_normalize_code)
    panel = panel.drop_duplicates(["trade_date_compact", "code_norm"], keep="last")
    panel = panel[panel["trade_date_compact"].le(signal_date)].copy()
    panel = panel.sort_values(["code_norm", "trade_date_compact"]).reset_index(drop=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    panel.to_parquet(temporary, index=False)
    os.replace(temporary, destination)
    return {
        "panel_path": str(destination),
        "panel_sha256": sha256_file(destination),
        "panel_rows": int(len(panel)),
        "panel_code_count": int(panel["code_norm"].nunique()),
        "panel_max_date": str(panel["trade_date_compact"].max()),
        "historical_signal_panel_count": len(included_sha256s),
        "historical_signal_panel_sha256s": included_sha256s,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _vipdoc_lday_root(tdx_root: Path) -> Path:
    candidates = (tdx_root / "vipdoc" / "ds" / "lday", tdx_root)
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("71#*.day")):
            return candidate
    raise StoreError("HK 0.2 VIPDOC lday source is missing")


def _read_vipdoc_increment(
    lday_root: Path,
    *,
    after_date: str,
    through_date: str,
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    files = sorted(lday_root.glob("71#*.day"))
    for path in files:
        code = _normalize_code(path.stem)
        raw_code = code.replace("HK.", "")
        if not code:
            continue
        size = path.stat().st_size
        if size % _VIPDOC_DAY_STRUCT.size:
            raise StoreError(f"HK 0.2 VIPDOC file has trailing bytes: {path.name}")
        with path.open("rb") as handle:
            while raw := handle.read(_VIPDOC_DAY_STRUCT.size):
                date_int, open_v, high_v, low_v, close_v, amount_v, trade_v, position_v = _VIPDOC_DAY_STRUCT.unpack(raw)
                date_text = _compact_date(date_int)
                if not date_text or date_text <= after_date or date_text > through_date:
                    continue
                if (
                    min(open_v, high_v, low_v, close_v) <= 0
                    or high_v < low_v
                    or close_v > high_v
                    or close_v < low_v
                ):
                    continue
                rows.append(
                    {
                        "trade_date": int(date_text),
                        "trade_date_compact": date_text,
                        "code_norm": code,
                        "ts_code": f"{raw_code}.HK_CONNECT",
                        "raw_code": raw_code,
                        "market_type": "HK",
                        "exchange": "HK_CONNECT",
                        "open": float(open_v),
                        "high": float(high_v),
                        "low": float(low_v),
                        "close": float(close_v),
                        "amount": float(amount_v),
                        "trade": int(trade_v),
                        "position": int(position_v),
                        "source": "tdx_vipdoc_71_day",
                        "source_path": f"vipdoc/ds/lday/{path.name}",
                        "name": "",
                    }
                )
    return rows, len(files)


def _enrich_vipdoc_increment(existing, increment):
    import numpy as np
    import pandas as pd

    if increment.empty:
        return increment
    prior_by_code = {
        str(code): group.sort_values("trade_date_compact").iloc[-1]
        for code, group in existing.groupby("code_norm", sort=False)
    }
    enriched: list[dict[str, Any]] = []
    for code, group in increment.sort_values(["code_norm", "trade_date_compact"]).groupby("code_norm", sort=True):
        prior = prior_by_code.get(str(code))
        for _, item in group.iterrows():
            row = item.to_dict()
            break_reason = ""
            pre_close: float | None = None
            prior_segment = 0
            if prior is None:
                break_reason = "first_observation"
            else:
                prior_close = float(prior["close"])
                prior_date = datetime.strptime(str(prior["trade_date_compact"]), "%Y%m%d")
                current_date = datetime.strptime(str(row["trade_date_compact"]), "%Y%m%d")
                prior_segment_value = prior.get("continuity_segment_id", 1)
                prior_segment = int(prior_segment_value) if pd.notna(prior_segment_value) else 1
                close_ratio = float(row["close"]) / prior_close if prior_close > 0 else math.inf
                if (current_date - prior_date).days > _MAX_PRE_CLOSE_GAP_CALENDAR_DAYS:
                    break_reason = "long_calendar_gap"
                elif close_ratio > _MAX_CROSS_DAY_CLOSE_RATIO or close_ratio < 1.0 / _MAX_CROSS_DAY_CLOSE_RATIO:
                    break_reason = "cross_day_close_ratio"
                else:
                    pre_close = prior_close
            row["continuity_break"] = break_reason
            row["pre_close"] = pre_close
            row["continuity_segment_id"] = max(prior_segment, 0) + (1 if break_reason else 0)
            row["pct_chg"] = (float(row["close"]) / pre_close - 1.0) * 100.0 if pre_close else np.nan
            row["amplitude_pct"] = (float(row["high"]) - float(row["low"])) / pre_close * 100.0 if pre_close else np.nan
            row["intraday_high_pct"] = (float(row["high"]) / pre_close - 1.0) * 100.0 if pre_close else np.nan
            enriched.append(row)
            prior = pd.Series(row)
    return pd.DataFrame(enriched)


def update_hk_0_2_panel_from_vipdoc(
    asset_root: Path | str,
    *,
    tdx_root: Path | str,
    through_date: str,
    minimum_code_count: int = 500,
    minimum_positive_coverage_rate: float = 0.80,
) -> dict[str, Any]:
    """Append verified VIPDOC daily rows and atomically advance ``panel_latest``.

    The updater owns only shared-store assets.  It never imports V3 runtime
    output and refuses to publish a date with thin or market-wide zero-trade
    coverage.
    """
    import pandas as pd

    through_date = validate_date(through_date)
    asset_root = Path(asset_root)
    assets = load_frozen_hk_0_2_assets(asset_root)
    existing = pd.read_parquet(assets.panel_path)
    if existing.empty or not {"trade_date_compact", "code_norm", "close"}.issubset(existing.columns):
        raise StoreError("HK 0.2 current panel is invalid")
    existing["trade_date_compact"] = existing["trade_date_compact"].astype(str)
    current_max = str(existing["trade_date_compact"].max())
    if through_date <= current_max:
        day = existing[existing["trade_date_compact"].eq(through_date)]
        if day["code_norm"].nunique() < minimum_code_count:
            raise StoreError("HK 0.2 existing through-date coverage below minimum")
        pointer = _read_json(asset_root / "panel_latest.json")
        return {
            "status": "READY",
            "already_current": True,
            "through_date": through_date,
            "through_date_code_count": int(day["code_norm"].nunique()),
            "panel_sha256": str(assets.panel_manifest.get("panel_sha256") or ""),
            "manifest_relative": str(pointer.get("manifest_relative") or ""),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    lday_root = _vipdoc_lday_root(Path(tdx_root))
    raw_rows, source_file_count = _read_vipdoc_increment(
        lday_root,
        after_date=current_max,
        through_date=through_date,
    )
    increment = pd.DataFrame(raw_rows)
    if increment.empty or through_date not in set(increment.get("trade_date_compact", pd.Series(dtype=str)).astype(str)):
        raise StoreError(f"HK 0.2 VIPDOC through date is absent: {through_date}")
    increment = increment.drop_duplicates(["trade_date_compact", "code_norm"], keep="last")
    day = increment[increment["trade_date_compact"].eq(through_date)]
    code_count = int(day["code_norm"].nunique())
    if code_count < minimum_code_count:
        raise StoreError(f"HK 0.2 through-date market coverage below {minimum_code_count}")
    positive_trade_rate = float(pd.to_numeric(day["trade"], errors="coerce").fillna(0).gt(0).mean())
    positive_amount_rate = float(pd.to_numeric(day["amount"], errors="coerce").fillna(0).gt(0).mean())
    if min(positive_trade_rate, positive_amount_rate) < minimum_positive_coverage_rate:
        raise StoreError("HK 0.2 through-date positive coverage below 80%")

    enriched = _enrich_vipdoc_increment(existing, increment)
    output = pd.concat([existing, enriched], ignore_index=True)
    output["trade_date_compact"] = output["trade_date_compact"].astype(str)
    output["code_norm"] = output["code_norm"].map(_normalize_code)
    output = output.drop_duplicates(["trade_date_compact", "code_norm"], keep="last")
    output = output.sort_values(["code_norm", "trade_date_compact"]).reset_index(drop=True)

    staging = asset_root / "panels" / f".panel-{through_date}-{os.getpid()}.parquet"
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.to_parquet(staging, index=False)
        panel_sha = sha256_file(staging)
        panel_dir = asset_root / "panels" / f"{through_date}-{panel_sha[:12]}"
        destination = panel_dir / "hkconnect_vipdoc_daily_panel.parquet"
        if destination.exists():
            if sha256_file(destination) != panel_sha:
                raise StoreError("HK 0.2 immutable daily panel conflict")
            staging.unlink()
        else:
            panel_dir.mkdir(parents=True, exist_ok=True)
            os.replace(staging, destination)
    finally:
        if staging.exists():
            staging.unlink()
    manifest = {
        "asset_schema_version": "v3_shared_data.hk_0_2_panel_asset.v2",
        "source_contract": "tdx_vipdoc_71_day+verified_zero_trade_repairs",
        "increment_contract": "tdx_vipdoc_71_day_daily_append.v1",
        "panel_relative": f"panels/{panel_dir.name}/hkconnect_vipdoc_daily_panel.parquet",
        "panel_sha256": panel_sha,
        "parent_panel_sha256": str(assets.panel_manifest.get("panel_sha256") or ""),
        "panel_rows": int(len(output)),
        "panel_code_count": int(output["code_norm"].nunique()),
        "panel_max_date": through_date,
        "new_row_count": int(len(enriched)),
        "new_dates": sorted(set(enriched["trade_date_compact"].astype(str))),
        "through_date_code_count": code_count,
        "positive_trade_coverage_rate": positive_trade_rate,
        "positive_amount_coverage_rate": positive_amount_rate,
        "source_file_count": source_file_count,
        "source_location_contract": "vipdoc/ds/lday/71#*.day",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    manifest_relative = f"panels/{panel_dir.name}/manifest.json"
    _write_json(panel_dir / "manifest.json", manifest)
    _write_json(asset_root / "panel_latest.json", {"manifest_relative": manifest_relative})
    return {
        "status": "READY",
        "already_current": False,
        "through_date": through_date,
        "through_date_code_count": code_count,
        "new_row_count": int(len(enriched)),
        "panel_sha256": panel_sha,
        "manifest_relative": manifest_relative,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _resolve_asset_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise StoreError("HK 0.2 asset path escapes root") from error
    return candidate


def load_frozen_hk_0_2_assets(asset_root: Path | str) -> FrozenHK02Assets:
    root = Path(asset_root)
    panel_pointer = _read_json(root / "panel_latest.json")
    model_pointer = _read_json(root / "model_latest.json")
    panel_manifest_path = _resolve_asset_path(root, str(panel_pointer.get("manifest_relative") or ""))
    model_manifest_path = _resolve_asset_path(root, str(model_pointer.get("manifest_relative") or ""))
    panel_manifest = _read_json(panel_manifest_path)
    model_manifest = _read_json(model_manifest_path)
    panel_path = _resolve_asset_path(root, str(panel_manifest.get("panel_relative") or ""))
    model_path = _resolve_asset_path(root, str(model_manifest.get("bundle_relative") or ""))
    if sha256_file(panel_path) != str(panel_manifest.get("panel_sha256") or ""):
        raise StoreError("HK 0.2 stored panel checksum mismatch")
    _validate_model_manifest(model_manifest, model_path)
    if dict(model_manifest.get("oracle_sha256s") or {}) != HK_0_2_ORACLE_SHA256S:
        raise StoreError("HK 0.2 oracle sha contract mismatch")
    name_dictionary_path: Path | None = None
    if (root / "name_latest.json").is_file():
        name_pointer = _read_json(root / "name_latest.json")
        name_manifest = _read_json(_resolve_asset_path(root, str(name_pointer.get("manifest_relative") or "")))
        name_dictionary_path = _resolve_asset_path(root, str(name_manifest.get("dictionary_relative") or ""))
        if sha256_file(name_dictionary_path) != str(name_manifest.get("dictionary_sha256") or ""):
            raise StoreError("HK 0.2 name dictionary checksum mismatch")
    return FrozenHK02Assets(root, panel_path, panel_manifest, model_path, model_manifest, name_dictionary_path)


def _compact_date(value: Any) -> str:
    text = "".join(ch for ch in str(value or "") if ch.isdigit())
    return text[:8] if len(text) >= 8 else ""


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper().replace("HK.", "").replace(".HK_CONNECT", "").replace(".HK", "")
    digits = "".join(ch for ch in text if ch.isdigit())
    return f"HK.{digits[-5:].zfill(5)}" if digits else ""


def _is_name_code_placeholder(code: Any, name: Any) -> bool:
    """Return whether a pool name is empty or merely a code placeholder."""
    text = str(name or "").strip()
    normalized_code = _normalize_code(code)
    if not text:
        return True
    if not normalized_code:
        return False
    raw_code = normalized_code[3:]
    return text.upper() in {
        normalized_code,
        raw_code,
        f"{raw_code}.HK",
        f"{raw_code}.HK_CONNECT",
    }


def _load_verified_security_master(
    store_root: Path | str, signal_date: str
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Load the signal-date master through its checksum-verified reader.

    The HK 0.2 producer is deliberately coupled to this shared, read-only
    reference.  The reader validates the latest pointer, manifest, receipt,
    artifact SHA and safety flags; callers must retain the returned identity
    in their own provenance rather than trusting an unverified CSV.
    """
    from .hk_security_master import load_verified_hk_security_master

    try:
        rows, manifest = load_verified_hk_security_master(store_root, signal_date)
    except StoreError as error:
        raise StoreError(f"HK security master verification failed: {error}") from error
    run_id = str(manifest.get("run_id") or "").strip()
    artifact_sha256 = str(manifest.get("artifact_sha256") or "").strip().lower()
    if not run_id or len(artifact_sha256) != 64:
        raise StoreError("HK security master provenance missing")
    return rows, manifest


def _fill_name_placeholders(
    rows: Iterable[Mapping[str, Any]],
    security_master: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Fill only blank/code names; preserve every existing non-empty name."""
    enriched: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        code = _normalize_code(row.get("code_norm") or row.get("code"))
        name = str(row.get("name") or "").strip()
        if _is_name_code_placeholder(code, name):
            master_row = security_master.get(code)
            verified_name = str((master_row or {}).get("name") or "").strip()
            if _is_name_code_placeholder(code, verified_name):
                raise StoreError(f"HK security master name missing: {code}")
            row["name"] = verified_name
        enriched.append(row)
    return enriched


def _add_daily_features(panel):
    import numpy as np
    import pandas as pd

    frame = panel.copy()
    frame["trade_date_compact"] = frame["trade_date_compact"].map(_compact_date)
    frame["code_norm"] = frame["code_norm"].map(_normalize_code)
    frame = frame[frame["trade_date_compact"].str.len().eq(8) & frame["code_norm"].str.startswith("HK.")].copy()
    frame = frame.sort_values(["code_norm", "trade_date_compact"]).reset_index(drop=True)
    grouped = frame.groupby("code_norm", group_keys=False)
    if "pre_close" not in frame.columns or frame["pre_close"].isna().all():
        frame["pre_close"] = grouped["close"].shift(1)
    frame["gap_open_pct"] = np.where(frame["pre_close"] > 0, (frame["open"] / frame["pre_close"] - 1.0) * 100.0, np.nan)
    frame["intraday_high_pct"] = np.where(frame["pre_close"] > 0, (frame["high"] / frame["pre_close"] - 1.0) * 100.0, np.nan)
    frame["intraday_low_pct"] = np.where(frame["pre_close"] > 0, (frame["low"] / frame["pre_close"] - 1.0) * 100.0, np.nan)
    frame["pct_chg"] = np.where(frame["pre_close"] > 0, (frame["close"] / frame["pre_close"] - 1.0) * 100.0, np.nan)
    frame["amplitude_pct"] = np.where(frame["pre_close"] > 0, (frame["high"] - frame["low"]) / frame["pre_close"] * 100.0, np.nan)
    frame["upper_shadow_pct"] = np.where(frame["pre_close"] > 0, (frame["high"] - frame[["open", "close"]].max(axis=1)) / frame["pre_close"] * 100.0, np.nan)
    frame["lower_shadow_pct"] = np.where(frame["pre_close"] > 0, (frame[["open", "close"]].min(axis=1) - frame["low"]) / frame["pre_close"] * 100.0, np.nan)
    frame["close_in_bar_pos"] = np.where((frame["high"] - frame["low"]) > 0, (frame["close"] - frame["low"]) / (frame["high"] - frame["low"]), np.nan)
    frame["amount_log"] = np.log1p(frame["amount"].clip(lower=0))
    frame["listing_age_days_in_panel"] = frame.groupby("code_norm").cumcount() + 1
    frame["panel_first_date"] = frame.groupby("code_norm")["trade_date_compact"].transform("min")
    for window in _WINDOWS:
        if window > 1:
            frame[f"ret_{window}d"] = (frame["close"] / grouped["close"].shift(window) - 1.0) * 100.0
        frame[f"amount_ma{window}"] = grouped["amount"].rolling(window, min_periods=1).mean().reset_index(level=0, drop=True)
        frame[f"amount_ratio_{window}d"] = np.where(frame[f"amount_ma{window}"] > 0, frame["amount"] / frame[f"amount_ma{window}"], np.nan)
        high = grouped["high"].rolling(window, min_periods=1).max().reset_index(level=0, drop=True)
        low = grouped["low"].rolling(window, min_periods=1).min().reset_index(level=0, drop=True)
        frame[f"high_{window}d"], frame[f"low_{window}d"] = high, low
        frame[f"dd_from_{window}d_high"] = (frame["close"] / high - 1.0) * 100.0
        frame[f"bounce_from_{window}d_low"] = (frame["close"] / low - 1.0) * 100.0
        frame[f"close_pos_{window}d"] = np.where((high - low) > 0, (frame["close"] - low) / (high - low), np.nan)
        frame[f"amp_max_{window}d"] = grouped["amplitude_pct"].rolling(window, min_periods=1).max().reset_index(level=0, drop=True)
        frame[f"intraday_high_max_{window}d"] = grouped["intraday_high_pct"].rolling(window, min_periods=1).max().reset_index(level=0, drop=True)
        frame[f"pct_chg_min_{window}d"] = grouped["pct_chg"].rolling(window, min_periods=1).min().reset_index(level=0, drop=True)
        frame[f"pct_chg_max_{window}d"] = grouped["pct_chg"].rolling(window, min_periods=1).max().reset_index(level=0, drop=True)
    for window in (2, 3, 5):
        frame[f"crash_after_high_{window}d"] = (frame["close"] / grouped["high"].shift(window) - 1.0) * 100.0
        frame[f"ret_from_close_{window}d"] = (frame["close"] / grouped["close"].shift(window) - 1.0) * 100.0
    positive, negative = frame["pct_chg"] > 0, frame["pct_chg"] < 0
    frame["up_days_5d"] = positive.groupby(frame["code_norm"]).rolling(5, min_periods=1).sum().reset_index(level=0, drop=True)
    frame["down_days_5d"] = negative.groupby(frame["code_norm"]).rolling(5, min_periods=1).sum().reset_index(level=0, drop=True)
    frame["up_days_10d"] = positive.groupby(frame["code_norm"]).rolling(10, min_periods=1).sum().reset_index(level=0, drop=True)
    frame["down_days_10d"] = negative.groupby(frame["code_norm"]).rolling(10, min_periods=1).sum().reset_index(level=0, drop=True)
    return frame


def _add_proxy_labels(features):
    import numpy as np

    out = features.copy()
    out["pullback"] = (out["intraday_high_pct"] - out["pct_chg"]) / np.maximum(out["intraday_high_pct"].abs(), 1.0)
    out["is_intraday_top20"] = out["is_close_top20"] = out["is_daily_tradable_proxy"] = 0
    proxy_map: dict[str, list[str]] = {}
    for date_value, day in out.groupby("trade_date_compact", sort=True):
        day = day.dropna(subset=["intraday_high_pct", "pct_chg", "pre_close"])
        if day["code_norm"].nunique() < 80:
            continue
        intr = day.sort_values(["intraday_high_pct", "amount"], ascending=[False, False]).head(20)
        close = day.sort_values(["pct_chg", "amount"], ascending=[False, False]).head(20)
        intr_codes = set(intr["code_norm"].map(_normalize_code))
        close_codes = set(close["code_norm"].map(_normalize_code))
        proxy = day[day["code_norm"].map(_normalize_code).isin(intr_codes) & (day["pct_chg"] >= np.maximum(3.0, day["intraday_high_pct"] * 0.35)) & (day["pullback"] <= 0.65)]
        proxy = proxy.sort_values(["intraday_high_pct", "pct_chg", "amount"], ascending=[False, False, False])
        d = str(date_value)
        proxy_map[d] = list(proxy["code_norm"].map(_normalize_code))
        index = out["trade_date_compact"].eq(date_value)
        out.loc[index & out["code_norm"].isin(intr_codes), "is_intraday_top20"] = 1
        out.loc[index & out["code_norm"].isin(close_codes), "is_close_top20"] = 1
        out.loc[index & out["code_norm"].isin(proxy_map[d]), "is_daily_tradable_proxy"] = 1
    return out, proxy_map


def _add_proxy_memory(features, proxy_map):
    import pandas as pd

    dates = sorted(features["trade_date_compact"].dropna().unique())
    code_dates = features[["trade_date_compact", "code_norm"]].drop_duplicates().copy()
    label_rows: list[dict[str, Any]] = []
    for index, date_value in enumerate(dates):
        prior_dates = dates[: index + 1]
        counts_by_code: dict[str, dict[str, Any]] = {}
        for lookback in _WINDOWS:
            for days_ago, prior in enumerate(reversed(prior_dates[-lookback:])):
                for rank, code in enumerate(proxy_map.get(str(prior), []), start=1):
                    row = counts_by_code.setdefault(code, {"trade_date_compact": date_value, "code_norm": code})
                    row[f"recent_top20_count_{lookback}d"] = row.get(f"recent_top20_count_{lookback}d", 0) + 1
                    row[f"recent_top20_best_rank_{lookback}d"] = min(row.get(f"recent_top20_best_rank_{lookback}d", 99), rank)
                    row["last_top20_days_ago"] = min(row.get("last_top20_days_ago", 999), days_ago)
        label_rows.extend(counts_by_code.values())
    memory = pd.DataFrame(label_rows)
    if memory.empty:
        memory = code_dates.iloc[0:0].copy()
    out = code_dates.merge(memory, on=["trade_date_compact", "code_norm"], how="left")
    for lookback in _WINDOWS:
        out[f"recent_top20_count_{lookback}d"] = pd.to_numeric(out.get(f"recent_top20_count_{lookback}d"), errors="coerce").fillna(0)
        out[f"recent_top20_best_rank_{lookback}d"] = pd.to_numeric(out.get(f"recent_top20_best_rank_{lookback}d"), errors="coerce").fillna(99)
    out["last_top20_days_ago"] = pd.to_numeric(out.get("last_top20_days_ago"), errors="coerce").fillna(999)
    drop = [column for column in features.columns if column.startswith("recent_top20_") or column == "last_top20_days_ago"]
    return features.drop(columns=drop, errors="ignore").merge(out, on=["trade_date_compact", "code_norm"], how="left")


def _heuristic_scores(frame):
    import numpy as np

    day = frame.copy()
    day["memory_score"] = day["recent_top20_count_1d"] * 28 + day["recent_top20_count_3d"] * 18 + day["recent_top20_count_5d"] * 12 + day["recent_top20_count_10d"] * 7 + day["recent_top20_count_20d"] * 3.5 + day["recent_top20_count_60d"] * 1.2 - np.minimum(day["last_top20_days_ago"].fillna(999), 90) * 0.55
    day["active_score"] = day["intraday_high_pct"].clip(-5, 30).fillna(0) * 2.0 + day["pct_chg"].clip(-12, 18).fillna(0) * 1.25 + day["amplitude_pct"].clip(0, 35).fillna(0) * 1.05 + (day["amount_ratio_5d"].fillna(1) - 1).clip(0, 6) * 9 + (day["amount_ratio_20d"].fillna(1) - 1).clip(0, 6) * 6
    day["oversold_score"] = (-day["ret_20d"]).clip(0, 60).fillna(0) * 0.65 + (-day["ret_60d"]).clip(0, 85).fillna(0) * 0.35 + (-day["dd_from_60d_high"]).clip(0, 90).fillna(0) * 0.5 + (0.5 - day["close_pos_60d"]).clip(0, 0.5).fillna(0) * 42
    day["crash_reflow_score"] = day["intraday_high_max_20d"].clip(0, 80).fillna(0) * 0.85 + day["amp_max_20d"].clip(0, 80).fillna(0) * 0.45 + (-day["ret_5d"]).clip(0, 45).fillna(0) * 1.05 + (-day["ret_10d"]).clip(0, 60).fillna(0) * 0.75 + (-day["pct_chg_min_5d"]).clip(0, 25).fillna(0) + day["amount_ratio_20d"].fillna(1).clip(0, 6) * 5
    day["ipo_highvol_score"] = (1.0 / np.sqrt(day["listing_age_days_in_panel"].clip(lower=1))).fillna(0) * 35 + day["amp_max_60d"].clip(0, 90).fillna(0) * 0.55 + day["intraday_high_max_60d"].clip(0, 90).fillna(0) * 0.55 + day["amount_log"].rank(pct=True).fillna(0) * 18
    day["hybrid_score"] = day["memory_score"] * 1.15 + day["active_score"] * 0.55 + day["oversold_score"] * 0.35 + day["crash_reflow_score"] * 0.65 + day["ipo_highvol_score"] * 0.25
    return day


def _probability(model, x):
    import numpy as np

    if hasattr(model, "predict_proba"):
        return model.predict_proba(x)[:, 1]
    score = model.decision_function(x)
    return 1.0 / (1.0 + np.exp(-score))


def _zscore(series):
    import numpy as np
    import pandas as pd

    values = pd.to_numeric(series, errors="coerce")
    std = values.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(np.zeros(len(values)), index=values.index)
    return (values - values.mean()) / std


def _score_with_strategies(frame, models, feature_columns):
    out = _heuristic_scores(frame.copy())
    x = out[feature_columns]
    for name, model in models.items():
        out[f"prob_{name}"] = _probability(model, x)
        out[f"score_{name}"] = out[f"prob_{name}"]
    out["score_fixed_4model_old_weight"] = 0.34 * out["prob_hgb_depth6"] + 0.28 * out["prob_extra_trees"] + 0.24 * out["prob_random_forest"] + 0.14 * out["prob_logit"]
    out["score_equal_4model"] = out[["prob_hgb_depth6", "prob_extra_trees", "prob_random_forest", "prob_logit"]].mean(axis=1)
    for column in ("memory_score", "active_score", "crash_reflow_score", "oversold_score", "hybrid_score"):
        out[f"z_{column}"] = out.groupby("target_date")[column].transform(_zscore) if "target_date" in out.columns else _zscore(out[column])
    out["score_prob_memory"] = out["score_equal_4model"] + 0.035 * out["z_memory_score"]
    out["score_prob_active"] = out["score_equal_4model"] + 0.025 * out["z_active_score"]
    out["score_prob_crash_reflow"] = out["score_equal_4model"] + 0.025 * out["z_crash_reflow_score"]
    return out


def _load_models(assets: FrozenHK02Assets, *, signal_date: str):
    if str(assets.model_manifest.get("trained_through") or "") > signal_date:
        raise StoreError("HK 0.2 frozen model uses future training data")
    if platform.python_version() != HK_0_2_PYTHON_VERSION:
        raise StoreError("HK 0.2 requires Python 3.13.12")
    if _package_version("scikit-learn") != HK_0_2_SKLEARN_VERSION:
        raise StoreError("HK 0.2 requires scikit-learn 1.9.0")
    if _package_version("joblib") != HK_0_2_JOBLIB_VERSION:
        raise StoreError("HK 0.2 requires joblib 1.5.3")
    import joblib

    models = joblib.load(assets.model_path)
    if not isinstance(models, dict) or sorted(models) != list(_MODEL_NAMES):
        raise StoreError("HK 0.2 frozen model keys mismatch")
    return models


def score_frozen_hk_0_2(
    asset_root: Path | str,
    *,
    signal_date: str,
    target_date: str,
    eligible_codes: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    import pandas as pd

    signal_date, target_date = validate_date(signal_date), validate_date(target_date)
    if signal_date >= target_date:
        raise StoreError("HK 0.2 target_date must follow signal_date")
    assets = load_frozen_hk_0_2_assets(asset_root)
    panel = pd.read_parquet(assets.panel_path)
    panel["trade_date_compact"] = panel["trade_date_compact"].astype(str)
    panel = panel[panel["trade_date_compact"].le(signal_date)].copy()
    if signal_date not in set(panel["trade_date_compact"]):
        raise StoreError(f"HK 0.2 signal date is absent from panel: {signal_date}")
    features, proxy_map = _add_proxy_labels(_add_daily_features(panel))
    features = _add_proxy_memory(features, proxy_map)
    feature_columns = list(assets.model_manifest.get("feature_columns") or [])
    missing = sorted(set(feature_columns) - set(features.columns))
    if missing:
        raise StoreError("HK 0.2 model features missing: " + ",".join(missing))
    models = _load_models(assets, signal_date=signal_date)
    predict = features[features["trade_date_compact"].eq(signal_date)].copy()
    if eligible_codes is not None:
        normalized_eligible_codes = {_normalize_code(code) for code in eligible_codes}
        normalized_eligible_codes.discard("")
        predict = predict[
            predict["code_norm"].map(_normalize_code).isin(normalized_eligible_codes)
        ].copy()
    if predict["code_norm"].nunique() < 500:
        message = (
            "HK 0.2 eligible signal-date market coverage below 500"
            if eligible_codes is not None
            else "HK 0.2 signal-date market coverage below 500"
        )
        raise StoreError(message)
    predict["signal_date"], predict["target_date"] = signal_date, target_date
    ranked = _score_with_strategies(predict, models, feature_columns).sort_values("score_prob_active", ascending=False).head(100).copy()
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    ranked["trade_date"], ranked["bar_time"] = target_date, "17:30"
    ranked["code"] = ranked["code_norm"]
    ranked["ts_code"] = ranked["code_norm"].map(lambda code: f"{str(code).replace('HK.', '').zfill(5)}.HK_CONNECT")
    if assets.name_dictionary_path is not None:
        names = pd.read_csv(assets.name_dictionary_path, encoding="utf-8-sig").set_index("code")["name"]
        current_names = ranked.get("name", "")
        if not hasattr(current_names, "where"):
            current_names = pd.Series("", index=ranked.index)
        ranked["name"] = current_names.fillna("").astype(str).where(current_names.fillna("").astype(str).str.strip().ne(""), ranked["code_norm"].map(names).fillna(""))
    ranked["selected_strategy"] = ranked["weekly_tuning_selected_strategy"] = "prob_active"
    ranked["pool_version"] = "hkconnect_d1_top100_pool.v3_vipdoc_panel"
    ranked["freeze_status"] = "D1_POOL_V1_FROZEN_RESEARCH_ONLY"
    ranked["recommendation_status"] = "WATCH_ONLY_BACKTEST_GATED"
    ranked["trade_status_contract"] = "WATCH_ONLY"
    ranked["production_allowed"], ranked["lane"] = False, ""
    ranked["d1_snapshot_close_hkd"], ranked["d1_snapshot_prev_close_hkd"] = ranked["close"], ranked["pre_close"]
    ranked["candidate_pool_time"], ranked["data_cutoff"] = "D-1 close", f"{signal_date} close"
    ranked["research_only"], ranked["cannot_confirm"] = True, ""
    ranked["pct_chg_original_vipdoc"] = ranked["pct_chg"]
    ranked["pct_chg_source"] = ranked["d1_freshness_source"] = "VIPDOC_SIGNAL_DATE_CLOSE_PREVCLOSE"
    ranked["pct_chg_diff_pct"], ranked["d1_freshness_status"] = 0.0, "PASS"
    ranked["d1_close_hkd"], ranked["d1_prev_close_hkd"] = ranked["close"], ranked["pre_close"]
    return [{field: row.get(field, "") for field in _OUTPUT_FIELDS} for row in ranked.to_dict(orient="records")]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def publish_hk_0_2_rows(
    store_root: Path | str,
    *,
    signal_date: str,
    eligibility_source_date: str | None = None,
    target_date: str,
    rows: Iterable[Mapping[str, Any]],
    panel_sha256: str,
) -> dict[str, Any]:
    signal_date, target_date = validate_date(signal_date), validate_date(target_date)
    eligibility_source_date = validate_date(eligibility_source_date or signal_date)
    normalized = [{field: _cell(dict(row).get(field)) for field in _OUTPUT_FIELDS} for row in rows]
    if len(normalized) != 100:
        raise StoreError("HK 0.2 strict pool must contain exactly 100 rows")
    expected_ranks = [str(index) for index in range(1, 101)]
    if [row["rank"] for row in normalized] != expected_ranks:
        raise StoreError("HK 0.2 ranks must be 1..100")
    if len({row["code_norm"] for row in normalized}) != 100:
        raise StoreError("HK 0.2 pool contains duplicate codes")
    scores = [float(row["score_prob_active"]) for row in normalized]
    if scores != sorted(scores, reverse=True):
        raise StoreError("HK 0.2 pool is not sorted by prob_active")
    for row in normalized:
        if row["trade_date"] != target_date or row["target_date"] != target_date or row["signal_date"] != signal_date:
            raise StoreError("HK 0.2 row date mismatch")
        if row["selected_strategy"] != "prob_active" or row["d1_freshness_status"] != "PASS":
            raise StoreError("HK 0.2 strict semantics mismatch")
        if row["production_allowed"].lower() != "false" or row["cannot_confirm"]:
            raise StoreError("HK 0.2 safety boundary mismatch")
        if _is_name_code_placeholder(row["code_norm"], row["name"]):
            raise StoreError(f"HK 0.2 name missing or code placeholder: {row['code_norm']}")
    _, security_master_manifest = _load_verified_security_master(store_root, eligibility_source_date)
    security_master_captured_at = str(security_master_manifest.get("captured_at") or "")
    captured_date = _capture_date_shanghai(security_master_captured_at)
    if captured_date != eligibility_source_date:
        raise StoreError("HK 0.2 security-master capture date does not match eligibility source")
    with tempfile.TemporaryDirectory(prefix="v3sd_hk02_publish_") as temporary:
        source = Path(temporary) / "hkconnect_d1_top100_0_2.csv"
        with open(source, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_OUTPUT_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(normalized)
        artifact_sha = sha256_file(source)
        provenance = {
            "signal_date": signal_date,
            "source_contract": "tdx_vipdoc_71_day_prob_active",
            "panel_sha256": panel_sha256.lower(),
            "model_bundle_sha256": HK_0_2_MODEL_SHA256,
            "daily_features_sha256": HK_0_2_ORACLE_SHA256S["daily_features"],
            "proxy_prob_active_sha256": HK_0_2_ORACLE_SHA256S["proxy_prob_active"],
            "eligibility_source_date": eligibility_source_date,
            "security_master_trade_date": eligibility_source_date,
            "security_master_run_id": str(security_master_manifest["run_id"]),
            "security_master_artifact_sha256": str(security_master_manifest["artifact_sha256"]),
            "security_master_captured_at": _encode_capture_at_provenance(
                security_master_captured_at
            ),
        }
        spec = SourceSpec(
            source_id="hkconnect_0_2_frozen_prob_active",
            role=HK_0_2_ROLE,
            trade_date=target_date,
            market="HK_CONNECT",
            stages=(HK_0_2_STAGE_ID,),
            cutoff_at="17:30:00",
            source_path=source,
            required_columns=("trade_date", "bar_time", "signal_date", "target_date", "rank", "code_norm", "score_prob_active"),
            bar_time_column="bar_time",
            expected_input_sha256=artifact_sha,
            expected_row_count=100,
            provenance=provenance,
        )
        store = SafeRootStore(Path(store_root), AllowlistRegistry({(target_date, HK_0_2_ROLE): (spec,)}))
        outcome = store.replay_file(owner="v3_shared_data", trade_date=target_date, role=HK_0_2_ROLE, source_id=spec.source_id, stage_id=HK_0_2_STAGE_ID)
    read_verified_hk_0_2_pool(
        store_root,
        target_date=target_date,
        expected_signal_date=signal_date,
        expected_eligibility_source_date=eligibility_source_date,
    )
    return outcome


def read_verified_hk_0_2_pool(
    store_root: Path | str,
    *,
    target_date: str,
    expected_signal_date: str,
    expected_eligibility_source_date: str | None = None,
) -> VerifiedHK02Pool:
    target_date, expected_signal_date = validate_date(target_date), validate_date(expected_signal_date)
    eligibility_source_date = validate_date(
        expected_eligibility_source_date or expected_signal_date
    )
    security_master, security_master_manifest = _load_verified_security_master(
        store_root, eligibility_source_date
    )
    security_master_captured_at = str(
        security_master_manifest.get("captured_at") or ""
    )
    if _capture_date_shanghai(security_master_captured_at) != eligibility_source_date:
        raise StoreError("HK 0.2 security-master capture date does not match eligibility source")
    run = read_verified_latest(store_root, target_date, HK_0_2_ROLE)
    provenance = dict(run.manifest.get("provenance") or {})
    expected = {
        "signal_date": expected_signal_date,
        "source_contract": "tdx_vipdoc_71_day_prob_active",
        "model_bundle_sha256": HK_0_2_MODEL_SHA256,
        "daily_features_sha256": HK_0_2_ORACLE_SHA256S["daily_features"],
        "proxy_prob_active_sha256": HK_0_2_ORACLE_SHA256S["proxy_prob_active"],
        "security_master_trade_date": eligibility_source_date,
        "security_master_run_id": str(security_master_manifest["run_id"]),
        "security_master_artifact_sha256": str(security_master_manifest["artifact_sha256"]),
    }
    if eligibility_source_date != expected_signal_date:
        expected.update({
            "eligibility_source_date": eligibility_source_date,
        })
    elif "eligibility_source_date" in provenance:
        expected["eligibility_source_date"] = eligibility_source_date
    for key, value in expected.items():
        if provenance.get(key) != value:
            raise StoreError(f"HK 0.2 provenance mismatch: {key}")
    if (
        eligibility_source_date != expected_signal_date
        or "eligibility_source_date" in provenance
    ) and _decode_capture_at_provenance(
        provenance.get("security_master_captured_at")
    ) != security_master_captured_at:
        raise StoreError("HK 0.2 provenance mismatch: security_master_captured_at")
    rows: list[dict[str, str]] = []
    with open(run.artifact_path, "r", encoding="utf-8-sig", newline="") as handle:
        rows.extend(dict(row) for row in csv.DictReader(handle))
    if len(rows) != 100 or [int(row["rank"]) for row in rows] != list(range(1, 101)):
        raise StoreError("HK 0.2 verified artifact rank/count mismatch")
    if [float(row["score_prob_active"]) for row in rows] != sorted((float(row["score_prob_active"]) for row in rows), reverse=True):
        raise StoreError("HK 0.2 verified artifact ordering mismatch")
    for row in rows:
        if _is_name_code_placeholder(row.get("code_norm"), row.get("name")):
            raise StoreError(f"HK 0.2 verified artifact name missing: {row.get('code_norm')}")
    return VerifiedHK02Pool(run, tuple(rows))


def _copy_exact_run_file(source: Path, destination: Path) -> bool:
    payload = source.read_bytes()
    if destination.exists():
        if destination.read_bytes() != payload:
            raise StoreError(f"HK 0.2 target evidence conflict: {destination}")
        return False
    _atomic_write(destination, payload)
    return True


def _verified_hk_0_2_identity(pool: VerifiedHK02Pool) -> dict[str, Any]:
    provenance = dict(pool.run.manifest.get("provenance") or {})
    return {
        "run_id": pool.run.verification.get("run_id"),
        "artifact_sha256": pool.run.verification.get("artifact_sha256"),
        "manifest_sha256": pool.run.verification.get("manifest_sha256"),
        "receipt_sha256": pool.run.verification.get("receipt_sha256"),
        "security_master_trade_date": provenance.get("security_master_trade_date"),
        "security_master_run_id": provenance.get("security_master_run_id"),
        "security_master_artifact_sha256": provenance.get("security_master_artifact_sha256"),
    }


def restore_verified_hk_0_2_source(
    source_store_root: Path | str,
    target_store_root: Path | str,
    *,
    signal_date: str,
    target_date: str,
) -> dict[str, Any]:
    """Copy one exact reader-verified HK D-1 run into the V4 owned root.

    The source is never used as an online fallback.  Both the source and the
    restored target pass the current HK 0.2 reader, including the signal-date
    security-master provenance, before READY is returned.
    """
    signal_date, target_date = validate_date(signal_date), validate_date(target_date)
    source_root, target_root = Path(source_store_root), Path(target_store_root)
    source_pool = read_verified_hk_0_2_pool(
        source_root, target_date=target_date, expected_signal_date=signal_date
    )
    source_entry = dict(source_pool.run.latest)
    canonical_entry = {
        "run_id": source_pool.run.verification["run_id"],
        "artifact_relative": source_pool.run.verification["artifact_relative"],
        "manifest_relative": source_pool.run.verification["manifest_relative"],
        "receipt_relative": source_pool.run.verification["receipt_relative"],
    }
    if any(source_entry.get(field) != value for field, value in canonical_entry.items()):
        raise StoreError("HK 0.2 source latest metadata mismatch")
    source_entry.update(canonical_entry)

    try:
        existing = read_verified_hk_0_2_pool(
            target_root, target_date=target_date, expected_signal_date=signal_date
        )
    except StoreError:
        existing = None
    if existing is not None:
        if _verified_hk_0_2_identity(existing) != _verified_hk_0_2_identity(source_pool):
            raise StoreError("HK 0.2 target date already contains a different verified run")
        return {
            "status": "READY",
            "restored": False,
            "already_exists": True,
            **existing.run.verification,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    from .hk_security_master import restore_verified_hk_security_master
    restore_verified_hk_security_master(
        source_root, target_root, trade_date=signal_date
    )

    target_store = SafeRootStore(target_root)
    target_store._check_owner("v3_shared_data")
    key = target_store._entry_key(target_date, HK_0_2_ROLE)
    with target_store._lock():
        latest = target_store._load_latest()
        prior = latest["entries"].get(key)
        if prior is not None and any(
            prior.get(field) != source_entry.get(field)
            for field in ("run_id", "artifact_relative", "manifest_relative", "receipt_relative")
        ):
            raise StoreError("HK 0.2 target slot already points to a different run")
        copied = False
        for source_path, relative in (
            (source_pool.run.artifact_path, source_pool.run.verification["artifact_relative"]),
            (source_pool.run.manifest_path, source_pool.run.verification["manifest_relative"]),
            (source_pool.run.receipt_path, source_pool.run.verification["receipt_relative"]),
        ):
            destination = resolve_under(target_root, str(relative))
            copied = _copy_exact_run_file(source_path, destination) or copied
        latest["entries"][key] = source_entry
        target_store._write_json(target_store.latest_path, latest)

    restored = read_verified_hk_0_2_pool(
        target_root, target_date=target_date, expected_signal_date=signal_date
    )
    if _verified_hk_0_2_identity(restored) != _verified_hk_0_2_identity(source_pool):
        raise StoreError("HK 0.2 restored identity mismatch")
    return {
        "status": "READY",
        "restored": copied,
        "already_exists": not copied,
        **restored.run.verification,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def materialize_frozen_hk_0_2(
    store_root: Path | str,
    asset_root: Path | str,
    *,
    signal_date: str,
    target_date: str,
    eligibility_source_date: str | None = None,
) -> dict[str, Any]:
    signal_date, target_date = validate_date(signal_date), validate_date(target_date)
    eligibility_source_date = validate_date(eligibility_source_date or signal_date)
    assets = load_frozen_hk_0_2_assets(asset_root)
    security_master, _ = _load_verified_security_master(store_root, eligibility_source_date)
    rows = score_frozen_hk_0_2(
        asset_root,
        signal_date=signal_date,
        target_date=target_date,
        eligible_codes=security_master.keys(),
    )
    rows = _fill_name_placeholders(rows, security_master)
    return publish_hk_0_2_rows(
        store_root,
        signal_date=signal_date,
        eligibility_source_date=eligibility_source_date,
        target_date=target_date,
        rows=rows,
        panel_sha256=str(assets.panel_manifest["panel_sha256"]),
    )


def quarantine_rejected_hk_0_2_run(
    store_root: Path | str,
    *,
    target_date: str,
    expected_run_id: str,
    expected_artifact_sha256: str,
    reason: str,
) -> dict[str, Any]:
    """Recoverably remove a rejected HK 0.2 run from the authoritative pointer."""
    target_date = validate_date(target_date)
    store = SafeRootStore(Path(store_root))
    with store._lock():
        latest = store._load_latest()
        key = store._entry_key(target_date, HK_0_2_ROLE)
        entry = latest["entries"].get(key)
        if not isinstance(entry, Mapping) or entry.get("run_id") != expected_run_id:
            raise StoreError("HK 0.2 quarantine latest run mismatch")
        verified = store.verify_run(target_date, HK_0_2_ROLE, expected_run_id, expected_owner="v3_shared_data")
        if verified["artifact_sha256"] != expected_artifact_sha256:
            raise StoreError("HK 0.2 quarantine artifact sha mismatch")
        source = store.runs_root / target_date / HK_0_2_ROLE / expected_run_id
        quarantine = store.root / "quarantine" / target_date / HK_0_2_ROLE / expected_run_id
        if quarantine.exists():
            raise StoreError("HK 0.2 quarantine destination already exists")
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, quarantine)
        del latest["entries"][key]
        store._write_json(store.latest_path, latest)
        receipt = {
            "schema_version": "v3_shared_data.quarantine.v1",
            "trade_date": target_date,
            "role": HK_0_2_ROLE,
            "run_id": expected_run_id,
            "artifact_sha256": expected_artifact_sha256,
            "reason": reason,
            "quarantined_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "recoverable": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        store._write_json(quarantine / "quarantine.json", receipt)
    return receipt
