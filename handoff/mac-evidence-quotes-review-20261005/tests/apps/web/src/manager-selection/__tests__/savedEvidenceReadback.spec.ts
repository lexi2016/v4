// @vitest-environment jsdom
import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {it,expect} from 'vitest';
import {validateManagerWorkspace} from '../../api/managerWorkspace';
import {renderResearchAttention} from '../researchAttention';
it('reads exact saved COMPANY_MATERIAL excerpts without changing the stored workspace',()=>{
  const bytes=readFileSync(process.env.V4_REVIEW_SAMPLE_PATH!);
  const raw=JSON.parse(bytes.toString('utf8')), original=JSON.stringify(raw);
  const checked=validateManagerWorkspace(raw,raw.target_trade_date);
  const host=document.createElement('section');
  renderResearchAttention(host,checked.research_attention,checked.us_market_attention,checked.selection_diagnostics);
  const attention=checked.research_attention!;
  const configured=Number(attention.config.display_limit);
  const limit=Number.isSafeInteger(configured)&&configured>0&&configured<=100?configured:30;
  const articles=host.querySelectorAll('.research-attention-card');
  const readbacks:Array<Record<string,unknown>>=[];
  attention.cards.slice(0,limit).forEach((card:any,i:number)=>{
    const details=Array.from(articles[i].children).filter(n=>n.tagName==='DETAILS'&&n.querySelector('summary')?.textContent?.startsWith('COMPANY_MATERIAL'));
    const evidence=card.evidence.slice(0,6).filter((e:any)=>e.evidence_lane==='COMPANY_MATERIAL');
    expect(details).toHaveLength(evidence.length);
    evidence.forEach((row:any,j:number)=>{
      if(typeof row.evidence_quote!=='string'||!row.evidence_quote.trim())return;
      const detail=details[j] as HTMLDetailsElement;detail.open=true;
      expect(detail.querySelector('blockquote')?.textContent===row.evidence_quote).toBe(true);
      expect(detail.textContent?.includes(row.title)).toBe(true);
      expect(detail.textContent?.includes('不据此确认事件发生在本次窗口')).toBe(true);
      readbacks.push({card_index:i,evidence_index:j,quote_length:row.evidence_quote.length,
        quote_sha256:createHash('sha256').update(row.evidence_quote).digest('hex'),exact_dom_match:true,title_present:true,details_open:true});
    });
  });
  expect(readbacks.length).toBeGreaterThan(0);expect(JSON.stringify(raw)===original).toBe(true);
  writeFileSync(process.env.V4_REVIEW_RESULT_PATH!,JSON.stringify({status:'SAVED_SAMPLE_JSDOM_READBACK_PASS',
    source_sha256:createHash('sha256').update(bytes).digest('hex'),target_trade_date:raw.target_trade_date,
    displayed_cards:articles.length,verified_excerpts:readbacks.length,readbacks,input_unchanged:true,
    live_api:'NOT_RUN',browser_visual:'NOT_RUN',classification_acceptance:'NOT_CLAIMED'},null,2));
});
