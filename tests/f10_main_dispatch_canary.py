"""Run in the prepared Main runtime; use a temporary product and fake F10 I/O."""
from pathlib import Path
from types import SimpleNamespace
import fcntl,hashlib,json,os,tempfile
import pyarrow as pa
import pyarrow.parquet as pq
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from ops import research_panel_daily_product as daily, research_panel_f10 as f10, research_panel_top200 as top
from ops import sync_stock_history_completion as owner

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,sort_keys=True))
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def main():
    with tempfile.TemporaryDirectory(prefix='f10-main-dispatch-') as folder:
        r=Path(folder).resolve();root=r/'daily_products/a_share';(root/'events').mkdir(parents=True)
        panel=r/'panel.parquet';pq.write_table(pa.table({'ts_code':['002865.SZ','301048.SZ'],'exchange':['SZ','SZ']}),panel)
        context=SimpleNamespace(scope=['002865.SZ','301048.SZ'],panel=panel,target=20261030,generation='a'*64,
             identity={'selector_artifact_sha256':'b'*64,'input_sha256':'c'*64},unchanged=lambda:None)
        manifest=save(root/'manifest.json',{'source_generation':context.generation,'input_sha256':context.identity['input_sha256']})
        save(root/'index.json',{'dates':{'20261030':manifest}})
        save(root/'events/latest.json',{'data_date':'20261030','source_generation':context.generation,'input_sha256':context.identity['input_sha256'],'manifest':manifest})
        receipt_root=r/'receipts';save(receipt_root/'a_sync_authority/official_daily/20261030/input.json',{})
        lock=r/'A_LONG.lock';lock.touch();owner.DEFAULT_OWNER_LOCK=lock
        daily.SourceContext=lambda *_:context
        top.run_incremental_history=lambda *_:{'status':'COMPLETE_NO_HISTORY_GAPS'}
        top.publish_current_history_view=lambda *_:{'status':'NO_NEW_COMPLETION'}
        top.build=lambda *_:({}, {'reused':True})
        original=f10.complete_f10;calls=[]
        def run(context,ref,root,**kwargs):
            calls.append(ref)
            return original(context,ref,root,fetch=lambda code,exchange:{'symbol':code,'exchange':exchange,
                'status':'OBSERVED','historical_PIT':False,**f10.FLAGS},**kwargs)
        f10.complete_f10=run
        os.environ.update(V4_A_SHARE_DAILY_PRODUCT_ROOT=str(r),V4_RESEARCH_PANEL_A_DATA_ROOT=str(r),
            V4_RESEARCH_PANEL_RECEIPT_ROOT=str(receipt_root),V4_WORKBENCH_CLASSIFICATION_ROOT=str(r),RESEARCH_PANEL_QFQ_WORKERS='2')
        os.environ.pop('V4_WORKBENCH_STATISTICS_ROOT',None)
        lane=os.open(lock,os.O_RDONLY);fcntl.flock(lane,fcntl.LOCK_EX|fcntl.LOCK_NB)
        os.environ.update(V4_SCHEDULER_LANE_FD=str(lane),V4_SCHEDULER_LANE_NAME='A_LONG',
                          V4_SCHEDULER_RESOLVED_DATE='20261030',V4_SCHEDULER_RESOLVED_SLOT='1540')
        registry=SimpleNamespace(_run_a_daily_source=lambda request:{'status':'COMPLETE'})
        request=SimpleNamespace(mode=SimpleNamespace(value='LIVE'),business_date='20261030')
        result=FixedExecutorRegistry._run_a_daily(registry,request);derived=result['daily_derivatives'];f=derived['f10']
        index=json.loads((root/'index.json').read_text());event=json.loads((root/'events/latest.json').read_text())
        assert len(calls)==1 and calls[0]==derived['attempt']
        assert f['status']=='COMPLETE' and f['requested']==f['observed']==2,repr(f)
        assert index['attempts']['20261030']==derived['attempt']
        assert index['f10']['20261030']==event['f10']==f['receipt']
        assert json.loads(Path(f['receipt']['path']).read_text())['upstream_success_receipt']==derived['attempt']
        assert hashlib.sha256(Path(derived['attempt']['path']).read_bytes()).hexdigest()==derived['attempt']['sha256']
        os.close(lane)
        print(json.dumps({'status':'CANDIDATE_MAIN_ACTUAL_DISPATCH_AND_PERSISTENCE_PASS','symbols':2,
            'f10_calls':len(calls),'attempt_ref_matches':True,'index_event_f10_ref_matches':True,
            'existing_attempt_sha_unchanged':True,'inherited_a_long_lock':'PASS',
            'source':'isolated fake F10; actual prepared Main modules',**f10.FLAGS}))
if __name__=='__main__':main()
