"""Explicit-scope static dashboard code evidence; no runtime collection or data IO."""
from pathlib import Path
import argparse,ast,hashlib,html,json,re,subprocess
from datetime import datetime,timezone

TASK=Path(__file__).resolve().parents[1]
NODE='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
canonical=lambda v:json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
TASK_FILES=[
 'apps/api/v4_api/research_panel_mount.py','infrastructure/research_classification_view.py','tests/test_workbench_entry_migration.py','tests/test_received_classification_view.py','research/stock_panel_collab_20261030/mac-host/entry-date.mjs','research/stock_panel_collab_20261030/mac-host/classification-local.mjs',
 'infrastructure/research_workbench_host.py','ops/build_mac_workbench.py','ops/collect_workbench_observations.py',
 'ops/run_workbench_observation_slot.py','ops/research_panel_daily_product.py','domains/research_event_case_cache.py',
 'ops/sync_stock_history_completion.py','research/stock_panel_collab_20261030/stock-bridge.mjs',
 'research/stock_panel_collab_20261030/mac-host/bootstrap.mjs','research/stock_panel_collab_20261030/mac-host/completion-action.mjs',
 'research/stock_panel_collab_20261030/mac-host/rate-sort.mjs','research/stock_panel_collab_20261030/mac-host/observation-local.mjs',
 'tests/test_mac_framework_host.py','tests/test_workbench_observations.py','tests/test_daily_product_durable_cache.py',
 'ops/render_daily_dashboard_code_map.py','domains/research_daily_statistics.py','domains/research_daily_product.py',
 'infrastructure/research_lane_source.py','apps/api/v4_api/research_router.py',
 'research-panel/numeric283-panel.js','research-panel/related-reports.js','research-panel/待删除/legacy-daily.html',
 'docs/handoffs/a_daily_dashboard_closure_20261029/SOURCE_CONFIG.json',
 'docs/handoffs/a_daily_dashboard_closure_20261029/readable_stock_materials/project_event_details.py',
 'docs/handoffs/a_daily_dashboard_closure_20261029/readable_stock_materials/prepare_c9.py',
 'tests/test_event_percentile_strata.py','tests/test_daily_display_names.py','tests/test_original_chart_interactions.py',
 'tests/test_daily_dashboard_code_map.py','tests/test_readable_stock_materials.py','research-panel/code-map/ARCHIFY_LICENSE.txt',
 'docs/handoffs/a_daily_dashboard_closure_20261029/readable_stock_materials/control_c9.py']
API_FILES=['apps/api/v4_api/research_panel_mount.py','infrastructure/research_workbench_host.py','infrastructure/research_classification_view.py','apps/web/dist/index.html','apps/web/dist/assets/main-workbench-entry-8008e8728f18.js','apps/api/v4_api/app.py','apps/api/v4_api/research_router.py','apps/api/v4_api/research_lane_router.py',
 'infrastructure/research_lane_source.py','infrastructure/zsxq_pdf_search_index.py','domains/related_pdf_reports.py',
 'research-panel/numeric283-panel.js','research-panel/related-reports.js','research-panel/待删除/legacy-daily.html']
MAIN_FILES=['ops/run_v4_macos_scheduler_daemon.py','ops/run_scheduled_slot.py','ops/research_panel_daily_product.py',
 'ops/render_original_formula_projection.py','ops/macos_research_panel_daily_gate.py','ops/research_panel_qfq.py',
 'infrastructure/scheduling/executor_registry.py','contracts/runtime_workloads.json','contracts/a_share_daily_source_policy.json',
 'domains/research_daily_statistics.py','domains/research_daily_product.py']
REFERENCE_FILES=['docs/v35-mac-end-to-end-code-graph.md','infrastructure/runtime_graph/_service_parts/graph_build.py','ops/collect_runtime_graph.py']

def build(api_root,main_root,output):
    records=[];drift=[];missing=[];input_hashes={}
    groups=[('TASK_SOURCE_DIRTY_AT_CAPTURE',TASK,TASK_FILES),('API_CANDIDATE_NOT_RUNTIME_PROOF',api_root,API_FILES),
            ('MAIN_C8_INSTALLED_SOURCE_AT_CAPTURE',main_root,MAIN_FILES),('REFERENCE_ONLY_LEGACY_GRAPH',TASK,REFERENCE_FILES)]
    for role,root,files in groups:
        for name in files:
            path=root/name
            if name.startswith('research-panel/') and role.startswith('API_'):path=root.parent/name
            locator=role+'/'+name
            if not path.is_file():missing.append(dict(source=locator,status='CANNOT_CONFIRM_MISSING'));continue
            raw=path.read_bytes();input_hashes[locator]=(path,sha(raw));text=raw.decode('utf-8-sig');symbols=[];imports=[];routes=[];parse='NOT_APPLICABLE'
            if path.suffix=='.py':
                try:
                    tree=ast.parse(text);parse='AST_PARSED_STATIC_ONLY'
                    for node in ast.walk(tree):
                        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):symbols.append(dict(name=node.name,line=node.lineno,end_line=node.end_lineno,kind=type(node).__name__))
                        if isinstance(node,ast.Import):imports.extend(dict(module=n.name,line=node.lineno) for n in node.names)
                        if isinstance(node,ast.ImportFrom):imports.append(dict(module='.'*node.level+(node.module or ''),line=node.lineno))
                        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                            for d in node.decorator_list:
                                if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr in {'get','post','put','delete','patch'} and d.args and isinstance(d.args[0],ast.Constant) and isinstance(d.args[0].value,str):routes.append(dict(method=d.func.attr.upper(),route_fragment=d.args[0].value,symbol=node.name,line=d.lineno))
                except SyntaxError as error:parse='CANNOT_CONFIRM_PARSE:'+str(error.lineno)
            elif path.suffix in {'.js','.cjs','.mjs'}:
                check=subprocess.run([NODE,'--check',str(path)],capture_output=True);parse='NODE_SYNTAX_STATIC_ONLY' if check.returncode==0 else 'CANNOT_CONFIRM_JS_PARSE'
                symbols=[dict(name=m.group(1),line=text[:m.start()].count('\n')+1,kind='js_function') for m in re.finditer(r'function\s+([A-Za-z_$][\w$]*)\s*\(',text)]
            elif path.suffix=='.json':json.loads(text);parse='JSON_PARSED_STATIC_ONLY'
            record=dict(id=sha(locator.encode())[:16],source=locator,logical_path=name,source_role=role,bytes=len(raw),language=path.suffix.lstrip('.'),original_sha256=sha(raw),parse_status=parse,symbols=symbols,routes=routes,imports=imports,git_state='WORKTREE_SNAPSHOT' if root==TASK else 'RELEASE_SOURCE_NO_GIT_INFERENCE',runtime_behavior='NOT_PROVEN_BY_THIS_STATIC_MAP',packaged_kind='SANITIZED_SYMBOL_METADATA_NOT_SOURCE_COPY')
            records.append(record)
    known={r['logical_path'].removesuffix('.py').replace('/','.') for r in records if r['language']=='py'}
    for r in records:
        for item in r['imports']:item['resolution']='IN_SCOPE_SOURCE_ROLE_MUST_MATCH' if item['module'].lstrip('.') in known else 'EXTERNAL_OR_OUT_OF_SCOPE_NOT_RECURSED'
    for record in records:record['packaged_metadata_sha256']=sha(canonical(record))
    modules={}
    for role,_,_ in groups:modules[role]=[r['id'] for r in records if r['source_role']==role]
    for locator,(path,digest) in input_hashes.items():
        observed=sha(path.read_bytes())
        if observed!=digest:drift.append(dict(source=locator,before=digest,after=observed,status='SOURCE_CHANGED_DURING_CAPTURE'))
    captured_at=datetime.now(timezone.utc).isoformat()
    previous=json.loads((output/'MODULES.json').read_text()) if (output/'MODULES.json').is_file() else {}
    previous['archify_edge_sources']={a['from']+'->'+a['to']:dict(from_node=a['from'],to_node=a['to'],basis='static source relationship; precise node paths below; projection also reads accepted cache TRUE') for a in json.loads((output/'overview.json').read_text())['connections']}
    mapping={k:v for k,v in previous.items() if k.startswith('archify_')}
    record_by_source={r['source']:r for r in records}
    for refs in mapping.get('archify_node_sources',{}).values():
        for ref in refs:
            record=record_by_source.get(ref['path'])
            if record:
                symbol=next((x for x in record['symbols'] if x['name']==ref['label']),None)
                ref['line']=symbol['line'] if symbol else ref['line']
    graph=dict(captured_at=captured_at,version_boundary='Workbench engineering candidate plus exact read-only API/Main source roots at capture; legacy role names retain original map provenance; Root release receipt is required for deployment identity',schema='v4.dashboard.static_code_evidence.v1',status='STATIC_SOURCE_SNAPSHOT_NOT_RUNTIME_ACCEPTANCE',records=records,missing=missing,scope='dashboard only: original owner/caches/GET/Canvas/materials/events/deployment; no price/account/PDF contents')
    output.mkdir(parents=True,exist_ok=True)
    def save(name,value):
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode()+b'\n'
        if b'/Users/' in raw:raise ValueError('PRIVATE_ABSOLUTE_PATH_IN_PUBLIC_MAP:'+name)
        (output/name).write_bytes(raw)
    save('SOURCE_MANIFEST.json',dict(captured_at=captured_at,version_boundary=graph['version_boundary'],schema=graph['schema'],sources=records,missing=missing,source_bytes_included=False))
    save('MODULES.json',dict(groups=modules,evidence_status='static; no natural/deploy/API/UI promotion',**mapping))
    save('EXCLUSIONS.json',dict(excluded=['raw prices and selector rows','statistics/cache contents','received company/report data','PDF/OCR bodies','credentials/accounts','unrelatedV4modules','historicalV3migration graph as today authority'],reference_only=REFERENCE_FILES))
    save('SANITIZATION.json',dict(private_absolute_paths='not emitted; logical role/path aliases only',source_body='not included',metadata='symbols/imports/routes/SHA only',source_config_values='not included',packaged_sha='sanitized metadata digest; not a claim of copiedsource bytes'))
    save('SNAPSHOT_DRIFT.json',dict(status='NO_DRIFT_DURING_CAPTURE' if not drift else 'CANNOT_CONFIRM_DRIFT',changes=drift,ongoing_runtime='NOT_MEASURED'))
    save('graph.json',graph)
    payload=json.dumps(graph,ensure_ascii=False).replace('<','\\u003c')
    body='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V4 看板开发图谱</title><style>body{margin:0;background:#091522;color:#dce8f4;font:14px/1.6 system-ui}main{max-width:1350px;margin:auto;padding:22px}a{color:#91c5f3}input,select{font:inherit;padding:8px;background:#10283a;color:inherit;border:1px solid #335369}iframe{width:100%;height:780px;border:1px solid #2d465c}article{border:1px solid #29445a;padding:12px;margin:12px 0;border-radius:6px}code{overflow-wrap:anywhere;font-size:12px}details{margin:6px 0}table{width:100%;border-collapse:collapse}td,th{padding:6px;text-align:left;border-bottom:1px solid #243e53}p{margin:8px 0}.note{color:#9db7ca}@media(max-width:760px){main{padding:12px}iframe{height:650px}}</style><main><h1>V4 看板开发图谱</h1><p>静态源码证据快照。连线不代表自然运行、数据认证或部署验收；工作台整改候选、API/Main运行源码快照与历史参照分别标记；旧角色名称保留图谱来源，不据此判断本批发布后的现役版本。</p><p><a href="../workbench.html">返回看板</a> · <a href="overview.html">打开架构总览</a> · <a href="/api/v3/runtime-graph">既有运行图（独立证据）</a></p><iframe title="看板架构总览" src="overview.html"></iframe><h2>节点与源码定位</h2><div id="node-sources"></div><h2>按文件、符号、接口或SHA排查</h2><input id="search" placeholder="搜索文件 / function / route / SHA" aria-label="搜索源码证据"><select id="role" aria-label="源码角色"><option value="">全部角色</option></select><div id="results"></div><details><summary>范围、脱敏与漂移记录</summary><p><a href="SOURCE_MANIFEST.json">源码清单</a> · <a href="MODULES.json">模块角色</a> · <a href="EXCLUSIONS.json">明确排除</a> · <a href="SANITIZATION.json">脱敏规则</a> · <a href="SNAPSHOT_DRIFT.json">采集漂移</a></p></details><script id="evidence" type="application/json">PAYLOAD</script><script>const data=JSON.parse(document.getElementById('evidence').textContent),search=document.getElementById('search'),role=document.getElementById('role'),host=document.getElementById('results');for(const name of [...new Set(data.records.map(r=>r.source_role))]){const o=document.createElement('option');o.value=o.textContent=name;role.append(o)}function add(p,t,x){const e=document.createElement(t);e.textContent=x;p.append(e);return e}function render(){host.replaceChildren();const q=search.value.toLowerCase();for(const r of data.records.filter(r=>(!role.value||r.source_role===role.value)&&JSON.stringify(r).toLowerCase().includes(q))){const a=add(host,'article','');a.id=r.id;add(a,'h3',r.logical_path);add(a,'p',r.source_role+' · '+r.parse_status);add(a,'code','source SHA256 '+r.original_sha256);const d=add(a,'details','');add(d,'summary',r.symbols.length+'符号 / '+r.routes.length+'接口 / '+r.imports.length+'依赖');const table=add(d,'table','');for(const s of r.symbols){const tr=add(table,'tr','');add(tr,'td',s.name);add(tr,'td',r.logical_path+':'+s.line)}for(const t of r.routes){const tr=add(table,'tr','');add(tr,'td',t.method+' '+t.route_fragment);add(tr,'td',r.logical_path+':'+t.line)}for(const i of r.imports){const tr=add(table,'tr','');add(tr,'td',i.module);add(tr,'td','line '+i.line+' · '+i.resolution)}}}search.oninput=role.onchange=render;render();</script></main></html>'''.replace('PAYLOAD',payload)
    mapping_js=json.dumps(mapping.get('archify_node_sources',{}),ensure_ascii=False).replace('<','\\u003c')
    body=body.replace('</main>', '<script>const nodeSources='+mapping_js+';for(const [name,refs] of Object.entries(nodeSources)){const a=add(document.getElementById("node-sources"),"details","");add(a,"summary",name);for(const r of refs){const key=r.path||r.source||"",found=data.records.find(x=>x.source===key);const p=add(a,"p",""),link=add(p,"a",key+":"+(r.line||"?"));link.href=found?"#"+found.id:"MODULES.json";link.onclick=()=>{if(found){role.value="";search.value=key;render()}}}}</script></main>')
    (output/'index.html').write_text(body)
    return dict(files=len(records),symbols=sum(len(r['symbols']) for r in records),missing=missing,drift=drift,private_data_included=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--api-root',required=True,type=Path);p.add_argument('--main-root',required=True,type=Path);p.add_argument('--output',type=Path,default=TASK/'research-panel/code-map');a=p.parse_args();print(json.dumps(build(a.api_root,a.main_root,a.output),ensure_ascii=False))
