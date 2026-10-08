"""SYNTHETIC ONLY. Creates real Parquet and original-owner-format test files."""
import hashlib,json
from pathlib import Path

def publish_fixture(root:Path, original, master_captured_at='2026-10-07T17:00:00+08:00'):
    import pandas as pd
    from v3_shared_data.shared_data.hk_security_master import publish_hk_security_master,LATEST_SCHEMA_VERSION
    day='20261007';sessions=original.rebound_history_sessions(day)
    rows=[];codes=['HK.00001','HK.00002','HK.00003','HK.00004']
    for code in codes:
        for date in sessions['prior60']:
            rows.append(dict(trade_date_compact=date,code_norm=code,name='SYNTHETIC '+code,open=9.,high=10.,low=8.,close=9.,amount=100_000_000.,trade=100.,pre_close=9.))
    for code,close,volume in zip(codes,[7.,7.,9.,9.],[200.,100.,200.,100.]):
        rows.append(dict(trade_date_compact=day,code_norm=code,name='SYNTHETIC '+code,open=close,high=close+1,low=close-1,close=close,amount=100_000_000.,trade=volume,pre_close=9.))
    temp=root/'synthetic.parquet';pd.DataFrame(rows).to_parquet(temp,index=False)
    raw=temp.read_bytes();digest=hashlib.sha256(raw).hexdigest();temp.unlink()
    relative=f'panels/{day}-{digest[:12]}/hkconnect_vipdoc_daily_panel.parquet'
    asset=root/'assets'/'hk_0_2';path=asset/relative;path.parent.mkdir(parents=True);path.write_bytes(raw)
    manifest=dict(asset_schema_version='v3_shared_data.hk_0_2_panel_asset.v2',panel_max_date=day,panel_relative=relative,panel_sha256=digest,panel_code_count=4,panel_rows=len(rows),source_contract='tdx_vipdoc_71_day+verified_zero_trade_repairs',manifest_prepared_at='2026-10-07T17:30:00+08:00',research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    (path.parent/'manifest.json').write_text(json.dumps(manifest,sort_keys=True))
    (asset/'panel_latest.json').write_text(json.dumps({'manifest_relative':str((path.parent/'manifest.json').relative_to(asset))}))
    master=root/'assets'/'hk_security_master';master.mkdir(parents=True)
    (master/'latest.json').write_text(json.dumps({'schema_version':LATEST_SCHEMA_VERSION,'entries':{}}))
    publish_hk_security_master(root,trade_date=day,rows=[dict(code=c,name='SYNTHETIC '+c,outstanding_shares=1000,circular_market_val=10000,listing_date='2020-01-01',lot_size=100,stock_owner='SYNTHETIC',stock_child_type='SYNTHETIC',sec_status='NORMAL') for c in codes],universe_codes_sha256=hashlib.sha256(json.dumps(codes).encode()).hexdigest(),captured_at=master_captured_at)
    (root/'SYNTHETIC_INPUT.json').write_text(json.dumps({'data_kind':'SYNTHETIC','not_real_prices':True}))
    return str(path.parent/'manifest.json')
