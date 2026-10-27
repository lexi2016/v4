from datetime import datetime,timezone
import json
from pathlib import Path

import pytest
from infrastructure.runtime_graph.current import SCHEMA,atomic_json
from infrastructure.runtime_graph.event_collector import collect_events

FLAGS=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)


@pytest.mark.parametrize('binding',['correct','wrong_config','wrong_date','corrupt'])
def test_old_date_event_uses_exact_dated_snapshot_without_replacing_newer_global(tmp_path,binding):
    root=tmp_path/'runtime_graph/v4';inbox=root/'inbox';inbox.mkdir(parents=True)
    config={'graph_root':str(tmp_path),'inbox':str(inbox),'_sha256':'a'*64,'main':{'app_root':'exact'}}
    descriptors=[{'node_id':'main_task','owner':'MAIN','kind':'MAIN'}]
    snapshot=lambda date:dict(schema_version=SCHEMA,business_date=date,config_sha256='a'*64,authority_identity=config['main'],descriptors=descriptors,nodes=[{'node_id':'main_task','status':'OLD'}],**FLAGS)
    atomic_json(root/'snapshot.json',snapshot('20261028'));before=(root/'snapshot.json').read_bytes()
    dated=snapshot('20261027')
    if binding=='wrong_config':dated['config_sha256']='b'*64
    if binding=='wrong_date':dated['business_date']='20261026'
    atomic_json(root/'snapshot-20261027.json',dated)
    if binding=='corrupt':(root/'snapshot-20261027.json').write_text('{broken')
    event=dict(schema_version='v4.runtime_graph_hint.v1',owner='MAIN',node_id='main_task',business_date='20261027',phase='EXECUTOR_ENTERED',observed_at=datetime.now(timezone.utc).isoformat(),**FLAGS)
    atomic_json(inbox/'owned.json',event);calls=[]
    def get(url):
        calls.append(url)
        return dict(schema_version='v4.runtime_graph_authority.v1',business_date='20261027',authority_identity=config['main'],descriptors=descriptors,nodes=[{'node_id':'main_task','status':'PENDING'}],api_template_catalog_sha256='c'*64,**FLAGS)
    result=collect_events(config,get,quiet_seconds=0)
    assert result['status']=='COLLECTED' and len(calls)==1
    assert '&projection=compact' in calls[0]
    assert ('&node_ids=main_task' in calls[0])==(binding=='correct')
    assert (root/'snapshot.json').read_bytes()==before and not (inbox/'owned.json').exists()
    assert json.loads((root/'snapshot-20261027.json').read_bytes())['business_date']=='20261027'
