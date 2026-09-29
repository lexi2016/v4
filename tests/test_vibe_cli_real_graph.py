"""Actual CLI -> data owner -> original LangGraph -> exact writer -> reader.

Only provider raw responses and the final ChatOpenAI-compatible SDK are fixtures.
No graph, node, runtime, entry, serializer or writer is replaced. Missing real
LangGraph is a FAIL, not a skip. Kept separate from the dependency-light suite.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_vibe_assembly import config_fixture
from test_vibe_model_factory import SdkFixture
from vibe_ownership_fixtures import DATE,focus,extract_items


@pytest.mark.parametrize('verification,deep_calls',[(True,1),(False,2)])
def test_actual_cli_collect_graph_publish_and_duplicate(tmp_path,capsys,verification,deep_calls):
    from ops.run_research_review_generation import main
    from domains.daily_research_review import load_daily_research_review
    path,pin,code,tr,config=config_fixture(tmp_path)
    clients=[]
    class FinalSdk(SdkFixture):
        def __init__(self, *, is_deep, **kw):
            super().__init__(**kw);self.is_deep=is_deep;self.calls=0
        def invoke(self,prompt):
            self.calls+=1
            if not self.is_deep:
                return SimpleNamespace(content='[离线合成分析] '+'仅讨论固定原始响应样本，不是交易建议。'*20)
            value=focus(verification=verification) if self.calls==1 else {'items':extract_items()}
            return SimpleNamespace(content=json.dumps(value,ensure_ascii=False))
    def factory(**kw):
        result=FinalSdk(is_deep=bool(clients),**kw);clients.append(result);return result
    argv=['--date',DATE,'--config',str(path),'--config-sha256',pin,'--source-manifest-sha256',code]
    result=main(argv,transport=tr,client_factory=factory)
    output=json.loads(capsys.readouterr().out)
    assert result==0,output
    root=Path(config['state_root']);artifact=(root/'reviews'/f'{DATE}.json').read_bytes()
    payload=json.loads(artifact);lineage=payload['v4_generation']['source_provenance']
    assert lineage['graph']['implementation'].startswith('langgraph.')
    assert lineage['authority_receipt_independently_verified'] is True
    assert lineage['evidence_validation']['source_files_verified']==18
    assert lineage['assembly']['model_and_data_materialization_under_public_task_lock'] is True
    assert [c.calls for c in clients]==[5,deep_calls]
    assert lineage['llm_invoke_counts']=={'quick_invoke':5,'deep_invoke':deep_calls}
    assert payload['trade_date']==payload['target_date']==DATE
    assert payload['data_as_of']==config['data_as_of']
    env=load_daily_research_review(DATE,review_root=root/'reviews')
    assert env['status']=='READY'
    assert env['artifact_sha256']==output['artifact_sha256']==hashlib.sha256(artifact).hexdigest()
    before=dict(tr.calls)
    assert main(argv,transport=tr,client_factory=factory)==2
    capsys.readouterr()
    assert dict(tr.calls)==before and len(clients)==2 and [c.calls for c in clients]==[5,deep_calls]
    assert not (root/'reviews'/'latest.json').exists()
    (tmp_path/'cli_graph_evidence.json').write_text(json.dumps({'status':'PASS',
        'receipt':output,'provider_counts':lineage['snapshot']['upstream_provider_counts_reported'],
        'quick_calls':clients[0].calls,'deep_calls':clients[1].calls,
        'duplicate_exit_code':2,'synthetic_only':True},ensure_ascii=False,indent=2))
