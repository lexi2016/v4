"""Frozen ZGE B1 and auxiliary ABC on a bound local RAW panel; no data provider."""
import sys
sys.dont_write_bytecode = True
import argparse, csv, dataclasses, hashlib, importlib.util, json, logging, math, resource, time, types
from pathlib import Path

HERE = Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p, value): Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
def stat(p):
    s=Path(p).stat()
    return dict(inode=s.st_ino,mtime_ns=s.st_mtime_ns,size_bytes=s.st_size)
def deny(*a, **k): raise RuntimeError('OFFLINE_FORBIDDEN_DEPENDENCY')
def namespace(name, path=None):
    m=types.ModuleType(name);m.__path__=[str(path)] if path else [];sys.modules[name]=m;return m
def load(name, relative):
    spec=importlib.util.spec_from_file_location(name,HERE/'upstream'/relative)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def exports(dst, src):
    for k,v in vars(src).items():
        if not k.startswith('_'): setattr(dst,k,v)
def algorithms(names, histories):
    namespace('modules');ind=namespace('modules.indicators');pp=namespace('modules.indicators.price_patterns');namespace('modules.screener');namespace('modules.core')
    db=types.ModuleType('modules.database');db.DB_PATH='OFFLINE_NO_DATABASE';db.get_db_connection=deny;sys.modules[db.__name__]=db
    core=load('modules.indicators.core','modules/indicators/core.py');exports(ind,core)
    for name in ['base','brick','complex_patterns','screener_helper','bull_rope','sandglass','key_candles']:
        m=load('modules.indicators.price_patterns.'+name,'modules/indicators/price_patterns/'+name+'.py');exports(pp,m);exports(ind,m)
    for name in ['volume_patterns','wave_theory','kirin_detector']:
        m=load('modules.indicators.'+name,'modules/indicators/'+name+'.py');exports(ind,m)
    data=types.ModuleType('modules.screener.data')
    def same_daily(rows):
        assert not rows or isinstance(rows[0],core.DailyData),'IMPLICIT_DICT_CONVERSION_FORBIDDEN'
        return rows
    data._dict_to_daily=same_daily
    data.get_recent_klines=lambda code,count,datasource=None:histories[code][-count:]
    data.get_all_stocks=lambda datasource=None:[dict(ts_code=c,name=names[c]) for c in sorted(histories)]
    sys.modules[data.__name__]=data
    ds=types.ModuleType('modules.datasource');ds.DataSource=object;ds.daily_to_dict=dataclasses.asdict;sys.modules[ds.__name__]=ds
    er=types.ModuleType('modules.core.errors');er.ErrorCode=types.SimpleNamespace(SCREENER_INVALID_CRITERIA='INVALID_CRITERIA',SCREENER_NO_DATA='NO_DATA');er.ZettarancError=RuntimeError;sys.modules[er.__name__]=er
    load('modules.screener.models','modules/screener/models.py')
    load('modules.screener.scoring','modules/screener/scoring.py')
    load('modules.screener.criteria','modules/screener/criteria.py')
    engine=load('modules.screener.engine','modules/screener/engine.py')
    class NameCursor:
        def execute(self,sql,params):
            assert sql=='SELECT name FROM stock_basic WHERE ts_code = ?' and len(params)==1
            self.code=params[0]
        def fetchone(self): return {'name':names[self.code]}
    class NameOnlyConnection:
        def cursor(self): return NameCursor()
        def close(self): pass
    # Replace only the storage name lookup; original scoring/filter function bytes remain intact.
    engine.get_db_connection=NameOnlyConnection
    return core,ind,engine

class Warnings(logging.Handler):
    def __init__(self): super().__init__(logging.WARNING);self.rows=[]
    def emit(self,record): self.rows.append(record.getMessage())

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--contract',required=True);args=parser.parse_args()
    cp=Path(args.contract);c=json.loads(cp.read_text());out=Path(c['output_directory']);out.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,c['registrar_directory']);from mac_registry import register
    started=time.monotonic();register(cp,'RUN_STARTED','ZGE_LOCAL_STARTED',decision='RUNNING')
    try:
        for p,h in c['frozen_source_bindings'].items(): assert sha(p)==h,'SOURCE_DRIFT:'+p
        binding=json.loads(Path(c['mac_binding_path']).read_text());panel=Path(binding['selector']['target_path']);assert stat(panel)==binding['selector']['target_stat'],'PANEL_STAT_DRIFT'
        with Path(c['universe_path']).open(encoding='utf-8-sig',newline='') as f: universe=list(csv.DictReader(f))
        today=sorted([r for r in universe if r['trade_date']==c['signal_date']],key=lambda r:r['ts_code']);stale=[r for r in universe if r['trade_date']!=c['signal_date']]
        assert len(today)==5494 and len(stale)==318
        codes=[r['ts_code'] for r in today];names={r['ts_code']:r['name'] for r in today}
        import pandas as pd
        import pyarrow.dataset as ds
        core,ind,engine=algorithms(names,{})
        def fence(event,args):
            if event.startswith(('socket.','sqlite3.connect','subprocess.Popen','os.system','os.exec','os.posix_spawn')): deny()
        sys.addaudithook(fence)
        dataset=ds.dataset(str(panel),format='parquet')
        columns=['ts_code','trade_date','open','high','low','close','volume','amount','pct_chg','pre_close']
        predicate=ds.field('ts_code').isin(codes)&(ds.field('trade_date')>=c['history_start'])&(ds.field('trade_date')<=c['signal_date'])
        batches=[];nr=0
        for batch in dataset.scanner(columns=columns,filter=predicate,batch_size=65536,use_threads=False).to_batches():
            nr+=batch.num_rows;assert nr<=4000000,'ROW_BOUND';batches.append(batch)
        import pyarrow as pa
        frame=pa.Table.from_batches(batches).to_pandas();del batches
        frame=frame.sort_values(['ts_code','trade_date'])
        assert not frame.duplicated(['ts_code','trade_date']).any(),'DUPLICATE_HISTORY'
        frame=frame.groupby('ts_code',sort=False).tail(c['history_bars'])
        histories={}
        for code,stock in frame.groupby('ts_code',sort=False):
            histories[code]=[core.DailyData(ts_code=code,trade_date=str(x.trade_date),open=float(x.open),high=float(x.high),low=float(x.low),close=float(x.close),vol=float(x.volume),amount=float(x.amount),pct_chg=float(x.pct_chg),prev_close=float(x.pre_close)) for x in stock.itertuples(index=False)]
        del frame
        sys.modules['modules.screener.data'].get_recent_klines=lambda code,count,datasource=None:histories.get(code,[])[-count:]
        engine.get_recent_klines=sys.modules['modules.screener.data'].get_recent_klines
        warning=Warnings();logging.getLogger().addHandler(warning)
        def evaluate(code):
            warning.rows=[];bars=histories.get(code,[])
            row=dict(ts_code=code,name=names[code],signal_date=c['signal_date'],history_bars=len(bars),first_date=bars[0].trade_date if bars else None,last_date=bars[-1].trade_date if bars else None,status='ERROR',selected_b1=None,abc=None)
            try:
                result=engine._analyze_worker(code,asof=c['signal_date']);matched=engine._filter_stock(result,'b1');abc=ind.detect_abc_stages(bars)
                if warning.rows: raise RuntimeError('UPSTREAM_WARNING:'+repr(warning.rows))
                row.update(status='COMPLETE',selected_b1=bool(matched),score=dataclasses.asdict(result[2]),abc=abc)
            except Exception as exc: row.update(error_type=type(exc).__name__,error=str(exc),upstream_warnings=warning.rows[:])
            return row
        canary=[]
        for suffix in ['.SH','.SZ','.BJ']:
            canary.append(next(code for code in codes if code.endswith(suffix)))
        results={code:evaluate(code) for code in canary}
        save(out/'CANARY.json',dict(codes=canary,rows=list(results.values()),elapsed_seconds=time.monotonic()-started,rss_peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
        assert all(r['status']=='COMPLETE' for r in results.values()),'CANARY_FAILED'
        register(cp,'CHECKPOINT','ZGE_CANARY_COMPLETE',[out/'CANARY.json'],dict(canary_count=3),decision='ENGINEERING_CANARY_ONLY')
        print(json.dumps(dict(event='CANARY_COMPLETE_FULL_STARTED',codes=canary,requested=len(codes))),flush=True)
        rows_path=out/'ALL_STOCK_RESULTS.jsonl'
        with rows_path.open('w') as f:
            for i,code in enumerate(codes,1):
                r=results.get(code) or evaluate(code);results[code]=r;f.write(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n')
                if i%500==0:
                    f.flush();register(cp,'CHECKPOINT','ZGE_PROGRESS_'+str(i),[rows_path],dict(completed=i,errors=sum(r['status']!='COMPLETE' for r in results.values())),decision='RUNNING')
                    print(json.dumps(dict(event='PROGRESS',completed=i)),flush=True)
        ordered=[results[x] for x in codes];complete=[r for r in ordered if r['status']=='COMPLETE'];errors=[r for r in ordered if r['status']!='COMPLETE']
        b1=sorted([r for r in complete if r['selected_b1']],key=lambda r:(-r['score']['score'],r['ts_code']))
        auxiliary={stage:sorted([r for r in complete if r['abc']['stage']==stage],key=lambda r:(-r['abc']['confidence'],r['ts_code'])) for stage in ['A','B','C']}
        for mode,items in [('B1',b1),*auxiliary.items()]:
            with (out/(mode+'_CANDIDATES.csv')).open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['rank','code','name','signal_date','score','mode','research_only']);w.writeheader()
                for i,r in enumerate(items,1): w.writerow(dict(rank=i,code=r['ts_code'],name=r['name'],signal_date=c['signal_date'],score=r['score']['score'] if mode=='B1' else r['abc']['confidence'],mode=mode,research_only=True))
        assert stat(panel)==binding['selector']['target_stat'],'PANEL_CHANGED'
        summary=dict(status='COMPLETED_WITH_COVERAGE_LIMITS' if errors else 'COMPLETED_PENDING_INDEPENDENT_REVIEW',execution_id=c['execution_id'],upstream_commit=c['upstream_commit'],signal_date=c['signal_date'],selection_date=c['selection_date'],price_basis=c['price_basis'],pool_count=len(codes),scan_requested=len(codes),not_scanned=0,complete=len(complete),errors=len(errors),b1_candidates=len(b1),abc_auxiliary_counts={s:len(v) for s,v in auxiliary.items()},stale_excluded=len(stale),b1_top10=[dict(code=r['ts_code'],name=r['name'],score=r['score']['score']) for r in b1[:10]],elapsed_seconds=time.monotonic()-started,rss_peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,network_calls=0,sqlite_connections=0,source_modified=False,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,abc_B_usage='DIAGNOSTIC_ONLY',known_qfq_input_unavailable_at_D22=True)
        save(out/'RESULT.json',summary);save(out/'ERRORS.json',errors)
        save(out/'ARTIFACT_MANIFEST.json',dict(files={str(p):sha(p) for p in out.iterdir() if p.is_file() and p.name!='ARTIFACT_MANIFEST.json'}))
        print(json.dumps(summary,ensure_ascii=False),flush=True)
        terminal=register(cp,'TERMINAL','ZGE_LOCAL_TERMINAL',[out/'RESULT.json',out/'ARTIFACT_MANIFEST.json'],summary,decision='DIRECTION_ONLY' if not errors else 'CANNOT_CONFIRM')
        save(out/'REGISTRY_TERMINAL.json',terminal)
    except BaseException as exc:
        save(out/'FAILURE.json',dict(type=type(exc).__name__,error=str(exc)))
        register(cp,'TERMINAL','ZGE_LOCAL_FAILED',[out/'FAILURE.json'],decision='CANNOT_CONFIRM');raise

if __name__=='__main__': main()
