"""Display projection is read-only and never changes recorded research decisions."""
import copy,csv,hashlib,json,io
from types import SimpleNamespace as NS
from pathlib import Path
from v4.manager_workbench.display_read import saved_names,display_stock,us_summary
sha=lambda b:hashlib.sha256(b).hexdigest()

def fixture(tmp_path):
 base='assets/hk_security_master/runs/20261012/run';raw=b'code,name\nHK.09927,Test saved name\n';manifest=dict(schema_version='v3_shared_data.hk_security_master_manifest.v1',trade_date='20261012',captured_at='2026-10-12T17:30:00+08:00',artifact_relative='runs/20261012/run/artifact.csv',artifact_sha256=sha(raw),row_count=1)
 m=json.dumps(manifest).encode();r=json.dumps(dict(manifest_sha256=sha(m))).encode()
 for path,data in [('artifact.csv',raw),('manifest.json',m),('receipt.json',r)]:
  p=tmp_path/base/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 ref=NS(role='HK_SECURITY_MASTER',verification=NS(value='VERIFIED'),artifact_ref=base+'/artifact.csv',sha256=sha(raw),source_session='20261012',manifest_ref=base+'/manifest.json',available_at='2026-10-12T17:30:00+08:00',owner='v3_shared_data')
 pin=dict(manifest_relative=base+'/manifest.json',manifest_sha256=sha(m),checked_files=[dict(relative=base+'/receipt.json',sha256=sha(r))])
 snap=NS(context=NS(scope_refs={'owner_bindings':{'security_master':pin}},cutoff='2026-10-13T20:00:00+08:00',source_sessions={'hk_price':'20261012'}),lanes=[NS(evidence_refs=[ref])])
 return snap,ref

def test_exact_saved_name_only_and_never_mutates_record(tmp_path):
 snap,ref=fixture(tmp_path);names=saved_names(snap,tmp_path);stock=dict(symbol='HK.09927',name=None,decision='SELECTED',metrics={'close':'38.92'});before=copy.deepcopy(stock)
 shown=display_stock(stock,names);assert shown['name']=='Test saved name' and shown['name_source']['display_only']
 assert stock==before and shown['decision']==stock['decision']
 assert display_stock(dict(stock,name='Original saved name'),names)['name']=='Original saved name'
 assert display_stock(dict(stock,symbol='HK.99999'),names)['name'] is None


def test_bad_sha_late_identity_and_conflicting_name_fail_closed(tmp_path):
 snap,ref=fixture(tmp_path);ref.sha256='0'*64;assert saved_names(snap,tmp_path)=={}
 snap,ref=fixture(tmp_path);ref.available_at='2026-10-14T00:00:00+08:00';assert saved_names(snap,tmp_path)=={}
 snap,ref=fixture(tmp_path);snap.context.source_sessions['hk_price']='20261013';assert saved_names(snap,tmp_path)=={}
 snap,ref=fixture(tmp_path);(tmp_path/ref.artifact_ref).write_bytes(b'corrupt newer data');assert saved_names(snap,tmp_path)=={}


def test_summary_preserves_us_source_units_and_mixed_decisions():
 rows=[dict(us_symbol='NVDA',symbol='HK.00992',decision='UNASSESSED'),dict(us_symbol='NVDA',symbol='HK.01810',decision='UNASSESSED'),dict(us_symbol='LITE',symbol='HK.06166',decision='NOT_SELECTED'),dict(us_symbol='XLP',symbol=None,decision='UNASSESSED')]
 original=copy.deepcopy(rows);lane=NS(lane=NS(value='US_MAPPING'),rows=rows,coverage=NS(model_dump=lambda **k:{'scope_count':33}),gaps=[])
 snap=NS(lanes=[lane],run_id='saved-run');s=us_summary(snap,{})
 assert (s['source_symbol_count'],s['source_row_count'],s['relation_row_count'],s['mapped_hk_count'])==(3,4,3,3)
 assert s['source_decision_counts']['SELECTED']==0 and s['source_decision_counts']['UNASSESSED']==2
 assert rows==original
 rows.append(dict(us_symbol='NVDA',symbol='HK.02015',decision='NOT_SELECTED'));s=us_summary(snap,{})
 assert s['mixed_source_count']==1 and s['source_decision_counts']['UNASSESSED']==1
