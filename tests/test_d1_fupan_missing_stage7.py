"""Independent fupan recovery retains Stage7 failure without creating rows."""
import csv
import json
from pathlib import Path
import pytest
import os
if os.environ.get("D1_FUPAN_RUNTIME_CANDIDATE"):
    import runpy
    runpy.run_path(os.environ["D1_FUPAN_RUNTIME_CANDIDATE"])["load_candidate"]()
from domains import d1_review_source_producer as source
from domains.d1_review_lane_producer import ensure_preopen_lane_artifacts
from ops import materialize_d1_review_lanes as owner

DAY='20261111';TARGET='20261112'
GAP='SELECTION_ERROR:ResearchContextError:RESEARCH_SOURCE_WITNESS_INVALID:HOURLY_COMPLETION_WITNESS_MISSING'

def inputs(stage7):
    plate={'result':'success','html':"<div class='list-group-item ztitem'><b>测试主题</b><table><tr style='row'><td>测试股</td><td>600000</td><td>10.0</td><td>1.0%</td></tr></table></div>"}
    payload=dict(trade_date=DAY,stage_id='STAGE_1445_1500',selection_status='PARTIAL_WITH_ROWS'if stage7 else 'CANNOT_CONFIRM',rows={'A':[dict(code='A.600000',pool_rank=1,pool_score=7)]if stage7 else [],'HK':[]},cannot_confirm=[]if stage7 else[GAP],source_summary={'cannot_confirm':[]if stage7 else[GAP]},market_status={'A_SHARE':'PARTIAL_WITH_ROWS'if stage7 else'CANNOT_CONFIRM'},production_allowed=False,buy_gate_updated=False,orders_sent=False)
    return dict(trade_date=DAY,public_files={'plate.json':json.dumps(plate).encode()},public_manifest_sha256='a'*64,selector_rows=[dict(trade_date=DAY,ts_code='600000.SH',name='测试股',pct_chg=1.0,amount=100000000)],selector_sha256='b'*64,stage_inputs={'STAGE_1445_1500':payload})

def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='')as handle:return list(csv.DictReader(handle))

def test_fupan_missing_stage7_keeps_real_rows_scores_and_no_synthetic_stage7(tmp_path):
    data=inputs(False)
    with pytest.raises(ValueError,match='evidence incomplete'):
        source.materialize_d1_review_sources(**data,output_dir=tmp_path/'strict')
    assert not (tmp_path/'strict').exists()
    receipt=source.materialize_d1_review_sources(**data,output_dir=tmp_path/'partial',fupan_only=True)
    assert receipt['status']=='PARTIAL'and receipt['counts']['stage7_tail_replay']==0
    assert GAP in receipt['cannot_confirm']
    assert not (tmp_path/'partial/stage7_tail_replay.csv').exists()
    diagnostic=json.loads((tmp_path/'partial/stage7_tail_replay.manifest.json').read_text())
    assert diagnostic['status']=='CANNOT_CONFIRM'and diagnostic['row_count']==0
    lane=ensure_preopen_lane_artifacts(TARGET,signal_date=DAY,source_dir=tmp_path/'partial',output_dir=tmp_path/'lanes-partial',fupan_only=True)
    assert lane['ok']is True and lane['stage7_row_count']==0
    assert lane['stage7_source_role']=='STAGE7_NOT_MATERIALIZED'
    assert GAP in lane['cannot_confirm']
    assert not (tmp_path/'lanes-partial/stage7.csv').exists()
    assert not (tmp_path/'lanes-partial/stage7.manifest.json').exists()
    assert not (tmp_path/'lanes-partial/_stage7_evidence').exists()
    manifest=json.loads((tmp_path/'lanes-partial/fupan.manifest.json').read_text(encoding='utf-8-sig'))
    assert manifest['status']=='FUPAN_WATCHLIST_POOL_READY_DATA_PARTIAL'
    assert GAP in manifest['cannot_confirm']
    # Same public/selector role inputs, with valid Stage7 in the original path.
    # Fupan scores/ranks must remain those of the unchanged original formula.
    source.materialize_d1_review_sources(**inputs(True),output_dir=tmp_path/'control')
    ensure_preopen_lane_artifacts(TARGET,signal_date=DAY,source_dir=tmp_path/'control',output_dir=tmp_path/'lanes-control')
    key=lambda r:(r['ts_code'],r['pool_rank'],r['pool_score'],r['role'],r['theme'])
    assert list(map(key,rows(tmp_path/'lanes-partial/fupan.csv')))==list(map(key,rows(tmp_path/'lanes-control/fupan.csv')))
    for flag in ['production_allowed','buy_gate_updated','orders_sent']:
        assert receipt[flag]is False and manifest[flag]is False
    before=(tmp_path/'lanes-partial/fupan.manifest.json').read_bytes()
    again=ensure_preopen_lane_artifacts(TARGET,signal_date=DAY,source_dir=tmp_path/'partial',output_dir=tmp_path/'lanes-partial',fupan_only=True)
    assert again['ok']is True and GAP in again['cannot_confirm']
    assert again['status']=='PREOPEN_D1_FUPAN_READY_STAGE7_MISSING_EXISTING'
    assert again['stage7_row_count']==0 and again['stage7_source_role']=='STAGE7_NOT_MATERIALIZED'
    assert (tmp_path/'lanes-partial/fupan.manifest.json').read_bytes()==before

def test_selector_reader_handles_exact_int_day_for_physical_and_logical(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from ops.research_panel_logical import descriptor,anchor_bytes
    table=pa.table(dict(trade_date=[20261110,20261111],ts_code=['600000.SH']*2,name=['测试股']*2,pct_chg=[0.,1.],amount=[1.,2.]))
    physical=tmp_path/'physical.parquet';pq.write_table(table,physical)
    logical=tmp_path/'logical.parquet';logical.write_bytes(anchor_bytes(table.schema,[descriptor(physical)],rows=2))
    assert owner._selector_rows(physical,DAY)==owner._selector_rows(logical,DAY)
    assert len(owner._selector_rows(logical,DAY))==1
    with pytest.raises(ValueError,match='no exact-date'):
        owner._selector_rows(logical,'20261112')

def test_public_or_selector_missing_does_not_create_fupan(tmp_path):
    missing=inputs(False);missing['selector_rows']=[]
    with pytest.raises(ValueError,match='selector close rows missing'):
        source.materialize_d1_review_sources(**missing,output_dir=tmp_path/'missing',fupan_only=True)
    missing=inputs(False);missing['public_files']={}
    with pytest.raises(ValueError,match='plate source missing'):
        source.materialize_d1_review_sources(**missing,output_dir=tmp_path/'missing',fupan_only=True)
    assert not (tmp_path/'missing').exists()


def test_failed_stage_receipt_reason_is_preserved_without_rows(tmp_path,monkeypatch):
    class Consumer:
        def __init__(self,*_a):pass
        def get(self,day,stage,**_kw):return dict(status='CANNOT_CONFIRM',markets={'A_SHARE':dict(rows=[],status='CANNOT_CONFIRM')})
    monkeypatch.setattr(owner,'StageSelectionConsumer',Consumer)
    path=tmp_path/'receipts'/DAY/'STAGE_1445_1500/receipt.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(trade_date=DAY,stage_id='STAGE_1445_1500',markets={'A_SHARE':dict(cannot_confirm=[GAP])},production_allowed=False,buy_gate_updated=False,orders_sent=False)))
    payload=owner._stage_inputs(tmp_path/'data',DAY,stage_selection_root=tmp_path/'selection',stage_receipt_root=tmp_path/'receipts')['STAGE_1445_1500']
    assert payload['rows']['A']==[]and GAP in payload['cannot_confirm']
    assert payload['source_summary']['failure_receipt']['path']==str(path)
