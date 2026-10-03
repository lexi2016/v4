"""Single-writer production tick for the Mac stage center.

The runner is deliberately an orchestration boundary, not another market data
implementation.  A deployed caller supplies already-reviewed, read-only
collector bridges and selection builders.  The runner owns the things that
must not be duplicated by V3/V3.5: one explicit candidate pointer, one slot
lock, immutable raw publication before selection publication, and fail-closed
receipts for calendar/input/integrity failures.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from . import end_to_end_deadline as _deadline
from .acquisition import AcquisitionPlan, SourceResult, StageUniverseBinding, build_plan
from .candidate_input import CandidateInputError, read_candidate_input
from .calendar import (
    TradingDayState,
    calendar_provenance,
    eligible_stage_markets,
    resolve_market_states,
)
from .contracts import EIGHT_STAGES, SAFETY_FLAGS
from .raw_store import RAW_FIELDS, RawStore, RawStoreError, publish_raw_artifact, validate_rows
from .scheduler import DueDecision, evaluate_due
from .selection import SelectionError, SelectionStore


class RunnerError(ValueError):
    """A runner configuration, input, or integrity failure."""


# This object is the runner-controlled proof that an exact-date formal
# authority overlay was attached.  A raw collector row can carry the legacy
# boolean marker for compatibility, but it cannot manufacture this identity.
# The live selection builder checks this sentinel rather than trusting a
# caller-supplied value.
_FORMAL_AUTHORITY_OVERLAY_PROOF = object()


def lane_status_bundle(
    a_share: StageUniverseBinding,
    hk_connect: StageUniverseBinding,
) -> dict[str, Any]:
    """Summarize independent A/HK universe readiness.

    This is deliberately a pure boundary helper.  It is used by the runner
    and by contract tests to ensure one lane's missing authority cannot erase
    a verified result from the other lane.
    """
    from stage_center._runner_parts.row_evidence import _lane_status_bundle_body as _v4_impl
    return _v4_impl(globals(), a_share, hk_connect)


Collector = Callable[[AcquisitionPlan, str], SourceResult]
SelectionBuilder = Callable[[SourceResult, AcquisitionPlan, Mapping[str, Any]], Mapping[str, Any]]

# These stages consume the V4 hourly research overlay.  A production tick
# must receive that bridge explicitly; it may not infer it from the formal
# pool root (which is a different release and date contract).
V3_RESEARCH_STAGES = frozenset(
    {
        "STAGE_0930_0935",
        "STAGE_0935_0940",
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
    }
)

# The old V3 service only carried the 09:20 second-filter signal into the
# stages that follow the 09:40 hand-off.  Keep this list explicit so an exact
# second-filter artifact is optional for ordinary stages, but never inferred
# from a current or stale source row.
HK_CONTINUATION_STAGES = frozenset(
    {
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
    }
)
HK_STATIC_LANES = frozenset(
    {
        "NEW_HKCONNECT_BATCH",
        "OLD_DEMON_MEMORY",
        "LOW_FLOAT_FILTER",
    }
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_from_hk_binding(
    *,
    root: Path,
    trade_date: str,
    binding: StageUniverseBinding,
) -> Any:
    """Build a plan-only candidate view from the verified HK universe.

    Stage Center's historical ``AcquisitionPlan`` carries one candidate field
    for compatibility.  When the A current is absent, this adapter supplies
    only the HK lane's exact D-1 Top100 binding; it is never used to make
    an A-share selection appear ready.
    """
    from stage_center._runner_parts.hk_input_validation import __candidate_from_hk_binding_body as _v4_impl
    return _v4_impl(globals(), root=root, trade_date=trade_date, binding=binding)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    from stage_center._runner_parts.row_evidence import __atomic_json_body as _v4_impl
    return _v4_impl(globals(), path, payload)


def _date_prefix(trade_date: str) -> str:
    if not re.fullmatch(r"\d{8}", trade_date):
        raise RunnerError("trade_date must be YYYYMMDD")
    return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"


def _evidence_has(evidence: Sequence[Any], key: str, value: str) -> bool:
    needle = f"{key}={value}"
    return any(str(item) == needle for item in evidence)


def _existing_binding_matches(
    evidence: Sequence[Any],
    *,
    market: str,
    expected_sha: str | None,
) -> bool:
    """Accept only this lane's candidate proof (or its exact HK authority).

    HK receipts written before the per-market binding fix may carry the A
    plan-carrier SHA, but their immutable D-1 JSON SHA still proves the HK
    authority.  That narrow compatibility path cannot make an A lane pass and
    still requires the current expected HK binding.
    """
    from stage_center._runner_parts.row_evidence import __existing_binding_matches_body as _v4_impl
    return _v4_impl(globals(), evidence, market=market, expected_sha=expected_sha)


def _evidence_value(evidence: Sequence[Any], key: str) -> str | None:
    prefix = f"{key}="
    values = [str(item)[len(prefix):] for item in evidence if str(item).startswith(prefix)]
    return values[-1] if values else None


def _validated_hk_binding_evidence(
    binding: StageUniverseBinding,
    trade_date: str,
) -> tuple[str, ...]:
    """Validate the already-read HK universe binding for this exact slot."""
    if (
        binding.status != "READY"
        or binding.market != "HK_CONNECT"
        or binding.trade_date != trade_date
        or not re.fullmatch(r"[0-9a-f]{64}", binding.sha256)
        or not binding.source_run_id
        or len(binding.codes) != 100
        or len(set(binding.codes)) != 100
        or any(not re.fullmatch(r"HK\.\d{5}", code) for code in binding.codes)
    ):
        raise RunnerError("HK D1 exact-input binding is invalid")
    if binding.role == "HK_CONNECT_D1_TOP100_PRIOR_VERIFIED_OBSERVATION":
        source_date = _evidence_value(binding.evidence, "hk_d1_source_trade_date")
        signal_date = _evidence_value(binding.evidence, "hk_d1_source_signal_date")
        if (
            not source_date
            or not re.fullmatch(r"\d{8}", source_date)
            or source_date >= trade_date
            or not signal_date
            or not re.fullmatch(r"\d{8}", signal_date)
            or signal_date >= source_date
            or _evidence_value(binding.evidence, "hk_observation_trade_date") != trade_date
            or _evidence_value(binding.evidence, "hk_observation_mode")
            != "HK_SECURITIES_OPEN_HK_CONNECT_CLOSED"
        ):
            raise RunnerError("HK prior-observation exact-input binding is invalid")
    elif (
        binding.role != "HK_CONNECT_D1_TOP100"
        or not _evidence_has(
            binding.evidence, "hk_d1_membership", "exact_date_top100"
        )
    ):
        raise RunnerError("HK D1 exact-input binding role is invalid")
    return tuple(
        dict.fromkeys(
            (*binding.evidence, f"hk_d1_binding_sha256={binding.sha256}")
        )
    )


def _read_bound_prior_hk_d1_payload(
    binding: StageUniverseBinding,
    *,
    d1_root: Path,
    preselection_source_root: Path | str | None,
) -> tuple[Path, Mapping[str, Any], str]:
    """Read the prior D-1 pool under its existing owner lease and verify its trio."""
    _validated_hk_binding_evidence(binding, binding.trade_date)
    source_date = _evidence_value(binding.evidence, "hk_d1_source_trade_date")
    signal_date = _evidence_value(binding.evidence, "hk_d1_source_signal_date")
    bound_path_text = _evidence_value(binding.evidence, "hk_d1_json")
    expected_manifest_sha = _evidence_value(
        binding.evidence, "hk_d1_source_manifest_sha256"
    )
    expected_receipt_sha = _evidence_value(
        binding.evidence, "hk_d1_source_receipt_sha256"
    )
    if (
        not source_date
        or not signal_date
        or not bound_path_text
        or not expected_manifest_sha
        or not expected_receipt_sha
        or not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_receipt_sha)
        or _evidence_value(binding.evidence, "hk_d1_sha256") != binding.sha256
    ):
        raise RunnerError("HK prior-observation binding source identity is incomplete")

    from infrastructure.preselection_pool_store import PreselectionSourceResolver

    resolver = PreselectionSourceResolver(
        d1_root, source_root=preselection_source_root
    )
    identity_keys = (
        "artifact_raw_sha256",
        "manifest_raw_sha256",
        "receipt_raw_sha256",
        "physical_source_root",
        "artifact_relative",
        "manifest_relative",
        "receipt_relative",
    )
    try:
        with resolver.source_read_lease(source_date, timeout_seconds=0):
            owner = resolver.root_for_date(source_date)
            snapshot = resolver.read_pool_snapshot(
                source_date, "hkconnect_d1_top100"
            )
            bound_path = Path(bound_path_text)
            expected_path = owner / str(snapshot.get("artifact_relative") or "")
            if (
                snapshot.get("physical_source_root") != str(owner)
                or bound_path != expected_path
                or snapshot.get("artifact_raw_sha256") != binding.sha256
                or snapshot.get("manifest_raw_sha256") != expected_manifest_sha
                or snapshot.get("receipt_raw_sha256") != expected_receipt_sha
            ):
                raise RunnerError("HK prior-observation binding source identity changed")

            source_binding = _build_hk_d1_binding(owner, source_date)
            if (
                source_binding.sha256 != binding.sha256
                or source_binding.codes != binding.codes
                or source_binding.role != "HK_CONNECT_D1_TOP100"
            ):
                raise RunnerError("HK prior-observation binding source SHA/membership changed")
            signal_dates = {
                str(row.get("signal_date") or "")
                for row in snapshot["artifact"].get(
                    "rows", snapshot["artifact"].get("data", ())
                )
                if isinstance(row, Mapping)
            }
            if signal_dates != {signal_date}:
                raise RunnerError("HK prior-observation source signal date changed")

            confirmed = resolver.read_pool_snapshot(
                source_date, "hkconnect_d1_top100"
            )
            if any(confirmed.get(key) != snapshot.get(key) for key in identity_keys):
                raise RunnerError("HK prior-observation source trio changed during binding read")
            if confirmed.get("artifact") != snapshot.get("artifact"):
                raise RunnerError("HK prior-observation source payload changed during binding read")
            return bound_path, snapshot["artifact"], binding.sha256
    except RunnerError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RunnerError(
            f"HK prior-observation source lease/read CANNOT_CONFIRM: {error}"
        ) from error


@dataclass(frozen=True)
class RunnerConfig:
    """All roots are explicit; no V3/V3.5 relative path inference is allowed."""

    candidate_acquisition_root: Path
    raw_root: Path
    selection_root: Path
    receipt_root: Path
    v3_formal_root: Path | None = None
    v3_research_root: Path | None = None
    # V4-owned hourly research root.  The legacy spelling above remains only
    # for config deserialization compatibility and is never used as a
    # research context source.
    v4_research_data_root: Path | None = None
    # Independent owner root for exact-date shared morning news.  It is kept
    # separate from the hourly research archive root.
    v4_morning_news_root: Path | None = None
    hk_d1_root: Path | None = None
    # Separate read-only owner root retained from the active Stage release.
    # A date directory in hk_d1_root owns that date even when incomplete;
    # source-root fallback is allowed only when the primary date is absent.
    preselection_source_root: Path | None = None
    hk_second_filter_root: Path | None = None
    hk_full_universe_root: Path | None = None
    a_auction_root: Path | None = None
    hk_auction_root: Path | None = None
    # Explicit root for the read-only legacy HK Stage8 RT_DATA replay.  It is
    # required only for STAGE_1545_1555; ordinary stages and STAGE_0925 keep
    # their existing source contracts.
    hk_stage_replay_root: Path | None = None
    # Daily A-share research-panel receipt root.  The target-date D-1 pool is
    # read from ``candidate_acquisition_root``; this root contains the exact
    # signal-date ``a-YYYYMMDD.json`` receipt and its selector parquet path.
    a_research_panel_receipt_root: Path | None = None
    # Explicit runtime bridge inputs.  They are optional only so a static
    # config can be linted without importing a market-data client; production
    # ``tick`` requires both before it will construct the built-in bridges.
    shared_data_root: Path | None = None
    python_path: Path | None = None
    # Compatibility spelling used by the batch-1 dry-run contract.
    candidate_input_root: Path | None = None
    # ``None`` means production mode: exact formal/HK inputs are mandatory and
    # no collector/selection implementation is inferred by this package.
    selection_builders: Mapping[str, SelectionBuilder] | None = None
    # Historical runs are deliberately scoped below an immutable run-specific
    # namespace.  The field is internal to the runner and never points at a
    # live current/latest root.
    backfill_run_id: str | None = None

    def __post_init__(self) -> None:
        candidate = self.candidate_acquisition_root
        alias = self.candidate_input_root
        if alias is not None and Path(candidate).expanduser().resolve() != Path(alias).expanduser().resolve():
            raise RunnerError("candidate_acquisition_root and candidate_input_root disagree")
        object.__setattr__(self, "candidate_acquisition_root", Path(candidate).expanduser().resolve())
        object.__setattr__(self, "raw_root", Path(self.raw_root).expanduser().resolve())
        object.__setattr__(self, "selection_root", Path(self.selection_root).expanduser().resolve())
        object.__setattr__(self, "receipt_root", Path(self.receipt_root).expanduser().resolve())
        object.__setattr__(self, "candidate_input_root", Path(candidate).expanduser().resolve())
        for name in ("v3_formal_root", "v3_research_root", "v4_research_data_root", "v4_morning_news_root", "hk_d1_root", "preselection_source_root", "hk_second_filter_root", "hk_full_universe_root", "a_auction_root", "hk_auction_root", "hk_stage_replay_root", "a_research_panel_receipt_root", "shared_data_root", "python_path"):
            value = getattr(self, name)
            if value is not None:
                expanded = Path(value).expanduser()
                if name == "python_path":
                    # Keep the dependency-bearing venv path lexical.  A venv
                    # commonly exposes ``bin/python`` as a symlink; resolving
                    # it here silently selects the bare interpreter and loses
                    # the venv's installed pytdx/pandas/futu modules.
                    object.__setattr__(self, name, expanded)
                else:
                    object.__setattr__(self, name, expanded.resolve())

    @property
    def injected_test_mode(self) -> bool:
        return self.selection_builders is not None


def build_production_config(
    *,
    candidate_acquisition_root: Path | str,
    raw_root: Path | str,
    selection_root: Path | str,
    receipt_root: Path | str,
    v3_formal_root: Path | str | None = None,
    v3_research_root: Path | str | None = None,
    v4_research_data_root: Path | str | None = None,
    v4_morning_news_root: Path | str | None = None,
    hk_d1_root: Path | str | None = None,
    preselection_source_root: Path | str | None = None,
    hk_second_filter_root: Path | str | None = None,
    hk_full_universe_root: Path | str | None = None,
    a_auction_root: Path | str | None = None,
    hk_auction_root: Path | str | None = None,
    hk_stage_replay_root: Path | str | None = None,
    a_research_panel_receipt_root: Path | str | None = None,
    shared_data_root: Path | str | None = None,
    python_path: Path | str | None = None,
) -> RunnerConfig:
    """Construct a production-shaped config without starting any collector.

    ``v4_research_data_root`` is the explicit V4-owned hourly archive root for
    the six research stages.  ``v3_research_root`` is accepted for older
    serialized configs but is not read by the stage context adapter.
    ``v4_morning_news_root`` is the separate exact-date shared producer store.
    ``shared_data_root`` and ``python_path`` are explicit bridge inputs; the
    runner uses them to construct the packaged read-only collectors at tick
    time.
    """
    from stage_center._runner_parts.configuration import _build_production_config_body as _v4_impl
    return _v4_impl(globals(), candidate_acquisition_root=candidate_acquisition_root, raw_root=raw_root, selection_root=selection_root, receipt_root=receipt_root, v3_formal_root=v3_formal_root, v3_research_root=v3_research_root, v4_research_data_root=v4_research_data_root, v4_morning_news_root=v4_morning_news_root, hk_d1_root=hk_d1_root, preselection_source_root=preselection_source_root, hk_second_filter_root=hk_second_filter_root, hk_full_universe_root=hk_full_universe_root, a_auction_root=a_auction_root, hk_auction_root=hk_auction_root, hk_stage_replay_root=hk_stage_replay_root, a_research_panel_receipt_root=a_research_panel_receipt_root, shared_data_root=shared_data_root, python_path=python_path)


class SlotLock:
    """Cross-process slot lock using the shared persistent kernel mutex protocol."""

    def __init__(self, path: Path | str, *, stale_seconds: float = 300.0):
        self.path = Path(path).expanduser().resolve()
        self.stale_seconds = float(stale_seconds)
        self._token = f"{os.getpid()}:{time.time_ns()}"  # Legacy diagnostic only.
        self._owned = False
        self._lock_context = None
        self._lease = None

    def acquire(self) -> bool:
        from stage_center._runner_parts.slot_lock import _SlotLock_acquire_body as _v4_impl
        return _v4_impl(globals(), self)

    def release(self) -> None:
        from stage_center._runner_parts.slot_lock import _SlotLock_release_body as _v4_impl
        _v4_impl(globals(), self)

    def __enter__(self) -> "SlotLock":
        if not self.acquire():
            raise RunnerError("slot lock is already held")
        return self

    def __exit__(self, *_: Any) -> None:
        self.release()


def _slot_lock_path(config: RunnerConfig, trade_date: str, stage_id: str) -> Path:
    return config.receipt_root / ".locks" / f"{trade_date}-{stage_id}.lock"


def _stage_markets(stage_id: str) -> tuple[str, ...]:
    for stage in EIGHT_STAGES:
        if stage.stage_id == stage_id:
            return stage.markets
    raise RunnerError(f"unknown stage {stage_id!r}")


def _stage_markets_for_date(stage_id: str, trade_date: str) -> tuple[str, ...]:
    """Keep stage lanes isolated by their own securities-market calendar."""
    try:
        return eligible_stage_markets(_stage_markets(stage_id), trade_date)
    except ValueError as error:
        raise RunnerError(str(error)) from error


def _resolve_stage_market_scope(
    stage_id: str,
    trade_date: str,
    *,
    historical_backfill: bool,
    historical_markets: Sequence[str] | None,
) -> tuple[str, ...]:
    """Apply an optional, historical-only lane allowlist to calendar output."""
    eligible = _stage_markets_for_date(stage_id, trade_date)
    if historical_markets is None:
        return eligible
    if not historical_backfill:
        raise RunnerError("historical market allowlist requires historical_backfill")
    if isinstance(historical_markets, (str, bytes)):
        raise RunnerError("historical market allowlist must be a sequence of market ids")
    try:
        requested = tuple(historical_markets)
    except TypeError as error:
        raise RunnerError("historical market allowlist is invalid") from error
    scheduled = _stage_markets(stage_id)
    if any(not isinstance(market, str) or market not in scheduled for market in requested):
        raise RunnerError("historical market allowlist contains a market outside the stage contract")
    if not requested or len(requested) != len(set(requested)):
        raise RunnerError("historical market allowlist must be non-empty and unique")
    if any(market not in eligible for market in requested):
        raise RunnerError("historical market allowlist contains a market closed by the date calendar")
    requested_set = set(requested)
    return tuple(market for market in eligible if market in requested_set)


def _latest_entry(root: Path, filename: str, key: str) -> Mapping[str, Any] | None:
    from stage_center._runner_parts.row_evidence import __latest_entry_body as _v4_impl
    return _v4_impl(globals(), root, filename, key)


def _read_verified_raw_source(root: Path, verified: Mapping[str, Any]) -> SourceResult:
    """Rehydrate a SourceResult from one already verified immutable raw run."""
    from stage_center._runner_parts.row_evidence import __read_verified_raw_source_body as _v4_impl
    return _v4_impl(globals(), root, verified)


def _required_formal_paths(root: Path, trade_date: str) -> tuple[Path, Path]:
    if root.is_file():
        csv_path = root
    else:
        csv_path = root / "formal_pools" / trade_date / f"formal_opening_pool_{trade_date}.csv"
    manifest = csv_path.with_suffix(".manifest.json")
    if not csv_path.is_file() or not manifest.is_file():
        raise RunnerError("exact-date V3 formal pool CSV/manifest missing")
    return csv_path, manifest


def _validate_formal_input(root: Path, trade_date: str) -> tuple[Path, Path, str]:
    from stage_center._runner_parts.selection_input_validation import __validate_formal_input_body as _v4_impl
    return _v4_impl(globals(), root, trade_date)


def _formal_selection_codes(root: Path, trade_date: str) -> tuple[set[str], str]:
    from stage_center._runner_parts.selection_input_validation import __formal_selection_codes_body as _v4_impl
    return _v4_impl(globals(), root, trade_date)


def _find_exact_file(root: Path, trade_date: str, basename: str) -> Path:
    from stage_center._runner_parts.selection_input_validation import __find_exact_file_body as _v4_impl
    return _v4_impl(globals(), root, trade_date, basename)


def _validate_hk_d1(
    root: Path,
    trade_date: str,
    *,
    preselection_source_root: Path | str | None = None,
) -> tuple[Path, str]:
    from stage_center._runner_parts.hk_input_validation import __validate_hk_d1_body as _v4_impl
    return _v4_impl(globals(), root, trade_date, preselection_source_root=preselection_source_root)


def _validate_hk_full_universe(root: Path, trade_date: str) -> tuple[Path, tuple[str, ...], str]:
    from stage_center._runner_parts.hk_input_validation import __validate_hk_full_universe_body as _v4_impl
    return _v4_impl(globals(), root, trade_date)


def _hk_selection_codes(
    root: Path,
    trade_date: str,
    *,
    preselection_source_root: Path | str | None = None,
) -> tuple[set[str], str]:
    from stage_center._runner_parts.hk_input_validation import __hk_selection_codes_body as _v4_impl
    return _v4_impl(globals(), root, trade_date, preselection_source_root=preselection_source_root)


def _build_hk_d1_binding(
    root: Path,
    trade_date: str,
    *,
    preselection_source_root: Path | str | None = None,
) -> StageUniverseBinding:
    """Create the exact fixed D-1 membership shared by acquisition and selection."""
    from stage_center._runner_parts.hk_input_validation import __build_hk_d1_binding_body as _v4_impl
    return _v4_impl(globals(), root, trade_date, preselection_source_root=preselection_source_root)


def _build_hk_stage_binding(
    root: Path,
    trade_date: str,
    *,
    preselection_source_root: Path | str | None = None,
) -> StageUniverseBinding:
    """Bind the exact HK D-1 pool or its exact prior Connect observation."""
    from infrastructure.preselection_pool_store import PreselectionSourceResolver

    resolver = PreselectionSourceResolver(root, source_root=preselection_source_root)
    open_states = {
        TradingDayState.FULL_TRADING_DAY,
        TradingDayState.HALF_TRADING_DAY_AM,
    }
    try:
        target_states = resolve_market_states(trade_date)
        securities_state = target_states["hk_securities"]
        connect_state = target_states["hk_connect"]
        if securities_state is TradingDayState.UNKNOWN or connect_state is TradingDayState.UNKNOWN:
            raise RunnerError("HK D1 target calendar CANNOT_CONFIRM")
        if securities_state not in open_states:
            raise RunnerError(
                f"HK D1 binding unavailable: HK securities market is closed on {trade_date}"
            )

        if connect_state in open_states:
            # An open Connect date always binds only its own exact-date pool.
            with resolver.source_read_lease(trade_date, timeout_seconds=0):
                return _build_hk_d1_binding(
                    root,
                    trade_date,
                    preselection_source_root=preselection_source_root,
                )

        if connect_state is not TradingDayState.NON_TRADING_DAY:
            raise RunnerError("HK D1 Connect calendar CANNOT_CONFIRM")

        def previous_session(market: str) -> str:
            cursor = datetime.strptime(trade_date, "%Y%m%d")
            for _ in range(45):
                cursor -= timedelta(days=1)
                candidate_date = cursor.strftime("%Y%m%d")
                state = resolve_market_states(candidate_date)[market]
                if state is TradingDayState.UNKNOWN:
                    raise RunnerError("HK D1 previous-session calendar CANNOT_CONFIRM")
                if state in open_states:
                    return candidate_date
            raise RunnerError("HK D1 previous-session calendar CANNOT_CONFIRM")

        price_signal_date = previous_session("hk_securities")
        source_date = previous_session("hk_connect")
        if source_date >= trade_date:
            raise RunnerError("HK D1 prior Connect session identity CANNOT_CONFIRM")

        with resolver.source_read_lease(source_date, timeout_seconds=0):
            owner = resolver.root_for_date(source_date)
            snapshot = resolver.read_pool_snapshot(
                source_date, "hkconnect_d1_top100"
            )
            if snapshot.get("physical_source_root") != str(owner):
                raise RunnerError("HK D1 prior source owner changed during binding")
            source_binding = _build_hk_d1_binding(
                root,
                source_date,
                preselection_source_root=preselection_source_root,
            )
            source_sha = str(snapshot.get("artifact_raw_sha256") or "")
            source_path = owner / str(snapshot.get("artifact_relative") or "")
            if (
                source_binding.sha256 != source_sha
                or _evidence_value(source_binding.evidence, "hk_d1_json") != str(source_path)
                or _evidence_value(source_binding.evidence, "hk_d1_sha256") != source_sha
            ):
                raise RunnerError("HK D1 prior artifact identity changed during binding")

            confirmed = resolver.read_pool_snapshot(
                source_date, "hkconnect_d1_top100"
            )
            identity_keys = (
                "artifact_raw_sha256",
                "manifest_raw_sha256",
                "receipt_raw_sha256",
                "physical_source_root",
                "artifact_relative",
                "manifest_relative",
                "receipt_relative",
            )
            if (
                any(confirmed.get(key) != snapshot.get(key) for key in identity_keys)
                or confirmed.get("artifact") != snapshot.get("artifact")
            ):
                raise RunnerError("HK D1 prior source trio changed during binding")

            source_rows = snapshot["artifact"].get(
                "rows", snapshot["artifact"].get("data", ())
            )
            source_signal_dates = {
                str(row.get("signal_date") or "")
                for row in source_rows
                if isinstance(row, Mapping)
            }
            if len(source_signal_dates) != 1:
                raise RunnerError("HK D1 prior signal date identity CANNOT_CONFIRM")
            source_signal_date = next(iter(source_signal_dates))
            if (
                not re.fullmatch(r"\d{8}", source_signal_date)
                or source_signal_date >= source_date
            ):
                raise RunnerError("HK D1 prior signal date is outside its PIT boundary")

            return StageUniverseBinding.ready(
                market="HK_CONNECT",
                trade_date=trade_date,
                role="HK_CONNECT_D1_TOP100_PRIOR_VERIFIED_OBSERVATION",
                codes=source_binding.codes,
                source_run_id=f"hk-d1-{source_date}-{source_sha[:16]}",
                sha256=source_sha,
                evidence=(
                    *source_binding.evidence,
                    f"hk_d1_source_trade_date={source_date}",
                    f"hk_d1_source_signal_date={source_signal_date}",
                    f"hk_d1_source_manifest_sha256={snapshot['manifest_raw_sha256']}",
                    f"hk_d1_source_receipt_sha256={snapshot['receipt_raw_sha256']}",
                    f"hk_observation_trade_date={trade_date}",
                    f"hk_observation_eligibility_source_date={source_date}",
                    f"hk_observation_price_signal_date={price_signal_date}",
                    "hk_observation_mode=HK_SECURITIES_OPEN_HK_CONNECT_CLOSED",
                ),
            )
    except RunnerError:
        raise
    except (OSError, ValueError) as error:
        raise RunnerError(
            f"HK D1 source read lease CANNOT_CONFIRM for {trade_date}: {error}"
        ) from error


def _validate_hk_second_filter(root: Path, trade_date: str) -> tuple[Path, Path, str]:
    from stage_center._runner_parts.hk_input_validation import __validate_hk_second_filter_body as _v4_impl
    return _v4_impl(globals(), root, trade_date)


def _hk_second_filter_codes(root: Path, trade_date: str) -> tuple[set[str], str]:
    from stage_center._runner_parts.hk_input_validation import __hk_second_filter_codes_body as _v4_impl
    return _v4_impl(globals(), root, trade_date)


def _validate_exact_selection_inputs(
    config: RunnerConfig,
    trade_date: str,
    stage_id: str,
    *,
    market: str | None = None,
    hk_binding: StageUniverseBinding | None = None,
) -> tuple[str, ...]:
    """Validate only the exact inputs owned by one market lane.

    The stage has one shared candidate clock but two independently publishable
    market lanes.  A missing HK artifact must therefore be represented on the
    HK lane instead of aborting an otherwise valid A-share lane.  ``market``
    is optional for compatibility with callers that want the whole-stage
    aggregate validation; the runner itself always validates per market.
    """
    from stage_center._runner_parts.selection_input_validation import __validate_exact_selection_inputs_body as _v4_impl
    return _v4_impl(globals(), config, trade_date, stage_id, market=market, hk_binding=hk_binding)


def _attach_stage_research_roots(
    builder_raw: dict[str, Any],
    config: RunnerConfig,
    stage_id: str,
    *,
    market: str,
) -> None:
    """Bind the hourly archive and morning-news owner roots independently."""
    if config.injected_test_mode or market != "A_SHARE" or stage_id not in V3_RESEARCH_STAGES:
        return
    if config.v4_research_data_root is None:
        raise RunnerError(f"V4 research data root is required for {stage_id} A_SHARE")
    if config.v4_morning_news_root is None:
        raise RunnerError(f"V4 morning-news root is required for {stage_id} A_SHARE")
    builder_raw["_v4_research_data_root"] = config.v4_research_data_root
    builder_raw["_v4_morning_news_root"] = config.v4_morning_news_root


def _normal_code(market: str, value: Any) -> str:
    raw = str(value or "").strip().upper()
    match = re.search(r"(\d{6})", raw) if market == "A_SHARE" else re.search(r"(?:HK\.)?(\d{5})", raw)
    return f"{'A' if market == 'A_SHARE' else 'HK'}.{match.group(1)}" if match else raw


def _is_code_display_name(value: Any, code: str) -> bool:
    """Return whether a provider label is only a code placeholder.

    Live quote bridges historically filled missing labels with their symbol.
    That is not a name and must remain replaceable by an exact-date authority.
    """
    normalized = str(value or "").strip().upper()
    canonical = str(code or "").strip().upper()
    return not normalized or normalized == canonical


def _selection_source(
    source: SourceResult,
    *,
    market: str,
    membership: set[str] | None,
) -> SourceResult:
    from stage_center._runner_parts.selection_input_validation import __selection_source_body as _v4_impl
    return _v4_impl(globals(), source, market=market, membership=membership)


def _a_d1_premarket_pool_path(candidate_root: Path, trade_date: str) -> Path:
    candidates = (
        candidate_root / "preselection_pools" / trade_date / "a_d1_premarket_pool.json",
        candidate_root / trade_date / "a_d1_premarket_pool.json",
        candidate_root / "a_d1_premarket_pool.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise RunnerError("exact-date A D-1 premarket pool missing")


def _a_research_receipt_path(receipt_root: Path, signal_date: str) -> Path:
    candidates = (
        receipt_root / f"a-{signal_date}.json",
        receipt_root / "receipts" / f"a-{signal_date}.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise RunnerError("exact-date A research-panel receipt missing")


def _a_selector_name_map(
    *,
    candidate_root: Path,
    research_panel_receipt_root: Path,
    trade_date: str,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Read the exact signal-date A selector panel, fail-closed on drift."""
    from stage_center._runner_parts.a_name_authority import __a_selector_name_map_body as _v4_impl
    return _v4_impl(globals(), candidate_root=candidate_root, research_panel_receipt_root=research_panel_receipt_root, trade_date=trade_date)


def _attach_a_name_authority(
    source: SourceResult,
    *,
    candidate_root: Path,
    research_panel_receipt_root: Path,
    trade_date: str,
) -> SourceResult:
    from stage_center._runner_parts.a_name_authority import __attach_a_name_authority_body as _v4_impl
    return _v4_impl(globals(), source, candidate_root=candidate_root, research_panel_receipt_root=research_panel_receipt_root, trade_date=trade_date)


def _attach_a_authority(source: SourceResult, *, formal_root: Path, trade_date: str) -> SourceResult:
    """Overlay exact formal-pool metadata onto a selection-only copy.

    The acquisition artifact remains untouched.  ``pool_score`` and
    ``formal_rank`` are V3 upstream fields, so they must be read from the
    verified formal CSV instead of inferred from the 125-code acquisition
    universe or defaulted to zero.
    """
    from stage_center._runner_parts.a_candidate_authority import __attach_a_authority_body as _v4_impl
    return _v4_impl(globals(), source, formal_root=formal_root, trade_date=trade_date)


def _attach_hk_authority(
    source: SourceResult,
    *,
    d1_root: Path,
    second_root: Path | None,
    preselection_source_root: Path | str | None,
    trade_date: str,
    stage_id: str,
    hk_binding: StageUniverseBinding | None = None,
) -> SourceResult:
    """Overlay only exact D-1/second-filter fields onto acquired HK rows.

    Fixed-pool acquisition rows alone do not prove a V3 lane.  D-1 contributes
    membership/metadata only; live minute lanes must come from the separate
    code-bounded snapshot probe.  The 09:25 second-filter is the sole explicit
    pre-open lane source.
    """
    from stage_center._runner_parts.hk_candidate_authority import __attach_hk_authority_body as _v4_impl
    return _v4_impl(globals(), source, d1_root=d1_root, second_root=second_root, preselection_source_root=preselection_source_root, trade_date=trade_date, stage_id=stage_id, hk_binding=hk_binding)


def _with_candidate_evidence(
    result: SourceResult,
    candidate: Any,
    extra: Sequence[str] = (),
    *,
    candidate_sha: str | None = None,
    candidate_run_id: str | None = None,
) -> SourceResult:
    """Bind a source to the candidate authority for its own market lane.

    ``CandidateInput`` is retained as the historical plan carrier, but A and
    HK have separate authorities.  A caller that has no verified binding for a
    lane must leave its candidate evidence absent instead of borrowing the
    other market's synthetic SHA.
    """
    from stage_center._runner_parts.row_evidence import __with_candidate_evidence_body as _v4_impl
    return _v4_impl(globals(), result, candidate, extra, candidate_sha=candidate_sha, candidate_run_id=candidate_run_id)


def _project_raw_rows(rows: Sequence[Mapping[str, Any]], *, trade_date: str, stage_id: str, market: str) -> tuple[dict[str, Any], ...]:
    """Project collector rows to the immutable SafeRootStore 19-field shape.

    Collector rows are intentionally richer than raw storage: auction rank,
    D-1 lanes, and second-filter fields belong to the selection-only copy.  We
    retain the original ``SourceResult`` for selection, but raw publication
    receives only the frozen fields.  Missing/invalid required fields are
    rejected before ``RawStore.publish`` so a malformed row cannot advance a
    CANNOT_CONFIRM latest pointer or leave an incomplete bundle behind.
    """
    from stage_center._runner_parts.row_evidence import __project_raw_rows_body as _v4_impl
    return _v4_impl(globals(), rows, trade_date=trade_date, stage_id=stage_id, market=market)


class StageCenterRunner:
    """Run one or all due slots while keeping a single Writer boundary."""

    def __init__(self, config: RunnerConfig, *, collectors: Mapping[str, Collector] | None = None):
        self.config = config
        self.collectors = dict(collectors or {})

    def _validate_hk_auction_root_binding(self, stage_id: str) -> None:
        if stage_id != "STAGE_0925" or self.config.hk_auction_root is None:
            return
        if self.config.hk_second_filter_root is None or self.config.hk_auction_root != self.config.hk_second_filter_root:
            raise RunnerError("production 09:25 HK auction collector must use the same verified HK second-filter root")

    def _prepare_hk_active_snapshots(
        self,
        trade_date: str,
        evaluated_at: datetime,
        *,
        stage_id: str | None = None,
        historical_backfill: bool = False,
    ) -> list[dict[str, Any]]:
        """Delegate the Stage-8-only 15:50 immutable pre-capture.

        The universe loader keeps the existing V4 verified-pool validator at
        the boundary.  On HK-open/Connect-closed days it may use the newest
        earlier verified D-1 membership, preserving the original source date
        and SHA; quotes remain exact to the observation date.
        """
        from stage_center._runner_parts.runner_receipts import _StageCenterRunner__prepare_hk_active_snapshots_body as _v4_impl
        return _v4_impl(globals(), self, trade_date, evaluated_at, stage_id=stage_id, historical_backfill=historical_backfill)

    def due_decisions(self, trade_date: str, evaluated_at: datetime, *, historical_backfill: bool = False) -> tuple[DueDecision, ...]:
        return tuple(evaluate_due(stage.stage_id, trade_date, evaluated_at, historical_backfill=historical_backfill) for stage in EIGHT_STAGES)

    def _backfill_runner(self, run_id: str) -> "StageCenterRunner":
        from stage_center._runner_parts.tick_planning import _StageCenterRunner__backfill_runner_body as _v4_impl
        return _v4_impl(globals(), self, run_id)

    def _receipt_path(self, trade_date: str, stage_id: str) -> Path:
        return self.config.receipt_root / trade_date / stage_id / "receipt.json"

    def _write_receipt(self, payload: Mapping[str, Any], trade_date: str, stage_id: str) -> dict[str, Any]:
        from stage_center._runner_parts.runner_receipts import _StageCenterRunner__write_receipt_body as _v4_impl
        return _v4_impl(globals(), self, payload, trade_date, stage_id)

    def _existing_slot(
        self,
        trade_date: str,
        stage_id: str,
        markets: Sequence[str],
        candidate_sha_by_market: Mapping[str, str | None] | str,
    ) -> tuple[str, dict[str, Any] | None]:
        """Read reusable slot lanes against their own authority bindings.

        The old slot identity carried one candidate SHA for the whole stage.
        That made a missing A current turn the HK D-1 SHA into a global
        mismatch (and made a good HK lane unreusable).  Keep malformed store
        trios fail-closed, while treating a candidate mismatch as a lane-local
        cache miss so the other market can be reused safely.
        """
        from stage_center._runner_parts.slot_idempotency import _StageCenterRunner__existing_slot_body as _v4_impl
        return _v4_impl(globals(), self, trade_date, stage_id, markets, candidate_sha_by_market)

    def _run_one(
        self,
        decision: DueDecision,
        *,
        historical_backfill: bool = False,
        backfill_run_id: str | None = None,
        historical_markets: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        from stage_center._runner_parts.slot_execution import _StageCenterRunner__run_one_body as _v4_impl
        return _v4_impl(globals(), self, decision, historical_backfill=historical_backfill, backfill_run_id=backfill_run_id, historical_markets=historical_markets)

    def tick(
        self,
        trade_date: str,
        evaluated_at: datetime,
        *,
        stage_id: str | None = None,
        historical_backfill: bool = False,
        historical_markets: Sequence[str] | None = None,
        _skip_precapture: bool = False,
    ) -> dict[str, Any]:
        # Capture once per outer scheduler tick, before due work can spend
        # time in another provider. Recursive stage dispatches reuse it.
        from stage_center._runner_parts.tick_planning import _StageCenterRunner_tick_body as _v4_impl
        return _v4_impl(globals(), self, trade_date, evaluated_at, stage_id=stage_id, historical_backfill=historical_backfill, historical_markets=historical_markets, _skip_precapture=_skip_precapture)


__all__ = ["RunnerConfig", "RunnerError", "SlotLock", "StageCenterRunner", "build_production_config"]
