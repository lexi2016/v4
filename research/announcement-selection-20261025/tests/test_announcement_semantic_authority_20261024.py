"""Offline synthetic binding cases. PASS here is never business-semantic PASS."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from ops import run_manager_flash_announcements as original_producer
_ORIGINAL_MATERIAL_BUILDER = original_producer._owned_request_material

from infrastructure.owned_io import SafeRoot
from v4.manager_workbench import announcement_semantic_authority as authority
from v4.manager_workbench import announcement_delivery as delivery
from v4.manager_workbench.announcement_preprocessing import SEMANTIC_CONTRACT, SEMANTIC_CONTRACT_VERSION
from v4.manager_workbench.announcement_projection import project_delivery_contribution


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def genuine_material(*, runtime_sha=None, model_sha=None):
    """Original pure constructor, exact full frozen envelope; never add aliases."""
    from v4.manager_workbench.engines import announcement as engine
    path=Path('/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_FULL_AUDIT_20261023/canary-input-preparation/authority-materials/request-material.original.json')
    original_raw=path.read_bytes()
    assert sha(original_raw)=='0dfc87bf405a9bb17b207ca41009d6227d01303978e89c90c67724b275a29c99'
    original=json.loads(original_raw);base=deepcopy(original)
    base['prompt']=base['prompt'].removesuffix('\n\n'+SEMANTIC_CONTRACT)
    base['prompt_sha256']=sha(base['prompt'].encode())
    base.pop('validation_contract_sha256')
    base['source_code_sha256'].pop('v4/manager_workbench/engines/announcement.py')
    config=base['configuration_material']
    for key in ('validation_contract_sha256','semantic_contract_version','base_prompt_sha256','system_prompt_sha256'):
        config.pop(key)
    for key,value in [('runtime_settings_sha256',runtime_sha),('model_settings_sha256',model_sha)]:
        if value is not None:base[key]=config[key]=value
    if model_sha is not None:
        base['runtime_limits']['model_settings_sha256']=model_sha
        config['runtime_limits']['model_settings_sha256']=model_sha
    base['configuration_sha256']=sha(encoded(config))
    contract=SimpleNamespace(read_prompt=engine.READ_PROMPT,reader_schema=engine.READER_SCHEMA,
        prompt_version=engine.PROMPT_VERSION,source_sha256=sha(Path(engine.__file__).read_bytes()))
    value=_ORIGINAL_MATERIAL_BUILDER(SimpleNamespace(_full_day_request_material=lambda c:deepcopy(base)),
        SimpleNamespace(load_active_contract=lambda *a:contract),contract)
    assert 'model_id' not in value and 'max_completion_tokens' not in value
    if runtime_sha is None and model_sha is None:assert value==original
    return value


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*a, **k):
        pytest.fail("Task8a attempted network or production material read")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    original = SafeRoot.read_bytes
    def local_only(io, ref, **kwargs):
        if str(io.root).startswith(("/Users/lexi/Library/", "/Users/lexi/Desktop/学习/v4_app")):
            forbidden()
        return original(io, ref, **kwargs)
    monkeypatch.setattr(SafeRoot, "read_bytes", local_only)


class SyntheticCase:
    """Build producer-shaped files without invoking any producer, model or gate."""
    def __init__(self, root):
        self.root = root
        self.state, self.capture, self.config = [SafeRoot(root / x) for x in ("state", "capture", "config")]
        self.code = SafeRoot(Path(__file__).resolve().parents[1])
        vendor=Path('/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary')
        raw_sources={name:(vendor/('evidence/recent-day-20261014/'+name if name=='recent_day_freeze.py' else name)).read_bytes()
            for name in authority.PURE_SOURCE_PINS}
        self.pipeline=authority.load_pure_projection_sources(raw_sources)
        pure_bindings={}
        for name,raw in raw_sources.items():
            self.config.write_bytes('pure/'+name,raw)
            pure_bindings[name]={'artifact_ref':'pure/'+name,'sha256':sha(raw)}
        from v4.manager_workbench.engines import announcement as contract
        self.reader_contract=SimpleNamespace(reader_schema=contract.READER_SCHEMA,read_prompt=contract.READ_PROMPT,
            prompt_version=contract.PROMPT_VERSION,validate_reader=contract._validate_reader)
        self.membership={'status':'VERIFIED','codes':['HK.00001'],'authority_sha256':'f'*64}
        self.job, self.article, self.day = "a" * 32, "EASTMONEY:ONLY_ARTICLE", "20261021"
        self.prefix = "announcement_flash/jobs/" + self.job
        body = "公司名稱：SYNTHETIC有限公司\n股份代號：00001\n本公司2026年上半年营业收入为人民币100万元，同比增长20%。\n"
        source = {"body_text": body, "body_text_sha256": sha(body.encode()), "body_complete": True}
        source_ref = self.put(self.capture, "products/", source, addressed=True)
        raw_row={'art_code':'ONLY_ARTICLE','SYNTHETIC':True}
        listing = self.put(self.capture, "objects/listing.bin", {"data":{"list":[raw_row]}})
        self.row = dict(art_code="ONLY_ARTICLE", body_text=body, body_text_sha256=source["body_text_sha256"],
            source_sha256=source_ref["sha256"], body_complete=True, body_artifact_ref=source_ref["artifact_ref"],
            source_issuer_codes=[{"code": "HK.00001",'name':'SYNTHETIC ISSUER'}], publication_date="2026-10-20",
            raw_row=raw_row,listing_source_ref=listing,title='SYNTHETIC STRUCTURAL FIXTURE',available_at='2026-10-21T01:00:00+00:00')
        # Keep the genuine content-addressed listing convention as well.
        listing_raw=self.capture.read_bytes(listing['artifact_ref'])
        listing={'artifact_ref':'objects/'+sha(listing_raw)+'.bin','sha256':sha(listing_raw)}
        self.capture.write_bytes(listing['artifact_ref'],listing_raw);self.row['listing_source_ref']=listing
        capture_ref = self.put(self.capture, "products/", {"rows": [self.row]}, addressed=True)
        code_refs = ["v4/manager_workbench/announcement_semantic_authority.py",
            "v4/manager_workbench/engines/announcement.py", "v4/manager_workbench/announcement_preprocessing.py",
            "ops/run_manager_flash_announcements.py", "v4/manager_workbench/announcement_update.py",
            "v4/manager_workbench/announcement_test.py"]
        codes = {p: sha(self.code.read_bytes(p)) for p in code_refs}
        runner,_,helper=self.pipeline
        self.material = genuine_material()
        material_ref = self.put(self.config, "request-material.json", self.material)
        entry = dict(article_id=self.article, source_sha256=source_ref["sha256"], body_sha256=source["body_text_sha256"],
            symbol="HK.00001", primary_disposition="MODEL_ORDINARY", part_count=0, expected_requests=1)
        self.report = dict(schema="v4.manager_workbench.announcement_preprocessing.v1", job_id=self.job,
            target_date=self.day, accounting_closed=True, capture_product=capture_ref,
            catalogue=[entry], execution_manifest=[entry], first_article_id=self.article,
            processing_contract=original_producer._classification_contract(self.material, SimpleNamespace(MODEL_ID="qwen3_8_flash_next")),
            counts={"expected_model_requests": 1, "model_required_articles": 1},
            limits={"max_articles": 8, "max_model_requests": 16, "max_reader_parts_per_article": 6})
        report_ref = self.put(self.state, self.prefix + "/preprocessing-report.json", self.report)
        self.report_sha = report_ref["sha256"]
        inp = dict(job_id=self.job, target_date=self.day, capture_product=capture_ref,membership_gate=self.membership)
        input_ref = self.put(self.state, self.prefix + "/input.json", inp)
        identities = dict(controller="SYNTHETIC_CONTROLLER", writer="SYNTHETIC_WRITER", executor="SYNTHETIC_EXECUTOR",
            reviewer="SYNTHETIC_INDEPENDENT_REVIEWER", reviewer_execution_id="SYNTHETIC_REVIEW_EXECUTION")
        dispatch = dict(schema=authority.DISPATCH_SCHEMA, job_id=self.job, **identities,
            receipt_initially_absent=True, registration_initially_absent=True)
        dispatch_ref = self.put(self.config, "reviewer-dispatch.json", dispatch)
        self.contract = dict(schema=authority.PRE_RUN_SCHEMA, job_id=self.job, target_date=self.day,
            market="HK_CONNECT", **entry, input=input_ref, report=report_ref, capture=capture_ref,
            capture_origin={**capture_ref, "row_index": 0},
            capture_sizes={'capture':len(self.capture.read_bytes(capture_ref['artifact_ref'])),
                'origin':len(self.capture.read_bytes(capture_ref['artifact_ref']))},projection_sources=pure_bindings,
            source=source_ref, source_objects=[listing], capture_row_index=0, request_material=material_ref,
            code_identity=codes, identities=identities,
            roots={"state": str(self.state.root), "capture": str(self.capture.root),
                "authority": str(self.config.root), "code": str(self.code.root)},
            semantic_contract_version=SEMANTIC_CONTRACT_VERSION, semantic_contract_sha256=sha(SEMANTIC_CONTRACT.encode()),
            budget={"expected_requests": 1, "max_attempts": 1, "prior_attempts": 0},
            projection_pit_annotation=runner._simple_workflow_pit_provenance({'article_metadata':{
                'pit_status':'CANNOT_CONFIRM','pit_reason':'OFFICIAL_FIRST_PUBLICATION_TIME_NOT_BOUND'}})['annotation'],
            outputs={"receipt_ref": self.prefix + "/semantic-authority/receipt.json",
                "registration_ref": self.prefix + "/semantic-authority/registration.json"})
        self.descriptor = dict(schema=authority.DESCRIPTOR_SCHEMA, job_id=self.job,
            pre_run=self.put(self.config, "pre-run.json", self.contract), dispatch=dispatch_ref)
        self.context_binding = dict(run_id="SYNTHETIC_RUN", context_sha256="d"*64, source_manifest_sha256="e"*64)
        self.artifacts = None

    def put(self, io, ref, value, *, addressed=False):
        raw = encoded(value)
        if addressed:
            ref += sha(raw) + ".json"
        io.write_bytes(ref, raw)
        return {"artifact_ref": ref, "sha256": sha(raw)}

    def verifier(self):
        return authority.FirstSemanticAuthority(self.descriptor, state_io=self.state, capture_io=self.capture,
            authority_io=self.config, code_io=self.code, context_binding=self.context_binding)

    def reseal_contract(self):
        self.descriptor["pre_run"] = self.put(self.config, "pre-run.json", self.contract)

    def execute_synthetic_files(self, *, selected=True):
        """Writes synthetic wire/queue/delivery evidence; does not execute a job."""
        c, m = self.contract, self.material
        runner,length,helper=self.pipeline
        from ops.run_manager_flash_announcements import _source_article
        capture=json.loads(self.capture.read_bytes(c['capture']['artifact_ref']))
        article=_source_article(self.row,0,capture,c['capture'],self.capture,runner,self.membership)
        unit_map=runner.build_source_unit_map(self.row['body_text'],c['body_sha256'])
        article['fixed_fact_ledger']=runner.simple_fixed_facts.extract_fixed_facts(self.row['body_text'],unit_map,article['article_metadata'])
        batch=length.make_batch([article],'V4_FLASH_'+sha(self.article.encode())[:16])
        raw_reader = dict(disposition="SELECTED_EVENT" if selected else "NOT_SELECTED",
            selection_basis="OPERATING_EVENT" if selected else "NOT_SELECTED", direction="POSITIVE" if selected else "NEUTRAL",
            evidence_sufficiency="VERIFIED_EXISTING_FACTS", reason="SYNTHETIC ONLY",
            risk_notes=[], facts=[], changes=[], impact=[], confirmation_conditions=[], counter_evidence=[],
            source_sha256="", body_sha256="")
        if selected:
            for field in ("changes", "impact"):
                raw_reader[field] = [dict(claim='SYNTHETIC SOURCE CLAIM',
                    start_source_unit_id=self.article+'::'+unit_map['units'][0]['source_unit_id'],
                    end_source_unit_id=self.article+'::'+unit_map['units'][-1]['source_unit_id'])]
        wire=dict(action='complete',lookup_request=None,reader_output=raw_reader)
        raw=encoded(wire)
        result,_=runner.project_simple_workflow_output(wire,batch,self.reader_contract,
            expected_source_unit_map_sha256_by_article={self.article:unit_map['source_unit_map_sha256']},
            citation_protocol=runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL,preserve_model_changes=True)
        reader=result['results'][0]['reader_output']
        payload = {k: c[k] for k in ("article_id", "source_sha256", "body_sha256")}
        payload.update(article_body=self.row["body_text"], article_metadata=article['article_metadata'],
            fixed_fact_ledger=article['fixed_fact_ledger'],validated_article_batch=batch,source_unit_map_sha256=unit_map['source_unit_map_sha256'],
            date=self.row["publication_date"], market="HK", model_id=m["configuration_material"]["model_id"], prompt_sha256=m["prompt_sha256"],
            configuration_sha256=m["configuration_sha256"], rules="SYNTHETIC_READER_RULES", role="announcement_reader",
            stage="v4_manager_announcement_flash_incremental",
            messages=helper._messages_for_article(article,self.reader_contract,m['prompt'],runner.SIMPLE_WORKFLOW_RANGE_PROFILE),
            structured_output_schema=m["schema"], bounded_execution={"job_id": self.job, "report_sha256": self.report_sha})
        fields = ("date", "market", "article_id", "source_sha256", "body_sha256", "prompt_sha256", "model_id",
            "configuration_sha256", "rules", "role", "stage")
        identity = {k: payload[k] for k in fields}
        key = sha(encoded(identity))
        self.key = key
        qprefix = "announcement_flash/queue/jobs/" + key
        payload_ref = self.put(self.state, qprefix + "/input.json", payload)
        self.state.write_bytes(qprefix + "/attempt-0001.raw", raw)
        result_ref = self.put(self.state, qprefix + "/attempt-0001.validated.json", result)
        item = dict(identity=identity, idempotency_key=key, status="SUCCEEDED", attempt_count=1, max_attempts=1,
            input_path="jobs/"+key+"/input.json", payload_sha256=payload_ref["sha256"],
            raw_path="jobs/"+key+"/attempt-0001.raw", raw_sha256=sha(raw),
            validated_path="jobs/"+key+"/attempt-0001.validated.json", validated_sha256=result_ref["sha256"],
            attempts=[dict(number=1, status="SUCCEEDED", raw_sha256=sha(raw), validated_sha256=result_ref["sha256"])])
        self.put(self.state, "announcement_flash/queue/queue-state.json", {"jobs": {key: item}})
        trace = "announcement_flash/evidence/streams/" + key + "/attempt-0001/"
        request = dict(model=m["configuration_material"]["model_id"], messages=payload["messages"], structured_outputs={"json": m["schema"]},
            temperature=0.0, enable_thinking=False, max_tokens=m["configuration_material"]["max_completion_tokens"], stream=True,stream_options={'include_usage':True})
        request_ref = self.put(self.state, trace + "round-01.request-input.json", request)
        sse = ("data: " + json.dumps({"choices": [{"delta": {"content": raw.decode()}}]}) + "\n\ndata: [DONE]\n\n").encode()
        self.state.write_bytes(trace + "round-01.raw.sse", sse)
        stream = dict(idempotency_key=key, attempt=1, model_id=m["configuration_material"]["model_id"], status="RESPONSE_RECEIVED",
            runtime_settings_sha256=m["runtime_settings_sha256"], model_settings_sha256=m["model_settings_sha256"],
            runtime_settings_sha256_status="MATCH", model_settings_sha256_status="MATCH", request_rounds=1,
            final_text_sha256=sha(raw), tool_receipts=[], rounds=[dict(round=1,request_input_sha256=request_ref["sha256"], raw_sse_sha256=sha(sse))])
        stream_ref = self.put(self.state, trace + "stream-receipt.json", stream)
        article = dict(self.report["catalogue"][0], state="SUCCEEDED", queue_key=key,
            result_ref=item["validated_path"], result_sha256=item["validated_sha256"], source_coverage="COMPLETE_ARTICLE",
            **{k: reader[k] for k in ("disposition", "direction", "selection_basis", "reason")})
        self.delivered = dict(schema=delivery.SCHEMA, job_id=self.job, target_trade_date=self.day,
            preprocessing_report_sha256=self.report_sha, capture_product=c["capture"], articles=[article],
            stocks=[dict(symbol=c["symbol"], articles=[deepcopy(article)], reasons=[article["reason"]])] if selected else [],
            state="PARTIAL", counts={"SUCCEEDED": 1})
        binding = delivery.publish(self.state, self.job, self.delivered)
        self.artifacts = dict(queue_key=key, payload_sha256=payload_ref["sha256"], raw_sha256=sha(raw),
            validated_sha256=result_ref["sha256"], request_sha256=request_ref["sha256"],
            stream_sha256=stream_ref["sha256"], sse_sha256=sha(sse), delivery_sha256=binding["sha256"])

    def append_synthetic_review(self, *, verdict="PASS", source_faithfulness="PASS", **overrides):
        receipt = dict(schema=authority.RECEIPT_SCHEMA, pre_run_sha256=self.descriptor["pre_run"]["sha256"],
            dispatch_sha256=self.descriptor["dispatch"]["sha256"], context_binding=self.context_binding,
            job_id=self.job, target_date=self.day, market="HK_CONNECT", reviewer=self.contract["identities"]["reviewer"],
            reviewer_execution_id=self.contract["identities"]["reviewer_execution_id"],
            verdict=verdict, source_faithfulness=source_faithfulness, actual_calls=1,
            **{k: self.contract[k] for k in ("article_id", "source_sha256", "body_sha256", "symbol")},
            report_sha256=self.report_sha, capture_sha256=self.contract["capture"]["sha256"],
            input_sha256=self.contract["input"]["sha256"], **self.artifacts)
        receipt.update(overrides)
        raw = encoded(receipt)
        self.state.write_bytes(self.contract["outputs"]["receipt_ref"], raw, require_absent=True)
        registration = dict(schema=authority.REGISTRATION_SCHEMA, job_id=self.job,
            controller=self.contract["identities"]["controller"], pre_run_sha256=self.descriptor["pre_run"]["sha256"],
            receipt_ref=self.contract["outputs"]["receipt_ref"], receipt_sha256=sha(raw), context_binding=self.context_binding)
        self.state.write_bytes(self.contract["outputs"]["registration_ref"], encoded(registration), require_absent=True)


@pytest.fixture
def case(tmp_path):
    return SyntheticCase(tmp_path.resolve())


def test_preflight_then_append_only_review_and_zero_write_get(case, monkeypatch):
    case.verifier().preflight()
    case.execute_synthetic_files()
    pending = case.verifier()(case.job, case.report_sha)
    assert project_delivery_contribution(case.delivered, pending)["availability"] == "UNREVIEWED"
    case.append_synthetic_review()
    before = {str(p): p.read_bytes() for p in case.root.rglob("*") if p.is_file()}
    monkeypatch.setattr(SafeRoot, "write_bytes", lambda *a, **k: pytest.fail("GET wrote evidence"))
    accepted = case.verifier()(case.job, case.report_sha)
    assert project_delivery_contribution(case.delivered, accepted)["availability"] == "AVAILABLE"
    assert before == {str(p): p.read_bytes() for p in case.root.rglob("*") if p.is_file()}


def test_not_selected_review_preserves_zero_stocks(case):
    case.execute_synthetic_files(selected=False)
    case.append_synthetic_review()
    result = project_delivery_contribution(case.delivered, case.verifier()(case.job, case.report_sha))
    assert result["availability"] == "AVAILABLE" and result["stocks"] == []


@pytest.mark.parametrize("verdict,faithfulness", [("FAIL", "FAIL"), ("CANNOT_CONFIRM", "CANNOT_CONFIRM"), ("PASS", "FAIL")])
def test_rejected_semantics_never_promote_and_quarantine_exact_result(case, verdict, faithfulness):
    case.execute_synthetic_files()
    case.append_synthetic_review(verdict=verdict, source_faithfulness=faithfulness)
    snapshot = case.verifier()(case.job, case.report_sha)
    assert snapshot["quarantined_results"] == [{"queue_key": case.key, "result_sha256": case.artifacts["validated_sha256"]}]
    assert project_delivery_contribution(case.delivered, snapshot)["stocks"] == []


@pytest.mark.parametrize("field", ["job_id", "target_date", "market", "reviewer", "reviewer_execution_id", "context_binding",
    "pre_run_sha256", "dispatch_sha256", "article_id", "source_sha256", "body_sha256", "symbol", "report_sha256",
    "capture_sha256", "input_sha256", "queue_key", "payload_sha256", "raw_sha256", "validated_sha256", "request_sha256",
    "stream_sha256", "sse_sha256", "delivery_sha256", "actual_calls"])
def test_each_receipt_binding_tamper_rejected_even_with_valid_registration_hash(case, field):
    case.execute_synthetic_files()
    case.append_synthetic_review(**{field: "SYNTHETIC_TAMPER"})
    with pytest.raises(ValueError): case.verifier()(case.job, case.report_sha)


@pytest.mark.parametrize("field", ["source_sha256", "body_sha256", "symbol", "article_id", "market", "budget", "code_identity", "identities"])
def test_pre_run_tamper_cannot_self_authenticate(case, field):
    case.contract[field] = "SYNTHETIC_TAMPER"
    case.reseal_contract()
    with pytest.raises(ValueError): case.verifier().preflight()


def test_unregistered_receipt_remains_unreviewed_and_preflight_cannot_repeat(case):
    case.execute_synthetic_files()
    case.append_synthetic_review()
    (case.state.root / case.contract["outputs"]["registration_ref"]).unlink()
    assert case.verifier()(case.job, case.report_sha)["checkpoint_state"] != "SUCCEEDED"
    with pytest.raises(ValueError): case.verifier().preflight()


@pytest.mark.parametrize("artifact", ["input", "report", "source", "capture", "request_material"])
def test_pinned_artifact_bytes_drift_rejected(case, artifact):
    io = case.state if artifact in {"input", "report"} else case.config if artifact == "request_material" else case.capture
    io.write_bytes(case.contract[artifact]["artifact_ref"], b"{}")
    with pytest.raises(ValueError): case.verifier().preflight()


def test_actual_stream_or_attempt_drift_rejected(case):
    case.execute_synthetic_files()
    case.append_synthetic_review()
    ref = "announcement_flash/queue/queue-state.json"
    queue = json.loads(case.state.read_bytes(ref)); queue["jobs"][case.key]["attempt_count"] = 2
    case.put(case.state, ref, queue)
    with pytest.raises(ValueError): case.verifier()(case.job, case.report_sha)


def test_formal_explicit_owner_uses_same_verifier_without_recovery_helper(case, monkeypatch):
    from v4.manager_workbench.announcement_update import AnnouncementUpdate
    import ops.run_manager_flash_announcements as runner
    monkeypatch.setattr(runner, "_extension_plan", lambda *a, **k: pytest.fail("fake recovery used"))
    case.execute_synthetic_files(); case.append_synthetic_review()
    owner = AnnouncementUpdate(SimpleNamespace(), first_authority=case.verifier())
    assert owner.semantic_recovery_snapshot(case.job, case.report_sha) == case.verifier()(case.job, case.report_sha)


@pytest.mark.parametrize("artifact", ["queue", "payload", "raw", "result", "request", "stream", "sse", "delivery", "receipt", "registration"])
def test_post_response_actual_bytes_cannot_inherit_acceptance_after_drift(case, artifact):
    case.execute_synthetic_files(); case.append_synthetic_review()
    trace = f"announcement_flash/evidence/streams/{case.key}/attempt-0001/"
    delivery_ref = json.loads(case.state.read_bytes(case.prefix + "/deliveries/latest.json"))["artifact_ref"]
    refs = dict(queue="announcement_flash/queue/queue-state.json", payload=f"announcement_flash/queue/jobs/{case.key}/input.json",
        raw=f"announcement_flash/queue/jobs/{case.key}/attempt-0001.raw", result=f"announcement_flash/queue/jobs/{case.key}/attempt-0001.validated.json",
        request=trace + "round-01.request-input.json", stream=trace + "stream-receipt.json", sse=trace + "round-01.raw.sse",
        delivery=delivery_ref, receipt=case.contract["outputs"]["receipt_ref"], registration=case.contract["outputs"]["registration_ref"])
    case.state.write_bytes(refs[artifact], b"{}")
    with pytest.raises(ValueError): case.verifier()(case.job, case.report_sha)


def test_symlink_receipt_and_changed_registration_context_rejected(case):
    case.execute_synthetic_files(); case.append_synthetic_review()
    ref = case.contract["outputs"]["receipt_ref"]
    p = case.state.root / ref
    raw = p.read_bytes(); p.unlink()
    outside = case.root / "not-the-registered-receipt.json"; outside.write_bytes(raw)
    p.symlink_to(outside)
    with pytest.raises(ValueError): case.verifier()(case.job, case.report_sha)


def test_loaded_verifier_rejects_runtime_code_drift(case, monkeypatch):
    original = case.code.read_bytes
    monkeypatch.setattr(case.code, "read_bytes", lambda ref: b"changed" if ref.endswith("announcement_semantic_authority.py") else original(ref))
    with pytest.raises(ValueError, match="CODE_CHANGED"): case.verifier().preflight()


def test_existing_explicit_reader_for_other_job_preserves_default_route(case):
    from v4.manager_workbench.announcement_update import AnnouncementUpdate
    owner = AnnouncementUpdate(SimpleNamespace(), first_authority=case.verifier(),
        semantic_reader=lambda j, s: {"legacy_explicit": j})
    assert owner.semantic_recovery_snapshot("f" * 32, "f" * 64) == {"legacy_explicit": "f" * 32}


@pytest.mark.parametrize("field", ["actual_calls", "attempt_count", "max_attempts", "expected_requests"])
def test_boolean_is_not_an_integer_request_or_attempt_receipt(case, field):
    if field == "expected_requests":
        case.contract["budget"][field] = True
        case.reseal_contract()
        with pytest.raises(ValueError): case.verifier().preflight()
        return
    case.execute_synthetic_files()
    if field == "actual_calls":
        case.append_synthetic_review(actual_calls=True)
    else:
        case.append_synthetic_review()
        ref="announcement_flash/queue/queue-state.json"
        queue=json.loads(case.state.read_bytes(ref)); queue["jobs"][case.key][field]=True
        case.put(case.state,ref,queue)
    with pytest.raises(ValueError): case.verifier()(case.job, case.report_sha)


@pytest.mark.parametrize("variant", ["wrong_request_source", "extra_wire_tools", "unresolved_raw_citation",
    "changed_validated_fact", "boolean_stream_count", "boolean_attempt_number"])
def test_review_counterexamples_reject_coherently_rebound_actual_artifacts(case, variant):
    case.verifier().preflight(); case.execute_synthetic_files()
    state=case.state; qref="announcement_flash/queue/queue-state.json"
    queue=json.loads(state.read_bytes(qref)); item=queue["jobs"][case.key]
    trace=f"announcement_flash/evidence/streams/{case.key}/attempt-0001/"
    payload_ref="announcement_flash/queue/"+item["input_path"]
    payload=json.loads(state.read_bytes(payload_ref))
    request=json.loads(state.read_bytes(trace+"round-01.request-input.json"))
    stream=json.loads(state.read_bytes(trace+"stream-receipt.json"))
    if variant=="wrong_request_source":
        if len(payload["messages"]) == 1:
            payload["messages"].append({"role":"user","content":"OTHER_ISSUER. Frozen source units absent."})
        else:
            payload["messages"][-1]={"role":"user","content":"OTHER_ISSUER. Frozen source units absent."}
        request["messages"]=payload["messages"]
        raw=encoded(payload);state.write_bytes(payload_ref,raw)
        item["payload_sha256"]=sha(raw);case.artifacts["payload_sha256"]=sha(raw)
    if variant=="extra_wire_tools":
        request["tools"]=[{"type":"function","function":{"name":"unexpected_tool"}}]
        request["tool_choice"]="auto"
    if variant in {"wrong_request_source","extra_wire_tools"}:
        raw=encoded(request);state.write_bytes(trace+"round-01.request-input.json",raw)
        stream["rounds"][0]["request_input_sha256"]=sha(raw);case.artifacts["request_sha256"]=sha(raw)
    if variant=="unresolved_raw_citation":
        ref="announcement_flash/queue/"+item["raw_path"];wire=json.loads(state.read_bytes(ref))
        wire["reader_output"]["impact"][0].update(start_source_unit_id="OTHER_ARTICLE::NOT_A_UNIT",end_source_unit_id="OTHER_ARTICLE::NOT_A_UNIT")
        raw=encoded(wire);state.write_bytes(ref,raw)
        item["raw_sha256"]=sha(raw);item["attempts"][0]["raw_sha256"]=sha(raw);case.artifacts["raw_sha256"]=sha(raw)
        sse=("data: "+json.dumps({"choices":[{"delta":{"content":raw.decode()}}]})+"\n\ndata: [DONE]\n\n").encode()
        state.write_bytes(trace+"round-01.raw.sse",sse);stream["final_text_sha256"]=sha(raw)
        stream["rounds"][0]["raw_sse_sha256"]=sha(sse);case.artifacts["sse_sha256"]=sha(sse)
    if variant=="changed_validated_fact":
        ref="announcement_flash/queue/"+item["validated_path"];result=json.loads(state.read_bytes(ref))
        result["results"][0]["reader_output"]["facts"][0]["claim"]="INJECTED_FACT_NOT_PRODUCED_BY_APPROVED_PROJECTION"
        raw=encoded(result);state.write_bytes(ref,raw)
        item["validated_sha256"]=sha(raw);item["attempts"][0]["validated_sha256"]=sha(raw);case.artifacts["validated_sha256"]=sha(raw)
        case.delivered["articles"][0]["result_sha256"]=sha(raw)
        case.delivered["stocks"][0]["articles"][0]["result_sha256"]=sha(raw)
        case.artifacts["delivery_sha256"]=delivery.publish(state,case.job,case.delivered)["sha256"]
    if variant=="boolean_stream_count":stream["request_rounds"]=True;stream["attempt"]=True
    if variant=="boolean_attempt_number":item["attempts"][0]["number"]=True
    if variant!="changed_validated_fact":
        raw=encoded(stream);state.write_bytes(trace+"stream-receipt.json",raw);case.artifacts["stream_sha256"]=sha(raw)
    state.write_bytes(qref,encoded(queue));case.append_synthetic_review()
    with pytest.raises(ValueError):case.verifier()(case.job,case.report_sha)


@pytest.mark.parametrize('field', ['report_expected','report_required','manifest_expected','manifest_parts',
    'stream_attempt','stream_requests','stream_round','queue_number'])
def test_every_one_request_count_uses_strict_integer_types(case,field):
    if field.startswith('report_') or field.startswith('manifest_'):
        report=deepcopy(case.report)
        if field.startswith('report_'):
            report['counts']['expected_model_requests' if field=='report_expected' else 'model_required_articles']=True
        else:
            report['execution_manifest'][0]['expected_requests' if field=='manifest_expected' else 'part_count']=True if field=='manifest_expected' else False
        case.contract['report']=case.put(case.state,case.prefix+'/preprocessing-report.json',report)
        case.reseal_contract()
        with pytest.raises(ValueError):case.verifier().preflight()
        return
    case.execute_synthetic_files()
    if field=='queue_number':
        ref='announcement_flash/queue/queue-state.json';value=json.loads(case.state.read_bytes(ref))
        value['jobs'][case.key]['attempts'][0]['number']=True;case.put(case.state,ref,value)
    else:
        ref=f'announcement_flash/evidence/streams/{case.key}/attempt-0001/stream-receipt.json'
        value=json.loads(case.state.read_bytes(ref))
        if field=='stream_round':value['rounds'][0]['round']=True
        else:value['attempt' if field=='stream_attempt' else 'request_rounds']=True
        case.artifacts['stream_sha256']=case.put(case.state,ref,value)['sha256']
    case.append_synthetic_review()
    with pytest.raises(ValueError):case.verifier()(case.job,case.report_sha)


def test_original_frozen_85mb_capture_through_same_context_io_without_copy(case):
    from v4.manager_workbench.announcement_test import TestContext
    root=Path('/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_FULL_AUDIT_20261023/canary-input-preparation/materials/capture')
    pin='620cdbd5e7d32e739b5f2849589a1c47550b106ccba495053dcf0395636007b2'
    ref='products/'+pin+'.json';size=85203875
    # Use the actual context.io('capture') seam and the retained isolated file.
    # No capture, report, model call or 85MB test copy is created.
    context=TestContext(case.root/'unused-context.json','0'*64,case.root,{}, {'capture':root},
        {'capture':{ref:pin}}, {'capture':{ref:size}})
    value=case.verifier()._pinned(context.io('capture'),{'artifact_ref':ref,'sha256':pin},kind='capture',expected_bytes=size)
    assert len(value['rows'])==983
    row=value['rows'][550]
    assert sha(encoded(row))=='53c591ea7899c00bc19af7783795ca083e44f87a2f540e7ba4a6bb5049f44162'
    assert row['art_code']=='AN202610201830727898'
    assert row['body_text_sha256']=='73b05fa7066b21be9de2d4ee5708f54086e9f838609c2775715cce4921a02b5b'


@pytest.mark.parametrize('logical_root,declared,requested,expected_limit', [
    ('state',3,256*1024*1024,64*1024*1024),('config',3,256*1024*1024,64*1024*1024),
    ('capture',None,256*1024*1024,64*1024*1024),('capture',3,256*1024*1024,256*1024*1024)])
def test_capture_size_extension_cannot_escape_logical_kind(case,monkeypatch,logical_root,declared,requested,expected_limit):
    from v4.manager_workbench.announcement_test import FrozenIO
    raw=b'{}\n';pin=sha(raw);ref='products/'+pin+'.json';seen=[]
    def bounded(io,relative,*,max_bytes):seen.append(max_bytes);return raw
    monkeypatch.setattr(SafeRoot,'read_bytes',bounded)
    io=FrozenIO(case.root,{ref:pin},logical_root=logical_root,declared_sizes={} if declared is None else {ref:declared})
    assert io.read_bytes(ref,max_bytes=requested)==raw
    assert seen==[expected_limit]


@pytest.mark.parametrize('declared', [True,-1,256*1024*1024+1])
def test_capture_manifest_bad_size_rejected_before_read(case,monkeypatch,declared):
    from v4.manager_workbench.announcement_test import FrozenIO
    pin='a'*64;ref='products/'+pin+'.json'
    monkeypatch.setattr(SafeRoot,'read_bytes',lambda *a,**k:pytest.fail('invalid size reached read'))
    io=FrozenIO(case.root,{ref:pin},logical_root='capture',declared_sizes={ref:declared})
    with pytest.raises(ValueError):io.read_bytes(ref)


def test_capture_content_address_and_size_sha_symlink_guards(case):
    from v4.manager_workbench.announcement_test import FrozenIO
    raw=encoded({'synthetic':True});pin=sha(raw);ref='products/'+pin+'.json'
    case.capture.write_bytes(ref,raw)
    for expected_size in (len(raw)-1,len(raw)+1):
        io=FrozenIO(case.capture.root,{ref:pin},logical_root='capture',declared_sizes={ref:expected_size})
        with pytest.raises(ValueError):io.read_bytes(ref)
    io=FrozenIO(case.capture.root,{ref:'b'*64},logical_root='capture',declared_sizes={ref:len(raw)})
    with pytest.raises(ValueError):io.read_bytes(ref)
    outside=case.root/'outside.json';outside.write_bytes(raw)
    p=case.capture.root/ref;p.unlink();p.symlink_to(outside)
    with pytest.raises((OSError,ValueError)):
        FrozenIO(case.capture.root,{ref:pin},logical_root='capture',declared_sizes={ref:len(raw)}).read_bytes(ref)


def test_self_declared_replacement_projection_source_is_not_accepted(case):
    name='simple_fixed_facts.py';raw=case.config.read_bytes(case.contract['projection_sources'][name]['artifact_ref'])+b'\n# unauthorized bytes\n'
    case.config.write_bytes('pure/replacement.py',raw)
    case.contract['projection_sources'][name]={'artifact_ref':'pure/replacement.py','sha256':sha(raw)}
    case.reseal_contract()
    with pytest.raises(ValueError,match='PURE_SOURCE_IDENTITY_CHANGED'):case.verifier().preflight()


def test_genuine_full_original_envelope_preflight_without_manufactured_aliases(case):
    from ops.run_manager_flash_announcements import _classification_contract
    material=genuine_material()
    case.material=material
    case.contract['request_material']=case.put(case.config,'request-material.json',material)
    case.report['processing_contract']=_classification_contract(material,SimpleNamespace(MODEL_ID='qwen3_8_flash_next'))
    assert case.report['processing_contract']['max_completion_tokens'] is None
    case.contract['report']=case.put(case.state,case.prefix+'/preprocessing-report.json',case.report)
    case.report_sha=case.contract['report']['sha256'];case.reseal_contract()
    case.verifier().preflight()


ENVELOPE_DRIFTS = ("missing_config", "config_hash", "missing_nested_model", "missing_nested_budget",
    "nested_model", "nested_budget", "boolean_budget", "conflicting_model_alias", "conflicting_budget_alias",
    "boolean_budget_alias", "runtime_limits", "runtime_completion", "boolean_runtime_completion",
    "runtime_settings", "model_settings", "schema_hash", "schema_wrapper", "prompt_hash")


def drift_envelope(material, variant):
    """Adversarial assertions, never a valid producer envelope or authority."""
    config=material['configuration_material']
    if variant=='missing_config':material.pop('configuration_material');return
    if variant=='config_hash':material['configuration_sha256']='0'*64;return
    if variant=='missing_nested_model':material['model_id']=config.pop('model_id')
    elif variant=='missing_nested_budget':material['max_completion_tokens']=config.pop('max_completion_tokens')
    elif variant=='nested_model':config['model_id']='default_model'
    elif variant=='nested_budget':config['max_completion_tokens']=16384
    elif variant=='boolean_budget':config['max_completion_tokens']=True
    elif variant=='conflicting_model_alias':material['model_id']='default_model'
    elif variant=='conflicting_budget_alias':material['max_completion_tokens']=16384
    elif variant=='boolean_budget_alias':material['max_completion_tokens']=True
    elif variant=='runtime_limits':material['runtime_limits']['context_limit_tokens']=123
    elif variant=='runtime_completion':
        config['runtime_limits']['completion_max_tokens']=material['runtime_limits']['completion_max_tokens']=16384
    elif variant=='boolean_runtime_completion':
        config['runtime_limits']['completion_max_tokens']=material['runtime_limits']['completion_max_tokens']=True
    elif variant=='runtime_settings':config['runtime_settings_sha256']='0'*64
    elif variant=='model_settings':config['model_settings_sha256']='0'*64
    elif variant=='schema_hash':config['request_schema_sha256']='0'*64
    elif variant=='schema_wrapper':config['request_schema_wrapper_sha256']='0'*64
    elif variant=='prompt_hash':material['prompt_sha256']='0'*64
    else:raise AssertionError(variant)
    material['configuration_sha256']=sha(encoded(config))


@pytest.mark.parametrize('variant', ENVELOPE_DRIFTS)
def test_genuine_envelope_drift_cannot_self_assert_authority(case,variant):
    drift_envelope(case.material,variant)
    case.contract['request_material']=case.put(case.config,'request-material.json',case.material)
    # An inconsistent envelope remains invalid even when its linked bytes and
    # original-shaped report are jointly resealed in this synthetic attack.
    case.report['processing_contract']=original_producer._classification_contract(case.material,SimpleNamespace(MODEL_ID='qwen3_8_flash_next'))
    case.contract['report']=case.put(case.state,case.prefix+'/preprocessing-report.json',case.report)
    case.reseal_contract()
    with pytest.raises(ValueError):case.verifier().preflight()


@pytest.mark.parametrize('field', ['max_completion_tokens','citation_protocol','source_code_sha256',
    'runtime_limits','parser_sha256','workflow_profile','model_id','extra'])
def test_genuine_original_full_report_contract_is_exact(case,field):
    assert case.report['processing_contract']['max_completion_tokens'] is None
    case.report['processing_contract'][field]=32768 if field=='max_completion_tokens' else 'DRIFT'
    case.contract['report']=case.put(case.state,case.prefix+'/preprocessing-report.json',case.report)
    case.reseal_contract()
    with pytest.raises(ValueError,match='PROCESSING_CONTRACT_CHANGED'):case.verifier().preflight()


def test_genuine_original_envelope_model_and_effective_wire_budget_remain_bound(case):
    assert 'model_id' not in case.material and 'max_completion_tokens' not in case.material
    case.verifier().preflight();case.execute_synthetic_files();case.append_synthetic_review()
    assert project_delivery_contribution(case.delivered,case.verifier()(case.job,case.report_sha))['availability']=='AVAILABLE'
    request_ref=f'announcement_flash/evidence/streams/{case.key}/attempt-0001/round-01.request-input.json'
    request=json.loads(case.state.read_bytes(request_ref))
    assert request['model']==case.material['configuration_material']['model_id']=='qwen3_8_flash_next'
    assert type(request['max_tokens']) is int and request['max_tokens']==32768


@pytest.mark.parametrize('variant', ['base_prompt','sampling_hash','validator_source','missing_report_field'])
def test_original_material_identity_metadata_is_not_self_asserted(case,variant):
    if variant=='base_prompt':case.material['configuration_material']['base_prompt_sha256']='0'*64
    elif variant=='sampling_hash':case.material['sampling_policy_sha256']='0'*64
    elif variant=='validator_source':case.material['source_code_sha256']['v4/manager_workbench/engines/announcement.py']='0'*64
    case.material['configuration_sha256']=sha(encoded(case.material['configuration_material']))
    case.contract['request_material']=case.put(case.config,'request-material.json',case.material)
    case.report['processing_contract']=original_producer._classification_contract(case.material,SimpleNamespace(MODEL_ID='qwen3_8_flash_next'))
    if variant=='missing_report_field':case.report['processing_contract'].pop('max_completion_tokens')
    case.contract['report']=case.put(case.state,case.prefix+'/preprocessing-report.json',case.report);case.reseal_contract()
    with pytest.raises(ValueError):case.verifier().preflight()
