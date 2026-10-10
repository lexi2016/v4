"""Semantic copies of already owner-verified research artifact references.

This module does not verify files or authorize material admission. Original
owner readers remain mandatory. Its only normalization is the registry-wide
manifest fingerprint in a complete, verified research binding; every other
field remains part of semantic identity. Raw rows and content are opaque.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import PurePosixPath
import re
from typing import Any, Mapping


_SHA256 = re.compile(r'[0-9a-f]{64}')
_REFERENCE_FIELDS = frozenset({'source_refs', 'input_bindings'})
_CONTENT_FIELDS = frozenset({'source_row', 'original_source_row', 'content', 'body', 'text', 'raw'})
IDENTITY_VERSION = 'CONSUMED_RESEARCH_ARTIFACTS_V1'
COMPONENT_SCHEMA = 'v4.manager_research.input_identity_components.v1'
_DIAGNOSTIC_SCHEMA = 'v4.manager_research.input_identity_diagnostics.v1'
_COMPONENT_NAME = re.compile(r'[a-z][a-z0-9_.]{0,63}')
MAX_COMPONENTS = 32
MAX_CHANGED_COMPONENTS = 16


def _complete_research_binding(value: Mapping[str, Any]) -> bool:
    """Recognize the exact ResearchLaneSource binding after owner validation.

    The original binding's payload_sha256 is the manifest entry for its exact
    payload_path. An explicitly supplied entry digest must agree. Unknown or
    incomplete shapes deliberately keep the registry fingerprint sensitive.
    """
    if (value.get('source_id') != 'V35_RESEARCH_DATA_ROOT'
            or value.get('status') != 'VERIFIED'
            or value.get('write_policy') != 'read_only'
            or value.get('recommendation_status') != 'RESEARCH_ONLY'
            or ('RESEARCH_ONLY' in value and value['RESEARCH_ONLY'] is not True)
            or any(value.get(key) is not False for key in
                   ('production_allowed', 'buy_gate_updated', 'orders_sent'))
            or value.get('manifest_path') != 'manifest.json'):
        return False
    root = value.get('source_root')
    if not isinstance(root, str) or not root or not PurePosixPath(root).is_absolute() or '..' in PurePosixPath(root).parts:
        return False
    source_date = value.get('source_date')
    if not isinstance(source_date, str) or not re.fullmatch(r'[0-9]{8}', source_date):
        return False
    try:
        datetime.strptime(source_date, '%Y%m%d')
    except ValueError:
        return False
    mode, slot = value.get('mode'), value.get('slot')
    if not isinstance(mode, str) or mode not in {'LIVE', 'REPLAY', 'BACKFILL'} or not isinstance(slot, str):
        return False
    if slot:
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3])[0-5][0-9]', slot):
            return False
        payload_path = f'research/hourly/{mode.lower()}/{source_date}/{slot}.json'
    else:
        payload_path = f'research/archives/{source_date}.json'
    if (value.get('payload_path') != payload_path
            or value.get('receipt_path') != 'receipts/' + payload_path):
        return False
    if any(not isinstance(value.get(key), str) or _SHA256.fullmatch(value[key]) is None
           for key in ('payload_sha256', 'receipt_sha256', 'manifest_sha256')):
        return False
    return ('manifest_entry_sha256' not in value
            or value['manifest_entry_sha256'] == value['payload_sha256'])


def semantic_inputs(value: Any, *, _reference: bool = False) -> Any:
    """Copy declared provenance containers without a verified global SHA.

    source_row/original_source_row and literal content are never traversed,
    even when the original content happens to quote a binding-shaped object.
    Callers use this copy solely for identity calculations, preserving the
    original input/output objects and their complete provenance.
    """
    if isinstance(value, Mapping):
        if _reference and _complete_research_binding(value):
            return {key: deepcopy(item) for key, item in value.items() if key != 'manifest_sha256'}
        return {
            key: deepcopy(item) if key in _CONTENT_FIELDS else
                 semantic_inputs(item, _reference=key in _REFERENCE_FIELDS)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [semantic_inputs(item, _reference=_reference) for item in value]
    if isinstance(value, tuple):
        return tuple(semantic_inputs(item, _reference=_reference) for item in value)
    return deepcopy(value)


def _component_digests(workspace: Mapping[str, Any]) -> dict[str, str] | None:
    evidence = workspace.get('input_identity_components')
    if (not isinstance(evidence, Mapping) or evidence.get('schema_version') != COMPONENT_SCHEMA
            or evidence.get('identity_version') != workspace.get('input_identity_version')):
        return None
    digests = evidence.get('digests')
    if (not isinstance(digests, Mapping) or not 0 < len(digests) <= MAX_COMPONENTS
            or any(not isinstance(key, str) or _COMPONENT_NAME.fullmatch(key) is None
                   or not isinstance(value, str) or _SHA256.fullmatch(value) is None
                   for key, value in digests.items())):
        return None
    return dict(digests)


def identity_diagnostics(saved: Mapping[str, Any] | None, current: Mapping[str, Any]) -> dict:
    """Compare bounded evidence; this never authorizes saved-plan consumption.

    Old sealed plans are not reconstructed or migrated. Without their recorded
    components a historical changed field remains CANNOT_CONFIRM.
    """
    saved = saved if isinstance(saved, Mapping) else {}
    def identity(workspace: Mapping[str, Any]) -> str | None:
        value = workspace.get('input_identity')
        return value if isinstance(value, str) and _SHA256.fullmatch(value) else None
    def version(workspace: Mapping[str, Any]) -> str | None:
        value = workspace.get('input_identity_version')
        return value if isinstance(value, str) and re.fullmatch(r'[A-Z0-9_]{1,64}', value) else None
    result = dict(schema_version=_DIAGNOSTIC_SCHEMA, status='CANNOT_CONFIRM',
        reason='COMPONENT_EVIDENCE_UNAVAILABLE', saved_input_identity=identity(saved),
        current_input_identity=identity(current), saved_identity_version=version(saved),
        current_identity_version=version(current), changed_component_count=None,
        changed_components=[], truncated=False)
    before, after = _component_digests(saved), _component_digests(current)
    if (before is None or after is None or result['saved_identity_version'] is None
            or result['current_identity_version'] is None
            or result['saved_input_identity'] is None or result['current_input_identity'] is None):
        return result
    changed = [dict(component=key, saved_sha256=before.get(key), current_sha256=after.get(key))
               for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]
    identities_match = (result['saved_input_identity'] == result['current_input_identity']
                        and result['saved_identity_version'] == result['current_identity_version'])
    if identities_match and changed:
        result['reason'] = 'COMPONENT_EVIDENCE_INCONSISTENT'
        return result
    if not identities_match and not changed:
        result['reason'] = 'IDENTITY_CHANGED_OUTSIDE_RECORDED_COMPONENTS'
        return result
    result.update(status='CHANGED' if changed else 'UNCHANGED',
        reason='RECORDED_COMPONENTS_CHANGED' if changed else 'INPUT_IDENTITIES_MATCH',
        changed_component_count=len(changed), changed_components=changed[:MAX_CHANGED_COMPONENTS],
        truncated=len(changed) > MAX_CHANGED_COMPONENTS)
    return result
