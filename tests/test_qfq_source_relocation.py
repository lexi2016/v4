import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_factor_cache as cache


def _write_panel(path, generation, snapshot):
    meta={b'a_share_qfq_contract_v1':json.dumps({'generation_id':generation,'asof_date':20261030,'adjustment_snapshot':snapshot}).encode()}
    pq.write_table(pa.table({'value':[1]}).replace_schema_metadata(meta),path)


def _setup(tmp_path, monkeypatch):
    generation='a'*64; snapshot={'path':'/frozen/snapshot.json','sha256':'b'*64}; descriptor_ref={'path':'/frozen/descriptor.json','sha256':'c'*64}
    monkeypatch.setattr(cache,'_RELOCATION_GENERATION',generation)
    allowed={};roles={};descriptor={'baseline_roles':{},'baseline_snapshot':snapshot}
    for role in ('selector','backtest'):
        original=str(tmp_path/f'old_{role}.parquet');target=tmp_path/f'archive_{role}.parquet';_write_panel(target,generation,snapshot);digest=cache.sha(target)
        allowed[role]=(original,digest);roles[role]={'original_path':original,'expected_sha256':digest,'relocated_path':str(target)};descriptor['baseline_roles'][role]={'path':original,'sha256':digest}
    monkeypatch.setattr(cache,'_RELOCATION_ROLES',allowed)
    manifest={'schema':'qfq_same_asof_exact_archive_relocation_v1','mode':'ISOLATED_READ_ONLY','baseline_generation':generation,'asof_date':20261030,'descriptor':descriptor_ref,'roles':roles,'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    path=tmp_path/'mapping.json'
    def save():path.write_text(json.dumps(manifest));return {'path':str(path),'sha256':cache.sha(path)}
    return descriptor_ref,descriptor,manifest,save


def test_explicit_pair_accepts_identical_sources(tmp_path,monkeypatch):
    desc,descriptor,manifest,save=_setup(tmp_path,monkeypatch)
    result=cache._relocated_baseline_paths(save(),desc,descriptor,20261030)
    assert result == {role:Path(item['relocated_path']) for role,item in manifest['roles'].items()}


def test_manifest_sha_and_undeclared_original_fail_closed(tmp_path,monkeypatch):
    desc,descriptor,manifest,save=_setup(tmp_path,monkeypatch); ref=save()
    manifest['roles']['selector']['original_path']='/unapproved/selector';save()
    with pytest.raises(cache.QfqGateError):cache._relocated_baseline_paths(ref,desc,descriptor,20261030)
    with pytest.raises(cache.QfqGateError,match='ORIGINAL_BINDING_CONFLICT'):cache._relocated_baseline_paths(save(),desc,descriptor,20261030)


def test_changed_target_and_wrong_footer_fail_closed(tmp_path,monkeypatch):
    desc,descriptor,manifest,save=_setup(tmp_path,monkeypatch);ref=save();target=Path(manifest['roles']['selector']['relocated_path'])
    _write_panel(target,'d'*64,descriptor['baseline_snapshot'])
    with pytest.raises(cache.QfqGateError,match='TARGET_CONFLICT'):cache._relocated_baseline_paths(ref,desc,descriptor,20261030)
    digest=cache.sha(target);manifest['roles']['selector']['expected_sha256']=digest;descriptor['baseline_roles']['selector']['sha256']=digest
    monkeypatch.setitem(cache._RELOCATION_ROLES,'selector',(manifest['roles']['selector']['original_path'],digest))
    with pytest.raises(cache.QfqGateError,match='TARGET_CONFLICT'):cache._relocated_baseline_paths(save(),desc,descriptor,20261030)


def test_relocation_rejects_publication_before_side_effect(tmp_path):
    from ops.research_panel_qfq import run_daily_rebuild,QfqGateError
    with pytest.raises(QfqGateError,match='ISOLATED_CANDIDATE_ONLY'):
        run_daily_rebuild(driver_path=tmp_path/'driver',formula_path=tmp_path/'formula',tdx_root=tmp_path,
            data_root=tmp_path,pointers={},contract_csv=tmp_path/'csv',return_root=tmp_path,target=20261030,
            publish=True,source_relocation_ref={'path':'/x','sha256':'0'*64})
