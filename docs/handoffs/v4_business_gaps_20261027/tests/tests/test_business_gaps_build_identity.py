import ast
import hashlib
import json
import os
from pathlib import Path
import re

import pytest


def reader(file):
    path=Path(__file__).parents[1]/'apps/api/v35_api/runtime_graph_router.py'
    fn=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_frontend_build_identity')
    ns=dict(Path=Path,hashlib=hashlib,json=json,os=os,re=re,__file__=str(file))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),ns)
    return ns['_frontend_build_identity']


@pytest.mark.parametrize('defect',[None,'asset','manifest','root','entry'])
def test_frontend_identity_requires_actual_script_bytes_and_current_api_manifest(tmp_path,monkeypatch,defect):
    release=tmp_path/'release';app=release/'app';dist=app/'apps/web/dist';asset=dist/'assets/main-new.js';asset.parent.mkdir(parents=True)
    asset.write_text('immutable bundle');index=dist/'index.html';index.write_text('<script type="module" src="/assets/main-new.js"></script>')
    if defect=='entry':index.write_text('<script src="/outside.js"></script>')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    value={'schema_version':'v4.release_candidate.v1','candidate':{'app_root':str(app),'root':str(release),'release_id':'test'},
        'app_files':[{'path':'apps/web/dist/index.html','sha256':digest(index)},{'path':'apps/web/dist/assets/main-new.js','sha256':digest(asset)}]}
    if defect=='root':value['candidate']['app_root']='/wrong/app'
    manifest=release/'release-manifest.json';manifest.write_text(json.dumps(value))
    monkeypatch.setenv('V35_RELEASE_MANIFEST_SHA256',digest(manifest) if defect!='manifest' else '0'*64);monkeypatch.setenv('V35_RELEASE_ID','test')
    if defect=='asset':asset.write_text('unreviewed byte drift')
    result=reader(app/'apps/api/v35_api/runtime_graph_router.py')()
    assert result['status']==('VERIFIED' if defect is None else 'CANNOT_CONFIRM')
    if defect is None:assert result['script_path']=='/assets/main-new.js' and result['bundle_sha256']==digest(asset)
