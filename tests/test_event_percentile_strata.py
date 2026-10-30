import copy
from datetime import date, timedelta
import pytest
from domains.research_daily_statistics import stratify_event_cases_by_prefix_percentile as stratify


def rows(values):
    return [dict(date=(date(2020,1,1)+timedelta(days=i)).isoformat(),close=v) for i,v in enumerate(values)]


def cases(days,statuses):
    values=[dict(event_date=d,target_date=d,status=s,return_pct=1.0 if s=='positive' else -1.0 if s=='negative' else 0.0 if s=='flat' else None) for d,s in zip(days,statuses)]
    return {'d2':copy.deepcopy(values),'d5':copy.deepcopy(values)}


@pytest.mark.parametrize('lower,expected',[(49,1),(199,4),(249,4)])
def test_frozen_bucket_boundaries_and_inclusive_ties(lower,expected):
    data=rows([1.0]*lower+[10.0]*(249-lower)+[5.0]);day=data[-1]['date']
    result=stratify(close_rows=data,event_cases=cases([day],['positive']),asof=day)
    c=result['horizons']['d2']['conditional'];assert c['bucket']==expected and c['valid']==1 and c['positive_fraction']==1


def test_future_prices_do_not_change_any_event_percentile_and_inputs_not_mutated():
    data=rows(list(range(1,261)));cutoff=data[253]['date'];events=cases([data[249]['date'],cutoff],['positive','negative']);before=copy.deepcopy(events)
    a=stratify(close_rows=data,event_cases=events,asof=cutoff)
    changed=copy.deepcopy(data)
    for r in changed[254:]:r['close']=0.0001
    b=stratify(close_rows=changed,event_cases=events,asof=cutoff)
    assert a==b and events==before
    assert a['horizons']['d2']['cases'][0]['price_percentile']==1


def test_insufficient_prefix_is_unknown_not_zero_and_total_cases_remain():
    data=rows(list(range(1,251)));events=cases([data[248]['date'],data[249]['date']],['positive','not_matured'])
    result=stratify(close_rows=data,event_cases=events,asof=data[-1]['date']);h=result['horizons']['d2']
    assert len(h['cases'])==2 and h['cases'][0]['price_percentile'] is None
    assert h['conditional']['valid']==0 and h['conditional']['positive_fraction'] is None and h['conditional']['not_matured']==1


def test_flat_stays_in_valid_and_genuine_zero_success_is_zero():
    data=rows(list(range(1,254)));events=cases([r['date'] for r in data[-4:]],['negative','flat','not_matured','missing_price'])
    result=stratify(close_rows=data,event_cases=events,asof=data[-1]['date']);h=result['horizons']['d2']
    assert len(h['cases'])==4 and h['conditional']['valid']==2 and h['conditional']['positive_fraction']==0
    assert h['conditional']['not_matured']==1 and h['conditional']['missing_or_invalid_return']==1


def test_config_and_unmatched_horizon_event_set_fail_closed():
    data=rows(list(range(1,251)));day=data[-1]['date'];events=cases([day],['positive'])
    with pytest.raises(ValueError,match='frozen'):stratify(close_rows=data,event_cases=events,asof=day,lookback=20)
    events['d5']=[]
    with pytest.raises(ValueError,match='same accepted'):stratify(close_rows=data,event_cases=events,asof=day)
