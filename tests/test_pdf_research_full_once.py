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
            'numeric_values':[{'value_as_source':'100','sign':'正','unit':'万元','period':'2026年','actual_or_forecast':'预测','evidence':[e]}],'related_entities':[],'unknowns':['发布日期未核实']}


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
