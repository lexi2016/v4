"""Freeze the current API owner and the exact third-stock/N display delta."""
from pathlib import Path
import json
import plistlib
from ops import junda_single_release as operator
from ops import research_panel_qfq as q

E=Path(__file__).resolve().parent
REPO=Path(q.__file__).resolve().parents[1]
candidate=json.loads((E/'EDAN_CANDIDATE_23b93631f53b2e70.json').read_text())
generation=candidate['candidate_generation'];assert generation.startswith('23b93631f53b2e70')
stage=E/('activation_stage_'+generation[:16]+'_r3');stage.mkdir()
plist=operator.PLIST;plist_sha=q.sha(plist)
assert plist_sha=='1b50bcc4ed4696d701107849c59c5e7a9eb796129a2c57a7e00424735f2c7bcf'
payload=plistlib.loads(plist.read_bytes());all_env=payload['EnvironmentVariables']
keys=('V4_APP_ROOT','V4_RELEASE_ID','V4_RELEASE_MANIFEST_PATH','V4_RELEASE_MANIFEST_SHA256',
      'V4_RESEARCH_PANEL_ROOT','V4_RESEARCH_PANEL_ASSET_MANIFEST','V4_WORKBENCH_HOST_BINDING',
      'V4_WORKBENCH_HOST_BINDING_SHA256')
env={key:all_env[key] for key in keys}
base=Path(env['V4_APP_ROOT']).parent
assert str(base).endswith('/top200-manual-r4-20261102-a4e6b78d4b1d8ab3')
assert env['V4_RELEASE_MANIFEST_SHA256']=='ed5a244d363328f303d3f8ba86e60944bab083635a3fb7de44b35c298beb69ee'
assert q.sha(env['V4_RELEASE_MANIFEST_PATH'])==env['V4_RELEASE_MANIFEST_SHA256']
assert q.sha(env['V4_WORKBENCH_HOST_BINDING'])==env['V4_WORKBENCH_HOST_BINDING_SHA256']
process=operator.live_process();assert process['pid']==42294
operator.assert_live_root(process['pid'],env['V4_APP_ROOT'])
live=operator.verify_http(8873,release_id=env['V4_RELEASE_ID'],manifest_sha=env['V4_RELEASE_MANIFEST_SHA256'],single=False)
roots={'api':Path(env['V4_APP_ROOT']),'site':Path(env['V4_RESEARCH_PANEL_ROOT'])}
spec=[('api','infrastructure/research_workbench_host.py'),('site','workbench.html'),
      ('site','workbench-host/kb-single-stock.mjs'),('site','workbench-host/kb-signal-view.mjs')]
expected_before={'api:infrastructure/research_workbench_host.py':'7543ff09fc8254e5c7c1d0188a4490ec0e34a9ed89e7ad46df6cca8f898839d6',
                 'site:workbench.html':'96f0ea4e3000e9a1e864f4e2ddafc8678271fcd9afa251c94d14d874546d1eb9',
                 'site:workbench-host/kb-single-stock.mjs':'1280ba3c62c5b863f88f95f56af76b33314a415fe999804bc1f2f1a1358b7ec3',
                 'site:workbench-host/kb-signal-view.mjs':'d0b928cb241a59f1c036c8a993a923dff2ef314fed781c7db4672040886902df'}
def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise RuntimeError('STAGE_ALREADY_EXISTS:'+str(path))
    path.write_bytes(data)
    return {'path':str(path),'sha256':q.sha(path),'bytes':len(data)}
def json_save(path,value):return save(path,(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode())
changes=[];assets=json.loads(Path(env['V4_RESEARCH_PANEL_ASSET_MANIFEST']).read_text());asset_map={x['path']:x for x in assets['files']}
for kind,relative in spec:
    old=roots[kind]/relative;new=REPO/(('research-panel/' if kind=='site' else '')+relative)
    assert q.sha(old)==expected_before[kind+':'+relative]
    after=save(stage/'after'/kind/relative,new.read_bytes())
    rollback=save(stage/'before'/kind/relative,old.read_bytes())
    changes.append({'kind':kind,'path':relative,'before_sha256':rollback['sha256'],'after':after,'rollback':rollback})
    if kind=='site':
        assert relative in asset_map
        asset_map[relative]['sha256']=after['sha256']
new_assets=json_save(stage/'new_static_assets.json',assets)
old_binding=Path(env['V4_WORKBENCH_HOST_BINDING']);binding=json.loads(old_binding.read_text())
previous=json.loads((E.parent/'n_hold_score_integration_20261102_r1/TWO_STOCK_N_CANDIDATES_R3.json').read_text())
references={item['symbol']:item['binding'] for item in previous};references['300206.SZ']=candidate['binding']
binding['single_stock_research_by_symbol']=references;binding['single_stock_research']=references['002865.SZ']
new_binding=json_save(stage/'new_workbench_binding.json',binding)
baseline={'pid':process['pid'],'plist_sha256':plist_sha,'env':env,'generation':operator.SOURCE_GENERATION,
          'input_sha256':operator.INPUT_SHA,'source_date':'2026-10-30','observation_date':'2026-11-02',
          'candidate_pool_count':172,'pool_rows_sha256':live['pool_rows_sha256'],
          'top200_rows_sha256':live['top200_rows_sha256'],'top200_representative':live['top200_representative']}
baseline_ref=json_save(stage/'ACTIVATION_BASELINE.json',baseline)
stocks={
 '002865.SZ':{'candidate_generation':'daa649db4dd53e7be5fe9c4da8ae08a6f9b8f9dbb3c24858403b2a0dff94c112',
              'rows':2311,'candidate_pool_member':False,'score':[4,4,4],'trend':False,'concept_count':6,
              'action_no_position':'等回调','action_with_position':'持有','source_root':str(operator.PRIOR_N_ROOT)},
 '301048.SZ':{'candidate_generation':'9bf8022c1206fea7d5dd07c086ed3a4af23d61be4d75ab1b39d7625500975f43',
              'rows':1258,'candidate_pool_member':True,'score':[None,1,2],'trend':None,'concept_count':3,
              'action_no_position':'等回调','action_with_position':'卖出','source_root':str(operator.PRIOR_N_ROOT)},
 '300206.SZ':{'candidate_generation':generation,'rows':3767,'candidate_pool_member':False,'score':[4,4,4],
              'trend':False,'concept_count':8,'action_no_position':'等回调','action_with_position':'放飞','source_root':str(REPO)}}
old_assets=Path(env['V4_RESEARCH_PANEL_ASSET_MANIFEST'])
plan={'schema':'junda_workbench_activation_stage.v1','status':'PREPARED_NOT_ACTIVATED','candidate_generation':generation,
      'baseline':baseline_ref,'changes':changes,'stocks':stocks,'new_binding':new_binding,'new_asset_manifest':new_assets,
      'old_binding':{'path':str(old_binding),'sha256':q.sha(old_binding)},
      'old_asset_manifest':{'path':str(old_assets),'sha256':q.sha(old_assets)},
      'precondition':'exact pid, plist, full app and site inventories, source and 172/Top200 identity',
      'global_panel_pointers_write':False,'operator_sha256':q.sha(Path(operator.__file__)),**q.FLAGS}
assert operator.live_process()==process and q.sha(plist)==plist_sha
output=json_save(stage/'STAGED_DELTA.json',plan)
print(json.dumps({'stage':output,'baseline':baseline_ref,'stocks':stocks},ensure_ascii=False))
