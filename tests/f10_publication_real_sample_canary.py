"""Exercise the two captured samples and real publisher against an isolated index."""
import importlib.util,json,os,tempfile
from pathlib import Path
from ops import sync_stock_history_completion as owner

SCRIPT=Path('/Users/lexi/Desktop/学习/v4_app/.task_worktrees/junda-research-closure-20261101/ops/f10_publish_existing_samples.py')
spec=importlib.util.spec_from_file_location('f10_sample_canary_operator',SCRIPT);op=importlib.util.module_from_spec(spec);spec.loader.exec_module(op)
ctx,real_root,gate,sample,old,checkpoint,items,index,event,attempt=op.context_and_inputs()
real_index=json.loads(Path(index['path']).read_bytes());real_event=json.loads(Path(event['path']).read_bytes())
with tempfile.TemporaryDirectory(prefix='f10-real-sample-canary-') as folder:
    root=Path(folder).resolve();(root/'events').mkdir();op.save(root/'index.json',real_index);op.save(root/'events/latest.json',real_event)
    local_index=op.ref(root/'index.json');local_event=op.ref(root/'events/latest.json');lock=root/'A_LONG.lock';lock.touch();owner.DEFAULT_OWNER_LOCK=lock
    op.EVIDENCE=root;op.assert_main_active=lambda:None
    op.context_and_inputs=lambda:(ctx,root,gate,sample,old,checkpoint,items,local_index,local_event,attempt)
    plan={'schema':'v4.f10_two_sample_publication_plan.v1','status':'PREPARED_NOT_PUBLISHED','script_sha256':op.sha(SCRIPT),
          'adapter_sha256':op.sha(op.f10.__file__),'main_manifest':op.ref(op.MAIN/'release-manifest.json'),
          'symbols':list(op.SYMBOLS),'source_gate':gate,'sample_receipt':sample,'sample_items':checkpoint['items'],
          'product_root':str(root),'expected_index':local_index,'expected_event':local_event,'upstream_attempt':attempt,
          'historical_PIT':False,**op.FLAGS}
    plan_path=root/'plan.json';plan_ref=op.save(plan_path,plan);op.publish(plan_path,plan_ref['sha256'])
    idx=json.loads((root/'index.json').read_bytes());ev=json.loads((root/'events/latest.json').read_bytes())
    assert idx['f10']['20261030']==ev['f10'];receipt=op.read(idx['f10']['20261030']);saved=op.read(receipt['checkpoint'])
    assert receipt['scope']=={'kind':'EXPLICIT_SYMBOLS','count':2,'symbols':list(op.SYMBOLS)}
    assert set(saved['items'])==set(op.SYMBOLS) and receipt['upstream_success_receipt']==attempt
    for symbol in op.SYMBOLS:
        assert op.read(saved['items'][symbol])==items[symbol]
    assert op.ref(real_root/'index.json')==index and op.ref(real_root/'events/latest.json')==event
    print(json.dumps({'status':'ISOLATED_REAL_TWO_SAMPLE_PUBLICATION_PASS','real_samples':2,'network_fetches':0,
        'source_sample_sha256':sample['sha256'],'upstream_attempt_sha256':attempt['sha256'],
        'real_index_and_event_unchanged':True,'explicit_scope':'TWO_STOCKS_ONLY',**op.FLAGS}))
