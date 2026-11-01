"""Stage completion consumer. Default off; writes only derived isolated sidecars."""
from __future__ import annotations
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from infrastructure.report_evidence_index import SAFETY, canonical, digest


def sidecar_key(date, stage, selection_run, market):
    if not re.fullmatch(r'\d{8}', date) or not re.fullmatch(r'STAGE_[0-9_]+', stage):
        raise ValueError('INVALID_STAGE_SCOPE')
    if not re.fullmatch(r'run-[A-Za-z0-9_.-]+', selection_run) or market not in {'A_SHARE','HK_CONNECT'}:
        raise ValueError('INVALID_SELECTION_SCOPE')
    return digest(canonical([date, stage, selection_run, market]))


def _root(value, selection_root, data_root):
    root = Path(value).absolute()
    for source in (Path(selection_root).resolve(), Path(data_root).resolve()):
        if root.resolve() == source or source in root.resolve().parents or root.resolve() in source.parents:
            raise ValueError('SIDECAR_ROOT_MUST_BE_ISOLATED')
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError('SIDECAR_SYMLINK_REJECTED')
    return root


async def materialize(*, config, trade_date, stage_id, receipt, service, root):
    from stage_center.consumer import StageSelectionConsumer
    from stage_center.contracts import STAGE_BY_ID
    if receipt.get('trade_date') != trade_date or receipt.get('stage_id') != stage_id:
        raise ValueError('RUNNER_SCOPE_MISMATCH')
    if any(receipt.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):
        raise ValueError('RUNNER_SAFETY_MISMATCH')
    consumer = StageSelectionConsumer(config['selection_root'], execution_receipt_root=config.get('receipt_root'))
    if consumer.execution_receipt_root is None:
        raise ValueError('RUNNER_RECEIPT_ROOT_UNVERIFIED')
    receipt_path = consumer.execution_receipt_root / trade_date / stage_id / 'receipt.json'
    if receipt_path.is_symlink() or any(p.is_symlink() for p in receipt_path.parents):
        raise ValueError('RUNNER_RECEIPT_SYMLINK_REJECTED')
    receipt_raw = receipt_path.read_bytes()
    if json.loads(receipt_raw) != receipt:
        raise ValueError('PERSISTED_RUNNER_RECEIPT_MISMATCH')
    markets = list((receipt.get('markets') or {}).keys())
    projected = consumer.get(trade_date, stage_id, markets=markets, allow_backfill=False)
    cutoff = datetime.strptime(trade_date + STAGE_BY_ID[stage_id].cutoff, '%Y%m%d%H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Shanghai')).isoformat()
    outputs = []
    for market in markets:
        lane = projected['markets'][market]
        original = receipt['markets'][market]
        if (lane.get('selection_manifest_receipt_verified') is not True or
            lane.get('run_id') != original.get('run_id') or lane.get('artifact_id') != original.get('artifact_id')):
            outputs.append(dict(market=market,status='EVIDENCE_GAP',reason='ORIGINAL_SELECTION_BINDING_UNVERIFIED'))
            continue
        # Verify actual immutable trio and bind observed runner declarations separately.
        envelope = consumer.store.read_verified(trade_date,stage_id,market)
        verified = consumer.store._verify_run(trade_date,stage_id,market,lane['run_id'])
        key = sidecar_key(trade_date,stage_id,lane['run_id'],market)
        generation = None
        with service.index.connect() as db:
            generation = service.index.generation(db)
        binding = dict(original_selection_run=lane['run_id'],market=market,date=trade_date,stage=stage_id,
            cutoff=cutoff,cutoff_source='stage_center.contracts.StageSpec.cutoff',index_generation=generation,
            selection_root=str(consumer.store.root),selection_artifact_sha256=verified['artifact_sha256'],selection_manifest_sha256=verified['manifest_sha256'],
            selection_receipt_sha256=verified['receipt_sha256'],runner_receipt_observed_sha256=digest(receipt_raw),
            runner_receipt_verified=True, runner_verification_scope='PERSISTED_DECLARATION_AND_SELECTION_TRIO_ONLY_NOT_NATURAL_EXECUTION',
            runner_execution_status=projected.get('execution_evidence',{}).get('status'))
        path=root/(key+'.json')
        if path.exists():
            old=json.loads(path.read_text())
            if old.get('binding') == binding:
                outputs.append(dict(market=market,status='REUSED',path=str(path)))
                continue
        evidence=[]
        for row in envelope['rows']:
            code=str(row['code'])
            result=await service.search(code,security=code,market='A' if market=='A_SHARE' else 'HK',
                mode='historical_evidence',as_of=cutoff,limit=3)
            evidence.append(dict(code=code,evidence=result))
        # Recheck the same input bytes after retrieval; sidecar never blesses a new run.
        if consumer.store.read_verified(trade_date,stage_id,market) != envelope:
            raise ValueError('SELECTION_CHANGED_DURING_SIDECAR')
        with service.index.connect() as db:
            if service.index.generation(db) != generation:
                raise ValueError('INDEX_GENERATION_CHANGED_DURING_SIDECAR')
        payload=dict(schema_version='v4.stage_report_evidence.v1',status='EXPLANATION_ONLY',binding=binding,
            rows=evidence,selection_scores_used=False,independent_corrob_count_basis='UNIQUE_ORIGINAL_PDF_SHA',**SAFETY)
        root.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.tmp');temp.write_text(canonical(payload));os.replace(temp,path)
        outputs.append(dict(market=market,status='MATERIALIZED',path=str(path)))
    return dict(status='SIDECAR_ONLY',items=outputs,**SAFETY)


def on_stage_completed(*, config, trade_date, stage_id, receipt):
    if os.environ.get('V4_STAGE_REPORT_EVIDENCE_ENABLED') != '1':
        return dict(status='DISABLED',**SAFETY)
    try:
        from apps.api.v4_api.report_evidence_router import configured_service
        data_root=os.environ.get('V4_RESEARCH_DATA_ROOT')
        sidecar_root=os.environ.get('V4_REPORT_EVIDENCE_SIDECAR_ROOT')
        if not data_root or not sidecar_root:
            return dict(status='EVIDENCE_GAP',reason='SIDECAR_NOT_CONFIGURED',**SAFETY)
        service=configured_service(data_root)
        if service is None or not service.index.path.is_file():
            return dict(status='EVIDENCE_GAP',reason='INDEX_NOT_CONFIGURED',**SAFETY)
        root=_root(sidecar_root,config['selection_root'],data_root)
        return asyncio.run(materialize(config=config,trade_date=trade_date,stage_id=stage_id,receipt=receipt,service=service,root=root))
    except Exception as error:
        return dict(status='EVIDENCE_GAP',reason=type(error).__name__,**SAFETY)


def read_sidecar(root, *, date, stage, selection_run, market):
    key=sidecar_key(date,stage,selection_run,market)
    if not root:
        return dict(status='EVIDENCE_GAP',reason='SIDECAR_NOT_CONFIGURED',**SAFETY)
    path=Path(root)/(key+'.json')
    if not path.is_file():
        return dict(status='EVIDENCE_GAP',reason='SIDECAR_NOT_MATERIALIZED',**SAFETY)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('SIDECAR_SYMLINK_REJECTED')
    value=json.loads(path.read_text())
    binding=value.get('binding',{})
    if any(binding.get(k)!=v for k,v in [('date',date),('stage',stage),('original_selection_run',selection_run),('market',market)]):
        raise ValueError('SIDECAR_BINDING_MISMATCH')
    from stage_center.selection import SelectionStore
    selected = SelectionStore(binding['selection_root'])._verify_run(date,stage,market,selection_run)
    for field, original in [('artifact_sha256','selection_artifact_sha256'),('manifest_sha256','selection_manifest_sha256'),('receipt_sha256','selection_receipt_sha256')]:
        if selected[field] != binding[original]:
            raise ValueError('ORIGINAL_SELECTION_SHA_CHANGED')
    # Do not serve stale original text merely because the sidecar is persisted.
    from apps.api.v4_api.report_evidence_router import configured_service
    service=configured_service(os.environ.get('V4_RESEARCH_DATA_ROOT',''))
    if service is None:
        return dict(status='EVIDENCE_GAP',reason='INDEX_NOT_CONFIGURED',**SAFETY)
    with service.index.connect() as db:
        if service.index.generation(db)!=binding.get('index_generation'):
            return dict(status='EVIDENCE_GAP',reason='INDEX_GENERATION_CHANGED',**SAFETY)
    for row in value.get('rows',[]):
        for hit in row.get('evidence',{}).get('hits',[]):
            for cid in hit.get('merged_chunk_ids', [hit['chunk_id']]):
                service.read(cid)
    return value
