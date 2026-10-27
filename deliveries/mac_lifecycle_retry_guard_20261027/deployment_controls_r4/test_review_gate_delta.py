from pathlib import Path
import json
import pytest
import controller as c

def case(tmp_path,monkeypatch):
 monkeypatch.setattr(c,'D',tmp_path);(tmp_path/'PLAN.json').write_text('{}');(tmp_path/'probe.py').write_text('accepted probe')
 (tmp_path/'CASE_MANIFEST.json').write_text(json.dumps({'files':{'PLAN.json':c.sha(tmp_path/'PLAN.json'),'probe.py':c.sha(tmp_path/'probe.py')}}))
 r={'verdict':'PASS','deployment_plan_sha256':c.sha(tmp_path/'PLAN.json'),'controller_sha256':c.sha(c.__file__),'case_manifest_sha256':c.sha(tmp_path/'CASE_MANIFEST.json')}
 p=tmp_path/'review.json';p.write_text(json.dumps(r));return p,r

def test_review_requires_actual_bound_case_and_controller(tmp_path,monkeypatch):
 p,r=case(tmp_path,monkeypatch);c.approve(p,c.sha(p));r['case_manifest_sha256']='unbound';p.write_text(json.dumps(r))
 with pytest.raises(c.Stop,match='SCOPED_DELTA'):c.approve(p,c.sha(p))

def test_review_binds_materialized_probe_before_dynamic_imports(tmp_path,monkeypatch):
 p,r=case(tmp_path,monkeypatch);(tmp_path/'probe.py').write_text('changed after review')
 with pytest.raises(c.Stop,match='PIN_DRIFT'):c.approve(p,c.sha(p))
