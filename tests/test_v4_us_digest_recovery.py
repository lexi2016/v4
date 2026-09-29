"""Public US producer/registry tests with HTTP transport-only fixtures."""
from __future__ import annotations

import importlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from infrastructure.scheduling.catalog import load_workload_catalog
from ops.run_scheduled_slot import ALL_SLOTS


def digest_module():
    assert importlib.util.find_spec('ops.us_market_digest') is not None, 'original US producer is not owned by V4'
    return importlib.import_module('ops.us_market_digest')


def test_natural_slots_reach_registered_original_producer():
    catalog = {w.workload_id: w for w in load_workload_catalog().workloads}
    assert 'us_market_digest' in catalog
    assert catalog['us_market_digest'].slots == ('0415', '0515', '2100', '2200')
    assert {'0415','0515','2100','2200'} <= set(ALL_SLOTS)
    from infrastructure.scheduling.executor_registry import ALLOWED_WORKLOAD_IDS
    assert 'us_market_digest' in ALLOWED_WORKLOAD_IDS


def test_shanghai_slot_binds_ny_prior_close_and_dst_not_due():
    module = digest_module()
    capture = module.resolve_capture_for_shanghai_slot('20260915', '0415')
    assert capture['us_session_date'] == '20260914'
    assert capture['capture_phase'] == 'POST_CLOSE'
    with pytest.raises(ValueError, match='US_CAPTURE_SLOT_NOT_DUE'):
        module.resolve_capture_for_shanghai_slot('20260915', '0515')
    certified = module.us_market_day_certification('20260914')
    assert certified['status'] == 'VERIFIED'
    assert certified['reason'] == 'OPEN_FULL_DAY'
    assert certified['close_at'].startswith('2026-09-14T16:00:00-04:00')
    uncovered = module.us_market_day_certification('20270104')
    assert uncovered == {
        'status': 'CANNOT_CONFIRM',
        'reason': 'US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE',
    }
    capture = module.resolve_capture_for_shanghai_slot('20260115', '0515')
    assert capture['us_session_date'] == '20260114'


def transport_clock(monkeypatch, *, stamp='2026-09-14T16:15:00-04:00', quote_date='20260914'):
    module = digest_module()
    from infrastructure.http_transport import ProxyAwareHTTPTransport, FetchResult
    from hashlib import sha256
    calls = []
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromisoformat(stamp).astimezone(tz) if tz else cls.fromisoformat(stamp).replace(tzinfo=None)
    monkeypatch.setattr(module, 'datetime', Clock)
    def fetch(self, url, *, timeout=None, **kwargs):
        calls.append(url)
        if 'qt.gtimg.cn' in url:
            symbols = list(dict.fromkeys(s for group in module.GLOBAL_INDUSTRY_PROXY_MAP for s in group['proxy_symbols']))
            records = []
            for symbol in symbols:
                fields = ['']*31
                fields[1:5] = [symbol,symbol,'110','100']
                fields[30] = quote_date+'160000'
                records.append('v_us'+symbol+'="'+'~'.join(fields)+'";')
            body = ''.join(records).encode()
        else:
            key=sha256(url.encode()).hexdigest()[:12]
            body=(f'<rss><channel><item><title>美股公司季度业绩观察{key}</title>'
                  f'<link>https://example.test/news/{key}</link>'
                  '<pubDate>Mon, 14 Sep 2026 20:00:00 GMT</pubDate>'
                  '<source>研究测试</source></item></channel></rss>').encode()
        return FetchResult(body, dict(status='READY', source='SYNTHETIC_TRANSPORT',
                        source_url=url, response_sha256=sha256(body).hexdigest(),
                        production_allowed=False,buy_gate_updated=False,orders_sent=False))
    monkeypatch.setattr(ProxyAwareHTTPTransport, 'fetch', fetch)
    return module, calls


def registry_for(tmp_path, monkeypatch, **clock_kwargs):
    import subprocess, contextlib, io
    from contracts.runtime_tasks import DispatchRequest, DispatchMode
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    module, calls=transport_clock(monkeypatch, **clock_kwargs)
    invoked=[]
    def process(command, *, cwd, timeout_seconds, env):
        assert command[1:3] == ['-m','ops.us_market_digest']
        invoked.append(command)
        out, err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc=module.main(command[3:])
        return subprocess.CompletedProcess(command,rc,out.getvalue(),err.getvalue())
    root=Path(__file__).resolve().parents[1]
    registry=FixedExecutorRegistry(data_root=tmp_path/'data',repo_root=root,runner=process)
    request=DispatchRequest(scheduled_date='20260915', business_date='20260915',
              target_date='20260915',slot='0415',mode=DispatchMode.LIVE)
    workload=next(w for w in load_workload_catalog().workloads if w.workload_id=='us_market_digest')
    return registry,request,workload,module,calls,invoked


def test_actual_registry_public_cli_to_verified_33_symbol_snapshot_and_reuse(tmp_path, monkeypatch):
    from infrastructure.research_peripheral_store import ResearchPeripheralStore
    registry,request,workload,module,calls,commands=registry_for(tmp_path,monkeypatch)
    result=registry(workload,request)
    assert result['status']=='SUCCEEDED' and result['receipt_verified'] is True,result
    assert result['us_session_date']=='20260914'
    payload=ResearchPeripheralStore(tmp_path/'data').read_exact('20260914','external_finance')
    snapshot=payload['market_snapshot']
    assert snapshot['status']=='READY',snapshot
    assert len(module.GLOBAL_INDUSTRY_PROXY_MAP)==24
    assert len({s for g in module.GLOBAL_INDUSTRY_PROXY_MAP for s in g['proxy_symbols']})==33
    assert len(calls)==6,calls
    first=result['payload_sha256']
    assert registry(workload,request)['payload_sha256']==first
    assert len(calls)==6
    assert len(commands)==2
    assert all(payload[k] is False for k in ('production_allowed','buy_gate_updated','orders_sent'))
    assert result['market_day_status']=='VERIFIED'
    assert result['cannot_confirm']==[]


def test_dispatcher_reports_uncovered_us_calendar_year_without_running_producer(tmp_path, monkeypatch):
    from contracts.runtime_tasks import DispatchRequest, DispatchMode
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError

    registry,_,workload,module,calls,commands=registry_for(tmp_path,monkeypatch)
    request=DispatchRequest(scheduled_date='20270105', business_date='20270105',
        target_date='20270105',slot='0515',mode=DispatchMode.LIVE)
    with pytest.raises(WorkloadExecutionError) as error:
        registry(workload,request)
    assert error.value.result['market_day_status']=='CANNOT_CONFIRM'
    assert error.value.result['market_day_reason']=='US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE'
    assert calls==[] and commands==[]
    assert not (tmp_path/'data/research/peripherals/20270104/external_finance.json').exists()


def test_us_wrong_provider_session_refuses_ready(tmp_path, monkeypatch):
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError
    registry,request,workload,module,calls,_=registry_for(tmp_path,monkeypatch,quote_date='20260911')
    with pytest.raises(WorkloadExecutionError) as error:
        registry(workload,request)
    assert error.value.result['status']=='FAILED'
    assert len(calls)==6


def test_us_natural_late_request_does_not_fetch_or_publish(tmp_path,monkeypatch):
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError
    registry,request,workload,module,calls,_=registry_for(tmp_path,monkeypatch,stamp='2026-09-14T17:00:00-04:00')
    with pytest.raises(WorkloadExecutionError):
        registry(workload,request)
    assert calls==[]
    assert not (tmp_path/'data/research/peripherals/20260914/external_finance.json').exists()


def test_us_controlled_late_mode_reuses_only_its_own_session(tmp_path,monkeypatch,capsys):
    module,calls=transport_clock(monkeypatch,stamp='2026-09-14T17:00:00-04:00')
    args=['--data-root',str(tmp_path/'data'),'--trade-date','20260914',
          '--capture-phase','POST_CLOSE','--allow-late-post-close']
    rc=module.main(args); result=json.loads(capsys.readouterr().out)
    assert rc==0,result
    assert result['late'] is True and result['capture_mode']=='CONTROLLED_LATE_POST_CLOSE'
    before=len(calls)
    assert module.main(args)==0
    capsys.readouterr()
    assert len(calls)==before==6
    assert module.main([*args[:3],'20260911',*args[4:]])==2
    capsys.readouterr()
    assert len(calls)==before


def bind_release(tmp_path,monkeypatch):
    import hashlib
    from infrastructure.scheduling.dispatcher import _RUNTIME_IDENTITY_FILES
    root=Path(__file__).resolve().parents[1]
    entries=[dict(path=p,kind='file',size=(root/p).stat().st_size,
                  sha256=hashlib.sha256((root/p).read_bytes()).hexdigest()) for p in _RUNTIME_IDENTITY_FILES]
    canonical=lambda value: json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    raw=canonical(dict(schema_version='v4.release_candidate.v1',
                       candidate=dict(app_root=str(root),release_id='US_ISOLATED_TEST'),
                       application_inventory=dict(entries=entries,entry_count=len(entries),
                                                  aggregate_sha256=hashlib.sha256(canonical(entries)).hexdigest())))
    path=tmp_path/'release-manifest.json'; path.write_bytes(raw)
    for key,value in dict(V35_APP_ROOT=str(root),V35_RELEASE_ID='US_ISOLATED_TEST',
                           V35_RELEASE_MANIFEST_PATH=str(path),
                           V35_RELEASE_MANIFEST_SHA256=hashlib.sha256(raw).hexdigest()).items():
        monkeypatch.setenv(key,value)


def test_actual_dispatcher_registry_cli_owned_artifact_and_ledger(tmp_path,monkeypatch):
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    registry,request,workload,module,calls,commands=registry_for(tmp_path,monkeypatch)
    bind_release(tmp_path,monkeypatch)
    ledger=ExecutionLedger(tmp_path/'ledger')
    result=dispatch_due(request,load_workload_catalog(),registry,ledger=ledger,dry_run=False)
    assert result.status=='SUCCEEDED',result
    assert result.started_workload_ids==('us_market_digest',)
    assert result.release_id=='US_ISOLATED_TEST'
    receipt=ledger.read_receipt(result.receipt_path) if hasattr(ledger,'read_receipt') else json.loads((tmp_path/'ledger'/result.receipt_path).read_text())
    assert receipt['workload_results'][0]['receipt_verified'] is True
    repeated=dispatch_due(request,load_workload_catalog(),registry,ledger=ledger,dry_run=False)
    assert repeated.status == 'CONCURRENCY_SKIPPED',repeated
    assert len(calls)==6 and len(commands)==1


def test_preopen_and_inactive_dst_slots_do_not_fetch_close_quotes(tmp_path,monkeypatch):
    from dataclasses import replace
    registry,request,workload,module,calls,commands=registry_for(tmp_path,monkeypatch,stamp='2026-09-15T09:00:00-04:00')
    inactive=registry(workload,replace(request,slot='2200'))
    assert inactive['capture_status']=='NOT_DUE' and calls==[]
    request=replace(request,slot='2100')
    first=registry(workload,request)
    assert first['receipt_verified'] is True
    assert len(calls)==5 and not any('qt.gtimg.cn' in url for url in calls)
    assert registry(workload,request)['payload_sha256']==first['payload_sha256']
    assert len(calls)==5


def test_concurrent_public_materialization_has_one_capture_owner(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    module,calls=transport_clock(monkeypatch)
    def invoke(_):
        return module.materialize_us_market_phase(data_root=tmp_path/'data',trade_date='20260914',capture_phase='POST_CLOSE')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(invoke,range(4)))
    assert len({r['payload_sha256'] for r in results})==1
    assert len(calls)==6
    assert sum(r.get('reused',False) for r in results)==3


def test_registry_rejects_success_stdout_without_real_receipt(tmp_path,monkeypatch):
    import subprocess
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError
    registry,request,workload,module,calls,commands=registry_for(tmp_path,monkeypatch)
    registry._runner=lambda command,**kw: subprocess.CompletedProcess(command,0,json.dumps(dict(
        status='READY',trade_date='20260914',source='external_finance',
        payload_path='research/peripherals/20260914/external_finance.json',payload_sha256='a'*64)), '')
    with pytest.raises(WorkloadExecutionError) as error:
        registry(workload,request)
    assert error.value.result['reason']=='US_CAPTURE_EVIDENCE_INVALID'
    assert calls==[]


def test_scheduled_slot_cli_reaches_us_workload_and_repeat_is_no_fetch(tmp_path,monkeypatch,capsys):
    from ops import run_scheduled_slot as slot
    import infrastructure.scheduling.executor_registry as registry_module
    registry,request,workload,module,calls,commands=registry_for(tmp_path,monkeypatch)
    bind_release(tmp_path,monkeypatch)
    monkeypatch.setattr(registry_module,'_default_runner',registry._runner)
    args=['--slot','0415','--date','20260915','--data-root',str(tmp_path/'data'),
          '--ledger-root',str(tmp_path/'ledger')]
    assert slot.main(args)==0
    first=json.loads(capsys.readouterr().out)
    assert first['status']=='SUCCEEDED',first
    assert first['started_workload_ids']==['us_market_digest']
    assert slot.main(args)==0
    repeated=json.loads(capsys.readouterr().out)
    assert repeated['status']=='CONCURRENCY_SKIPPED',repeated
    assert len(calls)==6 and len(commands)==1
