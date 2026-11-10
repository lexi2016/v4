from pathlib import Path
from types import SimpleNamespace
import pytest
from ops import repair_301314_admission as repair


def test_no_scoped_fact_keeps_original_admission_and_other_symbols_unchanged(monkeypatch):
    for key in ('V4_A_DAILY_301314_TYPED_FACT_PATH','V4_A_DAILY_301314_TYPED_FACT_SHA256','V4_A_DAILY_TYPED_END_FACT_PATH','V4_A_DAILY_TYPED_END_FACT_SHA256'):monkeypatch.delenv(key,raising=False)
    result=dict(status='UNKNOWN',reason='CURRENT_SYMBOL_HISTORY_END_MISMATCH')
    context=SimpleNamespace(target=repair.TARGET,footer={},receipt={},quarantine={},generation=repair.GENERATION,quarantine_ref={'path':'/q'},snapshot={'symbols':{}},helper=SimpleNamespace(verify_symbol_admission=lambda *_:result))
    assert repair.owner.SourceContext.qualify(context,repair.SYMBOL)is result
    monkeypatch.setenv('V4_A_DAILY_301314_TYPED_FACT_PATH','/invalid')
    assert repair.owner.SourceContext.qualify(context,'002731.SZ')is result
    with pytest.raises(ValueError,match='BINDING_INCOMPLETE'):repair.owner.SourceContext.qualify(context,repair.SYMBOL)


def test_original_rule_identity_resolves_actual_imported_module_with_injected_evaluator(tmp_path):
    from domains import research_daily_product as original_rules
    context=SimpleNamespace(root=tmp_path,target=repair.TARGET,generation=repair.GENERATION,
        read=lambda _: ([{'trade_date':repair.TARGET,'close':'1'}],None),qualify=lambda _:dict(status='UNKNOWN',reason='SOURCE_PENDING'),
        calendars={'SZ':[repair.TARGET]},config={'formula':{'sha256':'formula'}},label_results={},identity={'input_sha256':'input'})
    def evaluate(**kwargs):
        return dict(groups={g:dict(status='FALSE',reasons=[])for g in repair.owner.GROUPS})
    row,cache,path=repair.owner.compute_stock(context,repair.SYMBOL,evaluate=evaluate)
    expected=repair.owner.sha(Path(original_rules.__file__))
    assert cache['rule_sha256']==expected==repair.DOMAIN_DEPENDENCIES['research_daily_product.py']
    assert path==tmp_path/'history'/expected/repair.SYMBOL/'checkpoint.json'
