import copy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from ops import research_panel_chart_blocks as blocks
from ops import render_original_formula_projection as render


def rows(last,revision=False):
    return [dict(trade_date=d,ohlcv=dict(trade_date=d,open=1.,high=2.,low=.5,close=1.5,vol=100.),
        values={f'f{i}':(-1 if revision and d==20261109 else i) for i in range(51)},
        drawings=[dict(id=i+1,kind='DRAWTEXT',styles=[],condition=False,y=None,payload='test')for i in range(22)])for d in range(20261109,last+1)]


def context(tmp_path,date):
    inventory=dict(assignments=[dict(name=f'f{i}')for i in range(51)],drawings=[dict(id=i+1,kind='DRAWTEXT',styles=[])for i in range(22)])
    engine=SimpleNamespace(inventory=lambda:inventory,json_ready=lambda x:x)
    config=dict(formula=dict(sha256=render.FORMULA_SHA),engine=dict(sha256=render.ENGINE_SHA))
    return SimpleNamespace(root=tmp_path,target=date,generation='generation'+str(date),identity=dict(input_sha256='input'+str(date),basis=dict(price_basis='QFQ_ASOF',volume_basis='QFQ_EVENT_VOLUME')),
        config=config,config_ref=dict(path='frozen.config',sha256='config'),calendars={'SZ':[20261109,20261110,20261111]},engine=lambda:engine)


def result(date,revision=False):return dict(formula_sha256=render.FORMULA_SHA,mode='prefix',field_count=51,drawing_count=22,rows=rows(date,revision))


def finalize(c,parts):
    symbol='000001.SZ';r=blocks.ref(parts/'original_retained'/f'{symbol}.json.gz')
    product=dict(rows=[dict(symbol=symbol)],row_refs={symbol:dict(path='row.json',sha256='row')})
    version=c.root/'versions'/str(c.target);version.mkdir(parents=True,exist_ok=True)
    manifest=version/'manifest.json';manifest.write_text('{}')
    return render.finalize_owner_charts(c,parts,product,blocks.ref(manifest),dict(path='product.json',sha256='product'),gaps={})


def test_delta_retention_shared_html_virtual_projection_no_automatic_png(tmp_path):
    c=context(tmp_path,20261110);parts=tmp_path/'parts10'
    bars=[r['ohlcv']for r in result(c.target)['rows']]
    render.retain_owner_result(c,parts,'000001.SZ',bars,result(c.target))
    old=finalize(c,parts);assert old['status']=='OWNER_CHARTS_COMPLETED'
    (tmp_path/'index.json').write_text(json.dumps(dict(original_charts={'20261110':old})))
    c=context(tmp_path,20261111);parts=tmp_path/'parts11';allrows=result(c.target)
    render.retain_owner_result(c,parts,'000001.SZ',[r['ohlcv']for r in allrows['rows']],allrows)
    source=blocks.ref(parts/'original_retained/000001.SZ.json.gz')
    delta=blocks.decode(blocks.checked(source));assert len(delta['formula_result']['rows'])==1
    assert len(delta['history_blocks'])==1
    assert blocks.retained(source)['formula_result']==allrows
    current=finalize(c,parts);assert current['status']=='OWNER_CHARTS_COMPLETED'
    item=json.loads(blocks.checked(current['manifest']))['samples']['000001.SZ']
    assert item['PNG'] is None and item['png_export']=='ON_USER_REQUEST_CANVAS'
    assert len(list(tmp_path.rglob('*.html')))==1
    assert not list(tmp_path.rglob('*.png'))
    assert not list(tmp_path.rglob('*.projection.json.gz'))
    decoded=json.loads(gzip.decompress(blocks.projection_bytes(item['projection'])))
    assert decoded['formula_result']==allrows
    assert decoded['source']['generation_id']==c.generation
    assert json.loads(blocks.checked(item['projection']['spec']))['source_cache']==item['source_cache']
    # A second finalize reuses immutable sidecars, even after a process restart.
    before={str(p):p.read_bytes()for p in tmp_path.rglob('*')if p.is_file()}
    assert finalize(c,parts)==current
    assert {str(p):p.read_bytes()for p in tmp_path.rglob('*')if p.is_file()}==before


def test_real_row_revisions_retained_and_bad_source_rejected(tmp_path):
    c=context(tmp_path,20261110);parts=tmp_path/'old';render.retain_owner_result(c,parts,'000001.SZ',[r['ohlcv']for r in result(c.target)['rows']],result(c.target));old=finalize(c,parts)
    (tmp_path/'index.json').write_text(json.dumps(dict(original_charts={'20261110':old})))
    c=context(tmp_path,20261111);parts=tmp_path/'new';render.retain_owner_result(c,parts,'000001.SZ',[r['ohlcv']for r in result(c.target,True)['rows']],result(c.target,True))
    source=blocks.ref(parts/'original_retained/000001.SZ.json.gz')
    assert len(blocks.decode(blocks.checked(source))['formula_result']['rows'])==2
    assert blocks.retained(source)['formula_result']==result(c.target,True)
    previous=Path(blocks.decode(blocks.checked(source))['history_blocks'][0]['path']);previous.write_bytes(previous.read_bytes()+b'x')
    with pytest.raises(ValueError,match='SHA_DRIFT'):blocks.retained(source)


def test_shared_html_transport_is_same_origin_bound_and_export_only():
    html=blocks.shared_html(render.pinned(render.OWNER_RENDERER))
    assert "u.origin!==location.origin" in html
    assert "crypto.subtle.digest('SHA-256'" in html
    assert "CHART_METADATA_IDENTITY" in html and "CHART_DECOMPRESSED_LIMIT" in html
    assert "toDataURL('image/png')" in html and '导出当前图 PNG' in html
    assert 'const projectionGzip=' not in html


def test_shared_html_actual_isolated_canvas(tmp_path):
    import base64,subprocess,hashlib
    projection=dict(symbol='000001.SZ',data_date='20261111',formula_result=result(20261111),
        source=dict(generation_id='fixture',source_input_sha256='input',price_basis='QFQ_ASOF',volume_basis='QFQ_EVENT_VOLUME',adjustment_convention='fixture'),
        lineage={},**blocks.FLAGS)
    raw=gzip.compress(blocks.canonical(projection),mtime=0)
    metadata=dict(status='READY',symbol='000001.SZ',data_date='20261111',source_generation='fixture',input_sha256='input',rows=3,
        assets=dict(projection=dict(url='/projection',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))))
    payload=dict(html=blocks.shared_html(render.pinned(render.OWNER_RENDERER)),metadata=metadata,projection=base64.b64encode(raw).decode())
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    run=subprocess.run([node,str(Path(__file__).with_name('chart_blocks_browser.cjs'))],input=json.dumps(payload),text=True,capture_output=True,timeout=50)
    assert run.returncode==0,run.stderr
    outcome=json.loads(run.stdout);assert outcome['status']=='PASS' and outcome['automatic_png_requests']==0


def test_original_api_reader_and_host_bind_virtual_projection(tmp_path):
    from infrastructure.research_lane_source import ResearchLaneSource
    from infrastructure.research_workbench_host import ResearchWorkbenchHost
    import threading
    c=context(tmp_path,20261111);config_path=tmp_path/'config.json';config_path.write_bytes(blocks.canonical(c.config));c.config_ref=blocks.ref(config_path)
    parts=tmp_path/'parts';values=result(c.target)
    render.retain_owner_result(c,parts,'000001.SZ',[r['ohlcv']for r in values['rows']],values)
    descriptor=finalize(c,parts)
    product=dict(status='READY',data_date='20261111',source_generation=c.generation,source_identity=c.identity,source_config=c.config_ref,
        rows=[dict(symbol='000001.SZ')],row_refs={'000001.SZ':dict(path='row.json',sha256='row')},
        manifest=descriptor['numeric_manifest'],artifact=dict(path='product.json',sha256='product'),original_charts=descriptor)
    source=ResearchLaneSource.__new__(ResearchLaneSource);source.original_chart_binding=None;source.original_chart_artifact_root=tmp_path;source._a_product_root=lambda:tmp_path
    bind=dict(artifact_root=str(tmp_path),manifest=descriptor['manifest'],receipt=descriptor['receipt'])
    meta=source._read_original_chart_product(product,'000001.SZ',generation=c.generation,input_sha256=c.identity['input_sha256'],binding_override=bind)
    assert set(meta['assets'])=={'html','projection'} and meta['status']=='READY'
    reference=meta['assets']['projection']
    asset=source._read_original_chart_product(product,'000001.SZ',asset='projection',asset_sha256=reference['sha256'],binding_override=bind)
    assert json.loads(gzip.decompress(asset['_asset_bytes']))['formula_result']==values
    with pytest.raises(ValueError,match='ASSET_SHA_CONFLICT'):source._read_original_chart_product(product,'000001.SZ',asset='png',asset_sha256='0'*64,binding_override=bind)
    with pytest.raises(ValueError,match='PRODUCT_IDENTITY_CONFLICT'):source._read_original_chart_product(product,'000001.SZ',generation='wrong',binding_override=bind)
    host=ResearchWorkbenchHost.__new__(ResearchWorkbenchHost);host.source=source;host._view=lambda *a:product;host._is_skill_date=lambda *a:False;host._lock=threading.RLock();host._chart_cache={}
    view=host.chart_views('2026-11-11')
    assert 'image_url' not in view['charts']['rows'][0] and 'html_url' in view['charts']['rows'][0]
    projection=view['projections']['rows'][0]
    assert projection['bytes']==reference['bytes'] and projection['encoding']=='gzip' and projection['sha256']==reference['sha256']
