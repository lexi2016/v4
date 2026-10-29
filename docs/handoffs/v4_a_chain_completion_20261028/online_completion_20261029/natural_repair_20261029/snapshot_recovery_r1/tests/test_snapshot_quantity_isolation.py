"""Exact reviewer P2: one NaN volume must not prevent good-row publication."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import importlib.util,json,sys
N=Path(__file__).resolve().parents[1]
sys.path.insert(0,'/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-native-window-20261029-r1-stage/app')
spec=importlib.util.spec_from_file_location('quantity_candidate',N/'sources/stage/stage_center/snapshot_recovery.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
def test_nan_volume_quarantines_only_bad_row_encode_and_store_roundtrip(tmp_path):
 snap=json.loads((N/'current_capture/snapshot.json').read_bytes());good=deepcopy(snap['rows'][0]);bad=deepcopy(snap['rows'][1]);bad['volume']=float('nan');snap['rows']=[good,bad]
 codes=[good['symbol'],bad['symbol']];candidate=SimpleNamespace(current_sha256='c'*64,run_id='exact-quantity-isolation')
 observation=R.build_observation(snap,codes,candidate,'20261029','STAGE_0930_0935',{'sha256':'d'*64,'reasons':['HOURLY_COMPLETION_WITNESS_MISSING']},R.now())
 assert len(observation['rows'])==1 and observation['rows'][0]['code']==good['symbol']
 assert observation['rejected_rows']==[{'symbol':bad['symbol'],'reason':'QUOTE_QUANTITY_FIELD_INVALID:volume'}]
 R.encoded(observation)
 store=R.ObservationStore(tmp_path/'selection');result=store.publish(observation,R.encoded(R.sanitize(snap)))
 assert result['observed_rows']==1 and result['rows'][0]['volume']==good['volume']
 assert store.read('20261029','STAGE_0930_0935')==result
 assert result['formal_selected_rows']==0 and result['rows'][0]['score'] is None
