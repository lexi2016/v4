"""stage_center.selection: artifact_codec (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __artifact_rows_body(_v4_scope, /, rows, *, fields):
    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                field: _v4_global(_v4_scope, 'json').dumps(row.get(field), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if field == "lane_evidence"
                else ("" if row.get(field) is None else row.get(field))
                for field in fields
            }
        )
    return output


def __decode_artifact_rows_body(_v4_scope, /, rows, *, fields):
    output: list[dict[str, Any]] = []
    for raw in rows:
        row = _v4_global(_v4_scope, 'dict')(raw)
        if fields is None:
            raw_fields = _v4_global(_v4_scope, 'tuple')(row)
            if _v4_global(_v4_scope, 'set')(raw_fields) == _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V1')):
                fields = _v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V1')
            elif _v4_global(_v4_scope, 'set')(raw_fields) == _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V2')):
                fields = _v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V2')
            else:
                raise _v4_global(_v4_scope, 'SelectionError')("selection artifact fields mismatch")
        if _v4_global(_v4_scope, 'set')(row) != _v4_global(_v4_scope, 'set')(fields):
            raise _v4_global(_v4_scope, 'SelectionError')("selection artifact fields mismatch")
        if row.get("lane_evidence"):
            try:
                row["lane_evidence"] = _v4_global(_v4_scope, 'json').loads(row["lane_evidence"])
            except _v4_global(_v4_scope, 'ValueError') as error:
                raise _v4_global(_v4_scope, 'SelectionError')("selection lane evidence is invalid") from error
        else:
            row["lane_evidence"] = []
        for field in ("rank",):
            if field in row and row[field] != "":
                row[field] = _v4_global(_v4_scope, 'int')(row[field])
        for field in ("score", "support", "pressure", "invalidation", "current_change_pct", "open_price", "last_price", "high_price", "low_price", "support_primary_price", "pressure_price", "invalidation_price"):
            if field in row and row[field] != "":
                row[field] = _v4_global(_v4_scope, 'float')(row[field])
            elif field in row:
                row[field] = None
        row["formal_eligible"] = _v4_global(_v4_scope, 'str')(row.get("formal_eligible", "")).lower() in {"true", "1", "yes"}
        for field in _v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V2'):
            if field not in row:
                row[field] = None
        row["lane_evidence"] = _v4_global(_v4_scope, 'list')(row.get("lane_evidence") or ())
        output.append(row)
    return output
