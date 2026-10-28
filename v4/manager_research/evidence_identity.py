"""Canonical identity and provenance merge for already-owned research evidence.

The helper is deliberately I/O free.  It prevents the same source event from
appearing as several rows merely because multiple Manager cards referenced it,
while retaining every source reference and acquisition trace for audit.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import re
from typing import Any, Iterable, Mapping

from .workspace_projection import canonical_url, digest, timestamp

_SPACE=re.compile(r"\s+")
_ACQUISITION_FIELDS=("first_seen_at","collected_at","retrieved_at","available_at","archive_recorded_at")
_OWNER_ACQUISITION_FIELDS=frozenset({"first_seen_at","collected_at","retrieved_at","available_at"})


def acquisition_timestamps(row: Mapping[str, Any]) -> list[tuple[str, datetime]] | None:
    """Return every persisted acquisition clock, or None for a malformed value.

    Distinct owner clocks must not be collapsed before cutoff validation.
    """
    values=[]
    for key in _ACQUISITION_FIELDS:
        raw=row.get(key)
        if raw is None or raw=="":
            continue
        parsed=timestamp(raw)
        if parsed is None:
            return None
        values.append((key,parsed))
    return values


def acquisition_is_within_window(row: Mapping[str, Any], start: datetime | None, cutoff: datetime | None) -> bool:
    values=acquisition_timestamps(row)
    if values is None or start is None or cutoff is None:
        return False
    if not any(key in _OWNER_ACQUISITION_FIELDS for key,_ in values):
        return False
    return all(start<=value<=cutoff for _,value in values)


def acquired_at(row: Mapping[str, Any]) -> str | None:
    """Prefer the owner's first-seen clock; fall back to later capture fields.

    These fields describe different stages, so the function never synthesizes
    one timestamp by taking the minimum across them.
    """
    values=acquisition_timestamps(row)
    if values is None:
        return None
    by_key=dict(values)
    for key in _ACQUISITION_FIELDS:
        if key in by_key:
            return by_key[key].isoformat()
    return None


def _text(value: Any) -> str:
    return _SPACE.sub(" ",str(value or "").strip()).casefold()


def _assertion(row: Mapping[str, Any]) -> str:
    propositions=row.get("propositions")
    if isinstance(propositions,list):
        quotes=[_text(item.get("quote")) for item in propositions if isinstance(item,Mapping) and item.get("quote")]
        if quotes:return "|".join(sorted(set(quotes)))
    for key in ("source_excerpt","evidence_quote","relation_quote","issuer_quote","title"):
        if row.get(key):return _text(row.get(key))
    return ""


def event_identity(symbol: str, row: Mapping[str, Any]) -> str:
    raw_url=row.get("source_url") or row.get("url")
    source_url=canonical_url(raw_url) or _SPACE.sub(" ",str(raw_url or "").strip())
    published=timestamp(row.get("published_at"))
    published_text=published.isoformat() if published is not None else ""
    assertion=_assertion(row)
    if source_url or published_text or assertion:
        return digest([symbol,source_url,published_text,assertion])
    fallback=str(row.get("original_article_id") or row.get("event_id") or row.get("evidence_id") or row.get("card_id") or row.get("material_id") or "")
    return digest([symbol,"FALLBACK",fallback])


def _merge_source_refs(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique={}
    for row in rows:
        for ref in row.get("source_refs") or []:
            if not isinstance(ref,Mapping):continue
            key=json.dumps(dict(ref),ensure_ascii=False,sort_keys=True,separators=(",",":"))
            unique.setdefault(key,deepcopy(dict(ref)))
    return [unique[key] for key in sorted(unique)]


def merge_event_rows(symbol: str, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str,list[Mapping[str,Any]]]={}
    order=[]
    for row in rows:
        identity=event_identity(symbol,row)
        if identity not in groups:order.append(identity);groups[identity]=[]
        groups[identity].append(row)
    result=[]
    for identity in order:
        values=groups[identity]
        base=deepcopy(dict(values[0]))
        base["canonical_event_id"]=identity
        base["source_refs"]=_merge_source_refs(values)
        traces=[]
        for value in values:
            traces.append({
                "event_id":value.get("event_id"),"evidence_id":value.get("evidence_id"),
                "card_id":value.get("card_id"),"material_id":value.get("material_id"),
                "available_at":value.get("available_at"),"retrieved_at":value.get("retrieved_at"),
                "first_seen_at":value.get("first_seen_at"),"collected_at":value.get("collected_at"),
                "source_refs":deepcopy(list(value.get("source_refs") or [])),
            })
        base["merged_provenance"]=traces
        base["provenance_count"]=len(values)
        base["acquired_at"]=min((value for value in (acquired_at(row) for row in values) if value),default=None)
        result.append(base)
    return result


__all__=["acquired_at","acquisition_is_within_window","acquisition_timestamps","event_identity","merge_event_rows"]
