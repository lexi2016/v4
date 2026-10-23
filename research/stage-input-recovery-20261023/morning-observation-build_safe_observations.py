"""One-shot, cache-only derivation. No acquisition/runner/model inference is invoked."""
from pathlib import Path
import csv,hashlib,io,json,sys
from types import SimpleNamespace

E=Path('/Users/lexi/Desktop/学习/agents调试/V4_STAGE_INPUT_RECOVERY_20261023/morning-observation')
S=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage')
POOL=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
RUNTIME=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/stage-input-recovery-20261023-stage-r1/app')
sys.path.insert(0,str(RUNTIME))
from stage_center.acquisition import SourceResult
from stage_center.runner import _attach_hk_authority
from stage_center.live_collectors import production_selection_builders
from stage_center.selection import SelectionStore,HK_FULL_POOL_ALGORITHM_SHA256

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,value):p.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def build(stage, output_root=None):
 b=json.loads((E/'frozen-bindings.json').read_text())[stage]
 for rel,expected in b['files'].items():assert sha(S/rel)==expected,rel
 assert sha(POOL/'preselection_pools/20261023/hkconnect_d1_top100.json')=='e8921f1eadf3cbac3d63fe2b012e5c9ac25652af08a68681886fc179b540dbef'
 original=json.loads((S/b['selection_manifest']).read_text())['selection_envelope']
 assert original['algorithm_sha256']==HK_FULL_POOL_ALGORITHM_SHA256=='f2991c472b17742acfd3adb81458ff13826f99dfb7b8a223ad8d6a5dfbbd1a1e'
 starts={'STAGE_0930_0935':'09:31:00','STAGE_0935_0940':'09:36:00','STAGE_0940_0945':'09:41:00','STAGE_0945_1030':'09:46:00'}
 ends={'STAGE_0930_0935':'09:34:00','STAGE_0935_0940':'09:39:00','STAGE_0940_0945':'09:44:00','STAGE_0945_1030':'10:29:00'}
 lo='2026-10-23 '+starts[stage];hi='2026-10-23 '+ends[stage];count=44 if stage=='STAGE_0945_1030' else 4
 capture=json.loads((S/b['capture_relative']).read_text());bars={code:[] for code in capture['codes']}
 for row in capture['rows']:
  if lo<=row['time_key']<=hi:bars[row['code']].append(row)
 rawrows=list(csv.DictReader((S/b['raw_artifact']).open(encoding='utf-8-sig')))
 for r in rawrows:
  bs=sorted(bars[r['code']],key=lambda x:x['time_key']);assert len(bs)==count;assert bs[0]['time_key']==lo and bs[-1]['time_key']==hi
  r.update(open_price=bs[0]['open'],last_price=bs[-1]['close'],high_price=max(x['high'] for x in bs),low_price=min(x['low'] for x in bs),volume=sum(x['volume'] for x in bs),turnover=sum(x['turnover'] for x in bs),update_time=hi,bar_time=hi[-8:],window_start=lo,window_end=hi,bar_count=count,temporal_cutoff_safe=False)
 # This is an explicitly derived observation input; original raw artifacts are untouched.
 dest=(Path(output_root) if output_root else E/'observations/20261023')/stage
 assert not dest.exists(), 'Never overwrite a prior observation packet'
 dest.mkdir(parents=True)
 stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=list(rawrows[0]));writer.writeheader();writer.writerows(rawrows)
 derived=dest/'derived_raw.csv';derived.write_bytes(stream.getvalue().encode('utf-8-sig'));rawsha=sha(derived)
 evidence=tuple(dict.fromkeys([*original['source_evidence'],
  'historical_observation_contract=HK_MORNING_CONSERVATIVE_INTERSECTION_20261023_R1',
  'bar_interval_semantics=CANNOT_CONFIRM','boundary_bars_excluded=true',
  f'observation_safe_label_start={lo}',f'observation_safe_label_end={hi}',
  f'observation_derived_raw_sha256={rawsha}', 'original_formal_result_unchanged=true']))
 source=SourceResult('futu','CANNOT_CONFIRM',tuple(rawrows),('HK_ACTIVE_SNAPSHOT_UNAVAILABLE',),requested_rows=100,source_evidence=evidence)
 source=_attach_hk_authority(source,d1_root=POOL,second_root=None,preselection_source_root=POOL,trade_date='20261023',stage_id=stage)
 plan=SimpleNamespace(trade_date='20261023',stage_id=stage)
 raw=dict(artifact_sha256=rawsha,status='CANNOT_CONFIRM',requested_rows=100,missing_symbols=[],cannot_confirm=['HK_ACTIVE_SNAPSHOT_UNAVAILABLE'],source_evidence=list(evidence),cutoff_at=b['cutoff_at'])
 scorer=production_selection_builders(stage)['HK_CONNECT']
 envelope=scorer(source,plan,raw)
 assert len(envelope['rows'])==10 and envelope['source_rows']==100
 assert envelope['algorithm_sha256']==original['algorithm_sha256']
 assert all(r['formal_eligible'] is False and r['action_level']=='NO_BUY' for r in envelope['rows'])
 store=SelectionStore(dest/'selection');store.publish(envelope,market='HK_CONNECT');assert store.read_verified('20261023',stage,'HK_CONNECT')==envelope
 sourcefiles={str(p.relative_to(RUNTIME)):sha(p) for p in [RUNTIME/'stage_center/selection.py',RUNTIME/'stage_center/_selection_parts/hk_four_lanes.py',RUNTIME/'stage_center/_selection_parts/hk_scoring.py',RUNTIME/'stage_center/_live_collectors_parts/selection_builder_registry.py'] if p.exists()}
 metadata=dict(trade_date='20261023',stage_id=stage,source_id='FUTU_K_1M',source_capture_sha256=b['capture_sha256'],captured_at=b['captured_at'],asof_cutoff=b['cutoff_at'],safe_label_start=lo,safe_label_end=hi,bars_per_code=count,window_bar_count=count*100,boundary_bars_excluded=True,bar_interval_semantics='CANNOT_CONFIRM',stage_window_coverage='CONSERVATIVE_INTERSECTION_ONLY',native_snapshot_available=False,original_run_id=b['run_id'],selection_run_id=envelope['run_id'],raw_artifact_sha256=rawsha,algorithm_id=envelope['algorithm_id'],algorithm_sha256=envelope['algorithm_sha256'],topn_contract='selection_contract=V3_TOP10_RECOMMENDATION',scorer_files=sourcefiles,network_calls=0,model_inference_calls=0,stage_owner_calls=0,formal_eligible=False,natural=False,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 dump(dest/'observation_receipt.json',metadata)
 return metadata
if __name__=='__main__':
 stage=sys.argv[1];print(json.dumps(build(stage, sys.argv[2] if len(sys.argv)>2 else None),ensure_ascii=False))
