"""This install only: preserve active V4 API bytes and overlay exact accepted deltas."""
from pathlib import Path
import ast,copy,hashlib,json,os,plistlib,shutil,subprocess,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/install_and_single_stock_002003')
OLD=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-stage-performance-supplementary-20261030-r2-api');NEW=OLD.parent/'a-daily-dashboard-c6-20261030-r2-api'
PRODUCT=B.parent.parent/'today_full_r1';ARTIFACT=B.parent.parent
sys.path.insert(0,str(ROOT));from ops.api_release_integration import inventory_tree,inventory_digest
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n');return {'path':str(p),'sha256':sha(p)}
def gitbytes(name):return subprocess.run(['git','show','HEAD:'+name],cwd=ROOT,check=True,capture_output=True).stdout
def rewrite(v):
 if isinstance(v,str):return str(NEW)+v[len(str(OLD)):] if v.startswith(str(OLD)) else v
 if isinstance(v,list):return [rewrite(x) for x in v]
 if isinstance(v,dict):return {k:rewrite(x) for k,x in v.items()}
 return v
if NEW.exists():raise FileExistsError('inactive API candidate exists; preserve it')
NEW.mkdir();(NEW/'.candidate-build-in-progress').write_text('inactive exact V4 API overlay\n')
base=inventory_tree(OLD/'app');shutil.copytree(OLD/'app',NEW/'app',symlinks=True);assert inventory_tree(NEW/'app')==base
source_paths=['apps/api/v4_api/research_router.py','apps/api/v4_api/research_lane_router.py','infrastructure/research_lane_source.py','infrastructure/zsxq_pdf_search_index.py','domains/related_pdf_reports.py','domains/related_pdf_cursor.py']
for name in source_paths:
 p=NEW/'app'/name;p.parent.mkdir(parents=True,exist_ok=True);p.chmod(p.stat().st_mode|0o200) if p.exists() else None;p.write_bytes(gitbytes(name))
# Active ingestion plus only the previously accepted two GET functions and 3 verified fields.
ingestion=NEW/'app/infrastructure/zsxq_pdf_ingestion.py';ingestion.chmod(ingestion.stat().st_mode|0o200)
for patch in [ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/repair_3p2/formula_followup/ingestion_get_recovery.patch',ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/report_relations_real_owner_fix/OWNER_THREE_FIELDS.patch']:
 subprocess.run(['git','apply','--check',str(patch)],cwd=NEW/'app',check=True,capture_output=True);subprocess.run(['git','apply',str(patch)],cwd=NEW/'app',check=True,capture_output=True)
# Explicit daily-output root is separate from raw/history root; artifact root is fixed config, never request input.
p=NEW/'app/apps/api/v4_api/research_router.py';text=p.read_text();text=text.replace('    original_chart_binding: Mapping[str, Any] | None = None,','    original_chart_binding: Mapping[str, Any] | None = None,\n    a_share_daily_root: Path | str | None = None,\n    original_chart_artifact_root: Path | str | None = None,',1);text=text.replace('a_share_daily_root=shared_data_root,\n                                       original_chart_binding=original_chart_binding)', 'a_share_daily_root=a_share_daily_root if a_share_daily_root is not None else shared_data_root,\n                                       original_chart_binding=original_chart_binding, original_chart_artifact_root=original_chart_artifact_root)',1);p.write_text(text)
p=NEW/'app/infrastructure/research_lane_source.py';text=p.read_text();text=text.replace('original_chart_binding: Mapping[str, Any] | None = None) -> None:', 'original_chart_binding: Mapping[str, Any] | None = None, original_chart_artifact_root: Path | str | None = None) -> None:',1);text=text.replace('        self.original_chart_binding = original_chart_binding','        self.original_chart_binding = original_chart_binding\n        self.original_chart_artifact_root = Path(original_chart_artifact_root).resolve() if original_chart_artifact_root is not None else None',1)
text=text.replace('''        product = self.read_a_daily_product(date)
        binding = self.original_chart_binding''','''        product = self.read_a_daily_product(date)
        current_product = product
        chart_origin = None
        binding = self.original_chart_binding''',1)
text=text.replace('''            binding = {"artifact_root": str(root), "manifest": descriptor.get("manifest"), "receipt": descriptor.get("receipt")}''','''            binding = {"artifact_root": str(self.original_chart_artifact_root or root), "manifest": descriptor.get("manifest"), "receipt": descriptor.get("receipt")}
            chart_origin = descriptor.get("chart_origin_manifest")
            if chart_origin is not None:
                origin_manifest = self._a_product_reference(chart_origin)
                origin = self._a_product_reference(origin_manifest["artifact"])
                excluded = {"row_refs", "artifact", "manifest", "available_dates", "original_charts"}
                if ({k:v for k,v in origin.items() if k not in excluded} != {k:v for k,v in product.items() if k not in excluded}
                        or origin_manifest.get("schema_version") != "v4.a_share.daily_product_manifest.v1"
                        or origin_manifest.get("data_date") != date or origin_manifest.get("source_generation") != product["source_generation"]
                        or origin_manifest.get("input_sha256") != product["source_identity"]["input_sha256"]
                        or set(origin["row_refs"]) != set(product["row_refs"])):
                    raise ValueError("ORIGINAL_CHART_NUMERIC_ORIGIN_CONFLICT")
                changed = {s for s in origin["row_refs"] if origin["row_refs"][s] != product["row_refs"][s]}
                if len(changed) != 1 or changed != set(descriptor.get("history_updated_symbols", [])):
                    raise ValueError("ORIGINAL_CHART_SINGLE_HISTORY_ORIGIN_INVALID")
                for changed_symbol in changed:
                    old_row = self._a_product_reference(origin["row_refs"][changed_symbol])
                    new_row = self._a_product_reference(product["row_refs"][changed_symbol])
                    self._a_daily_checkpoint_binding(new_row, product, changed_symbol, date)
                    if ({k:v for k,v in old_row.items() if k not in {"statistics", "historical_coverage"}}
                            != {k:v for k,v in new_row.items() if k not in {"statistics", "historical_coverage"}}):
                        raise ValueError("ORIGINAL_CHART_HISTORY_ORIGIN_ROW_CONFLICT")
                product = {**origin, "manifest": chart_origin, "artifact": origin_manifest["artifact"]}''',1)
text=text.replace('''        if asset is not None:
            if asset not in refs''','''        if chart_origin is not None:
            answer.update(product_manifest=current_product["manifest"], product_artifact=current_product["artifact"], chart_numeric_origin_manifest=chart_origin)
        if asset is not None:
            if asset not in refs''',1);p.write_text(text)
# No untracked app.py is copied: exactly two existing factory call sites gain the explicit root.
p=NEW/'app/apps/api/v4_api/app.py';text=p.read_text();needle='            shared_data_root=os.environ.get("V4_A_SHARE_HISTORY_DATA_ROOT"),\n';assert text.count(needle)==1;text=text.replace(needle,needle+'            a_share_daily_root=os.environ.get("V4_A_SHARE_DAILY_PRODUCT_ROOT") or os.environ.get("V4_A_SHARE_HISTORY_DATA_ROOT"),\n            original_chart_artifact_root=os.environ.get("V4_ORIGINAL_CHART_ARTIFACT_ROOT"),\n',1);needle='            us_market_data_root=store.root,\n';assert text.count(needle)==1;text=text.replace(needle,needle+'            a_share_daily_root=os.environ.get("V4_A_SHARE_DAILY_PRODUCT_ROOT") or os.environ.get("V4_A_SHARE_HISTORY_DATA_ROOT"),\n',1);p.chmod(p.stat().st_mode|0o200);p.write_text(text)
# Fixed panel assets: copy active immutable tree, overlay only four accepted files.
shutil.copytree(OLD/'research-panel',NEW/'research-panel',symlinks=True)
for name in ['daily.html','daily.js','numeric283-panel.js','related-reports.js']:
 p=NEW/'research-panel'/name;p.chmod(p.stat().st_mode|0o200);p.write_bytes(gitbytes('research-panel/'+name))
p=NEW/'research-panel/numeric283-panel.js';text=p.read_text();assert text.count('未启动全历史回算')==2;p.write_text(text.replace('未启动全历史回算','本页仅读取已绑定结果，不触发重算'))
p=NEW/'research-panel/numeric283-panel.js';text=p.read_text();text=text.replace('      ? evaluatedDates.map(displayDay).join("、")','      ? (evaluatedDates.length > 8\n        ? `${displayDay(evaluatedDates[0])} 至 ${displayDay(evaluatedDates[evaluatedDates.length - 1])}，共 ${evaluatedDates.length} 个日期`\n        : evaluatedDates.map(displayDay).join("、"))',1);p.write_text(text)
assets=json.loads((OLD/'research-panel-assets.json').read_text())
for row in assets['files']:row['sha256']=sha(NEW/'research-panel'/row['path'])
save(NEW/'research-panel-assets.json',assets)
entries=inventory_tree(NEW/'app');base_map={r['path']:r for r in base};after_map={r['path']:r for r in entries};delta=[p for p in sorted(set(base_map)|set(after_map)) if base_map.get(p)!=after_map.get(p)]
expected=set(source_paths)|{'infrastructure/zsxq_pdf_ingestion.py','apps/api/v4_api/app.py'};assert set(delta)==expected,(delta,expected)
manifest=json.loads((OLD/'release-manifest.json').read_text());manifest.update(release_id=NEW.name,source_root=str(ROOT),parent_release_root=str(OLD),app_root=str(NEW/'app'),activation_status='INACTIVE_PENDING_COMPOSED_REVIEW',production_allowed=False,buy_gate_updated=False,orders_sent=False,RESEARCH_ONLY=True);manifest['candidate'].update(root=str(NEW),app_root=str(NEW/'app'),release_id=NEW.name);manifest['application_inventory']={'entries':entries,'entry_count':len(entries),'aggregate_sha256':inventory_digest(entries)};manifest['app_files']=[{'path':r['path'],'kind':'file','sha256':r['sha256'],'size':r['size']} for r in entries if r['kind']=='file'];manifest['research_panel'].update(root=str(NEW/'research-panel'),asset_manifest=str(NEW/'research-panel-assets.json'),asset_manifest_sha256=sha(NEW/'research-panel-assets.json'));save(NEW/'release-manifest.json',manifest)
raw=(B/'com.lexi.v4.api.concurrent_before.plist').read_bytes();value=rewrite(plistlib.loads(raw));env=value['EnvironmentVariables'];env.update(V4_RELEASE_ID=NEW.name,V4_APP_ROOT=str(NEW/'app'),V4_RELEASE_MANIFEST_PATH=str(NEW/'release-manifest.json'),V4_RELEASE_MANIFEST_SHA256=sha(NEW/'release-manifest.json'),V4_A_SHARE_DAILY_PRODUCT_ROOT=str(PRODUCT),V4_ORIGINAL_CHART_ARTIFACT_ROOT=str(ARTIFACT),V4_RESEARCH_PANEL_ROOT=str(NEW/'research-panel'),V4_RESEARCH_PANEL_ASSET_MANIFEST=str(NEW/'research-panel-assets.json'));template=B/'com.lexi.v4.api.candidate.plist';template.write_bytes(plistlib.dumps(value,sort_keys=True))
receipt={'status':'API_INACTIVE_CANDIDATE_PREPARED_WAIT_COMPOSED_REVIEW','release':str(NEW),'manifest':{'path':str(NEW/'release-manifest.json'),'sha256':sha(NEW/'release-manifest.json')},'app_delta':{p:{'before':base_map.get(p),'after':after_map.get(p)} for p in delta},'panel_delta':['daily.html','daily.js','numeric283-panel.js','related-reports.js'],'assets_manifest':{'path':str(NEW/'research-panel-assets.json'),'sha256':sha(NEW/'research-panel-assets.json')},'plist_before':{'path':str(B/'com.lexi.v4.api.concurrent_before.plist'),'sha256':hashlib.sha256(raw).hexdigest()},'plist_candidate':{'path':str(template),'sha256':sha(template)},'builder_pattern':'accepted prepare_bundle.py exact active copy + existing inventory_tree/inventory_digest + explicit SHA allowlist; no V35 role assumptions','raw_history_root_unchanged':env['V4_A_SHARE_HISTORY_DATA_ROOT'],'daily_parent':str(PRODUCT),'fixed_artifact_root':str(ARTIFACT),'no_live_service_actions':True};save(B/'API_CANDIDATE_RECEIPT.json',receipt);(NEW/'.candidate-build-in-progress').unlink();print(json.dumps({'status':receipt['status'],'release':str(NEW),'manifest_sha256':receipt['manifest']['sha256'],'delta_paths':delta}),flush=True)
