"""Bounded provenance selection; no historical producer/import/data mutation."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json,hashlib
import pytest
from infrastructure import manager_input_attestation as m


def test_current_materializer_uses_current_owner_and_original_cutoff(tmp_path,monkeypatch):
    current=tmp_path/'current';stage=tmp_path/'stage';data=tmp_path/'data';(current/'ops').mkdir(parents=True);stage.mkdir();(current/'ops/run_hourly_research.py').write_bytes(b'fixture-current-source')
    (stage/'stage_center_tick_config.json').write_text(json.dumps({'research_historical_owner_bindings':[]}))
    record=data/'research/hourly/publication/live/20261028/2000.json';record.parent.mkdir(parents=True);record.write_text(json.dumps({'materializer_sha256':hashlib.sha256(b'fixture-current-source').hexdigest()}))
    monkeypatch.setattr(m,'trusted_research_owner',lambda *a:(current,tmp_path/'ledger',('current-owner-pin',)))
    calls=[];monkeypatch.setattr(m,'read_hourly_attestation',lambda **kw:calls.append(kw) or {'fixture_only':True})
    cutoff=datetime(2026,10,28,20,30,tzinfo=ZoneInfo('Asia/Hong_Kong'))
    value,evidence=m.read_stage_hourly_attestation(stage_app=stage,data_root=data,date='20261028',slot='2000',mode='LIVE',as_of=cutoff)
    assert calls[0]['owner_root']==current and calls[0]['as_of']==cutoff and evidence==('current-owner-pin',)
    record.write_text(json.dumps({'materializer_sha256':'0'*64}))
    with pytest.raises(m.PublicationError,match='HOURLY_PROVENANCE_OWNER_NOT_ALLOWLISTED'):
        m.read_stage_hourly_attestation(stage_app=stage,data_root=data,date='20261028',slot='2000',mode='LIVE',as_of=cutoff)
    assert len(calls)==1


def test_source_role_reader_preserves_shared_types_and_explicit_stage_dispatch(tmp_path,monkeypatch):
    from stage_center import research_context as api
    from stage_center import research_context_stage_owner as stage
    assert stage.ResearchContext is api.ResearchContext and stage.ResearchContextError is api.ResearchContextError and stage.ResearchScore is api.ResearchScore
    sentinel=object();calls=[]
    monkeypatch.setattr(stage,'load_research_context',lambda *a,**k:calls.append((a,k)) or sentinel)
    monkeypatch.setenv('STAGE_CENTER_CONFIG',str(tmp_path/'fixed-stage-config.json'))
    value=api.load_research_context(tmp_path,trade_date='20261028',stage_cutoff='09:25:00')
    assert value is sentinel and calls==[((tmp_path,),{'trade_date':'20261028','stage_cutoff':'09:25:00','morning_root':None})]
