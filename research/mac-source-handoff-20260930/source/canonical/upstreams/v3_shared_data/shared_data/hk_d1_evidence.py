"""Verified, read-only HK D-1 change map from the shared VIPDOC panel."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class HkD1EvidenceError(RuntimeError):
    pass


def read_verified_hk_d1_evidence(
    store_root: Path | str,
    *,
    target_trade_date: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    import pandas as pd

    root = Path(store_root).resolve()
    asset_root = (root / "assets" / "hk_0_2").resolve()
    pointer = _read_json(asset_root / "panel_latest.json")
    manifest_path = _under(asset_root, pointer.get("manifest_relative"))
    manifest = _read_json(manifest_path)
    if manifest.get("asset_schema_version") not in {
        "v3_shared_data.hk_0_2_panel_asset.v1",
        "v3_shared_data.hk_0_2_panel_asset.v2",
    }:
        raise HkD1EvidenceError("HK D-1 panel schema mismatch")
    if manifest.get("production_allowed") is not False:
        raise HkD1EvidenceError("HK D-1 panel safety flag mismatch")
    panel_path = _under(asset_root, manifest.get("panel_relative"))
    expected_sha = str(manifest.get("panel_sha256") or "")
    if not expected_sha or _sha256_file(panel_path) != expected_sha:
        raise HkD1EvidenceError("HK D-1 panel SHA mismatch")

    required = ["trade_date_compact", "code_norm", "close", "pre_close", "pct_chg"]
    frame = pd.read_parquet(panel_path, columns=required)
    frame["trade_date_compact"] = frame["trade_date_compact"].astype(str)
    eligible = frame[frame["trade_date_compact"] < str(target_trade_date)]
    if eligible.empty:
        raise HkD1EvidenceError("HK D-1 panel has no prior trading date")
    signal_date = str(eligible["trade_date_compact"].max())
    day = eligible[eligible["trade_date_compact"].eq(signal_date)]
    rows: dict[str, dict[str, Any]] = {}
    for raw in day.to_dict("records"):
        symbol = _normalize_hk_symbol(raw.get("code_norm"))
        if not symbol:
            continue
        try:
            change = float(raw["pct_chg"])
            close = float(raw["close"])
            previous_close = float(raw["pre_close"])
        except (TypeError, ValueError):
            continue
        rows[symbol] = {
            "d1_change_pct": change,
            "d1_change_pct_source": f"VIPDOC_SIGNAL_DATE_CLOSE_PREVCLOSE:{signal_date}",
            "d1_freshness_status": "PASS",
            "d1_close_hkd": close,
            "d1_prev_close_hkd": previous_close,
            "d1_signal_date": signal_date,
        }
    if not rows:
        raise HkD1EvidenceError("HK D-1 verified day is empty")
    return rows, {
        "schema_version": "v3_shared_data.hk_d1_evidence.v1",
        "signal_date": signal_date,
        "row_count": len(rows),
        "panel_sha256": expected_sha,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise HkD1EvidenceError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise HkD1EvidenceError(f"{path.name} must be an object")
    return value


def _under(root: Path, relative: Any) -> Path:
    text = str(relative or "").strip()
    if not text:
        raise HkD1EvidenceError("HK D-1 relative path missing")
    path = (root / text).resolve()
    if root != path and root not in path.parents:
        raise HkD1EvidenceError("HK D-1 path escapes asset root")
    if not path.is_file():
        raise HkD1EvidenceError("HK D-1 artifact missing")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_hk_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("HK."):
        text = text[3:]
    elif text.endswith(".HK"):
        text = text[:-3]
    digits = "".join(character for character in text if character.isdigit())
    return f"HK.{digits.zfill(5)}" if digits and len(digits) <= 5 else ""


__all__ = ["HkD1EvidenceError", "read_verified_hk_d1_evidence"]
