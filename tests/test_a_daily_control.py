from pathlib import Path
import ast,hashlib,json,runpy,subprocess,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
HELPER=ROOT/'docs/handoffs/a_daily_1530_20261029/control_candidate.py'
def test_control_checks_are_not_asserts():
    assert not any(isinstance(n,ast.Assert) for n in ast.walk(ast.parse(HELPER.read_text())))
@pytest.mark.parametrize('optimized',[False,True])
def test_invalid_review_blocked_without_service_action(tmp_path,optimized):
    review=tmp_path/'review.json';review.write_text(json.dumps({'verdict':'FAIL'}))
    p=subprocess.run([sys.executable,*(['-O'] if optimized else []),str(HELPER),'stage','--review',str(review),'--review-sha256',hashlib.sha256(review.read_bytes()).hexdigest()],capture_output=True,text=True)
    assert p.returncode!=0 and 'SCOPED_REVIEW_REQUIRED' in p.stderr
@pytest.mark.parametrize('label',['SOURCE','STAGE','DURABLE'])
def test_full_inventory_rejects_unlisted_file(tmp_path,label):
    ns=runpy.run_path(str(HELPER));(tmp_path/'allowed.py').write_text('pass\n')
    expected=ns['inventory_tree'](tmp_path);ns['verify_inventory'](tmp_path,expected,label)
    (tmp_path/'unlisted.py').write_text('pass\n')
    with pytest.raises(ValueError,match=label+'_FULL_INVENTORY_DRIFT'):ns['verify_inventory'](tmp_path,expected,label)
