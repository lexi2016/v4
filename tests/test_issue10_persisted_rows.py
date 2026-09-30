"""Synthetic JSON evidence fixtures, not market-data or pipeline acceptance."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import pytest


def api():
    assert importlib.util.find_spec('ops.inspect_hk_observation_rows') is not None
    return importlib.import_module('ops.inspect_hk_observation_rows')


def data():
    codes = [f'HK.{i:05}' for i in range(1,65)]
    source = {'source_id':'pytdx_exhq','status':'PARTIAL_WITH_ROWS','requested_rows':64,
        'missing_symbols':[], 'cannot_confirm':['HK_FUTU_HISTORICAL_ACTIVE_SNAPSHOT_UNAVAILABLE'],
        'source_evidence':['fixture=SYNTHETIC_NOT_MARKET_DATA'],
        'rows':[{'code':c,'update_time':'2026-09-30 13:14:00','bar_count':14} for c in codes]}
    return codes,source


def test_64_reported_and_three_saved_are_not_complete():
    codes,src=data();src['rows']=src['rows'][:3]
    out=api().inspect_rows(src,codes,trade_date='20260930',stage_id='STAGE_1300_1315')
    assert out['status']=='INCOMPLETE_OR_INVALID'
    assert out['persisted_unique_rows']==3 and out['requested_code_count']==64
    assert out['unaccounted_code_count']==61
    assert out['observation_pool_admitted'] is False


def test_all_rows_are_counted_without_implying_pool_or_natural_success():
    codes,src=data();before=deepcopy(src)
    out=api().inspect_rows(src,codes,trade_date='20260930',stage_id='STAGE_1300_1315')
    assert out['status']=='ROW_ACCOUNTING_COMPLETE'
    assert out['persisted_unique_rows']==64 and out['source_limitations']==src['cannot_confirm']
    for name in ('bar_series_verified','observation_pool_admitted','stage_selection_generated',
                 'api_ui_verified','production_allowed','buy_gate_updated','orders_sent','write_performed'):
        assert out[name] is False
    assert src==before


@pytest.mark.parametrize('mutation', ['duplicate','outside','request_count','sample','missing_overlap',
    'wrong_date','after_cutoff','subsecond_after_cutoff','unsafe_stage','unsafe_date','source_failure','bad_codes','empty'])
def test_invalid_or_unproven_inputs_are_not_counted_as_complete(mutation):
    codes,src=data();date='20260930';stage='STAGE_1300_1315'
    if mutation=='duplicate': src['rows'][-1]=deepcopy(src['rows'][0])
    elif mutation=='outside': src['rows'][0]['code']='HK.99999'
    elif mutation=='request_count': src['requested_rows']=63
    elif mutation=='sample': src['sample']=src.pop('rows')[:3]
    elif mutation=='missing_overlap':src['missing_symbols']=[codes[0]]
    elif mutation=='wrong_date':src['rows'][0]['update_time']='2026-09-29 13:14:00'
    elif mutation=='after_cutoff':src['rows'][0]['update_time']='2026-09-30 13:15:01'
    elif mutation=='subsecond_after_cutoff':src['rows'][0]['update_time']='2026-09-30 13:15:00.001'
    elif mutation=='unsafe_stage':stage='STAGE_0930_0935'
    elif mutation=='unsafe_date':date='20261001'
    elif mutation=='source_failure':src['status']='CANNOT_CONFIRM'
    elif mutation=='bad_codes':codes.append(codes[0])
    elif mutation=='empty':src['rows']=[];src['missing_symbols']=codes
    assert api().inspect_rows(src,codes,trade_date=date,stage_id=stage)['status']=='INCOMPLETE_OR_INVALID'


def test_truthful_partial_keeps_all_available_rows_and_exact_missing_set():
    codes,src=data();src['rows']=src['rows'][:63];src['missing_symbols']=[codes[-1]]
    out=api().inspect_rows(src,codes,trade_date='20260930',stage_id='STAGE_1300_1315')
    assert out['status']=='ROW_ACCOUNTING_COMPLETE'
    assert out['persisted_unique_rows']==63 and out['declared_missing_count']==1
    assert out['observation_pool_admitted'] is False


def test_readonly_file_inspection_requires_both_hashes_and_no_directory_search(tmp_path):
    codes,src=data();source=tmp_path/'source.json';request=tmp_path/'codes.json'
    source.write_text(json.dumps(src));request.write_text(json.dumps(codes))
    before={p:p.read_bytes() for p in tmp_path.iterdir()}
    shas=[hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,request)]
    out=api().inspect_files(root=tmp_path,source_relative=source.name,source_sha256=shas[0],
        codes_relative=request.name,codes_sha256=shas[1],trade_date='20260930',stage_id='STAGE_1300_1315')
    assert out['status']=='ROW_ACCOUNTING_COMPLETE' and out['source_file_sha256']==shas[0]
    assert {p:p.read_bytes() for p in tmp_path.iterdir()}==before
    source.write_bytes(source.read_bytes()+b' ')
    with pytest.raises(ValueError,match='SHA'):
        api().inspect_files(root=tmp_path,source_relative=source.name,source_sha256=shas[0],
            codes_relative=request.name,codes_sha256=shas[1],trade_date='20260930',stage_id='STAGE_1300_1315')
