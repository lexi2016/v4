"""Pure due-slot and catch-up resolution for the V3.5 macOS scheduler."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from .run_scheduled_slot import ALL_SLOTS, SHANGHAI
except ImportError:  # pragma: no cover - direct script imports
    from run_scheduled_slot import ALL_SLOTS, SHANGHAI

CATCHUP_HOURLY_SLOTS = tuple(f"{hour:02d}00" for hour in range(7, 24))
# Research-panel A/H lanes are fixed canonical producer slots.  They receive
# the same fairness treatment as hourly work; executor-level dependencies are
# evaluated only after a slot is selected.
CATCHUP_EXACT_PRIORITY_SLOTS = frozenset(CATCHUP_HOURLY_SLOTS) | frozenset({"1530", "1700", "1720"})
# Fixed non-hourly owners must be recoverable after a five-minute launchd
# heartbeat without being confused with the neighbouring hourly workload.
# Morning stage/pre-stage slots are listed explicitly because a retryable
# 09:01 receipt must not monopolize the dispatcher after launchd wakes late.
# The post-close owners remain in ``POST_CLOSE_CATCHUP_SLOTS``; the dedicated
# branch below only orders due work fairly and leaves business dependencies to
# each executor's existing gate.
CATCHUP_FIXED_SLOTS = (
    "0415",
    "0515",
    "0830",
    "0840",
    "0901",
    "0915",
    "0925",
    "0935",
    "0940",
    "0945",
    "1030",
    "1730",
    "2001",
    "2115",
)
POST_CLOSE_CATCHUP_SLOTS = (
    "1500", "1530", "1555", "1605", "1608", "1700", "1710", "1720", "1730", "1800", "2030", "2040",
    "2050", "2105", "2108", "2110", "2115", "2140",
)
# The post-close nodes remain the fixed candidate order used for tie-breaking.
# 21:40 remains the final same-day materializer slot in this sequence.
CRITICAL_SAME_DAY_SLOT = "2140"
CRITICAL_SAME_DAY_CATCHUP_END_HOUR = 23
DEFAULT_CATCHUP_WINDOW_MINUTES = 59
FAILED_SLOT_RETRY_BACKOFF_SECONDS = 300
MAX_FAILED_SLOT_ATTEMPTS = 3
RETRYABLE_FAILURE_CLASSES = frozenset(
    {"UPSTREAM_NOT_READY", "NETWORK", "EXTERNAL_SOURCE", "RESEARCH_SOURCE_REFRESH_RETRY_REQUIRED"}
)
TERMINAL_FAILURE_CLASSES = frozenset(
    {"CONTRACT", "INVALID_INPUT", "SAFETY", "NON_TRADING_DAY", "NOT_DUE"}
)

def _fixed_slot_catchup_allowed(slot: str, moment: datetime) -> bool:
    """Apply slot-specific catch-up deadlines to non-hourly owners.

    The 09:15 HK auction capture is an opening-window input.  A late wake can
    recover it only while the capture window is still open; after 09:19:59 a
    retry of that slot would be a false representation of the live auction.
    Other fixed slots retain the caller's normal bounded catch-up window.
    """

    if slot != "0915":
        return True
    return moment.hour == 9 and moment.minute <= 19

def current_slot(now: datetime | None = None) -> tuple[str, str]:
    moment = now or datetime.now(SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    else:
        moment = moment.astimezone(SHANGHAI)
    return moment.strftime("%Y%m%d"), moment.strftime("%H%M")


def _slot_blocks_retry(
    ledger_root: Path,
    business_date: str,
    slot: str,
    *,
    moment: datetime,
    retry_backoff_seconds: int = FAILED_SLOT_RETRY_BACKOFF_SECONDS,
    max_failed_attempts: int = MAX_FAILED_SLOT_ATTEMPTS,
    upstream_fingerprint: str | None = None,
    release_id: str | None = None,
) -> bool:
    claim = (
        ledger_root
        / "claims"
        / "live"
        / business_date
        / slot
        / "dispatch.claim.json"
    )
    if claim.is_file():
        return True
    receipts = ledger_root / "receipts" / "live" / business_date / slot
    if not receipts.is_dir():
        return False
    observed: list[dict[str, Any]] = []
    for path in receipts.glob("*.dispatch-receipt.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return True
        if not isinstance(payload, dict):
            return True
        observed.append(payload)
    if not observed:
        return False
    identity_requested = upstream_fingerprint is not None or release_id is not None
    if identity_requested:
        def matches_current_identity(payload: dict[str, Any]) -> bool:
            return (
                (upstream_fingerprint is None
                 or str(payload.get("upstream_fingerprint") or "") == upstream_fingerprint)
                and (release_id is None
                     or str(payload.get("release_id") or "") == release_id)
            )

        current_observed = [
            payload for payload in observed if matches_current_identity(payload)
        ]
        # Historical receipts from another release/upstream are provenance,
        # not attempts for this identity.  A new identity gets one fresh try;
        # once its own receipt exists, its backoff and failure cap apply.
        if not current_observed:
            return False
        observed = current_observed
    if any(str(payload.get("status") or "") != "FAILED" for payload in observed):
        return True
    failure_classes = {str(payload.get("failure_class") or "").upper() for payload in observed}
    if failure_classes & TERMINAL_FAILURE_CLASSES:
        return True
    legacy_receipts = [payload for payload in observed if not str(payload.get("failure_class") or "").strip()]
    typed_classes = failure_classes - {""}
    if typed_classes and not typed_classes.issubset(RETRYABLE_FAILURE_CLASSES):
        # Unknown failure types stay fail-closed until the executor classifies
        # them; they must not be retried blindly by the minute launcher.
        return True
    if legacy_receipts and len(legacy_receipts) >= max(0, int(max_failed_attempts)):
        # Receipts emitted before typed failure metadata existed retain the
        # historical bounded-attempt contract.  A current release or exact
        # upstream fingerprint was handled above and intentionally resets this
        # compatibility cap without rewriting the old receipts.
        return True
    # Retryable upstream/network failures are governed by time backoff, not a
    # permanent attempt ceiling.  ``max_failed_attempts`` remains accepted for
    # compatibility with older callers but is intentionally not used to turn
    # a recoverable input outage into a terminal receipt.
    finished: list[datetime] = []
    retry_after: list[datetime] = []
    for payload in observed:
        retry_value = str(payload.get("retry_after") or "")
        if retry_value:
            try:
                parsed_retry = datetime.fromisoformat(retry_value.replace("Z", "+00:00"))
            except ValueError:
                return True
            if parsed_retry.tzinfo is None or parsed_retry.utcoffset() is None:
                return True
            retry_after.append(parsed_retry.astimezone(UTC))
            continue
        raw = str(payload.get("finished_at") or "")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return True
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return True
        finished.append(parsed.astimezone(UTC))
    current = moment.astimezone(UTC)
    if retry_after:
        return current < max(retry_after)
    return current - max(finished) < timedelta(
        seconds=max(0, int(retry_backoff_seconds))
    )


def _slot_has_retryable_failure(
    ledger_root: Path,
    business_date: str,
    slot: str,
    *,
    upstream_fingerprint: str | None = None,
    release_id: str | None = None,
) -> bool:
    """Return whether a slot has a retryable failure for this identity."""

    receipts = Path(ledger_root) / "receipts" / "live" / business_date / slot
    if not receipts.is_dir():
        return False
    for path in receipts.glob("*.dispatch-receipt.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or str(payload.get("status") or "") != "FAILED":
            continue
        if upstream_fingerprint is not None and str(
            payload.get("upstream_fingerprint") or ""
        ) != upstream_fingerprint:
            continue
        if release_id is not None and str(payload.get("release_id") or "") != release_id:
            continue
        if str(payload.get("failure_class") or "").upper() in RETRYABLE_FAILURE_CLASSES:
            return True
    return False


def resolve_due_slot(
    *,
    ledger_root: Path,
    now: datetime | None = None,
    catchup_window_minutes: int = DEFAULT_CATCHUP_WINDOW_MINUTES,
    upstream_fingerprint: str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Resolve an exact slot or the earliest bounded unclaimed catch-up.

    Only the most recent hour and only a bounded sub-hour window are eligible.
    Claims and successful receipts block duplicates. Failed hourly receipts are
    eligible for a bounded, backoff-controlled retry so a temporary network
    outage can recover after wake. Special stage and pool slots are never
    synthesized.
    """
    moment = now or datetime.now(SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    else:
        moment = moment.astimezone(SHANGHAI)
    business_date = moment.strftime("%Y%m%d")
    observed_slot = moment.strftime("%H%M")
    exact = {
        "business_date": business_date,
        "observed_slot": observed_slot,
        "slot": observed_slot,
        "catchup": False,
        "lag_minutes": 0,
    }
    # Do not let an older post-close retry monopolize the dispatcher at an
    # exact hourly wake.  The current hourly workload is independent of the
    # prior close node and must get one attempt; the ordered post-close list
    # remains eligible on the next five-minute wake.  This prevents a failed
    # 15:00 receipt from starving 16:00/17:00 research indefinitely while
    # preserving each executor's existing dependency gate for fixed evidence.
    if observed_slot in CATCHUP_EXACT_PRIORITY_SLOTS and not _slot_blocks_retry(
        Path(ledger_root),
        business_date,
        observed_slot,
        moment=moment,
        upstream_fingerprint=upstream_fingerprint,
        release_id=release_id,
    ):
        return exact
    window = max(0, int(catchup_window_minutes))
    if 15 <= int(observed_slot[:2]) <= CRITICAL_SAME_DAY_CATCHUP_END_HOUR:
        current_hour_slot = f"{int(observed_slot[:2]):02d}00"
        current_hour_scheduled = moment.replace(
            hour=int(observed_slot[:2]),
            minute=0,
            second=0,
            microsecond=0,
        )
        current_hour_lag = int(
            (moment - current_hour_scheduled).total_seconds() // 60
        )
        if (
            current_hour_slot in CATCHUP_HOURLY_SLOTS
            and 0 <= current_hour_lag <= window
            and not _slot_blocks_retry(
                Path(ledger_root),
                business_date,
                current_hour_slot,
                moment=moment,
                upstream_fingerprint=upstream_fingerprint,
                release_id=release_id,
            )
            and any(
                slot < current_hour_slot
                and _slot_has_retryable_failure(
                    Path(ledger_root),
                    business_date,
                    slot,
                    upstream_fingerprint=upstream_fingerprint,
                    release_id=release_id,
                )
                for slot in POST_CLOSE_CATCHUP_SLOTS
            )
        ):
            return {
                "business_date": business_date,
                "observed_slot": observed_slot,
                "slot": current_hour_slot,
                "catchup": True,
                "lag_minutes": current_hour_lag,
            }
        def _attempted(slot: str) -> bool:
            claim = (
                Path(ledger_root)
                / "claims"
                / "live"
                / business_date
                / slot
                / "dispatch.claim.json"
            )
            if claim.is_file():
                return True
            receipts = Path(ledger_root) / "receipts" / "live" / business_date / slot
            if not receipts.is_dir():
                return False
            identity_requested = upstream_fingerprint is not None or release_id is not None
            for path in receipts.glob("*.dispatch-receipt.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    return True
                if not isinstance(payload, dict):
                    return True
                if identity_requested and (
                    (
                        upstream_fingerprint is not None
                        and str(payload.get("upstream_fingerprint") or "")
                        != upstream_fingerprint
                    )
                    or (
                        release_id is not None
                        and str(payload.get("release_id") or "") != release_id
                    )
                ):
                    continue
                return True
            return False

        def _last_attempt(slot: str) -> datetime:
            receipts = Path(ledger_root) / "receipts" / "live" / business_date / slot
            latest = datetime.min.replace(tzinfo=UTC)
            if not receipts.is_dir():
                return latest
            identity_requested = upstream_fingerprint is not None or release_id is not None
            for path in receipts.glob("*.dispatch-receipt.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                if identity_requested and (
                    (
                        upstream_fingerprint is not None
                        and str(payload.get("upstream_fingerprint") or "")
                        != upstream_fingerprint
                    )
                    or (
                        release_id is not None
                        and str(payload.get("release_id") or "") != release_id
                    )
                ):
                    continue
                for field in ("finished_at", "started_at", "created_at"):
                    value = str(payload.get(field) or "")
                    if not value:
                        continue
                    try:
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if parsed.tzinfo is None or parsed.utcoffset() is None:
                        continue
                    latest = max(latest, parsed.astimezone(UTC))
                    break
            return latest

        untried_candidates: list[tuple[int, str, int]] = []
        retry_candidates: list[tuple[datetime, int, str, int]] = []
        for index, slot in enumerate(POST_CLOSE_CATCHUP_SLOTS):
            if observed_slot < slot:
                continue
            scheduled = moment.replace(
                hour=int(slot[:2]), minute=int(slot[2:]), second=0, microsecond=0
            )
            lag_minutes = int((moment - scheduled).total_seconds() // 60)
            if _slot_blocks_retry(
                Path(ledger_root),
                business_date,
                slot,
                moment=moment,
                upstream_fingerprint=upstream_fingerprint,
                release_id=release_id,
            ):
                continue
            # An untried due slot always wins over a retry, regardless of
            # whether it is hourly or fixed.  The original post-close list is
            # the only tie-breaker for never-attempted work; hourly work still
            # retains the current-hour branch above and the fallback scan
            # below when no untried candidate is available.
            attempted = _attempted(slot)
            if not attempted:
                untried_candidates.append((index, slot, lag_minutes))
            elif attempted:
                retry_candidates.append(
                    (_last_attempt(slot), index, slot, lag_minutes)
                )
        if untried_candidates:
            _, slot, lag_minutes = min(untried_candidates, key=lambda candidate: candidate[0])
            if slot == observed_slot:
                return exact
            return {
                "business_date": business_date,
                "observed_slot": observed_slot,
                "slot": slot,
                "catchup": True,
                "lag_minutes": lag_minutes,
            }
        if retry_candidates:
            _, _, slot, lag_minutes = min(
                retry_candidates, key=lambda candidate: (candidate[0], candidate[1])
            )
            if slot == observed_slot:
                return exact
            return {
                "business_date": business_date,
                "observed_slot": observed_slot,
                "slot": slot,
                "catchup": True,
                "lag_minutes": lag_minutes,
            }
        for slot in POST_CLOSE_CATCHUP_SLOTS:
            if observed_slot < slot:
                continue
            if _slot_blocks_retry(
                Path(ledger_root),
                business_date,
                slot,
                moment=moment,
                upstream_fingerprint=upstream_fingerprint,
                release_id=release_id,
            ):
                continue
            scheduled = moment.replace(
                hour=int(slot[:2]), minute=int(slot[2:]), second=0, microsecond=0
            )
            if slot == observed_slot:
                return exact
            return {
                "business_date": business_date,
                "observed_slot": observed_slot,
                "slot": slot,
                "catchup": True,
                "lag_minutes": int((moment - scheduled).total_seconds() // 60),
            }
    if observed_slot in ALL_SLOTS:
        if _slot_blocks_retry(
            Path(ledger_root),
            business_date,
            observed_slot,
            moment=moment,
            upstream_fingerprint=upstream_fingerprint,
            release_id=release_id,
        ):
            return {
                **exact,
                "slot": None,
                "status": "RETRY_BACKOFF",
                "retry_blocked": True,
            }
        return exact
    for slot in reversed(CATCHUP_FIXED_SLOTS):
        if not _fixed_slot_catchup_allowed(slot, moment):
            continue
        scheduled = moment.replace(
            hour=int(slot[:2]),
            minute=int(slot[2:]),
            second=0,
            microsecond=0,
        )
        lag_minutes = int((moment - scheduled).total_seconds() // 60)
        if lag_minutes < 0 or lag_minutes > window:
            continue
        if _slot_blocks_retry(
            Path(ledger_root),
            business_date,
            slot,
            moment=moment,
            upstream_fingerprint=upstream_fingerprint,
            release_id=release_id,
        ):
            continue
        return {
            "business_date": business_date,
            "observed_slot": observed_slot,
            "slot": slot,
            "catchup": True,
            "lag_minutes": lag_minutes,
        }
    for slot in reversed(CATCHUP_HOURLY_SLOTS):
        scheduled = moment.replace(
            hour=int(slot[:2]),
            minute=0,
            second=0,
            microsecond=0,
        )
        lag_minutes = int((moment - scheduled).total_seconds() // 60)
        if lag_minutes < 0 or lag_minutes > window:
            continue
        if _slot_blocks_retry(
            Path(ledger_root),
            business_date,
            slot,
            moment=moment,
            upstream_fingerprint=upstream_fingerprint,
            release_id=release_id,
        ):
            continue
        return {
            "business_date": business_date,
            "observed_slot": observed_slot,
            "slot": slot,
            "catchup": True,
            "lag_minutes": lag_minutes,
        }
    return exact
