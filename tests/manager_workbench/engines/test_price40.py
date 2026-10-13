from copy import deepcopy
from test_oversold_inputs import ctx, rec, batch
from v4.manager_workbench.engines.oversold import run_oversold, PRICE40_RULES_VERSION
from v4.manager_workbench.config import WorkbenchConfig


def screen(close='60', volume='150', missing=False, legacy=False):
    context=ctx()
    if not legacy:context['rules_version']=PRICE40_RULES_VERSION
    record=rec();record['previous_bar'].update(close=close,volume=volume)
    if missing:record['high_history60'].pop()
    source=batch([record]);source['context']=context
    return run_oversold(context,source)['rows'][0]


def test_new_forty_percent_boundary_and_and_rule():
    row=screen();assert row['decision']=='SELECTED'
    assert row['metrics']['price_threshold']=='60.0'
    assert row['metrics']['price_ratio']=='0.6'
    assert row['metrics']['oversold_rules_version']==PRICE40_RULES_VERSION
    assert screen(close='60.000001')['decision']=='CONDITIONAL_WATCH'
    assert screen(volume='149.999999')['decision']=='CONDITIONAL_WATCH'
    assert screen(close='60.000001',volume='149.999999')['decision']=='NOT_SELECTED'
    assert screen(missing=True)['decision']=='UNASSESSED'


def test_legacy_context_preserves_eighty_percent_gate():
    row=screen(close='80',legacy=True);assert row['decision']=='SELECTED'
    assert row['metrics']['price_threshold']=='80.0'
    assert screen(close='80')['decision']=='CONDITIONAL_WATCH'


def test_seres_saved_values_and_default_new_identity(tmp_path):
    c=ctx();c['rules_version']=PRICE40_RULES_VERSION;r=rec()
    r['previous_bar'].update(close='38.92',volume='10826100')
    for bar in r['high_history60']:bar['high']='48.98'
    for bar in r['volume_history5']:bar['volume']='1657863.8'
    b=batch([r]);b['context']=c;before=deepcopy(r);out=run_oversold(c,b)['rows'][0]
    assert out['decision']=='CONDITIONAL_WATCH';assert out['metrics']['price_threshold']=='29.388'
    assert out['metrics']['price_pass'] is False and out['metrics']['volume_pass'] is True
    assert r==before
    assert WorkbenchConfig(state_root=tmp_path).rules_version==PRICE40_RULES_VERSION


def test_context_accepts_only_old_and_new_rules():
    import pytest
    from v4.manager_workbench.engines.common import validate_context
    context=ctx();assert validate_context(context)==context
    context['rules_version']=PRICE40_RULES_VERSION;assert validate_context(context)==context
    context['rules_version']='UNREVIEWED_RULE';
    with pytest.raises(ValueError,match='MWB_RULE_VERSION'):validate_context(context)
