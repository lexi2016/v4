"""Exact-identity reader for the original daily owner's score/action sidecar."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
SCORE_WRITER_MODULE = 'materialize_workbench_score_action.py'
SCORE_CALCULATION_MODULE = 'workbench_score_calculation.py'
PINNED_SCORE_CALCULATION_SHA256 = '4e039f65ef92e597bed7af212a7d98ccf8ca523100b1fc854e3a0b177f74b152'
LEGACY_SCORE_WRITER_SHA256S = frozenset({
    'c70c1d8bd6dba9fe2e89dba88d7ded5cff05342ee13ef1516087355b966f52df',
    '005c8b3ef4723ffc56385d2ad91d5487e3cd3aeb30d56886671f063e39c96b1b',
})
SCORE_RULE_FILES = frozenset({
    'a_share_kb_action_v1.json', 'a_share_kb_fields_v1.json',
    'a_share_kb_hold_score_v1.json', 'a_share_kb_n_structure_v1.json',
    'kb_action_authority.py', 'kb_hold_score.py', 'kb_n_structure.py',
    'kb_signal_authority.py',
})


def _is_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _valid_writer_provenance(provenance):
    return (isinstance(provenance, dict) and set(provenance) == {'module', 'sha256'}
            and provenance['module'] == SCORE_WRITER_MODULE and _is_sha(provenance['sha256']))


def score_rule_identity(rules, writer_provenance=None):
    """Compare the fixed calculation identity independently of the writer."""
    if (not isinstance(rules, dict)
            or set(rules) not in (SCORE_RULE_FILES | {SCORE_CALCULATION_MODULE},
                                  SCORE_RULE_FILES | {SCORE_WRITER_MODULE})
            or not all(map(_is_sha, rules.values()))):
        raise ValueError('SCORE_RULE_MAP_INVALID')
    if SCORE_WRITER_MODULE in rules:
        if writer_provenance is not None:
            raise ValueError('SCORE_DUPLICATE_WRITER_PROVENANCE')
        if rules[SCORE_WRITER_MODULE] not in LEGACY_SCORE_WRITER_SHA256S:
            raise ValueError('SCORE_LEGACY_WRITER_CONFLICT')
        writer_provenance = dict(module=SCORE_WRITER_MODULE, sha256=rules[SCORE_WRITER_MODULE])
    elif rules[SCORE_CALCULATION_MODULE] != PINNED_SCORE_CALCULATION_SHA256:
        raise ValueError('SCORE_CALCULATION_PIN_CONFLICT')
    if not _valid_writer_provenance(writer_provenance):
        raise ValueError('SCORE_WRITER_PROVENANCE_INVALID')
    semantic = {name: rules[name] for name in SCORE_RULE_FILES}
    semantic[SCORE_CALCULATION_MODULE] = PINNED_SCORE_CALCULATION_SHA256
    return semantic, writer_provenance


def read_score_action(root,descriptor,product,source_date,symbol):
    root=Path(root).resolve()
    def read(ref):
        p=Path(ref['path'])
        if not p.is_absolute() or p.is_symlink() or p.resolve(strict=True)!=p or not p.is_relative_to(root):
            raise ValueError('SCORE_ASSET_PATH_CONFLICT')
        raw=p.read_bytes()
        if len(raw)>8*1024*1024 or hashlib.sha256(raw).hexdigest()!=ref['sha256']:
            raise ValueError('SCORE_ASSET_SHA_CONFLICT')
        return json.loads(raw)
    day=source_date.replace('-','')
    identity=dict(data_date=day,source_generation=product['source_generation'],
                  input_sha256=product['source_identity']['input_sha256'],numeric_manifest=product['manifest'])
    if any(descriptor.get(k)!=v for k,v in identity.items()):raise ValueError('SCORE_DESCRIPTOR_IDENTITY_CONFLICT')
    index=read(descriptor['index'])
    if (index.get('schema')!='v4.workbench.daily_score_action.v1' or index.get('historical_PIT') is not False
            or any(index.get(k)!=v for k,v in (identity|FLAGS).items())
            or index.get('source_selector_sha256')!=product['source_identity']['selector_artifact_sha256']):
        raise ValueError('SCORE_INDEX_IDENTITY_CONFLICT')
    new_identity = (SCORE_CALCULATION_MODULE in (index.get('rules') or {})
                    or index.get('writer_provenance') is not None
                    or index.get('row_writer_sha256s') is not None)
    if new_identity:
        score_rule_identity(index.get('rules'), index.get('writer_provenance'))
        if SCORE_CALCULATION_MODULE not in index['rules']:
            raise ValueError('SCORE_MIXED_INDEX_ENCODING')
        row_writers = index.get('row_writer_sha256s')
        if (not isinstance(row_writers, list) or not all(map(_is_sha, row_writers))
                or row_writers != sorted(set(row_writers)) or len(row_writers) > len(index.get('items', {}))):
            raise ValueError('SCORE_INDEX_WRITER_PARTITION_INVALID')
    ref=index.get('items',{}).get(symbol)
    if ref is None:return dict(status='UNKNOWN',reason='SYMBOL_NOT_MATERIALIZED_FOR_DATE',row=None)
    row=read(ref)
    cache=row.get('cache_identity',{})
    if (row.get('symbol')!=symbol or str(row.get('trade_date'))!=day or row.get('historical_PIT') is not False
            or any(row.get(k)!=v for k,v in FLAGS.items())
            or cache.get('rules')!=index['rules']
            or cache.get('writer_provenance') is not None
            or cache.get('price_basis')!=index['price_basis']):
        raise ValueError('SCORE_ROW_IDENTITY_CONFLICT')
    provenance = row.get('writer_provenance')
    if (new_identity and (not _valid_writer_provenance(provenance) or provenance['sha256'] not in row_writers)
            or not new_identity and provenance is not None):
        raise ValueError('SCORE_ROW_WRITER_PROVENANCE_CONFLICT')
    return dict(status=row['status'],reason=row.get('reason'),row=row,rules=index['rules'],
                score_index_sha256=descriptor['index']['sha256'],score_row_sha256=ref['sha256'],
                action_contract_sha256=index['rules']['a_share_kb_action_v1.json'],
                hold_score_contract_sha256=index['rules']['a_share_kb_hold_score_v1.json'],
                price_basis=index['price_basis'])
