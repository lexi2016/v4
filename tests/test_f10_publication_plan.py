import json
from pathlib import Path
import pytest
from ops import f10_publish_existing_samples as op


def test_publication_rechecks_captured_baseline_before_writing(tmp_path,monkeypatch):
    root=tmp_path.resolve();main=root/'main';main.mkdir();(main/'release-manifest.json').write_text('{}')
    monkeypatch.setattr(op,'EVIDENCE',root);monkeypatch.setattr(op,'MAIN',main);monkeypatch.setattr(op,'assert_main_active',lambda:None)
    gate={'path':'gate','sha256':'a'*64};sample={'path':'sample','sha256':'b'*64};items={'002865.SZ':{},'301048.SZ':{}}
    index={'path':'index','sha256':'c'*64};event={'path':'event','sha256':'d'*64};attempt={'path':'attempt','sha256':'e'*64}
    data={'002865.SZ':{'symbol':'002865.SZ'},'301048.SZ':{'symbol':'301048.SZ'}}
    context=object();current=[context,root,gate,sample,{}, {'items':items},data,index,event,attempt]
    monkeypatch.setattr(op,'context_and_inputs',lambda:tuple(current));calls=[]
    monkeypatch.setattr(op.f10,'complete_f10',lambda *args,**kwargs:(calls.append('complete') or {'status':'COMPLETE','observed':2,'receipt':{'path':'f10','sha256':'f'*64}}))
    def publish(*args,**kwargs):calls.append(kwargs);return {'status':'PUBLISHED_F10_COMPLETION'}
    monkeypatch.setattr(op.f10,'publish_f10_completion',publish)
    plan={'schema':'v4.f10_two_sample_publication_plan.v1','status':'PREPARED_NOT_PUBLISHED','script_sha256':op.sha(op.__file__),
      'adapter_sha256':op.sha(op.f10.__file__),'main_manifest':op.ref(main/'release-manifest.json'),'symbols':list(op.SYMBOLS),
      'source_gate':gate,'sample_receipt':sample,'sample_items':items,'product_root':str(root),'expected_index':index,
      'expected_event':event,'upstream_attempt':attempt,'historical_PIT':False,**op.FLAGS}
    path=root/'plan.json';plan_ref=op.save(path,plan)
    current[8]={'path':'event','sha256':'0'*64}
    with pytest.raises(ValueError,match='F10_SAMPLE_PLAN_BASELINE_DRIFT'):
        op.publish(path,plan_ref['sha256'])
    assert calls==[]
    current[8]=event;op.publish(path,plan_ref['sha256'])
    assert calls==['complete',{'expected_index_sha256':index['sha256'],'expected_event_sha256':event['sha256']}]
