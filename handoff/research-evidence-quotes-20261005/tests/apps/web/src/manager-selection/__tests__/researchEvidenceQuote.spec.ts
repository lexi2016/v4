// @vitest-environment jsdom
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {validateManagerWorkspace} from '../../api/managerWorkspace';
import {renderResearchAttention} from '../researchAttention';
import {mountCatalystObservations} from '../catalystObservationPanel';

// Executes the real Python producer. Only input bodies and the workspace shell
// are synthetic; no API/service/market-data acceptance is claimed.
const appRoot=resolve(process.cwd(),'../..');
const outputs=JSON.parse(execFileSync(process.env.V4_TEST_PYTHON || 'python3',
  [resolve(appRoot,'tests/fixtures/research_evidence_quote_pipeline.py')],{cwd:appRoot,encoding:'utf8'}));
const date='20261002';
const fresh=()=>structuredClone(outputs.current);
const evidence=(x:any)=>x.research_attention.cards[0].evidence[0];
const render=(x:any)=>{
  const checked=validateManagerWorkspace(x,date);const host=document.createElement('section');
  renderResearchAttention(host,checked.research_attention,checked.us_market_attention,checked.selection_diagnostics);
  return host;
};
afterEach(()=>vi.unstubAllGlobals());

describe('synthetic Python body -> research reason -> real DOM',()=>{
  it('preserves and displays the exact producer quote with its source title and clocks',()=>{
    const x=fresh(),before=structuredClone(x),row=evidence(x),host=render(x);
    const card=host.querySelector('.research-attention-card')!;
    expect(card.querySelector('blockquote')?.textContent).toBe(row.evidence_quote);
    expect(card.textContent).toContain(row.title);
    expect(card.textContent).toContain(row.published_at);
    expect(card.textContent).toContain(row.available_at);
    expect(card.textContent).toContain('不据此确认事件发生在本次窗口');
    expect(card.querySelector('a')?.href).toBe(row.source_url);
    expect(x).toEqual(before); // No score, decision, PIT, membership or safety mutation.
    expect(x.research_attention.cards[0].decision.state).toBe('COMPANY_EVIDENCE_WAIT_MARKET');
  });
  it('runs the real panel request decoder and renderer with the Python payload',async()=>{
    const x=fresh(),row=evidence(x);
    const fetcher=vi.fn(async(url:unknown,init?:RequestInit)=>{
      expect(init?.method).toBe('GET');
      return String(url).includes('/workspace?')
        ? new Response(JSON.stringify(x),{status:200,headers:{'content-type':'application/json'}})
        : new Response('{}',{status:503}); // unrelated announcement review remains explicitly unavailable
    });
    vi.stubGlobal('fetch',fetcher);
    const host=document.createElement('main');document.body.append(host);
    const dispose=mountCatalystObservations(host,date);
    try{
      await vi.waitFor(()=>expect(host.querySelector('.research-attention-card blockquote')?.textContent).toBe(row.evidence_quote));
      expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('READY');
      const details=host.querySelector('.research-attention-card blockquote')!.closest('details')!;
      details.open=true;expect(details.open).toBe(true);
      expect(details.textContent).toContain(row.title);
      expect(fetcher).toHaveBeenCalledTimes(2);
    }finally{dispose();host.remove();}
  });
  it.each([undefined,null,'   ',42,{text:'not a quote'}])('does not invent an excerpt from a title or invalid quote %s',quote=>{
    const x=fresh();evidence(x).evidence_quote=quote;
    const card=render(x).querySelector('.research-attention-card')!;
    expect(card.querySelector('blockquote')).toBeNull();
    expect(card.textContent).toContain('未提供可展示正文摘录');
    expect(card.textContent).toContain(evidence(x).title);
  });
  it('renders historical/negative words literally without inventing a current positive event',()=>{
    const x=fresh();const row=evidence(x);row.evidence_quote='合成展示边界：去年签署；本次尚未获批。';
    const before=structuredClone(x),host=render(x);
    expect(host.querySelector('blockquote')?.textContent).toBe(row.evidence_quote);
    expect(host.textContent).toContain('不据此确认事件发生在本次窗口');expect(x).toEqual(before);
  });
  it('escapes both title and quote and still rejects unsafe source links',()=>{
    const x=fresh(),row=evidence(x);row.title='<img src=x onerror=alert(1)>';
    row.evidence_quote='<script>alert(1)</script>';row.source_url='javascript:alert(1)';
    const host=render(x);expect(host.querySelector('img,script,a')).toBeNull();
    expect(host.querySelector('blockquote')?.textContent).toBe(row.evidence_quote);
    expect(host.textContent).toContain(row.title);
  });
  it.each(['after_cutoff','title_only'])('keeps rejected %s synthetic inputs out of research cards',key=>{
    const host=render(structuredClone(outputs[key]));
    expect(host.querySelector('.research-attention-card')).toBeNull();
    expect(host.querySelector('blockquote')).toBeNull();
  });
});
