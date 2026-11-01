"""A short listing must remain UNKNOWN and not reuse stale rule checkpoints."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ops import research_panel_daily_product as product


def test_short_source_never_calls_formula_or_turns_false(tmp_path):
    bars=[{'trade_date':20261029,'open':'10','high':'11','low':'9','close':'10','vol':'100'},
          {'trade_date':20261030,'open':'10','high':'11','low':'9','close':'10','vol':'100'}]
    ctx=SimpleNamespace(root=tmp_path,target=20261030,calendars={'BJ':[20261029,20261030]},
        generation='a'*64,identity={'input_sha256':'b'*64},config={'formula':{'sha256':'c'*64}},
        read=lambda _: (bars,None),qualify=lambda _:{'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH',
                                                   'history_start_date':'20261029'})
    with patch.object(product,'source_inputs',side_effect=AssertionError('SHORT_FORMULA_SHOULD_NOT_RUN')):
        row,cache,_=product.compute_stock(ctx,'920201.BJ',history_dates=[20261029])
    assert {v['status'] for v in row['evaluation']['groups'].values()}=={'UNKNOWN'}
    assert all(v['groups'][name]=='UNKNOWN' for v in cache['evaluations'].values() for name in product.GROUPS)
    assert 'INSUFFICIENT_HISTORY_114' in row['evaluation']['input_coverage']['reasons']


def test_rule_change_invalidates_checkpoint_runkey():
    ctx=SimpleNamespace(identity={'input_sha256':'a'},config_ref={'sha256':'b'})
    first=product.daily_product_run_key(ctx,['920201.BJ'],[], 'c'*64)
    assert first==product.daily_product_run_key(ctx,['920201.BJ'],[], 'c'*64)
    assert first!=product.daily_product_run_key(ctx,['920201.BJ'],[], 'd'*64)
    first=product.daily_product_run_key(ctx,['920201.BJ'],[], 'c'*64,producer_sha256='e'*64)
    assert first!=product.daily_product_run_key(ctx,['920201.BJ'],[], 'c'*64,producer_sha256='f'*64)


def test_parallel_and_parent_use_same_rule_bound_checkpoint_namespace(tmp_path):
    from ops import research_daily_product_parallel as parallel
    ctx=SimpleNamespace(identity={'input_sha256':'a'},config_ref={'sha256':'b'},root=tmp_path,target=20261030)
    selected=['920201.BJ']
    rule=product.sha(Path(product.__file__).resolve().parents[1]/'domains/research_daily_product.py')
    expected=tmp_path/'checkpoints'/'20261030'/product.daily_product_run_key(ctx,selected,[],rule)
    assert parallel.checkpoint_parts(ctx,selected)==expected


def test_old_rule_cache_is_preserved_but_not_reused(tmp_path):
    previous={'rule_sha256':'a'*64,'rules_signature':product.digest({'rule':'same'}),
              'evaluations':{'20261029':{'groups':{'original':'FALSE'}}}}
    history=product.save(tmp_path/'previous.json',previous,immutable=True)
    result=product.save(tmp_path/'result.json',{'status':'COMPLETE_DESCRIPTIVE_NONPIT','symbol':'920201.BJ',
        'history_cache':history,**product.FLAGS},immutable=True)
    ctx=SimpleNamespace(config={'rule':'same'},label_results={'920201.BJ':result})
    fresh={'rule_sha256':'b'*64,'evaluations':{}}
    output=product.accepted_label_cache(ctx,'920201.BJ','b'*64,fresh)
    assert output['evaluations']=={} and output['prior_label_cache_not_reused']['result']==result
    assert json.loads(Path(history['path']).read_text())==previous
    same=product.accepted_label_cache(ctx,'920201.BJ','a'*64,{'evaluations':{}})
    assert same==previous


def test_source_hash_cache_rejects_same_size_restored_mtime_after_rewrite(tmp_path):
    path=tmp_path/'source.json';path.write_text('aa')
    context=object.__new__(product.SourceContext);context.hash_cache={}
    original=path.stat();context.cached_sha(path)
    path.write_text('bb');os.utime(path,ns=(original.st_atime_ns,original.st_mtime_ns))
    assert path.stat().st_size==original.st_size and path.stat().st_mtime_ns==original.st_mtime_ns
    assert path.stat().st_ctime_ns!=original.st_ctime_ns
    import pytest
    with pytest.raises(ValueError,match='DAILY_REFERENCE_CHANGED'):
        context.cached_sha(path)


def test_source_hash_cache_rejects_change_during_hash(tmp_path,monkeypatch):
    path=tmp_path/'source.json';path.write_text('aa')
    context=object.__new__(product.SourceContext);context.hash_cache={}
    original=product.sha
    def change_while_hashing(value):
        digest=original(value);Path(value).write_text('bb');return digest
    monkeypatch.setattr(product,'sha',change_while_hashing)
    import pytest
    with pytest.raises(ValueError,match='DAILY_REFERENCE_CHANGED_DURING_HASH'):
        context.cached_sha(path)


def test_source_context_rejects_panel_rewrite_with_restored_mtime(tmp_path):
    panel=tmp_path/'panel';panel.write_text('aa')
    pointer=tmp_path/'selector';pointer.write_text(str(panel))
    back=tmp_path/'backtest';back.write_text('unchanged')
    context=object.__new__(product.SourceContext)
    context.panel=panel;context.panel_stat=panel.stat();context.pointer=pointer;context.backpointer=back
    context.pointer_bytes=pointer.read_bytes();context.back_bytes=back.read_bytes()
    panel.write_text('bb');os.utime(panel,ns=(context.panel_stat.st_atime_ns,context.panel_stat.st_mtime_ns))
    import pytest
    with pytest.raises(ValueError,match='DAILY_GENERATION_CHANGED_DURING_PROJECTION'):
        context.unchanged()
