"""Synthetic eight-file HK reader fixture; no model, publisher or SDK execution."""
import base64
import csv
from pathlib import Path
from v5_shadow.digests import canonical_bytes,sha256_json
import hashlib

SAFETY=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)
ROLE='HK_CONNECT_D1_TOP100_0_2'


def create_hk_reader_fixture(root,*,target='20261008',signal='20261007',eligibility='20260930',
                             count=100,status='READY',unknown_member=False,model_sha=None,
                             master_capture_time='16:30:00',pool_capture_time='07:59:00',temporal=None,score_override=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    captured=f'{eligibility[:4]}-{eligibility[4:6]}-{eligibility[6:]}T{master_capture_time}+08:00'
    def write_json(relative,value):
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(canonical_bytes(value));return path
    def write_csv(relative,rows):
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        return hashlib.sha256(path.read_bytes()).hexdigest()
    master_run='SYNTHETIC_MASTER_RUN';master_relative=f'runs/{eligibility}/{master_run}'
    master_rows=[dict(code=f'HK.{i:05}',name=f'SYNTHETIC_{i:05}',outstanding_shares='',circular_market_val='',
                      listing_date='2020-01-01',lot_size=100,stock_owner='',stock_child_type='',sec_status='NORMAL',
                      captured_at=captured,source='SYNTHETIC_FIXTURE') for i in range(1,101)]
    master_sha=write_csv('assets/hk_security_master/'+master_relative+'/artifact.csv',master_rows)
    master=dict(schema_version='v3_shared_data.hk_security_master_manifest.v1',trade_date=eligibility,
                run_id=master_run,captured_at=captured,row_count=100,artifact_relative=master_relative+'/artifact.csv',
                artifact_sha256=master_sha,universe_codes_sha256=sha256_json([r['code'] for r in master_rows]),
                stage_valuation_policy='OUTSTANDING_SHARES_X_CUTOFF_LAST_PRICE',valuation_eligibility_field='circular_market_val',
                later_snapshot_price_allowed=False,fixture_only=True,**SAFETY)
    write_json('assets/hk_security_master/'+master_relative+'/manifest.json',master)
    write_json('assets/hk_security_master/'+master_relative+'/receipt.json',dict(
        schema_version='v3_shared_data.hk_security_master_receipt.v1',status='READY',trade_date=eligibility,
        run_id=master_run,artifact_sha256=master_sha,manifest_sha256=sha256_json(master),**SAFETY))
    write_json('assets/hk_security_master/latest.json',dict(schema_version='v3_shared_data.hk_security_master_latest.v1',
        entries={eligibility:dict(run_id=master_run,manifest_relative=master_relative+'/manifest.json',receipt_relative=master_relative+'/receipt.json')}))
    pool_run='SYNTHETIC_HK02_RUN';relative=f'runs/{target}/{ROLE}/{pool_run}'
    rows=[dict(rank=i,code_norm=f'HK.{i:05}',name=f'SYNTHETIC_{i:05}',score_prob_active=1-i/1000,
               trade_date=target,signal_date=signal,target_date=target,selected_strategy='prob_active',d1_freshness_status='PASS') for i in range(1,count+1)]
    if score_override is not None:rows[0]['score_prob_active']=score_override
    if unknown_member:rows[0]['code_norm']='HK.00999'
    pool_sha=write_csv(relative+'/artifact.csv',rows)
    provenance=dict(signal_date=signal,source_contract='tdx_vipdoc_71_day_prob_active',panel_sha256='f'*64,
        model_bundle_sha256=model_sha or '3b0d5d5239342439cabf25b30012365a64d78839bc3cd4d90bad7be6ff4aaa07',
        daily_features_sha256='6604c499f7b3dbbed4b8493c6574c1f2ca6af52125cfe9f7d5f740cf01c94228',
        proxy_prob_active_sha256='6248bc44d77500185d9eae88fe575ed0dfe617f6f4e6649e3f6e82aa8f65fc5f',
        eligibility_source_date=eligibility,security_master_trade_date=eligibility,security_master_run_id=master_run,
        security_master_artifact_sha256=master_sha,security_master_captured_at='b64url.'+base64.urlsafe_b64encode(captured.encode()).decode())
    manifest=dict(schema_version='v3_shared_data.manifest.v1',trade_date=target,signal_date=signal,
                  captured_at=f'{target[:4]}-{target[4:6]}-{target[6:]}T{pool_capture_time}+08:00',
                  artifact_relative=relative+'/artifact.csv',artifact_sha256=pool_sha,row_count=count,
                  temporal_cutoff_safe=(status=='READY' if temporal is None else temporal),input_sha256='e'*64,provenance=provenance,fixture_only=True,**SAFETY)
    write_json(relative+'/manifest.json',manifest)
    write_json(relative+'/receipt.json',dict(schema_version='v3_shared_data.receipt.v1',owner='SYNTHETIC_FIXTURE',
        run_id=pool_run,status=status,trade_date=target,role=ROLE,artifact_sha256=pool_sha,
        manifest_sha256=sha256_json(manifest),finished_at=f'{target[:4]}-{target[4:6]}-{target[6:]}T08:00:00+08:00',**SAFETY))
    write_json('latest.json',dict(schema_version='v3_shared_data.latest.v1',entries={target+'/'+ROLE:dict(
        owner='SYNTHETIC_FIXTURE',run_id=pool_run,artifact_relative=relative+'/artifact.csv',
        manifest_relative=relative+'/manifest.json',receipt_relative=relative+'/receipt.json')}))
    return {str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}
