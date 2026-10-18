"""Mechanical isolated build of the existing manager entry from its live base."""
from pathlib import Path
import hashlib, json, shutil, subprocess
R=Path.cwd(); H=R/'docs/handoffs/monthly_membership_research_fix_20261018'
B=json.loads((H/'ROOT_BASELINE_R4.json').read_text())
assert (H/'WRITER_R4_RECEIPT.json').is_file()
base=Path(B['runtimes']['api']['app_root'])/'apps/web'
stage=H/'local_only/web_build_r4'
source=H/'local_only/runtime_overlay_r4/app/apps/web'
shutil.copytree(base,stage,ignore=shutil.ignore_patterns('dist','node_modules','.vite'))
for p in stage.rglob('*'):
    if not p.is_symlink(): p.chmod(p.stat().st_mode|0o200)
stage.chmod(stage.stat().st_mode|0o700)
scope={'ALLOWED_PATHS':json.loads((H/'R4_COPY_SCOPE.json').read_text())['allowed_paths']}
overlaid=[]
for name in scope['ALLOWED_PATHS']:
    if not name.startswith('apps/web/'): continue
    rel=Path(name).relative_to('apps/web'); p=source/rel
    if p.is_file():
        shutil.copy2(p,stage/rel); overlaid.append(name)
assert overlaid
(stage/'node_modules').symlink_to(R/'apps/web/node_modules',target_is_directory=True)
(stage/'build-manager.mjs').write_text("import {build} from 'vite';\nimport vue from '@vitejs/plugin-vue';\nimport {resolve} from 'node:path';\nawait build({configFile:false,root:process.cwd(),plugins:[vue()],build:{outDir:'manager-build',rollupOptions:{input:{managerSelection:resolve('manager-selection/index.html')}}}});\n")
result=subprocess.run(['/Users/lexi/.local/node-v24.19.0/bin/node','build-manager.mjs'],cwd=stage,capture_output=True,text=True)
(H/'local_only/web_build_r4.log').write_text(result.stdout+result.stderr)
assert result.returncode==0, 'MANAGER_WEB_BUILD_FAILED'
files=[]
for p in (stage/'manager-build').rglob('*'):
    if p.is_file():
        rel=p.relative_to(stage/'manager-build'); dst=source/'dist'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
        files.append(dict(path='apps/web/dist/'+str(rel),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
report=dict(status='BUILT_FROM_ACTIVE_API_SOURCE_PLUS_REVIEW_SCOPE',base=str(base),source_overlays=overlaid,entry='manager-selection/index.html',generated_files=files,other_entrypoints_rebuilt=False)
(H/'ROOT_WEB_BUILD_R4.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
