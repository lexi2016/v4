"""Offline regressions for Issue #38; no external model, network or trading."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from ops.announcement_prefilter_qwen import (
    LocalModelIdentity, TriageEngine, audit_catalog, route_article,
    verify_facts, parse_usage, ProviderFailure,
)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def fixture(articles):
    rows=[]
    bodies=[]
    for code, title, body in articles:
        rows.append(dict(art_code=code, title=title, notice_date="2026-10-11 10:05:00",
                         source_issuer_codes=[dict(code="01191", name="发行人", market_code="116", ann_type="H")],
                         raw_body_sha256=sha("listing"+code), source_ref={"sha256":sha("source"+code)}))
        bodies.append(dict(art_code=code, title=title,
            body_status="COMPLETE_CONTENT_API_BODY" if body is not None else "BODY_CAPTURE_FAILED",
            body_text=body, body_text_sha256=sha(body) if body is not None else None))
    return ({"readback_status":"VERIFIED", "target_trade_date":"20261012",
             "publication_date":"2026-10-11", "catalog":{"status":"COMPLETE", "run_id":"a"*32,
             "sha256":"b"*64,"manager_consumer_rows":rows}},
            {"target_notice_date":"2026-10-11", "article_count":len(bodies), "rows":bodies})


def model():
    return LocalModelIdentity(name="Qwen3.8-27B-8bit", revision="f"*40,
        config_sha256="c"*64, endpoint="http://127.0.0.1:8199/v1/chat/completions",
        proof_status="VERIFIED_LOCAL_PROCESS_AND_WEIGHTS", proof_sha256="e"*64)


def answer(body):
    quote = body
    return {"issuer_code":"01191", "classification":"MATERIAL_RESEARCH",
        "is_material":True, "facts":[{"quote":quote,"claim":quote,
        "subject":"发行人", "relation":"UNKNOWN", "event_status":"UNKNOWN",
        "number":None,"unit":None}]}


class Fake:
    def __init__(self): self.calls=0
    def __call__(self, title, body, identity):
        self.calls+=1
        return {"content":json.dumps(answer(body),ensure_ascii=False),
                "usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120}}


def test_fail_closed_when_no_body_and_complete_reconciliation(tmp_path):
    catalog, body = fixture([("A1","重大合同","发行人签署重大合同"),
                              ("A2","年度业绩","发行人盈利警告"),
                              ("A3","未知公告",None)])
    fake=Fake()
    out=TriageEngine(tmp_path, model(),fake).run(catalog,body)
    assert len(out["rows"]) == 3
    assert fake.calls == 2
    assert out["rows"][2]["route"] == "NOT_ASSESSED"
    assert out["rows"][2]["reason"] == "BODY_CAPTURE_FAILED"
    assert out["target_trade_date"] == "20261012"
    assert out["publication_date"] == "2026-10-11"


def test_routine_skip_needs_exact_template_and_no_exception():
    clean="兹通知股东，公司通讯将以电子方式发送，请浏览公司网站查阅。"
    assert route_article("公司通讯的发布通知",clean)[0]=="SKIPPED_ROUTINE"
    assert route_article("公司通讯的发布通知",clean+" 本期融资100万元")[0]=="MODEL_REQUIRED"
    assert route_article("公司通讯的发布通知",clean+" 同时重大诉讼")[0]=="MODEL_REQUIRED"
    assert route_article("未知事项", clean)[0]=="MODEL_REQUIRED"
    assert route_article("董事会会议通告", "2026年10月30日召开会议")[0]=="MODEL_REQUIRED"


def test_source_conflict_or_wrong_date_does_not_become_success(tmp_path):
    catalog, body=fixture([("A1","重大合同","发行人签署重大合同")])
    catalog["catalog"]["manager_consumer_rows"][0]["notice_date"]="2026-10-09"
    out=TriageEngine(tmp_path,model(),Fake()).run(catalog,body)
    assert out["rows"][0]["route"]=="NOT_ASSESSED"
    assert out["rows"][0]["reason"]=="PUBLICATION_DATE_MISMATCH"
    catalog, body=fixture([("A1","重大合同","发行人签署重大合同")])
    body["rows"][0]["body_text_sha256"]="0"*64
    out=TriageEngine(tmp_path,model(),Fake()).run(catalog,body)
    assert out["rows"][0]["reason"]=="BODY_SHA256_MISMATCH"


def test_duplicate_identical_fold_and_conflicts_are_not_silent():
    c,b=fixture([("A1","重大合同","发行人签署重大合同")])
    from copy import deepcopy
    c["catalog"]["manager_consumer_rows"].append(deepcopy(c["catalog"]["manager_consumer_rows"][0]))
    pairs=audit_catalog(c,b)
    assert len(pairs)==2 and pairs[1]["error"]=="DUPLICATE_IDENTICAL"
    c["catalog"]["manager_consumer_rows"][1]["source_issuer_codes"][0]["code"]="09876"
    pairs=audit_catalog(c,b)
    assert all(x["error"]=="IDENTITY_CONFLICT" for x in pairs)


def test_semantic_regressions_and_quote_proof():
    body="邦泰跃尚为独立第三方，尚有未偿还本金人民币200万元。"
    wrong=answer(body)
    wrong["facts"][0].update(subject="邦泰跃尚",number="200",unit="万元",relation="ASSOCIATE",event_status="COMPLETED")
    with pytest.raises(ValueError): verify_facts(wrong,body,"01191")
    wrong["facts"][0].update(relation="INDEPENDENT_THIRD_PARTY",event_status="OUTSTANDING")
    assert verify_facts(wrong,body,"01191")["status"]=="QUOTE_CHECKED_REVIEW_REQUIRED"
    wrong["facts"][0]["quote"]="捏造的引文"
    with pytest.raises(ValueError): verify_facts(wrong,body,"01191")


def test_singleflight_cache_and_body_sha_invalidation(tmp_path):
    c,b=fixture([("A1","重大合同","发行人签署重大合同")])
    fake=Fake(); engine=TriageEngine(tmp_path,model(),fake)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _:engine.run(c,b),range(6)))
    assert fake.calls==1
    assert sum(r["new_model_calls"] for r in results)==1
    second=engine.run(c,b)
    assert second["new_model_calls"]==0 and second["new_model_tokens"]==0
    b["rows"][0]["body_text"]="发行人签署金额较大的重大合同"
    b["rows"][0]["body_text_sha256"]=sha(b["rows"][0]["body_text"])
    third=engine.run(c,b)
    assert third["new_model_calls"]==1 and fake.calls==2


def test_failures_never_cached_and_usage_failures_preserved(tmp_path):
    c,b=fixture([("A1","重大合同","发行人签署重大合同")])
    class Broken:
        def __init__(self):self.calls=0
        def __call__(self,*_):
            self.calls+=1
            raise ProviderFailure("UPSTREAM_TIMEOUT",{"prompt_tokens":7,"total_tokens":7})
    fake=Broken();engine=TriageEngine(tmp_path,model(),fake)
    one=engine.run(c,b);two=engine.run(c,b)
    assert fake.calls==2
    assert all(r["rows"][0]["route"]=="NOT_ASSESSED" for r in (one,two))
    assert one["new_model_tokens"]==7 and two["new_model_tokens"]==7


def test_usage_does_not_double_count_and_missing_is_not_zero():
    assert parse_usage({"prompt_tokens":10,"completion_tokens":4,"total_tokens":14,"cached_tokens":5})["total_tokens"]==14
    assert parse_usage({"prompt_tokens":10})["total_tokens"]=="NOT_REPORTED"
    assert parse_usage(None)["total_tokens"]=="NOT_REPORTED"


def test_unknown_model_identity_never_calls(tmp_path):
    c,b=fixture([("A1","重大合同","发行人签署重大合同")])
    identity=LocalModelIdentity(name="qwen-alias",revision="",config_sha256="",endpoint="http://127.0.0.1:8199/v1/chat/completions", proof_status="CANNOT_CONFIRM",proof_sha256="")
    f=Fake();out=TriageEngine(tmp_path,identity,f).run(c,b)
    assert f.calls==0
    assert out["rows"][0]["route"]=="NOT_ASSESSED"
    assert out["rows"][0]["reason"]=="MODEL_IDENTITY_CANNOT_CONFIRM"


def test_model_quote_validation_failure_is_not_cached(tmp_path):
    c,b=fixture([("A1","重大合同","发行人签署重大合同")])
    class Hallucinating:
        calls=0
        def __call__(self,*_):
            self.calls+=1
            data=answer("捏造引文")
            return {"content":json.dumps(data,ensure_ascii=False),
                    "usage":{"prompt_tokens":8,"completion_tokens":3,"total_tokens":11}}
    f=Hallucinating();engine=TriageEngine(tmp_path,model(),f)
    x=engine.run(c,b)
    assert x["rows"][0]["route"]=="NOT_ASSESSED"
    assert x["new_model_tokens"]==11 and f.calls==1
    assert engine.run(c,b)["new_model_calls"]==1 and f.calls==2


def test_invalid_cache_sha_rejected_instead_of_silent_model_fallback(tmp_path):
    c,b=fixture([("A1","重大合同","发行人签署重大合同")])
    f=Fake();engine=TriageEngine(tmp_path,model(),f)
    engine.run(c,b)
    file=next((tmp_path/"cache").glob("*.json"))
    raw=json.loads(file.read_text())
    raw["model_result"]["facts"][0]["quote"]="edited"
    file.write_text(json.dumps(raw))
    with pytest.raises(ValueError,match="SEAL_INVALID"):
        engine.run(c,b)
    assert f.calls==1


def test_core_engine_accepts_date_from_run_not_cache(tmp_path):
    c,b=fixture([("A1","重大合同","发行人签署重大合同")])
    f=Fake();e=TriageEngine(tmp_path,model(),f)
    first=e.run(c,b)
    c["target_trade_date"]="20261013"
    c["catalog"]["target_trade_date"]="20261013"
    second=e.run(c,b)
    assert second["target_trade_date"]=="20261013"
    assert second["new_model_calls"]==0 and f.calls==1
    assert second["rows"][0]["catalog_run_id"]==first["rows"][0]["catalog_run_id"]
    # A true PIT/cutoff check remains with the original source owner, not cache.


def test_no_network_without_verified_identity_and_missing_usage(tmp_path):
    c,b=fixture([("A1","重大合同","发行人签署重大合同")])
    class MissingUsage:
        def __call__(self,*_):
            return {"content":json.dumps(answer("发行人签署重大合同"),ensure_ascii=False)}
    result=TriageEngine(tmp_path,model(),MissingUsage()).run(c,b)
    assert result["new_model_calls"]==1
    assert result["new_model_tokens"]=="NOT_REPORTED"
    assert result["new_model_tokens_known_sum"]==0


def test_cli_capture_receipt_binding_and_no_model_remains_unassessed(tmp_path):
    from ops.run_manager_announcement_prefilter import run_from_evidence
    c,b=fixture([("A1","重大合同","发行人签署重大合同")])
    def dump(name,value):
        path=tmp_path/name
        path.write_text(json.dumps(value,ensure_ascii=False))
        return hashlib.sha256(path.read_bytes()).hexdigest()
    catalog_sha=dump("catalog_read.json",c)
    body_sha=dump("body_corpus.json",b)
    receipt={"schema_version":"v4.manager_research.announcement_daily_capture.v1",
       "evidence_run_id":"1"*32,"target_trade_date":"20261012",
       "publication_date":"2026-10-11","catalog_run_id":"a"*32,
       "catalog_product_sha256":"b"*64,"catalog_read_file_sha256":catalog_sha,
       "body_corpus_file_sha256":body_sha,"semantic_status":"NOT_REVIEWED",
       "RESEARCH_ONLY":True,"production_allowed":False,
       "buy_gate_updated":False,"orders_sent":False}
    dump("capture_receipt.json",receipt)
    result=run_from_evidence(evidence_root=tmp_path,cache_root=tmp_path/"cache_tmp",
       output=tmp_path/"output.json")
    assert result["unassessed_rows"]==1 and result["new_model_calls"]==0
    assert result["owner_import_status"]=="NOT_RUN"
    assert (tmp_path/"output.json").exists()
    receipt["body_corpus_file_sha256"]="0"*64
    dump("capture_receipt.json",receipt)
    with pytest.raises(ValueError,match="SOURCE_OR_DATE_MISMATCH"):
        run_from_evidence(evidence_root=tmp_path,cache_root=tmp_path/"cache_tmp",
            output=tmp_path/"bad.json")
    assert not (tmp_path/"bad.json").exists()
