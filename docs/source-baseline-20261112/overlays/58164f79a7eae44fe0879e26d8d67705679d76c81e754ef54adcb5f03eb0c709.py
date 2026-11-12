"""Publish the fixed A candidate and complete HK Connect universe manifests.

The CLI accepts a trade date only.  All roots are trusted environment values;
there is no user-selected path option and no V3 runtime dependency.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.hashing import canonical_bytes, is_sha256_hex, sha256_file, sha256_json
from shared_data.paths import validate_date
from shared_data.store import ConflictError, SafeRootStore, StoreError
from scripts.live_acquisition.universe import (
    UNIVERSE_SCHEMA_VERSION,
    UNIVERSE_SCHEMA_VERSION_V2,
    V35_STAGE_ACQUISITION_ROLE,
    normalize_symbol,
    read_verified_v35_stage_acquisition_universe,
    resolve_stage_universe,
    universe_manifest_revision_path,
    universe_manifest_publish_path,
    universe_manifest_supersession_dir,
)

_STORE_ROOT_ENV = "V3_SHARED_DATA_STORE_ROOT"
_V35_DATA_ROOT_ENV = "V35_DATA_ROOT"
_SELECTOR_PANEL_ENV = "V3_SHARED_SELECTOR_READY_PANEL"


def _load_hk_codes(selector_panel: Path, trade_date: str) -> tuple[list[str], str]:
    import pandas as pd

    frame = pd.read_parquet(
        selector_panel,
        columns=["trade_date", "ts_code", "exchange", "market_type"],
    )
    dates = frame["trade_date"].astype(str).str.replace("-", "", regex=False)
    eligible = frame.loc[dates <= trade_date].copy()
    if eligible.empty:
        raise ValueError("selector-ready panel has no date at/before target")
    source_date = str(eligible["trade_date"].astype(str).max()).replace("-", "")
    source_rows = eligible.loc[
        eligible["trade_date"].astype(str).str.replace("-", "", regex=False).eq(source_date)
    ]
    if "exchange" in source_rows:
        hk = source_rows.loc[source_rows["exchange"].astype(str).str.upper().eq("HK_CONNECT")]
    else:
        hk = source_rows.loc[source_rows["market_type"].astype(str).str.upper().eq("HK")]
    codes = [str(value) for value in hk["ts_code"].dropna().tolist()]
    if not codes:
        raise ValueError("selector-ready panel has no HK Connect membership")
    return codes, source_date


def _manifest(
    *, trade_date: str, market: str, scope: str, codes: list[str],
    source_role: str, source_sha256: str, source_date: str,
    schema_version: str = UNIVERSE_SCHEMA_VERSION,
    artifact_role: str = "",
    artifact_version: str = "",
    source_projection_sha256: str = "",
    source_merge_role: str = "",
    stage_selection_eligible: bool | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": schema_version,
        "trade_date": trade_date,
        "market": market,
        "scope": scope,
        "codes": codes,
        "code_count": len(codes),
        "codes_sha256": sha256_json(codes),
        "source_role": source_role,
        "source_sha256": source_sha256,
        "source_date": source_date,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if artifact_role:
        payload.update(
            artifact_role=artifact_role,
            artifact_version=artifact_version,
            source_projection_sha256=source_projection_sha256,
            source_merge_role=source_merge_role,
            stage_selection_eligible=stage_selection_eligible,
        )
    return payload


def _build_a_payload(trade_date: str, verified_a: dict[str, Any]) -> dict[str, Any]:
    """Re-materialize the A payload only from the verified V3.5 artifact."""
    a_artifact = verified_a["artifact"]
    a_codes = [normalize_symbol(value, "A_SHARE") for value in verified_a["codes"]]
    if len(set(a_codes)) != len(a_codes):
        raise ValueError("V3.5 stage-acquisition universe contains duplicate symbols")
    payload = _manifest(
        trade_date=trade_date,
        market="A_SHARE",
        scope="STAGE_CANDIDATES",
        codes=a_codes,
        source_role=V35_STAGE_ACQUISITION_ROLE,
        source_sha256=verified_a["artifact_sha256"],
        source_date=trade_date,
        schema_version=UNIVERSE_SCHEMA_VERSION_V2,
        artifact_role="A_SHARE_STAGE_CANDIDATES_V2",
        artifact_version="V2",
        source_projection_sha256=a_artifact["source_projection_sha256"],
        source_merge_role=a_artifact["source_merge_role"],
        stage_selection_eligible=a_artifact["stage_selection_eligible"],
    )
    payload.update(
        candidate_semantics="QUOTE_ACQUISITION_ONLY",
        source_status=a_artifact["status"],
        source_cannot_confirm=[
            str(item) for item in a_artifact.get("cannot_confirm") or []
        ],
        source_row_count=a_artifact["row_count"],
    )
    return payload


def materialize_stage_universes(
    store_root: Path | str,
    v35_data_root: Path | str,
    selector_panel: Path | str,
    trade_date: str,
    *,
    hk_loader: Callable[[Path, str], tuple[list[str], str]] = _load_hk_codes,
) -> dict[str, Any]:
    trade_date = validate_date(trade_date)
    store_root = Path(store_root)
    v35_data_root = Path(v35_data_root)
    selector_panel = Path(selector_panel)
    if not selector_panel.is_file():
        raise ValueError(f"selector-ready panel missing: {selector_panel}")

    verified_a = read_verified_v35_stage_acquisition_universe(
        v35_data_root, trade_date
    )
    a_artifact = verified_a["artifact"]
    a_payload = _build_a_payload(trade_date, verified_a)
    hk_raw_codes, hk_source_date = hk_loader(selector_panel, trade_date)
    hk_codes = [normalize_symbol(value, "HK_CONNECT") for value in hk_raw_codes]
    if len(set(hk_codes)) != len(hk_codes):
        raise ValueError("HK Connect selector membership contains duplicate codes")
    payloads = {
        "A_SHARE": a_payload,
        "HK_CONNECT": _manifest(
            trade_date=trade_date,
            market="HK_CONNECT",
            scope="FULL_MARKET",
            codes=hk_codes,
            source_role="SELECTOR_READY_CURRENT_HK_CONNECT",
            source_sha256=sha256_file(selector_panel),
            source_date=hk_source_date,
        ),
    }
    paths = {
        market: universe_manifest_publish_path(store_root, trade_date, market)
        for market in payloads
    }
    store = SafeRootStore(store_root)
    with store._lock():
        for market, path in paths.items():
            if not path.exists():
                continue
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise StoreError(f"existing universe manifest is corrupt: {path}") from exc
            if canonical_bytes(existing) != canonical_bytes(payloads[market]):
                raise ConflictError(f"universe slot already has different evidence: {path}")
        for market, path in paths.items():
            if not path.exists():
                store._write_json(path, payloads[market])

    return {
        "ok": True,
        "trade_date": trade_date,
        "markets": {
            market: {
                "code_count": payload["code_count"],
                "codes_sha256": payload["codes_sha256"],
                "source_role": payload["source_role"],
                "source_sha256": payload["source_sha256"],
                "source_date": payload["source_date"],
                **(
                    {"source_projection_sha256": payload["source_projection_sha256"]}
                    if market == "A_SHARE"
                    else {}
                ),
            }
            for market, payload in payloads.items()
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _read_existing_a_payload(path: Path, store_root: Path, trade_date: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise StoreError(f"existing A-share universe manifest is corrupt: {path}") from exc
    if not isinstance(value, dict):
        raise StoreError("existing A-share universe manifest must be an object")
    resolved = resolve_stage_universe(store_root, trade_date, "A_SHARE")
    if resolved.path != path:
        raise StoreError("A-share CAS slot is not the versioned V2 manifest")
    if value.get("source_row_count") != value.get("code_count"):
        raise StoreError("existing A-share universe manifest is incomplete")
    return value


def _replacement_result(receipt: dict[str, Any], root: Path) -> dict[str, Any]:
    return {
        "ok": True,
        "status": receipt["status"],
        "trade_date": receipt["trade_date"],
        "previous_sha256": receipt["previous_sha256"],
        "replacement_sha256": receipt["replacement_sha256"],
        "row_count": receipt["row_count"],
        "supersession_receipt_path": str(root / receipt["supersession_receipt_relative"]),
        "previous_revision_path": str(root / receipt["previous_revision_relative"]),
        "replacement_revision_path": str(root / receipt["replacement_revision_relative"]),
    }


def replace_a_share_stage_universe(
    store_root: Path | str,
    v35_data_root: Path | str,
    trade_date: str,
    *,
    expected_sha256: str,
    reason: str,
) -> dict[str, Any]:
    """CAS-replace the A V2 slot from one verified V3.5 authority.

    The normal materializer remains immutable.  This explicit repair API
    accepts exactly one expected old payload/file SHA, records immutable old
    and replacement revisions plus a supersession receipt under the store
    lock, and atomically updates the V2 slot last.  Repeating the same
    expected SHA is idempotent; a different expected SHA conflicts.
    """
    trade_date = validate_date(trade_date)
    expected_sha256 = str(expected_sha256 or "").lower()
    reason = str(reason or "").strip()
    if not is_sha256_hex(expected_sha256):
        raise ValueError("expected_sha256 must be a 64-hex SHA256")
    if not reason:
        raise ValueError("reason is required for A-share universe replacement")
    root = Path(store_root)
    verified_a = read_verified_v35_stage_acquisition_universe(v35_data_root, trade_date)
    replacement = _build_a_payload(trade_date, verified_a)
    replacement_bytes = canonical_bytes(replacement)
    replacement_sha = sha256_json(replacement)
    slot = universe_manifest_publish_path(root, trade_date, "A_SHARE")
    store = SafeRootStore(root)

    with store._lock():
        try:
            existing = _read_existing_a_payload(slot, root, trade_date)
        except FileNotFoundError as exc:
            raise StoreError(f"A-share CAS slot missing: {slot}") from exc
        previous_bytes = slot.read_bytes()
        previous_file_sha = sha256_file(slot)
        previous_payload_sha = sha256_json(existing)
        previous_matches = expected_sha256 in {previous_file_sha, previous_payload_sha}
        # On a repeated call the slot already points at the replacement, so
        # the original expected SHA is no longer the current slot SHA.  Locate
        # the immutable receipt by its full identity and return it idempotently.
        supersession_root = root / "universes" / trade_date / "A_SHARE_STAGE_CANDIDATES_V2.supersessions"
        if supersession_root.is_dir():
            for candidate in supersession_root.iterdir():
                candidate_receipt = candidate / "receipt.json"
                if not candidate_receipt.is_file():
                    continue
                try:
                    prior_receipt = json.loads(candidate_receipt.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if (
                    isinstance(prior_receipt, dict)
                    and prior_receipt.get("expected_sha256") == expected_sha256
                    and prior_receipt.get("replacement_sha256") == replacement_sha
                    and prior_receipt.get("reason") == reason
                ):
                    return _replacement_result(prior_receipt, root)
        supersession_dir = universe_manifest_supersession_dir(
            root, trade_date, "A_SHARE", previous_file_sha, replacement_sha
        )
        receipt_path = supersession_dir / "receipt.json"
        if receipt_path.is_file():
            try:
                prior_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise StoreError("A-share supersession receipt is corrupt") from exc
            if (
                not isinstance(prior_receipt, dict)
                or prior_receipt.get("expected_sha256") != expected_sha256
                or prior_receipt.get("replacement_sha256") != replacement_sha
                or prior_receipt.get("reason") != reason
            ):
                raise ConflictError("A-share supersession receipt identity mismatch")
            return _replacement_result(prior_receipt, root)
        if not previous_matches:
            raise ConflictError(
                f"A-share CAS expected SHA mismatch: got file={previous_file_sha} "
                f"payload={previous_payload_sha} expected={expected_sha256}"
            )
        if replacement_sha == previous_payload_sha and replacement_bytes == previous_bytes:
            return {
                "ok": True,
                "status": "ALREADY_CURRENT",
                "trade_date": trade_date,
                "previous_sha256": previous_file_sha,
                "replacement_sha256": replacement_sha,
                "row_count": replacement["code_count"],
            }

        previous_revision = universe_manifest_revision_path(
            root, trade_date, "A_SHARE", previous_file_sha
        )
        replacement_revision = universe_manifest_revision_path(
            root, trade_date, "A_SHARE", replacement_sha
        )
        for path, data in (
            (previous_revision, previous_bytes),
            (replacement_revision, replacement_bytes),
        ):
            if path.exists() and path.read_bytes() != data:
                raise ConflictError(f"A-share immutable revision differs: {path}")
            if not path.exists():
                store._atomic_write_bytes(path, data)

        supersession_dir.mkdir(parents=True, exist_ok=True)
        replacement_evidence = supersession_dir / "replacement.json"
        if replacement_evidence.exists() and replacement_evidence.read_bytes() != replacement_bytes:
            raise ConflictError("A-share replacement evidence differs")
        if not replacement_evidence.exists():
            store._atomic_write_bytes(replacement_evidence, replacement_bytes)
        receipt = {
            "schema_version": "v3_shared_data.stage_universe.supersession.v1",
            "trade_date": trade_date,
            "market": "A_SHARE",
            "artifact_role": "A_SHARE_STAGE_CANDIDATES_V2",
            "status": "SUPERSEDED",
            "reason": reason,
            "expected_sha256": expected_sha256,
            "previous_sha256": previous_file_sha,
            "previous_payload_sha256": previous_payload_sha,
            "replacement_sha256": replacement_sha,
            "row_count": replacement["code_count"],
            "codes_sha256": replacement["codes_sha256"],
            "source_role": replacement["source_role"],
            "source_sha256": replacement["source_sha256"],
            "source_date": replacement["source_date"],
            "target_relative": _relative(root, slot),
            "previous_revision_relative": _relative(root, previous_revision),
            "replacement_revision_relative": _relative(root, replacement_revision),
            "replacement_evidence_relative": _relative(root, replacement_evidence),
            "supersession_receipt_relative": _relative(root, receipt_path),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        receipt_bytes = canonical_bytes(receipt)
        if receipt_path.exists() and receipt_path.read_bytes() != receipt_bytes:
            raise ConflictError("A-share supersession receipt differs")
        if not receipt_path.exists():
            store._atomic_write_bytes(receipt_path, receipt_bytes)
        # The slot is updated only after all immutable evidence is durable.
        store._atomic_write_bytes(slot, replacement_bytes)
        return _replacement_result(receipt, root)


def _parse_args(argv: list[str]) -> dict[str, str]:
    if len(argv) != 2 or argv[0] != "--trade-date":
        raise ValueError("usage: materialize_stage_universes --trade-date YYYYMMDD")
    return {"trade_date": validate_date(argv[1])}


def main(argv: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    try:
        args = _parse_args(argv)
        required = {
            _STORE_ROOT_ENV: str(env.get(_STORE_ROOT_ENV, "") or "").strip(),
            _V35_DATA_ROOT_ENV: str(env.get(_V35_DATA_ROOT_ENV, "") or "").strip(),
            _SELECTOR_PANEL_ENV: str(env.get(_SELECTOR_PANEL_ENV, "") or "").strip(),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"missing trusted environment: {', '.join(missing)}")
        return materialize_stage_universes(
            required[_STORE_ROOT_ENV],
            required[_V35_DATA_ROOT_ENV],
            required[_SELECTOR_PANEL_ENV],
            args["trade_date"],
        )
    except (ValueError, StoreError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    outcome = main(sys.argv[1:])
    print(json.dumps(outcome, ensure_ascii=False))
    sys.exit(0 if outcome.get("ok") else 1)
