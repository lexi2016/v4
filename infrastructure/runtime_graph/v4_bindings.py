"""Separate live binding snapshot interface for the static V4 graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any


LIVE_BINDING_SCHEMA = "v35.runtime_graph.live_binding.v1"
SAFETY = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def empty_live_binding_snapshot(*, reason: str = "LIVE_BINDING_NOT_COLLECTED") -> dict[str, Any]:
    """Return an honest no-claim snapshot when launchd/state evidence is absent."""

    return {
        "schema": LIVE_BINDING_SCHEMA,
        "status": "CANNOT_CONFIRM",
        "reason": reason,
        "binding": {},
        "source": {"release": None, "plist": None, "process": None, "state_root": None},
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def collect_live_binding_snapshot(*, release: Path | None = None, plist: Path | None = None, state_root: Path | None = None) -> dict[str, Any]:
    """Expose a future collector seam without claiming live deployment.

    This batch intentionally does not read launchctl or mutate runtime state.
    Callers must provide an independently collected binding later; until then
    the graph remains ``CANNOT_CONFIRM``.
    """

    if release is None or plist is None or state_root is None:
        return empty_live_binding_snapshot()
    return {
        **empty_live_binding_snapshot(reason="LIVE_BINDING_COLLECTOR_REQUIRES_VERIFIED_PROBES"),
        "source": {"release": str(release), "plist": str(plist), "process": None, "state_root": str(state_root)},
    }


__all__ = ["LIVE_BINDING_SCHEMA", "collect_live_binding_snapshot", "empty_live_binding_snapshot"]
