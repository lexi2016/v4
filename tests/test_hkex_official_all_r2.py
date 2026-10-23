"""Official JS is genuine. DOM, directory positives and PDFs are offline fixtures."""
from pathlib import Path
from base64 import b64decode
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import hashlib, json, shutil, subprocess
import pytest
from v4.manager_research import hkex_directory_protocol as hp
from v4.manager_research.announcement_source import CaptureBudget, collect_batch, read_response
from v4.manager_research.hkex_provider import HkexOfficialProvider
from v4.manager_research.materials import MaterialStore
from v4.manager_research.ports import SourceResponse
F=Path(__file__).parent/'fixtures/hkex_query_contract_r2'
OLD=Path(__file__).parent/'fixtures/source_first_r4'
CTX={'plan_trade_date':'20260928','market_session':'20260925','focus_window_start':'2026-09-24T16:10:00+08:00','research_cutoff':'2026-09-28T18:29:55.388780+08:00'}
ISS={'stock_id':'1','issuer':'Synthetic Co'}
NEW='HKEX_SERVLET_ALL_SELECTION_V2'
REAL=Path(__file__).parent/'fixtures/hkex_real_failures_r2'
REAL_ISS={'stock_id':'2'}
REAL_ECHO=(REAL/'HK.00002_form_directory_ref.html').read_bytes()
assert hashlib.sha256(REAL_ECHO).hexdigest()=='5cdb0c297ea7668ee9e39ed39d5a6bfa623976f31967a28802e0d0cf7db341fe'

def posted_params(req):
    return {k:v[0] for k,v in parse_qs(b64decode(req['body_b64']).decode(),keep_blank_values=True).items()}


def params(req):return {k:v[0] for k,v in parse_qs(urlparse(req['url']).query,keep_blank_values=True).items()}

def test_official_executed_all_selection_matches_post_not_assumed_echo():
    node=shutil.which('node')
    assert node,'approved Node is required for this official-script differential test'
    cp=subprocess.run([node,str(F/'official_request_oracle.cjs')],check=True,capture_output=True,text=True,timeout=5)
    expected=json.loads(cp.stdout)
    # This old oracle has a synthetic DOM. It proves ALL reset inputs only;
    # actual returned criteria are covered by test_hkex_real_failures_r2.py.
    got=hp.all_form_request(ISS,CTX)
    assert got['method']=='POST' and expected['method']=='GET'
    assert urlparse(got['url']).path=='/search/titlesearch.xhtml'
    assert expected['url']=='titleSearchServlet.do'
    posted=posted_params(got)
    for key in ('category','market','stockId','documentType','title','searchType','t1code','t2Gcode','t2code'):
        assert posted[key]==expected['params'][key]
    assert posted['from']==expected['params']['fromDate']
    assert posted['to']==expected['params']['toDate']
    assert posted['lang']=='EN' and expected['params']['lang']=='E'

@pytest.mark.parametrize('key', ['documentType','t1code','t2Gcode','t2code'])
def test_all_selection_uses_explicit_empty_filters(key):
    assert key in posted_params(hp.all_form_request(ISS,CTX))
    assert posted_params(hp.all_form_request(ISS,CTX))[key]==''

def test_legacy_query_is_readable_without_rewriting_history():
    assert params(hp.servlet_request(ISS,CTX,100,protocol='HKEX_SERVLET_CUMULATIVE_V1'))['documentType']=='-1'
    assert hp.servlet_request(REAL_ISS,CTX,100,form_raw=REAL_ECHO)['protocol']==NEW

@pytest.mark.parametrize('key,value',[('research_cutoff','2026-09-23T11:00:00+08:00'),('focus_window_start','2026-09-24T16:10:00')])
def test_bad_query_window_still_refused(key,value):
    with pytest.raises(ValueError):hp.servlet_request(REAL_ISS,{**CTX,key:value},100,form_raw=REAL_ECHO)

@pytest.mark.parametrize('limit',[100,300,600,1000,2000])
def test_only_filters_change_not_dates_identity_or_existing_range(limit):
    p=params(hp.servlet_request(REAL_ISS,CTX,limit,form_raw=REAL_ECHO))
    assert (p['fromDate'],p['toDate'],p['stockId'],p['rowRange'],p['category'],p['market'],p['searchType'])==('20260924','20260928','2',str(limit),'0','SEHK','0')

def setup_owner(tmp_path, mode='normal'):
    calls=[]
    shell=sorted(OLD.glob('*.html'))[0].read_bytes()
    def response(url, body, status=200):
        return SourceResponse(url=url,final_url=url,status_code=status,body=body,headers={},retrieved_at='2026-09-28T18:30:10+08:00')
    def transport(url,**kwargs):
        calls.append((url,kwargs.get('method','GET')))
        if 'activestock' in url:return response(url,b'[{"c":"00001","i":1,"n":"Synthetic Co"}]')
        if url.endswith('/titlesearch.js'):
            if mode=='main-transport':raise TimeoutError('synthetic')
            if mode=='main-http':return response(url,b'error',503)
            raw=(F/'titlesearch.js').read_bytes()
            return response(url,raw.replace(b"this.SetDocumentType('');",b"this.SetDocumentType('-1');") if mode=='main-drift' else raw)
        if url.endswith('/titlesearch_research.js'):return response(url,(F/'titlesearch_research.js').read_bytes())
        if 'titleSearchServlet' in url:
            assert params({'url':url})['documentType']=='','the transport must not receive the legacy filter'
            if mode=='page-transport':raise TimeoutError('synthetic')
            if mode=='empty':return response(url,(OLD/'hkex_empty_servlet_20260928.json').read_bytes())
            row={'NEWS_ID':'123','FILE_LINK':'/listedco/listconews/sehk/2026/0928/synthetic1.pdf','DATE_TIME':'28/09/2026 17:00','STOCK_CODE':'00001','STOCK_NAME':'Synthetic Co','TITLE':'Synthetic announcement','SHORT_TEXT':'Announcements','LONG_TEXT':'Announcements'}
            return response(url,json.dumps({'result':json.dumps([row]),'hasNextRow':False,'rowRange':100,'lang':'E','loadedRecord':1,'recordCnt':1}).encode())
        if url.endswith('/synthetic1.pdf'):return response(url,(OLD/'synthetic_issuer_document.pdf').read_bytes())
        if kwargs.get('method')=='POST':
            form=parse_qs(kwargs['body'].decode(),keep_blank_values=True)
            assert all(form[key]==[''] for key in ('documentType','t1code','t2Gcode','t2code'))
            # Synthetic compatibility fixture only; not a server-normalization proof.
            # Immutable server HTML and original-owner replay live in the real-failures suite.
            echoed=shell.replace(b'value="-1"',b'value=""').replace(b'value="-2"',b'value=""')
            import re
            echoed=re.sub(rb'(<input id="stockId"[^>]*value=")[^"]*',lambda m:m[1]+b'1',echoed)
            if mode=='echo-mismatch':echoed=shell
            return response(url,echoed)
        return response(url,shell)
    store=MaterialStore(tmp_path/'materials')
    return HkexOfficialProvider(transport=transport,material_store=store),store,calls

def run(p,limit=57,documents=0):
    return collect_batch(p,context=CTX,issuers=[{'code':'HK.00001','name':'Synthetic Co'}],max_documents=documents,budget=CaptureBudget(max_requests=limit,interval=0))

def test_original_owner_new_query_has_both_official_scripts_and_no_wrong_post(tmp_path):
    p,s,calls=setup_owner(tmp_path)
    r=run(p);q=r['queries'][0]
    assert q['status']=='OBSERVED',q
    assert q['directory_protocol']==NEW
    assert q['legacy_directory_ref']==q['prime_ref']
    assert q['selection_script_ref']['request']['url'].endswith('/titlesearch.js')
    assert read_response(s,q['selection_script_ref'])==(F/'titlesearch.js').read_bytes()
    assert sum(method=='POST' for _,method in calls)==1
    assert q['form_directory_ref']['request']==hp.all_form_request(ISS,CTX)
    before=list(calls)
    hp.revalidate_servlet_query(q,CTX,lambda ref:read_response(s,ref))
    assert calls==before

def test_synthetic_nonempty_goes_through_real_pdf_parser_store_and_readonly_projection(tmp_path,monkeypatch):
    p,s,calls=setup_owner(tmp_path)
    r=run(p,documents=1)
    assert len(r['documents'])==1 and r['documents'][0]['parse_status']=='BODY_PARSED'
    from v4.manager_research import workspace_announcements as wa
    witness={'source':'synthetic-master'}
    monkeypatch.setattr(wa,'_master',lambda *a:({'HK.00001':{'name':'Synthetic Co'}},witness))
    product={'context':CTX,'target_trade_date':'20260928','identity_witness':witness,'scope':['HK.00001'],
      **r,'generated_at':'2026-09-28T18:30:20+08:00','next_index':1,'run_id':'synthetic-r2','revision':1,'sha256':'a'*64}
    before=list(calls);wa._check_sources(SimpleNamespace(_material_store=s),product)
    proj=wa.project(SimpleNamespace(_material_store=s),product,{**CTX,'research_cutoff':'2026-09-28T18:31:00+08:00'})
    assert proj['official_documents'][0]['body_status']=='BODY_PARSED'
    assert calls==before
    assert proj['positive_observations'][0]['focus_eligible'] is False

@pytest.mark.parametrize('mode',['main-transport','main-http','main-drift','page-transport','echo-mismatch'])
def test_script_or_network_failure_remains_failed_and_revalidates(tmp_path,mode):
    p,s,calls=setup_owner(tmp_path,mode)
    q=run(p)['queries'][0]
    assert q['status']=='FAILED'
    assert not q.get('directory_exhaustion_verified')
    hp.revalidate_servlet_query(q,CTX,lambda ref:read_response(s,ref))

@pytest.mark.parametrize('limit',[2,3,4,5])
def test_budget_before_each_protocol_stage_preserves_real_partial_refs(tmp_path,limit):
    p,s,_=setup_owner(tmp_path)
    q=run(p,limit)['queries'][0]
    assert q['status']=='FAILED' and q['reason']=='ANNOUNCEMENT_REQUEST_BUDGET_EXHAUSTED'
    assert q['capture_failure']['outcome']=='BUDGET_REFUSED_BEFORE_PROVIDER_CALL'
    hp.revalidate_servlet_query(q,CTX,lambda ref:read_response(s,ref))

@pytest.mark.parametrize('tamper',['selection-ref','protocol-downgrade','request-filter','remove-selection','body-hash','context-cutoff','form-params'])
def test_readback_rejects_changed_evidence_or_query(tmp_path,tamper):
    p,s,_=setup_owner(tmp_path)
    q=deepcopy(run(p)['queries'][0]);ctx=deepcopy(CTX)
    assert q['directory_protocol']==NEW
    if tamper=='selection-ref':q['selection_script_ref']['request']['url']='https://evil.test/titlesearch.js'
    elif tamper=='protocol-downgrade':q['directory_protocol']='HKEX_SERVLET_CUMULATIVE_V1'
    elif tamper=='request-filter':q['directory_pages'][0]['request']['url']=q['directory_pages'][0]['request']['url'].replace('documentType=&','documentType=-1&')
    elif tamper=='remove-selection':q.pop('selection_script_ref')
    elif tamper=='body-hash':q['selection_script_ref']['body_sha256']='0'*64
    elif tamper=='form-params':q['form_directory_ref']['request']['body_b64']='eD0x'
    else:ctx['research_cutoff']='2026-09-28T18:29:56+08:00'
    with pytest.raises(ValueError):hp.revalidate_servlet_query(q,ctx,lambda ref:read_response(s,ref))

def test_three_real_legacy_captures_revalidate_without_network_or_rewrite(tmp_path):
    receipt=json.loads((F/'legacy_owner_receipt.json').read_bytes())
    destination=tmp_path/'legacy_store'
    shutil.copytree(F/'legacy_owner_materials',destination)
    store=MaterialStore(destination)
    def inventory():return {str(p.relative_to(destination)):hashlib.sha256(p.read_bytes()).hexdigest() for part in ('blobs','index') for p in (destination/part).rglob('*') if p.is_file()}
    before=inventory()
    assert len(receipt['result']['queries'])==3
    for q in receipt['result']['queries']:
        assert q['directory_protocol']=='HKEX_SERVLET_CUMULATIVE_V1'
        hp.revalidate_servlet_query(q,receipt['request']['context'],lambda r:read_response(store,r))
        assert params(q['directory_pages'][0]['request'])['documentType']=='-1'
    assert inventory()==before

def test_empty_current_query_remains_empty_not_document_success(tmp_path):
    p,s,_=setup_owner(tmp_path,'empty')
    result=run(p,documents=1)
    q=result['queries'][0]
    assert q['status']=='OBSERVED' and q['directory_exhaustion_verified']
    assert not result['documents'] and not result['pending_documents']
    assert q['selection_script_ref']
    hp.revalidate_servlet_query(q,CTX,lambda r:read_response(s,r))

def test_real_official_main_script_proves_primary_all_form_filters():
    from base64 import b64decode
    request=hp.all_form_request(ISS,CTX)
    fields={k:v[0] for k,v in parse_qs(b64decode(request['body_b64']).decode(),keep_blank_values=True).items()}
    assert request['method']=='POST' and request['url'].endswith('/titlesearch.xhtml?lang=en')
    assert fields=={'lang':'EN','category':'0','market':'SEHK','searchType':'0','documentType':'',
      't1code':'','t2Gcode':'','t2code':'','stockId':'1','from':'20260924','to':'20260928','title':''}
    hp.attest_selection_script((F/'titlesearch.js').read_bytes())

@pytest.mark.parametrize('mode',['absent-id','duplicate-id','wrong-issuer','wrong-date','wrong-type','old-filters'])
def test_response_echo_must_agree_with_real_submitted_selection(tmp_path,mode):
    p,s,_=setup_owner(tmp_path)
    q=run(p)['queries'][0]
    raw=read_response(s,q['form_directory_ref'])
    hp.attest_form_echo(raw,ISS,CTX)
    if mode=='absent-id':raw=raw.replace(b'id="stockId"',b'id="other"')
    elif mode=='duplicate-id':raw+=b'<input id="stockId" value="1">'
    elif mode=='wrong-issuer':raw=raw.replace(b'id="stockId" type="hidden" value="1"',b'id="stockId" type="hidden" value="2"')
    elif mode=='wrong-date':raw=raw.replace(b'value="2026-09-24"',b'value="2026-09-23"')
    elif mode=='wrong-type':raw=raw.replace(b'id="searchTypeInt" type="hidden" value="0"',b'id="searchTypeInt" type="hidden" value="1"')
    else:raw=raw.replace(b'id="selectedDocType" type="hidden" value=""',b'id="selectedDocType" type="hidden" value="-1"')
    with pytest.raises(ValueError):hp.attest_form_echo(raw,ISS,CTX)
