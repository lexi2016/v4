import json,shutil
from pathlib import Path
import pytest
from test_integration import config,context,us,monthly,write
from test_native_pipeline import fixture
from v4.manager_workbench.inputs import source_bindings as bindings
from v4.manager_workbench.inputs.native import NativeAdapters
from v4.manager_workbench.inputs.validation import raw_sha
from v4.manager_workbench.contracts import Lane
CANONICAL=Path('/Users/lexi/Desktop/学习/v4_app')


def seed_copy(cfg):
    for rel in [bindings.SEED_RELATIVE,bindings.REGISTRY_RELATIVE]:
        dst=cfg.relation_root/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(CANONICAL/rel,dst)


def test_exact_reviewed_seed_joins_existing_cards_with_both_sources(tmp_path):
    cfg=config(tmp_path);us(cfg);seed_copy(cfg);c=context();c.source_sessions['us']='20261012'
    pin=bindings.us_mapping(cfg,c);cards=pin['relation_projection']['cards']
    assert len(cards)==5
    restored=[x for x in cards if x.get('research_priority')=='PRIORITY']
    assert {(x['us_symbol'],x['hk_symbol']) for x in restored}=={('LITE','HK.06166'),('COHR','HK.06166'),('AVGO','HK.06088'),('CIEN','HK.00763')}
    assert all(len(x['relation_source_refs'])==2 for x in restored)
    assert all(x['published_at']==x['publication_evidence'][0]['published_at'] and len(x['published_at'])==10 for x in restored)
    assert cards[0].get('research_priority') is None
    assert len(pin['checked_files'])==4
    c.scope_refs['owner_bindings']={'us_mapping':pin}
    (cfg.relation_root/bindings.SEED_RELATIVE).write_text('{}')
    with pytest.raises(ValueError,match='OWNER_BOUND_BYTES_CHANGED'):NativeAdapters(cfg).us_mapping(c)


@pytest.mark.parametrize('bad',['seed','registry','early'])
def test_seed_exact_sha_registry_and_cutoff_failclosed(tmp_path,bad):
    cfg=config(tmp_path);seed_copy(cfg);c=context()
    if bad=='early':c.cutoff='2026-10-05T16:18:15+00:00'
    else:(cfg.relation_root/(bindings.SEED_RELATIVE if bad=='seed' else bindings.REGISTRY_RELATIVE)).write_text('{}')
    with pytest.raises(ValueError):bindings.reviewed_seed(cfg,c)


def test_native_uses_card_priority_keeps_source_dates_and_quote_not_priority(tmp_path):
    cfg=config(tmp_path);us(cfg);seed_copy(cfg);monthly(cfg)
    rel='research/peripherals/20261012/external_finance.json'
    from v4.manager_workbench.inputs.source_bindings import US_SYMBOLS
    qsha=write(cfg.us_root,rel,dict(market_snapshot=dict(capture_session_date='20261012',captured_at='2026-10-13T05:00:00+08:00',quotes=[dict(symbol=s,change_pct=-1,priority='PRIORITY') for s in US_SYMBOLS])))
    write(cfg.us_root,'research/peripherals/manifest.json',{rel:qsha});write(cfg.us_root,'receipts/research/peripherals/20261012/external_finance.json',{'payload_sha256':qsha})
    a=NativeAdapters(cfg);c=a.prepare_context(context());b=a.load(Lane.US_MAPPING,c)
    nvda=next(x for x in b.records if x['us_symbol']=='NVDA');lite=next(x for x in b.records if x['us_symbol']=='LITE')
    assert nvda['relations'][0]['research_priority'] is None
    assert lite['relations'][0]['research_priority']=='PRIORITY'
    assert lite['relations'][0]['published_at']=='2026-09-03'
    assert all(x['source_status']=='CANNOT_CONFIRM' for x in b.records)
    assert len([r for r in b.evidence_refs if r.owner=='V4_REVIEWED_US_MAPPING_SEED'])==2


def test_oversold_per_bar_source_provenance_survives_without_unit_invention(tmp_path):
    import pandas as pd
    cfg=fixture(tmp_path,count=1);panel=cfg.shared_root/'panel.parquet';frame=pd.read_parquet(panel)
    frame['source']='tdx_vipdoc_71_day';frame['source_path']='original/day';frame['history_source_provider']='original-owner';frame['history_source_row_sha256']='a'*64
    frame.to_parquet(panel,index=False);m=json.loads((cfg.shared_root/'panel_manifest.json').read_text());m['panel_sha256']=raw_sha(panel.read_bytes())
    cfg.source_bindings['hk_panel']['20261012']['manifest_sha256']=write(cfg.shared_root,'panel_manifest.json',m)
    cfg.source_bindings['hk_panel']['20261012'].pop('volume_unit');cfg.source_bindings['hk_panel']['20261012'].pop('price_basis')
    a=NativeAdapters(cfg);c=a.prepare_context(context());b=a.load(Lane.OVERSOLD,c)
    for bar in [b.records[0]['previous_bar'],*b.records[0]['high_history60'],*b.records[0]['volume_history5']]:
        assert bar['source_metadata']['history_source_row_sha256']=='a'*64
        assert bar['source_metadata']['source']=='tdx_vipdoc_71_day'
        assert bar['volume_unit'] is None and bar['adjustment'] is None
