from pathlib import Path
import copy
import hashlib
import json
import pytest
from ops import run_pdf_research_full_once as f
from ops import run_pdf_research_batch as b


def fixture_source(tmp_path):
    pdf=tmp_path/'original.pdf';pdf.write_bytes(b'original PDF unchanged');did=f.sha(pdf.read_bytes())
    text='2026年收入预测100万元。\n原作者估计，仍有不确定性。'
    page={'page_number':1,'status':'NATIVE_TEXT','text':text,'text_sha256':f.sha(text.encode())}
    ip=tmp_path/'input.json';ip.write_text(json.dumps({'document_id':did,'pdf_sha256':did,'source':{'page_count':1},'pages':[page]}))
    rp=tmp_path/'prepared.json';rp.write_text(json.dumps({'status':'READY'}))
    row={'document_id':did,'pdf_sha256':did,'original_pdf_path':str(pdf),'page_input':f.ref(ip),'prepared_receipt':f.ref(rp),'pages':[{'page_number':1,'text_sha256':page['text_sha256'],'text_characters':len(text),'selected':True}],'restricted_uses':['date is source stated only']}
    return did,row,[{k:v for k,v in page.items() if k!='status'}]


def sample_card(pages):
    p=pages[0];e={'page_number':p['page_number'],'text_sha256':p['text_sha256'],'excerpt':'2026年收入预测100万元。'}
    claim={'claim':'作者预测2026年收入100万元','attribution':'原作者','period':'2026年','unit':'万元','evidence':[e]}
    return {'material_type':'研究材料','event_or_meeting_object':'UNKNOWN','speaker_and_source_attribution':['原作者'],'date':{'value':None,'basis':'UNKNOWN','evidence':[]},'facts':[],'forecasts':[claim],'inferences':[],
            'numeric_values':[{'value_as_source':'100','sign':'正','unit':'万元','period':'2026年','actual_or_forecast':'预测','comparison_operator':'EQ','measure_kind':'revenue','evidence':[e]}],'related_entities':[],'unknowns':['发布日期未核实'],'source_usage_limits':[]}


def test_full_lossless_unicode_all_pages_and_actual_envelopes():
    row={'document_id':'a'*64,'restricted_uses':['No date guess']}
    pages=[{'page_number':1,'text_sha256':'a'*64,'text':'中文1.2% 2027E\n'*2400},
           {'page_number':2,'text_sha256':'b'*64,'text':'English $116 / HK$115 forecast\n'*900}]
    groups=f.source_groups(row,pages)
    assert len(groups)>2
    for p in pages:
        units=[u for g in groups for u in g if u['page_number']==p['page_number']]
        assert ''.join(u['text'] for u in units)==p['text']
        assert all(u['text_sha256']==p['text_sha256'] for u in units)
    assert all(sum(len(u['text']) for u in g)<=8000 for g in groups)
    assert all(len(b._request_envelope(f.messages(row,g,synthesis=False)))<=32768 for g in groups)
    assert '不可信数据' in f.SYSTEM and 'UNKNOWN' in f.SYSTEM


def test_full_synthesis_oversize_fails_without_truncation():
    row={'document_id':'a'*64}
    unit={'card':{'unmodified':'中文'*20000}};original=copy.deepcopy(unit)
    with pytest.raises(b.BatchError,match='OVERSIZE'):f.pack(row,[unit],synthesis=True)
    assert unit==original


def test_full_source_exact_ready_and_foreign_rejected(tmp_path):
    did,row,pages=fixture_source(tmp_path)
    assert f.source(did,{did:row})[1]==pages
    with pytest.raises(b.BatchError,match='NOT_ADMITTED'):f.source('f'*64,{did:row})
    ip=Path(row['page_input']['path']);v=json.loads(ip.read_bytes());v['pages'][0]['text']='wrong';ip.write_text(json.dumps(v));row['page_input']=f.ref(ip)
    with pytest.raises(b.BatchError,match='PAGE_TEXT_OR_SHA'):f.source(did,{did:row})


def test_full_original_pdf_drift_is_rejected(tmp_path):
    did,row,_=fixture_source(tmp_path);Path(row['original_pdf_path']).write_bytes(b'changed')
    with pytest.raises(b.BatchError,match='PDF_SHA'):f.source(did,{did:row})


def test_full_missing_page_not_silently_selected(tmp_path):
    did,row,_=fixture_source(tmp_path);row['pages']=[]
    with pytest.raises(b.BatchError,match='PAGE_COUNT'):f.source(did,{did:row})


def test_full_card_forecast_period_unit_and_exact_citation(tmp_path):
    _,_,pages=fixture_source(tmp_path);card=sample_card(pages)
    assert f.validate_card(card,pages)==card
    for mutation in ['quote','sha','period','number','date']:
        bad=copy.deepcopy(card)
        if mutation=='quote':bad['forecasts'][0]['evidence'][0]['excerpt']='2026收入100万元'
        if mutation=='sha':bad['forecasts'][0]['evidence'][0]['text_sha256']='f'*64
        if mutation=='period':del bad['forecasts'][0]['period']
        if mutation=='number':bad['numeric_values'][0]['value_as_source']='1000'
        if mutation=='date':bad['date']['value']='2026-10-20'
        with pytest.raises(b.BatchError):f.validate_card(bad,pages)


def test_full_max_five_core_facts_not_unbounded_report(tmp_path):
    _,_,pages=fixture_source(tmp_path);card=sample_card(pages);card['facts']=card['forecasts']*6
    with pytest.raises(b.BatchError,match='LIMIT'):f.validate_card(card,pages)


def test_full_first_only_and_waits_for_independent_content(monkeypatch,tmp_path):
    monkeypatch.setattr(f,'first_card_gate',lambda c:False)
    context={'checkpoints':[{'batch_id':'LIGHT-001','document_ids':['a'*64,'b'*64]}]}
    assert f.pending_ids(context,[])==('FIRST_CARD_ONLY',['a'*64])
    receipt=tmp_path/'r.json';receipt.write_text('{}')
    events=[{'event':'full_terminal','document_id':'a'*64,'status':'GENERATED_MACHINE_VALIDATED_CONTENT_PENDING','receipt':f.ref(receipt)}]
    assert f.pending_ids(context,events)==('WAITING_FIRST_CARD_CONTENT_REVIEW',[])
    events[0]['status']='FAILED_NO_RETRY'
    with pytest.raises(b.BatchError,match='NO_RETRY'):f.pending_ids(context,events)


def test_full_duplicate_terminal_rejected(monkeypatch):
    monkeypatch.setattr(f,'first_card_gate',lambda c:True)
    e={'event':'full_terminal','document_id':'a'*64,'status':'x'}
    with pytest.raises(b.BatchError,match='DUPLICATE'):f.pending_ids({'checkpoints':[{'document_ids':['a'*64]}]},[e,e])


def test_full_missing_root_and_worker_are_zero_request(monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(f.packages,'load_context',lambda:{})
    monkeypatch.setattr(f,'selection',lambda:({},[]))
    monkeypatch.setattr(f,'ROOT',tmp_path/'missing.json')
    monkeypatch.setattr(b,'_perform_request',lambda *a,**k:calls.append(1))
    with pytest.raises(Exception):f.execute(1)
    with pytest.raises(Exception):f.worker('a'*64,tmp_path/'foreign-plan')
    assert calls==[] and not list(tmp_path.iterdir())


def test_full_bounds_and_mixed_cli_fail_before_model(monkeypatch):
    monkeypatch.setattr(f,'load_context',lambda:pytest.fail('must reject before load'))
    with pytest.raises(b.BatchError,match='BOUND'):f.execute(21)
    with pytest.raises(b.BatchError,match='BOUND'):f.execute(0)
    assert f.main(['--execute','--worker-id','a'*64,'--plan','/tmp/unused'])==2


def test_full_checkpoint_gate_exact_output_and_template(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'RESEARCH_PILOT_ROOT',tmp_path);monkeypatch.setattr(f,'ARTIFACTS',tmp_path/'outputs')
    did='a'*64;p=f.job_folder(did)/'card.json';p.parent.mkdir(parents=True);p.write_text('{}')
    pi={'path':'source','sha256':'b'*64};context={'documents':{did:{'page_input':pi}}};c={'batch_id':'LIGHT-001','document_ids':[did]}
    q=tmp_path/'independent-review/full-LIGHT-001-content-review.json';q.parent.mkdir()
    review={'reviewer':f.REVIEWER,'status':'FULL_LIGHT_CHECKPOINT_CONTENT_PASS','template_sha256':f.TEMPLATE_SHA,'documents':[{'document_id':did,'card':f.ref(p),'page_input':pi,'status':'LIGHT_CARD_CONTENT_PASS'}]};q.write_text(json.dumps(review));f.checkpoint_gate(c,context)
    review['documents'][0]['page_input']['sha256']='c'*64;q.write_text(json.dumps(review))
    with pytest.raises(b.BatchError,match='BINDING'):f.checkpoint_gate(c,{'documents':{did:{'page_input':{'path':'source','sha256':'b'*64}}}})


def test_independent_light_real69_lane_isolation_preserves_failed_medium_and_rejects_new_halt(tmp_path):
    from types import SimpleNamespace
    from ops import run_pdf_research_remaining_once as d
    raw=(b.RESEARCH_PILOT_ROOT/'model/v4-checkpoint/dispatch-prefix69.jsonl').read_bytes()
    assert f.sha(raw)==b.PILOT_V4_PREFIX_SHA256
    lines=raw.splitlines(keepends=True);events=[json.loads(x) for x in lines]
    folder=tmp_path/'same-journal-copy';folder.mkdir();path=folder/'dispatch.jsonl'
    # Source adoption is independent of acceptance of667; no successful status is inserted.
    path.write_bytes(raw+d.canonical_json({'event':'pilot_adoption','at_utc':'fixture'})+b'\n')
    context={'full_adoption_ref':{'path':'fixedROOT','sha256':'a'*64},'authorization_sha256':'b'*64,
             'full_adoption':{'independent_light_lane':{'failed_receipt':{'sha256':events[67]['receipt_sha256']},'independent_failure_review':{'path':'fixedFAIL','sha256':'c'*64}}}}
    with d.DurableJournal(folder) as journal:
        lane=f.prepare_light_lane_isolation(journal,context)
        assert journal.events[-1]['event']=='full_light_lane_isolation' and journal.events[67]['decision']=='HALT'
        assert journal.events[68]['event']=='halt' and not any(x.get('event')=='halt_resolution' for x in journal.events[69:])
        descriptors=[]
        for ri,hi in [(37,38),(53,54),(60,61)]:
            e=events[ri];descriptors.append({'reconciled_event_index':ri,'halt_event_index':hi,'reconciled_event_line_sha256':f.sha(lines[ri]),'continuation_id':e['continuation_id'],'document_id':e['document_id']})
        d._halt_if_required(journal,{},halt_resume_descriptor=descriptors[0],additional_halt_resume_descriptor=descriptors[1],synthesis_halt_resume_descriptor=descriptors[2],sectioned_halt_resume_descriptor=lane)
        f.prepare_light_lane_isolation(journal,context);assert len(journal.events)==71
        journal.append({'event':'halt','document_id':f.LIGHT_FIRST_ID,'reason':'newactualfailure'})
        with pytest.raises(d.DispatcherError,match='PREVIOUSLY_HALTED'):
            d._halt_if_required(journal,{},halt_resume_descriptor=descriptors[0],additional_halt_resume_descriptor=descriptors[1],synthesis_halt_resume_descriptor=descriptors[2],sectioned_halt_resume_descriptor=lane)
        journal.events[70]['allowed_selection_sha256']='d'*64
        with pytest.raises(b.BatchError,match='ISOLATION_MISMATCH'):f.prepare_light_lane_isolation(journal,context)
    assert (folder/'dispatch.jsonl').read_bytes().startswith(raw)


def test_independent_light_lane_does_not_require_pilot_or_packages(monkeypatch):
    # Only this lane contract is isolated here; actual source/manifest contracts
    # retain their already passed tests and frozen identities.
    failure={'status':'FAILED_DOCUMENT_ISOLATED','document_id':b.PILOT_TOOL_BUDGET_DOCUMENT_ID}
    old_read=f.read
    monkeypatch.setattr(f,'read',lambda r,**k:{'status':'AUTHORIZED_INDEPENDENT_LIGHT_CANARY_THEN_BATCHES'} if r==f.LIGHT_DECISION else failure)
    monkeypatch.setattr(f,'independent',lambda *a,**k:{'status':'ACTUAL_FAILURE_CHECKPOINT_CONFIRMED_NO_RETRY'})
    monkeypatch.setattr(f,'selection',lambda:({f.LIGHT_FIRST_ID:{}},[{'document_ids':[f.LIGHT_FIRST_ID]}]))
    lane={'controller_decision':f.LIGHT_DECISION,'selection_sha256':f.PINS['planning/light716.json'],'checkpoint_event_count':69,'checkpoint_sha256':b.PILOT_V4_PREFIX_SHA256,'excluded_document_id':b.PILOT_TOOL_BUDGET_DOCUMENT_ID,'first_document_id':f.LIGHT_FIRST_ID,'concurrency':1,
          'failed_receipt':{'sha256':'1110d1c4da5a9529809bfdf6ac02d3b7298bc92d8c5c589adc8a4a02529a624c'},'independent_failure_review':{'sha256':'cf3894fca4ac11892f1810899e1a035013fd5aac6fc533672f5cd8b121b6a50d'}}
    context={'analysis_admission':{'pilot':{'phase':'first3','value':{'sources':{'acceptedbase':'sha'}}}}}
    adoption={'independent_light_lane':lane,'base_sources':{'acceptedbase':'sha'}}
    f.independent_light_gates(adoption,context)
    assert 'pilot_acceptance' not in adoption and 'package_acceptance' not in adoption
    with pytest.raises(b.BatchError,match='ADMISSION'):f.independent_light_gates({**adoption,'independent_light_lane':{**lane,'excluded_document_id':'foreign'}},context)


def test_source_invalid_exact_pair_receipt_inputs_and_retained_root(tmp_path,monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket,'connect',lambda *a:pytest.fail('offline source-invalid test'))
    docs,_=f.selection();backup=b.RESEARCH_PILOT_ROOT/'model/full-source-invalid-before'
    previous=f.ref(backup/'previous-full-root.json');oldproof=f.ref(backup/'previous-code-review.json')
    adoption=json.loads(Path(previous['path']).read_text())
    monkeypatch.setattr(b,'RESEARCH_PILOT_ROOT',tmp_path)
    rp=tmp_path/'independent-review/full-source-invalid-review.json';rp.parent.mkdir()
    rows=[{'document_id':did,'status':'SOURCE_INVALID_NO_RESEARCH_BODY','page_input':docs[did]['page_input']} for did in f.SOURCE_INVALID_INPUTS]
    rp.write_text(json.dumps({'reviewer':f.REVIEWER,'status':'SOURCE_INVALID_PAIR_CONFIRMED','documents':rows}))
    data={'independent_review':f.ref(rp),'documents':[{'document_id':did,'page_input':docs[did]['page_input']} for did in f.SOURCE_INVALID_INPUTS],
          'positive_first_document_id':f.POSITIVE_FIRST_ID,'previous_adoption_backup':previous,'previous_source_review_backup':oldproof}
    adoption['source_invalid_admission']=data
    actual,prior=f.source_invalid_admission(adoption,docs)
    assert list(actual)==list(f.SOURCE_INVALID_INPUTS) and prior['adoption']['sha256']==f.PRE_INVALID_ROOT_SHA
    for changed in ['foreign','input','proof','positive','previous']:
        invalid=copy.deepcopy(adoption)
        if changed=='foreign':invalid['source_invalid_admission']['documents'][0]['document_id']='f'*64
        elif changed=='input':invalid['source_invalid_admission']['documents'][0]['page_input']['sha256']='f'*64
        elif changed=='proof':invalid['source_invalid_admission']['independent_review']['sha256']='f'*64
        elif changed=='positive':invalid['source_invalid_admission']['positive_first_document_id']=f.LIGHT_FIRST_ID
        else:invalid['source_invalid_admission']['previous_adoption_backup']['sha256']='f'*64
        with pytest.raises(b.BatchError):f.source_invalid_admission(invalid,docs)


def test_source_invalid_positive_canary_only_then_checkpoint_mixed_rows(tmp_path,monkeypatch):
    ids=[*f.SOURCE_INVALID_INPUTS,f.POSITIVE_FIRST_ID,'f'*64]
    context={'checkpoints':[{'batch_id':'LIGHT-001','document_ids':ids}],
             'source_invalid_rows':{did:{} for did in f.SOURCE_INVALID_INPUTS},'source_invalid_review':{'path':'source-review','sha256':'a'*64},
             'documents':{did:{'page_input':{'path':did,'sha256':'b'*64}} for did in ids}}
    monkeypatch.setattr(f,'first_card_gate',lambda _:False)
    original={'event':'full_terminal','document_id':f.LIGHT_FIRST_ID,'status':'GENERATED_MACHINE_VALIDATED_CONTENT_PENDING'}
    assert f.pending_ids(context,[original])==('FIRST_CARD_ONLY',[f.POSITIVE_FIRST_ID])
    rp=tmp_path/'receipt.json';rp.write_text('{}')
    positive={'event':'full_terminal','document_id':f.POSITIVE_FIRST_ID,'status':'GENERATED_MACHINE_VALIDATED_CONTENT_PENDING','receipt':f.ref(rp)}
    assert f.pending_ids(context,[original,positive])==('WAITING_FIRST_CARD_CONTENT_REVIEW',[])
    rp.write_text(json.dumps({'page_input':context['documents'][f.POSITIVE_FIRST_ID]['page_input'],'template_sha256':f.TEMPLATE_SHA,'card':f.ref(rp)}))
    monkeypatch.setattr(f,'read',lambda ref,**_: {'page_input':context['documents'][f.POSITIVE_FIRST_ID]['page_input'],'template_sha256':f.TEMPLATE_SHA,'card':{}})
    monkeypatch.setattr(f,'first_card_gate',lambda _:True)
    assert f.pending_ids(context,[original,positive])==('LIGHT-001',['f'*64])
    # Checkpoint receipt accounts for invalid sources without pretending they have cards.
    monkeypatch.setattr(b,'RESEARCH_PILOT_ROOT',tmp_path);monkeypatch.setattr(f,'ARTIFACTS',tmp_path/'output')
    cp={'batch_id':'LIGHT-001','document_ids':ids[:3]};card=f.job_folder(f.POSITIVE_FIRST_ID)/'card.json';card.parent.mkdir(parents=True);card.write_text('{}')
    expected=[{'document_id':did,'page_input':context['documents'][did]['page_input'],'status':'SOURCE_INVALID_NO_RESEARCH_BODY','source_invalid_review':context['source_invalid_review']} for did in ids[:2]]
    expected.append({'document_id':f.POSITIVE_FIRST_ID,'card':f.ref(card),'page_input':context['documents'][f.POSITIVE_FIRST_ID]['page_input'],'status':'LIGHT_CARD_CONTENT_PASS'})
    monkeypatch.setattr(f,'independent',lambda *a,**k:{'documents':expected,'template_sha256':f.TEMPLATE_SHA})
    review=tmp_path/'independent-review/full-LIGHT-001-content-review.json';review.parent.mkdir();review.write_text('{}')
    f.checkpoint_gate(cp,context)
    expected[0]['status']='LIGHT_CARD_CONTENT_PASS'
    with pytest.raises(b.BatchError,match='CHECKPOINT_CONTENT_BINDING'):f.checkpoint_gate(cp,context)
    monkeypatch.setattr(f,'checkpoint_gate',lambda *a:None)
    done={**context,'checkpoints':[cp]}
    assert f.pending_ids(done,[original,positive])==('ALL716_ACCOUNTED_WITH_SOURCE_INVALID_AND_CHECKPOINTS_ACCEPTED',[])


def test_source_invalid_current_adoption_preserves_exact_previous_event_and_worker_gate():
    from types import SimpleNamespace
    prior={'adoption':{'path':'sameROOT','sha256':f.PRE_INVALID_ROOT_SHA},'sources':{'old':'hash'}}
    context={'full_adoption_ref':{'path':'sameROOT','sha256':'c'*64},'sources':{'current':'hash'},'previous_full_adoption':prior}
    old={'event':'full_adoption',**prior,'template_sha256':f.TEMPLATE_SHA};events=[old]
    journal=SimpleNamespace(events=events,append=events.append)
    with pytest.raises(b.BatchError,match='PRECLAIM'):f.verify_full_adoption(journal,context,append=False)
    f.verify_full_adoption(journal,context,append=True);assert len(events)==2 and events[0]==old
    f.verify_full_adoption(journal,context,append=False);assert len(events)==2
    for bad in [events+[events[-1]],list(reversed(events)),[{**old,'sources':{'fake':'hash'}},events[-1]],[]]:
        with pytest.raises(b.BatchError,match='ADOPTION_MISMATCH'):f.verify_full_adoption(SimpleNamespace(events=bad),context,append=True)


def test_source_invalid_disposition_retains_all_identities_and_never_counts_completion(tmp_path,monkeypatch):
    ids=list(f.SOURCE_INVALID_INPUTS);pdf=tmp_path/'source.pdf';pdf.write_bytes(b'preserved')
    rows=[{'document_id':did,'route':'LIGHT_EXTRACTION' if i<2 else 'SAVE','original_pdf_path':str(pdf),'pdf_sha256':did} for i,did in enumerate(ids+[f'{i:064x}' for i in range(2207)])]
    monkeypatch.setattr(f,'pinned',lambda _: {'documents':rows})
    monkeypatch.setattr(f.packages,'selected_package',lambda _:({},[],''))
    monkeypatch.setattr(f,'ARTIFACTS',tmp_path/'accounting')
    context={'full_adoption':{},'full_adoption_ref':{'path':'sameROOT','sha256':'a'*64},'source_invalid_rows':{did:{} for did in ids},'source_invalid_review':{'path':'review','sha256':'b'*64},'analysis_admission':{'pilot':{'source_hold_ids':[]}}}
    negative={'event':'full_terminal','document_id':ids[0],'status':'GENERATED_MACHINE_VALIDATED_CONTENT_PENDING','receipt':{'path':'retained1POST','sha256':'c'*64}}
    output=f.write_disposition(context,[negative]);value=json.loads(Path(output['path']).read_text())
    assert value['identity_count']==2209 and len(value['documents'])==2209 and value['counts']['SOURCE_INVALID_NO_RESEARCH_BODY']==2
    first,second=value['documents'][:2]
    assert all(x['model_complete'] is False and x['route']=='LIGHT_EXTRACTION' for x in (first,second))
    assert first['actual_model_POSTs']==1 and first['prior_negative_terminal']==negative and second['actual_model_POSTs']==0
    assert pdf.read_bytes()==b'preserved'


def test_source_invalid_proofs_have_distinct_paths_preserving_base_authority():
    old_code,old_runtime=f.release_review_paths({})
    new_code,new_runtime=f.release_review_paths({'source_invalid_admission':{'exact_pair':'present'}})
    assert old_code.name=='full-adapter-code-review.json' and old_runtime.name=='full-adapter-runtime-review.json'
    assert new_code.name=='full-source-invalid-code-review.json' and new_runtime.name=='full-source-invalid-runtime-review.json'
    assert old_code!=new_code and old_runtime!=new_runtime


# V2 cases exercise only the changed contract and direct recovery/isolation risks.
def _v2_81e_fixture():
    root=b.RESEARCH_PILOT_ROOT/'model/full-routed-execution/positive-first-light-execution'
    raw=(root/'preserved-raw-model-inner-card.json').read_text()
    ip=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/prepared/full-cohort-sol-20261019-r1/documents')/f.POSITIVE_FIRST_ID/'page-input.json'
    assert f.sha(ip.read_bytes())=='9653c17fb83c287313b7a77e6f9e7b983ecf3bfe86784032debae655755db95a'
    pages=[{k:p[k] for k in ('page_number','text_sha256','text')} for p in json.loads(ip.read_text())['pages']]
    card,audit=f.canonicalize_citations(raw,pages);original=copy.deepcopy(card)
    card['facts']=[original['facts'][0],original['facts'][2],original['facts'][3],original['inferences'][0],original['inferences'][2]]
    card['forecasts']=[original['inferences'][1]];card['inferences']=[]
    for item in card['numeric_values']:item.update(comparison_operator='EQ',measure_kind='date')
    card['numeric_values'][0].update(value_as_source='不少于10',comparison_operator='GE',measure_kind='annual_capacity',actual_or_forecast='REPORTED_CAPACITY_NOT_OUTPUT')
    card['numeric_values'][1]['measure_kind']='price_return'
    page=pages[0];quote=lambda text:{'page_number':1,'text_sha256':page['text_sha256'],'excerpt':text}
    card['speaker_and_source_attribution']=[{'entity':'风口研报','role':'publisher','evidence':[quote('风口研报')]},{'entity':'润邦股份','role':'respondent','evidence':[quote('润邦股份于9月28日接待南方基金独家调研')]},{'entity':'南方基金','role':'visitor','evidence':[quote('润邦股份于9月28日接待南方基金独家调研')]}]
    card['unknowns'].append('实际发言人及作者身份未核实')
    card['source_usage_limits']=[{'limitation':e['excerpt'],'evidence':[e]} for e in f.source_limit_quotes(pages)]
    return raw,pages,card,audit


def test_v2_real_failure_only_three_unique_whitespace_spans_no_lexical_repair():
    raw,pages,card,audit=_v2_81e_fixture()
    assert len(audit)==3 and [x['source_start_character'] for x in audit]==[219,327,428]
    assert all(x['raw_inner_sha256']==f.sha(raw.encode()) and x['source_excerpt'] in pages[0]['text'] and f._compact(x['original_excerpt'])==f._compact(x['source_excerpt']) for x in audit)
    assert 'REPORTED_CAPACITY_NOT_OUTPUT' in json.dumps(card)
    page={'page_number':1,'text':'甲\n乙；甲\n乙；10艘','text_sha256':'a'*64}
    for quote in ['甲乙','11艘','甲丙']:
        inner=json.dumps({'evidence':[{'page_number':1,'text_sha256':'a'*64,'excerpt':quote}]},ensure_ascii=False)
        with pytest.raises(b.BatchError,match='SPAN_NOT_UNIQUE'):f.canonicalize_citations(inner,[page])
    assert page['text']=='甲\n乙；甲\n乙；10艘'


@pytest.mark.parametrize('mutation,code',[('inference','INFERENCE_FORBIDDEN'),('future','FORECAST_CLASSIFIED'),('bound','BOUND_LOST'),('capacity','CAPACITY_MISCLASSIFIED'),('role','ROLE_INVALID'),('speaker','NOT_IDENTIFIED'),('restriction','USE_LIMIT_OMITTED')])
def test_v2_four_confirmed_semantic_failures_rejected(mutation,code):
    _,pages,valid,_=_v2_81e_fixture();assert f.validate_card(valid,pages)==valid
    bad=copy.deepcopy(valid)
    if mutation=='inference':bad['inferences']=[bad['facts'].pop()]
    elif mutation=='future':bad['facts'][0]=bad['forecasts'].pop()
    elif mutation=='bound':bad['numeric_values'][0]['comparison_operator']='EQ'
    elif mutation=='capacity':bad['numeric_values'][0].update(measure_kind='actual_output',actual_or_forecast='actual')
    elif mutation=='role':bad['speaker_and_source_attribution']=['风口研报','润邦股份','南方基金']
    elif mutation=='speaker':bad['speaker_and_source_attribution'][2]['role']='speaker'
    else:bad['source_usage_limits']=[]
    with pytest.raises(b.BatchError,match=code):f.validate_card(bad,pages)


def test_v2_source_use_limits_survive_source_and_synthesis():
    _,pages,card,_=_v2_81e_fixture();limits=f.source_limit_quotes(pages)
    assert limits and '不构成投研观点' in limits[0]['excerpt'] and '公告和分析师公开报告为准' in limits[0]['excerpt']
    units=[{**pages[0],'offset':0}]
    assert f.material_limits(units,synthesis=False)==limits
    assert f.material_limits([{'card':card}],synthesis=True)==[e for item in card['source_usage_limits'] for e in item['evidence']]
    missing=copy.deepcopy(card);missing['source_usage_limits']=[]
    with pytest.raises(b.BatchError,match='USE_LIMIT_OMITTED'):f.validate_card(missing,pages,required_limits=limits)


def _v2_real80_context():
    from ops import run_pdf_research_remaining_once as d
    docs,checkpoints=f.selection();base=f.packages.load_context();backup=b.RESEARCH_PILOT_ROOT/'model/light-v2-before'
    adoption=json.loads((backup/'full-root-ef32.json').read_text())
    data={'decision':f.LIGHT_V2_DECISION,'document_id':f.POSITIVE_FIRST_ID,'page_input':docs[f.POSITIVE_FIRST_ID]['page_input'],'generation':1,'max_new_POSTs':1,
          'journal_prefix80_sha256':f.V2_PREFIX80_SHA,'failed_terminal_index':78,'halt_index':79,'template_sha256':f.TEMPLATE_SHA,
          'failure_review':f.ref(b.RESEARCH_PILOT_ROOT/'independent-review/full-positive-first-failure-review.json'),
          'previous_adoption_backup':f.ref(backup/'full-root-ef32.json'),'previous_source_review_backup':f.ref(backup/'code-504.json'),'template_budget':f.ref(b.RESEARCH_PILOT_ROOT/'model/light-v2-template-budget.json')}
    adoption.update(template_sha256=f.TEMPLATE_SHA,light_v2_recovery=data)
    invalid,previous=f.source_invalid_admission(adoption,docs);recovery,previous_v2=f.load_v2_recovery(adoption,docs)
    return {**base,'documents':docs,'checkpoints':checkpoints,'full_adoption':adoption,'full_adoption_ref':{'path':str(f.ROOT),'sha256':'e'*64},'sources':{'reviewed_candidate':'e'*64},'source_invalid_rows':invalid,'source_invalid_review':adoption['source_invalid_admission']['independent_review'],'previous_full_adoption':previous,'light_lane_anchor':previous['adoption'],'light_v2_recovery':recovery,'v2_previous_adoption':previous_v2}


def test_v2_actual80_typed_recovery_no_journal_write_unknown_halt_and_quota_refused(monkeypatch):
    from datetime import datetime,timezone
    from ops import run_pdf_research_remaining_once as d
    ctx=_v2_real80_context();jp=d.EVIDENCE_ROOT/'dispatch.jsonl';actual=jp.read_bytes();raw=(b.RESEARCH_PILOT_ROOT/'model/light-v2-before/dispatch-prefix80.jsonl').read_bytes()
    assert f.sha(raw)==f.V2_PREFIX80_SHA
    class Memory:
        path=jp;root=d.EVIDENCE_ROOT
        def __init__(self):self.raw=raw;self.events=[json.loads(x) for x in raw.splitlines()];self.emitted=[]
        def append(self,event):
            row={'at_utc':datetime.now(timezone.utc).isoformat(),**event};self.events.append(row);self.emitted.append(row);self.raw+=d.canonical_json(row)+b'\n'
    journal=Memory();original=d._read_regular;monkeypatch.setattr(d,'_read_regular',lambda path,code:journal.raw if Path(path)==jp else original(path,code))
    with pytest.raises(b.BatchError,match='TRANSITION_REQUIRED'):f.verify_history(journal,ctx)
    f.verify_history(journal,ctx,append=True);f.verify_full_adoption(journal,ctx,append=True)
    assert [x['event'] for x in journal.emitted]==['halt_resolution','full_adoption']
    f.verify_history(journal,ctx);f.verify_full_adoption(journal,ctx,append=False);assert len(journal.emitted)==2
    before_raw=journal.raw;before_events=copy.deepcopy(journal.events)
    for variant in ['unknown','duplicate','quota']:
        journal.raw=before_raw;journal.events=copy.deepcopy(before_events)
        if variant=='unknown':journal.append({'event':'halt','document_id':'f'*64})
        elif variant=='duplicate':journal.append({k:v for k,v in journal.events[80].items() if k!='at_utc'})
        else:
            for _ in range(2):journal.append({'event':'full_intent','document_id':f.POSITIVE_FIRST_ID,'generation':1})
        with pytest.raises((b.BatchError,d.DispatcherError),match='FAILURE|DUPLICATE|QUOTA'):f.verify_history(journal,ctx)
    assert jp.read_bytes()==actual


def test_v2_failure_isolation_streak_and_repair_terminal_generation():
    raw=(b.RESEARCH_PILOT_ROOT/'model/light-v2-before/dispatch-prefix80.jsonl').read_bytes();events=[json.loads(x) for x in raw.splitlines()];context={'light_v2_recovery':{'generation':1}}
    good={'event':'full_terminal','document_id':f.POSITIVE_FIRST_ID,'status':'GENERATED_MACHINE_VALIDATED_CONTENT_PENDING','generation':1}
    assert f.terminal_map(context,events+[good])[f.POSITIVE_FIRST_ID]==good
    for bad in [events+[good,good],events+[{**good,'generation':2}]]:
        with pytest.raises(b.BatchError,match='DUPLICATE|GENERATION'):f.terminal_map(context,bad)
    failures=[{'event':'full_terminal','document_id':str(i)*64,'status':'FAILED_DOCUMENT_ISOLATED','code':'FULL_CITATION_NOT_EXACT_SOURCE'} for i in range(3)]
    assert f.protocol_failure_streak(events+failures)
    assert not f.protocol_failure_streak(events+failures[:2])
    assert not f.protocol_failure_streak(events+failures[:2]+[good])
    assert not f.protocol_failure_streak(events+[failures[0]]*3)


@pytest.mark.parametrize('worker_code,should_continue',[('FULL_CITATION_NOT_EXACT_SOURCE',True),('MODEL_IDENTITY_DRIFT',False)])
def test_v2_actual_loop_isolates_document_failures_continues_and_system_fault_stops(tmp_path,monkeypatch,worker_code,should_continue):
    from ops import run_pdf_research_remaining_once as d
    import socket
    monkeypatch.setattr(socket.socket,'connect',lambda *a:pytest.fail('no model or network in loop fixture'))
    ids=['a'*64,'b'*64,'c'*64];sources={}
    for did in ids:
        p=tmp_path/(did+'.json');p.write_text('{}');sources[did]={'document_id':did,'page_input':f.ref(p)}
    context={'documents':sources,'checkpoints':[{'batch_id':'LIGHT-001','document_ids':ids}],'full_adoption':{},'full_adoption_ref':{'path':'fixedROOT','sha256':'d'*64}}
    monkeypatch.setattr(f,'load_context',lambda **_:context);monkeypatch.setattr(f,'verify_history',lambda *a,**k:None);monkeypatch.setattr(f,'verify_full_adoption',lambda *a,**k:None)
    monkeypatch.setattr(f,'first_card_gate',lambda _:True);monkeypatch.setattr(f,'write_disposition',lambda *a:{'fixture':'accounting-not-semanticPASS'})
    monkeypatch.setattr(f,'ARTIFACTS',tmp_path/'outputs');monkeypatch.setattr(d,'EVIDENCE_ROOT',tmp_path/'journal')
    d.EVIDENCE_ROOT.mkdir();(d.EVIDENCE_ROOT/'dispatch.jsonl').write_text('{"event":"binding"}\n')
    monkeypatch.setattr(b,'_priority_snapshot',lambda:{'status':'ALLOW'});monkeypatch.setattr(d,'sample_resource_metrics',lambda:{'swap_used_bytes':0});monkeypatch.setattr(d,'_resource_stop_reason',lambda *a:None);monkeypatch.setattr(d,'_owned_child_create_time',lambda _:1)
    def source(did,docs):
        if did==ids[0]:raise b.BatchError('FULL_PAGE_COUNT_MISMATCH')
        return docs[did],[]
    monkeypatch.setattr(f,'source',source);launched=[]
    class Child:
        def __init__(self,argv,**kwargs):
            path=Path(argv[-1]);plan=json.loads(path.read_bytes());did=plan['document_id'];launched.append(did);self.pid=1000+len(launched)
            self.rc=2 if did==ids[1] else 0
            if self.rc:kwargs['stderr'].write((json.dumps({'status':'FAILED_CLOSED','code':worker_code})+'\n').encode());kwargs['stderr'].flush()
            else:
                cp=path.parent/'card.json';cp.write_text('{}');rp=path.parent/'receipt.json';rp.write_text(json.dumps({'status':'GENERATED_MACHINE_VALIDATED_CONTENT_PENDING','plan':f.ref(path),'card':f.ref(cp),'page_input':sources[did]['page_input'],'template_sha256':f.TEMPLATE_SHA}))
        def poll(self):return self.rc
        def wait(self):return self.rc
    monkeypatch.setattr(f.subprocess,'Popen',Child)
    result=f.execute(3);events=[json.loads(x) for x in (d.EVIDENCE_ROOT/'dispatch.jsonl').read_bytes().splitlines()]
    terms=[e for e in events if e['event']=='full_terminal']
    assert terms[0]['status']=='SOURCE_INVALID_NO_MODEL' and f.read(terms[0]['failure'])['new_model_POSTs']==0
    if should_continue:
        assert launched==ids[1:] and [e['status'] for e in terms]==['SOURCE_INVALID_NO_MODEL','FAILED_DOCUMENT_ISOLATED','GENERATED_MACHINE_VALIDATED_CONTENT_PENDING']
        assert not any(e['event']=='halt' for e in events)
        # One independent checkpoint may accept mixed truthful dispositions.
        monkeypatch.setattr(b,'RESEARCH_PILOT_ROOT',tmp_path)
        q=tmp_path/'independent-review/full-LIGHT-001-content-review.json';q.parent.mkdir()
        rows=[{'document_id':e['document_id'],'page_input':sources[e['document_id']]['page_input'],'status':e['status'],'failure':e['failure']} for e in terms[:2]]
        rows.append({'document_id':ids[2],'page_input':sources[ids[2]]['page_input'],'status':'LIGHT_CARD_CONTENT_PASS','card':f.ref(f.output_folder(ids[2],context)/'card.json')})
        q.write_text(json.dumps({'status':'FULL_LIGHT_CHECKPOINT_DISPOSITION_ACCEPTED','reviewer':f.REVIEWER,'template_sha256':f.TEMPLATE_SHA,'documents':rows}))
        context['light_v2_recovery']={'fixture_only':'no recovery POST'}
        f.checkpoint_gate(context['checkpoints'][0],context,events)
        rows[-1].update(status='CONTENT_FAILED_DOCUMENT_ISOLATED',findings=[{'id':'fixture-semantic-failure'}]);q.write_text(json.dumps({'status':'FULL_LIGHT_CHECKPOINT_DISPOSITION_ACCEPTED','reviewer':f.REVIEWER,'template_sha256':f.TEMPLATE_SHA,'documents':rows}))
        f.checkpoint_gate(context['checkpoints'][0],context,events)
    else:
        assert launched==[ids[1]] and terms[-1]['status']=='FAILED_NO_RETRY' and events[-1]['event']=='halt' and ids[2] not in launched
    assert all(x.get('status')!='LIGHT_CARD_CONTENT_PASS' for x in terms)  # Execution never fabricates independent acceptance.


def test_v2_company_name_future_is_not_automatically_a_forecast():
    text='未来电器2025年收入为100万元。';page={'page_number':1,'text':text,'text_sha256':f.sha(text.encode())};e={'page_number':1,'text_sha256':page['text_sha256'],'excerpt':text}
    card={'material_type':'来源摘要','event_or_meeting_object':'UNKNOWN','speaker_and_source_attribution':[],'date':{'value':None,'basis':'UNKNOWN','evidence':[]},'facts':[{'claim':text,'attribution':'原文','period':'2025年','unit':'万元','evidence':[e]}],'forecasts':[],'inferences':[],'numeric_values':[],'related_entities':['未来电器'],'unknowns':[],'source_usage_limits':[]}
    assert f.validate_card(card,[page])==card


@pytest.mark.parametrize('field,value,code',[
    ('page_number',[], 'FULL_CITATION_INVALID'),('page_number',True,'FULL_CITATION_INVALID'),
    ('page_number','1','FULL_CITATION_INVALID'),('text_sha256',{},'FULL_CITATION_INVALID'),
    ('role',[],'FULL_ATTRIBUTION_ROLE_INVALID'),('role',{},'FULL_ATTRIBUTION_ROLE_INVALID'),
])
def test_v2_r2_malformed_hashed_fields_are_local_schema_failures(field,value,code):
    _,pages,valid,_=_v2_81e_fixture();bad=copy.deepcopy(valid)
    if field=='role':bad['speaker_and_source_attribution'][0][field]=value
    else:bad['date']['evidence'][0][field]=value
    raw=json.dumps(bad,ensure_ascii=False)
    with pytest.raises(b.BatchError,match='^'+code+'$'):
        candidate,_=f.canonicalize_citations(raw,pages);f.validate_card(candidate,pages)
    with pytest.raises(b.BatchError,match='^'+code+'$'):f.validate_card(bad,pages)
    assert code in f.LOCAL_OUTPUT_ERRORS and json.loads(raw)==bad


@pytest.mark.parametrize('kind',['PRECLAIM_PRIORITY_GUARD','QUEUE_ZERO_ATTEMPT'])
def test_v2_r2_proven_zero_attempt_defer_same_plan_resume_and_real_attempt_rejected(tmp_path,monkeypatch,kind):
    from types import SimpleNamespace
    from ops import run_pdf_research_remaining_once as d
    ctx=_v2_real80_context();jp=d.EVIDENCE_ROOT/'dispatch.jsonl';actual=jp.read_bytes()
    raw=(b.RESEARCH_PILOT_ROOT/'model/light-v2-before/dispatch-prefix80.jsonl').read_bytes()
    journal=SimpleNamespace(path=jp,events=[json.loads(x) for x in raw.splitlines()])
    def append(e):
        nonlocal raw
        journal.events.append(e);raw+=d.canonical_json(e)+b'\n'
    journal.append=append;oldread=d._read_regular
    monkeypatch.setattr(d,'_read_regular',lambda path,code:raw if Path(path)==jp else oldread(path,code))
    monkeypatch.setattr(f,'output_folder',lambda did,context:tmp_path)
    plan=tmp_path/'plan.json';plan.write_text(json.dumps({'document_id':f.POSITIVE_FIRST_ID,'generation':1,'state_root':'same-existing-job','template_sha256':f.TEMPLATE_SHA}))
    f.prepare_v2_recovery(journal,ctx,append=True)
    intent={'event':'full_intent','document_id':f.POSITIVE_FIRST_ID,'generation':1,'template_sha256':f.TEMPLATE_SHA,'plan_sha256':f.ref(plan)['sha256']}
    append(intent);index=len(journal.events)-1
    # A second unresolved intent is never a zero-attempt proof.
    saved_events=copy.deepcopy(journal.events);saved_raw=raw
    append(intent)
    with pytest.raises(b.BatchError,match='QUOTA_EXCEEDED'):f.prepare_v2_recovery(journal,ctx,append=False)
    journal.events=saved_events;raw=saved_raw
    code='DEFERRED_ANNOUNCEMENT_PRIORITY' if kind=='PRECLAIM_PRIORITY_GUARD' else 'DEFERRED_MODEL_LOCK_BUSY'
    proof={'status':'PROVEN_ZERO_ATTEMPT_DEFER','document_id':f.POSITIVE_FIRST_ID,'generation':1,'intent_index':index,
           'plan':f.ref(plan),'page_input':ctx['documents'][f.POSITIVE_FIRST_ID]['page_input'],'adoption':ctx['full_adoption_ref'],
           'template_sha256':f.TEMPLATE_SHA,'attempted':False,'issued_attempts':0,'new_model_POSTs':0,'code':code,'proof_kind':kind,
           'queue_outcome':None if kind=='PRECLAIM_PRIORITY_GUARD' else {'status':code,'attempted':False,'attempt_count':0,'queue_status':'PENDING','queue_key':'same-bound-request'}}
    pp=f.zero_attempt_path(ctx,index);pp.write_text(json.dumps(proof))
    deferred={'event':'full_deferred','document_id':f.POSITIVE_FIRST_ID,'generation':1,'template_sha256':f.TEMPLATE_SHA,'code':code,'intent_index':index,'attempted':False,'new_model_POSTs':0,'zero_attempt_proof':f.ref(pp)}
    append(deferred);append(intent)
    f.prepare_v2_recovery(journal,ctx,append=False)  # Same immutable plan, no real request consumed.
    marker=tmp_path/f'request-started-{index}.json';marker.write_text('{"status":"REQUEST_ATTEMPT_STARTED"}')
    with pytest.raises(b.BatchError,match='QUOTA_EXCEEDED'):f.prepare_v2_recovery(journal,ctx,append=False)
    marker.unlink()
    for field,value in [('attempted',True),('issued_attempts',1),('new_model_POSTs',1),('plan',{'path':str(plan),'sha256':'f'*64})]:
        bad=copy.deepcopy(proof);bad[field]=value;pp.write_text(json.dumps(bad));journal.events[-2]['zero_attempt_proof']=f.ref(pp)
        with pytest.raises(b.BatchError,match='QUOTA_EXCEEDED'):f.prepare_v2_recovery(journal,ctx,append=False)
    if kind=='QUEUE_ZERO_ATTEMPT':
        bad=copy.deepcopy(proof);bad['queue_outcome']['attempt_count']=1;pp.write_text(json.dumps(bad));journal.events[-2]['zero_attempt_proof']=f.ref(pp)
        with pytest.raises(b.BatchError,match='QUOTA_EXCEEDED'):f.prepare_v2_recovery(journal,ctx,append=False)
    pp.write_text(json.dumps(proof));journal.events[-2]['zero_attempt_proof']=f.ref(pp)
    journal.events[-1]['plan_sha256']='d'*64
    with pytest.raises(b.BatchError,match='QUOTA_EXCEEDED'):f.prepare_v2_recovery(journal,ctx,append=False)
    assert jp.read_bytes()==actual  # No production journal, queue or network mutation.


@pytest.mark.parametrize('entity,role,normalized',[('unknown','UNKNOWN',True),('UnKnOwN','UNKNOWN',True),('UNKNOWN','UNKNOWN',False),(' unknown','UNKNOWN',False),('unknown','publisher',False),('Unknown Corp','UNKNOWN',False),('润邦股份','UNKNOWN',False)])
def test_v2_sentinel_schema_only_audited_no_entity_rewrite(entity,role,normalized):
    _,pages,valid,_=_v2_81e_fixture();valid['speaker_and_source_attribution'].append({'entity':entity,'role':role,'evidence':[valid['date']['evidence'][0]]})
    raw=json.dumps(valid,ensure_ascii=False);candidate,audit=f.canonicalize_citations(raw,pages)
    changes=[x for x in audit if x['transformation']=='SCHEMA_UNKNOWN_SENTINEL_CASE_NORMALIZATION']
    assert bool(changes)==normalized and candidate['speaker_and_source_attribution'][-1]['entity']==('UNKNOWN' if normalized else entity)
    assert json.loads(raw)['speaker_and_source_attribution'][-1]['entity']==entity
    if normalized:
        assert changes[0]['original_value']==entity and changes[0]['raw_inner_sha256']==f.sha(raw.encode()) and changes[0]['no_source_entity_identity_inferred'] is True
        f.validate_card(candidate,pages)
    elif entity not in {'UNKNOWN','润邦股份'}:
        with pytest.raises(b.BatchError,match='ENTITY_UNSUPPORTED'):f.validate_card(candidate,pages)


def _actual_v2_normalized():
    did=f.POSITIVE_FIRST_ID;folder=f.job_folder(did)/'repair-generation1'
    raw=(folder/'stages/source-0001.raw-model-inner.json').read_text()
    assert f.sha(raw.encode())==f.NORMALIZATION_RAW_SHA
    docs,_=f.selection();_,pages=f.source(did,docs)
    card,audit=f.canonicalize_citations(raw,pages)
    return raw,pages,card,audit


def test_common_normalization_actual_raw_preserves_supported_content_and_full_audit():
    raw,pages,card,audit=_actual_v2_normalized();original=json.loads(raw)
    assert f.validate_card(card,pages)==card
    assert [a['transformation'] for a in audit]==['SCHEMA_UNKNOWN_SENTINEL_CASE_NORMALIZATION','EXPLICIT_CURRENT_SOURCE_STATEMENT','UNPERIODIZED_FOOTER_RETURN_EXCLUDED','UNSUPPORTED_DATE_GUESS_NOT_ADOPTED']
    assert card['facts']==original['facts']+[original['forecasts'][1]] and card['forecasts']==original['forecasts'][:1]
    assert card['numeric_values']==original['numeric_values'][:1]
    assert card['date']==original['date'] and card['source_usage_limits']==original['source_usage_limits']
    assert card['unknowns'][:-1]==original['unknowns'][:2] and '2026' not in card['unknowns'][-1] and 'UNKNOWN' in card['unknowns'][-1]
    assert card['speaker_and_source_attribution'][:3]==original['speaker_and_source_attribution'][:3]
    assert card['speaker_and_source_attribution'][3]['entity']=='UNKNOWN'
    assert all(a['raw_inner_sha256']==f.NORMALIZATION_RAW_SHA and a['rule_version']=='LIGHT_SOURCE_CONSTRAINTS_V1' for a in audit)
    assert audit[1]['original_value']==audit[1]['canonical_value']==original['forecasts'][1]
    assert audit[2]['original_value']==original['numeric_values'][1] and audit[2]['canonical_value'] is None
    assert audit[3]['original_value']==original['unknowns'][2]
    assert all(a['source_page_sha256']=={'1':pages[0]['text_sha256']} for a in audit)


@pytest.mark.parametrize('variant',['future_marker','unsupported_current','overflow','non_footer','supported_period','capacity','not_date_guess'])
def test_common_normalization_conservative_boundaries_no_doc_or_index_rules(variant):
    text='目前需求旺盛。未来预计增长。已知产能100艘。\n某公司 +2.38％';p={'page_number':1,'text':text,'text_sha256':f.sha(text.encode())}
    ev=lambda q:{'page_number':1,'text_sha256':p['text_sha256'],'excerpt':q}
    item={'claim':'目前需求旺盛','attribution':'来源称','period':'目前','unit':'UNKNOWN','evidence':[ev('目前需求旺盛。')]}
    card={'facts':[],'forecasts':[copy.deepcopy(item)],'numeric_values':[{'measure_kind':'price_return','period':'UNKNOWN','evidence':[ev('某公司 +2.38％')]}],'unknowns':['事件年份推测为2028年']}
    if variant=='future_marker':card['forecasts'][0]['claim']='目前未来预计增长'
    elif variant=='unsupported_current':card['forecasts'][0]['evidence']=[ev('已知产能100艘。')]
    elif variant=='overflow':card['facts']=[copy.deepcopy(item)]*5
    elif variant=='non_footer':card['numeric_values'][0]['evidence']=[ev('目前需求旺盛。')]
    elif variant=='supported_period':card['numeric_values'][0]['period']='2025年'
    elif variant=='capacity':card['numeric_values'][0]['measure_kind']='annual_capacity'
    else:card['unknowns']=['产能估计2028年增长，但口径不明']
    before=copy.deepcopy(card);audit=[]
    if variant in {'future_marker','unsupported_current','overflow'}:
        with pytest.raises(b.BatchError,match='CURRENT_'):f.normalize_source_constraints(card,[p],audit,raw_inner_sha256='f'*64)
    else:
        f.normalize_source_constraints(card,[p],audit,raw_inner_sha256='f'*64)
        if variant in {'non_footer','supported_period','capacity'}:assert card['numeric_values']==before['numeric_values']
        if variant=='not_date_guess':assert card['unknowns']==before['unknowns']
        assert card['facts']==[item] and card['forecasts']==[]


def _normalization_real86_context():
    ctx=_v2_real80_context();backup=b.RESEARCH_PILOT_ROOT/'model/light-v2-sentinel-before'
    adoption=json.loads((backup/'full-root-7fbd.json').read_bytes())
    data={'decision':f.NORMALIZATION_DECISION,'document_id':f.POSITIVE_FIRST_ID,'page_input':ctx['documents'][f.POSITIVE_FIRST_ID]['page_input'],
          'raw_inner':f.ref(f.job_folder(f.POSITIVE_FIRST_ID)/'repair-generation1/stages/source-0001.raw-model-inner.json'),
          'raw_failure_review':f.ref(b.RESEARCH_PILOT_ROOT/'independent-review/full-light-v2-actual-failure-review.json'),
          'previous_adoption_backup':f.ref(backup/'full-root-7fbd.json'),'previous_source_review_backup':f.ref(backup/'code-482.json'),
          'journal_prefix86_sha256':f.NORMALIZATION_PREFIX86_SHA}
    adoption['common_normalization']=data
    parsed,previous=f.load_normalization_admission(adoption,ctx['documents'])
    return {**ctx,'full_adoption':adoption,'common_normalization':parsed,'normalization_previous_adoption':previous,'v2_resolution_anchor':previous['adoption']}


def test_common_normalization_same_raw_replay_exact_closure_and_unknown_halt_zero_network(tmp_path,monkeypatch):
    import socket
    from ops import run_pdf_research_remaining_once as d
    monkeypatch.setattr(socket.socket,'connect',lambda *a:pytest.fail('replay and closure must never connect'))
    ctx=_normalization_real86_context();actual_jp=d.EVIDENCE_ROOT/'dispatch.jsonl';actual_raw=actual_jp.read_bytes()
    assert f.sha(actual_raw)==f.NORMALIZATION_PREFIX86_SHA
    row,pages,raw=f.authenticate_replay(ctx)
    original_hash=f.ref(Path(ctx['common_normalization']['raw_inner']['path']))
    monkeypatch.setattr(f,'load_context',lambda **_:ctx);monkeypatch.setattr(f,'output_folder',lambda did,context:tmp_path/'derived')
    receipt=f.replay_normalized_card();cp=tmp_path/'derived/card.json';ap=tmp_path/'derived/normalization-audit.json';rp=tmp_path/'derived/receipt.json'
    assert receipt['new_model_POSTs']==0 and receipt['original_raw_content_status']=='CONTENT_FAIL_PRESERVED'
    common,audit=f.canonicalize_citations(raw,pages)
    assert f.read(f.ref(cp))['content']==common and f.read(f.ref(ap))['changes']==audit
    # Real proof is not fabricated: this fixture supplies an explicit mocked independent verdict only in memory.
    proofpath=b.RESEARCH_PILOT_ROOT/'independent-review/full-light-v2-first-card-content-review.json'
    oldref=f.ref;oldread=f.read
    proofref={'path':str(proofpath),'sha256':'f'*64}
    proof={'status':'SOURCE_CONSTRAINED_DERIVED_CARD_PASS','reviewer':f.REVIEWER,'fixture_only':'not actual semantic acceptance','document_id':f.POSITIVE_FIRST_ID,
           'page_input':row['page_input'],'template_sha256':f.TEMPLATE_SHA,'card':oldref(cp),'receipt':oldref(rp),'normalization_audit':oldref(ap)}
    monkeypatch.setattr(f,'ref',lambda p:proofref if Path(p)==proofpath else oldref(p))
    monkeypatch.setattr(f,'read',lambda r,**kw:proof if r==proofref else oldread(r,**kw))
    original_exists=Path.exists;monkeypatch.setattr(Path,'exists',lambda p:True if p==proofpath else original_exists(p))
    class Memory:
        path=actual_jp;root=d.EVIDENCE_ROOT
        def __init__(self):self.raw=actual_raw;self.events=[json.loads(x) for x in self.raw.splitlines()]
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def append(self,e):self.events.append(e);self.raw+=d.canonical_json(e)+b'\n'
    j=Memory();oldregular=d._read_regular;monkeypatch.setattr(d,'_read_regular',lambda p,c:j.raw if Path(p)==actual_jp else oldregular(p,c));monkeypatch.setattr(d,'DurableJournal',lambda _:j)
    with pytest.raises(b.BatchError,match='FULL_PRIOR_FAILURE_NO_RETRY'):f.verify_history(j,ctx)
    first=f.close_normalized_replay()
    assert first['status']=='EXACT84_85_CLOSED_DERIVED_ACCEPTANCE_RAW_FAIL_PRESERVED' and len(first['pending_ids'])==17
    assert [e['event'] for e in j.events[86:]]==['full_adoption','halt_resolution']
    assert f.terminal_map(ctx,j.events)[f.POSITIVE_FIRST_ID]['derived_from_accepted_zero_POST_replay']
    before=j.raw;f.close_normalized_replay();assert j.raw==before
    original_events=copy.deepcopy(j.events)
    for variant in ['duplicate','unknown_halt','extra_terminal']:
        j.events=copy.deepcopy(original_events);j.raw=before
        if variant=='duplicate':j.append(j.events[-1])
        elif variant=='unknown_halt':j.append({'event':'halt','document_id':'a'*64})
        else:j.append({'event':'full_terminal','document_id':f.POSITIVE_FIRST_ID,'status':'GENERATED_MACHINE_VALIDATED_CONTENT_PENDING','generation':1,'receipt':oldref(rp)})
        with pytest.raises((b.BatchError,d.DispatcherError),match='DUPLICATE|FAILURE|EXTRA_TERMINAL'):
            f.verify_history(j,ctx);f.terminal_map(ctx,j.events)
    assert actual_jp.read_bytes()==actual_raw and f.ref(Path(ctx['common_normalization']['raw_inner']['path']))==original_hash
