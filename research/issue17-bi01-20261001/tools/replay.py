#!/usr/bin/env python3
"""Assemble only frozen test dependencies into a NEW directory; never deploy."""
import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path
P=Path(__file__).resolve().parents[1]
REPO=P.parents[1]
BASE='research/manager-r9-consumer-r1-20260930'
def git(*args):
    return subprocess.check_output(['git',*args],cwd=REPO)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--jsdom',type=Path,required=True,help='existing node_modules/jsdom directory')
    parser.add_argument('--image',choices=['before','after'],default='after')
    a=parser.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    app=out/'app';app.mkdir();lock=json.loads((P/'TEST_SOURCE_LOCK.json').read_text())
    for row in lock['files']:
        rel=row['path'];dest=app/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        if row.get('recipe'):
            prefix=BASE+'/api6726_business_combo_20260930/'
            dest.write_bytes(git('show','95426ac3db39f6d86ec2031617c4ac180d40868e:'+prefix+'reference_only/r3b_input/'+rel))
            patch=git('show','95426ac3db39f6d86ec2031617c4ac180d40868e:'+prefix+'evidence/integration_actual_diff.patch').decode()
            section=next('--- a/'+s for s in patch.split('--- a/')[1:] if s.startswith(rel+'\n'))
            subprocess.run(['git','apply','-'],input=section,text=True,cwd=app,check=True)
            raw=dest.read_bytes()
        else:
            raw=(P/row['package_path']).read_bytes() if 'package_path' in row else git('cat-file','blob',row['blob'])
            dest.write_bytes(raw)
        if sha(raw)!=row['sha256']:raise ValueError('SHA_MISMATCH:'+rel)
    rel='v4/manager_research/workspace_announcements.py'
    # Prove exact patch forward AND reverse on the pinned before image.
    (app/rel).write_bytes((P/'before/app'/rel).read_bytes())
    subprocess.run(['git','apply','--check',str(P/'runtime.patch')],cwd=app,check=True)
    subprocess.run(['git','apply',str(P/'runtime.patch')],cwd=app,check=True)
    assert (app/rel).read_bytes()==(P/'after/app'/rel).read_bytes()
    subprocess.run(['git','apply','--reverse','--check',str(P/'runtime.patch')],cwd=app,check=True)
    if a.image=='before':(app/rel).write_bytes((P/'before/app'/rel).read_bytes())
    support=out/'support';support.mkdir()
    (support/'test_b1_history.py').write_bytes(git('show','95426ac3db39f6d86ec2031617c4ac180d40868e:'+BASE+'/final_business_20260930/test_support/test_b1_history.py'))
    expected={str(p.relative_to(app)):sha(p.read_bytes()) for p in app.rglob('*') if p.is_file()}
    env={**os.environ,'PYTHONPATH':str(app)+os.pathsep+str(support),'PYTHONDONTWRITEBYTECODE':'1',
         'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTEST_ADDOPTS':'','BI01_APP':str(app),
         'BI01_JSDOM':str(a.jsdom.resolve()),'FINAL_APP_ROOT':str(app),'FINAL_IMPORT_RECEIPT':str(out/'import_receipt.json')}
    cmd=[sys.executable,'-m','pytest','-q','-s','-p','no:cacheprovider','-c','/dev/null',str(P/'tests'),
         '--junitxml='+str(out/'junit.xml')]
    with (out/'tests.log').open('w') as log:
        run=subprocess.run(cmd,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT)
    unchanged=all(sha((app/p).read_bytes())==s for p,s in expected.items())
    receipt={'image':a.image,'python':sys.version,'node':subprocess.check_output(['node','--version'],text=True).strip(),
             'command':cmd,'exit_code':run.returncode,'source_unchanged':unchanged,
             'patch_forward_exact':True,'patch_reverse_check':True,'deployed':False}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print((out/'tests.log').read_text());print(json.dumps(receipt,indent=2))
    return run.returncode if unchanged else 2
if __name__=='__main__':raise SystemExit(main())
