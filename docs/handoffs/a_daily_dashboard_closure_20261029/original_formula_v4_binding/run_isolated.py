from pathlib import Path
import subprocess,sys,socket,json,shlex,shutil
root=Path(__file__).resolve().parents[4]
out=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/original_formula_v4_binding')
base=out.parent
panel=out/'static_overlay';shutil.copytree(base/'headless_ui_0300/static_overlay',panel,dirs_exist_ok=True)
for name in ['daily.html','numeric283-panel.js','daily.js','related-reports.js']:shutil.copyfile(root/'research-panel'/name,panel/name)
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
entry=root/'docs/handoffs/a_daily_dashboard_closure_20261029/serve_daily_dashboard_demo.py';helper=entry.with_name('run_targeted_checks.py')
code=f"import runpy,sys;runpy.run_path({str(helper)!r},run_name='candidate_read_only_imports');sys.argv=[{str(entry)!r},'--daily-product-root','/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1','--port',{str(port)!r},'--panel-root',{str(panel)!r},'--original-chart-manifest',{str(base/'original_formula_charts_247/MANIFEST.json')!r}];runpy.run_path({str(entry)!r},run_name='__main__')"
command=[sys.executable,'/Users/lexi/.agents/skills/webapp-testing/scripts/with_server.py','--server',shlex.join([sys.executable,'-I','-B','-c',code]),'--port',str(port),'--timeout','30','--','/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',str(Path(__file__).with_name('check.cjs')),f'http://127.0.0.1:{port}',str(out)]
r=subprocess.run(command,capture_output=True,text=True);(out/'runner.log').write_text(r.stdout+r.stderr)
with socket.socket() as s:s.settimeout(1);closed=s.connect_ex(('127.0.0.1',port))!=0
receipt={'runner_exit_code':r.returncode,'port':port,'temporary_service_stopped_port_closed':closed,'PANEL_PYTHON':sys.executable,'user_control_acquired':False};(out/'CLEANUP_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));print(r.stdout[-3000:]);print(r.stderr[-1000:]);raise SystemExit(r.returncode)
