import json
import gzip
import hashlib
from pathlib import Path

import pytest

from ops import bootstrap_stock_event_history as owner
from ops import run_retained_history_batches as batch


def _write(path,value):return owner.save(path,value)


def _fixture(tmp_path):
    src=tmp_path/'producer.py';src.write_text('projection')
    producer=owner.ref(src)
    calendar=_write(tmp_path/'calendar.json',{'historical_PIT':False})
    inputs={}
    for name in ('old','new','other'):
        path=tmp_path/(name+'.gz');path.write_bytes(b'old' if name in ('old','new') else b'other')
        inputs[name]={**owner.ref(path),'bytes':len(path.read_bytes()),'decoded_bytes':20,'encoding':'gzip'}
    asset=tmp_path/'history.gz';asset.write_bytes(b'existing history');asset_ref=owner.ref(asset)
    identity={'source_date':'2026-10-30','source_generation':'a'*64,'input_sha256':'b'*64,
        'candidate_generation':'c'*64,'candidate_input_sha256':'d'*64,
        'paired_receipt':{'path':'/fixture/receipt','sha256':'e'*64},'pair_sha256':{'selector':'f'*64}}
    def stock(symbol,history_input,history=None):
        value={'symbol':symbol,'candidate_generation':identity['candidate_generation'],
            'candidate_input_sha256':identity['candidate_input_sha256'],'paired_receipt':identity['paired_receipt'],
            'history_input':history_input,'details':{'history':history or {'status':'UNKNOWN'}},**owner.FLAGS}
        return _write(tmp_path/(symbol+'-'+Path(history_input['path']).stem+'.json'),value)
    old_history={'status':'READY','asset':asset_ref,'candidate_generation':identity['candidate_generation']}
    old_binding=stock('000001.SZ',inputs['old'],old_history)
    new_binding=stock('000001.SZ',inputs['new'])
    other_binding=stock('600000.SH',inputs['other'])
    prior={'schema':'v4.workbench.generic_single_index.v1',**identity,**owner.FLAGS,
        'symbols':{'000001.SZ':{'status':'READY','binding':old_binding}}}
    current={'schema':'v4.workbench.generic_single_index.v1',**identity,**owner.FLAGS,
        'projection_producer':producer,'symbols':{'000001.SZ':{'status':'READY','binding':new_binding},
        '600000.SH':{'status':'READY','binding':other_binding},'688496.SH':{'status':'UNKNOWN','reason':'SOURCE_GAP'}}}
    prior_ref=_write(tmp_path/'prior.json',prior);index_ref=_write(tmp_path/'index.json',current)
    return index_ref,prior_ref,calendar,inputs


def test_plan_reuses_identical_history_and_retains_unknown(tmp_path):
    index,prior,calendar,_=_fixture(tmp_path)
    _,states,jobs=batch.plan(index,prior,calendar,tmp_path/'out',expected_owner_sha256=owner.sha(owner.__file__))
    assert states['000001.SZ']['status']=='REUSED_EXISTING_HISTORY'
    assert states['688496.SH']=={'status':'UNKNOWN','reason':'SOURCE_GAP'}
    assert [x['symbol'] for x in jobs]==['600000.SH']


def test_plan_reuses_exact_checkpoint_and_stops_on_saved_failure(tmp_path):
    index,prior,calendar,_=_fixture(tmp_path);out=tmp_path/'out';owner_sha=owner.sha(owner.__file__)
    _,_,jobs=batch.plan(index,prior,calendar,out,expected_owner_sha256=owner_sha);job=jobs[0]
    shard=_write(tmp_path/'shard.json',{'symbol':job['symbol'],'history_input':job['key']['history_input'],
        'projection_binding':job['key']['binding'],'market_calendar':calendar,
        'paired_receipt':job['key']['paired_receipt'],'producer_sha256':owner_sha,
        'projection_index':job['source_index']})
    _write(Path(job['checkpoint']),{'key':job['key'],'shard':shard})
    _,states,jobs=batch.plan(index,prior,calendar,out,expected_owner_sha256=owner_sha)
    assert not jobs and states['600000.SH']['status']=='REUSED_CHECKPOINT'
    Path(job['checkpoint']).unlink()
    _write(Path(job['failure']),{'key':job['key'],'error':'RETAINED_FAILURE'})
    _,states,jobs=batch.plan(index,prior,calendar,out,expected_owner_sha256=owner_sha)
    assert not jobs and states['600000.SH']['status']=='FAILED'


def test_plan_keeps_changed_existing_history_unknown(tmp_path):
    index,prior,calendar,inputs=_fixture(tmp_path)
    current=owner.load(index);reference=current['symbols']['000001.SZ']['binding'];value=owner.load(reference)
    value['history_input']=inputs['other'];new_binding=_write(tmp_path/'changed.json',value)
    current['symbols']['000001.SZ']['binding']=new_binding;index=_write(tmp_path/'changed-index.json',current)
    _,states,_=batch.plan(index,prior,calendar,tmp_path/'out',expected_owner_sha256=owner.sha(owner.__file__))
    assert states['000001.SZ']=={'status':'UNKNOWN','reason':'EXISTING_HISTORY_INPUT_CHANGED'}


def test_compact_history_roundtrips_exact_owner_bytes_and_reuses_checkpoint(tmp_path,monkeypatch):
    index,prior,calendar,_=_fixture(tmp_path);out=tmp_path/'out';owner_sha=owner.sha(owner.__file__)
    _,_,jobs=batch.plan(index,prior,calendar,out,expected_owner_sha256=owner_sha);job=jobs[0]
    shard_value={'symbol':job['symbol'],'history_input':job['key']['history_input'],
        'projection_binding':job['key']['binding'],'market_calendar':calendar,
        'paired_receipt':job['key']['paired_receipt'],'producer_sha256':owner_sha,
        'projection_index':job['source_index'],'statistics':{'data':'same owner content'}}
    monkeypatch.setattr(owner,'build_retained_pair_history',lambda _i,_s,_c,root,**_k:
                        owner.save(root/'original.json',shard_value))
    result=batch._run_one({**job,'compact':True});raw=gzip.decompress(Path(result['path']).read_bytes())
    assert result['encoding']=='gzip' and result['decoded_bytes']==len(raw)
    assert result['decoded_sha256']==hashlib.sha256(raw).hexdigest() and owner.load(result)==shard_value
    assert not list((out/'temporary_history').iterdir())
    _,states,jobs=batch.plan(index,prior,calendar,out,expected_owner_sha256=owner_sha)
    assert not jobs and states['600000.SH']['status']=='REUSED_CHECKPOINT'


def test_compaction_failure_keeps_its_temporary_evidence(tmp_path,monkeypatch):
    index,prior,calendar,_=_fixture(tmp_path);out=tmp_path/'out'
    _,_,jobs=batch.plan(index,prior,calendar,out,expected_owner_sha256=owner.sha(owner.__file__))
    def fail(_i,_s,_c,root,**_k):
        (root/'diagnostic.txt').write_text('retained')
        raise ValueError('ORIGINAL_OWNER_FAILURE')
    monkeypatch.setattr(owner,'build_retained_pair_history',fail)
    with pytest.raises(ValueError,match='HISTORY_TEMPORARY_PRESERVED'):
        batch._run_one({**jobs[0],'compact':True})
    assert len(list((out/'temporary_history').glob('*/diagnostic.txt')))==1
