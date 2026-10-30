"""The normal producer uses accepted durable arithmetic; never touch live store."""
import copy
import json
from datetime import date,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from domains import research_daily_statistics as stats
from domains.research_event_case_cache import EventCaseCache
from ops.research_panel_daily_product import cached_daily_statistics


def test_daily_owner_exact_statistics_parity_repeats_append_revision_and_earlier_asof(tmp_path):
    dates=[(date(2026,1,1)+timedelta(days=i)).strftime('%Y%m%d') for i in range(310)]
    bars=[dict(trade_date=int(d),close=i+10) for i,d in enumerate(dates)]
    iso=lambda d:f'{d[:4]}-{d[4:6]}-{d[6:]}'
    context=SimpleNamespace(target=int(dates[300]),identity=dict(basis=dict(amount_basis='RAW_TURNOVER',price_basis='QFQ_ASOF',volume_basis='QFQ_EVENT_VOLUME',asof_date=dates[300])),reader_ref=dict(path='existing_reader',sha256='c'*64),config=dict(formula=dict(sha256='b'*64)))
    groups=[dict(group_id=g,event_dates=[iso(dates[250]),iso(dates[299])],rule_sha256='a'*64,source_identity=dict(generation='g',input='i',formula='b'*64,rule_sha256='a'*64,asof=iso(dates[300]),market='SZ',basis='QFQ_ASOF',pit_status='NONPIT')) for g in ('original','nav_smallk')]
    path=tmp_path/'accepted.sqlite3';EventCaseCache(path).close()
    first,full,counters=cached_daily_statistics(context,'001328.SZ',bars,list(map(int,dates)),groups,path)
    expected=stats.build_daily_event_statistics(close_rows=[dict(date=iso(str(b['trade_date'])),close=float(b['close'])) for b in bars],market_calendar=list(map(iso,dates)),asof=iso(dates[300]),event_groups=groups)
    assert first==expected and sum(r['return_evaluations'] for r in counters)>0
    with patch.object(stats,'_evaluate_event_return',side_effect=AssertionError('repeat arithmetic forbidden')):
        repeated,_,counts=cached_daily_statistics(context,'001328.SZ',bars,list(map(int,dates)),groups,path)
    assert repeated==first and all(r['return_evaluations']==0 for r in counts)
    # Advancing one day matures exactly one shared D+2 value; old values hit.
    later=copy.deepcopy(context);later.target=int(dates[301]);later_groups=copy.deepcopy(groups)
    for g in later_groups:g['source_identity']['asof']=iso(dates[301])
    _,_,counts=cached_daily_statistics(later,'001328.SZ',bars,list(map(int,dates)),later_groups,path)
    assert sum(r['return_evaluations'] for r in counts)==1  # second group reuses the same mathematical event/horizon value

    revised=copy.deepcopy(bars);revised[252]['close']=10.0
    _,_,counts=cached_daily_statistics(later,'001328.SZ',revised,list(map(int,dates)),later_groups,path)
    assert sum(r['return_evaluations'] for r in counts)==1
    early=copy.deepcopy(context);early.target=int(dates[251]);early_groups=copy.deepcopy(groups)
    for g in early_groups:g['source_identity']['asof']=iso(dates[251])
    _,full,_=cached_daily_statistics(early,'001328.SZ',bars,list(map(int,dates)),early_groups,path)
    assert all(c['status']=='not_matured' and c['return_pct'] is None for h in full['original'].values() for c in h['cases'])


def test_next_daily_owner_restores_accepted_labels_then_evaluates_only_current_day(tmp_path,monkeypatch):
    from ops import research_panel_daily_product as owner
    dates=[20261020,20261021,20261022,20261023,20261026,20261027,20261028,20261029,20261030]
    bars=[dict(trade_date=d,close='10') for d in dates]
    config=dict(formula=dict(sha256='b'*64));rule=owner.sha(Path(owner.__file__).resolve().parents[1]/'domains/research_daily_product.py')
    q=dict(status='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH',history_start_date=str(dates[0]))
    evaluations={str(d):dict(groups={g:'TRUE' if g=='original' else 'FALSE' for g in owner.GROUPS}) for d in dates[:-1]}
    cache=dict(rule_sha256=rule,rules_signature=owner.digest(config),evaluations=evaluations,prefix_sha256=owner.digest(bars[:-1]))
    cache_ref=owner.save(tmp_path/'accepted/history.json',cache)
    result_ref=owner.save(tmp_path/'accepted/result.json',dict(status='COMPLETE_DESCRIPTIVE_NONPIT',symbol='001328.SZ',history_cache=cache_ref,**owner.FLAGS))
    store=tmp_path/'accepted.sqlite3';EventCaseCache(store).close();monkeypatch.setenv('V4_RESEARCH_EVENT_CASE_CACHE',str(store))
    context=SimpleNamespace(root=tmp_path/'current',target=dates[-1],generation='c'*64,identity=dict(input_sha256='d'*64,basis=dict(amount_basis='RAW_TURNOVER',price_basis='QFQ_ASOF',volume_basis='QFQ_EVENT_VOLUME')),reader_ref=dict(path='reader',sha256='e'*64),config=config,label_results={'001328.SZ':result_ref},calendars={'SZ':dates},read=lambda s:(bars,'name'),qualify=lambda s:q)
    monkeypatch.setattr(owner,'source_inputs',lambda *a,**k:{})
    calls=[]
    def evaluate(**kwargs):
        calls.append(kwargs['asof']);return dict(groups={g:dict(status='TRUE' if g=='original' else 'FALSE') for g in owner.GROUPS})
    row,updated,path=owner.compute_stock(context,'001328.SZ',evaluate=evaluate)
    assert calls==[20261030] and len(updated['evaluations'])==9
    assert row['statistics']['groups'][0]['eligible_event_count']==9
    assert json.loads(Path(cache_ref['path']).read_text())==cache
    assert path.is_relative_to(context.root) and not path.exists()
