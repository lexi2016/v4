from copy import deepcopy
from types import SimpleNamespace
import pytest
from infrastructure.research_workbench_host import ResearchWorkbenchHost


def setup_host(monkeypatch,*,fail=False):
    native_rows=[dict(symbol=f'{i:06d}.SZ') for i in range(371)]
    model_rows=[dict(symbol=f'{600000+i:06d}.SH',v192_member=True) for i in range(19)]
    product=dict(data_date='20261109',source_generation='g',source_identity={'input_sha256':'i','selector_artifact_sha256':'s'},manifest={'path':'/numeric','sha256':'m'},rows=native_rows)
    result=dict(status='READY',rows=model_rows,count=19)
    monkeypatch.setattr('infrastructure.research_workbench_v192.project',lambda *a:deepcopy(result))
    calls=[]
    def read(scoped):
        calls.append(deepcopy(scoped))
        if fail:raise ValueError('QUOTE_REFERENCE_ACCEPTED_SOURCE_CONFLICT')
        return dict(status='BOUND_SOURCE_CLOSE',scope_count=len(scoped['rows']),rows={r['symbol']:{'price':10} for r in scoped['rows']})
    host=object.__new__(ResearchWorkbenchHost)
    host._view=lambda *a:product
    host.source=SimpleNamespace(read_a_daily_product=lambda *a,**kw:product)
    host._observation_date=lambda day:'2026-11-10'
    host.chart_views=lambda *a:{'projections':{'rows':[]}}
    host._quote_references=SimpleNamespace(read=read)
    return host,product,calls


def test_existing_quote_reader_receives_19_scope_with_same_identity_and_no_371_mutation(monkeypatch):
    host,product,calls=setup_host(monkeypatch);before=deepcopy(product)
    result=host.v192_group('2026-11-09','g')
    assert len(calls)==1 and len(calls[0]['rows'])==19
    assert calls[0]['manifest']==product['manifest']
    assert calls[0]['source_identity']==product['source_identity']
    assert {r['symbol'] for r in calls[0]['rows']}=={r['symbol'] for r in result['rows']}
    assert product==before and len(product['rows'])==371
    assert result['source_close_reference']['scope_count']==19
    assert all(r['original_chart_status']=='NOT_MATERIALIZED' for r in result['rows'])


def test_quote_binding_failure_preserves_19_members_and_has_no_old_quote_rows(monkeypatch):
    host,product,calls=setup_host(monkeypatch,fail=True)
    result=host.v192_group('2026-11-09','g')
    assert result['count']==19 and len(result['rows'])==19
    assert result['source_close_reference']['status']=='CANNOT_CONFIRM'
    assert result['source_close_reference']['rows']=={}
    assert len(product['rows'])==371
