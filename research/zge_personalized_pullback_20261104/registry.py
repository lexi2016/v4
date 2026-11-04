"""Append this experiment's live events through the existing locked registry adapter."""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/Users/lexi/Desktop/学习/因子工厂')
OUT = Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/pullback_model_design_20261104/training_v1')
BASE_SIZE=45788659
BASE_SHA='6eef813ee188c8d7e98c130b71823aad2ffed41f32c16aee18b59f57dd9ae224'
LEGACY_EXCEPTIONS={
  6764:'6b0d8e4a97272832aa15436d11bba52604100a0af4462799853bb7e36e6e7f46',
  6767:'ed2b1d1b6e95adf9abc5375632ec618ad05711113d12272088ecf7f3b7cdcc15',
  6772:'1599192a8320f3ffdfc2b7c87258af3514d6fb55cab99cf0af00073def27c1dc',
  6775:'b175fff329a0dbe2d71589b286bb344f710fec9bdca0433395861a51f7a1491c',
}
sys.path.insert(0, str(ROOT/'workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity'))
from registry_adapter import OfficialRegistryAdapter

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(1048576), b''): h.update(data)
    return h.hexdigest()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('execution_id'); p.add_argument('event_type', choices=['RUN_STARTED','CHECKPOINT','TERMINAL','CORRECTION','PREFLIGHT_COMPLETED'])
    p.add_argument('stage'); p.add_argument('code'); p.add_argument('--artifact'); p.add_argument('--decision', default='RUNNING')
    p.add_argument('--reason', default='NONE'); p.add_argument('--contract',default=str(OUT/'EXPERIMENT_CONTRACT.json'))
    p.add_argument('--corrects-event-sha'); args = p.parse_args()
    config=Path(args.contract); contract=json.loads(config.read_text()); adapter=OfficialRegistryAdapter()
    with adapter._locked():
        preimage=adapter.registry_path.read_bytes()
        assert len(preimage)>=BASE_SIZE and hashlib.sha256(preimage[:BASE_SIZE]).hexdigest()==BASE_SHA, 'BASELINE_CHANGED_STOP'
        baseevents=[json.loads(x) for x in preimage[:BASE_SIZE].decode('utf-8').splitlines()]
        for line,expected in LEGACY_EXCEPTIONS.items():
            e=baseevents[line-1]
            assert e.get('event_sha256')==expected and e.get('event_type')=='EVIDENCE_BOUND', 'LEGACY_EXCEPTION_CHANGED_STOP'
        suffix=[json.loads(x) for x in preimage[BASE_SIZE:].decode('utf-8').splitlines()]
        assert all(e.get('route_id')==contract['route_id'] and str(e.get('execution_id','')).startswith('ZGE_PB_V1_') for e in suffix), 'CONCURRENT_SUFFIX_CHANGED_STOP'
        # Only these four already-hashed historical events receive the compatibility
        # exception. Every newly appended event uses the official lifecycle rule.
        official=adapter.validator.OFFICIAL; standard_reuse=official._execution_reuse_allowed
        official._execution_reuse_allowed=lambda e: standard_reuse(e) or e.get('event_sha256') in LEGACY_EXCEPTIONS.values()
        raw, events=adapter._read_validated()
        prior=[e for e in events if e.get('execution_id')==args.execution_id]
        if args.event_type in ('RUN_STARTED','PREFLIGHT_COMPLETED'):
            assert not prior, 'duplicate execution id'
        else:
            assert any(e.get('event_type')=='RUN_STARTED' for e in prior), 'missing start'
            if args.event_type!='CORRECTION':
                assert not any(e.get('event_type')=='TERMINAL' for e in prior), 'already terminal'
        template=next(e for e in reversed(events) if e.get('event_type')=='RUN_STARTED')
        spec={k:v for k,v in template.items() if k not in ('previous_event_sha256','event_sha256','artifact_sha256')}
        artifact=Path(args.artifact) if args.artifact else config
        metrics={'truth_positive_denominator':None,'selection_slots':None}
        if args.artifact and artifact.suffix=='.json':
            metrics['artifact_summary_path']=str(artifact)
        spec.update(schema_version='1.0',route_id=contract['route_id'],experiment_id=contract['route_id'],
            execution_id=args.execution_id,track_id='A_SHARE_PERSONALIZED_PULLBACK_DIRECTION_PROXY',
            registry_event_id=f'{args.execution_id}_{args.stage}_{args.event_type}',stage=args.stage,event_type=args.event_type,
            registration_mode='LIVE_EXECUTION',occurred_at=datetime.now(timezone.utc).isoformat(),occurred_at_reason='LIVE_EXECUTION_UTC',
            contract_path=str(config),contract_sha256=sha(config),input_sha256=contract['input']['selector_declared_sha256'],
            code_sha256=sha(args.code),config_sha256=sha(config),baseline_id=contract['baseline_id'],one_variable=contract['one_variable'],
            signal_date_range=contract['signal_date_range'],target_date_range=contract['target_date_range'],
            truth_access='OPENBOOK_PANEL_PRICE_DIRECTION_PROXY',sealed_status='NOT_SEALED_EXPOSED_HISTORY',
            runtime={'python':sys.executable,'threads':os.environ.get('OMP_NUM_THREADS')},device='CPU',
            artifact_path=str(artifact),artifact_paths=[str(artifact)],artifact_sha256=sha(artifact),
            checkpoint_ref=str(artifact) if args.event_type=='CHECKPOINT' else None,deterministic_metrics=metrics,
            decision=args.decision,stop_reason=args.reason,evidence_level='DIRECTION_ONLY',
            input_identity={'generation':contract['input']['generation'],'declared_sha_only':True,'null_reasons':{'deterministic_metrics.truth_positive_denominator':'NOT_TOPN_TRUTH','deterministic_metrics.selection_slots':'NO_SELECTION'}},
            research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
        if args.event_type=='CORRECTION':
            targets=[e for e in prior if e.get('event_sha256')==args.corrects_event_sha]
            assert len(targets)==1 and targets[0].get('event_type')=='RUN_STARTED', 'CORRECTION_TARGET_MISMATCH'
            spec['registration_mode']='APPENDED_CORRECTION'
            corrected_identity=dict(targets[0]['input_identity'])
            corrected_identity.update(basis_semantics='RETAINED_ORIGINAL_BASIS_PER_SYMBOL_ASOF_IDENTITY_CANNOT_CONFIRM',
                retained_history_asof=contract['input']['retained_history_asof'],
                source_provenance_report=str(artifact))
            spec['deterministic_metrics'].update(corrects_event_sha256=args.corrects_event_sha,
                corrects_registry_event_id=targets[0]['registry_event_id'],
                corrected_fields=['contract_path','contract_sha256','config_sha256','input_identity'],
                corrected_values={'contract_path':str(config),'contract_sha256':sha(config),'config_sha256':sha(config),
                  'input_identity':corrected_identity})
        if args.event_type=='PREFLIGHT_COMPLETED':
            # Historical evidence was first noticed in a bounded inline tool call,
            # not via this registrar; never invent an earlier RUN_STARTED/time.
            spec['registration_mode']='BACKFILLED_FROM_ARTIFACT';spec['occurred_at']=None
            spec['occurred_at_reason']='EXACT_TOOL_CALL_TIME_NOT_PRESERVED'
            spec['code_sha256']=None
            spec['input_identity']['null_reasons']['code_sha256']='INLINE_TOOL_COMMAND_BYTES_NOT_PERSISTED'
            spec['runtime']={'scope':'PREVIOUS_READ_ONLY_CACHED_PRICE_VALIDITY_DISCOVERY','interpreter':sys.executable}
        adapter._append_unlocked(raw,events,spec)
        newraw, current=adapter._read_validated()
        assert newraw.startswith(raw), 'OLD_PREFIX_CHANGED_STOP'
        mine=[e for e in current if e.get('route_id')==contract['route_id']]
        def counts(seq):return {'routes':len({e.get('route_id') for e in seq}),'events':len(seq),'executions':len({e.get('execution_id') for e in seq}),'corrections':sum(e.get('event_type')=='CORRECTION' for e in seq)}
        receipt={'registry_path':str(adapter.registry_path),'registry_sha256':hashlib.sha256(newraw).hexdigest(),
            'global_counts':counts(current),'route_counts':counts(mine),'global_unregistered_routes':None,
            'global_contract_only':None,'global_unknown_reason':'GLOBAL_ROUTE_INVENTORY_NOT_AUDITED',
            'route_unregistered_executions':0,'route_contract_only':0,'last_event_sha256':current[-1]['event_sha256'],
            'external_or_git_persistence':'CANNOT_CONFIRM','event_type':args.event_type,'execution_id':args.execution_id,
            'baseline_bytes':BASE_SIZE,'baseline_sha256':BASE_SHA,'preimage_sha256':hashlib.sha256(raw).hexdigest(),
            'legacy_exact_event_sha_exceptions':LEGACY_EXCEPTIONS,'historical_semantic_validation':'FAIL',
            'global_validation':'FAIL_PREEXISTING_SEMANTIC_DEBT','compatibility_validation':'PASS_ONLY_WITH_EXACT_FOUR_HISTORICAL_EXCEPTIONS',
            'new_event_chain_and_lifecycle':'PASS','old_prefix_byte_identity':'PASS'}
        rp=OUT/f'REGISTRY_{args.execution_id}_{args.stage}_{args.event_type}.json'
        with rp.open('x') as f: json.dump(receipt,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':main()
