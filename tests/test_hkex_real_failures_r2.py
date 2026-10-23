"""Two real P1s: immutable HTML positives; mutations and servlet pages are explicitly synthetic.

The fixture provider never accesses the internet. Its default stops before a
servlet response, so passing these tests is not live directory/body acceptance.
"""
from base64 import b64decode
from copy import deepcopy
from hashlib import sha256
from html.parser import HTMLParser
from itertools import product
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json
import re
import shutil
import subprocess
import pytest
from v4.manager_research import hkex_directory_protocol as hp
from v4.manager_research.announcement_source import CaptureBudget, collect_batch, read_response
from v4.manager_research.hkex_provider import HkexOfficialProvider
from v4.manager_research.materials import MaterialStore
from v4.manager_research.ports import SourceResponse

F=Path(__file__).parent/'fixtures/hkex_real_failures_r2'
JS=Path(__file__).parent/'fixtures/hkex_query_contract_r2'
RECEIPT=json.loads((F/'original_owner_attempt.json').read_bytes())
CTX=RECEIPT['request']['context']
QUERIES={q['code']:q for q in RECEIPT['result']['queries']}
INDEX={Path(r['path']).name:r for r in json.loads((F/'DECODED_ORIGINALS_INDEX.json').read_bytes())}
FILTERS=('selectedDocType','tierOneId','tierTwoGpId','tierTwoId')
SENTINELS=('-1','-2','-2','-2')


def raw(name):
    data=(F/name).read_bytes()
    assert sha256(data).hexdigest()==INDEX[name]['body_sha256']
    return data


def issuer(code):
    return QUERIES[code]['official_issuer']


def echo(code='HK.00002'):
    return raw(code+'_form_directory_ref.html')


def parameters(request):
    return {k:v[0] for k,v in parse_qs(urlparse(request['url']).query,keep_blank_values=True).items()}


def original_values(data):
    """Independent input reader; does not call the implementation under test."""
    class Inputs(HTMLParser):
        def __init__(self):super().__init__();self.values={}
        def handle_starttag(self,tag,attrs):
            fields=dict(attrs)
            if tag=='input' and fields.get('id'):
                assert fields['id'] not in self.values
                self.values[fields['id']]=fields.get('value','')
    parser=Inputs();parser.feed(data.decode('utf8'));return parser.values


@pytest.mark.parametrize('name', sorted(INDEX))
def test_unmodified_decoded_original_matches_blob_and_receipt(name):
    entry=INDEX[name]
    store=MaterialStore(F/'original_materials')
    assert raw(name)==read_response(store,entry['original_ref'])


def test_real_session_suffixed_shell_is_recognized():
    assert hp.is_search_shell(raw('HK.00001_prime_ref.html'))


def test_actual_owner_leading_hyphen_session_shell_is_recognized():
    # Exact original-owner HTTP 200 body; the raw session token stays in the fixture.
    data=(F/'HK.00001_prime_leading_hyphen_ref.html').read_bytes()
    assert sha256(data).hexdigest()=='580c582c51eb11c9a60fbbf89db10efcf3423da4b02a9541155b288f62b8035f'
    assert hp.is_search_shell(data)


@pytest.mark.parametrize('code',['HK.00002','HK.00003'])
def test_real_unsuffixed_shell_and_normalized_echo_are_accepted(code):
    assert hp.is_search_shell(raw(code+'_prime_ref.html'))
    values=hp.attest_form_echo(echo(code),issuer(code),CTX)
    assert tuple(values[k] for k in FILTERS)==SENTINELS
    assert values['stockId']==issuer(code)['stock_id']


BAD_ACTIONS=[
    'https://evil.test/search/titlesearch.xhtml;jsessionid=abc',
    '//evil.test/search/titlesearch.xhtml;jsessionid=abc',
    'https://www1.hkexnews.hk.evil.test/search/titlesearch.xhtml',
    'https://www1.hkexnews.hk@evil.test/search/titlesearch.xhtml',
    'https://evil.test@www1.hkexnews.hk/search/titlesearch.xhtml',
    'http://www1.hkexnews.hk/search/titlesearch.xhtml',
    'https://www1.hkexnews.hk:444/search/titlesearch.xhtml',
    '/search/other.xhtml;jsessionid=abc',
    '/search/titlesearch.xhtml.evil;jsessionid=abc',
    '/search/titlesearch.xhtml/other;jsessionid=abc',
    '/search/titlesearch.xhtml;other=abc',
    '/search/titlesearch.xhtml;jsessionid=',
    '/search/titlesearch.xhtml;jsessionid=abc;other=1',
    '/search/titlesearch.xhtml;jsessionid=abc;jsessionid=def',
    '/search/titlesearch.xhtml;jsessionid=abc/../other',
    '/search/titlesearch.xhtml;jsessionid=abc%2fdef',
    '/search/titlesearch.xhtml%3bjsessionid=abc',
    '/search/titlesearch.xhtml;jsessionid=abc?redirect=evil',
    '/search/titlesearch.xhtml;jsessionid=abc#fragment',
    '/search/../search/titlesearch.xhtml;jsessionid=abc',
    '\n/search/titlesearch.xhtml;jsessionid=abc',
]


def with_action(data,action):
    changed,count=re.subn(rb'(<form\b[^>]*\baction=")[^"]*',lambda m:m[1]+action.encode(),data,count=1)
    assert count==1
    return changed


@pytest.mark.parametrize('action',BAD_ACTIONS)
def test_synthetic_bad_action_is_refused_without_relaxing_origin(action):
    assert not hp.is_search_shell(with_action(raw('HK.00001_prime_ref.html'),action))


@pytest.mark.parametrize('change', ['missing-name','wrong-name','wrong-method','duplicate-action','duplicate-form'])
def test_synthetic_ambiguous_or_wrong_form_identity_is_refused(change):
    data=raw('HK.00002_prime_ref.html')
    if change=='missing-name':data=data.replace(b'name="j_idt10" method=',b'method=',1)
    elif change=='wrong-name':data=data.replace(b'name="j_idt10" method=',b'name="other" method=',1)
    elif change=='wrong-method':data=data.replace(b'method="post"',b'method="get"',1)
    elif change=='duplicate-action':data=data.replace(b'action="/search/titlesearch.xhtml"',b'action="https://evil.test/" action="/search/titlesearch.xhtml"',1)
    else:data+=b'<form id="j_idt10" name="j_idt10" method="post" action="/search/titlesearch.xhtml"></form>'
    assert not hp.is_search_shell(data)


@pytest.mark.parametrize('code',['HK.00002','HK.00003'])
def test_post_preserves_exact_actual_empty_all_submission(code):
    request=hp.all_form_request(issuer(code),CTX)
    original=QUERIES[code]['form_directory_ref']['request']
    assert request==original
    form=parse_qs(b64decode(request['body_b64']).decode(),keep_blank_values=True)
    assert all(form[k]==[''] for k in ('documentType','t1code','t2Gcode','t2code'))


@pytest.mark.parametrize('code',['HK.00002','HK.00003'])
@pytest.mark.parametrize('limit',hp.RANGES)
def test_get_matches_official_function_executed_with_real_echo(code,limit):
    node=shutil.which('node');assert node,'Node is required for the retained-script oracle'
    data=echo(code)
    values=original_values(data)
    cp=subprocess.run([node,str(F/'official_echo_oracle.cjs'),str(JS/'titlesearch_research.js')],
        input=json.dumps({'values':values,'limit':limit}),capture_output=True,text=True,check=True,timeout=5)
    expected=json.loads(cp.stdout)
    request=hp.servlet_request(issuer(code),CTX,limit,form_raw=data)
    assert request['method']==expected['method']
    assert urlparse(request['url']).path=='/search/'+expected['url']
    assert parameters(request)==expected['params']
    assert request['protocol']==hp.PROTOCOL
    assert request['context']==hp.all_form_request(issuer(code),CTX)['context']


def test_current_get_without_a_server_echo_is_refused():
    with pytest.raises(ValueError,match='HKEX_ALL_FORM_ECHO_REQUIRED'):
        hp.servlet_request(issuer('HK.00002'),CTX,100)


@pytest.mark.parametrize('field,value', [
    ('stockId','3'),('startDate','2026-09-23'),('endDate','2026-09-29'),
    ('searchTypeInt','1'),('selectedSecurities','1'),('newsTitle','restricted'),('lang','C'),
    ('selectedDocType','1'),('tierOneId','1'),('tierTwoGpId','1'),('tierTwoId','1')])
def test_synthetic_issuer_date_or_filter_changes_are_refused(field,value):
    data=echo()
    pattern=rb'(<input id="'+field.encode()+rb'"[^>]*)(/>)'
    def mutate(m):
        prefix=re.sub(rb'\svalue="[^"]*"',b'',m[1])
        return prefix+b' value="'+value.encode()+b'" '+m[2]
    data,count=re.subn(pattern,mutate,data,count=1);assert count==1
    with pytest.raises(ValueError):hp.attest_form_echo(data,issuer('HK.00002'),CTX)


@pytest.mark.parametrize('mask',[m for m in product((False,True),repeat=4) if any(m) and not all(m)])
def test_synthetic_mixed_blank_sentinel_vectors_are_refused(mask):
    data=echo()
    for key,value,blank in zip(FILTERS,SENTINELS,mask):
        if blank:
            old=f'id="{key}" type="hidden" value="{value}"'.encode()
            assert data.count(old)==1
            data=data.replace(old,f'id="{key}" type="hidden" value=""'.encode())
    with pytest.raises(ValueError):hp.attest_form_echo(data,issuer('HK.00002'),CTX)


@pytest.mark.parametrize('change',['duplicate-element','same-duplicate','duplicate-value','duplicate-id','not-hidden','missing-id'])
def test_synthetic_forged_or_conflicting_echo_is_refused(change):
    data=echo()
    if change=='duplicate-element':data+=b'<input id="stockId" type="hidden" value="3">'
    elif change=='same-duplicate':data+=b'<input id="stockId" type="hidden" value="2">'
    elif change=='duplicate-value':data=data.replace(b'id="stockId" type="hidden" value="2"',b'id="stockId" type="hidden" value="3" value="2"')
    elif change=='duplicate-id':data=data.replace(b'id="stockId" type="hidden"',b'id="wrong" id="stockId" type="hidden"')
    elif change=='not-hidden':data=data.replace(b'id="stockId" type="hidden"',b'id="stockId" type="text"')
    else:data=data.replace(b'id="stockId"',b'id="otherStockId"')
    with pytest.raises(ValueError):hp.attest_form_echo(data,issuer('HK.00002'),CTX)


def fixture_owner(tmp_path,code='HK.00002',mode='no-servlet-response'):
    """Original master/shell/POST bytes. Any servlet result here is SYNTHETIC."""
    calls=[];old=QUERIES[code];store=MaterialStore(tmp_path/'store')
    original_store=MaterialStore(F/'original_materials')
    master=read_response(original_store,old['mapping_ref'])
    def response(url,data):
        return SourceResponse(url=url,final_url=url,status_code=200,body=data,headers={},retrieved_at='2026-09-28T12:29:10+00:00')
    def transport(url,**kwargs):
        method=kwargs.get('method','GET');calls.append((url,method,kwargs.get('body')))
        if 'activestock_sehk_e.json' in url:return response(url,master)
        if url==hp.SELECTION_SCRIPT_URL:return response(url,(JS/'titlesearch.js').read_bytes())
        if url==hp.RESEARCH_SCRIPT_URL:return response(url,(JS/'titlesearch_research.js').read_bytes())
        if method=='POST':
            assert kwargs['body']==b64decode(hp.all_form_request(issuer(code),CTX)['body_b64'])
            if code=='HK.00001':raise TimeoutError('Offline fixture has no ALL POST response for issuer 1')
            return response(url,echo(code))
        if 'titleSearchServlet.do' in url:
            actual=parameters({'url':url});assert tuple(actual[k] for k in ('documentType','t1code','t2Gcode','t2code'))==SENTINELS
            if mode=='no-servlet-response':raise TimeoutError('Offline fixture: GET was constructed but not sent')
            limit=int(actual['rowRange']);count=100 if limit==100 else 101
            rows=[{'NEWS_ID':str(n),'FILE_LINK':f'/listedco/listconews/sehk/2026/0928/synthetic{n}.pdf',
                   'DATE_TIME':'28/09/2026 17:00','STOCK_CODE':code[3:],'STOCK_NAME':issuer(code)['issuer'],
                   'TITLE':'SYNTHETIC announcement','LONG_TEXT':'SYNTHETIC','FILE_TYPE':'PDF'} for n in range(count)]
            return response(url,json.dumps({'result':json.dumps(rows),'rowRange':limit,'hasNextRow':limit==100,
                  'loadedRecord':count,'recordCnt':count,'lang':'E'}).encode())
        return response(url,raw(code+'_prime_ref.html'))
    return HkexOfficialProvider(transport=transport,material_store=store),store,calls


def collect_fixture(provider,code='HK.00002',max_requests=57):
    return collect_batch(provider,context=CTX,issuers=[{'code':code,'name':QUERIES[code]['name']}],
          max_documents=0,budget=CaptureBudget(max_requests=max_requests,interval=0))


@pytest.mark.parametrize('code',['HK.00002','HK.00003'])
def test_real_html_drives_original_owner_to_get_without_claiming_a_response(tmp_path,code):
    provider,store,calls=fixture_owner(tmp_path,code)
    result=collect_fixture(provider,code);q=result['queries'][0]
    assert q['form_directory_ref']['body_sha256']==sha256(echo(code)).hexdigest()
    assert read_response(store,q['form_directory_ref'])==echo(code)
    assert q['status']=='FAILED' and q['directory_pages']==[] and result['documents']==[]
    assert q['capture_failure']['outcome']=='NO_RESPONSE_REFERENCE_RETURNED'
    assert parameters(q['capture_failure']['request'])['documentType']=='-1'
    before=deepcopy(calls)
    hp.revalidate_servlet_query(q,CTX,lambda ref:read_response(store,ref))
    assert calls==before


def test_session_shell_routes_to_all_post_not_legacy_post(tmp_path):
    provider,store,calls=fixture_owner(tmp_path,'HK.00001')
    result=collect_fixture(provider,'HK.00001');q=result['queries'][0]
    assert q['directory_protocol']==hp.PROTOCOL
    assert q['selection_script_ref'] and q['form_directory_ref'] is None
    assert q['capture_failure']['request']==hp.all_form_request(issuer('HK.00001'),CTX)
    assert sum(method=='POST' for _,method,_ in calls)==1
    hp.revalidate_servlet_query(q,CTX,lambda ref:read_response(store,ref))


@pytest.mark.parametrize('budget',[5,6])
def test_synthetic_pagination_budget_binds_pending_request_to_real_echo(tmp_path,budget):
    provider,store,_=fixture_owner(tmp_path,mode='synthetic-pages')
    q=collect_fixture(provider,max_requests=budget)['queries'][0]
    assert q['status']=='FAILED'
    assert q['capture_failure']['outcome']=='BUDGET_REFUSED_BEFORE_PROVIDER_CALL'
    assert len(q['directory_pages'])==budget-5
    assert parameters(q['capture_failure']['request'])['documentType']=='-1'
    assert parameters(q['capture_failure']['request'])['rowRange']==str(hp.RANGES[budget-5])
    hp.revalidate_servlet_query(q,CTX,lambda ref:read_response(store,ref))


def test_synthetic_pagination_and_readback_preserve_same_real_echo(tmp_path):
    provider,store,calls=fixture_owner(tmp_path,mode='synthetic-pages')
    result=collect_fixture(provider);q=result['queries'][0]
    assert q['status']=='OBSERVED' and len(q['directory_pages'])==2
    assert len(q['entries'])==101 and q['directory_exhaustion_verified']
    assert result['documents']==[] and len(result['pending_documents'])==101
    before=deepcopy(calls)
    hp.revalidate_servlet_query(q,CTX,lambda ref:read_response(store,ref))
    assert calls==before
    altered=deepcopy(q)
    altered['directory_pages'][1]['request']['url']=altered['directory_pages'][1]['request']['url'].replace('documentType=-1&','documentType=&')
    with pytest.raises(ValueError):hp.revalidate_servlet_query(altered,CTX,lambda ref:read_response(store,ref))


@pytest.mark.parametrize('tamper',['post-filter','wrong-issuer','wrong-date','foreign-form-url'])
def test_readback_cannot_use_valid_echo_to_hide_a_different_submission(tmp_path,tamper):
    provider,store,_=fixture_owner(tmp_path)
    q=collect_fixture(provider)['queries'][0]
    assert 'capture_failure' in q
    altered=deepcopy(q)
    if tamper=='post-filter':
        from base64 import b64encode
        request=altered['form_directory_ref']['request']
        request['body_b64']=b64encode(b64decode(request['body_b64']).replace(b'documentType=&',b'documentType=-1&')).decode()
    elif tamper=='wrong-issuer':altered['official_issuer']['stock_id']='3'
    elif tamper=='wrong-date':altered['form_directory_ref']['request']['context']['since']='2026-09-23T16:10:00+08:00'
    else:altered['form_directory_ref']['request']['url']='https://evil.test/search/titlesearch.xhtml?lang=en'
    with pytest.raises(ValueError):hp.revalidate_servlet_query(altered,CTX,lambda ref:read_response(store,ref))
