import hashlib,json
from pathlib import Path
from ops import research_panel_daily_source as source,research_panel_qfq as q
from ops import research_panel_factor_cache as cache


def test_same_day_membership_revision_preserves_old_identity_and_reuses_exact_hash(tmp_path,monkeypatch):
    root=tmp_path/'data';root.mkdir();tdx=tmp_path/'tdx';tdx.mkdir()
    monkeypatch.setattr(q,'input_path',lambda _:root/'input.json')
    policy=dict(observed_provider_only_exceptions=[],provider_only_exception_scope='existing',source_comparison_refs=[])
    monkeypatch.setattr(source,'source_policy',lambda:policy)
    monkeypatch.setattr(source,'_detector',lambda *a,**kw:{'target':20261110})
    config=tmp_path/'prior_config.json';config.write_text(json.dumps(dict(current_detector={'target':20261109},current_identities={'prior':'identity'})))
    prior=tdx.parent/'adjustment_inputs/futu_rehab/research_carry/20261109/prior.json';prior.parent.mkdir(parents=True);prior.write_text(json.dumps(dict(schema='research_factor_cache_carry_forward.v1',status='READY_RESEARCH_CACHE',asof_date=20261109,configuration=dict(path=str(config),sha256=hashlib.sha256(config.read_bytes()).hexdigest()))))
    summary=tdx.parent/'receipts/a_sync_authority/20261110/summary.json';summary.parent.mkdir(parents=True);summary.write_text('{}')
    members={'300556.SZ':{}}
    monkeypatch.setattr(cache,'_sync_prequery_rows',lambda *a:members)
    first=source.build_cache_configuration(data_root=root,tdx_root=tdx,target=20261110,codes=[])
    first_config=json.loads(Path(first['path']).read_text());oldref=first_config['current_identities'];old=Path(oldref['path']).read_bytes()
    assert Path(oldref['path']).name=='20261110.json'
    same=source.build_cache_configuration(data_root=root,tdx_root=tdx,target=20261110,codes=[])
    assert same==first
    members['920202.BJ']={}
    revised=source.build_cache_configuration(data_root=root,tdx_root=tdx,target=20261110,codes=[])
    revised_config=json.loads(Path(revised['path']).read_text());newref=revised_config['current_identities'];value=json.loads(Path(newref['path']).read_text())
    assert Path(newref['path']).name=='20261110-'+source.canonical_sha(value)+'.json'
    assert Path(oldref['path']).read_bytes()==old
    assert set(value['symbols'])==set(members)
    assert source.build_cache_configuration(data_root=root,tdx_root=tdx,target=20261110,codes=[])==revised
