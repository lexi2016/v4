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
from .calendar import TradingDayState, calendar_provenance, eligible_stage_markets, resolve_market_states
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
    lanes = {"A_SHARE": a_share, "HK_CONNECT": hk_connect}
    output: dict[str, Any] = {}
    for market, binding in lanes.items():
        output[market] = {
            "status": binding.status,
            "trade_date": binding.trade_date,
            "role": binding.role,
            "row_count": len(binding.codes),
            "source_run_id": binding.source_run_id,
            "sha256": binding.sha256,
            "evidence": list(binding.evidence),
            **({"error": binding.error} if binding.error else {}),
        }
    if all(binding.status == "READY" for binding in lanes.values()):
        output["overall_status"] = "READY"
    elif any(binding.status == "READY" and binding.codes for binding in lanes.values()):
        output["overall_status"] = "PARTIAL_WITH_ROWS"
    else:
        output["overall_status"] = "CANNOT_CONFIRM"
    return output


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
    from .candidate_input import CandidateInput

    return CandidateInput(
        root=Path(root).expanduser().resolve(),
        trade_date=trade_date,
        current_relative=f"bindings/{trade_date}/HK_CONNECT/{binding.role}/current.json",
        current_sha256=binding.sha256,
        run_id=binding.source_run_id or f"hk-{binding.sha256[:16]}",
        codes=tuple(binding.codes),
        artifact_sha256=binding.sha256,
        manifest_sha256=binding.sha256,
        receipt_sha256=binding.sha256,
        source_projection_sha256=binding.sha256,
        source_evidence=tuple(binding.evidence),
    )


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


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
    if expected_sha is None:
        return False
    if _evidence_has(evidence, "candidate_current_sha256", expected_sha):
        return True
    return market == "HK_CONNECT" and _evidence_has(
        evidence, "hk_d1_json_sha256", expected_sha
    )


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
        dict.fromkeys((*binding.evidence, f"hk_d1_binding_sha256={binding.sha256}"))
    )


def _read_bound_prior_hk_d1_payload(
    binding: StageUniverseBinding,
    *,
    d1_root: Path,
    preselection_source_root: Path | str | None,
) -> tuple[Path, Mapping[str, Any], str]:
    """Read the already-bound prior D-1 pool under its owner lease."""
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
            snapshot = resolver.read_pool_snapshot(source_date, "hkconnect_d1_top100")
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
            confirmed = resolver.read_pool_snapshot(source_date, "hkconnect_d1_top100")
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
    return RunnerConfig(
        candidate_acquisition_root=Path(candidate_acquisition_root),
        raw_root=Path(raw_root),
        selection_root=Path(selection_root),
        receipt_root=Path(receipt_root),
        v3_formal_root=Path(v3_formal_root) if v3_formal_root is not None else None,
        v3_research_root=Path(v3_research_root) if v3_research_root is not None else None,
        v4_research_data_root=(Path(v4_research_data_root) if v4_research_data_root is not None else None),
        v4_morning_news_root=(Path(v4_morning_news_root) if v4_morning_news_root is not None else None),
        hk_d1_root=Path(hk_d1_root) if hk_d1_root is not None else None,
        preselection_source_root=(Path(preselection_source_root) if preselection_source_root is not None else None),
        hk_second_filter_root=Path(hk_second_filter_root) if hk_second_filter_root is not None else None,
        hk_full_universe_root=Path(hk_full_universe_root) if hk_full_universe_root is not None else None,
        a_auction_root=Path(a_auction_root) if a_auction_root is not None else None,
        hk_auction_root=Path(hk_auction_root) if hk_auction_root is not None else None,
        hk_stage_replay_root=Path(hk_stage_replay_root) if hk_stage_replay_root is not None else None,
        a_research_panel_receipt_root=Path(a_research_panel_receipt_root) if a_research_panel_receipt_root is not None else None,
        shared_data_root=Path(shared_data_root) if shared_data_root is not None else None,
        python_path=Path(python_path) if python_path is not None else None,
    )


class SlotLock:
    """Small cross-process slot lock using an exclusive file create."""

    def __init__(self, path: Path | str, *, stale_seconds: float = 300.0):
        self.path = Path(path).expanduser().resolve()
        self.stale_seconds = float(stale_seconds)
        self._token = f"{os.getpid()}:{time.time_ns()}"
        self._owned = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # A lock's age is not evidence that its owner is dead.  In
            # particular, a long-running collector may legitimately exceed
            # ``stale_seconds``.  Only reclaim a lock whose recorded PID is
            # demonstrably gone; malformed/legacy locks are conservatively
            # treated as live until an operator removes them.
            try:
                token = self.path.read_text(encoding="ascii").strip()
            except (FileNotFoundError, OSError, UnicodeError):
                return self.acquire()
            try:
                owner_pid = int(token.split(":", 1)[0])
            except (TypeError, ValueError):
                return False
            if owner_pid <= 0:
                return False
            try:
                os.kill(owner_pid, 0)
            except ProcessLookupError:
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    return self.acquire()
                return self.acquire()
            except PermissionError:
                # The process exists but is not ours; do not steal the slot.
                return False
            except OSError:
                return False
            return False
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(self._token)
            stream.flush()
            os.fsync(stream.fileno())
        self._owned = True
        return True

    def release(self) -> None:
        if not self._owned:
            return
        try:
            if self.path.read_text(encoding="ascii") == self._token:
                self.path.unlink()
        except FileNotFoundError:
            pass
        self._owned = False

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


def _latest_entry(root: Path, filename: str, key: str) -> Mapping[str, Any] | None:
    path = root / filename
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError(f"{filename} is malformed") from error
    entries = payload.get("entries")
    if not isinstance(entries, Mapping):
        raise RunnerError(f"{filename} entries are malformed")
    entry = entries.get(key)
    if entry is None:
        return None
    if not isinstance(entry, Mapping):
        raise RunnerError(f"{filename} entry is malformed")
    return entry


def _read_verified_raw_source(root: Path, verified: Mapping[str, Any]) -> SourceResult:
    """Rehydrate a SourceResult from one already verified immutable raw run."""
    artifact_path = root / str(verified["artifact_relative"])
    rows: list[dict[str, Any]] = []
    try:
        with artifact_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != ("trade_date", "bar_time", *RAW_FIELDS):
                raise RunnerError("verified raw artifact fields mismatch")
            for raw in reader:
                decoded = {field: raw.get(field, "") for field in RAW_FIELDS}
                for field in ("batch_index", "bar_count"):
                    try:
                        decoded[field] = int(decoded[field])
                    except (TypeError, ValueError) as error:
                        raise RunnerError(f"verified raw {field} is not an integer") from error
                for field in ("last_price", "open_price", "high_price", "low_price", "prev_close_price", "turnover", "volume", "bid_price", "ask_price", "bid_vol", "ask_vol"):
                    if decoded[field] in (None, ""):
                        decoded[field] = ""
                    else:
                        try:
                            decoded[field] = float(decoded[field])
                        except (TypeError, ValueError) as error:
                            raise RunnerError(f"verified raw {field} is not numeric") from error
                decoded["temporal_cutoff_safe"] = str(decoded["temporal_cutoff_safe"]).strip().lower() == "true"
                rows.append(decoded)
    except (OSError, UnicodeError, csv.Error) as error:
        raise RunnerError("verified raw artifact unreadable") from error
    return SourceResult(
        source_id=str(verified.get("source_id") or "verified_raw"),
        status=str(verified.get("status") or "CANNOT_CONFIRM"),
        rows=tuple(rows),
        cannot_confirm=tuple(str(item) for item in verified.get("cannot_confirm", ())),
        requested_rows=int(verified.get("requested_rows", len(rows))),
        missing_symbols=tuple(str(item) for item in verified.get("missing_symbols", ())),
        source_evidence=tuple(str(item) for item in verified.get("source_evidence", ())),
    )


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
    csv_path, manifest_path = _required_formal_paths(root, trade_date)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError("V3 formal manifest unreadable") from error
    if manifest.get("trade_date") != trade_date or manifest.get("status") not in {"FORMAL_CONFIRMED", "FORMAL_READY"}:
        raise RunnerError("V3 formal pool identity/status mismatch")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    eligible = [row for row in rows if str(row.get("eligible_for_formal_pool") or "").lower() in {"true", "1", "yes"}]
    if not eligible:
        raise RunnerError("V3 formal pool has no eligible rows")
    raw_codes = [str(row.get("ts_code") or row.get("stock_code") or "").strip().upper() for row in eligible]
    normalized_codes = [f"A.{match.group(1)}" for raw in raw_codes if (match := re.search(r"(\d{6})", raw))]
    if len(normalized_codes) != len(eligible) or len(set(normalized_codes)) != len(normalized_codes):
        raise RunnerError("V3 formal pool eligible membership must be non-empty and unique")
    if int(manifest.get("row_count", -1)) != len(rows):
        raise RunnerError("V3 formal pool manifest row_count mismatch")
    manifest_sha = manifest.get("csv_sha256")
    if not isinstance(manifest_sha, str) or re.fullmatch(r"[0-9a-fA-F]{64}", manifest_sha) is None:
        raise RunnerError("V3 formal csv_sha256 must be a 64-hex digest")
    actual_sha = _sha(csv_path)
    if manifest_sha.lower() != actual_sha:
        raise RunnerError("V3 formal pool CSV SHA mismatch")
    if any(manifest.get(flag) is not False for flag in SAFETY_FLAGS):
        raise RunnerError("V3 formal pool safety flag must be false")
    return csv_path, manifest_path, actual_sha


def _formal_selection_codes(root: Path, trade_date: str) -> tuple[set[str], str]:
    csv_path, _manifest_path, csv_sha = _validate_formal_input(root, trade_date)
    codes: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if str(row.get("eligible_for_formal_pool") or "").lower() not in {"true", "1", "yes"}:
                continue
            raw = str(row.get("ts_code") or row.get("stock_code") or "").strip().upper()
            match = re.search(r"(\d{6})", raw)
            if match:
                codes.add(f"A.{match.group(1)}")
    if not codes:
        raise RunnerError("V3 formal selection code set is empty")
    return codes, csv_sha


def _find_exact_file(root: Path, trade_date: str, basename: str) -> Path:
    if root.is_file():
        return root
    candidates = (
        root / basename,
        root / "preselection_pools" / trade_date / basename,
        root / trade_date / basename,
        root / "universes" / trade_date / basename,
        root / ".runtime" / "data" / "universes" / trade_date / basename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RunnerError(f"exact-date input missing: {basename}")


def _validate_hk_d1(
    root: Path,
    trade_date: str,
    *,
    preselection_source_root: Path | str | None = None,
) -> tuple[Path, str]:
    resolved_snapshot: Mapping[str, Any] | None = None
    source_resolver = None
    if preselection_source_root is not None:
        from infrastructure.preselection_pool_store import PreselectionSourceResolver

        source_resolver = PreselectionSourceResolver(root, source_root=preselection_source_root)
        try:
            resolved_snapshot = source_resolver.read_pool_snapshot(
                trade_date, "hkconnect_d1_top100"
            )
        except (OSError, ValueError) as error:
            raise RunnerError(f"HK D1 snapshot integrity invalid: {error}") from error
        path = Path(resolved_snapshot["physical_source_root"]) / resolved_snapshot["artifact_relative"]
    else:
        path = _find_exact_file(root, trade_date, "hkconnect_d1_top100.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError("HK D1 input unreadable") from error
    if resolved_snapshot is not None:
        if resolved_snapshot.get("artifact") != payload:
            raise RunnerError("HK D1 resolved trio changed during validation")
        try:
            current_snapshot = source_resolver.read_pool_snapshot(
                trade_date, "hkconnect_d1_top100"
            )
        except (OSError, ValueError) as error:
            raise RunnerError("HK D1 resolved source identity changed during validation") from error
        for identity_key in (
            "pool_sha256", "artifact_raw_sha256", "manifest_raw_sha256",
            "receipt_raw_sha256", "physical_source_root", "artifact_relative",
            "manifest_relative", "receipt_relative",
        ):
            if current_snapshot.get(identity_key) != resolved_snapshot.get(identity_key):
                raise RunnerError("HK D1 resolved source identity changed during validation")
        schema_version = payload.get("schema_version")
        if schema_version == "v3_5.preselection_pool.v1":
            if "target_date" in payload and payload.get("target_date") != trade_date:
                raise RunnerError("HK D1 exact-source target_date mismatch")
            if "stage_selection_eligible" in payload and payload.get("stage_selection_eligible") is not True:
                raise RunnerError("HK D1 exact-source stage_selection_eligible is not true")
        elif payload.get("target_date") != trade_date or payload.get("stage_selection_eligible") is not True:
            raise RunnerError("HK D1 exact-source explicit target/eligibility mismatch")
    if payload.get("status") != "STRICT_0_2_READY":
        raise RunnerError("HK D1 status must be STRICT_0_2_READY")
    if resolved_snapshot is not None and (
        payload.get("pool_id") != "hkconnect_d1_top100"
        or payload.get("producer_id") != "v3_shared_hk_0_2_consumer_v1"
        or payload.get("source_role") != "SHARED_VERIFIED_HK_0_2"
    ):
        raise RunnerError("HK D1 exact-source producer/source identity mismatch")
    if any(payload.get(flag) is not False for flag in SAFETY_FLAGS):
        raise RunnerError("HK D1 safety flags must be false")
    rows = payload.get("rows", payload.get("data"))
    if not isinstance(rows, list) or len(rows) != 100:
        raise RunnerError("HK D1 input must contain exactly 100 rows")
    envelope_date = payload.get("target_date", payload.get("trade_date"))
    if envelope_date is not None:
        if envelope_date != trade_date:
            raise RunnerError("HK D1 target_date mismatch")
    else:
        row_dates = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise RunnerError("HK D1 row must be an object")
            row_date = row.get("target_date", row.get("trade_date"))
            if row_date is None:
                raise RunnerError("HK D1 target_date missing")
            row_dates.add(str(row_date))
        if row_dates != {trade_date}:
            raise RunnerError("HK D1 target_date mismatch")
    for row in rows:
        if not isinstance(row, Mapping):
            raise RunnerError("HK D1 row must be an object")
        row_date = row.get("target_date", row.get("trade_date"))
        if row_date is not None and str(row_date) != trade_date:
            raise RunnerError("HK D1 row target_date mismatch")
    # Current authority rows identify the selected model as ``prob_active``
    # (some historical fixtures omit the optional field). When present, bind
    # it explicitly so a strict-status Top100 from another model cannot pass
    # as the HK primary contract.
    model_values = []
    for key in ("model_id", "model", "model_name", "selected_strategy", "weekly_tuning_selected_strategy"):
        value = payload.get(key)
        if value not in (None, ""):
            model_values.append(str(value))
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in ("model_id", "model", "model_name", "selected_strategy", "weekly_tuning_selected_strategy"):
            value = row.get(key)
            if value not in (None, ""):
                model_values.append(str(value))
    if model_values and any("prob_active" not in value.lower() for value in model_values):
        raise RunnerError("HK D1 model identity must be prob_active")
    if payload.get("schema_version") == "v3_5.preselection_pool.v1":
        from infrastructure.preselection_pool_store import PreselectionPoolStore

        # Canonical V4 inputs must use the exact-date physical trio.  The
        # older, standalone D1 JSON adapter below remains a read-only legacy
        # contract; a canonical object cannot downgrade to that adapter.
        if path.parent.name != trade_date or path.parent.parent.name != "preselection_pools":
            raise RunnerError("HK D1 canonical snapshot path invalid")
        try:
            snapshot = PreselectionPoolStore(path.parent.parent.parent).read_pool_snapshot(
                trade_date, "hkconnect_d1_top100"
            )
        except (OSError, ValueError) as error:
            raise RunnerError(f"HK D1 snapshot integrity invalid: {error}") from error
        if snapshot.get("payload") != payload:
            raise RunnerError("HK D1 snapshot changed during validation")
        previous = datetime.strptime(trade_date, "%Y%m%d")
        for _ in range(15):
            previous -= timedelta(days=1)
            previous_date = previous.strftime("%Y%m%d")
            state = resolve_market_states(previous_date)["hk_connect"]
            if state is TradingDayState.UNKNOWN:
                raise RunnerError("HK D1 signal calendar CANNOT_CONFIRM")
            if state in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
                break
        else:
            raise RunnerError("HK D1 signal calendar CANNOT_CONFIRM")
        if payload.get("market") != "HK" or payload.get("source_role") != "SHARED_VERIFIED_HK_0_2":
            raise RunnerError("HK D1 market/source role mismatch")
        codes = []
        for row in rows:
            if row.get("market") != "HK" or row.get("signal_date") != previous_date:
                raise RunnerError("HK D1 row market/signal_date mismatch")
            code = row.get("symbol", row.get("code"))
            if not isinstance(code, str) or re.fullmatch(r"HK\.\d{5}", code) is None:
                raise RunnerError("HK D1 row code invalid")
            if any(row.get(key) not in (None, code) for key in ("code", "symbol")):
                raise RunnerError("HK D1 row code/symbol identity mismatch")
            if any(row.get(key) not in (None, trade_date) for key in ("trade_date", "target_date")):
                raise RunnerError("HK D1 row trade/target_date mismatch")
            codes.append(code)
        if len(set(codes)) != 100:
            raise RunnerError("HK D1 unique Top100 required")
    digest = _sha(path)
    if resolved_snapshot is not None and (
        digest != resolved_snapshot.get("artifact_raw_sha256")
        or source_resolver.root_for_date(trade_date)
        != Path(str(resolved_snapshot["physical_source_root"]))
    ):
        raise RunnerError("HK D1 resolved source identity changed during validation")
    return path, digest


def _validate_hk_full_universe(root: Path, trade_date: str) -> tuple[Path, tuple[str, ...], str]:
    path = _find_exact_file(root, trade_date, "HK_CONNECT_FULL_MARKET.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError("HK full universe unreadable") from error
    if payload.get("trade_date") != trade_date or payload.get("market") != "HK_CONNECT" or payload.get("scope") != "FULL_MARKET":
        raise RunnerError("HK full universe identity/scope mismatch")
    if any(payload.get(flag) is not False for flag in SAFETY_FLAGS):
        raise RunnerError("HK full universe safety flag must be false")
    codes = payload.get("codes")
    if not isinstance(codes, list) or len(codes) < 500 or len(set(codes)) != len(codes) or any(not re.fullmatch(r"HK\.\d{5}", str(code)) for code in codes):
        raise RunnerError("HK full universe must contain unique 500+ HK codes")
    digest = hashlib.sha256(json.dumps(codes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if payload.get("codes_sha256") != digest:
        raise RunnerError("HK full universe codes SHA mismatch")
    return path, tuple(str(code) for code in codes), _sha(path)


def _hk_selection_codes(
    root: Path,
    trade_date: str,
    *,
    preselection_source_root: Path | str | None = None,
) -> tuple[set[str], str]:
    if preselection_source_root is None:
        path, path_sha = _validate_hk_d1(root, trade_date)
    else:
        path, path_sha = _validate_hk_d1(
            root, trade_date, preselection_source_root=preselection_source_root
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", payload.get("data"))
    codes: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw = str(row.get("code") or row.get("ts_code") or row.get("stock_code") or "").strip().upper()
        match = re.search(r"(?:HK\.)?(\d{5})", raw)
        if match:
            codes.add(f"HK.{match.group(1)}")
    if len(codes) != 100:
        raise RunnerError("HK D1 selection code set must contain exactly 100 unique codes")
    return codes, path_sha


def _build_hk_d1_binding(
    root: Path,
    trade_date: str,
    *,
    preselection_source_root: Path | str | None = None,
) -> StageUniverseBinding:
    """Create the exact fixed D-1 membership shared by acquisition and selection."""
    if preselection_source_root is None:
        path, source_sha = _validate_hk_d1(root, trade_date)
        codes, _codes_sha = _hk_selection_codes(root, trade_date)
    else:
        path, source_sha = _validate_hk_d1(
            root, trade_date, preselection_source_root=preselection_source_root
        )
        codes, _codes_sha = _hk_selection_codes(
            root, trade_date, preselection_source_root=preselection_source_root
        )
    if _codes_sha != source_sha:
        raise RunnerError("HK D1 membership SHA changed during binding")
    return StageUniverseBinding.ready(
        market="HK_CONNECT",
        trade_date=trade_date,
        role="HK_CONNECT_D1_TOP100",
        codes=tuple(sorted(codes)),
        source_run_id=f"hk-d1-{source_sha[:16]}",
        sha256=source_sha,
        evidence=(
            f"hk_d1_json={path}",
            f"hk_d1_sha256={source_sha}",
            "hk_d1_membership=exact_date_top100",
        ),
    )


def _build_hk_stage_binding(
    root: Path,
    trade_date: str,
    *,
    preselection_source_root: Path | str | None = None,
) -> StageUniverseBinding:
    """Bind an exact HK D-1 pool, or the latest verified prior pool on an HK-only observation day.

    The prior pool keeps its original artifact date and SHA.  The returned
    binding carries the current observation date separately for Stage Center's
    output slot; it never rewrites or retargets the source artifact.
    """

    states = resolve_market_states(trade_date)
    open_states = {
        TradingDayState.FULL_TRADING_DAY,
        TradingDayState.HALF_TRADING_DAY_AM,
    }
    if not (
        states["hk_securities"] in open_states
        and states["hk_connect"] is TradingDayState.NON_TRADING_DAY
    ):
        from infrastructure.preselection_pool_store import PreselectionSourceResolver

        resolver = PreselectionSourceResolver(root, source_root=preselection_source_root)
        try:
            with resolver.source_read_lease(trade_date, timeout_seconds=0):
                return _build_hk_d1_binding(
                    root,
                    trade_date,
                    preselection_source_root=preselection_source_root,
                )
        except RunnerError:
            raise
        except (OSError, ValueError) as error:
            raise RunnerError(
                f"HK D1 source read lease CANNOT_CONFIRM for {trade_date}: {error}"
            ) from error

    from infrastructure.preselection_pool_store import PreselectionSourceResolver

    resolver = PreselectionSourceResolver(root, source_root=preselection_source_root)
    cursor = datetime.strptime(trade_date, "%Y%m%d")
    connect_sessions_checked = 0
    for _ in range(45):
        cursor -= timedelta(days=1)
        source_date = cursor.strftime("%Y%m%d")
        source_state = resolve_market_states(source_date)["hk_connect"]
        if source_state is TradingDayState.UNKNOWN:
            raise RunnerError("HK D1 previous-session calendar CANNOT_CONFIRM")
        if source_state not in open_states:
            continue
        connect_sessions_checked += 1
        if connect_sessions_checked > 15:
            break
        lease_entered = False
        try:
            with resolver.source_read_lease(source_date, timeout_seconds=0):
                lease_entered = True
                owner = resolver.root_for_date(source_date)
                snapshot = resolver.read_pool_snapshot(
                    source_date, "hkconnect_d1_top100"
                )
                if snapshot.get("physical_source_root") != str(owner):
                    raise RunnerError("HK D1 prior source owner changed during read")
                source_binding = _build_hk_d1_binding(owner, source_date)
                source_sha = str(snapshot.get("artifact_raw_sha256") or "")
                if source_binding.sha256 != source_sha:
                    raise RunnerError("HK D1 prior artifact SHA changed during binding")
                confirmed = resolver.read_pool_snapshot(
                    source_date, "hkconnect_d1_top100"
                )
                for identity_key in (
                    "artifact_raw_sha256", "manifest_raw_sha256", "receipt_raw_sha256",
                    "physical_source_root", "artifact_relative", "manifest_relative",
                    "receipt_relative",
                ):
                    if confirmed.get(identity_key) != snapshot.get(identity_key):
                        raise RunnerError("HK D1 prior source identity changed during binding")
                rows = snapshot["artifact"].get("rows", snapshot["artifact"].get("data"))
                signal_dates = {
                    str(row.get("signal_date") or "")
                    for row in rows
                    if isinstance(row, Mapping)
                }
                if len(signal_dates) != 1 or not next(iter(signal_dates)):
                    raise RunnerError("HK D1 prior signal_date identity is invalid")
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
                        f"hk_d1_source_signal_date={next(iter(signal_dates))}",
                        f"hk_d1_source_manifest_sha256={snapshot['manifest_raw_sha256']}",
                        f"hk_d1_source_receipt_sha256={snapshot['receipt_raw_sha256']}",
                        f"hk_observation_trade_date={trade_date}",
                        "hk_observation_mode=HK_SECURITIES_OPEN_HK_CONNECT_CLOSED",
                    ),
                )
        except FileNotFoundError as error:
            # An absent date/pool is not a source; keep looking for the newest
            # existing, fully verified exact-date snapshot.
            if not lease_entered:
                raise RunnerError(
                    f"HK D1 prior source read lease CANNOT_CONFIRM for {source_date}: {error}"
                ) from error
            continue
        except RunnerError:
            raise
        except (OSError, ValueError) as error:
            raise RunnerError(
                f"HK D1 prior source CANNOT_CONFIRM for {source_date}: {error}"
            ) from error
    raise RunnerError("HK observation pool CANNOT_CONFIRM: no prior verified HK D1 snapshot")


def _validate_hk_second_filter(root: Path, trade_date: str) -> tuple[Path, Path, str]:
    stem = f"hkconnect_0920_auction_second_filter_{trade_date}"
    if root.is_file():
        csv_path = root
        acceptance_path = root.with_suffix(".acceptance.json")
    else:
        candidates = (
            root,
            root / trade_date,
            root / "hkconnect_0920_auction_second_filter",
        )
        csv_path = next((item / f"{stem}.csv" for item in candidates if (item / f"{stem}.csv").is_file()), None)
        acceptance_path = next((item / f"{stem}.acceptance.json" for item in candidates if (item / f"{stem}.acceptance.json").is_file()), None)
        if csv_path is None or acceptance_path is None:
            raise RunnerError("exact-date HK 09:20 second-filter CSV/acceptance missing")
    if not csv_path.is_file() or not acceptance_path.is_file():
        raise RunnerError("exact-date HK 09:20 second-filter pair incomplete")
    try:
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError("HK second-filter acceptance unreadable") from error
    if acceptance.get("target_date") != trade_date or acceptance.get("status") != "AUCTION_SECOND_FILTER_READY":
        raise RunnerError("HK second-filter identity/status mismatch")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if int(acceptance.get("row_count", -1)) != len(rows):
        raise RunnerError("HK second-filter row_count mismatch")
    declared_sha = acceptance.get("csv_sha256")
    if not isinstance(declared_sha, str) or re.fullmatch(r"[0-9a-fA-F]{64}", declared_sha) is None:
        raise RunnerError("HK second-filter csv_sha256 must be a 64-hex digest")
    actual_sha = _sha(csv_path)
    if declared_sha.lower() != actual_sha:
        raise RunnerError("HK second-filter CSV SHA mismatch")
    if acceptance.get("production_allowed") is not False:
        raise RunnerError("HK second-filter production_allowed must be false")
    authority_v2 = acceptance.get("schema_version") == "hkconnect_0920_auction_second_filter.v2"
    # The historical v2 authority predates the envelope's explicit order and
    # buy-gate keys.  Its equivalent safety proof is shadow_only=true; the
    # stage-center envelope adds all three canonical false flags on publish.
    if not authority_v2 and acceptance.get("orders_sent") is not False:
        raise RunnerError("HK second-filter orders_sent must be false")
    gate_keys = [key for key in ("buy_gate_updated", "buy_gate_changed") if key in acceptance]
    if gate_keys:
        if any(acceptance.get(key) is not False for key in gate_keys):
            raise RunnerError("HK second-filter buy gate safety flag must be explicitly false")
    elif authority_v2:
        if acceptance.get("shadow_only") is not True:
            raise RunnerError("HK second-filter shadow_only must be true for authority v2")
    else:
        raise RunnerError("HK second-filter buy gate safety flag must be explicitly false")
    return csv_path, acceptance_path, actual_sha


def _hk_second_filter_codes(root: Path, trade_date: str) -> tuple[set[str], str]:
    csv_path, _acceptance_path, csv_sha = _validate_hk_second_filter(root, trade_date)
    codes: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            raw = str(row.get("code") or row.get("ts_code") or row.get("stock_code") or "").strip().upper()
            match = re.search(r"(?:HK\.)?(\d{5})", raw)
            if match:
                codes.add(f"HK.{match.group(1)}")
    if not codes:
        raise RunnerError("HK second-filter selection code set is empty")
    return codes, csv_sha


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
    evidence: list[str] = []
    if config.injected_test_mode:
        return tuple(evidence)
    requested = (market,) if market is not None else _stage_markets(stage_id)
    unknown = set(requested) - {"A_SHARE", "HK_CONNECT"}
    if unknown:
        raise RunnerError(f"unknown exact-input market(s): {sorted(unknown)!r}")
    if "A_SHARE" in requested:
        if stage_id in V3_RESEARCH_STAGES and config.v4_research_data_root is None:
            raise RunnerError(
                f"V4 research data root is required for {stage_id} A_SHARE"
            )
        if stage_id in V3_RESEARCH_STAGES:
            if config.v4_morning_news_root is None:
                raise RunnerError(
                    f"V4 morning-news root is required for {stage_id} A_SHARE"
                )
            evidence.append(f"v4_research_data_root={config.v4_research_data_root}")
            evidence.append(f"v4_morning_news_root={config.v4_morning_news_root}")
        # Formal/name metadata are optional overlays, not the acquisition
        # authority. A's strict current pointer remains mandatory in _run_one.
        if config.v3_formal_root is None:
            evidence.append("a_formal_overlay_unavailable=ROOT_NOT_BOUND")
        else:
            try:
                formal_csv, formal_manifest, formal_sha = _validate_formal_input(config.v3_formal_root, trade_date)
                evidence.extend((f"formal_csv={formal_csv}", f"formal_manifest={formal_manifest}", f"formal_csv_sha256={formal_sha}"))
            except (RunnerError, OSError, ValueError) as error:
                evidence.append(f"a_formal_overlay_unavailable={error}")
        if config.a_research_panel_receipt_root is None:
            evidence.append("a_name_overlay_unavailable=ROOT_NOT_BOUND")
        else:
            try:
                _mapping, panel_evidence = _a_selector_name_map(
                    candidate_root=config.candidate_acquisition_root,
                    research_panel_receipt_root=config.a_research_panel_receipt_root,
                    trade_date=trade_date,
                )
                evidence.extend(panel_evidence)
            except (RunnerError, OSError, ValueError) as error:
                evidence.append(f"a_name_overlay_unavailable={error}")
    if "HK_CONNECT" in requested:
        if config.hk_d1_root is None:
            raise RunnerError("production HK D1 root is required")
        binding = hk_binding or _build_hk_stage_binding(
            config.hk_d1_root,
            trade_date,
            preselection_source_root=config.preselection_source_root,
        )
        evidence.extend(_validated_hk_binding_evidence(binding, trade_date))
        evidence.append(
            "hk_acquisition_scope=EXACT_D1_TOP100"
            if binding.role == "HK_CONNECT_D1_TOP100"
            else "hk_acquisition_scope=PRIOR_VERIFIED_D1_OBSERVATION"
        )
        # The opening auction is the only stage whose membership is bound to
        # the exact 09:20 second-filter.  Later minute stages use the verified
        # D-1 membership and its code-bounded live snapshot, so they must not be
        # blocked by a missing pre-open artifact.
        if stage_id == "STAGE_0925":
            if config.hk_second_filter_root is None:
                raise RunnerError("production HK second-filter root is required for STAGE_0925")
            second_csv, second_acceptance, second_sha = _validate_hk_second_filter(config.hk_second_filter_root, trade_date)
            evidence.extend((f"hk_second_filter_csv={second_csv}", f"hk_second_filter_acceptance={second_acceptance}", f"hk_second_filter_csv_sha256={second_sha}"))
        if stage_id == "STAGE_1545_1555":
            if config.hk_stage_replay_root is None:
                raise RunnerError("production HK Stage8 replay root is required for STAGE_1545_1555")
            evidence.append(f"hk_stage_replay_root={config.hk_stage_replay_root}")
    return tuple(evidence)


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
    if membership is None:
        return source
    rows = tuple(row for row in source.rows if _normal_code(market, getattr(row, "get", lambda *_: None)("code")) in membership)
    observed = {_normal_code(market, row.get("code")) for row in source.rows}
    missing = tuple(sorted(membership - observed))
    status = source.status
    if not rows:
        status = "CANNOT_CONFIRM"
    elif status == "READY" and (missing or len(rows) < len(membership)):
        status = "PARTIAL_WITH_ROWS"
    return replace(source, status=status, rows=rows, requested_rows=len(membership), missing_symbols=tuple(dict.fromkeys((*source.missing_symbols, *missing))), cannot_confirm=tuple(source.cannot_confirm) + (("SELECTION_MEMBERSHIP_INTERSECTION_EMPTY",) if not rows else ()))


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
    pool_path = _a_d1_premarket_pool_path(candidate_root, trade_date)
    try:
        pool = json.loads(pool_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError("A D-1 premarket pool unreadable") from error
    if not isinstance(pool, Mapping) or pool.get("target_date") != trade_date:
        raise RunnerError("A D-1 premarket pool target_date mismatch")
    if pool.get("status") != "V192_CANDIDATE_READY" or pool.get("stage_selection_eligible") is not True:
        raise RunnerError("A D-1 premarket pool status/eligibility mismatch")
    if any(pool.get(flag) is not False for flag in SAFETY_FLAGS):
        raise RunnerError("A D-1 premarket pool safety flags must be false")
    pool_rows = pool.get("rows", pool.get("data"))
    if not isinstance(pool_rows, list) or not pool_rows:
        raise RunnerError("A D-1 premarket pool rows missing")
    signal_dates = {
        str(row.get("signal_date") or row.get("trade_date") or "").replace("-", "")
        for row in pool_rows
        if isinstance(row, Mapping)
    }
    signal_dates.discard("")
    if len(signal_dates) != 1:
        raise RunnerError("A D-1 premarket pool signal_date is ambiguous")
    signal_date = next(iter(signal_dates))
    if not re.fullmatch(r"\d{8}", signal_date) or signal_date >= trade_date:
        raise RunnerError("A D-1 premarket pool signal_date is not prior to target")
    receipt_path = _a_research_receipt_path(research_panel_receipt_root, signal_date)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RunnerError("A research-panel receipt unreadable") from error
    if not isinstance(receipt, Mapping):
        raise RunnerError("A research-panel receipt status must be READY")
    if receipt.get("status") == "READY":
        receipt_payload: Mapping[str, Any] = receipt
        receipt_date = str(receipt.get("target_date") or "").replace("-", "")
        if receipt_date != signal_date:
            raise RunnerError("A research-panel receipt target_date mismatch")
    elif receipt.get("status") == "ATTEMPTED":
        receipt_date = str(receipt.get("target_date") or "").replace("-", "")
        if receipt_date != signal_date:
            raise RunnerError("A research-panel receipt target_date mismatch")
        lanes = receipt.get("lanes")
        receipt_payload = lanes.get("A") if isinstance(lanes, Mapping) else None
        if not isinstance(receipt_payload, Mapping) or receipt_payload.get("status") != "READY":
            raise RunnerError("A research-panel A lane status must be READY")
        lane_date = str(receipt_payload.get("target_date") or "").replace("-", "")
        if lane_date != signal_date:
            raise RunnerError("A research-panel A lane target_date mismatch")
    else:
        raise RunnerError("A research-panel receipt status must be READY")
    if any(receipt.get(flag) is not False for flag in SAFETY_FLAGS):
        raise RunnerError("A research-panel receipt safety flags must be false")
    if any(receipt_payload.get(flag) is not False for flag in SAFETY_FLAGS):
        raise RunnerError("A research-panel A lane safety flags must be false")
    formula = receipt_payload.get("formula")
    if not isinstance(formula, Mapping) or formula.get("status") != "READY":
        raise RunnerError("A research-panel formula status must be READY")
    formula_date = str(formula.get("target_date") or "").replace("-", "")
    if formula_date != signal_date:
        raise RunnerError("A research-panel formula target_date mismatch")
    selector_value = formula.get("selector")
    if not isinstance(selector_value, str) or not selector_value.startswith("/"):
        raise RunnerError("A research-panel selector parquet path missing")
    selector_path = Path(selector_value).expanduser().resolve()
    receipt_root = Path(research_panel_receipt_root).expanduser().resolve()
    if receipt_root.name == "receipts" and receipt_root.parent.name == "research_panel_daily":
        authority_root = receipt_root.parent.parent
    else:
        authority_root = receipt_root.parent
    try:
        selector_path.relative_to(authority_root)
    except ValueError as error:
        raise RunnerError("A research-panel selector parquet outside authority root") from error
    if not selector_path.is_file():
        raise RunnerError("A research-panel selector parquet missing")
    declared_sha = str(
        formula.get("selector_sha256")
        or receipt_payload.get("selector_sha256")
        or receipt.get("selector_sha256")
        or ""
    )
    if declared_sha:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", declared_sha) or _sha(selector_path).lower() != declared_sha.lower():
            raise RunnerError("A research-panel selector parquet SHA mismatch")
    try:
        import pyarrow.parquet as parquet

        schema = parquet.read_schema(selector_path)
    except Exception as error:
        raise RunnerError("A research-panel selector parquet unreadable") from error
    required = {"trade_date", "name"}
    column_names = set(schema.names)
    if not required.issubset(column_names) or not ({"ts_code", "raw_code"} & column_names):
        raise RunnerError("A research-panel selector parquet name schema missing")
    code_columns = [column for column in ("ts_code", "raw_code") if column in column_names]
    read_columns = ["trade_date", *code_columns, "name"]
    if "stock_name" in column_names:
        read_columns.append("stock_name")
    try:
        table = parquet.read_table(
            selector_path,
            columns=read_columns,
            filters=[("trade_date", "=", signal_date)],
        )
        records = table.to_pylist()
    except Exception as error:
        raise RunnerError("A research-panel selector parquet unreadable") from error
    if not records:
        raise RunnerError("A research-panel selector parquet is empty")
    panel_dates = {str(row.get("trade_date") or "").replace("-", "") for row in records}
    if panel_dates != {signal_date}:
        raise RunnerError("A research-panel selector parquet max trade_date mismatch")
    mapping: dict[str, str] = {}
    for row in records:
        row_date = str(row.get("trade_date") or "").replace("-", "")
        if row_date != signal_date:
            continue
        raw_code = row.get("ts_code") or row.get("raw_code")
        code = _normal_code("A_SHARE", raw_code)
        name = str(row.get("name") or row.get("stock_name") or "").strip()
        if not code or not name or name == code or name == str(raw_code or "").strip():
            continue
        previous = mapping.get(code)
        if previous is not None and previous != name:
            raise RunnerError(f"A research-panel selector name conflict: {code}")
        mapping[code] = name
    if not mapping:
        raise RunnerError("A research-panel selector code-name map is empty")
    evidence = (
        f"a_d1_premarket_pool_json={pool_path}",
        f"a_d1_premarket_pool_sha256={_sha(pool_path)}",
        f"a_research_panel_receipt={receipt_path}",
        f"a_research_panel_receipt_sha256={_sha(receipt_path)}",
        f"a_research_panel_signal_date={signal_date}",
        f"a_research_panel_selector={selector_path}",
        f"a_research_panel_selector_sha256={_sha(selector_path)}",
    )
    return mapping, evidence


def _attach_a_name_authority(
    source: SourceResult,
    *,
    candidate_root: Path,
    research_panel_receipt_root: Path,
    trade_date: str,
) -> SourceResult:
    mapping, evidence = _a_selector_name_map(
        candidate_root=Path(candidate_root),
        research_panel_receipt_root=Path(research_panel_receipt_root),
        trade_date=trade_date,
    )
    enriched: list[dict[str, Any]] = []
    fallback_codes: list[str] = []
    for raw in source.rows:
        merged = dict(raw)
        code = _normal_code("A_SHARE", raw.get("code"))
        name = mapping.get(code)
        if not name:
            # A missing authority label is not a display name. Keep the
            # candidate and its ordering fields, but clear provider/code
            # placeholders so downstream consumers can fail closed.
            name = None
            fallback_codes.append(code)
        merged["code"] = code
        merged["name"] = name
        merged["stock_name"] = name
        enriched.append(merged)
    if fallback_codes:
        evidence = (*evidence, *(
            f"name_authority_missing={code}" for code in sorted(set(fallback_codes))
        ))
    cannot_confirm = source.cannot_confirm
    status = source.status
    if fallback_codes:
        cannot_confirm = tuple(dict.fromkeys((*cannot_confirm, "NAME_AUTHORITY_CODE_NOT_FOUND")))
        if not enriched or source.status == "CANNOT_CONFIRM":
            status = "CANNOT_CONFIRM"
        elif source.status == "READY":
            status = "PARTIAL_WITH_ROWS"
    return replace(
        source,
        status=status,
        rows=tuple(enriched),
        cannot_confirm=cannot_confirm,
        source_evidence=tuple(dict.fromkeys((*source.source_evidence, *evidence))),
    )


def _attach_a_authority(source: SourceResult, *, formal_root: Path, trade_date: str) -> SourceResult:
    """Overlay exact formal-pool metadata onto a selection-only copy.

    The acquisition artifact remains untouched.  ``pool_score`` and
    ``formal_rank`` are V3 upstream fields, so they must be read from the
    verified formal CSV instead of inferred from the 125-code acquisition
    universe or defaulted to zero.
    """
    csv_path, _manifest_path, _csv_sha = _validate_formal_input(formal_root, trade_date)
    authority: dict[str, Mapping[str, Any]] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if str(row.get("eligible_for_formal_pool") or "").lower() not in {"true", "1", "yes"}:
                continue
            match = re.search(r"(\d{6})", str(row.get("ts_code") or row.get("stock_code") or ""))
            if not match:
                continue
            authority[f"A.{match.group(1)}"] = row
    enriched: list[dict[str, Any]] = []
    for raw in source.rows:
        code = _normal_code("A_SHARE", raw.get("code"))
        merged = dict(raw)
        # This private marker is created only by this verified exact-date
        # overlay.  Remove any inherited value before assigning the result so
        # a collector row cannot self-authorize formal membership.
        merged.pop("_formal_authority_overlay_verified", None)
        merged.pop("_formal_authority_overlay_proof", None)
        # PyTDX adapters may expose SH./SZ./BJ. prefixes; the cross-version
        # selection artifact is canonical A.###### regardless of provider.
        merged["code"] = code
        metadata = authority.get(code)
        if metadata is not None:
            merged["formal_eligible"] = True
            merged["formal_rank"] = metadata.get("rank") or metadata.get("pool_rank") or ""
            merged["pool_score"] = metadata.get("score") or metadata.get("pool_score") or 0.0
            merged["candidate"] = {"score": merged["pool_score"]}
            merged["_formal_authority_overlay_verified"] = True
            merged["_formal_authority_overlay_proof"] = _FORMAL_AUTHORITY_OVERLAY_PROOF
            merged["lane_evidence"] = list(dict.fromkeys([*(merged.get("lane_evidence") or ()), "A_SHARE_FORMAL_POOL"]))
        else:
            # Formal membership is an authority overlay, never a default for
            # every exact-date acquisition row. Keep the raw row eligible for
            # the Windows V3 live formula while explicitly proving that it is
            # non-formal and came from the stage acquisition universe.
            merged["formal_eligible"] = False
            merged["formal_rank"] = ""
            merged["_formal_authority_overlay_verified"] = False
            merged.pop("candidate", None)
            merged.pop("pool_score", None)
            lane_evidence = [
                item for item in (merged.get("lane_evidence") or ())
                if item != "A_SHARE_FORMAL_POOL"
            ]
            merged["lane_evidence"] = list(
                dict.fromkeys([*lane_evidence, "STAGE_ACQUISITION_UNIVERSE"])
            )
        enriched.append(merged)
    return replace(
        source,
        rows=tuple(enriched),
        source_evidence=tuple(
            dict.fromkeys(
                (
                    *source.source_evidence,
                    "formal_metadata_overlay=exact_date_authority_only",
                    f"v3_formal_pool_csv_sha256={_csv_sha}",
                    f"v3_formal_pool_trade_date={trade_date}",
                )
            )
        ),
    )


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
    binding = hk_binding or _build_hk_stage_binding(
        d1_root, trade_date, preselection_source_root=preselection_source_root
    )
    if binding.role == "HK_CONNECT_D1_TOP100_PRIOR_VERIFIED_OBSERVATION":
        d1_path, d1_payload, d1_sha = _read_bound_prior_hk_d1_payload(
            binding,
            d1_root=d1_root,
            preselection_source_root=preselection_source_root,
        )
    else:
        _validated_hk_binding_evidence(binding, trade_date)
        d1_path = Path(_evidence_value(binding.evidence, "hk_d1_json") or d1_root)
        d1_sha = binding.sha256
        if _validate_hk_d1(
            d1_root, trade_date, preselection_source_root=preselection_source_root
        )[1] != d1_sha:
            raise RunnerError("HK D1 exact binding SHA changed before authority overlay")
        d1_payload = json.loads(d1_path.read_text(encoding="utf-8"))
    d1_rows = d1_payload.get("rows", d1_payload.get("data")) or []
    authority: dict[str, Mapping[str, Any]] = {}
    for row in d1_rows:
        if not isinstance(row, Mapping):
            continue
        code = _normal_code("HK_CONNECT", row.get("code") or row.get("ts_code") or row.get("stock_code"))
        authority[code] = row
    second: dict[str, Mapping[str, Any]] = {}
    if stage_id == "STAGE_0925" or stage_id in HK_CONTINUATION_STAGES:
        if second_root is None:
            if stage_id == "STAGE_0925":
                raise RunnerError("HK 09:25 second-filter root is required")
        else:
            try:
                csv_path, _acceptance, _sha_value = _validate_hk_second_filter(second_root, trade_date)
            except RunnerError:
                # The continuation lane is an optional overlay for ordinary
                # stages.  A missing/stale exact-date artifact must not make
                # the live stage unusable, and it must never be replaced by
                # a previous date.  STAGE_0925 remains hard-gated below.
                if stage_id == "STAGE_0925":
                    raise
            else:
                with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                    for row in csv.DictReader(stream):
                        code = _normal_code("HK_CONNECT", row.get("code") or row.get("ts_code") or row.get("stock_code"))
                        second[code] = row
    rows: list[dict[str, Any]] = []
    payload_model_id = (
        d1_payload.get("model_id")
        or d1_payload.get("model")
        or d1_payload.get("model_name")
        or d1_payload.get("selected_strategy")
        or ""
    )
    payload_d1_status = str(d1_payload.get("status") or "")

    def _first_present(*values: Any) -> Any:
        for value in values:
            if value not in (None, ""):
                return value
        return ""

    for raw in source.rows:
        code = _normal_code("HK_CONNECT", raw.get("code"))
        merged = dict(raw)
        base = authority.get(code)
        if base:
            for key, value in base.items():
                if key not in {"code", "ts_code", "stock_code", "candidate_lanes", "source_universe", "lane", "membership_gate_ids"} and value not in (None, ""):
                    merged.setdefault(key, value)
            # D-1 is an exact-date name authority.  Quote bridges may encode
            # a missing name as the symbol itself; treat that placeholder as
            # empty so the authority can replace it.  If the exact authority
            # row has no name, retain a genuinely useful quote name and only
            # fall back to the canonical code when no name exists anywhere.
            authority_name = next(
                (
                    base.get(key)
                    for key in ("name", "stock_name", "security_name", "display_name")
                    if not _is_code_display_name(base.get(key), code)
                ),
                None,
            )
            if not _is_code_display_name(authority_name, code):
                merged["name"] = authority_name
                merged["stock_name"] = authority_name
            else:
                quote_name = next(
                    (
                        merged.get(key)
                        for key in ("name", "stock_name", "security_name", "display_name")
                        if not _is_code_display_name(merged.get(key), code)
                    ),
                    code,
                )
                merged["name"] = quote_name
                merged["stock_name"] = quote_name
            merged["d1_status"] = payload_d1_status
            merged["d1_model_id"] = _first_present(
                base.get("model_id"),
                base.get("model"),
                base.get("model_name"),
                base.get("selected_strategy"),
                base.get("weekly_tuning_selected_strategy"),
                payload_model_id,
            )
            merged["d1_prob_active"] = _first_present(
                base.get("prob_active"),
                base.get("probability"),
                base.get("prob_active_score"),
                base.get("score_prob_active"),
                base.get("pool_score"),
            )
            merged["d1_rank"] = _first_present(base.get("pool_rank"), base.get("rank"), base.get("d1_rank"))
            merged["d1_score"] = _first_present(base.get("pool_score"), base.get("score"), base.get("d1_score"))
            merged["d1_source_evidence"] = list(base.get("source_evidence") or ()) if isinstance(base.get("source_evidence"), (list, tuple)) else []
            merged["d1_source_evidence"].extend(binding.evidence)
            if base.get("pool_version"):
                merged["d1_source_evidence"].append(f"hk_d1_pool_version={base['pool_version']}")
            if d1_payload.get("source_sha256"):
                merged["d1_source_evidence"].append(f"hk_d1_source_sha256={d1_payload['source_sha256']}")
        else:
            # A full-market quote row can legitimately have no D-1 metadata;
            # never leave the UI with an empty name in that case.
            quote_name = next(
                (
                    merged.get(key)
                    for key in ("name", "stock_name", "security_name", "display_name")
                    if not _is_code_display_name(merged.get(key), code)
                ),
                code,
            )
            merged["name"] = quote_name
            merged["stock_name"] = quote_name
        # The active lane is a separate exact live-trigger assertion.  The
        # three static lanes are accepted only from this exact D-1 row;
        # copying arbitrary adapter/static labels would recreate the old bug
        # where a static pool became a realtime recommendation.
        live_lanes = [
            str(item)
            for item in (raw.get("candidate_lanes") or ())
            if str(item) == "LIVE_HKCONNECT_GAINER"
        ]
        static_lanes = [
            str(item)
            for item in (base.get("candidate_lanes") or ())
            if str(item) in HK_STATIC_LANES
        ] if base else []
        merged["candidate_lanes"] = list(dict.fromkeys([*live_lanes, *static_lanes]))
        if code in second:
            second_row = second[code]
            for key, value in second_row.items():
                if key not in {"code", "ts_code", "stock_code"} and value not in (None, ""):
                    merged.setdefault(key, value)
            merged["candidate_lanes"] = list(dict.fromkeys([*(merged.get("candidate_lanes") or ()), "PREOPEN_AUCTION_CONTINUATION"]))
        rows.append(merged)
    evidence = list(source.source_evidence)
    evidence.extend(
        (
            "hk_d1_status=STRICT_0_2_READY",
            f"hk_d1_json_sha256={d1_sha}",
            *binding.evidence,
        )
    )
    if payload_model_id:
        evidence.append(f"hk_d1_model_id={payload_model_id}")
    return replace(source, rows=tuple(rows), source_evidence=tuple(dict.fromkeys(evidence)))


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
    evidence = list(result.source_evidence)
    if candidate_sha is not None:
        evidence.extend(
            (
                f"candidate_current_sha256={candidate_sha}",
                f"candidate_run_id={candidate_run_id if candidate_run_id is not None else candidate.run_id}",
            )
        )
    evidence.extend(extra)
    evidence = tuple(dict.fromkeys(evidence))
    return replace(result, source_evidence=evidence)


def _project_raw_rows(rows: Sequence[Mapping[str, Any]], *, trade_date: str, stage_id: str, market: str) -> tuple[dict[str, Any], ...]:
    """Project collector rows to the immutable SafeRootStore 19-field shape.

    Collector rows are intentionally richer than raw storage: auction rank,
    D-1 lanes, and second-filter fields belong to the selection-only copy.  We
    retain the original ``SourceResult`` for selection, but raw publication
    receives only the frozen fields.  Missing/invalid required fields are
    rejected before ``RawStore.publish`` so a malformed row cannot advance a
    CANNOT_CONFIRM latest pointer or leave an incomplete bundle behind.
    """
    projected = tuple(
        {field: row[field] for field in RAW_FIELDS}
        if isinstance(row, Mapping) and all(field in row for field in RAW_FIELDS)
        else dict(row)
        for row in rows
    )
    _validated, issues = validate_rows(projected, trade_date=trade_date, stage_id=stage_id, market=market)
    if issues:
        raise RunnerError(f"raw projection validation failed for {market}: {'; '.join(issues[:3])}")
    return projected


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

        loaded_binding: StageUniverseBinding | None = None

        def universe_loader() -> tuple[Path, tuple[str, ...], str]:
            nonlocal loaded_binding
            if self.config.hk_d1_root is None:
                raise RunnerError("production HK D1 Top100 root is required for Stage 8 pre-capture")
            binding = _build_hk_stage_binding(
                self.config.hk_d1_root,
                trade_date,
                preselection_source_root=self.config.preselection_source_root,
            )
            loaded_binding = binding
            return (
                Path(_evidence_value(binding.evidence, "hk_d1_json") or self.config.hk_d1_root),
                binding.codes,
                binding.sha256,
            )

        from .hk_stage8 import prepare_due_snapshot, prepare_hk_active_snapshot

        results = prepare_due_snapshot(
            self.config,
            trade_date,
            evaluated_at,
            stage_id=stage_id,
            historical_backfill=historical_backfill,
            universe_loader=universe_loader,
            snapshot_preparer=prepare_hk_active_snapshot,
        )
        if loaded_binding is not None:
            source_trade_date = _evidence_value(
                loaded_binding.evidence, "hk_d1_source_trade_date"
            ) or trade_date
            source_signal_date = _evidence_value(
                loaded_binding.evidence, "hk_d1_source_signal_date"
            )
            for item in results:
                item.update({
                    "hk_d1_source_trade_date": source_trade_date,
                    "hk_d1_source_signal_date": source_signal_date,
                    "hk_d1_source_sha256": loaded_binding.sha256,
                    "hk_observation_trade_date": trade_date,
                    "source_evidence": list(loaded_binding.evidence),
                })
        return results

    def due_decisions(self, trade_date: str, evaluated_at: datetime, *, historical_backfill: bool = False) -> tuple[DueDecision, ...]:
        return tuple(evaluate_due(stage.stage_id, trade_date, evaluated_at, historical_backfill=historical_backfill) for stage in EIGHT_STAGES)

    def _backfill_runner(self, run_id: str) -> "StageCenterRunner":
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
            raise RunnerError("historical backfill run id is unsafe")
        base = self.config
        scoped = replace(
            base,
            raw_root=base.raw_root / "backfill" / run_id,
            selection_root=base.selection_root / "backfill" / run_id,
            receipt_root=base.receipt_root / "backfill" / run_id,
            backfill_run_id=run_id,
        )
        return StageCenterRunner(scoped, collectors=self.collectors)

    def _receipt_path(self, trade_date: str, stage_id: str) -> Path:
        return self.config.receipt_root / trade_date / stage_id / "receipt.json"

    def _write_receipt(self, payload: Mapping[str, Any], trade_date: str, stage_id: str) -> dict[str, Any]:
        result = {"schema_version": "stage_center.runner.receipt.v1", "runner": "stage_center", **_deadline.before_receipt(payload), **SAFETY_FLAGS}
        if self.config.backfill_run_id:
            result.update(
                {
                    "mode": "BACKFILL",
                    "backfill_run_id": self.config.backfill_run_id,
                    "latest_updated": False,
                    "current_updated": False,
                    "namespace": {
                        "raw_root": str(self.config.raw_root),
                        "selection_root": str(self.config.selection_root),
                        "receipt_root": str(self.config.receipt_root),
                    },
                }
            )
        receipt_path = self._receipt_path(trade_date, stage_id)
        _atomic_json(receipt_path, result)
        _deadline.receipt_written(receipt_path, result)
        return result

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
        if isinstance(candidate_sha_by_market, str):
            expected_sha = {market: candidate_sha_by_market for market in markets}
        else:
            expected_sha = {market: candidate_sha_by_market.get(market) for market in markets}
        raw_bundle_entry = _latest_entry(self.config.raw_root, "bundle_latest.json", f"{trade_date}/{stage_id}")
        selection_entries: dict[str, Mapping[str, Any] | None] = {
            market: _latest_entry(self.config.selection_root, "selection_latest.json", f"{trade_date}/{stage_id}/{market}")
            for market in markets
        }
        raw_market_present = any(_latest_entry(self.config.raw_root, "latest.json", f"{trade_date}/{stage_id}/{market}") is not None for market in markets)
        present = raw_bundle_entry is not None or raw_market_present or any(value is not None for value in selection_entries.values())
        if not present:
            return "ABSENT", None
        raw_store = RawStore(self.config.raw_root)
        selection_store = SelectionStore(self.config.selection_root)
        raw_verified: dict[str, Mapping[str, Any]] = {}
        selections: dict[str, Mapping[str, Any]] = {}
        candidate_binding_errors: dict[str, str] = {}
        for market in markets:
            raw_entry = _latest_entry(self.config.raw_root, "latest.json", f"{trade_date}/{stage_id}/{market}")
            if raw_entry is not None:
                try:
                    verified = raw_store.verify_run(trade_date, stage_id, market, str(raw_entry.get("run_id")))
                except (RawStoreError, ValueError) as error:
                    raise RunnerError(f"existing raw market integrity failure: {market}") from error
                expected = expected_sha.get(market)
                if expected is None:
                    candidate_binding_errors[market] = "existing raw candidate SHA cannot be verified: market binding unavailable"
                elif _existing_binding_matches(
                    verified.get("source_evidence", ()),
                    market=market,
                    expected_sha=expected,
                ):
                    raw_verified[market] = verified
                else:
                    candidate_binding_errors[market] = f"existing raw candidate SHA mismatch: {market}"
            selection_entry = selection_entries.get(market)
            if selection_entry is not None:
                try:
                    envelope = selection_store.read_verified(trade_date, stage_id, market)
                except (SelectionError, ValueError) as error:
                    raise RunnerError(f"existing selection integrity failure: {market}") from error
                expected = expected_sha.get(market)
                if expected is None:
                    candidate_binding_errors[market] = "existing selection candidate SHA cannot be verified: market binding unavailable"
                elif _existing_binding_matches(
                    envelope.get("source_evidence", ()),
                    market=market,
                    expected_sha=expected,
                ):
                    selections[market] = envelope
                else:
                    candidate_binding_errors[market] = f"existing selection candidate SHA mismatch: {market}"
        if raw_bundle_entry is not None and len(raw_verified) == len(markets):
            try:
                raw = raw_store.read_verified_bundle(trade_date, stage_id)
            except (RawStoreError, ValueError) as error:
                raise RunnerError("existing raw bundle integrity failure") from error
        else:
            raw = {"receipt": {"markets": {market: dict(entry) for market, entry in raw_verified.items()}}}
        if len(raw_verified) == len(markets) and len(selections) == len(markets):
            return "VERIFIED", {"raw": raw, "selections": selections, "raw_verified": raw_verified, "candidate_binding_errors": candidate_binding_errors}
        if not raw_verified and not selections:
            return "ABSENT", None
        return "PARTIAL", {"raw": raw, "selections": selections, "raw_verified": raw_verified, "candidate_binding_errors": candidate_binding_errors}

    def _run_one(
        self,
        decision: DueDecision,
        *,
        historical_backfill: bool = False,
        backfill_run_id: str | None = None,
    ) -> dict[str, Any]:
        if historical_backfill and backfill_run_id is None:
            run_id = uuid4().hex
            return self._backfill_runner(run_id)._run_one(
                decision,
                historical_backfill=True,
                backfill_run_id=run_id,
            )
        trade_date, stage_id = decision.trade_date, decision.stage_id
        markets = _stage_markets_for_date(stage_id, trade_date)
        if not markets:
            raise RunnerError("no securities market is open for this stage date")
        candidate_error = ""
        hk_binding: StageUniverseBinding | None = None
        hk_binding_error = ""
        try:
            candidate = read_candidate_input(self.config.candidate_acquisition_root, trade_date)
        except (CandidateInputError, OSError, ValueError) as error:
            # A and HK have separate fixed authorities; never fill either
            # lane from a full-market scan when the other lane is unavailable.
            candidate = None
            candidate_error = str(error)
            try:
                if "HK_CONNECT" not in markets or self.config.hk_d1_root is None:
                    raise RunnerError("production HK D1 root is required")
                hk_binding = _build_hk_stage_binding(
                    self.config.hk_d1_root,
                    trade_date,
                    preselection_source_root=self.config.preselection_source_root,
                )
            except (RunnerError, OSError, ValueError) as hk_error:
                errors = {"A_SHARE": candidate_error, "HK_CONNECT": str(hk_error)}
                return self._write_receipt({
                    "status": "CANNOT_CONFIRM", "due_status": decision.status,
                    "trade_date": trade_date, "stage_id": stage_id,
                    "error": candidate_error, "first_failed_layer": "EXACT_SELECTION_INPUT_BINDING",
                    "markets": {market: {"status": "CANNOT_CONFIRM", "selected_rows": 0,
                                "cannot_confirm": [errors[market]], "write_performed": False}
                                for market in markets}, "write_performed": False,
                }, trade_date, stage_id)
            candidate = _candidate_from_hk_binding(
                root=self.config.candidate_acquisition_root,
                trade_date=trade_date,
                binding=hk_binding,
            )
        a_candidate_missing = bool(candidate_error)
        if (
            not self.config.injected_test_mode
            and "HK_CONNECT" in markets
            and hk_binding is None
        ):
            try:
                if self.config.hk_d1_root is None:
                    raise RunnerError("production HK D1 root is required")
                hk_binding = _build_hk_stage_binding(
                    self.config.hk_d1_root,
                    trade_date,
                    preselection_source_root=self.config.preselection_source_root,
                )
            except (RunnerError, OSError, ValueError) as error:
                # Keep the HK authority failure lane-local.  A valid A
                # candidate may still be planned and collected independently.
                hk_binding_error = str(error)
        universe_bindings: dict[str, StageUniverseBinding] = {}
        if a_candidate_missing:
            universe_bindings["A_SHARE"] = StageUniverseBinding.unavailable(
                market="A_SHARE", trade_date=trade_date, reason=candidate_error
            )
        else:
            universe_bindings["A_SHARE"] = StageUniverseBinding.ready(
                market="A_SHARE",
                trade_date=trade_date,
                role="A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2",
                codes=tuple(candidate.codes),
                source_run_id=candidate.run_id,
                sha256=candidate.current_sha256,
                evidence=tuple(candidate.source_evidence),
            )
        if hk_binding is not None:
            universe_bindings["HK_CONNECT"] = hk_binding
        candidate_sha_by_market: dict[str, str | None] = {
            market: None for market in markets
        }
        candidate_run_id_by_market: dict[str, str | None] = {
            market: None for market in markets
        }
        if self.config.injected_test_mode:
            for market in markets:
                candidate_sha_by_market[market] = candidate.current_sha256
                candidate_run_id_by_market[market] = candidate.run_id
        else:
            if "A_SHARE" in markets and not a_candidate_missing:
                candidate_sha_by_market["A_SHARE"] = candidate.current_sha256
                candidate_run_id_by_market["A_SHARE"] = candidate.run_id
            if "HK_CONNECT" in markets and hk_binding is not None:
                candidate_sha_by_market["HK_CONNECT"] = hk_binding.sha256
                candidate_run_id_by_market["HK_CONNECT"] = hk_binding.source_run_id
        write_performed = False
        exact_input_errors: dict[str, str] = {}
        sources: dict[str, SourceResult] = {}
        try:
            self._validate_hk_auction_root_binding(stage_id)
            existing_state, existing = self._existing_slot(
                trade_date,
                stage_id,
                markets,
                candidate_sha_by_market,
            )
            if existing_state == "VERIFIED" and existing is not None:
                # An immutable slot may be reused only with its same fixed
                # HK authority. A damaged/replaced D1 input must not be hidden
                # behind the A pointer's unchanged idempotency identity.
                if "HK_CONNECT" in markets and not self.config.injected_test_mode:
                    try:
                        if self.config.hk_d1_root is None:
                            raise RunnerError("production HK D1 root is required")
                        current_hk = _build_hk_stage_binding(
                            self.config.hk_d1_root,
                            trade_date,
                            preselection_source_root=self.config.preselection_source_root,
                        )
                        raw_hk = existing["raw_verified"].get("HK_CONNECT") or {}
                        if not _evidence_has(raw_hk.get("source_evidence", ()), "hk_d1_sha256", current_hk.sha256):
                            raise RunnerError("HK D1 source SHA differs from verified slot")
                    except (RunnerError, OSError, ValueError) as error:
                        published = dict(existing["selections"])
                        published["HK_CONNECT"] = {"status": "CANNOT_CONFIRM", "selection_status": "CANNOT_CONFIRM",
                            "selected_rows": 0, "cannot_confirm": [str(error)], "write_performed": False}
                        return self._write_receipt({"status": "PARTIAL_WITH_ROWS" if "A_SHARE" in published else "CANNOT_CONFIRM",
                            "trade_date": trade_date, "stage_id": stage_id, "due_status": decision.status,
                            "candidate_current_sha256": candidate.current_sha256, "markets": published,
                            "error": str(error), "first_failed_layer": "EXACT_SELECTION_INPUT_BINDING",
                            "write_performed": False}, trade_date, stage_id)
                return self._write_receipt({"status": "NOOP_ALREADY_VERIFIED", "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id, "candidate_current_sha256": candidate.current_sha256, "candidate_run_id": candidate.run_id, "bundle_id": (existing["raw"].get("receipt") or {}).get("bundle_id"), "markets": {market: envelope for market, envelope in existing["selections"].items()}, "write_performed": False}, trade_date, stage_id)
            existing_raw_verified: dict[str, Mapping[str, Any]] = dict((existing or {}).get("raw_verified") or {})
            existing_selections: dict[str, Mapping[str, Any]] = dict((existing or {}).get("selections") or {})
            exact_evidence_by_market: dict[str, tuple[str, ...]] = {}
            exact_input_errors: dict[str, str] = {}
            if a_candidate_missing and "A_SHARE" in markets:
                exact_input_errors["A_SHARE"] = candidate_error
                exact_evidence_by_market["A_SHARE"] = (
                    f"a_share_universe_binding_error={candidate_error}",
                )
            if hk_binding_error and "HK_CONNECT" in markets:
                exact_input_errors["HK_CONNECT"] = hk_binding_error
                exact_evidence_by_market["HK_CONNECT"] = (
                    f"hk_d1_universe_binding_error={hk_binding_error}",
                )
            for market in markets:
                if market == "A_SHARE" and market in exact_input_errors:
                    continue
                try:
                    exact_evidence_by_market[market] = _validate_exact_selection_inputs(
                        self.config, trade_date, stage_id, market=market,
                        hk_binding=universe_bindings.get(market),
                    )
                except RunnerError as error:
                    # Exact-input failures are lane-local. Preserve the
                    # reason for that market while allowing the other lane to
                    # continue through collection and publication.
                    exact_evidence_by_market[market] = ()
                    exact_input_errors[market] = str(error)
            exact_evidence = tuple(
                item
                for market in markets
                for item in exact_evidence_by_market.get(market, ())
            )
            exact_evidence = tuple(
                dict.fromkeys(
                    (
                        *exact_evidence,
                        *(f"{market.lower()}_exact_input_error={error}" for market, error in exact_input_errors.items()),
                    )
                )
            )
            if decision.status not in {"DUE", "LATE_CATCHUP_REPLAY", "HISTORICAL_BACKFILL"}:
                return self._write_receipt({"status": decision.status, "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id, "candidate_current_sha256": candidate.current_sha256, "write_performed": False}, trade_date, stage_id)
            if self.config.injected_test_mode:
                collectors = self.collectors
            else:
                if self.config.shared_data_root is None or self.config.python_path is None:
                    raise RunnerError("production shared_data_root and python_path are required")
                from .live_collectors import production_collectors, production_selection_builders
                if self.collectors:
                    collectors = self.collectors
                elif stage_id == "STAGE_1545_1555":
                    from .hk_stage8 import production_natural_collectors, should_use_natural_route

                    if should_use_natural_route(
                        trade_date,
                        historical_backfill=historical_backfill,
                    ):
                        collectors = production_natural_collectors(
                            snapshot_root=self.config.raw_root,
                        )
                    else:
                        collectors = production_collectors(
                            plan=build_plan(
                                self.config.candidate_acquisition_root,
                                trade_date,
                                stage_id,
                                candidate=candidate,
                                universe_bindings=universe_bindings,
                                historical_backfill=historical_backfill,
                            ),
                            python_path=self.config.python_path,
                            shared_root=self.config.shared_data_root,
                            a_auction_root=self.config.a_auction_root,
                            hk_auction_root=self.config.hk_auction_root,
                            hk_stage_replay_root=self.config.hk_stage_replay_root,
                        )
                else:
                    collectors = production_collectors(
                        plan=build_plan(
                            self.config.candidate_acquisition_root,
                            trade_date,
                            stage_id,
                            candidate=candidate,
                            universe_bindings=universe_bindings,
                            historical_backfill=historical_backfill,
                        ),
                        python_path=self.config.python_path,
                        shared_root=self.config.shared_data_root,
                        a_auction_root=self.config.a_auction_root,
                        hk_auction_root=self.config.hk_auction_root,
                        hk_stage_replay_root=self.config.hk_stage_replay_root,
                    )
                if self.config.selection_builders is None:
                    builders = production_selection_builders(stage_id)
                else:
                    builders = self.config.selection_builders
            missing_raw_markets = tuple(market for market in markets if market not in existing_raw_verified)
            if not set(missing_raw_markets).issubset(set(collectors)):
                raise RunnerError(f"collectors are missing required markets {missing_raw_markets!r}")
            builders = self.config.selection_builders
            if builders is None and not self.config.injected_test_mode:
                from .live_collectors import production_selection_builders
                builders = production_selection_builders(stage_id)
            if builders is None:
                raise RunnerError("production selection builders are not installed")
            missing_builders = tuple(market for market in markets if market not in builders)
            if missing_builders:
                raise RunnerError(
                    f"selection builders are missing required markets {missing_builders!r}"
                )
            # A market closed by its own securities calendar does not need a
            # builder, but every eligible market still needs its exact builder.
            builders = {market: builders[market] for market in markets}
            selection_membership: dict[str, set[str] | None] = {market: None for market in markets}
            if not self.config.injected_test_mode:
                if "HK_CONNECT" in markets and "HK_CONNECT" not in exact_input_errors:
                    try:
                        hk_d1_binding = universe_bindings.get("HK_CONNECT")
                        if hk_d1_binding is None:
                            raise RunnerError("HK D1 binding is unavailable after exact-input validation")
                        _validated_hk_binding_evidence(hk_d1_binding, trade_date)
                        hk_d1_codes = set(hk_d1_binding.codes)
                        # Acquisition and selection share the same exact D-1
                        # Top100 binding already validated above. This binding is required for every HK stage,
                        # not just Stage8; no full-market collection is invoked.
                        selection_membership["HK_CONNECT"] = hk_d1_codes
                        # Minute stages use the frozen D-1 Top100.  The 09:25
                        # stage additionally binds the exact 09:20 second-filter
                        # universe; no current/previous-stage rows can fill it.
                        if stage_id == "STAGE_0925":
                            assert self.config.hk_second_filter_root is not None
                            second_codes, _second_sha = _hk_second_filter_codes(self.config.hk_second_filter_root, trade_date)
                            selection_membership["HK_CONNECT"] = hk_d1_codes & second_codes
                    except RunnerError as error:
                        exact_input_errors["HK_CONNECT"] = str(error)
            plan = build_plan(
                self.config.candidate_acquisition_root,
                trade_date,
                stage_id,
                candidate=candidate,
                universe_bindings=universe_bindings,
                historical_backfill=historical_backfill,
            )
            sources: dict[str, SourceResult] = {}
            selection_sources: dict[str, SourceResult] = {}
            for market in markets:
                if market in exact_input_errors:
                    error = exact_input_errors[market]
                    result = SourceResult(
                        market,
                        "CANNOT_CONFIRM",
                        cannot_confirm=(error,),
                        requested_rows=len(plan.codes_for(market)) or None,
                        source_evidence=(f"exact_input_error={error}",),
                    )
                elif market in existing_raw_verified:
                    result = _read_verified_raw_source(self.config.raw_root, existing_raw_verified[market])
                else:
                    try:
                        _deadline.checkpoint("COLLECTOR_START", market=market, stage_id=stage_id, trade_date=trade_date)
                        result = collectors[market](plan, market)
                        _deadline.checkpoint("COLLECTOR_END", market=market, stage_id=stage_id, trade_date=trade_date,
                                             source_observation=_deadline.source_observation(result))
                        if not isinstance(result, SourceResult):
                            raise RunnerError(f"collector {market} did not return SourceResult")
                    except _deadline.DeadlineExceeded:
                        raise
                    except Exception as error:
                        result = SourceResult(market, "CANNOT_CONFIRM", cannot_confirm=(f"COLLECTOR_ERROR:{type(error).__name__}",), requested_rows=len(plan.codes_for(market)) or None, source_evidence=(f"collector_error={type(error).__name__}",))
                if result.rows and result.requested_rows is not None and len(result.rows) < result.requested_rows and result.status == "READY":
                    result = replace(result, status="PARTIAL_WITH_ROWS")
                elif result.rows and result.missing_symbols and result.status == "READY":
                    result = replace(result, status="PARTIAL_WITH_ROWS")
                # Stage8 selection recovery must re-read the exact replay
                # provider, never rebuild LIVE lanes from a current Futu
                # snapshot.  Raw publication intentionally excludes lane
                # metadata, so a missing selection cannot be reconstructed
                # from the raw CSV alone.
                if (
                    market == "HK_CONNECT"
                    and stage_id == "STAGE_1545_1555"
                    and market in existing_raw_verified
                    and market not in existing_selections
                    and market not in exact_input_errors
                    and not self.config.injected_test_mode
                ):
                    if self.config.hk_stage_replay_root is None:
                        raise RunnerError("HK Stage8 selection recovery requires explicit replay root")
                    _deadline.checkpoint("COLLECTOR_START", market=market, stage_id=stage_id, trade_date=trade_date)
                    result = collectors[market](plan, market)
                    _deadline.checkpoint("COLLECTOR_END", market=market, stage_id=stage_id, trade_date=trade_date,
                                         source_observation=_deadline.source_observation(result))
                # Selection-only recovery must re-run the same read-only V3
                # active trigger when raw is already complete.  Raw bars are
                # never recollected or rewritten, and the active probe's
                # canonical SHA must match the evidence bound to that raw run.
                if (
                    market == "HK_CONNECT"
                    and stage_id != "STAGE_1545_1555"
                    and stage_id != "STAGE_0925"
                    and market in existing_raw_verified
                    and market not in existing_selections
                    and market not in exact_input_errors
                    and not self.config.injected_test_mode
                ):
                    previous_sha = _evidence_value(result.source_evidence, "active_snapshot_sha256")
                    previous_codes_sha = _evidence_value(result.source_evidence, "active_snapshot_codes_sha256")
                    expected_cutoff = next(
                        stage.cutoff for stage in EIGHT_STAGES if stage.stage_id == stage_id
                    )
                    previous_status = _evidence_value(
                        result.source_evidence, "active_snapshot_status"
                    )
                    previous_trade_date = _evidence_value(
                        result.source_evidence, "active_snapshot_trade_date"
                    )
                    previous_cutoff = _evidence_value(
                        result.source_evidence, "active_snapshot_cutoff"
                    )
                    previous_temporal = _evidence_value(
                        result.source_evidence, "active_snapshot_temporal_cutoff_safe"
                    )
                    reuse_degraded_observation = (
                        result.status == "PARTIAL_WITH_ROWS"
                        and bool(result.rows)
                        and previous_temporal == "false"
                        and _evidence_value(
                            result.source_evidence,
                            "active_snapshot_degraded_to_pytdx_observation",
                        )
                        == "true"
                    )
                    recovery_error: str | None = None
                    if not all(
                        (
                            previous_sha,
                            previous_codes_sha,
                            previous_status,
                            previous_trade_date,
                            previous_cutoff,
                        )
                    ):
                        recovery_error = "HK_ACTIVE_SNAPSHOT_EVIDENCE_MISSING"
                    elif not re.fullmatch(r"[0-9a-f]{64}", previous_sha) or not re.fullmatch(
                        r"[0-9a-f]{64}", previous_codes_sha
                    ):
                        recovery_error = "HK_ACTIVE_SNAPSHOT_EVIDENCE_INVALID"
                    elif (
                        previous_status != "FUTU_HKCONNECT_FULL_SCAN"
                        or previous_trade_date != trade_date
                        or previous_cutoff != expected_cutoff
                    ):
                        recovery_error = "HK_ACTIVE_SNAPSHOT_EVIDENCE_INVALID"
                    elif reuse_degraded_observation:
                        # The raw run is already exact-date/exact-stage and
                        # carries the historical PyTDX observation marker.  In
                        # this narrow mode the old runner deliberately reused
                        # those immutable rows instead of asking for a new
                        # current snapshot.  The builder will keep this lane
                        # PARTIAL/WATCH_ONLY and retain the evidence markers.
                        exact_evidence_by_market[market] = tuple(
                            dict.fromkeys(
                                (
                                    *exact_evidence_by_market.get(market, ()),
                                    "hk_active_selection_recovery=DEGRADED_OBSERVATION_REUSE",
                                )
                            )
                        )
                    elif previous_temporal != "true":
                        # An unsafe or unproven historical cutoff cannot be
                        # repaired by reading a new active snapshot. Keep the
                        # HK lane unconfirmed instead of relabelling current
                        # observations as the completed historical stage.
                        recovery_error = "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"
                    else:
                        try:
                            if not plan.codes_for("HK_CONNECT") or self.config.shared_data_root is None or self.config.python_path is None:
                                raise RunnerError("HK active-lane recovery requires explicit fixed D1 bridge roots")
                            from .live_collectors import refresh_hk_active_lanes
                            refreshed = refresh_hk_active_lanes(
                                result,
                                codes=plan.codes_for("HK_CONNECT"),
                                python_path=self.config.python_path,
                                shared_root=self.config.shared_data_root,
                                trade_date=trade_date,
                                stage_id=stage_id,
                                cutoff_at=expected_cutoff,
                            )
                            current_sha = _evidence_value(refreshed.source_evidence, "active_snapshot_sha256")
                            current_codes_sha = _evidence_value(refreshed.source_evidence, "active_snapshot_codes_sha256")
                            if not previous_sha or previous_sha != current_sha or not previous_codes_sha or previous_codes_sha != current_codes_sha:
                                recovery_error = "HK_ACTIVE_SNAPSHOT_EVIDENCE_CHANGED"
                            elif "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in refreshed.cannot_confirm:
                                recovery_error = "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"
                            elif "HK_ACTIVE_GAINER_SNAPSHOT_UNAVAILABLE" in refreshed.cannot_confirm:
                                recovery_error = "HK_ACTIVE_SNAPSHOT_UNAVAILABLE"
                            else:
                                result = refreshed
                        except Exception as error:
                            recovery_error = f"HK_ACTIVE_SELECTION_RECOVERY_FAILED:{type(error).__name__}"
                    if recovery_error:
                        exact_input_errors[market] = recovery_error
                        exact_evidence_by_market[market] = tuple(
                            dict.fromkeys(
                                (
                                    *exact_evidence_by_market.get(market, ()),
                                    f"hk_active_selection_recovery_error={recovery_error}",
                                )
                            )
                        )
                sources[market] = _with_candidate_evidence(
                    result,
                    candidate,
                    (
                        *exact_evidence_by_market.get(market, ()),
                        *((f"exact_input_error={exact_input_errors[market]}",) if market in exact_input_errors else ()),
                        f"due_status={decision.status}",
                    ),
                    candidate_sha=candidate_sha_by_market.get(market),
                    candidate_run_id=candidate_run_id_by_market.get(market),
                )
                if market == "A_SHARE" and not self.config.injected_test_mode and market not in exact_input_errors:
                    selected_source = sources[market]
                    if self.config.v3_formal_root is not None:
                        try:
                            selected_source = _attach_a_authority(selected_source, formal_root=self.config.v3_formal_root, trade_date=trade_date)
                        except (RunnerError, OSError, ValueError) as error:
                            selected_source = replace(selected_source, source_evidence=(*selected_source.source_evidence, f"a_formal_overlay_unavailable={error}"))
                    if self.config.a_research_panel_receipt_root is not None:
                        try:
                            selected_source = _attach_a_name_authority(
                                selected_source, candidate_root=self.config.candidate_acquisition_root,
                                research_panel_receipt_root=self.config.a_research_panel_receipt_root, trade_date=trade_date)
                        except (RunnerError, OSError, ValueError) as error:
                            selected_source = replace(selected_source, source_evidence=(*selected_source.source_evidence, f"a_name_overlay_unavailable={error}"))
                    selection_sources[market] = selected_source
                if (
                    market == "HK_CONNECT"
                    and not self.config.injected_test_mode
                    and self.config.hk_d1_root is not None
                    and market not in exact_input_errors
                ):
                    try:
                        selection_sources[market] = _attach_hk_authority(
                            sources[market],
                            d1_root=self.config.hk_d1_root,
                            second_root=(
                                self.config.hk_second_filter_root
                                if stage_id == "STAGE_0925" or stage_id in HK_CONTINUATION_STAGES
                                else None
                            ),
                            trade_date=trade_date,
                            stage_id=stage_id,
                            preselection_source_root=self.config.preselection_source_root,
                            hk_binding=universe_bindings.get("HK_CONNECT"),
                        )
                    except RunnerError as error:
                        exact_input_errors[market] = str(error)
                if market in exact_input_errors and market not in selection_sources:
                    sources[market] = replace(
                        sources[market],
                        status="CANNOT_CONFIRM",
                        rows=(),
                        cannot_confirm=tuple(dict.fromkeys((*sources[market].cannot_confirm, exact_input_errors[market]))),
                    )
                selection_sources[market] = _selection_source(
                    selection_sources.get(market, sources[market]),
                    market=market,
                    membership=selection_membership.get(market),
                )
            # Re-read the explicit pointer before any publication: a changed
            # candidate cannot produce a selection artifact for the old input.
            if not a_candidate_missing:
                read_candidate_input(
                    self.config.candidate_acquisition_root,
                    trade_date,
                    expected_current_sha256=candidate.current_sha256,
                )
            if (
                not self.config.injected_test_mode
                and "HK_CONNECT" in universe_bindings
                and "HK_CONNECT" not in exact_input_errors
            ):
                binding = universe_bindings["HK_CONNECT"]
                if binding.status == "READY" and self.config.hk_d1_root is not None:
                    try:
                        fresh = _build_hk_stage_binding(
                            self.config.hk_d1_root,
                            trade_date,
                            preselection_source_root=self.config.preselection_source_root,
                        )
                        if fresh.sha256 != binding.sha256 or fresh.codes != binding.codes:
                            raise RunnerError("HK D1 source SHA changed before publication")
                    except (RunnerError, OSError, ValueError) as error:
                        # Reject this lane's old acquisition, not a valid A
                        # aggregate. No HK raw/selection/latest is published.
                        exact_input_errors["HK_CONNECT"] = str(error)
                        sources["HK_CONNECT"] = replace(
                            sources["HK_CONNECT"], status="CANNOT_CONFIRM", rows=(),
                            cannot_confirm=tuple(dict.fromkeys((*sources["HK_CONNECT"].cannot_confirm, str(error)))),
                        )
                        selection_sources["HK_CONNECT"] = sources["HK_CONNECT"]
            raw_store = RawStore(self.config.raw_root)
            raw_markets: dict[str, dict[str, Any]] = {}
            stage_spec = next(stage for stage in EIGHT_STAGES if stage.stage_id == stage_id)
            # Validate every market's raw projection before touching the
            # store.  A sequential publish must not leave A_SHARE latest
            # behind when HK_CONNECT later violates the 19-field contract.
            projected_rows: dict[str, tuple[dict[str, Any], ...]] = {}
            for market in markets:
                source = sources[market]
                if source.status == "CANNOT_CONFIRM" and not source.rows:
                    continue
                projected_rows[market] = _project_raw_rows(
                    source.rows,
                    trade_date=trade_date,
                    stage_id=stage_id,
                    market=market,
                )
            for market in markets:
                source = sources[market]
                # A zero-row CANNOT_CONFIRM is a receipt-only outcome.  It
                # must never create a raw latest pointer or selection latest
                # entry that looks like a materialized stage.
                if source.status == "CANNOT_CONFIRM" and not source.rows:
                    continue
                window = stage_spec.hk_window if stage_id == "STAGE_0925" and market == "HK_CONNECT" else stage_spec.window
                cutoff_at = "09:20:05" if stage_id == "STAGE_0925" and market == "HK_CONNECT" else stage_spec.cutoff
                if market in existing_raw_verified:
                    raw_markets[market] = dict(existing_raw_verified[market])
                    continue
                _deadline.begin_write("RAW_PUBLISH", market=market, stage_id=stage_id)
                raw_markets[market] = publish_raw_artifact(
                    self.config.raw_root,
                    trade_date=trade_date,
                    stage_id=stage_id,
                    market=market,
                    source_id=source.source_id,
                    source_status=source.status,
                    rows=projected_rows[market],
                    cannot_confirm=source.cannot_confirm,
                    source_evidence=source.source_evidence,
                    requested_rows=source.requested_rows,
                    missing_symbols=source.missing_symbols,
                    window=window,
                    cutoff_at=cutoff_at,
                )
                write_performed = True
                _deadline.end_write("RAW_PUBLISH", market=market, artifact_sha256=raw_markets[market].get("artifact_sha256"))
            raw_bundle: dict[str, Any] = {"markets": raw_markets}
            if not raw_markets:
                raise RunnerError("all market collectors returned zero-row CANNOT_CONFIRM")
            if set(raw_markets) == set(markets):
                try:
                    _deadline.begin_write("BUNDLE_PUBLISH", stage_id=stage_id)
                    raw_bundle.update(raw_store.publish_bundle(trade_date=trade_date, stage_id=stage_id, status=("READY" if all(item["status"] == "READY" for item in raw_markets.values()) else "PARTIAL_WITH_ROWS"), markets=raw_markets))
                    _deadline.end_write("BUNDLE_PUBLISH", stage_id=stage_id)
                except RawStoreError as error:
                    # An immutable raw bundle may have been left absent after
                    # a prior selection-only failure.  Re-read an identical
                    # bundle if the store reports a conflict; any differing
                    # market identity remains fail-closed.
                    if "bundle slot conflict" not in str(error):
                        raise
                    raw_bundle.update(raw_store.read_verified_bundle(trade_date, stage_id))
            published: dict[str, Any] = {}
            selection_store = SelectionStore(self.config.selection_root)
            for market in markets:
                if market not in raw_markets:
                    published[market] = {
                        "market": market,
                        "selection_status": "CANNOT_CONFIRM",
                        "status": "CANNOT_CONFIRM",
                        "selected_rows": 0,
                        "source_status": sources[market].status,
                        "cannot_confirm": list(sources[market].cannot_confirm),
                        "write_performed": False,
                    }
                    continue
                if market in existing_selections:
                    published[market] = dict(existing_selections[market])
                    continue
                builder_raw = dict(raw_bundle["markets"][market])
                # These roots have distinct owners and must remain separate in
                # the exact-date selection context.
                _attach_stage_research_roots(
                    builder_raw,
                    self.config,
                    stage_id,
                    market=market,
                )
                envelope = dict(builders[market](selection_sources[market], plan, builder_raw))
                envelope.setdefault("source_evidence", [])
                envelope["source_evidence"] = list(
                    dict.fromkeys(
                        (
                            *envelope["source_evidence"],
                            *(
                                (
                                    f"candidate_current_sha256={candidate_sha_by_market[market]}",
                                    f"candidate_run_id={candidate_run_id_by_market[market]}",
                                )
                                if candidate_sha_by_market.get(market) is not None
                                else ()
                            ),
                            *exact_evidence_by_market.get(market, ()),
                            *((f"exact_input_error={exact_input_errors[market]}",) if market in exact_input_errors else ()),
                            f"due_status={decision.status}",
                        )
                    )
                )
                envelope["raw_artifact_sha256"] = raw_bundle["markets"][market]["artifact_sha256"]
                _deadline.begin_write("SELECTION_PUBLISH", market=market, stage_id=stage_id)
                published[market] = selection_store.publish(envelope, market=market)
                _deadline.end_write("SELECTION_PUBLISH", market=market, run_id=published[market].get("run_id"))
                write_performed = True
            statuses = {str(item.get("selection_status")) for item in published.values()}
            status = "READY" if statuses == {"READY"} and len(published) == len(markets) else "READY_EMPTY" if statuses == {"READY_EMPTY"} and len(published) == len(markets) else "PARTIAL_WITH_ROWS" if statuses and ("PARTIAL_WITH_ROWS" in statuses or len(published) < len(markets) or "READY" in statuses) else "CANNOT_CONFIRM"
            source_evidence = [f"candidate_current_sha256={candidate.current_sha256}", f"candidate_run_id={candidate.run_id}", *exact_evidence]
            if decision.status in {"LATE_CATCHUP_REPLAY", "HISTORICAL_BACKFILL"}:
                source_evidence.append(decision.status)
            return self._write_receipt({"status": status, "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id, "candidate_current_sha256": candidate.current_sha256, "candidate_run_id": candidate.run_id, "bundle_id": raw_bundle.get("bundle_id"), "markets": published, "source_evidence": list(dict.fromkeys(source_evidence)), "write_performed": True}, trade_date, stage_id)
        except (RunnerError, RawStoreError, SelectionError, CandidateInputError, OSError, ValueError) as error:
            lane_failures = {}
            for market in markets:
                source = sources.get(market)
                reasons = ([exact_input_errors[market]] if market in exact_input_errors
                           else list(source.cannot_confirm) if source else [str(error)])
                lane_failures[market] = {
                    "status": source.status if source else "CANNOT_CONFIRM",
                    "cannot_confirm": reasons, "first_error": reasons[0] if reasons else str(error),
                    "observed_rows": len(source.rows) if source else 0,
                    "requested_rows": source.requested_rows if source else None,
                    "source_evidence": list(source.source_evidence) if source else [],
                }
            return self._write_receipt({
                "status": "PARTIAL_COMMIT_RETRY_REQUIRED" if write_performed else "CANNOT_CONFIRM",
                "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id,
                "candidate_current_sha256": candidate.current_sha256, "error": str(error),
                "first_failed_layer": "EXACT_SELECTION_INPUT_BINDING" if exact_input_errors else "COLLECTION_OR_PUBLICATION",
                "markets": lane_failures, "write_performed": write_performed,
                **_deadline.failure_fields(error),
            }, trade_date, stage_id)

    def tick(
        self,
        trade_date: str,
        evaluated_at: datetime,
        *,
        stage_id: str | None = None,
        historical_backfill: bool = False,
        _skip_precapture: bool = False,
    ) -> dict[str, Any]:
        # Capture once per outer scheduler tick, before due work can spend
        # time in another provider. Recursive stage dispatches reuse it.
        precaptures = (
            []
            if _skip_precapture
            else self._prepare_hk_active_snapshots(
                trade_date,
                evaluated_at,
                stage_id=stage_id,
                historical_backfill=historical_backfill,
            )
        )
        decisions = self.due_decisions(trade_date, evaluated_at, historical_backfill=historical_backfill)
        if stage_id is None:
            due = [decision for decision in decisions if decision.status in {"DUE", "LATE_CATCHUP_REPLAY", "HISTORICAL_BACKFILL"}]
            if not due:
                return {"status": decisions[0].status if decisions else "CANNOT_CONFIRM", "trade_date": trade_date, "stages": [decision.status for decision in decisions], "pre_captures": precaptures, **SAFETY_FLAGS}
            results = [
                self.tick(
                    trade_date,
                    evaluated_at,
                    stage_id=decision.stage_id,
                    historical_backfill=historical_backfill,
                    _skip_precapture=True,
                )
                for decision in due
            ]
            return {"status": "TICK_COMPLETE", "trade_date": trade_date, "stages": results, "pre_captures": precaptures, **SAFETY_FLAGS}
        decision = next((item for item in decisions if item.stage_id == stage_id), None)
        if decision is None:
            decision = evaluate_due(stage_id, trade_date, evaluated_at, historical_backfill=historical_backfill)
        if decision.status not in {"DUE", "LATE_CATCHUP_REPLAY", "HISTORICAL_BACKFILL"}:
            if historical_backfill:
                scoped = self._backfill_runner(uuid4().hex)
                return scoped._write_receipt(
                    {
                        "status": decision.status,
                        "due_status": decision.status,
                        "trade_date": trade_date,
                        "stage_id": stage_id,
                        "write_performed": False,
                    },
                    trade_date,
                    stage_id,
                )
            return self._write_receipt({"status": decision.status, "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id, "pre_captures": precaptures, "write_performed": False}, trade_date, stage_id)
        runner = self
        backfill_run_id: str | None = None
        if historical_backfill:
            backfill_run_id = uuid4().hex
            runner = self._backfill_runner(backfill_run_id)
        lock = SlotLock(_slot_lock_path(runner.config, trade_date, stage_id))
        if not lock.acquire():
            return runner._write_receipt({"status": "SKIPPED_SLOT_LOCKED", "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id, "write_performed": False}, trade_date, stage_id)
        try:
            return runner._run_one(
                decision,
                historical_backfill=historical_backfill,
                backfill_run_id=backfill_run_id,
            )
        finally:
                lock.release()

    def run_one_for_supervisor(self, decision: DueDecision) -> dict[str, Any]:
        """Expose the existing one-stage path to a parent-supervised child.

        This is intentionally a thin delegation: the child uses the same
        collector, exact HK D-1 resolver/source-read lease, private-root
        stores, and safety checks as the ordinary StageCenterRunner path.
        Process supervision and visibility publication stay in the parent.
        """
        if not isinstance(decision, DueDecision):
            raise RunnerError("supervised Stage decision is invalid")
        if decision.status not in {"DUE", "LATE_CATCHUP_REPLAY"}:
            raise RunnerError("supervised Stage decision is not due")
        return self._run_one(decision)


__all__ = ["RunnerConfig", "RunnerError", "SlotLock", "StageCenterRunner", "build_production_config"]
