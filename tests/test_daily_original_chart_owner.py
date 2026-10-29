import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ops import research_panel_daily_product as owner
from ops import render_original_formula_projection as renderer
from infrastructure.research_lane_source import ResearchLaneSource
from apps.api.v4_api.research_lane_router import _daily_completion_matches_current_product


def owner_fixture(tmp_path):
    root = tmp_path.resolve() / 'daily_products/a_share'
    calls = {'compute': 0, 'render': 0}
    names = ['f' + str(i) for i in range(51)]
    definitions = [dict(id=i, kind='DRAWICON', styles=[]) for i in range(22)]
    bars = [dict(trade_date=d, open='10', high='11', low='9', close='10', vol='100') for d in (20261028, 20261029)]
    def compute(values, mode):
        calls['compute'] += 1
        return dict(formula_sha256=renderer.FORMULA_SHA, mode=mode, field_count=51, drawing_count=22,
                    rows=[dict(trade_date=b['trade_date'], values=dict.fromkeys(names, 1),
                               drawings=[dict(d, payload='1') for d in definitions]) for b in values])
    engine = SimpleNamespace(compute=compute, json_ready=lambda v: copy.deepcopy(v), boolean=lambda v: False,
                             inventory=lambda: dict(assignments=[dict(name=n) for n in names], drawings=definitions))
    config = dict(formula=dict(path='/no-formula-execution', sha256=renderer.FORMULA_SHA),
                  engine=dict(path='/no-engine-import', sha256=renderer.ENGINE_SHA), census={})
    config_path = tmp_path / 'config.json'; config_path.write_text(json.dumps(config))
    identity = dict(generation='a'*64, input_sha256='b'*64, asof=20261029,
                    basis=dict(price_basis='QFQ_ASOF', volume_basis='QFQ_EVENT_VOLUME'))
    context = SimpleNamespace(root=root, target=20261029, scope=['600025.SH'], generation='a'*64,
        identity=identity, config=config, config_ref=owner.reference(config_path), snapshot_ref=dict(path='/snapshot', sha256='d'*64),
        engine=lambda: engine, core=SimpleNamespace(signals=lambda v: {'membership':'YES'}),
        calendars={'SH':[20261028,20261029,20261030,20261102]}, read=lambda s: (copy.deepcopy(bars), 'fixture'),
        qualify=lambda s: dict(status='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH',history_start_date='20261028'),
        g4_reference=lambda *args: None, unchanged=lambda: None)
    def evaluate(**kwargs):
        return {'groups':{g:{'status':'TRUE' if g=='original' else 'FALSE','reasons':[]} for g in owner.GROUPS}}
    def png(items):
        assert not (root/'events/latest.json').exists()
        calls['render'] += 1
        for item in items: Path(item['png']).write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        return {}
    return context, calls, evaluate, png


def run_owner(context, evaluate, png, **kwargs):
    with patch.object(owner,'SourceContext',return_value=context), patch.object(owner,'_census',return_value=lambda a:(dict(stage='UNKNOWN'),None)):
        return owner.materialize_daily_product(data_root=context.root.parents[1],target=context.target,evaluate=evaluate,
                                               chart_png_renderer=png,**kwargs)


def test_numeric_bytes_parity_single_compute_and_final_completion_order(tmp_path):
    context,calls,evaluate,png=owner_fixture(tmp_path)
    result=run_owner(context,evaluate,png,original_charts=False)
    original_product=Path(result['artifact']['path']).read_bytes(); original_manifest=Path(result['manifest']['path']).read_bytes()
    # Fresh equivalent run in the same exact root: remove only owned checkpoints/history,
    # leaving immutable numeric artifacts in place to enforce byte parity.
    import shutil
    shutil.rmtree(context.root/'checkpoints');shutil.rmtree(context.root/'history');(context.root/'events/latest.json').unlink()
    calls['compute']=0
    charts=run_owner(context,evaluate,png)
    assert Path(charts['artifact']['path']).read_bytes()==original_product
    assert Path(charts['manifest']['path']).read_bytes()==original_manifest
    assert calls=={'compute':1,'render':1}
    source=ResearchLaneSource(tmp_path,a_share_daily_root=tmp_path)
    event=source.read_a_daily_latest_event();product=source.read_a_daily_product()
    assert _daily_completion_matches_current_product(event,product)
    assert event['original_charts']['numeric_manifest']==charts['manifest']
    assert source.read_original_chart('20261029','600025.SH')['status']=='READY'
    bad=copy.deepcopy(event);bad['original_charts']['numeric_manifest']['sha256']='0'*64
    assert not _daily_completion_matches_current_product(bad,product)


def test_render_failure_preserves_numeric_success_and_typed_gap(tmp_path):
    context,calls,evaluate,png=owner_fixture(tmp_path)
    result=run_owner(context,evaluate,lambda items:{'600025.SH':'PNG_FAILED_FIXTURE'})
    assert result['unique_count']==1 and calls['compute']==1
    source=ResearchLaneSource(tmp_path,a_share_daily_root=tmp_path)
    product=source.read_a_daily_product();event=source.read_a_daily_latest_event()
    assert event['original_charts']['status']=='OWNER_CHARTS_PARTIAL'
    assert _daily_completion_matches_current_product(event,product)
    with pytest.raises(ValueError,match='OWNER_TYPED_GAP:PNG_FAILED_FIXTURE'):
        source.read_original_chart('20261029','600025.SH')


def test_changed_projection_sha_is_rejected(tmp_path):
    context,calls,evaluate,png=owner_fixture(tmp_path);run_owner(context,evaluate,png)
    source=ResearchLaneSource(tmp_path,a_share_daily_root=tmp_path)
    result=source.read_original_chart('20261029','600025.SH')
    Path(result['assets']['projection']['path']).write_bytes(b'tampered')
    with pytest.raises(ValueError,match='SHA_DRIFT'):source.read_original_chart('20261029','600025.SH')


def test_non_candidate_never_retains_full_history_or_renders(tmp_path):
    context,calls,evaluate,png=owner_fixture(tmp_path)
    def no_match(**kwargs):
        return {'groups':{g:{'status':'FALSE','reasons':[]} for g in owner.GROUPS}}
    result=run_owner(context,no_match,lambda items:pytest.fail('non-candidate render'))
    assert result['unique_count']==0 and calls['compute']==1
    assert not list((context.root/'checkpoints').rglob('*.gz'))


def test_unsupported_drawing_does_not_discard_numeric_result(tmp_path):
    context,calls,evaluate,png=owner_fixture(tmp_path)
    inventory=context.engine().inventory
    context.engine().inventory=lambda: {**inventory(), 'drawings':[dict(id=i,kind='UNSUPPORTED',styles=[]) for i in range(22)]}
    result=run_owner(context,evaluate,lambda items:pytest.fail('unsupported render'))
    assert result['unique_count']==1 and calls['compute']==1
    source=ResearchLaneSource(tmp_path,a_share_daily_root=tmp_path)
    with pytest.raises(ValueError,match='OWNER_TYPED_GAP:OWNER_DRAWING_UNSUPPORTED'):
        source.read_original_chart('20261029','600025.SH')


def test_source_change_during_finalizer_preserves_artifacts_without_publication(tmp_path):
    context,calls,evaluate,png=owner_fixture(tmp_path)
    changed=False
    def unchanged():
        if changed:raise ValueError('DAILY_GENERATION_CHANGED_DURING_PROJECTION')
    def changed_while_rendering(items):
        nonlocal changed
        result=png(items)
        changed=True
        return result
    context.unchanged=unchanged
    with pytest.raises(ValueError,match='DAILY_GENERATION_CHANGED_DURING_PROJECTION'):
        run_owner(context,evaluate,changed_while_rendering)
    assert not (context.root/'index.json').exists()
    assert not (context.root/'events/latest.json').exists()
    errors=list((context.root/'checkpoints').rglob('publication_error.json'))
    assert len(errors)==1
    error=json.loads(errors[0].read_text())
    assert error['status']=='CANNOT_CONFIRM' and 'SOURCE_CHANGED_BEFORE_PUBLICATION' in error['reason']
    assert Path(error['manifest']['path']).is_file() and Path(error['artifact']['path']).is_file()
    assert list((context.root/'versions').rglob('600025.SH.png'))
    assert list((context.root/'versions').rglob('COMPLETION_RECEIPT.json'))
