import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const component = await readFile(new URL('../research-panel/related-reports.js', import.meta.url), 'utf8');
const safety = {research_only:true, production_allowed:false, buy_gate_updated:false, orders_sent:false};
const pdfSha = 'b'.repeat(64), docId = 'a'.repeat(64), receiptSha = 'c'.repeat(64);

function makeNode(tag = 'div') {
  let text = '';
  return {
    tagName:tag.toUpperCase(), dataset:{}, hidden:false, open:false, children:[], style:{},
    get childNodes(){ return this.children; },
    get textContent(){ return text + this.children.map(child => child.textContent).join(''); },
    set textContent(value){ text=String(value); this.children=[]; },
    append(...children){ this.children.push(...children); },
    replaceChildren(...children){ text=''; this.children=children; },
  };
}
function harness(fetcher) {
  const nodes = {};
  for (const id of ['relatedReports','relatedReportsState','relatedReportsOutput','relatedReportsRefresh']) nodes[id]=makeNode();
  nodes.relatedReports.dataset={hideEmpty:'true',identityDate:'20261030',generation:'g'};
  const context={document:{getElementById:id=>nodes[id],createElement:makeNode},window:{},fetch:fetcher,
    URLSearchParams,AbortController,setTimeout,clearTimeout,setInterval,clearInterval,Date,console};
  vm.runInNewContext(component,context);
  return {nodes, reader:context.window.RelatedReports};
}
function page({symbol='A.301048', cursor=null, offset=0, candidates=5, attempts=5, reports=[]}={}) {
  return {schema_version:'v4.related_pdf_reports.candidate.v1',status:'PARTIAL',search_mode:'FULLTEXT_INDEX',
    identity_date:'20261030',time_semantics:'CURRENT_KNOWLEDGE_NON_PIT',...safety,
    stocks:[{symbol,identity:{status:'CANNOT_CONFIRM'},reports}],next_cursor:cursor,
    coverage:{gaps:[],candidate_documents:candidates,detail_attempts:attempts,verified_documents:attempts,
      page_offset:offset,pagination_required:cursor!==null,pagination_incomplete:false,
      historical_sources_complete:false,limits:{documents:5}}};
}
function matchedReport() {
  return {relation_status:'TEXT_CANDIDATE_NOT_SUBJECT_CONFIRMED',dedup_status:'VERIFIED_PDF_BYTES',verified_pdf_sha256:pdfSha,
    sources:[{document_id:docId,research_date:'20261027',receipt_sha256:receiptSha,original_filename:'研究原文.pdf',
      pit_status:'NON_PIT_CURRENT_KNOWLEDGE_SUPPLEMENT',text_match_in_source:true,
      evidence:[{role:'BODY_MENTION_CANDIDATE',kind:'CODE',location:'page',page_number:1,text:'301048.SZ'}]}]};
}
function response(value) {return {ok:true,json:async()=>value};}
function find(node, tag) {return node.tagName===tag.toUpperCase() ? node : node.children.map(child=>find(child,tag)).find(Boolean);}

test('exhausted candidates do not hide incomplete archive coverage',async()=>{
  const {nodes,reader}=harness(async()=>response(page()));
  await reader.select('301048.SZ','金鹰重工',true);
  assert.equal(nodes.relatedReports.hidden,false);
  assert.match(nodes.relatedReportsOutput.textContent,/覆盖不完整/);
  assert.match(nodes.relatedReportsState.textContent,/当前游标已结束；覆盖仍以返回范围为准/);
});

test('failed candidate verification is not treated as a complete empty result',async()=>{
  const partial=page();
  partial.coverage.verified_documents=4;
  const {nodes,reader}=harness(async()=>response(partial));
  await reader.select('301048.SZ','金鹰重工',true);
  assert.equal(nodes.relatedReports.hidden,false);
  assert.match(nodes.relatedReportsOutput.textContent,/覆盖不完整/);
});

test('partial empty report page remains visible and continues using the existing cursor',async()=>{
  const first=page({cursor:'next123',candidates:10});
  const second=page({offset:5,candidates:10,reports:[matchedReport()]});
  const urls=[];
  const {nodes,reader}=harness(async url=>{urls.push(url);return response(urls.length===1?first:second);});
  await reader.select('301048.SZ','金鹰重工',true);
  assert.equal(urls.length,1);
  assert.match(urls[0],/max_documents=5/);
  assert.equal(nodes.relatedReports.hidden,false);
  assert.match(nodes.relatedReportsRefresh.textContent,/继续读取/);
  assert.match(nodes.relatedReportsOutput.textContent,/续页未完成/);
  nodes.relatedReportsRefresh.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(urls.length,2);
  assert.match(urls[1],/cursor=next123/);
  assert.equal(nodes.relatedReports.hidden,false);
  assert.match(nodes.relatedReportsState.textContent,/返回 1 篇匹配/);
});

test('continuation retains earlier matches and cumulative coverage',async()=>{
  const first=page({cursor:'next123',candidates:10,reports:[matchedReport()]});
  first.coverage.unavailable_documents=1506; first.coverage.large_ready_pending=23;
  const report=matchedReport();report.verified_pdf_sha256='e'.repeat(64);
  report.sources[0].document_id='f'.repeat(64);report.sources[0].original_filename='第二篇.pdf';
  const second=page({offset:5,candidates:10,reports:[report]});
  second.coverage.unavailable_documents=1506; second.coverage.large_ready_pending=23;
  let calls=0;
  const {nodes,reader}=harness(async()=>response(++calls===1?first:second));
  await reader.select('301048.SZ','金鹰重工',true);
  nodes.relatedReportsRefresh.onclick();await new Promise(resolve=>setImmediate(resolve));
  assert.match(nodes.relatedReportsState.textContent,/累计已取 10 篇候选，返回 2 篇匹配/);
  assert.match(nodes.relatedReportsOutput.textContent,/研究原文.pdf/);
  assert.match(nodes.relatedReportsOutput.textContent,/第二篇.pdf/);
  assert.match(nodes.relatedReportsOutput.textContent,/不可用 1506/);
  assert.match(nodes.relatedReportsOutput.textContent,/尚未具备可验证检索条件：23/);
});

test('a new validation window preserves prior results with dated snapshot status',async()=>{
  const first=page({cursor:'next123',candidates:10,reports:[matchedReport()]});
  first.coverage.pagination_window_reset=true; first.coverage.search_checkpoint_sha256='d'.repeat(64);
  const report=matchedReport();report.verified_pdf_sha256='e'.repeat(64);
  report.sources[0].document_id='f'.repeat(64);report.sources[0].original_filename='第二窗口.pdf';
  const second=page({offset:5,candidates:10,reports:[report]});
  second.coverage.pagination_window_reset=false; second.coverage.search_checkpoint_sha256='d'.repeat(64);
  let calls=0;
  const {nodes,reader}=harness(async()=>response(++calls===1?first:second));
  await reader.select('301048.SZ','金鹰重工',true);
  assert.match(nodes.relatedReportsRefresh.textContent,/保留旧窗口/);
  nodes.relatedReportsRefresh.onclick();await new Promise(resolve=>setImmediate(resolve));
  assert.match(nodes.relatedReportsOutput.textContent,/第二窗口.pdf/);
  assert.match(nodes.relatedReportsOutput.textContent,/研究原文.pdf/);
  assert.match(nodes.relatedReportsOutput.textContent,/本次窗口切换未重新核验/);
  assert.match(nodes.relatedReportsOutput.textContent,new RegExp('d'.repeat(64)));
});

test('a matched candidate shows non-PIT evidence and reads the existing verified OCR detail',async()=>{
  const urls=[];
  const detail={schema_version:'v4.zsxq_pdf_document_detail.v1',status:'READY',document_id:docId,research_date:'20261027',
    ...safety,receipt:{integrity:'SOURCE_PDF_AND_PAGE_HASHES_VERIFIED',sha256:receiptSha,verified_pdf_sha256:pdfSha},
    pages:[{page_number:1,text:'已校验的报告正文'}]};
  const {nodes,reader}=harness(async url=>{urls.push(url);return response(url.includes('/pdf-documents/')?detail:page({reports:[matchedReport()]}));});
  await reader.select('301048.SZ','金鹰重工',true);
  assert.equal(nodes.relatedReports.hidden,false);
  assert.match(nodes.relatedReportsOutput.textContent,/当前知识补充，非历史 PIT/);
  assert.match(nodes.relatedReportsOutput.textContent,/文字提及不是已认证主体/);
  assert.match(nodes.relatedReportsOutput.textContent,/正文提及/);
  assert.match(nodes.relatedReportsOutput.textContent,/20261027/);
  assert.match(nodes.relatedReportsOutput.textContent,new RegExp(pdfSha));
  await find(nodes.relatedReportsOutput,'button').onclick();
  assert.match(urls[1],new RegExp('/pdf-documents/'+docId+'\\?research_date=20261027'));
  assert.match(nodes.relatedReportsOutput.textContent,/已校验的报告正文/);
});

test('a mismatched receipt hash is rejected before displaying OCR text',async()=>{
  const detail={schema_version:'v4.zsxq_pdf_document_detail.v1',status:'READY',document_id:docId,research_date:'20261027',
    ...safety,receipt:{integrity:'SOURCE_PDF_AND_PAGE_HASHES_VERIFIED',sha256:'d'.repeat(64),verified_pdf_sha256:pdfSha},
    pages:[{page_number:1,text:'不可显示的报告正文'}]};
  const {nodes,reader}=harness(async url=>response(url.includes('/pdf-documents/')?detail:page({reports:[matchedReport()]})));
  await reader.select('301048.SZ','金鹰重工',true);
  await find(nodes.relatedReportsOutput,'button').onclick();
  assert.match(nodes.relatedReportsOutput.textContent,/正文版本已变化或摘要缺失/);
  assert.doesNotMatch(nodes.relatedReportsOutput.textContent,/不可显示的报告正文/);
});

test('a late response for a previous stock cannot replace the current stock',async()=>{
  let resolveFirst;
  const pending=new Promise(resolve=>{resolveFirst=resolve;});
  let calls=0;
  const {nodes,reader}=harness(async()=>++calls===1?pending:response(page({symbol:'A.002865',cursor:'next456',candidates:10})));
  const first=reader.select('301048.SZ','金鹰重工',true);
  await reader.select('002865.SZ','钧达股份',true);
  resolveFirst(response(page({reports:[matchedReport()]})));
  await first;
  assert.match(nodes.relatedReportsState.textContent,/002865\.SZ/);
  assert.doesNotMatch(nodes.relatedReportsOutput.textContent,/301048|研究原文/);
  assert.match(nodes.relatedReportsOutput.textContent,/续页未完成/);
});

test('switching stock aborts the pending report request and leaves the new stock responsive',async()=>{
  let aborted=false,calls=0;
  const {nodes,reader}=harness((url,options)=>{
    if (++calls===1) return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{
      aborted=true;reject(new Error('aborted'));
    },{once:true}));
    return Promise.resolve(response(page({symbol:'A.002865',reports:[matchedReport()]})));
  });
  const first=reader.select('301048.SZ','金鹰重工',true);
  await reader.select('002865.SZ','钧达股份',true);
  await first;
  assert.equal(aborted,true);
  assert.match(nodes.relatedReportsState.textContent,/002865\.SZ/);
  assert.match(nodes.relatedReportsOutput.textContent,/研究原文/);
});

test('a response with a mismatched stock identity is not displayed',async()=>{
  const {nodes,reader}=harness(async()=>response(page({symbol:'A.002865',reports:[matchedReport()]})));
  await reader.select('301048.SZ','金鹰重工',true);
  assert.match(nodes.relatedReportsState.textContent,/身份、覆盖或研究安全合同不匹配/);
  assert.equal(nodes.relatedReports.hidden,false);
  assert.equal(nodes.relatedReports.open,true);
  assert.match(nodes.relatedReportsRefresh.textContent,/重新读取/);
  assert.equal(nodes.relatedReportsOutput.children.length,0);
});

test('failed stock switch shows a retryable error and does not retain the previous report',async()=>{
  let failNext, calls=0;
  const pending=new Promise((_,reject)=>{failNext=reject;});
  const urls=[];
  const {nodes,reader}=harness(async url=>{
    urls.push(url);calls++;
    if(calls===1)return response(page({reports:[matchedReport()]}));
    if(calls===2)return pending;
    return response(page({symbol:'A.002865',cursor:'next456',candidates:10}));
  });
  await reader.select('301048.SZ','金鹰重工',true);
  assert.match(nodes.relatedReportsOutput.textContent,/研究原文/);
  const switched=reader.select('002865.SZ','钧达股份',true);
  failNext(new Error('网络中断'));
  await switched;
  assert.equal(nodes.relatedReports.hidden,false);
  assert.equal(nodes.relatedReports.open,true);
  assert.match(nodes.relatedReportsState.textContent,/002865\.SZ.*网络中断.*不能据此判断没有研报/);
  assert.match(nodes.relatedReportsRefresh.textContent,/重新读取/);
  assert.equal(nodes.relatedReportsOutput.children.length,0);
  nodes.relatedReportsRefresh.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls,3);
  assert.match(urls[2],/symbols=002865\.SZ/);
  assert.doesNotMatch(urls[2],/cursor=/);
  assert.match(nodes.relatedReportsState.textContent,/002865\.SZ.*仍有续页/);
  assert.doesNotMatch(nodes.relatedReportsOutput.textContent,/研究原文/);
});

test('render failure after receiving a cursor retries the first page',async()=>{
  const badReport=matchedReport();
  badReport.sources[0].evidence=[null];
  const urls=[];
  const {nodes,reader}=harness(async url=>{
    urls.push(url);
    return response(urls.length===1?page({cursor:'next123',candidates:10,reports:[badReport]}):page());
  });
  await reader.select('301048.SZ','金鹰重工',true);
  assert.equal(nodes.relatedReports.hidden,false);
  assert.equal(nodes.relatedReports.open,true);
  assert.match(nodes.relatedReportsState.textContent,/读取失败/);
  assert.equal(nodes.relatedReportsOutput.children.length,0);
  nodes.relatedReportsRefresh.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(urls.length,2);
  assert.doesNotMatch(urls[1],/cursor=/);
  assert.equal(nodes.relatedReports.hidden,false);
  assert.match(nodes.relatedReportsOutput.textContent,/覆盖不完整/);
});

test('invalid input exposes an actionable diagnostic without making a request',async()=>{
  for (const [day,symbol,message] of [['invalid','301048.SZ',/名单身份日期缺失或无效/],['20261030','bad',/股票代码无效/]]) {
    let calls=0;
    const {nodes,reader}=harness(async()=>{calls++;throw new Error('unexpected request');});
    nodes.relatedReports.dataset.identityDate=day;
    await reader.select(symbol,'金鹰重工',true);
    assert.equal(calls,0);
    assert.equal(nodes.relatedReports.hidden,false);
    assert.equal(nodes.relatedReports.open,true);
    assert.match(nodes.relatedReportsState.textContent,message);
    assert.match(nodes.relatedReportsRefresh.textContent,/重新读取/);
    assert.equal(nodes.relatedReportsOutput.children.length,0);
  }
});
