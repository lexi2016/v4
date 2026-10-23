"""Offline exact-evidence identity integration. No data producer or market client."""
from __future__ import annotations
import argparse,csv,hashlib,html,io,json,re,sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
sys.dont_write_bytecode=True
HEADER=re.compile(r'(?m)^([^\n]*)\((https://[^\s)]+)\)\n\ue200cite\ue202([^\ue201]+)\ue201')
NULL='null'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def clean(x):return ' '.join(html.unescape(re.sub(r'<[^>]*>',' ',x)).split())
def resources(path):
    text=load(path)
    if not isinstance(text,str):raise ValueError('CAPTURE_NOT_TEXT:'+str(path))
    hs=list(HEADER.finditer(text));out={}
    for i,m in enumerate(hs):
        raw=text[m.start():hs[i+1].start() if i+1<len(hs) else len(text)]
        out[m.group(3)]=dict(url=m.group(2),text=clean(raw),raw=raw,title=m.group(1).strip())
    return out

def official(url):
    h=urlparse(url).hostname or ''
    return any(h==x or h.endswith('.'+x) for x in ['sse.com.cn','szse.cn','bse.cn','neeq.com.cn','csindex.com.cn','cnindex.com.cn'])

def write_new(path,data):
    p=Path(path)
    if p.exists():raise RuntimeError('OUTPUT_EXISTS_NO_OVERWRITE:'+str(p))
    p.write_bytes(data)

def main(contract_path,config_path,output_override=None):
    c=load(contract_path);cfg=load(config_path);idx=load(c['input_index_path'])
    # Every read is bound before interpretation; no original file may change.
    for p,h in idx['files'].items():assert sha(p)==h,'FROZEN_INPUT_DRIFT:'+p
    assert sha(config_path)==c['execution_source_binding']['config_sha256'],'CONFIG_DRIFT'
    assert sha(__file__)==c['execution_source_binding']['source_sha256'],'CODE_DRIFT'
    before={p:sha(p) for p in idx['files']}
    bp=Path(cfg['baseline_csv']);assert sha(bp)==cfg['baseline_sha256']
    with bp.open(encoding='utf-8-sig',newline='') as f:baseline=list(csv.DictReader(f))
    assert len(baseline)==318 and len({r['ts_code'] for r in baseline})==318
    old={r['ts_code']:r for r in baseline}
    confirmed={k for k,r in old.items() if r['identity_classification_cn']!='身份待确认'}
    assert len(confirmed)==229
    proofs={};cache={};proof_errors=[]
    for item in cfg['entries']:
        key=item['ts_code'];code,market=key.split('.')
        assert key in old and key not in confirmed,'ENTRY_NOT_UNKNOWN:'+key
        assert item['source_path'] in idx['files'] and idx['files'][item['source_path']]==item['source_sha256']
        if item['source_path'] not in cache:cache[item['source_path']]=resources(item['source_path'])
        block=cache[item['source_path']][item['resource_ref']]
        assert block['url']==item['source_url'] and official(block['url']),'NONOFFICIAL_OR_RESOURCE_DRIFT'
        assert all(t in block['text'] for t in item['proof_fragments']),'EXACT_PROOF_FRAGMENT_MISSING:'+key
        assert any(re.search(r'(?<!\d)'+re.escape(code)+r'(?!\d)',t) for t in item['proof_fragments']),'NO_EXACT_CODE_PROOF:'+key
        assert item['instrument_type'] in ('EQUITY','BOND','INDEX')
        if key in proofs:assert proofs[key]['instrument_type']==item['instrument_type'],'TYPE_CONFLICT:'+key
        proofs.setdefault(key,item)
    # Current official STAR list is an equity code column, not an as-of-D22 roster.
    star=cfg['star_source'];assert star['path'] in idx['files'] and idx['files'][star['path']]==star['sha256']
    raw=Path(star['path']).read_text();m=re.search(r'\((\{.*\})\)\s*;?\s*$',raw,re.S)
    assert m,'STAR_JSONP_SCHEMA';records=json.loads(m.group(1))['result'];assert len(records)==star['expected_resource_rows']
    seen=set()
    for i,record in enumerate(records):
        code=str(record.get(star['code_field']) or '').strip()
        if not re.fullmatch(r'\d{6}',code):continue
        assert code not in seen,'STAR_DUPLICATE_CODE';seen.add(code);key=code+'.SH'
        if key not in old or key in confirmed:continue
        evidence=dict(ts_code=key,instrument_type='EQUITY',source_path=star['path'],source_sha256=star['sha256'],source_url='https://query.sse.com.cn/sseQuery/commonQuery.do',resource_ref=f'result[{i}]/{star["code_field"]}',proof_fragments=[code],evidence_kind='OFFICIAL_CURRENT_STAR_EQUITY_CODE_COLUMN',scope=star['scope'],source_date='2026-10-23',source_date_null_reason='',source_observation=star['http_date'])
        if key in proofs:assert proofs[key]['instrument_type']=='EQUITY','STAR_TYPE_CONFLICT'
        proofs.setdefault(key,evidence)
    changes=[];rows=[]
    for prior in baseline:
        row=dict(prior);key=row['ts_code'];ev=proofs.get(key);inherited=key in confirmed
        row.update(integration_origin='INHERITED_ACCEPTED_229_UNCHANGED' if inherited else 'UNKNOWN_RETAINED',type_evidence_scope='INHERITED_OFFICIAL_TYPE_ONLY' if inherited else 'CANNOT_CONFIRM',source_evidence_json='[]',observed_alias_old_code='null',observed_alias_new_code='null',observed_alias_null_reason='No newly bound pair row; inherited pair evidence remains in original fields',source_date='null',source_date_null_reason='No authenticated new source date for inherited/unknown row',available_asof='null',available_asof_null_reason='No source-system availability proof as of D22',effective_from='null',effective_to='null',effective_from_null_reason='No per-key effective interval authenticated',effective_to_null_reason='No per-key effective interval authenticated')
        if ev:
            typ=ev['instrument_type'];row.update(identity_classification_cn={'EQUITY':'确认股票','BOND':'非股票（债券）','INDEX':'非股票（指数）'}[typ],source_identity_subtype_cn='官方精确代码/类型证据增量；有效期及D22可用性未认证',identity_evidence_status='EXACT_OFFICIAL_TYPE_EVIDENCE_NOT_D22_GATE',source_security_type={'EQUITY':'股票','BOND':'债券','INDEX':'指数'}[typ],source_security_type_null_reason='',source_code_match_status='EXACT_MARKET_AND_CODE_MATCH',source_record_ref=ev['resource_ref']+'; '+' | '.join(ev['proof_fragments']),source_record_ref_null_reason='',evidence_source_id=ev['evidence_kind'],evidence_source_id_null_reason='',evidence_path=ev['source_path'],evidence_path_null_reason='',evidence_sha256=ev['source_sha256'],evidence_sha256_null_reason='',integration_origin='NEW_EXACT_OFFICIAL_EVIDENCE',type_evidence_scope=ev['scope'],source_evidence_json=json.dumps(ev,ensure_ascii=False,sort_keys=True),source_date=ev.get('source_date') or NULL,source_date_null_reason=ev.get('source_date_null_reason') or ('No authenticated publication date in capture' if not ev.get('source_date') else ''),disposition='NO_UPDATE_NON_EQUITY' if typ in ('BOND','INDEX') else 'IDENTITY_CANNOT_CONFIRM',disposition_reason='Exact official non-equity type evidence: preserve original record, do not request equity bars; D22 activity/availability not inferred' if typ in ('BOND','INDEX') else 'Stock identity is positively evidenced, including historical stocks; D22 effective alias/activity/availability remains unproven',review_note='Only identity/type integrated; no issuer substitution, prefix/arithmetic code mapping, market-data update or D22 gate certification')
            if ev.get('observed_old_code'):
                row.update(observed_alias_old_code=ev['observed_old_code'],observed_alias_new_code=ev['observed_new_code'],observed_alias_null_reason='')
            changes.append(dict(ts_code=key,old_type=prior['identity_classification_cn'],new_type=row['identity_classification_cn'],source_path=ev['source_path'],source_sha256=ev['source_sha256'],source_ref=ev['resource_ref']))
        row['instrument_type']={'确认股票':'EQUITY','非股票（债券）':'BOND','非股票（指数）':'INDEX','身份待确认':'UNKNOWN'}[row['identity_classification_cn']]
        # All inherited columns stay byte-value identical for accepted229.
        if inherited:assert all(row[k]==v for k,v in prior.items()),'INHERITED_ROW_MUTATED:'+key
        # No source-type inference upgrades original D22/TDX route fields.
        for k in ['d22_identity_status','d22_activity_status','data_available_asof_d22','canonical_code_asof_d22','alias_effective_date_asof_d22','tdx_market_binding_status','instrument_id']:
            assert row[k]==prior[k],'D22_OR_ROUTE_UPGRADE:'+key
        rows.append(row)
    count=dict(Counter(r['instrument_type'] for r in rows));dispositions=dict(Counter(r['disposition'] for r in rows))
    unknown=[r['ts_code'] for r in rows if r['instrument_type']=='UNKNOWN']
    # Expectations only diagnose completeness; never create a classification.
    expected=cfg['expected_final_counts_for_reconciliation_only'];complete=count==expected
    assert sum(count.values())==318 and len({r['ts_code'] for r in rows})==318
    assert {p:sha(p) for p in idx['files']}==before,'ORIGINAL_INPUT_MUTATED'
    out=Path(output_override or c['output_directory']);out.mkdir(parents=True,exist_ok=True)
    b=io.StringIO(newline='');writer=csv.DictWriter(b,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
    write_new(out/'INSTRUMENT_IDENTITY_318.csv',('\ufeff'+b.getvalue()).encode())
    summary=dict(status='READY_FOR_REVIEW' if complete else 'CANNOT_CONFIRM_EXPECTED_EVIDENCE_COVERAGE',execution_id=c['execution_id'],rows=len(rows),inherited_accepted_rows=229,inherited_original_columns_unchanged=True,new_positive_evidence_rows=len(changes),instrument_type_counts=count,disposition_counts=dispositions,unknown_keys=unknown,non_equity_no_update_keys=[r['ts_code'] for r in rows if r['disposition']=='NO_UPDATE_NON_EQUITY'],D22_unresolved_count=sum(r['disposition']=='IDENTITY_CANNOT_CONFIRM' for r in rows),D22_activity_or_availability_authenticated=0,tdx_market_verified=0,source_mutations=0,market_data_requests=0,daily_bars_recovered=0,full05_status='HOLD_CONTRACT_ONLY_NOT_COUNTED',interpretation='Identity type may be historical or current as explicitly scoped; neither current activity nor code canonicality as of D22 is inferred',source_path=str(Path(__file__).resolve()),source_sha256=sha(__file__),config_sha256=sha(config_path),input_index_sha256=sha(c['input_index_path']),research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    for name,data in [('IDENTITY_AUDIT_SUMMARY.json',summary),('CHANGE_LEDGER.json',changes)]:write_new(out/name,(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
    receipt=dict(status=summary['status'],contract_path=str(Path(contract_path).resolve()),contract_sha256=sha(contract_path),output_artifacts={p.name:sha(p) for p in out.iterdir() if p.name in ['INSTRUMENT_IDENTITY_318.csv','IDENTITY_AUDIT_SUMMARY.json','CHANGE_LEDGER.json']},independent_review='PENDING',scope='OFFICIAL_INSTRUMENT_IDENTITY_INTEGRATION_ONLY',source_code_sha256=sha(__file__),config_sha256=sha(config_path),read_only_inputs_unchanged=True,full_pool_run=False,network_calls=0,daily_bars_recovered=0,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    write_new(out/'WRITER_RECEIPT.json',(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode());print(json.dumps(summary,ensure_ascii=False))
    return 0 if complete else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--contract',required=True);p.add_argument('--config',required=True);p.add_argument('--output-directory');a=p.parse_args()
    # Stdlib audit hook blocks provider/SQL/process execution in this derivation.
    def deny(event,args):
        if event.startswith(('socket.','sqlite3.connect','subprocess.Popen')):raise RuntimeError('OFFLINE_ONLY')
    sys.addaudithook(deny);raise SystemExit(main(a.contract,a.config,a.output_directory))
