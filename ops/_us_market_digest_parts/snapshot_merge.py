"""ops.us_market_digest: snapshot_merge (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __merge_market_snapshots_body(_v4_scope, /, existing, incoming):
    """Keep the newest scheduled quote snapshot in one exact-date artifact."""
    if existing is None and incoming is None:
        return None
    if existing is None:
        return _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(incoming)) if incoming is not None else None
    if incoming is None:
        return _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(existing))
    existing_time = _v4_global(_v4_scope, '_snapshot_timestamp')(existing)
    incoming_time = _v4_global(_v4_scope, '_snapshot_timestamp')(incoming)
    existing_valid = existing.get("status") in {"READY", "PARTIAL"}
    incoming_valid = incoming.get("status") in {"READY", "PARTIAL"}
    if existing_valid != incoming_valid:
        winner = existing if existing_valid else incoming
    elif existing_time is None and incoming_time is None:
        winner = incoming
    elif existing_time is None:
        winner = incoming
    elif incoming_time is None:
        winner = existing
    else:
        winner = incoming if incoming_time >= existing_time else existing
    merged = _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(winner))
    # Metadata belongs to the same winning observation as quotes/rows/SHA.
    # Unioning timestamps from discarded quotes creates an invalid READY
    # snapshot after close normalization. Prior observations remain in the
    # owner's capture list and CAS history, not this winning quote identity.
    return merged
