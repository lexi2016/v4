"""Frozen rule/source parity and publication; never collect or rerun formulas."""
import json
from pathlib import Path
from statistics import mean
import pytest
from ops.research_panel_top200 import frozen_function,read_csv,TRIAL


def test_original_feature_is_reused_with_boundary_missingness():
    expected=list(range(20260001,20260062))
    histories={'TEST.SH':[dict(trade_date=day,open=10+index,high=11+index,low=9+index,close=10+index,volume=1000+index)for index,day in enumerate(expected)]}
    feature=frozen_function('feature',dict(histories=histories,expected=expected,mean=mean,finite=lambda value:isinstance(value,(float,int))))
    assert feature('TEST.SH')['structure_status']=='DESCRIPTIVE_EXPLORATORY'
    assert feature('MISSING.SH')['structure']=='UNKNOWN'
    histories['TEST.SH'][-1]['low']=0
    assert feature('TEST.SH')['structure_status']=='INVALID_OHLCV'


def test_d30_materialized_candidate_preserves_all_frozen_top200_rank_values():
    path=Path('/Users/lexi/Desktop/学习/因子工厂/research/workbench_daily_chain_completion_20261031_r1/execution/top200/CANDIDATE.json')
    candidate=json.loads(path.read_bytes());frozen=read_csv(TRIAL/'top200.csv')
    assert [(row['symbol'],row['rank'],row['change_pct'],row['structure'])for row in candidate['top200']]==[(row['symbol'],row['rank'],row['change_pct'],row['structure'])for row in frozen]
    assert candidate['directory_count']==5575 and candidate['valid_quote_count']==5573 and candidate['missing_quote_count']==2
    assert candidate['top200_count']==200 and candidate['computation']['computed_structures']==0
    assert candidate['computation']['formula_engine_calls']==0
    assert all(row['visual_review_status']=='UNKNOWN_NOT_REVIEWED'for row in candidate['top200'])
    for axis in ['industry','theme']:
        old=read_csv(TRIAL/(axis+'_statistics.csv'))
        assert {(row['label'],row['top200_count'],row['members_with_valid_quote'])for row in candidate['statistics'][axis]}=={(row['label'],row['top200_count'],row['members_with_valid_quote'])for row in old}


def test_frozen_rule_refuses_changed_source(tmp_path):
    (tmp_path/'build_report.py').write_text('def feature(x):return True')
    with pytest.raises(ValueError,match='FROZEN_RULE_DRIFT'):frozen_function('feature',{},tmp_path)


def test_roster_comparison_uses_previous_exchange_session_and_unique_denominators():
    from ops.research_panel_top200 import roster_comparison
    root=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1/daily_products/a_share')
    index=json.loads((root/'index.json').read_bytes());top={row['symbol']for row in read_csv(TRIAL/'top200.csv')}
    expected={'20261029':(247,14),'20261030':(172,29)}
    for day,(count,hits)in expected.items():
        manifest=json.loads(Path(index['dates'][day]['path']).read_bytes());product=json.loads(Path(manifest['artifact']['path']).read_bytes())
        result=roster_comparison(product,top,day,'frozen descriptive',index['dates'][day])
        assert result['candidate_count']==count and result['hits']==hits and result['top_count']==200
        assert result['share_of_top_pct']==hits/200*100 and result['share_of_candidates_pct']==hits/count*100
        assert result['manual_visual_review']=='UNKNOWN_NOT_REVIEWED'


def test_final_top200_excludes_nontrading_rows_and_keeps_frozen_200_rank_and_structure():
    base=Path('/Users/lexi/Desktop/学习/因子工厂/research/workbench_daily_chain_completion_20261031_r1/execution/top200')
    if not (base/'CANDIDATE_R3.json').exists():pytest.skip('Frozen Mac final source not present')
    old=json.loads((base/'CANDIDATE_R2.json').read_bytes());value=json.loads((base/'CANDIDATE_R3.json').read_bytes())
    assert value['positive_price_record_count']==5573 and value['valid_daily_gain_rank_record_count']==5569
    assert value['missing_quote_count']==2 and value['excluded_nontrading_or_invalid_bar_count']==4
    assert [(r['symbol'],r['rank'],r['change_pct'],r['structure'])for r in value['top200']]==[(r['symbol'],r['rank'],r['change_pct'],r['structure'])for r in old['top200']]
    excluded={'002717.SZ','002827.SZ','301139.SZ','601326.SH','605258.SH','688121.SH'}
    for row in value['top200']:
        assert row['symbol'] not in excluded and row['amount_cny']>0 and row['volume_shares']>0
        assert 0<row['low']<=min(row['open'],row['close'])<=max(row['open'],row['close'])<=row['high']
    assert value['computation']['computed_structures']==0


def test_incremental_resume_retains_exact_original_contract_and_does_not_reprepare(monkeypatch,tmp_path):
    import ops.research_panel_top200 as continuation
    import ops.bootstrap_stock_event_history as adapter
    from types import SimpleNamespace
    from ops.research_panel_daily_product import save,reference,digest
    root=tmp_path/'root';out=tmp_path/'out';symbol='000035.SZ';identity={'generation':'g','input_sha256':'i'}
    bars=[{'trade_date':20261029,'close':'1'},{'trade_date':20261030,'close':'1'}]
    row=save(tmp_path/'row.json',dict(historical_coverage={'known_full_history':False,'missing':['bootstrap']},qualification={},symbol=symbol))
    cache=save(root/'history'/adapter.RULE/symbol/'checkpoint.json',dict(evaluations={}))
    source=save(tmp_path/'source.json',{})
    projection=save(tmp_path/'projection.json',dict(source_cache=source))
    charts=save(tmp_path/'charts.json',{'samples':{symbol:{'projection':projection,'html':source,'PNG':source}}})
    product=save(tmp_path/'product.json',dict(rows=[{'symbol':symbol}],row_refs={symbol:row},source_config=source))
    manifest=save(tmp_path/'manifest.json',{'artifact':product})
    index=save(root/'index.json',dict(dates={'20261030':manifest},original_charts={'20261030':{'manifest':charts}}))
    for key in ('TARGET','GENERATION','INPUT','DATA','DAILY','MAIN','SETTINGS'):monkeypatch.setattr(adapter,key,getattr(adapter,key))
    monkeypatch.setattr(adapter,'retained_sample',lambda *args:({},bars));monkeypatch.setattr(adapter,'projection_identity',lambda p:identity)
    monkeypatch.setattr(continuation,'_prior_generation_proofs',lambda *args:(_ for _ in ()).throw(AssertionError('RESUME_MUST_NOT_REPREPARE')))
    refs={key:source for key in ('source_config','receipt','snapshot','quarantine','reader')};refs.update(index=index,numeric_manifest=manifest,numeric_product=product,pointers=[source])
    contract=dict(source_identity=identity,config={'symbols':[symbol]},code=[source],refs=refs)
    save(out/'CONTRACT.json',contract);immutable=save(out/('CONTRACT_'+digest(contract)+'.json'),contract,immutable=True)
    context=SimpleNamespace(target=20261030,generation='g',identity=identity,data_root=tmp_path)
    assert continuation.prepare_incremental_history(context,root,out)==immutable


def test_source_revision_refreshes_only_changed_structure_windows(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import ops.research_panel_top200 as continuation
    import ops.research_panel_qfq as owner
    from ops.research_panel_daily_product import save,reference
    old=tmp_path/'old.parquet';old.write_bytes(b'bound panel');new=tmp_path/'new.parquet';new.write_bytes(b'new panel')
    receipt=save(tmp_path/'candidate_receipt.json',dict(generation_id='old',candidates={'selector':str(old)},candidate_sha256={'selector':reference(old)['sha256']}))
    refs=[receipt,{**reference(old),'size':old.stat().st_size}]
    monkeypatch.setattr(owner,'panel_contract',lambda path:dict(generation_id='old'))
    before={'A.SH':[{'close':1}],'B.SH':[{'close':2}]};after={'A.SH':[{'close':1}],'B.SH':[{'close':3}]}
    monkeypatch.setattr(continuation,'structure_histories',lambda path,*args:before if path==old else after)
    calls=[];monkeypatch.setattr(continuation,'frozen_function',lambda *args:lambda symbol:(calls.append(symbol)or dict(structure='updated')))
    context=SimpleNamespace(generation='new',target=100,calendars={'SH':list(range(1,100))},panel=new)
    coverage=[dict(symbol='A.SH',structure='same'),dict(symbol='B.SH',structure='old')]
    changed,count=continuation.refresh_revised_trial_structures(context,coverage,{'A.SH':{},'B.SH':{}},SimpleNamespace(previous=99),refs,tmp_path)
    assert changed==['B.SH'] and count==1 and calls==['B.SH']
    assert coverage[0]['structure']=='same' and coverage[1]['structure']=='updated'

@pytest.fixture
def current_history_view_fixture(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from ops import research_panel_top200 as c
    from ops import research_panel_daily_product as p
    from ops import bootstrap_stock_event_history as a
    from ops import sync_stock_history_completion as sync
    root=tmp_path/'root';out=tmp_path/'stage';identity=dict(generation='a'*64,input_sha256='b'*64,asof=20261030,basis={'price_basis':'QFQ_ASOF'})
    config={};config_ref=p.save(tmp_path/'config.json',config);bars=[dict(trade_date=d,open='1.0',high='1.0',low='1.0',close='1.0',vol='100.0')for d in [20261029,20261030]]
    statuses={g:'TRUE'if g=='original'else'FALSE'for g in c.GROUPS};rows={};charts={}
    for symbol in ['000001.SZ','000002.SZ']:
        row=dict(symbol=symbol,data_date='20261030',evaluation={'groups':{g:{'status':v}for g,v in statuses.items()}},historical_coverage=dict(known_full_history=True,missing=[],evaluated_count=2))
        rows[symbol]=p.save(root/'rows'/(symbol+'.json'),row)
        cache=dict(rule_sha256=a.RULE,rules_signature=p.digest(config),source_identity=identity,prefix_sha256=p.digest(bars),evaluations={str(d):dict(groups=statuses,source_identity=identity)for d in [20261029,20261030]})
        p.save(root/'history'/a.RULE/symbol/'checkpoint.json',cache)
        source=p.save(root/'source'/(symbol+'.json'),{})
        projection=p.save(root/'projections'/(symbol+'.json'),dict(symbol=symbol,_bars=bars,source_cache=source,identity=identity))
        charts[symbol]={'projection':projection}
    product=p.save(root/'product.json',dict(data_date='20261030',source_identity=identity,source_generation=identity['generation'],source_config=config_ref,rows=[{'symbol':s,'groups':'original'}for s in rows],row_refs=rows))
    manifest=p.save(root/'manifest.json',dict(data_date='20261030',artifact=product,source_generation=identity['generation']))
    chart=p.save(root/'charts.json',dict(samples=charts));oldsync=dict(numeric_manifest={'path':'old','sha256':'0'*64},source_generation='old',input_sha256='old',stock_results={},contract=None,bootstrap_symbols=[])
    p.save(root/'index.json',dict(dates={'20261030':manifest},history_sync={'20261030':oldsync},original_charts={'20261030':{'manifest':chart}}))
    p.save(root/'events/latest.json',dict(data_date='20261030',manifest=manifest,artifact=product,source_generation=identity['generation']))
    lock=tmp_path/'A_LONG.lock';lock.touch();monkeypatch.setattr(sync,'DEFAULT_OWNER_LOCK',lock)
    monkeypatch.setattr(a,'retained_sample',lambda projection,source:({},projection['_bars']));monkeypatch.setattr(a,'projection_identity',lambda projection:projection['identity'])
    context=SimpleNamespace(target=20261030,generation=identity['generation'],identity=identity,config=config,config_ref=config_ref,calendars={'SZ':[20261029,20261030]},unchanged=lambda:None)
    return c,p,sync,context,root,out


def test_current_history_view_real_publisher_private_and_repeat_noop(current_history_view_fixture,monkeypatch):
    c,p,sync,context,root,out=current_history_view_fixture
    monkeypatch.setattr(p,'compute_stock',lambda *a,**k:pytest.fail('Metadata view must not evaluate labels'))
    plan=c.prepare_current_history_view(context,root,out);assert plan['status']=='PREPARED_CURRENT_HISTORY_VIEW'
    receipt=sync.publish(plan);assert receipt['status']=='PUBLISHED_HISTORY_SYNC'
    index=json.loads((root/'index.json').read_bytes());view=index['history_sync']['20261030'];assert view['status']=='COMPLETE'and view['reuse_status']=='REUSED_NO_COMPUTE';assert view['candidate_symbols']==view['completed_symbols']==['000001.SZ','000002.SZ']
    before=(root/'index.json').read_bytes();again=c.prepare_current_history_view(context,root,out/'again');assert again['status']=='NO_NEW_COMPLETION';assert (root/'index.json').read_bytes()==before


@pytest.mark.parametrize('mutation',['source','prefix','labels','history_only','incomplete'])
def test_current_history_view_rejects_mixed_source_or_incomplete_cache(current_history_view_fixture,mutation):
    import copy
    from ops import bootstrap_stock_event_history as a
    c,p,_,context,root,out=current_history_view_fixture
    if mutation=='source':context.identity={**context.identity,'input_sha256':'c'*64}
    elif mutation=='history_only':
        index=json.loads((root/'index.json').read_bytes());index['dates']['20261029']=index['dates']['20261030'];p.save(root/'index.json',index);context.target=20261029
    elif mutation=='prefix':
        index=json.loads((root/'index.json').read_bytes());chart=c.load(index['original_charts']['20261030']['manifest']);ref=chart['samples']['000001.SZ']['projection'];projection=c.load(ref);projection['_bars'][0]['close']='2.0';chart['samples']['000001.SZ']['projection']=p.save(Path(ref['path']),projection);index['original_charts']['20261030']['manifest']=p.save(root/'changed_chart.json',chart);p.save(root/'index.json',index)
    elif mutation=='labels':
        path=root/'history'/a.RULE/'000001.SZ/checkpoint.json';cache=json.loads(path.read_bytes());cache['evaluations']['20261030']['groups']['original']='FALSE';p.save(path,cache)
    elif mutation=='incomplete':
        path=root/'rows/000001.SZ.json';row=json.loads(path.read_bytes());row['historical_coverage']['known_full_history']=False;new=p.save(path,row);manifest=c.load(json.loads((root/'index.json').read_bytes())['dates']['20261030']);product=c.load(manifest['artifact']);product['row_refs']['000001.SZ']=new;manifest['artifact']=p.save(root/'product.json',product);index=json.loads((root/'index.json').read_bytes());index['dates']['20261030']=p.save(root/'manifest.json',manifest);p.save(root/'index.json',index)
    before=(root/'index.json').read_bytes()
    with pytest.raises(ValueError):c.prepare_current_history_view(context,root,out)
    assert (root/'index.json').read_bytes()==before

@pytest.fixture
def exact_metadata_publication_fixture(tmp_path,monkeypatch):
    from ops import research_panel_top200 as c
    from ops import research_panel_daily_product as p
    from ops import sync_stock_history_completion as sync
    root=tmp_path/'root';stage=tmp_path/'stage';root.mkdir();lock=tmp_path/'A_LONG.lock';lock.touch()
    index=p.save(root/'index.json',{'before':True});event=p.save(root/'events/latest.json',{'data_date':'20261030','before':True})
    cache=p.save(root/'cache.json',{'before':True});candidate=p.save(stage/'candidate_cache.json',{'after':True})
    oldcache=p.save(stage/'oldcache.json',{'before':True});stat=lock.stat()
    plan=dict(status='PREPARED_EXACT_METADATA_ROW',expected_index=index,expected_event=event,staged_index=p.save(stage/'index.json',{'after':True}),staged_event=p.save(stage/'event.json',{'data_date':'20261030','after':True}),immutable_files={},completed=['002731.SZ'],owner_publisher=p.reference(Path(p.__file__)),shared_owner_lock=dict(path=str(lock),device=stat.st_dev,inode=stat.st_ino),target_root=str(root),stage=str(stage),cache_path=cache['path'],expected_cache=cache,candidate_cache=candidate,previous_cache=oldcache)
    monkeypatch.setattr(c,'prepare_exact_metadata_row',lambda *args:plan)
    return c,p,root,stage,plan


def test_exact_metadata_row_real_private_publisher_keeps_cache_and_index_consistent(exact_metadata_publication_fixture):
    c,p,root,stage,plan=exact_metadata_publication_fixture
    result=c.publish_exact_metadata_row(None,root,stage,{'prepared':'result'})
    assert result['status']=='PUBLISHED_EXACT_METADATA_ROW'
    assert json.loads((root/'index.json').read_bytes())=={'after':True}
    assert json.loads((root/'cache.json').read_bytes())=={'after':True}


def test_exact_metadata_row_cache_failure_rolls_back_real_private_index_event(exact_metadata_publication_fixture,monkeypatch):
    c,p,root,stage,plan=exact_metadata_publication_fixture
    before={name:(root/name).read_bytes()for name in ['index.json','events/latest.json','cache.json']};save=p.save
    def fail_cache(path,*args,**kwargs):
        if Path(path)==root/'cache.json':raise OSError('INJECTED_CACHE_SAVE_FAILURE')
        return save(path,*args,**kwargs)
    monkeypatch.setattr(p,'save',fail_cache)
    with pytest.raises(OSError,match='INJECTED_CACHE_SAVE_FAILURE'):c.publish_exact_metadata_row(None,root,stage,{'prepared':'result'})
    assert {name:(root/name).read_bytes()for name in before}==before


def test_exact_metadata_row_cache_cas_and_noop_do_not_publish(exact_metadata_publication_fixture,monkeypatch):
    c,p,root,stage,plan=exact_metadata_publication_fixture
    p.save(root/'cache.json',{'unexpected':True});before=(root/'index.json').read_bytes()
    with pytest.raises(ValueError,match='CACHE_CAS_MOVED'):c.publish_exact_metadata_row(None,root,stage,{})
    assert (root/'index.json').read_bytes()==before
    monkeypatch.setattr(c,'prepare_exact_metadata_row',lambda *args:dict(status='NO_NEW_COMPLETION'))
    assert c.publish_exact_metadata_row(None,root,stage,{})['status']=='NO_NEW_COMPLETION'
    assert (root/'index.json').read_bytes()==before
