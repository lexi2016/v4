"""Only the new namespace/wiring/order contract; owner semantic checks are reused."""
import hashlib
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infrastructure.api_namespace import LegacyAliasRoute


def _app(tmp_path,monkeypatch):
    from apps.api.v4_api.app import create_app
    from apps.api.v4_api.opening_observation_service import OpeningObservationService
    calls=[]
    def get(self,**kwargs):
        calls.append(kwargs)
        return {'status':'UNAVAILABLE','symbol':kwargs['symbol'],'trade_date':kwargs['date'],
                'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    monkeypatch.setattr(OpeningObservationService,'get',get)
    panel=tmp_path/'panel';panel.mkdir();payload=b'<html>frozen research entry</html>';(panel/'daily.html').write_bytes(payload)
    manifest=tmp_path/'assets.json';manifest.write_text(json.dumps({'schema_version':'research_panel.assets.v1','files':[{'path':'daily.html','sha256':hashlib.sha256(payload).hexdigest()}]}))
    for k,v in {'V4_RESEARCH_PANEL_ROOT':panel,'V4_RESEARCH_PANEL_ASSET_MANIFEST':manifest,'V4_OPENING_RAW_ROOT':tmp_path/'raw','V4_OPENING_SELECTION_ROOT':tmp_path/'selection'}.items():monkeypatch.setenv(k,str(v))
    app=create_app(data_root=tmp_path/'data',ledger_root=tmp_path/'ledger',stage_center_selection_root=tmp_path/'selection',manager_research_state_root=tmp_path/'manager')
    return app,calls,payload


def test_original42_and_separate_approved_opening_alias_same_handler_once(tmp_path,monkeypatch):
    app,calls,_=_app(tmp_path,monkeypatch);client=TestClient(app)
    original=json.loads((Path(__file__).resolve().parents[1]/'contracts/v4_legacy_api_aliases.json').read_text())['routes']
    aliases={r.path:r for r in app.routes if isinstance(r,LegacyAliasRoute)}
    added='/api/v3/research/opening-observation'
    assert len(original)==42 and set(aliases)==set(original)|{added}
    alias=aliases[added]
    assert alias.methods=={'GET'} and alias.endpoint is alias.canonical_route.endpoint
    assert alias.app is alias.canonical_route.app
    responses=[]
    for version in ['v3','v4']:
        response=client.get('/api/'+version+'/research/opening-observation',params={'date':'2026-10-28','symbol':'301655.SZ'})
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        responses.append(response.json())
    assert len(calls)==2 and responses[0]==responses[1]  # one call for each separate request
    assert all(responses[0][key] is False for key in ['production_allowed','buy_gate_updated','orders_sent'])


def test_finite_panel_is_registered_before_spa_catchall(tmp_path,monkeypatch):
    app,_,payload=_app(tmp_path,monkeypatch);client=TestClient(app)
    response=client.get('/research-panel/daily.html?date=2026-10-28')
    assert response.status_code==200 and response.content==payload
    assert response.headers['cache-control']=='no-store'
    assert client.get('/research-panel/not-exported.html').status_code==404
    assert client.get('/research-panel/../private.json').status_code==404


def test_research_registration_is_limited_to_gateway_or_combined():
    from apps.api.v4_api.research_panel_mount import register_opening_research
    app=FastAPI();before=list(app.routes)
    register_opening_research(app,module_role='stage')
    assert app.routes==before
    root=Path(__file__).resolve().parents[1]
    source=(root/'apps/web/src/App.vue').read_text();nav=source.split('<nav class="entry-nav"',1)[1].split('</nav>',1)[0]
    assert nav.count('href="/research-panel/daily.html?date=2026-10-28"')==1
    assert '>研究看板</a>' in nav
    assert 'class="entry-nav-link research-panel-entry"' in nav
    css=(root/'apps/web/src/style.css').read_text()
    assert '.entry-nav .research-panel-entry {' in css and 'text-decoration: none' in css
    assert 'href="http://127.0.0.1:8910/a-share/review"' in nav
    assert 'class="entry-nav-link research-panel-entry" href="http://127.0.0.1:8910' not in nav
