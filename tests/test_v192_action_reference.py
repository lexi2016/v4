"""Frozen two-event denominator correction tests; all data are synthetic fixtures."""
import copy,hashlib,importlib.util,json,os,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
PAYLOAD=ROOT/"ops/runtime_payloads/a_share_daily_sync_v192_action_reference_v1.py"
BATCH=Path("/Users/lexi/Desktop/学习/因子工厂/research/a_v192_signal_pool_return_stability_v1/batches/v192_logic_input_diagnostic_20261020")

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
@pytest.fixture(scope="session",autouse=True)
def registered_scope():
 context=json.loads(Path(os.environ["NEXT_TDX_ACTION_TEST_CONTEXT"]).read_text());cp=Path(context["contract_path"]);c=json.loads(cp.read_text());assert sha(PAYLOAD)==c["payload_sha256"] and sha(__file__)==c["test_sha256"]
 events=[json.loads(l) for l in (BATCH.parents[3]/"contracts/EXPERIMENT_REGISTRY.jsonl").read_text().splitlines() if l.strip()];same=[e for e in events if e["execution_id"]==context["execution_id"]];assert len(same)==1 and same[0]["event_type"]=="RUN_STARTED" and same[0]["contract_sha256"]==sha(cp)
@pytest.fixture
def m(monkeypatch):
 for key in ("V35_A_SYNC_ACTION_REFERENCE_MANIFEST","V35_A_SYNC_ACTION_REFERENCE_SHA256","V35_A_SYNC_TRUSTED_CAS_INPUTS"):monkeypatch.delenv(key,raising=False)
 spec=importlib.util.spec_from_file_location("action_test_"+os.urandom(4).hex(),PAYLOAD);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod);return mod

def bar(date,close):return {"year":date//10000,"month":date//100%100,"day":date%100,"open":close,"high":close,"low":close,"close":close,"amount":10000.0,"vol":1000.0}
def case(code):
 if code=="301550":return 0,20260528,171.9,20260529,114.11,{"cash_per_share":0.3,"share_change_ratio":0.45,"nominal_share_ratio":0.45,"rights_price":0.0}
 return 1,20260526,42.31,20260527,27.57,{"cash_per_share":0.0,"share_change_ratio":0.47,"nominal_share_ratio":0.48,"rights_price":0.0}
def manifest(m,tmp,code="301550",event_close=None,change=None):
 market,prior,close,date,current,terms=case(code);rows=[bar(prior,close),bar(date,current if event_close is None else event_close)];tmp.mkdir(parents=True,exist_ok=True)
 pdf=tmp/"official.pdf";pdf.write_bytes(b"%PDF-synthetic-official-fixture")
 request={"category":9,"market":market,"code":code,"start":0,"count":800,"target_date":20261020,"previous_close":None,"after_date":None};time="2026-10-21T01:00:00+00:00";response=tmp/"response.json";response.write_text(json.dumps({"observed_at":time,"request":request,"response_rows":rows}))
 event={"code":code,"market":market,"event_date":date,"prior_date":prior,"prior_close":close,"event_close":rows[1]["close"],"prior_bar_sha256":hashlib.sha256(m.pack_hq_bar(rows[0])).hexdigest(),"event_bar_sha256":hashlib.sha256(m.pack_hq_bar(rows[1])).hexdigest(),"terms":terms,"evidence":[{"path":str(pdf),"sha256":sha(pdf),"url":"https://disc.static.szse.cn/fixture.pdf","pdf_pages":[2]}],"source_response":{"path":str(response),"sha256":sha(response),"request":request,"observed_at":time}}
 data={"schema_version":"v192.action_reference.v1","events":[event]}
 if change:change(data)
 path=tmp/"manifest.json";path.write_text(json.dumps(data));return path,sha(path),rows,event
class API:
 def __init__(self,rows):self.rows=rows;self.calls=0
 def get_security_bars(self,*args):self.calls+=1;return self.rows
 def connect(self,*args,**kwargs):return True
 def disconnect(self):pass

def fetch(m,rows,code,refs=None,**kwargs):
 market,_,_,date,_,_=case(code);return m._fetch_valid_target_bars(API(rows),m.DailyTarget(code,market,Path("unused")),date,None,800,None,action_references=refs,**kwargs)
@pytest.mark.parametrize("code",["301550","688489"])
def test_two_gates_and_raw_bytes(m,tmp_path,code):
 path,digest,rows,event=manifest(m,tmp_path,code);refs=m._load_action_reference_manifest(path,digest);market,_,_,date,_,terms=case(code)
 native=tmp_path/(("sz" if market==0 else "sh")+code+".day");native.write_bytes(b"".join(m.pack_hq_bar(row) for row in rows));before=native.read_bytes();audit=[]
 accepted,status=fetch(m,rows,code,refs,reference_audit=audit);assert status=="OK" and accepted==rows and len(audit)==1
 assert audit[0]["reference_used"]==(event["prior_close"]-terms["cash_per_share"])/(1+terms["share_change_ratio"])
 assert m._local_history_status(native,date,action_references=refs)[1] is None and native.read_bytes()==before
 assert fetch(m,rows,code)[1]==m.CROSS_DAY_CLOSE_RATIO
 assert m._local_history_status(native,date)[1]==m.CROSS_DAY_CLOSE_RATIO
@pytest.mark.parametrize("mutation",["code","date","prior_date","term","nan","duplicate","wildcard","evidence_sha","response_sha","event_bar_sha","extra"])
def test_manifest_rejects_invalid(m,tmp_path,mutation):
 def change(data):
  e=data["events"][0]
  if mutation=="code":e["code"]="000001"
  elif mutation=="date":e["event_date"]=20260530
  elif mutation=="prior_date":e["prior_date"]=20260527
  elif mutation=="term":e["terms"]["share_change_ratio"]=0.48
  elif mutation=="nan":e["prior_close"]=float("nan")
  elif mutation=="duplicate":data["events"].append(copy.deepcopy(e))
  elif mutation=="wildcard":e["code"]="*"
  elif mutation=="evidence_sha":e["evidence"][0]["sha256"]="0"*64
  elif mutation=="response_sha":e["source_response"]["sha256"]="0"*64
  elif mutation=="event_bar_sha":e["event_bar_sha256"]="0"*64
  else:e["unapproved"]=True
 path,digest,_,_=manifest(m,tmp_path,change=change)
 with pytest.raises(m.ActionReferenceError):m._load_action_reference_manifest(path,digest)
def test_wrong_or_missing_manifest_sha(m,tmp_path):
 path,_,_,_=manifest(m,tmp_path)
 with pytest.raises(m.ActionReferenceError):m._load_action_reference_manifest(path,"0"*64)
 with pytest.raises(m.ActionReferenceError):m._load_action_reference_manifest(path,None)
@pytest.mark.parametrize("field",["prior_close","event_close","prior_bar_volume"])
def test_identity_drift_fails_both_gates(m,tmp_path,field):
 path,digest,rows,_=manifest(m,tmp_path);refs=m._load_action_reference_manifest(path,digest);changed=copy.deepcopy(rows)
 if field=="prior_close":changed[0].update(open=170.0,high=170.0,low=170.0,close=170.0)
 elif field=="event_close":changed[1].update(open=113.0,high=113.0,low=113.0,close=113.0)
 else:changed[0]["vol"]+=1
 audit=[];assert fetch(m,changed,"301550",refs,reference_audit=audit)[1]==m.ACTION_REFERENCE_IDENTITY_MISMATCH;assert audit[0]["reference_used"] is None and "calculated_reference" in audit[0]
 native=tmp_path/"sz301550.day";native.write_bytes(b"".join(m.pack_hq_bar(x) for x in changed));assert m._local_history_status(native,20260529,action_references=refs)[1]==m.ACTION_REFERENCE_IDENTITY_MISMATCH
def test_adjusted_ratio_still_checked(m,tmp_path):
 path,digest,rows,_=manifest(m,tmp_path,event_close=300.0);refs=m._load_action_reference_manifest(path,digest)
 assert fetch(m,rows,"301550",refs)[1]==m.CROSS_DAY_CLOSE_RATIO
def test_missing_rule_and_other_date_keep_original_gate(m,tmp_path):
 path,digest,_,_=manifest(m,tmp_path);refs=m._load_action_reference_manifest(path,digest);_,prior,close,date,current,_=case("688489")
 assert fetch(m,[bar(prior,close),bar(date,current)],"688489",refs)[1]==m.CROSS_DAY_CLOSE_RATIO
 assert fetch(m,[bar(20260604,100),bar(20260605,30)],"301550",refs)[1]==m.OUT_OF_SCOPE_AFTER_TARGET_DATE
 target=m.DailyTarget("301550",0,tmp_path/"x");assert m._fetch_valid_target_bars(API([bar(20260604,100),bar(20260605,30)]),target,20260605,None,800,action_references=refs)[1]==m.CROSS_DAY_CLOSE_RATIO

def test_incremental_prior_identity_and_future_append(m,tmp_path):
 path,digest,rows,_=manifest(m,tmp_path);refs=m._load_action_reference_manifest(path,digest);target=m.DailyTarget("301550",0,tmp_path/"x")
 assert m._fetch_valid_target_bars(API([rows[1]]),target,20260529,171.9,800,20260528,action_references=refs,previous_date=20260528,previous_bar=rows[0])[1]=="OK"
 assert m._fetch_valid_target_bars(API([rows[1]]),target,20260529,171.9,800,20260528,action_references=refs,previous_date=20260527,previous_bar=rows[0])[1]==m.ACTION_REFERENCE_IDENTITY_MISMATCH
 native=tmp_path/"sz301550.day";native.write_bytes(b"".join(m.pack_hq_bar(x) for x in rows+[bar(20260601,115.0)]));assert m._local_history_status(native,20260601,action_references=refs)[1] is None

def test_run_sync_wiring_and_context_reset(m,tmp_path,monkeypatch):
 path,digest,rows,_=manifest(m,tmp_path/"fixture");native=tmp_path/"sz301550.day";target=m.DailyTarget("301550",0,native);api=API(rows);monkeypatch.setattr(m,"RUN_DIR",tmp_path/"run1")
 result=m.run_sync([target],target_date="20260529",api_factory=lambda *_:api,host_candidates=[("offline",7709)],count=800,action_reference_manifest=path,action_reference_sha256=digest)
 assert result["status"]=="PASS" and api.calls==1 and result["action_reference"]["configured"] and result["action_reference"]["comparisons"]
 assert m._local_history_status(native,20260529)[1] is None
 monkeypatch.setattr(m,"RUN_DIR",tmp_path/"run2");no_api=lambda *_:pytest.fail("local gate must precede provider")
 result=m.run_sync([target],target_date="20260529",api_factory=no_api,host_candidates=[("offline",7709)])
 assert not result["action_reference"]["configured"] and m._ACTION_REFERENCE_CONTEXT is None and m._local_history_status(native,20260529)[1]==m.CROSS_DAY_CLOSE_RATIO
 m._ACTION_REFERENCE_CONTEXT={"old":True}
 with pytest.raises(m.ActionReferenceError):m.run_sync([],target_date="20260529",api_factory=no_api,host_candidates=[("offline",7709)],action_reference_manifest=path,action_reference_sha256="0"*64)
 assert m._ACTION_REFERENCE_CONTEXT is None

def test_cli_env_and_cas_gate(m,tmp_path,monkeypatch):
 path,digest,rows,_=manifest(m,tmp_path/"fixture");args=m.parse_args(["--target-date","20260529","--action-reference-manifest",str(path),"--action-reference-sha256",digest]);assert args.action_reference_manifest==path and args.action_reference_sha256==digest
 native=tmp_path/"sz301550.day";native.write_bytes(b"".join(m.pack_hq_bar(x) for x in rows));target=m.DailyTarget("301550",0,native);monkeypatch.setattr(m,"RUN_DIR",tmp_path/"run");monkeypatch.setenv(m.ACTION_REFERENCE_MANIFEST_ENV,str(path));monkeypatch.setenv(m.ACTION_REFERENCE_SHA256_ENV,digest)
 result=m.run_sync([target],target_date="20260529",api_factory=lambda *_:pytest.fail("alreadycurrent"),host_candidates=[("offline",7709)]);assert result["status"]=="PASS" and result["by_symbol"]["301550"]["status"]=="ALREADY_CURRENT"
 assert m._trusted_cas_local_reuse({"target_date":20260529},target,20260529,sha(native),rows,m.ACTION_REFERENCE_IDENTITY_MISMATCH,[]) is None
