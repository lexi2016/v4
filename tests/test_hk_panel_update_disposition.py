from pathlib import Path
import struct

import pandas as pd
import pytest

from upstreams.v3_shared_data.shared_data.hk_0_2 import _read_vipdoc_increment, update_hk_0_2_panel_from_vipdoc
from upstreams.v3_shared_data.shared_data.store import StoreError


def record(date, *, open=10.,high=11.,low=9.,close=10.,amount=100.,trade=10):
    return struct.pack('<IfffffII',date,open,high,low,close,amount,trade,0)


def test_native_reader_accounts_all_records_and_keeps_provider_unknown(tmp_path):
    path=tmp_path/'71#00001.day'
    path.write_bytes(record(20261020)+record(20261021)+record(20261021)+record(20261022)+record(20261022,close=10.5)+record(20261023,open=12)+record(20260230)+record(20261024)+record(20261023,close=float('nan')))
    evidence={}
    rows,count=_read_vipdoc_increment(tmp_path,after_date='20261020',through_date='20261023',evidence=evidence)
    assert count==1 and len(rows)==1 and rows[0]['trade_date_compact']=='20261021'
    assert evidence['input_record_count']==9==sum(evidence['disposition_counts'].values())
    assert evidence['disposition_counts']=={'QUARANTINED':5,'OUT_OF_WINDOW':2,'ACCEPTED':1,'DUPLICATE_IDENTICAL':1}
    assert evidence['provider_identity']=='UNKNOWN_PACKED_DAY_UPSTREAM'
    assert evidence['fields']['amount']['unit_status']=='NOT_PROVEN'
    assert [r['byte_offset'] for r in evidence['row_dispositions']]==list(range(0,9*32,32))
    assert evidence['row_dispositions'][0]['native_source_sha256']==evidence['source_files'][0]['sha256']
    assert path.read_bytes().endswith(record(20261023,close=float('nan')))


def test_trailing_bytes_and_source_symlinks_fail_closed(tmp_path):
    file=tmp_path/'71#00001.day';file.write_bytes(b'x')
    with pytest.raises(StoreError,match='trailing bytes'):_read_vipdoc_increment(tmp_path,after_date='20261020',through_date='20261023')
    other=tmp_path/'other';other.write_bytes(record(20261023));file.unlink();file.symlink_to(other)
    with pytest.raises(StoreError,match='SYMLINK'):_read_vipdoc_increment(tmp_path,after_date='20261020',through_date='20261023')


def test_actual_updater_retains_prefix_and_publishes_complete_disposition(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import json
    import upstreams.v3_shared_data.shared_data.hk_0_2 as owner
    asset=tmp_path/'assets';asset.mkdir();source=asset/'old.parquet'
    old=pd.DataFrame(dict(code_norm=['HK.00001'],trade_date_compact=['20261022'],open=[10.],high=[11.],low=[9.],close=[10.],trade=[10.],amount=[100.],continuity_segment_id=[1]))
    old.to_parquet(source,index=False)
    monkeypatch.setattr(owner,'load_frozen_hk_0_2_assets',lambda root:SimpleNamespace(panel_path=source,panel_manifest={'panel_sha256':'a'*64}))
    native=tmp_path/'native';native.mkdir()
    (native/'71#00001.day').write_bytes(record(20261022)+record(20261023)+record(20261023))
    outcome=update_hk_0_2_panel_from_vipdoc(asset,tdx_root=native,through_date='20261023',minimum_code_count=1)
    assert outcome['status']=='READY' and outcome['new_row_count']==1
    manifest=json.loads((asset/outcome['manifest_relative']).read_text())
    assert manifest['native_observation']['input_record_count']==3
    assert manifest['native_observation']['disposition_counts']=={'ACCEPTED':1,'DUPLICATE_IDENTICAL':1,'OUT_OF_WINDOW':1}
    output=pd.read_parquet(asset/manifest['panel_relative'])
    assert len(output)==2
    pd.testing.assert_frame_equal(output.loc[output.trade_date_compact.eq('20261022'),old.columns].reset_index(drop=True),old,check_dtype=False)


def test_actual_updater_rejects_conflict_without_advancing_pointer(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import upstreams.v3_shared_data.shared_data.hk_0_2 as owner
    asset=tmp_path/'assets';asset.mkdir();source=asset/'old.parquet'
    pd.DataFrame(dict(code_norm=['HK.00001'],trade_date_compact=['20261022'],close=[10.])).to_parquet(source,index=False)
    monkeypatch.setattr(owner,'load_frozen_hk_0_2_assets',lambda root:SimpleNamespace(panel_path=source,panel_manifest={'panel_sha256':'a'*64}))
    native=tmp_path/'native';native.mkdir()
    (native/'71#00001.day').write_bytes(record(20261023)+record(20261023,close=10.5))
    with pytest.raises(StoreError,match='through date is absent'):
        update_hk_0_2_panel_from_vipdoc(asset,tdx_root=native,through_date='20261023',minimum_code_count=1)
    assert not (asset/'panel_latest.json').exists()


def test_import_only_seed_refuses_ambiguous_overlays_and_bad_schema(tmp_path):
    from upstreams.v3_shared_data.shared_data.hk_0_2 import compose_historical_hk_0_2_seed
    base=tmp_path/'base.parquet'
    frame=pd.DataFrame(dict(code_norm=['HK.00001'],trade_date_compact=['20261022'],close=[10.]))
    frame.to_parquet(base,index=False)
    previous=tmp_path/'previous';pool=previous/'20261022_hkconnect_d1_pool';pool.mkdir(parents=True)
    overlay=pool/'hkconnect_d1_close_panel_fixture.parquet';frame.to_parquet(overlay,index=False)
    target=tmp_path/'seed.parquet'
    with pytest.raises(StoreError,match='DUPLICATE_REQUIRES_AUDIT'):
        compose_historical_hk_0_2_seed(base_panel_path=base,prior_signal_panel_root=previous,signal_date='20261023',destination=target)
    assert not target.exists()
    frame.drop(columns=['trade_date_compact']).to_parquet(overlay,index=False)
    with pytest.raises(StoreError,match='DATE_COLUMN_MISSING'):
        compose_historical_hk_0_2_seed(base_panel_path=base,prior_signal_panel_root=previous,signal_date='20261023',destination=target)
    assert not target.exists()
