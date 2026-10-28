"""Close review consumes verified historical observations without formal promotion."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from ops import build_close_review as producer
from stage_center.selection import SelectionStore, ALGORITHM_SHA256
from stage_center.contracts import SELECTION_ALGORITHM_ID

DATE = '20261015'
STAGE = 'STAGE_0930_0935'
FLAGS = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)


def publish(root: Path, *, batch='recovered', stage=STAGE, date=DATE, market='HK_CONNECT', natural=False):
    lane = root if natural else root / 'backfill' / batch
    envelope = dict(schema_version='stage_center.selection.v2', trade_date=date, stage_id=stage,
                    market=market, algorithm_id=SELECTION_ALGORITHM_ID, algorithm_sha256=ALGORITHM_SHA256,
                    raw_artifact_sha256='a'*64, source_status='READY', selection_status='PARTIAL_WITH_ROWS',
                    requested_rows=100, source_rows=100, selected_rows=10, coverage_ratio=1.0,
                    missing_symbols=[], rows=[dict(code=f'HK.{i:05d}', market='HK', rank=i, name=f'Name{i}') for i in range(1,11)],
                    source_evidence=[] if natural else ['recovery_mode=HISTORICAL_BACKFILL'],
                    cannot_confirm=[] if natural else ['HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE'], **FLAGS)
    published = SelectionStore(lane).publish(envelope, market=market)
    receipt = root.parent / 'receipts' / 'backfill' / batch / date / stage / 'receipt.json'
    if not natural:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(dict(schema_version='stage_center.runner.receipt.v1', runner='stage_center',
            mode='BACKFILL', backfill_run_id=batch, due_status='HISTORICAL_BACKFILL', trade_date=date, stage_id=stage,
            latest_updated=False, current_updated=False, write_performed=True,
            markets={market:dict(run_id=published['run_id'], artifact_id=published['artifact_id'],
                raw_artifact_sha256=envelope['raw_artifact_sha256'], selection_status=envelope['selection_status'])}, **FLAGS)))
    return lane, published, receipt


def test_valid_backfill_enters_observations_with_bound_proof(tmp_path):
    root=tmp_path/'selection'; publish(root)
    rows,evidence=producer._stage_rows_with_evidence(root,DATE)
    assert len(rows[STAGE])==10
    e=evidence[STAGE]
    assert e['selection_mode']=='BACKFILL' and e['backfill_run_id']=='recovered'
    assert e['runner_receipt_verified'] is True
    assert 'HISTORICAL_BACKFILL_OBSERVATION:recovered' in e['cannot_confirm']
    assert all(len(e[key])==64 for key in ['selection_manifest_sha256','selection_receipt_sha256','selection_artifact_sha256','runner_receipt_sha256'])
    review=producer.build_native_close_review(DATE,close_rows=[],model_rows=[],stage_rows=rows,
        stage_evidence=evidence,close_source_sha256='a'*64)
    assert review['row_counts']['stage_rows']==10
    assert STAGE in review['unverified_stages']
    assert review['stage_union']['evidence_status']=='MISSING'
    assert review['observed_stage_union']['pit_status']=='UNVERIFIED'


@pytest.mark.parametrize('failure',['artifact','manifest','receipt','latest_sha','missing_runner','wrong_runner','wrong_date','wrong_market','conflict'])
def test_invalid_backfill_never_enters_review(tmp_path,failure):
    root=tmp_path/'selection'
    lane,published,runner=publish(root, date='20261014' if failure=='wrong_date' else DATE,
                                market='A_SHARE' if failure=='wrong_market' else 'HK_CONNECT')
    if failure in {'artifact','manifest','receipt'}:
        path=next((lane/'selection_runs').rglob({'artifact':'artifact.csv','manifest':'manifest.json','receipt':'receipt.json'}[failure]))
        path.write_bytes(path.read_bytes()+b'corrupt')
    elif failure=='latest_sha':
        p=lane/'selection_latest.json';d=json.loads(p.read_text());next(iter(d['entries'].values()))['artifact_sha256']='f'*64;p.write_text(json.dumps(d))
    elif failure=='missing_runner': runner.unlink()
    elif failure=='wrong_runner':
        d=json.loads(runner.read_text());d['markets']['HK_CONNECT']['run_id']='unknown';runner.write_text(json.dumps(d))
    elif failure=='conflict':
        publish(root,batch='second')
    rows,_=producer._stage_rows_with_evidence(root,DATE)
    assert rows[STAGE] is None


def test_valid_natural_wins_over_historical(tmp_path):
    root=tmp_path/'selection';publish(root);_,natural,_=publish(root,natural=True)
    rows,e=producer._stage_rows_with_evidence(root,DATE)
    assert len(rows[STAGE])==10 and e[STAGE]['run_id']==natural['run_id']
    assert e[STAGE]['selection_mode'] is None


def context():
    return dict(mode='MANUAL_HISTORICAL_RECOVERY', trade_date=DATE, original_natural_run_id='a'*32,
        original_close_sha256='b'*64, original_import_receipt_sha256='c'*64,
        original_dispatcher_receipt_sha256='d'*64, archive_inventory_sha256='e'*64)


@pytest.mark.parametrize('key,value',[('mode','NATURAL'),('trade_date','20261014'),('original_close_sha256','unknown'),('original_natural_run_id','unknown'),('archive_inventory_sha256',None)])
def test_manual_context_rejects_unknown_or_wrong_identity(key,value):
    c=context();c[key]=value
    with pytest.raises(ValueError,match='manual recovery'):
        producer._manual_recovery_context(c,DATE)


def test_manual_context_has_real_recovery_time_and_does_not_promote_natural():
    c=producer._manual_recovery_context(context(),DATE)
    assert c['mode']=='MANUAL_HISTORICAL_RECOVERY'
    assert c['recovered_at'].endswith('+08:00')
    assert c['original_close_sha256']=='b'*64
    with pytest.raises(ValueError,match='manual recovery'):
        producer._manual_recovery_context({**context(),'extra':'bad'},DATE)
