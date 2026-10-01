"""Python indexed producers -> original fetch/parser -> original DOM renderers.
Synthetic upstream fixtures; no network provider, no live 8873, no deployments.
"""
import json, os, subprocess, shutil
from copy import deepcopy
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
from producer_cases import CASES,DAY,CONTEXT,make_case,raw_doc,project_docs,mirror,old_material,ordinary,NAMES,IDENTITY
from v4.manager_research.announcement_materials import mirror_material
from v4.manager_research.workspace_discovery import project_material_discovery
from v4.manager_research.issuer_us_relations import material_us_relations
from v4.manager_research.workspace_projection import timestamp

APP=Path(os.environ['BI_APP']).resolve()
OUT=Path(os.environ['BI_OUTPUT']).resolve();OUT.mkdir(parents=True,exist_ok=True)

@pytest.fixture(scope='session')
def browser_page(tmp_path_factory):
    built=tmp_path_factory.mktemp('compiled')
    cmd=['tsc',*[str(APP/'apps/web/src'/p) for p in ('api/managerWorkspace.ts','manager-selection/researchAttention.ts','manager-selection/announcementObservation.ts')],
         '--target','ES2020','--module','ES2020','--lib','ES2020,DOM','--outDir',str(built),'--strict','--skipLibCheck']
    result=subprocess.run(cmd,text=True,capture_output=True)
    (OUT/'tsc.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0, result.stdout+result.stderr
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1280,'height':1000})
        page.route('**/*',lambda route:route.abort())
        page.set_content('<html lang="zh"><head><meta charset="utf-8"></head><body><main><section id="announcements"></section><section id="attention"></section></main></body></html>')
        modules={name:(built/path).read_text() for name,path in {
            'api':'api/managerWorkspace.js','ann':'manager-selection/announcementObservation.js',
            'attention':'manager-selection/researchAttention.js'}.items()}
        page.evaluate('''async modules=>{
          window.originalModules={};
          for(const [name,source] of Object.entries(modules)){
            const url=URL.createObjectURL(new Blob([source],{type:'text/javascript'}));
            window.originalModules[name]=await import(url); URL.revokeObjectURL(url);
          }
        }''',modules)
        yield page
        browser.close()


def render(page,value):
    raw=json.dumps(value,ensure_ascii=False)
    # Only fetch transport is synthetic, the public request/parser/validator
    # and renderer modules above execute their original compiled functions.
    page.evaluate("raw=>{window.testResponse=raw;window.fetch=async(url,options)=>{window.lastRequest={url,method:options.method};return new Response(window.testResponse,{status:200,headers:{'Content-Type':'application/json'}});};}",raw)
    return page.evaluate('''async date=>{
      const {api,ann,attention}=window.originalModules;
      try {
        const value=await api.requestManagerWorkspace(date,new AbortController().signal,'dynamic');
        ann.renderAnnouncementObservation(document.querySelector('#announcements'),value.announcement_observation);
        attention.renderResearchAttention(document.querySelector('#attention'),value.research_attention,value.us_market_attention);
        return {ok:true,ids:[...document.querySelectorAll('[data-eastmoney-announcement]')].map(n=>n.dataset.eastmoneyAnnouncement),
          cards:[...document.querySelectorAll('.research-attention-card')].map(n=>n.dataset.symbol),
          relationships:document.querySelectorAll('[data-research-relationship]').length,text:document.body.innerText};
      }catch(error){return {ok:false,error:String(error.message)};}
    }''',DAY)

@pytest.mark.parametrize('case',CASES)
def test_python_output_original_parser_and_dom(browser_page,case):
    produced=make_case(case)
    (OUT/(case+'.json')).write_text(json.dumps(produced,ensure_ascii=False,indent=2))
    assert produced['actual_mapping_count']==produced['expected_mapping_count'], produced['workspace']['research_attention']['us_mapping_diagnostics']
    view=render(browser_page,produced['workspace'])
    assert view['ok'], view
    if case in {'multi_instance','repeat_instance','two_issuers'}:
        expected={'multi_instance':3,'repeat_instance':1,'two_issuers':2}[case]
        assert len(view['ids'])==expected
        assert len(set(view['ids']))==expected
    if produced['expected_mapping_count']:
        assert view['relationships']==produced['expected_mapping_count']
        assert '关联不等于受益或买入' in view['text']
    if case=='standing':assert '长期关系' in view['text'] and '不是今天新增催化' in view['text']
    if case=='mirror':assert '镜像' in view['text'] and '首次发布' in view['text']
    if case=='risk_explanation':assert '减少' in view['text']
    if case in {'multi_instance','standing','mirror'}:
        browser_page.screenshot(path=str(OUT/(case+'.png')),full_page=True)
    assert all(c['buy_gate_updated'] is False and c['orders_sent'] is False and c['production_allowed'] is False
               for c in produced['workspace']['research_attention']['cards'])

@pytest.mark.parametrize('mutation',['duplicate_id','individual_semantic','relation_clock','standing_expiry','standing_source','same_source','mirror_publication','mirror_refs','unbound_old_sort_clock','standing_too_long','standing_missing_retrieved','wrong_issuer'])
def test_malformed_serialized_outputs_are_rejected(browser_page,mutation):
    case='multi_instance' if mutation=='duplicate_id' else 'standing' if mutation.startswith('standing') or mutation=='unbound_old_sort_clock' else 'mirror' if mutation.startswith('mirror') else 'native_current'
    value=deepcopy(make_case(case)['workspace'])
    if mutation=='duplicate_id':
        docs=value['announcement_observation']['eastmoney_hk_documents'];docs[1]['event_id']=docs[0]['event_id']
    else:
        card=value['research_attention']['cards'][0]
        if mutation.startswith('mirror'):
            row=next(e for e in card['evidence'] if e['evidence_lane']=='COMPANY_MATERIAL')
            if mutation=='mirror_publication':row['published_at']='2026-09-29T18:00:00+08:00'
            else:row['source_refs']=[]
        else:
            row=next(e for e in card['evidence'] if e['evidence_lane']=='US_INDIVIDUAL_MAPPING');rel=row['hk_relation']
            if mutation=='individual_semantic':rel['semantic_status']='STANDING_RELATION'
            elif mutation=='relation_clock':rel['issuer_available_at']=None;rel['available_at']=None
            elif mutation=='standing_expiry':rel['standing_validity']['valid_until']=CONTEXT['research_cutoff']
            elif mutation=='standing_source':rel['standing_validity']['source_payload_sha256']='0'*64
            elif mutation=='wrong_issuer':rel['symbol']='HK.05678'
            elif mutation=='same_source':row['source_identity']['payload_sha256']=rel['source_refs'][0]['payload_sha256']
            elif mutation=='unbound_old_sort_clock':card['freshest_published_at']='2025-01-01T00:00:00+08:00'
            elif mutation=='standing_too_long':rel['standing_validity']['valid_until']='2030-01-01T00:00:00+08:00'
            elif mutation=='standing_missing_retrieved':rel['retrieved_at']=None;rel['issuer_retrieved_at']=None
    assert render(browser_page,value)['ok'] is False

@pytest.mark.parametrize('mutation',['body','page','ref'])
def test_original_mirror_material_binding_rejects_tampered_provenance(mutation):
    docs,_=project_docs([raw_doc()]);doc=docs[0]
    if mutation=='body':doc['body_text']+='篡改'
    elif mutation=='page':doc['body_pages'][0]['text_sha256']='0'*64
    else:doc['body_pages'][0]['source_ref']['blob_sha256']='0'*64;doc['source_refs'][1]=deepcopy(doc['source_refs'][1]);doc['source_refs'][1]['blob_sha256']='f'*64
    capture=dict(source='EASTMONEY_HK',readback_status='VERIFIED',sha256='3'*64,run_id='4'*32,target_trade_date=DAY)
    with pytest.raises(ValueError):mirror_material(doc,capture)


def test_bi01_same_instance_identity_stable_across_capture_time():
    doc=raw_doc();a=project_docs([doc])[0][0]
    doc['available_at']='2026-09-30T08:00:00+08:00'
    b=project_docs([doc])[0][0]
    assert a['event_id']==b['event_id']
    body=raw_doc(text='本公司工业机器人订单增加。');c=project_docs([body])[0][0]
    issuer=raw_doc('HK.05678');d=project_docs([issuer])[0][0]
    assert len({a['event_id'],c['event_id'],d['event_id']})==3


def test_instance_id_propagates_material_and_dom_source_identity():
    docs,_=project_docs([raw_doc(),raw_doc(text='本公司工业机器人设备订单增长20%。')])
    assert len({d['event_id'] for d in docs})==2
    capture=dict(source='EASTMONEY_HK',readback_status='VERIFIED',sha256='3'*64,run_id='4'*32,target_trade_date=DAY)
    for doc in docs:
        material=mirror_material(doc,capture)
        assert material['original_article_id']==doc['event_id']
        cards=project_material_discovery([material],NAMES,IDENTITY,CONTEXT)
        assert cards and all(c['event_id']=='material:'+doc['event_id'] for c in cards)


def test_python_preserves_canonical_lane_labels_and_relation_claims():
    value=make_case('risk_explanation')['workspace']['research_attention']['cards'][0]
    assert value['decision']['why_now_readable']==['公司特异材料','已核美股个股映射','已核美股行业映射']
    assert value['research_relationships']
    assert any('减少' in r['issuer_cautions'][0]['quote'] for r in value['research_relationships'] if r['issuer_cautions'])


@pytest.fixture(scope='session',autouse=True)
def record_imported_source_identity():
    yield
    import sys, hashlib
    rows=[]
    for name,module in sorted(sys.modules.items()):
        file=getattr(module,'__file__',None)
        if not file:continue
        path=Path(file).resolve()
        if path.is_relative_to(APP) and path.is_file():
            rows.append(dict(module=name,path=path.relative_to(APP).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (OUT/'imports.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
