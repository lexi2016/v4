import gzip
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import copy

from upstreams.v3_shared_data.shared_data.hk_history_resolution import (
    FIELDS, RULE, SCHEMA, ResolutionError, ResolutionPolicy, canonical, guard_score_frame,
    verify_append_frames,
)
import upstreams.v3_shared_data.shared_data.hk_history_resolution as resolution


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def install_resolution(owner, records=(), *, C_relative=None):
    """Small synthetic fixture, never a live pointer or a market-data copy."""
    owner=Path(owner)
    pointer=json.loads((owner/'panel_latest.json').read_text())
    cm=owner/pointer['manifest_relative'];manifest=json.loads(cm.read_text())
    if C_relative is None:C_relative=manifest['panel_relative']
    descriptor=json.loads((owner/'research_history.json').read_text())
    b=Path(descriptor['source_descriptor']['sources']['B']['path'])
    directory=owner/'history_resolution/test';directory.mkdir(parents=True,exist_ok=True)
    prepared=[]
    for source in records:
        rec=dict(source)
        rec.update(B_source_sha256=sha(b),C_source_sha256=manifest['panel_sha256'])
        prepared.append(rec)
    payload=b''.join(canonical(record)+b'\n' for record in prepared)
    (directory/'decisions.jsonl.gz').write_bytes(gzip.compress(payload,mtime=0))
    contract=dict(schema_version=SCHEMA,rule_version=RULE,resolver_sha256=sha(resolution.__file__),
        research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,
        decisions_relative='history_resolution/test/decisions.jsonl.gz',
        decisions_sha256=sha(directory/'decisions.jsonl.gz'),decision_key_count=len(prepared),
        baseline_C_max_date=manifest.get('panel_max_date','20260102'),B_max_date='20260101',
        append_policy='ALL_KEYS_ALL_COLUMNS_EXACT',
        bindings=dict(descriptor_relative='research_history.json',descriptor_sha256=sha(owner/'research_history.json'),
            B_relative=b.relative_to(owner).as_posix(),B_sha256=sha(b),
            C_panel_relative=C_relative,C_panel_sha256=manifest['panel_sha256'],
            C_manifest_relative=pointer['manifest_relative'],C_manifest_sha256=sha(cm)))
    (directory/'manifest.json').write_bytes(canonical(contract))
    (owner/'history_resolution_latest.json').write_bytes(canonical(dict(
        manifest_relative='history_resolution/test/manifest.json',manifest_sha256=sha(directory/'manifest.json'))))
    return contract


def record(code,date,held=(),confirmed=()):
    return dict(symbol=code,date=date,B_row_sha256='a'*64,C_row_sha256='b'*64,
        field_decisions={field:dict(disposition='QUARANTINED' if field in held else
            'CONFIRMED_KEEP_C' if field in confirmed else 'UNDISPUTED_KEEP_C_EXISTING_POLICY') for field in FIELDS})


@pytest.fixture
def owner(tmp_path):
    root=tmp_path/'assets/hk_0_2';(root/'panels/v1').mkdir(parents=True);(root/'research_materials').mkdir()
    b=root/'research_materials/b.parquet';pd.DataFrame({'code':['HK.00001'],'date':['20260101'],'close':[1.0]}).to_parquet(b,index=False)
    c=root/'panels/v1/panel.parquet'
    pd.DataFrame(dict(code_norm=['HK.00001'],trade_date_compact=['20260102'],close=[2.0],pre_close=[1.0])).to_parquet(c,index=False)
    (root/'research_history.json').write_bytes(canonical(dict(source_descriptor=dict(sources=dict(B=dict(path=str(b)))))))
    (root/'panels/v1/manifest.json').write_bytes(canonical(dict(panel_relative='panels/v1/panel.parquet',panel_sha256=sha(c),panel_max_date='20260102',panel_rows=1,increment_contract='APPEND_FIXTURE_V1',source_contract='NATIVE_FIXTURE',research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)))
    (root/'panel_latest.json').write_bytes(canonical(dict(manifest_relative='panels/v1/manifest.json')))
    return root


def test_field_gate_preserves_close_use_and_whole_sequence(owner):
    install_resolution(owner,[record('HK.00001','20260102',held=('trade',))])
    policy=ResolutionPolicy(owner)
    frame=pd.DataFrame(dict(code_norm=['HK.00001']*3+['HK.00002']*3,
        trade_date_compact=['20260101','20260102','20260103']*2,close=[1,2,3,4,5,6],trade=[10]*6))
    close=policy.guard_frame(frame,required_fields=('close',))
    assert close.equals(frame)
    volume=policy.guard_frame(frame,required_fields=('trade',))
    assert set(volume.code_norm)=={'HK.00002'} and len(volume)==3
    assert volume.groupby('code_norm').close.shift().dropna().tolist()==[4,5]
    assert policy.held_fields('HK.00001','20260102',('close',),source='B')==['close']


def test_score_all_codes_held_returns_empty_with_complete_diagnostics(owner):
    install_resolution(owner,[record('HK.00001','20260102',held=('close',))])
    frame=pd.DataFrame(dict(code_norm=['HK.00001'],trade_date_compact=['20260102']))
    result=guard_score_frame(frame,ResolutionPolicy(owner),'20260102')
    assert result.empty and set(result.attrs['history_resolution_holds'])=={'HK.00001'}
    assert result.attrs['history_resolution_proof']['excluded_code_count']==1


def test_same_process_cached_ledger_cannot_attach_to_rebound_source(owner):
    install_resolution(owner,[record('HK.00001','20260102',confirmed=('trade',))])
    ResolutionPolicy(owner)
    path=owner/'history_resolution/test/manifest.json';contract=json.loads(path.read_text())
    source=owner/contract['bindings']['B_relative']
    pd.DataFrame({'code':['HK.00001'],'date':['20260101'],'close':[99.0]}).to_parquet(source,index=False)
    contract['bindings']['B_sha256']=sha(source);path.write_bytes(canonical(contract))
    (owner/'history_resolution_latest.json').write_bytes(canonical(dict(
        manifest_relative='history_resolution/test/manifest.json',manifest_sha256=sha(path))))
    with pytest.raises(ResolutionError,match='LEDGER_SOURCE_MISMATCH'):ResolutionPolicy(owner)


def test_missing_tampered_source_ledger_and_old_panel_fail_closed(owner):
    with pytest.raises(ResolutionError):ResolutionPolicy(owner)
    install_resolution(owner,[record('HK.00001','20260102',confirmed=('trade',))])
    policy=ResolutionPolicy(owner)
    assert not policy.held_fields('HK.00001','20260102',('trade',))
    with pytest.raises(ResolutionError,match='UNBOUND_PANEL'):policy.check_panel('0'*64)
    ledger=owner/'history_resolution/test/decisions.jsonl.gz';ledger.write_bytes(ledger.read_bytes()+b'x')
    with pytest.raises(ResolutionError,match='LEDGER_SHA'):ResolutionPolicy(owner)
    install_resolution(owner)
    (owner/'research_materials/b.parquet').write_bytes(b'changed')
    with pytest.raises(ResolutionError,match='SOURCE_SHA'):ResolutionPolicy(owner)


def test_cache_proof_binds_sources_rule_fields_window_and_codes(owner):
    install_resolution(owner)
    policy=ResolutionPolicy(owner)
    with pytest.raises(ResolutionError,match='PROOF_MISSING'):policy.verify_proof(None)
    proof=policy.proof(required_fields=FIELDS,start='20260101',end='20260102',consumer='test',allowed_codes=['HK.00001'])
    token=policy.encode_proof(proof)
    assert policy.verify_proof(token,codes=['HK.00001'])==proof
    with pytest.raises(ResolutionError,match='STALE'):policy.verify_proof(token,end='20260103')
    with pytest.raises(ResolutionError,match='STALE'):policy.verify_proof(token,codes=['HK.00002'])
    with pytest.raises(ResolutionError,match='STALE'):policy.verify_proof(token,required_fields=('close',))


def actual_admission_fixture(owner):
    """Real policy, owned parquet and existing verified reference publisher."""
    panel=owner/'panels/v1/panel.parquet'
    source=pd.DataFrame(dict(code_norm=['HK.00001','HK.00165'],trade_date_compact=['20260102']*2,close=[2.,3.],pre_close=[1.,2.]))
    source.to_parquet(panel,index=False)
    mp=owner/'panels/v1/manifest.json';m=json.loads(mp.read_bytes());m.update(panel_sha256=sha(panel),panel_rows=2);mp.write_bytes(canonical(m))
    install_resolution(owner,[record('HK.00165','20260102',held=('close',))])
    from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master
    publish_hk_security_master(owner.parent.parent,trade_date='20260102',
        rows=[dict(code=c,name='Name '+c) for c in source.code_norm],
        universe_codes_sha256='a'*64,captured_at='2026-01-02T17:30:00+08:00')
    policy=ResolutionPolicy(owner);proof=policy._trusted_score_proof('20260102')
    return policy,proof,panel


@pytest.mark.parametrize('forgery',['held_to_allowed','fake_eligible','fake_original','window'])
def test_actual_validators_reject_self_consistent_forged_admission(owner,forgery):
    policy,genuine,_=actual_admission_fixture(owner)
    assert policy.verify_proof(policy.encode_proof(genuine),codes=['HK.00001'])==genuine
    assert resolution.validate_score_coverage(genuine,policy=policy,selected_codes=['HK.00001'])
    forged=copy.deepcopy(genuine);coverage=forged['score_coverage']
    if forgery=='held_to_allowed':
        forged['excluded_codes'].remove('HK.00165');forged['allowed_codes'].append('HK.00165');forged['allowed_codes'].sort();forged['excluded_code_count']=0
        coverage['quality_quarantined_codes'].remove('HK.00165');coverage['scoreable_signal_codes'].append('HK.00165');coverage['scoreable_signal_codes'].sort()
    if forgery=='fake_eligible':
        coverage['eligible_codes'].append('HK.99999');coverage['missing_signal_codes'].append('HK.99999')
    if forgery=='fake_original':
        coverage['original_signal_codes'].remove('HK.00165');coverage['quality_quarantined_codes'].remove('HK.00165');coverage['missing_signal_codes'].append('HK.00165')
    if forgery=='window':forged['dependency_start']='20250101'
    assert resolution._check_score_coverage(forged)  # the prior self-consistency gate accepts it
    with pytest.raises(ResolutionError,match='ADMISSION_MISMATCH'):policy.verify_proof(policy.encode_proof(forged))
    with pytest.raises(ResolutionError,match='ADMISSION_MISMATCH'):resolution.validate_score_coverage(forged,policy=policy)


def test_admission_cache_rechecks_current_source_and_verified_master(owner):
    policy,proof,panel=actual_admission_fixture(owner)
    policy.verify_proof(policy.encode_proof(proof))
    frame=pd.read_parquet(panel);frame.loc[0,'close']=99.;frame.to_parquet(panel,index=False)
    with pytest.raises(ResolutionError,match='SOURCE_STALE'):policy.verify_proof(policy.encode_proof(proof))


def test_admission_cache_rechecks_exact_verified_master_identity(owner):
    policy,proof,_=actual_admission_fixture(owner)
    policy.verify_proof(policy.encode_proof(proof))
    from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master
    publish_hk_security_master(owner.parent.parent,trade_date='20260102',
        rows=[dict(code='HK.00001',name='Name HK.00001')],
        universe_codes_sha256='b'*64,captured_at='2026-01-02T17:31:00+08:00')
    with pytest.raises(ResolutionError,match='ADMISSION_MISMATCH'):policy.verify_proof(policy.encode_proof(proof))
    updated=policy._trusted_score_proof('20260102')
    assert updated['score_coverage']['eligible_codes']==['HK.00001']


def test_transitive_proxy_window_and_current_only_trade(owner):
    dates=pd.bdate_range('2025-01-01',periods=140).strftime('%Y%m%d').tolist();signal=dates[-1]
    # Proxy labels use raw high/close/amount and pre_close only, not rolling features.
    # Memory includes current + 119 dates; that earliest label's predecessor is -121.
    decisions=[record('HK.00001',dates[-121],held=('close',)),
               record('HK.00002',dates[-122],held=('close',)),
               record('HK.00003',dates[-40],held=('trade',)),
               record('HK.00004',signal,held=('trade',))]
    install_resolution(owner,decisions)
    frame=pd.DataFrame([dict(code_norm=code,trade_date_compact=date,close=10.0,high=11.0,low=9.0,open=10.0,amount=100.0,trade=10)
        for code in ('HK.00001','HK.00002','HK.00003','HK.00004') for date in dates])
    guarded=guard_score_frame(frame,ResolutionPolicy(owner),signal)
    assert set(guarded.code_norm)=={'HK.00002','HK.00003'}
    assert len(guarded)==280  # no isolated row removal and no historical-trade overblocking
    assert guarded.loc[guarded.code_norm.eq('HK.00002')].close.tolist()==[10.0]*140


def test_append_proof_checks_all_old_rows_columns_and_new_dates():
    base=pd.DataFrame(dict(code_norm=['HK.00001']*2,trade_date_compact=['20260101','20260102'],close=[1.0,2.0],pre_close=[0.0,1.0]))
    new=pd.concat([base,pd.DataFrame(dict(code_norm=['HK.00001'],trade_date_compact=['20260103'],close=[3.0],pre_close=[2.0]))],ignore_index=True)
    assert verify_append_frames(base,new,baseline_max='20260102',B_max='20260101')['new_rows']==1
    tamper=new.copy();tamper.loc[0,'pre_close']=99.0
    with pytest.raises(ResolutionError,match='OLD_KEYS_OR_VALUES'):verify_append_frames(base,tamper,baseline_max='20260102',B_max='20260101')
    with pytest.raises(ResolutionError,match='DUPLICATE'):verify_append_frames(base,pd.concat([new,new.iloc[-1:]]),baseline_max='20260102',B_max='20260101')
    with pytest.raises(ResolutionError,match='DATES_INVALID'):verify_append_frames(base,new,baseline_max='20260102',B_max='20260103')


def test_real_policy_accepts_exact_append_and_stales_old_cache(owner):
    install_resolution(owner)
    old=ResolutionPolicy(owner);token=old.encode_proof(old.proof(required_fields=FIELDS,start='20260101',end='20260102',consumer='test'))
    base=pd.read_parquet(owner/'panels/v1/panel.parquet')
    appended=pd.concat([base,pd.DataFrame(dict(code_norm=['HK.00001'],trade_date_compact=['20260103'],close=[3.0],pre_close=[2.0]))],ignore_index=True)
    folder=owner/'panels/v2';folder.mkdir();appended.to_parquet(folder/'panel.parquet',index=False)
    manifest=json.loads((owner/'panels/v1/manifest.json').read_text());manifest.update(panel_relative='panels/v2/panel.parquet',panel_sha256=sha(folder/'panel.parquet'),panel_rows=2,panel_max_date='20260103')
    (folder/'manifest.json').write_bytes(canonical(manifest));(owner/'panel_latest.json').write_bytes(canonical(dict(manifest_relative='panels/v2/manifest.json')))
    current=ResolutionPolicy(owner)
    assert current.append_proof['status']=='APPEND_ONLY_COMPATIBLE'
    current.check_panel(manifest['panel_sha256'])
    with pytest.raises(ResolutionError,match='STALE'):current.verify_proof(token)

@pytest.fixture
def corrected_owner(owner):
    data=pd.DataFrame(dict(code_norm=['HK.00001']*3,trade_date_compact=['20260703','20260706','20260707'],
        open=[2.,2.,3.],high=[2.,2.,3.],low=[2.,2.,3.],close=[2.,2.,3.],amount=[20.,20.,30.],trade=[100.]*3,
        pre_close=[1.,2.,2.],pct_chg=[100.,0.,50.],amplitude_pct=[0.]*3,intraday_high_pct=[100.,0.,50.],continuity_segment_id=[1]*3,continuity_break=['']*3))
    cp=owner/'panels/v1/panel.parquet';data.to_parquet(cp,index=False)
    mp=owner/'panels/v1/manifest.json';m=json.loads(mp.read_bytes());m.update(panel_sha256=sha(cp),panel_rows=3,panel_max_date='20260707');mp.write_bytes(canonical(m))
    contract=install_resolution(owner,[record('HK.00001','20260706',held=('close','amount','trade'))])
    raw=owner/'research_materials/raw.json';raw.write_bytes(b'fixture response')
    ref=dict(raw_relative='research_materials/raw.json',raw_sha256=sha(raw),request_sha256='1'*64,response_sha256='2'*64,catalogue_sha256='3'*64,captured_at='2026-10-14T06:00:00+00:00')
    vals=dict(open=2.5,high=3.,low=2.,close=3.,amount=30.)
    def anchor(date,value):
        fields=dict(open=value,high=value,low=value,close=value,amount=value*10)
        return dict(date=date,C_values=fields,TDX_values=fields,evidence_refs=[ref])
    rec=dict(symbol='HK.00001',date='20260706',rule_version=resolution.CORRECTION_RULE,channel='TDX_PROTOCOL_PARAM1_FIXED',
        C_source_sha256=contract['bindings']['C_panel_sha256'],B_source_sha256=contract['bindings']['B_sha256'],
        C_row_sha256='b'*64,B_row_sha256='a'*64,values=vals,evidence_refs=[ref],
        anchors=[anchor('20260703',2.),anchor('20260707',3.)],
        closure=dict(previous_date='20260703',next_date='20260707',event_pre_close=2.,next_pre_close=3.,continuity_segment_equal=True))
    directory=owner/'history_resolution/test';correction=directory/'corrections.jsonl.gz';correction.write_bytes(gzip.compress(canonical(rec)+b'\n',mtime=0))
    evidence=directory/'evidence.json';evidence.write_bytes(canonical(dict(sources=[dict(raw_relative=ref['raw_relative'],raw_sha256=sha(raw),manifest_relative='panels/v1/manifest.json',manifest_sha256=sha(mp))])))
    contract.update(corrections_relative='history_resolution/test/corrections.jsonl.gz',corrections_sha256=sha(correction),
        correction_evidence_relative='history_resolution/test/evidence.json',correction_evidence_sha256=sha(evidence),correction_key_count=1,correction_rule_version=resolution.CORRECTION_RULE)
    (directory/'manifest.json').write_bytes(canonical(contract));(owner/'history_resolution_latest.json').write_bytes(canonical(dict(manifest_relative='history_resolution/test/manifest.json',manifest_sha256=sha(directory/'manifest.json'))))
    return owner,data


def test_sparse_corrected_fields_and_next_preclose_subset(corrected_owner):
    root,data=corrected_owner;policy=ResolutionPolicy(root)
    result=policy.guard_frame(data,required_fields=('close','amount'))
    assert len(result)==3 and data.close.tolist()==[2.,2.,3.]
    assert result.close.tolist()==[2.,3.,3.] and result.pre_close.tolist()==[1.,2.,3.]
    subset=policy.guard_frame(data.iloc[[2]],required_fields=('close',))
    assert subset.iloc[0].pre_close==3. and subset.iloc[0].pct_chg==0.
    assert policy.held_fields('HK.00001','20260706')==['trade']
    assert policy.held_fields('HK.00001','20260706',('close',),source='B')==['close']
    assert policy.guard_frame(data,required_fields=('trade',)).empty
    assert policy.field_admission('HK.00001','20260706','close')=='CORRECTED_TDX_RETROSPECTIVE_CHANNEL'
    assert 'corrections_sha256' in result.attrs['history_resolution_proof']
    assert policy.project_frame(data,source='B').equals(data)


@pytest.mark.parametrize('tamper',['ledger','raw','evidence'])
def test_sparse_overlay_tamper_failclosed(corrected_owner,tamper):
    root,data=corrected_owner;policy=ResolutionPolicy(root)
    path={'ledger':root/policy.manifest['corrections_relative'],'raw':root/'research_materials/raw.json','evidence':root/policy.manifest['correction_evidence_relative']}[tamper]
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ResolutionError,match='CORRECTION'):ResolutionPolicy(root)


def test_sparse_overlay_old_cache_proof_rejected(corrected_owner):
    root,data=corrected_owner;policy=ResolutionPolicy(root)
    proof=policy.proof(required_fields=('close',),start='20260703',end='20260707',consumer='TEST')
    proof.pop('corrections_sha256');proof.pop('correction_rule_version')
    with pytest.raises(ResolutionError,match='PROOF_STALE'):policy.verify_proof(policy.encode_proof(proof))


def test_new_close_ratio_break_propagates_segment_and_never_bridges(corrected_owner):
    root,data=corrected_owner;directory=root/'history_resolution/test'
    path=directory/'corrections.jsonl.gz';rec=json.loads(gzip.decompress(path.read_bytes()))
    rec['values'].update(high=4.,close=4.)
    rec['closure'].update(event_pre_close=None,next_pre_close=4.,event_break='cross_day_close_ratio',next_break='')
    path.write_bytes(gzip.compress(canonical(rec)+b'\n',mtime=0))
    mp=directory/'manifest.json';manifest=json.loads(mp.read_bytes());manifest['corrections_sha256']=sha(path);mp.write_bytes(canonical(manifest))
    (root/'history_resolution_latest.json').write_bytes(canonical(dict(manifest_relative='history_resolution/test/manifest.json',manifest_sha256=sha(mp))))
    policy=ResolutionPolicy(root);result=policy.guard_frame(data,required_fields=('close',))
    assert pd.isna(result.iloc[1].pre_close) and pd.isna(result.iloc[1].pct_chg)
    assert result.continuity_segment_id.tolist()==[1,2,2]
    assert result.continuity_break.tolist()==['','cross_day_close_ratio','']
    assert result.iloc[2].pre_close==4.
    subset=policy.guard_frame(data.iloc[[2]],required_fields=('close',))
    assert subset.iloc[0].continuity_segment_id==2 and subset.iloc[0].pre_close==4.
    again=policy.guard_frame(result,required_fields=('close',))
    assert again.equals(result) and again.continuity_segment_id.tolist()==[1,2,2]
