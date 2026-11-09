"""Exact-identity reader for the original daily owner's score/action sidecar."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)


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
    ref=index.get('items',{}).get(symbol)
    if ref is None:return dict(status='UNKNOWN',reason='SYMBOL_NOT_MATERIALIZED_FOR_DATE',row=None)
    row=read(ref)
    if (row.get('symbol')!=symbol or str(row.get('trade_date'))!=day or row.get('historical_PIT') is not False
            or any(row.get(k)!=v for k,v in FLAGS.items())
            or row.get('cache_identity',{}).get('rules')!=index['rules']
            or row.get('cache_identity',{}).get('price_basis')!=index['price_basis']):
        raise ValueError('SCORE_ROW_IDENTITY_CONFLICT')
    return dict(status=row['status'],reason=row.get('reason'),row=row,rules=index['rules'],
                score_index_sha256=descriptor['index']['sha256'],score_row_sha256=ref['sha256'],
                action_contract_sha256=index['rules']['a_share_kb_action_v1.json'],
                hold_score_contract_sha256=index['rules']['a_share_kb_hold_score_v1.json'],
                price_basis=index['price_basis'])
