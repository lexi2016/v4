"""Independent, exact-date storage for V3.5 preselection pools."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from infrastructure.data_store import _canonical_bytes, _date, _sha256
from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.owned_path import resolve_owned_path


POOL_ORDER = (
    "a_d1_premarket_pool",
    "a_d1_fupan_watchlist_pool",
    "a_d1_stage7_fenshi_review_pool",
    "a_share_research_recommendation_pool",
    "a_share_baimao_research_map",
    "hkconnect_d1_top100",
    "wechat_public_account_v3_preselect",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")

# The original pool contract used three coarse roles.  Formal 20260824/25
# artifacts already carry these producer-specific roles, so readers must
# accept them without weakening the legacy final-output rejection.
FORMAL_SOURCE_ROLES = frozenset(
    {
        "SHARED_VERIFIED_V192",
        "VERIFIED_D1_FUPAN_REVIEW",
        "VERIFIED_D1_STAGE7_REPLAY",
        "VERIFIED_HOURLY_RESEARCH",
        "SHARED_VERIFIED_HK_0_2",
        "VERIFIED_WECHAT_RESEARCH",
        "VERIFIED_BAIMAO_RESEARCH",
    }
)

# These are the lineage additions present on the accepted formal artifacts.
# They remain optional so the generic v1 artifacts and their receipts keep
# their exact historical wire shape.
POOL_ARTIFACT_OPTIONAL_FIELDS = frozenset(
    {
        "artifact_role",
        "artifact_version",
        "signal_date",
        "target_date",
        "source_artifact_sha256",
        "source_merge_role",
        "source_row_count",
        "source_run_id",
        "stage_selection_eligible",
    }
)
RECEIPT_EXTENSION_FIELDS = frozenset({"source_row_count", "source_run_id"})

# The scheduled optional lanes may first be materialized as an explicit
# EXPECTED_MISSING artifact and become available after their upstream source
# is repaired.  Keep this refresh surface narrow: formal A/HK pools remain
# immutable and no other pool can be silently replaced by this consumer.
_REFRESHABLE_SOURCE_POOLS = frozenset(
    {
        "a_d1_fupan_watchlist_pool",
        "a_d1_stage7_fenshi_review_pool",
        "a_share_research_recommendation_pool",
    }
)
_ALLOWED_SOURCE_UPGRADES = {
    "a_d1_fupan_watchlist_pool": {
        ("EXPECTED_MISSING", "VERIFIED_D1_FUPAN_REVIEW"),
    },
    "a_d1_stage7_fenshi_review_pool": {
        ("EXPECTED_MISSING", "VERIFIED_D1_STAGE7_REPLAY"),
    },
    "a_share_research_recommendation_pool": {
        ("EXPECTED_MISSING", "VERIFIED_HOURLY_RESEARCH"),
    },
}

_BAIMAO_POOL_ID = "a_share_baimao_research_map"
_BAIMAO_MISSING_PRODUCER = "shared_data.baimao_observations.v1"
_BAIMAO_VERIFIED_PRODUCER = "wechat_baimao_shared_projection_v1"
_BAIMAO_VERIFIED_SOURCE_ROLE = "VERIFIED_BAIMAO_RESEARCH"
_BAIMAO_EMPTY_SOURCE_SHA = hashlib.sha256(b"").hexdigest()

_V192_POOL_ID = "a_d1_premarket_pool"
_V192_MISSING_PRODUCER = "graph_expected_missing_v1"
_V192_VERIFIED_PRODUCER = "v3_shared_v192_consumer_v1"
_V192_VERIFIED_SOURCE_ROLE = "SHARED_VERIFIED_V192"
_V192_VERIFIED_STATUS = "V192_CANDIDATE_READY"
_V192_ARTIFACT_ROLE = "A_SHARE_V192_PREMARKET_POOL_V3"

_HK_0_2_POOL_ID = "hkconnect_d1_top100"
_HK_0_2_MISSING_PRODUCER = "graph_expected_missing_v1"
_HK_0_2_EMPTY_SOURCE_SHA = hashlib.sha256(b"").hexdigest()
_HK_0_2_PRODUCER = "v3_shared_hk_0_2_consumer_v1"
_HK_0_2_ROLE = "HK_CONNECT_D1_TOP100_0_2"


def _is_exact_hk_0_2_missing_placeholder(
    payload: Mapping[str, Any], trade_date: str
) -> bool:
    rows = payload.get("rows")
    return (
        payload.get("pool_id") == _HK_0_2_POOL_ID
        and payload.get("trade_date") == trade_date
        and payload.get("market") == "HK"
        and payload.get("status") == "CANNOT_CONFIRM"
        and payload.get("producer_id") == _HK_0_2_MISSING_PRODUCER
        and payload.get("source_role") == "EXPECTED_MISSING"
        and payload.get("source_path") == ""
        and payload.get("source_sha256") == _HK_0_2_EMPTY_SOURCE_SHA
        and "source_artifact_sha256" not in payload
        and "source_run_id" not in payload
        and isinstance(rows, list)
        and not rows
        and payload.get("source_row_count", 0) == 0
        and isinstance(payload.get("cannot_confirm"), list)
        and bool(payload["cannot_confirm"])
        and payload.get("production_allowed") is False
        and payload.get("buy_gate_updated") is False
        and payload.get("orders_sent") is False
    )


def _is_verified_hk_0_2_pool_result(
    payload: Mapping[str, Any], trade_date: str
) -> bool:
    """Accept only a date-bound projection of a checksum-verified HK 0.2 run."""
    rows = payload.get("rows")
    status = payload.get("status")
    partial = status == "PARTIAL_WITH_ROWS"
    strict = status == "STRICT_0_2_READY"
    signal_date = str(payload.get("signal_date") or "")
    run_id = str(payload.get("source_run_id") or "")
    source_sha = str(payload.get("source_sha256") or "").lower()
    source_artifact_sha = str(payload.get("source_artifact_sha256") or "").lower()
    source_path = str(payload.get("source_path") or "")
    expected_source_path = f"runs/{trade_date}/{_HK_0_2_ROLE}/{run_id}/artifact.csv"
    if not (
        payload.get("pool_id") == _HK_0_2_POOL_ID
        and payload.get("trade_date") == trade_date
        and payload.get("target_date") == trade_date
        and payload.get("market") == "HK"
        and payload.get("producer_id") == _HK_0_2_PRODUCER
        and ((partial and payload.get("source_role") == "UPSTREAM_PRODUCER_ARTIFACT")
             or (strict and payload.get("source_role") == "SHARED_VERIFIED_HK_0_2"))
        and re.fullmatch(r"\d{8}-hk-connect-d1-top100-0-2-[0-9a-f]{12}", run_id)
        and source_path == expected_source_path
        and _SHA256.fullmatch(source_sha) is not None
        and source_artifact_sha == source_sha
        and isinstance(rows, list)
        and 1 <= len(rows) <= 100
        and payload.get("source_row_count") == len(rows)
        and payload.get("stage_selection_eligible") is True
        and payload.get("signal_date") == signal_date
        and re.fullmatch(r"\d{8}", signal_date) is not None
        and signal_date < trade_date
        and payload.get("cannot_confirm")
        and (not partial or any(
            str(reason).startswith("HK_0_2_")
            for reason in payload.get("cannot_confirm", ())
        ))
        and (not strict or len(rows) == 100)
        and payload.get("production_allowed") is False
        and payload.get("buy_gate_updated") is False
        and payload.get("orders_sent") is False
    ):
        return False
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        symbol = str(row.get("symbol") or "").strip().upper()
        code = str(row.get("code") or row.get("code_norm") or "").strip().upper()
        if code.isdigit():
            code = f"HK.{code.zfill(5)}"
        if not (
            re.fullmatch(r"HK\.\d{5}", symbol)
            and code == symbol
            and symbol not in seen
            and row.get("market") == "HK"
            and row.get("signal_date") == signal_date
            and row.get("target_date", row.get("trade_date")) == trade_date
            and row.get("trade_date", trade_date) == trade_date
            and row.get("pool_rank", row.get("rank")) == index
            and row.get("selected_strategy") == "prob_active"
            and all(row.get(flag) is False for flag in (
                "production_allowed", "buy_gate_updated", "orders_sent"
            ))
        ):
            return False
        try:
            score = float(row.get("pool_score"))
        except (TypeError, ValueError):
            return False
        if not math.isfinite(score):
            return False
        seen.add(symbol)
    return True


def _is_allowed_hk_0_2_verified_upgrade(
    existing_payload: Mapping[str, Any],
    payload: Mapping[str, Any],
    trade_date: str,
) -> bool:
    return _is_exact_hk_0_2_missing_placeholder(
        existing_payload, trade_date
    ) and _is_verified_hk_0_2_pool_result(payload, trade_date)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_exact_baimao_missing_placeholder(
    payload: Mapping[str, Any], trade_date: str
) -> bool:
    """Identify only the adapter's empty, fail-closed Baimao placeholder."""

    rows = payload.get("rows")
    pool_size = payload.get(
        "pool_size", len(rows) if isinstance(rows, list) else None
    )
    return (
        payload.get("pool_id") == _BAIMAO_POOL_ID
        and payload.get("trade_date") == trade_date
        and payload.get("market") == "A"
        and payload.get("status") == "CANNOT_CONFIRM"
        and payload.get("producer_id") == _BAIMAO_MISSING_PRODUCER
        and payload.get("source_role") == "RAW_SOURCE"
        and payload.get("source_sha256") == _BAIMAO_EMPTY_SOURCE_SHA
        and isinstance(rows, list)
        and not rows
        and pool_size == 0
        and isinstance(payload.get("cannot_confirm"), list)
        and bool(payload["cannot_confirm"])
        and payload.get("production_allowed") is False
        and payload.get("buy_gate_updated") is False
        and payload.get("orders_sent") is False
    )


def _is_exact_baimao_verified_pool(
    payload: Mapping[str, Any], trade_date: str
) -> bool:
    """Identify the sole verified Baimao target allowed by the stage contract."""

    rows = payload.get("rows")
    pool_size = payload.get(
        "pool_size", len(rows) if isinstance(rows, list) else None
    )
    source_path = str(payload.get("source_path") or "").strip()
    source_sha = str(payload.get("source_sha256") or "").lower()
    return (
        payload.get("pool_id") == _BAIMAO_POOL_ID
        and payload.get("trade_date") == trade_date
        and payload.get("market") == "A"
        and payload.get("status") == "BAIMAO_RESEARCH_MAP_READY"
        and payload.get("producer_id") == _BAIMAO_VERIFIED_PRODUCER
        and payload.get("source_role") == _BAIMAO_VERIFIED_SOURCE_ROLE
        and bool(source_path)
        and _SHA256.fullmatch(source_sha) is not None
        and isinstance(rows, list)
        and bool(rows)
        and pool_size == len(rows)
        and payload.get("production_allowed") is False
        and payload.get("buy_gate_updated") is False
        and payload.get("orders_sent") is False
    )


def _is_allowed_baimao_verified_upgrade(
    existing_payload: Mapping[str, Any],
    payload: Mapping[str, Any],
    trade_date: str,
) -> bool:
    """Allow one narrow fail-closed Baimao placeholder self-healing transition."""

    return _is_exact_baimao_missing_placeholder(
        existing_payload, trade_date
    ) and _is_exact_baimao_verified_pool(payload, trade_date)


def _is_exact_a_share_v192_missing_placeholder(
    payload: Mapping[str, Any], trade_date: str
) -> bool:
    """Identify the one fail-closed A-share V1.9.2 input placeholder."""

    rows = payload.get("rows")
    pool_size = payload.get("pool_size", 0)
    return (
        payload.get("pool_id") == _V192_POOL_ID
        and payload.get("trade_date") == trade_date
        and payload.get("market") == "A"
        and payload.get("status") == "CANNOT_CONFIRM"
        and payload.get("producer_id") == _V192_MISSING_PRODUCER
        and payload.get("source_role") == "EXPECTED_MISSING"
        and payload.get("source_path") == ""
        and payload.get("source_sha256") == _BAIMAO_EMPTY_SOURCE_SHA
        and "source_artifact_sha256" not in payload
        and "source_run_id" not in payload
        and isinstance(rows, list)
        and not rows
        and (
            pool_size is None
            or (isinstance(pool_size, int) and not isinstance(pool_size, bool) and pool_size == 0)
        )
        and isinstance(payload.get("cannot_confirm"), list)
        and bool(payload["cannot_confirm"])
        and payload.get("production_allowed") is False
        and payload.get("buy_gate_updated") is False
        and payload.get("orders_sent") is False
    )


def _is_exact_a_share_v192_verified_pool(
    payload: Mapping[str, Any], trade_date: str
) -> bool:
    """Identify the exact shared V1.9.2 A-share promotion target."""

    rows = payload.get("rows")
    source_sha = str(payload.get("source_sha256") or "").lower()
    source_artifact_sha = str(payload.get("source_artifact_sha256") or "").lower()
    source_path = str(payload.get("source_path") or "").strip()
    source_run_id = str(payload.get("source_run_id") or "").strip()
    return (
        payload.get("pool_id") == _V192_POOL_ID
        and payload.get("trade_date") == trade_date
        and payload.get("market") == "A"
        and payload.get("status") == _V192_VERIFIED_STATUS
        and payload.get("producer_id") == _V192_VERIFIED_PRODUCER
        and payload.get("source_role") == _V192_VERIFIED_SOURCE_ROLE
        and payload.get("artifact_role") == _V192_ARTIFACT_ROLE
        and payload.get("artifact_version") == "V3"
        and payload.get("source_merge_role") == "MAIN_STAGE_INPUT"
        and source_path == f"runs/{trade_date}/{_V192_ARTIFACT_ROLE}/{source_run_id}/artifact.csv"
        and _SHA256.fullmatch(source_sha) is not None
        and _SHA256.fullmatch(source_artifact_sha) is not None
        and source_sha == source_artifact_sha
        and re.fullmatch(
            rf"{trade_date}-a-share-v192-premarket-pool-v3-[0-9a-f]+",
            source_run_id,
        ) is not None
        and isinstance(rows, list)
        and bool(rows)
        and payload.get("source_row_count") == len(rows)
        and bool(payload.get("signal_date"))
        and payload.get("target_date") == trade_date
        and payload.get("stage_selection_eligible") is True
        and payload.get("production_allowed") is False
        and payload.get("buy_gate_updated") is False
        and payload.get("orders_sent") is False
    )


def _is_allowed_a_share_v192_verified_upgrade(
    existing_payload: Mapping[str, Any],
    payload: Mapping[str, Any],
    trade_date: str,
) -> bool:
    """Allow only exact placeholder -> verified V1.9.2 promotion."""

    return _is_exact_a_share_v192_missing_placeholder(
        existing_payload, trade_date
    ) and _is_exact_a_share_v192_verified_pool(payload, trade_date)


def _source_paths(payload: Mapping[str, Any]) -> set[str]:
    return {
        item.strip()
        for item in str(payload.get("source_path") or "").split("|")
        if item.strip()
    }


def _row_identity(row: Mapping[str, Any]) -> str:
    for field in ("symbol", "code", "ts_code"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def _hourly_research_append_only(
    trade_date: str,
    existing_payload: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> bool:
    """Allow only same-day verified hourly source-set extensions."""

    if (
        str(existing_payload.get("source_role") or "")
        != "VERIFIED_HOURLY_RESEARCH"
        or str(payload.get("source_role") or "") != "VERIFIED_HOURLY_RESEARCH"
        or str(existing_payload.get("trade_date") or "") != trade_date
        or str(payload.get("trade_date") or "") != trade_date
        or str(existing_payload.get("market") or "")
        != str(payload.get("market") or "")
    ):
        return False
    old_paths = _source_paths(existing_payload)
    new_paths = _source_paths(payload)
    if not old_paths or not old_paths < new_paths:
        return False
    old_dates = {
        token
        for path in old_paths
        for token in re.findall(r"\d{8}", path)
    }
    new_dates = {
        token
        for path in new_paths
        for token in re.findall(r"\d{8}", path)
    }
    if not new_dates.issubset(old_dates | {trade_date}):
        return False
    for field in ("signal_date", "target_date"):
        if field in existing_payload and field in payload:
            if str(existing_payload.get(field) or "") != str(payload.get(field) or ""):
                return False
    old_rows = existing_payload.get("rows")
    new_rows = payload.get("rows")
    if not isinstance(old_rows, list) or not isinstance(new_rows, list):
        return False
    old_ids = {_row_identity(row) for row in old_rows if isinstance(row, Mapping)}
    new_ids = {_row_identity(row) for row in new_rows if isinstance(row, Mapping)}
    old_ids.discard("")
    return old_ids.issubset(new_ids)


class PreselectionPoolStore:
    """Store each graph-defined pool as its own immutable artifact."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    def _read(self, relative: str) -> Any:
        return json.loads(self._path(relative).read_text(encoding="utf-8"))

    def _write(self, relative: str, value: Any) -> None:
        destination = self._path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(_canonical_bytes(value))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def _lock(self):
        path = self._path("preselection_pools/.materialize.lock")
        with owned_interprocess_lock(
            path,
            timeout_seconds=10,
            timeout_message="preselection-pool materialization lock timeout",
        ):
            yield

    @staticmethod
    def _relative(trade_date: str, pool_id: str) -> tuple[str, str]:
        return (
            f"preselection_pools/{trade_date}/{pool_id}.json",
            f"preselection_pools/{trade_date}/receipts/{pool_id}.json",
        )

    @staticmethod
    def _receipt(
        *,
        trade_date: str,
        pool_id: str,
        artifact_path: str,
        artifact_sha256: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": "v3_5.preselection_pool_receipt.v1",
            "trade_date": trade_date,
            "pool_id": pool_id,
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha256,
            "source_sha256": payload["source_sha256"],
            "source_role": payload["source_role"],
        }
        for key in RECEIPT_EXTENSION_FIELDS:
            if key in payload:
                receipt[key] = payload[key]
        return receipt

    def materialize(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date = validate_pool_artifact(payload)
        pool_id = str(payload["pool_id"])
        with self._lock():
            return self._materialize_locked(payload, trade_date, pool_id)

    def _materialize_locked(
        self,
        payload: Mapping[str, Any],
        trade_date: str,
        pool_id: str,
    ) -> dict[str, str]:
        artifact_path, receipt_path = self._relative(trade_date, pool_id)
        manifest_path = f"preselection_pools/{trade_date}/manifest.json"
        digest = _sha256(payload)
        receipt = self._receipt(
            trade_date=trade_date,
            pool_id=pool_id,
            artifact_path=artifact_path,
            artifact_sha256=digest,
            payload=payload,
        )
        manifest_file = self._path(manifest_path)
        manifest = self._read(manifest_path) if manifest_file.is_file() else {}
        if not isinstance(manifest, dict):
            raise ValueError("invalid preselection-pool manifest")
        existing = manifest.get(pool_id)
        artifact_file = self._path(artifact_path)
        receipt_file = self._path(receipt_path)
        if existing is not None:
            if not artifact_file.is_file() or not receipt_file.is_file():
                raise ValueError("conflicting preselection-pool materialization")
            existing_payload = self._read(artifact_path)
            existing_receipt = self._read(receipt_path)
            if (
                _sha256(existing_payload) != existing
                or existing_receipt != self._receipt(
                    trade_date=trade_date,
                    pool_id=pool_id,
                    artifact_path=artifact_path,
                    artifact_sha256=existing,
                    payload=existing_payload,
                )
            ):
                raise ValueError("conflicting preselection-pool materialization")
            if existing == digest:
                if existing_receipt != receipt:
                    raise ValueError("conflicting preselection-pool materialization")
                return {
                    "artifact_path": artifact_path,
                    "receipt_path": receipt_path,
                    "sha256": digest,
                }
            source_upgrade = (
                str(existing_payload.get("source_role") or ""),
                str(payload.get("source_role") or ""),
            ) in _ALLOWED_SOURCE_UPGRADES.get(pool_id, set())
            baimao_verified_upgrade = _is_allowed_baimao_verified_upgrade(
                existing_payload, payload, trade_date
            )
            v192_verified_upgrade = _is_allowed_a_share_v192_verified_upgrade(
                existing_payload, payload, trade_date
            )
            hk_0_2_verified_upgrade = (
                _is_allowed_hk_0_2_verified_upgrade(
                    existing_payload, payload, trade_date
                )
                if pool_id == _HK_0_2_POOL_ID
                else False
            )
            missing_evidence_refresh = (
                pool_id in _REFRESHABLE_SOURCE_POOLS
                and existing_payload.get("source_role") == "EXPECTED_MISSING"
                and payload.get("source_role") == "EXPECTED_MISSING"
            )
            hourly_research_refresh = (
                pool_id == "a_share_research_recommendation_pool"
                and _hourly_research_append_only(
                    trade_date, existing_payload, payload
                )
            )
            if (
                not source_upgrade
                and not baimao_verified_upgrade
                and not v192_verified_upgrade
                and not hk_0_2_verified_upgrade
                and not missing_evidence_refresh
                and not hourly_research_refresh
            ):
                raise ValueError("conflicting preselection-pool materialization")
            if (
                payload.get("source_role") == "EXPECTED_MISSING"
                and existing_payload.get("source_role") != "EXPECTED_MISSING"
            ):
                raise ValueError(
                    "refreshable preselection pool cannot downgrade to missing"
                )
            if (
                pool_id in _REFRESHABLE_SOURCE_POOLS
                or v192_verified_upgrade
                or hk_0_2_verified_upgrade
            ):
                self._archive_revision(
                    trade_date,
                    pool_id,
                    existing,
                    existing_payload,
                    existing_receipt,
                )
                self._archive_revision(trade_date, pool_id, digest, payload, receipt)
            self._write(artifact_path, payload)
            self._write(receipt_path, receipt)
            manifest[pool_id] = digest
            self._write(manifest_path, manifest)
            return {
                "artifact_path": artifact_path,
                "receipt_path": receipt_path,
                "sha256": digest,
            }
        if artifact_file.exists() or receipt_file.exists():
            raise ValueError("partial preselection-pool materialization")
        if pool_id in _REFRESHABLE_SOURCE_POOLS:
            self._archive_revision(trade_date, pool_id, digest, payload, receipt)
        self._write(artifact_path, payload)
        self._write(receipt_path, receipt)
        manifest[pool_id] = digest
        self._write(manifest_path, manifest)
        return {
            "artifact_path": artifact_path,
            "receipt_path": receipt_path,
            "sha256": digest,
        }

    def _archive_revision(
        self,
        trade_date: str,
        pool_id: str,
        digest: str,
        payload: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None:
        artifact_relative = f"preselection_revisions/{trade_date}/{digest}.json"
        receipt_relative = (
            f"preselection_revisions/{trade_date}/{digest}.receipt.json"
        )
        expected_receipt = {
            "schema_version": "v3_5.preselection_pool_revision_receipt.v1",
            "trade_date": trade_date,
            "pool_id": pool_id,
            "artifact_path": artifact_relative,
            "artifact_sha256": digest,
            "source_sha256": payload.get("source_sha256"),
            "source_role": payload.get("source_role"),
            "latest_receipt": dict(receipt),
        }
        artifact_file = self._path(artifact_relative)
        receipt_file = self._path(receipt_relative)
        if artifact_file.exists() or receipt_file.exists():
            if (
                not artifact_file.is_file()
                or _sha256(self._read(artifact_relative)) != digest
                or not receipt_file.is_file()
                or self._read(receipt_relative) != expected_receipt
            ):
                raise ValueError("preselection-pool revision integrity mismatch")
            return
        self._write(artifact_relative, payload)
        self._write(receipt_relative, expected_receipt)

    def read_pool(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        trade_date = _date(trade_date)
        if pool_id not in POOL_ORDER:
            raise ValueError("unknown preselection pool")
        artifact_path, receipt_path = self._relative(trade_date, pool_id)
        manifest_path = f"preselection_pools/{trade_date}/manifest.json"
        if not self._path(artifact_path).is_file():
            raise FileNotFoundError(pool_id)
        payload = self._read(artifact_path)
        digest = _sha256(payload)
        manifest = self._read(manifest_path)
        receipt = self._read(receipt_path)
        expected = self._receipt(
            trade_date=trade_date,
            pool_id=pool_id,
            artifact_path=artifact_path,
            artifact_sha256=digest,
            payload=payload,
        )
        if (
            not isinstance(manifest, dict)
            or manifest.get(pool_id) != digest
            or receipt != expected
        ):
            raise ValueError("preselection-pool manifest or receipt SHA mismatch")
        if validate_pool_artifact(payload) != trade_date or payload["pool_id"] != pool_id:
            raise ValueError("preselection-pool identity mismatch")
        return payload

    def read_pool_snapshot(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        """Read one pool artifact trio with canonical wire-byte identity.

        ``read_pool`` intentionally retains its historical semantic-object
        behavior.  The stage-acquisition gate needs a narrower primitive: each
        physical JSON file is read once, parsed, and required to be byte-for-
        byte equal to the store's canonical encoding.  This prevents harmless
        JSON presentation changes from becoming a different source snapshot
        and returns both the legacy semantic SHA and physical relative paths
        for provenance binding.
        """

        trade_date = _date(trade_date)
        if pool_id not in POOL_ORDER:
            raise ValueError("unknown preselection pool")
        artifact_relative, receipt_relative = self._relative(trade_date, pool_id)
        manifest_relative = f"preselection_pools/{trade_date}/manifest.json"
        artifact_path = self._path(artifact_relative)
        receipt_path = self._path(receipt_relative)
        manifest_path = self._path(manifest_relative)
        for path, label in (
            (artifact_path, "preselection-pool artifact"),
            (manifest_path, "preselection-pool manifest"),
            (receipt_path, "preselection-pool receipt"),
        ):
            if not path.is_file():
                raise FileNotFoundError(f"{label} missing: {path}")

        # Do not route through read_pool: that method decodes first and hashes
        # the resulting object, which intentionally ignores whitespace and
        # key-order mutations.
        artifact_bytes = artifact_path.read_bytes()
        manifest_bytes = manifest_path.read_bytes()
        receipt_bytes = receipt_path.read_bytes()
        try:
            artifact = json.loads(artifact_bytes.decode("utf-8"))
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            receipt = json.loads(receipt_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("preselection-pool physical JSON cannot be parsed") from error
        if not isinstance(artifact, Mapping) or not isinstance(manifest, Mapping) or not isinstance(receipt, Mapping):
            raise ValueError("preselection-pool physical snapshot must contain objects")
        if artifact_bytes != _canonical_bytes(artifact):
            raise ValueError("preselection-pool artifact bytes are not canonical")
        if manifest_bytes != _canonical_bytes(manifest):
            raise ValueError("preselection-pool manifest bytes are not canonical")
        if receipt_bytes != _canonical_bytes(receipt):
            raise ValueError("preselection-pool receipt bytes are not canonical")

        digest = _sha256(artifact)
        expected_receipt = self._receipt(
            trade_date=trade_date,
            pool_id=pool_id,
            artifact_path=artifact_relative,
            artifact_sha256=digest,
            payload=artifact,
        )
        if (
            manifest.get(pool_id) != digest
            or receipt != expected_receipt
        ):
            raise ValueError("preselection-pool manifest or receipt SHA mismatch")
        if validate_pool_artifact(artifact) != trade_date or artifact.get("pool_id") != pool_id:
            raise ValueError("preselection-pool identity mismatch")
        return {
            "artifact": dict(artifact),
            "payload": dict(artifact),
            "manifest": dict(manifest),
            "receipt": dict(receipt),
            "artifact_relative": artifact_relative,
            "manifest_relative": manifest_relative,
            "receipt_relative": receipt_relative,
            "artifact_relative_path": artifact_relative,
            "manifest_relative_path": manifest_relative,
            "receipt_relative_path": receipt_relative,
            # Keep the semantic pool SHA alongside raw byte digests.  For a
            # canonical store file these values are equal by construction.
            "pool_sha256": digest,
            "semantic_sha256": digest,
            "artifact_sha256": digest,
            "artifact_raw_sha256": _sha256_bytes(artifact_bytes),
            "manifest_raw_sha256": _sha256_bytes(manifest_bytes),
            "receipt_raw_sha256": _sha256_bytes(receipt_bytes),
        }

    # Explicit aliases make the narrow primitive discoverable without changing
    # the long-standing read_pool/read_all public behavior.
    read_pool_raw_snapshot = read_pool_snapshot
    read_raw_snapshot = read_pool_snapshot

    def read_all(self, trade_date: str) -> list[dict[str, Any]]:
        trade_date = _date(trade_date)
        pools: list[dict[str, Any]] = []
        for pool_id in POOL_ORDER:
            try:
                pools.append(self.read_pool(trade_date, pool_id))
            except FileNotFoundError:
                continue
        if not pools:
            raise FileNotFoundError(trade_date)
        return pools


def validate_pool_artifact(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("invalid preselection-pool artifact")
    required = {
        "schema_version", "trade_date", "pool_id", "display_name", "market",
        "status", "producer_id", "source_role", "source_path", "source_sha256",
        "rows", "cannot_confirm", "production_allowed", "buy_gate_updated", "orders_sent",
    }
    missing = required - set(payload)
    if missing:
        raise ValueError("missing required preselection-pool fields")
    unknown = set(payload) - required - POOL_ARTIFACT_OPTIONAL_FIELDS
    if unknown:
        raise ValueError("invalid preselection-pool fields")
    if payload.get("schema_version") != "v3_5.preselection_pool.v1":
        raise ValueError("invalid preselection-pool schema")
    trade_date = _date(str(payload.get("trade_date") or ""))
    pool_id = str(payload.get("pool_id") or "")
    if pool_id not in POOL_ORDER or pool_id == "legacy_partial_migration":
        raise ValueError("unknown or legacy preselection pool")
    if payload.get("source_role") == "LEGACY_FINAL_API":
        raise ValueError("legacy final API is oracle-only")
    if payload.get("source_role") not in {
        "RAW_SOURCE",
        "UPSTREAM_PRODUCER_ARTIFACT",
        "EXPECTED_MISSING",
        *FORMAL_SOURCE_ROLES,
    }:
        raise ValueError("invalid preselection source role")
    if not _SHA256.fullmatch(str(payload.get("source_sha256") or "")):
        raise ValueError("invalid preselection source SHA")
    if "source_artifact_sha256" in payload and not _SHA256.fullmatch(
        str(payload.get("source_artifact_sha256") or "")
    ):
        raise ValueError("invalid preselection source artifact SHA")
    if "source_row_count" in payload:
        value = payload["source_row_count"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("invalid preselection source row count")
    if "source_run_id" in payload and not str(payload.get("source_run_id") or "").strip():
        raise ValueError("invalid preselection source run id")
    for field in ("signal_date", "target_date"):
        if field in payload:
            value = str(payload.get(field) or "")
            if _date(value) != value:
                raise ValueError(f"invalid preselection {field}")
    if "target_date" in payload and payload["target_date"] != payload["trade_date"]:
        raise ValueError("preselection target date mismatch")
    if "stage_selection_eligible" in payload and not isinstance(
        payload["stage_selection_eligible"], bool
    ):
        raise ValueError("invalid preselection stage selection flag")
    if any(payload.get(field) is not False for field in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise ValueError("unsafe preselection-pool artifact")
    rows = payload.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("invalid preselection-pool rows")
    if not isinstance(payload.get("cannot_confirm"), list):
        raise ValueError("invalid preselection-pool cannot_confirm")
    if not rows and payload.get("status") not in {"CANNOT_CONFIRM", "MISSING", "VALID_EMPTY"}:
        raise ValueError("empty pool requires an explicit status")
    _assert_safe(payload)
    return trade_date


def _assert_safe(value: Any) -> None:
    unsafe_flags = {
        "production_allowed", "buy_gate_updated", "orders_sent", "order_sent",
        "formal_pool_write", "buy_gate_write", "opens_buy_gate", "order_allowed",
    }
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key.casefold() in unsafe_flags and nested not in (False, 0, None, ""):
                raise ValueError("unsafe preselection-pool trading field")
            _assert_safe(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_safe(nested)
