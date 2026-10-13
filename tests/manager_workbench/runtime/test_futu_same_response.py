from copy import deepcopy
from pathlib import Path
import json,shutil
import pytest
from test_native_pipeline import fixture
from test_integration import context
from v4.manager_workbench.inputs.native import NativeAdapters
from v4.manager_workbench.inputs.validation import raw_sha,owner_digest
from v4.manager_workbench.contracts import Lane
from v4.manager_workbench.engines.oversold import screen_one,run_oversold
ROOT=Path(__file__).resolve().parents[3]
REAL=ROOT/'docs/handoff/manager-workbench-implementation-20261013/.tmp/futu-61-session-canary-r1'

@pytest.fixture(autouse=True)
def active_calendar(monkeypatch):
    # The real response was requested against the accepted active calendar,
    # not the historical Mac checkout calendar. Its original identity is pinned.
    from contracts.trading_calendar import load_market_calendar
    from v4.manager_workbench.inputs import native
    path=ROOT/'docs/handoff/manager-workbench-implementation-20261013/deployment-deltas/isolated-api-candidate-v7-final/app/contracts/market_calendar_2026.json'
    assert raw_sha(path.read_bytes())=='9e2638b69e25495478cecb6ed551713178fcb989a63ebb4ecfd59689615f0acb'
    monkeypatch.setattr(native,'CALENDAR_PATH',path)
    monkeypatch.setattr(native,'load_market_calendar',lambda:load_market_calendar(path))


def prepared(tmp_path,count=1):
 cfg=fixture(tmp_path,count=count);source=tmp_path/'existing-owner-response';source.mkdir()
 for n in ('raw.json','receipt.json'):shutil.copyfile(REAL/n,source/n)
 pin=dict(source_local_path=str(source),raw_relative='raw.json',raw_sha256=raw_sha((source/'raw.json').read_bytes()),receipt_relative='receipt.json',receipt_sha256=raw_sha((source/'receipt.json').read_bytes()),symbol='HK.00001')
 cfg.source_bindings['hk_panel']['20261012']['futu_history']=[pin]
 # Remaining scope has no proven units, not synthetic positive evidence.
 for k in ('currency','price_basis','volume_unit'):cfg.source_bindings['hk_panel']['20261012'].pop(k)
 a=NativeAdapters(cfg);c=a.prepare_context(context(cutoff='2026-10-13T17:00:00+08:00'))
 return cfg,a,c,pin


def test_real_61_bars_complete_full692_scope_and_true_not_selected(tmp_path):
 cfg,a,c,pin=prepared(tmp_path,count=692);b=a.load(Lane.OVERSOLD,c)
 out=run_oversold(c.model_dump(mode='json'),b.model_dump(mode='json'))
 assert len(out['rows'])==692 and out['coverage']['scope_count']==692
 one=next(r for r in out['rows'] if r['symbol']=='HK.00001')
 assert one['decision']=='NOT_SELECTED' and one['reason']=='NEITHER_OVERSOLD_CONDITION'
 assert one['metrics']['close']=='66.2' and one['metrics']['max_high_60']=='74.4'
 assert one['metrics']['price_pass'] is False and one['metrics']['volume_pass'] is False
 assert one['metrics']['source_price_unit'] is None and one['metrics']['source_volume_unit'] is None
 assert len([r for r in out['rows'] if r['decision']=='UNASSESSED'])==691
 assert b.records[0]['owner']=='FUTU' and b.records[0]['comparison_basis']['raw_sha256']==pin['raw_sha256']


@pytest.mark.parametrize('change',['mixed_bar','security','request','adjustment','missing_session','bar_request','bar_receipt'])
def test_same_response_required_and_existing_thresholds_unchanged(tmp_path,change):
 cfg,a,c,pin=prepared(tmp_path);row=a.load(Lane.OVERSOLD,c).records[0];bad=deepcopy(row)
 if change=='mixed_bar':bad['high_history60'][0]['source_metadata']['raw_sha256']='0'*64
 elif change=='security':bad['volume_history5'][0]['source_metadata']['code']='HK.00002'
 elif change=='request':bad['comparison_basis']['request']['request']['ktype']='K_1M'
 elif change=='adjustment':bad['comparison_basis']['adjustment']='UNKNOWN'
 elif change=='bar_request':bad['volume_history5'][0]['source_metadata']['request']['request']['autype']='QFQ'
 elif change=='bar_receipt':bad['volume_history5'][0]['source_metadata']['receipt_sha256']='0'*64
 else:bad['high_history60'].pop()
 assert screen_one(c.model_dump(mode='json'),bad)['decision']=='UNASSESSED'


@pytest.mark.parametrize('change',['raw','receipt','late'])
def test_raw_receipt_and_cutoff_failclosed_but_other_scope_not_lost(tmp_path,change):
 cfg,a,c,pin=prepared(tmp_path,count=2)
 if change=='raw':(Path(pin['source_local_path'])/'raw.json').write_text('[]')
 elif change=='receipt':pin['receipt_sha256']='0'*64
 else:c.cutoff='2026-10-13T16:21:01+08:00'
 b=a.load(Lane.OVERSOLD,c)
 assert len(b.records)==2 and b.gaps
 assert all('comparison_basis' not in r for r in b.records)
 assert all(screen_one(c.model_dump(mode='json'),r)['decision']=='UNASSESSED' for r in b.records)
