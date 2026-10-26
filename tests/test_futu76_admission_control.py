"""Synthetic one-file CAS and rollback; no runtime target is mutated."""
import importlib.util
import json
from pathlib import Path

import pytest

B=Path('/Users/lexi/Desktop/学习/因子工厂/research/futu_qfq76_mac_integration_20261026_r1')


@pytest.fixture
def control(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('admission_test',B/'admission_control.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    state=tmp_path/'state';cache=state/'runtime/cache/data_layer_daily_formula_increment_update_v1'
    cache.mkdir(parents=True);(cache/'qfq_publish.lock').touch()
    monkeypatch.setattr(m,'STATE',state);monkeypatch.setattr(m,'TARGET',cache/m.TARGET.name)
    monkeypatch.setattr(m,'JOURNAL',tmp_path/'journal.json');monkeypatch.setattr(m,'B',tmp_path)
    api=tmp_path/'active/app/apps/api/v35_api/a_share_panel_history.py';api.parent.mkdir(parents=True);api.write_text('# fixture only\n')
    (tmp_path/'control').mkdir();projected=tmp_path/'control/release-manifest.materialized.json';projected.write_text('synthetic')
    (tmp_path/'control/PACKAGE_RESULT.json').write_text(json.dumps(dict(manifest_sha256='unprojected',api_source_sha256=m.q.sha(api))))
    monkeypatch.setattr(m.a,'read_active_release',lambda *args:dict(release_manifest_sha256=m.q.sha(projected),app_root=str(tmp_path/'active/app')))
    monkeypatch.setattr(m,'payload',lambda *args:dict(schema='SYNTHETIC_CONTROL_FIXTURE_NOT_ACCEPTANCE'))
    return m


def test_exact_absent_admission_and_owned_rollback(control):
    assert control.apply('fixture')['status']=='COMMITTED'
    assert control.TARGET.is_file()
    assert control.rollback()['status']=='ROLLED_BACK'
    assert not control.TARGET.exists()


def test_preimage_conflict_retains_existing_bytes(control):
    control.TARGET.write_bytes(b'third party')
    with pytest.raises(RuntimeError,match='PREIMAGE_CAS_CONFLICT'):
        control.apply('fixture')
    assert control.TARGET.read_bytes()==b'third party'
    assert not control.JOURNAL.exists()


def test_rollback_refuses_third_party_change(control):
    control.apply('fixture');control.TARGET.write_bytes(b'third party')
    with pytest.raises(RuntimeError,match='THIRD_PARTY_CAS_CONFLICT'):
        control.rollback()
    assert control.TARGET.read_bytes()==b'third party'


def test_prepared_journal_recovers_post_write_reporting_failure(control,monkeypatch):
    original=control.q._json
    def fail_final(path,value):
        if Path(path)==control.JOURNAL and value.get('status')=='COMMITTED':
            raise OSError('synthetic post-write journal failure')
        return original(path,value)
    monkeypatch.setattr(control.q,'_json',fail_final)
    with pytest.raises(OSError,match='post-write'):
        control.apply('fixture')
    assert json.loads(control.JOURNAL.read_text())['status']=='PREPARED'
    assert control.TARGET.exists()
    assert control.rollback()['status']=='ROLLED_BACK'
