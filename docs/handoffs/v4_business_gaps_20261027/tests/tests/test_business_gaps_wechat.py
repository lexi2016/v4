import ast
import hashlib
import json
from pathlib import Path
import pytest
from ops import wechat_preselection_sync as owner

from ops.wechat_preselection_sync import sync_wechat_preselection


@pytest.fixture(autouse=True)
def owned_test_root(tmp_path,monkeypatch):
    monkeypatch.setattr(owner,'_FORMAL_DATA_ROOT',tmp_path)


def projection():
    path=Path(__file__).parents[1]/'apps/api/v35_api/preselection_service.py'
    fn=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_project_wechat_input_gap')
    ns=dict(Path=Path,json=json,hashlib=hashlib)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),ns)
    return ns['_project_wechat_input_gap']


def test_original_consumer_missing_pair_reports_exact_paths_without_creating_inputs(tmp_path):
    root=tmp_path/'input';root.mkdir()
    result=sync_wechat_preselection('20261027',input_root=root)
    assert result['status']=='CANNOT_CONFIRM'
    assert result['missing_inputs']==[str(root/'20261027/wechat_manifest.json'),str(root/'20261027/wechat_rows.csv')]
    assert result['no_run'] is True and not list(root.iterdir())


def test_api_missing_pair_projection_is_exact_date_readonly_and_does_not_relabel_real_pool(tmp_path):
    root=tmp_path/'inputs';root.mkdir();data=tmp_path/'data';receipt=data/'receipts/wechat_preselection/20261027.json';receipt.parent.mkdir(parents=True)
    value=sync_wechat_preselection('20261027',input_root=root);receipt.write_text(json.dumps(value));before=receipt.read_bytes()
    response={'pools':[{'pool_id':'wechat_public_account_v3_preselect','pool_size':0,'rows':[],'status':'CANNOT_CONFIRM'}]}
    result=projection()(response,data,'20261027')
    assert len(result['pools'][0]['missing_inputs'])==2 and '原pair owner' in result['pools'][0]['cannot_confirm'][0]
    assert response['pools'][0].get('missing_inputs') is None and receipt.read_bytes()==before
    assert projection()(response,data,'20261028')==response
    response['pools'][0]['pool_size']=10
    assert projection()(response,data,'20261027')==response


@pytest.mark.parametrize('body',[[],None,'invalid'])
def test_api_invalid_receipt_shape_is_nonblocking(tmp_path,body):
    data=tmp_path/'data';receipt=data/'receipts/wechat_preselection/20261027.json';receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps(body));response={'pools':[]}
    assert projection()(response,data,'20261027')==response
