#!/usr/bin/env python3
"""Diagnose exact-date gaps or score an existing sealed afterfact observation.

No network transport and no rewriting original receipts/raw/selection. New
quotes remain owned by the existing natural Stage snapshot-recovery producer.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

if __name__=='__main__' and not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage_center.contracts import SAFETY_FLAGS, STAGE_BY_ID

def sha(raw):return hashlib.sha256(raw).hexdigest()
def run(config,date,stage,*,action='diagnose',expected_receipt_sha256=None):
    from stage_center.candidate_input import read_candidate_input
    from stage_center.snapshot_recovery import ObservationStore
    from stage_center.snapshot_selection import SupplementStore,recover_and_select
    if stage not in STAGE_BY_ID or len(date)!=8 or not date.isdigit():raise ValueError('EXACT_STAGE_DATE_REQUIRED')
    receipt=Path(config['receipt_root'])/date/stage/'receipt.json'
    original=receipt.read_bytes();observed_sha=sha(original)
    if expected_receipt_sha256 and observed_sha!=expected_receipt_sha256:raise ValueError('ORIGINAL_RECEIPT_CAS_MISMATCH')
    candidate=read_candidate_input(config['candidate_acquisition_root'],date)
    report={'status':'DIAGNOSED','trade_date':date,'stage_id':stage,'receipt_sha256':observed_sha,
        'original_row_count':candidate.original_row_count,'effective_row_count':len(candidate.codes),
        'quarantined_codes':list(candidate.quarantined_codes),'candidate_current_sha256':candidate.current_sha256,
        'network_invocations':0,'natural_execution_verified':False,**SAFETY_FLAGS}
    try:
        observation=ObservationStore(config['selection_root']).read(date,stage)
        report['observation']={k:observation.get(k) for k in ('observation_id','captured_at','observed_trade_date','observed_rows')}
    except FileNotFoundError:
        report['observation']={'status':'CANNOT_CONFIRM','reason':'SEALED_OBSERVATION_MISSING_NO_HISTORICAL_RECONSTRUCTION'}
        if action=='select-existing':return {**report,'status':'CANNOT_CONFIRM_NO_SEALED_OBSERVATION'}
    try:
        selected=SupplementStore(config['selection_root']).read(date,stage)
        report['supplement']={k:selected.get(k) for k in ('mode','selected_rows','captured_at','recommendation_status')}
    except FileNotFoundError:report['supplement']={'status':'MISSING'}
    if action=='select-existing':
        if not expected_receipt_sha256:raise ValueError('ORIGINAL_RECEIPT_CAS_REQUIRED')
        from stage_center.runner import SlotLock
        lock=SlotLock(Path(config['receipt_root'])/'.locks'/f'{date}-{stage}.lock')
        if not lock.acquire():raise ValueError('ORIGINAL_SLOT_LOCKED')
        try:
            if receipt.read_bytes()!=original:raise ValueError('ORIGINAL_RECEIPT_CAS_MISMATCH')
            # The observation was verified above, so no missing target may be
            # fetched. A deny-provider also fails closed on unexpected fallback.
            class DenyProvider:
                def snapshot(self,*args,**kwargs):raise ValueError('RECOVERY_NETWORK_FORBIDDEN')
            result=recover_and_select(config,date,stages=[stage],provider=DenyProvider())
            if receipt.read_bytes()!=original:raise ValueError('ORIGINAL_RECEIPT_CHANGED')
            report.update(status=result['status'],snapshot_reselection=result.get('snapshot_reselection'))
        finally:lock.release()
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--trade-date',required=True);p.add_argument('--stage-id',required=True)
    p.add_argument('--action',choices=('diagnose','select-existing'),default='diagnose')
    p.add_argument('--expected-receipt-sha256');a=p.parse_args()
    try:result=run(json.loads(a.config.read_bytes()),a.trade_date,a.stage_id,action=a.action,
                   expected_receipt_sha256=a.expected_receipt_sha256)
    except (OSError,ValueError,KeyError,TypeError) as error:
        result={'status':'CANNOT_CONFIRM','error':f'{type(error).__name__}:{error}','network_invocations':0,**SAFETY_FLAGS}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result['status'] in {'DIAGNOSED','SNAPSHOT_RESELECTION_READY'} else 3
if __name__=='__main__':raise SystemExit(main())
