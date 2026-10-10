"""Consumed-artifact fingerprints; registry provenance is never source content.

This module does not read or validate artifacts. Only exact V35 archive
bindings already emitted by the original verified reader have a provenance
exception, and only at a material's top-level ``source_refs`` boundary.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

IDENTITY_CONTRACT = 'CONSUMED_ARTIFACTS_V1'
COMPONENT_SCHEMA = 'v4.manager_input_identity_components.v1'
DIAGNOSTIC_SCHEMA = 'v4.manager_input_identity_diagnostic.v1'
_SHA = re.compile(r'[0-9a-f]{64}')


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _archive_ref(ref: Any) -> bool:
    if not isinstance(ref, Mapping):
        return False
    date, slot, mode = ref.get('source_date'), ref.get('slot'), ref.get('mode')
    if (ref.get('source_id') != 'V35_RESEARCH_DATA_ROOT' or ref.get('status') != 'VERIFIED'
            or not isinstance(date, str) or not re.fullmatch(r'\d{8}', date)
            or not isinstance(slot, str) or mode not in {'LIVE', 'REPLAY', 'BACKFILL'}
            or not isinstance(ref.get('source_root'), str)
            or ref.get('write_policy') != 'read_only'
            or any(ref.get(key) is not False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'))):
        return False
    if slot and (not re.fullmatch(r'\d{4}', slot) or int(slot[:2]) > 23 or int(slot[2:]) > 59):
        return False
    path = (f'research/hourly/{mode.lower()}/{date}/{slot}.json'
            if slot else f'research/archives/{date}.json')
    return (ref.get('payload_path') == path and ref.get('receipt_path') == 'receipts/' + path
        and ref.get('manifest_path') == 'manifest.json'
        and all(isinstance(ref.get(key), str) and _SHA.fullmatch(ref[key])
                for key in ('payload_sha256', 'receipt_sha256', 'manifest_sha256')))


def semantic_materials(materials: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Copy only the known material binding boundary; never walk source rows."""
    result = deepcopy(list(materials))
    for material in result:
        if not isinstance(material, Mapping) or not isinstance(material.get('source_refs'), list):
            continue
        for ref in material['source_refs']:
            if _archive_ref(ref):
                ref.pop('manifest_sha256')
    return result


def restore_material_provenance(value: Any, materials: Sequence[Mapping[str, Any]]) -> Any:
    """Overlay original refs on derived DTOs after their identities are fixed.

    The saved/UI material rows retain their original contract. Arbitrary
    material fields and original source bodies are copied without traversal.
    This adds read provenance only; it cannot promote a material or a plan.
    """
    refs, material_keys = {}, {}
    for material in materials:
        if not isinstance(material, Mapping):
            continue
        if material.get('material_id'):
            material_keys.setdefault(str(material['material_id']), set()).update(material)
        for ref in material.get('source_refs') or []:
            if _archive_ref(ref):
                semantic = {key: item for key, item in ref.items() if key != 'manifest_sha256'}
                refs[_digest(semantic)] = dict(ref)

    def visit(item: Any) -> Any:
        if isinstance(item, list):
            return [visit(child) for child in item]
        if not isinstance(item, Mapping):
            return deepcopy(item)
        protected = material_keys.get(str(item.get('material_id') or ''), set())
        result = {}
        for key, child in item.items():
            if key == 'source_refs' and isinstance(child, list):
                result[key] = [deepcopy(refs.get(_digest(ref), ref)) for ref in child]
            elif key in {'source_row', 'original_source_row'} or key in protected:
                result[key] = deepcopy(child)
            else:
                result[key] = visit(child)
        return result

    return visit(value) if refs else deepcopy(value)


def material_components(materials: Sequence[Mapping[str, Any]]) -> list[dict]:
    """One small, stable locator per consumed artifact, never raw source rows."""
    groups = {}
    for material, semantic in zip(materials, semantic_materials(materials)):
        if not isinstance(material, Mapping):
            continue
        for ref in material.get('source_refs') or []:
            if not _archive_ref(ref):
                continue
            source = {key: ref[key] for key in ('source_id', 'source_date', 'payload_path', 'receipt_path', 'slot', 'mode')}
            source['source_root_sha256'] = _digest(ref['source_root'])
            component_id = 'material_source:' + _digest(source)
            group = groups.setdefault(component_id, {'source': source, 'records': [], 'provenance': {}})
            group['records'].append(semantic)
            group['provenance'] = {key: ref[key] for key in ('manifest_path', 'manifest_sha256')}
    return [dict(component_id=key, sha256=_digest(group['records']),
                 source=group['source'], provenance=group['provenance'])
            for key, group in sorted(groups.items())]


def component_snapshot(identity: str, values: Mapping[str, Any], *,
                       previous: Mapping[str, Any] | None = None,
                       materials: Sequence[Mapping[str, Any]] = ()) -> dict:
    components = {row['component_id']: deepcopy(row) for row in (previous or {}).get('components', [])}
    components.update({key: dict(component_id=key, sha256=_digest(value)) for key, value in values.items()})
    components.update({row['component_id']: row for row in material_components(materials)})
    result = dict(schema_version=COMPONENT_SCHEMA, identity_contract=IDENTITY_CONTRACT,
        input_identity=identity, components=[components[key] for key in sorted(components)])
    result['sha256'] = _digest(result)
    return result


def _valid_component(row: Any) -> bool:
    if (not isinstance(row, Mapping) or set(row) - {'component_id', 'sha256', 'source', 'provenance'}
            or not isinstance(row.get('component_id'), str)
            or not re.fullmatch(r'[a-z][a-z0-9_.:]{0,159}', row['component_id'])
            or not isinstance(row.get('sha256'), str) or not _SHA.fullmatch(row['sha256'])):
        return False
    if 'source' not in row:
        return 'provenance' not in row and not row['component_id'].startswith('material_source:')
    source, provenance = row['source'], row.get('provenance')
    keys = {'source_id', 'source_date', 'source_root_sha256', 'payload_path', 'receipt_path', 'slot', 'mode'}
    if (not isinstance(source, Mapping) or set(source) != keys
            or any(not isinstance(value, str) for value in source.values())
            or source['source_id'] != 'V35_RESEARCH_DATA_ROOT'
            or not re.fullmatch(r'\d{8}', source['source_date'])
            or not _SHA.fullmatch(source['source_root_sha256'])
            or source['mode'] not in {'LIVE', 'REPLAY', 'BACKFILL'}
            or not isinstance(provenance, Mapping)
            or set(provenance) != {'manifest_path', 'manifest_sha256'}
            or provenance['manifest_path'] != 'manifest.json'
            or not isinstance(provenance['manifest_sha256'], str)
            or not _SHA.fullmatch(provenance['manifest_sha256'])):
        return False
    date, slot, mode = source['source_date'], source['slot'], source['mode']
    if slot and (not re.fullmatch(r'\d{4}', slot) or int(slot[:2]) > 23 or int(slot[2:]) > 59):
        return False
    path = (f'research/hourly/{mode.lower()}/{date}/{slot}.json'
            if slot else f'research/archives/{date}.json')
    return (source['payload_path'] == path and source['receipt_path'] == 'receipts/' + path
        and row['component_id'] == 'material_source:' + _digest(source))


def _verified_components(workspace: Mapping[str, Any], side: str) -> tuple[dict, str | None]:
    metadata = workspace.get('input_identity_components')
    if metadata is None:
        return {}, side + '_COMPONENT_METADATA_MISSING'
    if not isinstance(metadata, Mapping):
        return {}, side + '_COMPONENT_METADATA_INVALID'
    components = metadata.get('components')
    if (metadata.get('schema_version') != COMPONENT_SCHEMA
            or metadata.get('identity_contract') != IDENTITY_CONTRACT
            or metadata.get('input_identity') != workspace.get('input_identity')
            or not isinstance(components, list)
            or metadata.get('sha256') != _digest({key: value for key, value in metadata.items() if key != 'sha256'})):
        return {}, side + '_COMPONENT_METADATA_INVALID'
    result = {}
    for row in components:
        if not _valid_component(row) or row['component_id'] in result:
            return {}, side + '_COMPONENT_METADATA_INVALID'
        result[row['component_id']] = row
    return result, None


def compare_components(saved: Mapping[str, Any], current: Mapping[str, Any]) -> dict:
    result = dict(schema_version=DIAGNOSTIC_SCHEMA, status='CANNOT_CONFIRM',
        saved_input_identity=saved.get('input_identity'), current_input_identity=current.get('input_identity'),
        reason_codes=[], changed_components=[], provenance_changes=[])
    before, before_error = _verified_components(saved, 'SAVED')
    after, after_error = _verified_components(current, 'CURRENT')
    result['reason_codes'] = [error for error in (before_error, after_error) if error]
    if result['reason_codes']:
        return result
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key, {}), after.get(key, {})
        source = deepcopy(new.get('source') or old.get('source'))
        if old.get('sha256') != new.get('sha256'):
            row = dict(component_id=key, change='CHANGED' if old and new else 'ADDED' if new else 'REMOVED',
                saved_sha256=old.get('sha256'), current_sha256=new.get('sha256'))
            if source:
                row['source'] = source
            result['changed_components'].append(row)
        old_provenance, new_provenance = old.get('provenance', {}), new.get('provenance', {})
        if old_provenance != new_provenance:
            row = dict(component_id=key,
                saved_manifest_sha256=old_provenance.get('manifest_sha256'),
                current_manifest_sha256=new_provenance.get('manifest_sha256'))
            if source:
                row['source'] = source
            result['provenance_changes'].append(row)
    if result['changed_components']:
        result['status'] = 'CHANGED'
    elif result['saved_input_identity'] == result['current_input_identity']:
        result['status'] = 'MATCH'
    else:
        result['reason_codes'] = ['UNATTRIBUTED_INPUT_IDENTITY_CHANGE']
    return result


def components_allow_reuse(saved: Mapping[str, Any], current: Mapping[str, Any], diagnostic: Mapping[str, Any] | None = None) -> bool:
    # Optional metadata preserves legacy DTO callers' existing exact-equality
    # guard. A newly computed workspace always has metadata and requires the
    # saved side to verify; an old plan is never reinterpreted as a new one.
    if 'input_identity_components' not in saved and 'input_identity_components' not in current:
        return True
    return (diagnostic or compare_components(saved, current)).get('status') == 'MATCH'
