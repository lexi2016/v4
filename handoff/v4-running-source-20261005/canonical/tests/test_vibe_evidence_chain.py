"""Tamper the actual evidence bytes; formatted SHA strings alone never suffice."""
from dataclasses import replace
import hashlib
import json
import pytest
from domains.research_review_generation._owned_io import BoundaryError
from vibe_ownership_fixtures import DATE,make_runtime


@pytest.mark.parametrize('target',['receipt','source','raw','raw_date','source_date','receipt_date'])
def test_real_artifact_binding_before_model(tmp_path,target):
    runtime,payload=make_runtime(tmp_path)
    p=runtime.state_root
    # Fixtures must contain actual authority/source/raw records, not placeholder SHA.
    binding=payload.get('authority_receipt')
    assert isinstance(binding,dict),'fixture/producer must seal actual receipt'
    receipt=json.loads((p/binding['path']).read_bytes())
    if target.startswith('receipt'):path=p/binding['path']
    elif target.startswith('source'):path=p/payload['sources']['get_sentiment_data']['source_path']
    else:path=p/receipt['raw_refs'][0]['path']
    obj=json.loads(path.read_bytes());obj['target_date']='2026-09-10' if target.endswith('date') else DATE
    obj['unexpected_tamper']=True
    path.write_text(json.dumps(obj))
    with pytest.raises(BoundaryError):runtime.prepare(DATE,p/'reviews')
    assert not runtime.quick._client.prompts and not runtime.deep._client.prompts


def test_all_real_bindings_are_verified(tmp_path):
    runtime,_=make_runtime(tmp_path)
    proof=runtime.prepare(DATE,runtime.state_root/'reviews').provenance
    assert proof['authority_receipt_independently_verified'] is True
    assert proof['evidence_validation']['raw_files_verified']>=1
    assert proof['evidence_validation']['source_files_verified']==18


def test_client_label_cannot_impersonate_actual_provider(tmp_path):
    runtime,_=make_runtime(tmp_path)
    wrong=replace(runtime.quick_identity,model_id='other-model')
    with pytest.raises(BoundaryError):replace(runtime,quick_identity=wrong).prepare(DATE,runtime.state_root/'reviews')


def test_raw_date_is_checked_even_when_its_hash_is_rebound(tmp_path):
    from domains.research_review_generation._evidence import seal_snapshot,put_content
    from domains.research_review_generation._cache import encoded
    from domains.research_review_generation._owned_io import directory,records
    from infrastructure.owned_io import SafeRoot
    runtime,payload=make_runtime(tmp_path)
    io=SafeRoot(runtime.state_root)
    raw={'schema':'v4.vibe_raw.v1','review_target_date':DATE,
         'identity':{'session':'2026-09-10'},'result':{'kind':'SDK_RETURN_JSON','value':{}}}
    ref=put_content(io,'raw',encoded(raw));ref.update(session=DATE,kind='SDK_RETURN_JSON')
    with directory(runtime.state_root/'reflections') as fd:_,history,_=records(fd)
    with pytest.raises(BoundaryError,match='raw request date'):
        seal_snapshot(state_root=runtime.state_root,payload=payload,raw_refs=[ref],reflection_manifest=history,
                      implementation_sha256=runtime.implementation_manifest_sha256)


def test_unpinned_reflection_addition_is_rejected(tmp_path):
    runtime,_=make_runtime(tmp_path)
    (runtime.state_root/'reflections'/'2026-09-09.json').write_text('{"prediction_date":"2026-09-09"}')
    with pytest.raises(BoundaryError,match='reflection inventory'):
        runtime.prepare(DATE,runtime.state_root/'reviews')
