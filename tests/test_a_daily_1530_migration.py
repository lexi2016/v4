from pathlib import Path
from types import SimpleNamespace
import hashlib,json
import pytest
from contracts.runtime_tasks import DispatchRequest,DispatchMode
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry

def bound_receipt(tmp_path):
    selector=tmp_path/'selector.parquet';selector.write_bytes(b'exact selector bytes')
    backtest=tmp_path/'backtest.parquet';backtest.write_bytes(b'exact backtest bytes')
    sp=tmp_path/'selector.current';sp.write_text(str(selector))
    bp=tmp_path/'backtest.current';bp.write_text(str(backtest))
    sh=hashlib.sha256(selector.read_bytes()).hexdigest();bh=hashlib.sha256(backtest.read_bytes()).hexdigest()
    receipt={'schema_version':'v3.macos.research_panel_receipt.v1','lane':'A','target_date':'20261029','status':'PARTIAL','selector':str(selector),'backtest':str(backtest),'selector_sha256':sh,'backtest_sha256':bh,'sha256':hashlib.sha256(f'selector:{sh}\nbacktest:{bh}\n'.encode()).hexdigest(),'row_count':2,'accepted_target_date_file_count':2,'accepted_count':2,'quarantine_count':1,'target_count':3,'coverage_rate':2/3,'reconciliation':{'target_count':3,'accepted_count':2,'quarantine_count':1},'backtest_pointer_ready':True,'authority_status':'REBUILD_REQUIRED','production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    return receipt,sp,bp

@pytest.mark.parametrize('invalid',['none','date','bytes','pointer','safety','count','binding_missing'])
def test_migration_only_reuses_strict_bound_receipt(tmp_path,monkeypatch,invalid):
    receipt,sp,bp=bound_receipt(tmp_path)
    if invalid=='date':receipt['target_date']='20261028'
    if invalid=='bytes':Path(receipt['selector']).write_bytes(b'drift')
    if invalid=='pointer':sp.write_text(str(bp))
    if invalid=='safety':receipt['orders_sent']=True
    if invalid=='count':receipt['accepted_count']=0
    if invalid=='binding_missing':receipt.pop('backtest_sha256')
    (tmp_path/'a-20261029.json').write_text(json.dumps(receipt))
    for k,v in {'V4_RESEARCH_PANEL_RECEIPT_ROOT':tmp_path,'V4_RESEARCH_PANEL_A_SELECTOR_POINTER':sp,'V4_RESEARCH_PANEL_A_BACKTEST_POINTER':bp}.items():monkeypatch.setenv(k,str(v))
    calls=[]
    owner=SimpleNamespace(_active_workload_id='',_research_panel_daily=lambda *a,**kw:calls.append('provider') or {'status':'FAILED'})
    result=FixedExecutorRegistry._run_a_daily(owner,DispatchRequest('20261029','20261029','20261029','1530',DispatchMode.LIVE))
    if invalid=='none':
        assert not calls
        assert result['migration_reuse'] is True
        assert result['lane_status']=='PARTIAL_WITH_ROWS'
        assert result['provider_invoked'] is False
        assert result['natural_1530_verified'] is False
    else:assert calls==['provider']
