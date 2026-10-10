"""Semantic identity for already verified workspace inputs; no owner reads.

Only the global registry fingerprint of a complete V3.5 research binding is
provenance. All other binding fields and all original source_row content remain
semantic. This does not admit or verify an artifact: original readers still do.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping

INPUT_IDENTITY_SCHEMA = 'v4.manager_research.input_identity.v2'
_SHA = re.compile(r'[0-9a-f]{64}')


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _registry_binding(value: Mapping[str, Any]) -> bool:
    """Recognize only the exact read-only research-owner binding contract."""
    if (value.get('source_id') != 'V35_RESEARCH_DATA_ROOT'
            or value.get('status') != 'VERIFIED'
            or value.get('manifest_path') != 'manifest.json'
            or value.get('write_policy') != 'read_only'
            or value.get('recommendation_status') != 'RESEARCH_ONLY'
            or any(value.get(key) is not False for key in
                   ('production_allowed', 'buy_gate_updated', 'orders_sent'))
            or not all(_SHA.fullmatch(str(value.get(key, ''))) for key in
                       ('payload_sha256', 'receipt_sha256', 'manifest_sha256'))):
        return False
    root = PurePosixPath(str(value.get('source_root', '')))
    date = str(value.get('source_date', ''))
    slot, mode = value.get('slot'), value.get('mode')
    if (not root.is_absolute() or '..' in root.parts or not re.fullmatch(r'\d{8}', date)
            or mode not in {'LIVE', 'REPLAY', 'BACKFILL'} or not isinstance(slot, str)):
        return False
    try:
        datetime.strptime(date, '%Y%m%d')
    except ValueError:
        return False
    if slot and (not re.fullmatch(r'\d{4}', slot) or int(slot[:2]) > 23 or int(slot[2:]) > 59):
        return False
    payload = (f'research/hourly/{mode.lower()}/{date}/{slot}.json' if slot
               else f'research/archives/{date}.json')
    return (value.get('payload_path') == payload
            and value.get('receipt_path') == 'receipts/' + payload
            and value.get('manifest_entry_sha256', value['payload_sha256']) == value['payload_sha256'])


def semantic_value(value: Any, *, binding: bool = False) -> Any:
    if isinstance(value, Mapping):
        registry = binding and _registry_binding(value)
        return {key: (deepcopy(child) if key in {'source_row', 'original_source_row', 'content'}
                      else semantic_value(child, binding=key in {'source_refs', 'input_bindings'}))
                for key, child in value.items()
                if not (registry and key == 'manifest_sha256')}
    if isinstance(value, (list, tuple)):
        return [semantic_value(child, binding=binding) for child in value]
    return value


def semantic_digest(value: Any) -> str:
    return _digest(semantic_value(value))


def _source_refs(value: Any) -> list[dict]:
    refs: dict[str, dict] = {}
    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            if _registry_binding(node):
                refs[_digest(node)] = deepcopy(dict(node))
            for key, child in node.items():
                if key in {'source_row', 'original_source_row', 'content'}:
                    continue
                if key == 'source_refs' and isinstance(child, (list, tuple)):
                    for ref in child:
                        if isinstance(ref, Mapping):
                            refs[_digest(ref)] = deepcopy(dict(ref))
                else:
                    visit(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                visit(child)
    visit(value)
    return [refs[key] for key in sorted(refs)]


def identity_component(value: Any, *, sources: list[dict] | None = None) -> dict:
    return dict(sha256=semantic_digest(value),
                sources=deepcopy(sources) if sources is not None else _source_refs(value))


def identity_components_valid(value: Mapping[str, Any]) -> bool:
    components = value.get('input_identity_components')
    return bool(value.get('input_identity_schema') == INPUT_IDENTITY_SCHEMA
        and isinstance(components, Mapping) and components
        and all(isinstance(key, str) and key and isinstance(component, Mapping)
            and _SHA.fullmatch(str(component.get('sha256', '')))
            and isinstance(component.get('sources'), list)
            and all(isinstance(ref, Mapping) for ref in component['sources'])
            for key, component in components.items()))


def input_identity_diagnostics(saved: Mapping[str, Any] | None, current: Mapping[str, Any],
                               *, after_cutoff: bool = False) -> dict:
    """Compare sealed saved components with this read; never rewrite identities."""
    saved = saved if isinstance(saved, Mapping) else {}
    result = dict(schema_version='v4.manager_research.input_identity_diagnostics.v1',
        input_identity_schema=INPUT_IDENTITY_SCHEMA, status='CANNOT_CONFIRM',
        saved_input_identity=saved.get('input_identity'),
        current_input_identity=current.get('input_identity'), changed_components=[])
    changes = result['changed_components']
    for key in ('date_bindings', 'semantic_version'):
        if saved.get(key) != current.get(key):
            changes.append(dict(component=key, saved_value=deepcopy(saved.get(key)),
                current_value=deepcopy(current.get(key)),
                saved_sha256=_digest(saved.get(key)), current_sha256=_digest(current.get(key)),
                saved_sources=[], current_sources=[]))
    if after_cutoff:
        before = saved.get('plan_context', {}).get('research_cutoff')
        after = current.get('plan_context', {}).get('research_cutoff')
        changes.append(dict(component='research_cutoff', saved_value=before, current_value=after,
            saved_sha256=_digest(before), current_sha256=_digest(after), saved_sources=[], current_sources=[]))
    if not identity_components_valid(saved):
        result['reason'] = 'SAVED_IDENTITY_COMPONENTS_UNAVAILABLE_OWNER_REFRESH_REQUIRED'
        return result
    if not identity_components_valid(current):
        result['reason'] = 'CURRENT_IDENTITY_COMPONENTS_UNAVAILABLE'
        return result
    before, after = saved['input_identity_components'], current['input_identity_components']
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key, {}), after.get(key, {})
        if old.get('sha256') != new.get('sha256'):
            changes.append(dict(component=key, saved_sha256=old.get('sha256'),
                current_sha256=new.get('sha256'), saved_sources=deepcopy(old.get('sources', [])),
                current_sources=deepcopy(new.get('sources', []))))
    if changes:
        result['status'] = 'CHANGED'
    elif saved.get('input_identity') != current.get('input_identity'):
        result['reason'] = 'IDENTITY_CHANGED_WITHOUT_DIAGNOSTIC_COMPONENT'
    else:
        result['status'] = 'MATCH'
    return result
