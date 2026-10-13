"""Capture candidate read-only HTTP projection of immutable saved run; no new research."""
from pathlib import Path
import hashlib,json,sys,importlib.util
from types import SimpleNamespace
H=Path(__file__).resolve().parent;W=H.parents[2];sys.path.insert(0,str(W));sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('calendar_display',H/'recover_cached_full_date.py');runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime);runtime.install_runtime()
from fastapi import FastAPI
from fastapi.testclient import TestClient
from v4.manager_workbench.api import create_router
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.contracts import PlanSnapshot
RUN='84eafbbb71ba4767a591d1a4286fe061';FORMAL=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
raw=(FORMAL/'state/manager_workbench/manager_workbench/snapshots'/f'{RUN}.json').read_bytes();snapshot=PlanSnapshot.model_validate(json.loads(raw));sha=lambda b:hashlib.sha256(b).hexdigest()
assert sha(raw)=='ea5f7217ecd37824b467ff38a82ea88686d82827e3b3e18935e426aab53e10cf'
cfg=WorkbenchConfig.model_validate(json.loads((FORMAL/'config/manager-workbench-v7.json').read_bytes()))
service=SimpleNamespace(config=cfg,store=SimpleNamespace(get_plan=lambda *args,**kw:snapshot,list_plans=lambda date:[snapshot]))
app=FastAPI();app.include_router(create_router(service));client=TestClient(app)
day=client.get(f'/api/v4/manager-workbench/days/20261013?run_id={RUN}&q=赛力斯').json();detail=client.get(f'/api/v4/manager-workbench/stocks/HK.09927?date=20261013&run_id={RUN}').json()
assert day['data']['stocks'][0]['name']=='赛力斯' and detail['data']['stock']['name']=='赛力斯'
assert day['data']['snapshot']['product_sha256']==snapshot.product_sha256 and day['data']['display_projection']['snapshot_hash_basis']=='ORIGINAL_SAVED_SNAPSHOT'
us=day['data']['us_mapping_summary'];assert (us['source_symbol_count'],us['source_row_count'],us['relation_row_count'],us['mapped_hk_count'])==(33,37,14,10)
assert us['source_decision_counts']==dict(SELECTED=0,CONDITIONAL_WATCH=0,NOT_SELECTED=4,UNASSESSED=29,OBSERVATION_ONLY=0)
assert (FORMAL/'state/manager_workbench/manager_workbench/snapshots'/f'{RUN}.json').read_bytes()==raw and next(s for s in snapshot.stocks if s.symbol=='HK.09927').name is None
out=W/'apps/web/src/manager-workbench/__tests__/fixtures/display-repair-http.local.json';out.write_text(json.dumps(dict(day=day,detail=detail),ensure_ascii=False,indent=2)+'\n')
report=dict(status='CANDIDATE_SAVED_RUN_HTTP_PASS',fixture=str(out),fixture_sha256=sha(out.read_bytes()),snapshot_raw_sha256=sha(raw),product_sha256=snapshot.product_sha256,US_units=dict(source_symbols=33,source_rows=37,relation_rows=14,unique_hk=10),US_counts=us['source_decision_counts'],name=detail['data']['stock']['name'],name_source=detail['data']['stock']['name_source'],snapshot_unchanged=True,formal_writes=0,model_calls=0,network_calls=0)
p=H/'display-repair-http-r1.json';assert not p.exists();p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
