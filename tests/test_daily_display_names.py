import json
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest

from ops.research_panel_daily_product import SourceContext
from test_daily_completion_sse import _fixture_product_tree, _ref, _rebind_product


def test_owner_uses_latest_nonempty_bound_prefix_name():
    frame = pd.DataFrame([dict(trade_date=str(d), name=n, ts_code='002003.SZ', exchange='SZ', market_type='A_SHARE', open=1, high=2, low=1, close=2, volume=3)
                          for d,n in [(20261023,'伟星股份'),(20261028,''),(20261029,None)]])
    context = SimpleNamespace(target=20261029, panel='/fixture', reader=SimpleNamespace(load_selector_ready=lambda **kw:frame))
    bars,name=SourceContext.read(context,'002003.SZ')
    assert name=='伟星股份' and len(bars)==3 and bars[-1]['trade_date']==20261029


@pytest.mark.parametrize('drift',[None,'source_generation','numeric_manifest','selector'])
def test_display_binding_fills_list_and_detail_without_changing_numeric(tmp_path,drift):
    source,event,product=_fixture_product_tree(tmp_path)
    product['source_identity']['selector_artifact_sha256']='d'*64
    Path(event['artifact']['path']).write_text(json.dumps(product));_rebind_product(tmp_path,event)
    root=tmp_path/'daily_products/a_share';ip=root/'index.json';index=json.loads(ip.read_text())
    names=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,schema_version='v4.a_share.daily_display_names.v1',numeric_manifest=index['dates']['20261029'],data_date='20261029',source_generation=product['source_generation'],input_sha256=product['source_identity']['input_sha256'],selector={'path':'/pinned/selector','sha256':'d'*64},items={'600025.SH':dict(symbol='600025.SH',name='华能水电',source_date='20261023')})
    if drift: names[drift]={'sha256':'0'*64} if drift in {'numeric_manifest','selector'} else '0'*64
    path=root/'names.json';path.write_text(json.dumps(names));index['display_names']={'20261029':_ref(path)};ip.write_text(json.dumps(index))
    before=Path(event['artifact']['path']).read_bytes()
    if drift:
        with pytest.raises(ValueError,match='DISPLAY_NAMES_IDENTITY'):source.read_a_daily_product('20261029')
    else:
        assert source.read_a_daily_product('20261029')['rows'][0]['display_name']=='华能水电'
        detail=source.read_a_daily_product('20261029','600025.SH')['row']
        assert detail['display_name']=='华能水电' and detail['display_name_source']['source_date']=='20261023'
        assert 'display_name' not in source.read_a_daily_product('20261029',include_display_names=False)['rows'][0]
    assert Path(event['artifact']['path']).read_bytes()==before
