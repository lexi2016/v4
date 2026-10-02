import type { JsonObject, ResearchAttention, UsMarketAttention } from '../api/managerWorkspace.js';

const text=(value:unknown,fallback='未知')=>typeof value==='string'&&value.trim()?value:fallback;
const object=(value:unknown):JsonObject=>value&&typeof value==='object'&&!Array.isArray(value)?value as JsonObject:{};
const el=<K extends keyof HTMLElementTagNameMap>(tag:K,content='',className='')=>{const node=document.createElement(tag);node.textContent=content;node.className=className;return node;};

export function acquiredTime(row:JsonObject):string|null{
  for(const key of ['acquired_at','available_at','retrieved_at','first_seen_at','collected_at','archive_recorded_at','captured_at','us_captured_at']){
    const value=row[key];if(typeof value==='string'&&value.trim())return value;
  }
  return null;
}
function sourceLink(raw:unknown):HTMLAnchorElement|null{
  if(typeof raw!=='string')return null;
  try{const u=new URL(raw);if(!['https:','http:'].includes(u.protocol)||u.username||u.password)return null;const a=el('a','来源');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return null;}
}
function evidenceDetails(row:JsonObject):HTMLElement{
  const node=el('details');node.append(el('summary',`${text(row.evidence_lane,text(row.evidence_class,'证据'))} · ${text(row.published_at,text(row.issuer_published_at,'时间未知'))}`));
  const body=el('div');const acquired=acquiredTime(row);body.append(el('p',`公开/证据时间：${text(row.published_at,text(row.issuer_published_at,'UNKNOWN'))}；系统取得：${acquired??'未记录（不以当前时间补写）'}`));
  const link=sourceLink(row.source_url);if(link)body.append(link);
  const us=row.us_mover as JsonObject|undefined;if(us)body.append(el('p',`US：${text(us.label,text(us.symbol))} ${String(us.pct_change??us.change_pct??'')}%；此处只表示已核关系后的研究映射。`));
  node.append(body);return node;
}

function renderRelationships(article:HTMLElement, card:JsonObject):void{
  const relationships=Array.isArray(card.research_relationships)?card.research_relationships:[];
  const evidence=Array.isArray(card.evidence)?card.evidence as JsonObject[]:[];
  for(const raw of relationships){
    const row=object(raw);
    // Display only an explanation attached to a mapping that passed the original
    // card validator. Never promote a standalone relationship label into evidence.
    const bound=evidence.find(e=>{
      const r=object(e.hk_relation),m=object(e.us_mover);
      return e.evidence_lane===row.lane&&r.symbol===card.symbol&&row.symbol===card.symbol&&
        (m.symbol??m.label)===row.us_signal&&r.issuer_quote===row.evidence_quote&&r.direction===row.direction;
    });
    if(!bound)continue;
    const relation=object(bound.hk_relation),section=el('section','','research-relationship');
    section.dataset.researchRelationship=String(row.lane)+':'+String(row.us_signal);
    section.append(el('h5',`美股关系：${text(row.us_signal)}`),
      el('p',`美股关联原文方向：${text(row.direction)}；关联不等于受益或买入。`),
      el('blockquote',text(row.evidence_quote)));
    const mirror=relation.issuer_time_basis==='MIRROR_DISPLAY_TIME_NOT_HKEX_FIRST_PUBLICATION';
    const standing=relation.relation_temporal_role==='STANDING_RELATION_NOT_NEW_CATALYST';
    section.append(el('p',`${mirror?'镜像可见（非HKEX首次发布时间）':'原文发布时间'}：${text(mirror?relation.issuer_mirror_observed_at:row.published_at)}；原关系取得：${text(relation.issuer_available_at)}；双来源最晚取得：${text(row.acquired_at)}。`));
    if(standing){const validity=object(relation.standing_validity);section.append(el('p',`长期关系，不是今天新增催化；源内有效期：${text(validity.valid_from)} 至 ${text(validity.valid_until)}。`));}
    for(const caution of Array.isArray(relation.issuer_cautions)?relation.issuer_cautions:[])
      section.append(el('p',`本公司风险原文（非特定US关系因果）：${text(object(caution).quote)}`));
    section.append(el('p',text(row.observation_condition)),el('p',text(row.invalidation)));
    for(const ref of Array.isArray(relation.source_refs)?relation.source_refs:[]){
      const r=object(ref),link=sourceLink(r.source_url??r.url);if(link)section.append(link);
    }
    article.append(section);
  }
}

export function renderResearchAttention(host:HTMLElement, attention?:ResearchAttention, us?:UsMarketAttention):void{
  host.replaceChildren();host.setAttribute('aria-label','证据优先研究');
  host.append(el('h3','证据优先研究（只读，不是原筛选／focus／BUY 排名）'));
  const recheck=object(us?.historical_source_recheck);
  const wasRechecked=recheck.state==='COMPLETED_READ_ONLY_RECHECK';
  const savedCutoff=text(recheck.research_cutoff,text(us?.research_cutoff));
  const recheckLabel=wasRechecked
    ?`；历史来源已重新核验${text(recheck.checked_at,'')}；保存 cutoff ${savedCutoff}；原计划未消费本次回查，计划/选股判定未改。`
    :'';
  if(!attention){
    host.append(el('p',`研究优先级未读取，优先级未知且不等于0只。下方仅显示已绑定的美股 owner 原始数据；不代表关系映射或选股。${recheckLabel}`));
  }else{
    host.append(el('p',`状态 ${attention.status}；cutoff ${text(attention.research_cutoff)}。评分配置 ${text((attention.config as JsonObject).version)}，状态 ${text((attention.config as JsonObject).status)}。研究排序先按证据状态，再用既有proposal分数和PIT时点打破同组并列；不写回原rank/Stage/BUY。`));
    const configuredLimit=Number((attention.config as JsonObject|undefined)?.display_limit);
    const displayLimit=Number.isSafeInteger(configuredLimit)&&configuredLimit>0&&configuredLimit<=100?configuredLimit:30;
    for(const raw of attention.cards.slice(0,displayLimit)){
      const card=raw as JsonObject;const article=el('article','','research-attention-card');article.dataset.symbol=String(card.symbol||'');
      const decision=(card.decision as JsonObject|undefined)||{};
      article.dataset.decisionState=text(decision.state,'INSUFFICIENT');
      article.append(el('h4',`${text(card.name)} · ${text(card.symbol)} · ${text(decision.group_label,'证据待核')} · ${String(card.research_attention_score)}分`),
        el('p',`原量价分类：${text(card.screen_classification,'不在strict/near')}；原near/strict内部rank：${card.original_screen_rank??'无'}。`),
        el('p',`研究结论：${text(decision.summary,'当前没有可压缩的研究结论。')}`));
      const readable=(decision.why_now_readable as string[]||[]);
      article.append(el('p',`为什么现在看：${readable.join('；')||((card.why_now as string[]||[]).join('；')||'当前没有可计分证据。')}`),
        el('p',`下一步核什么：${text(decision.next_check,'继续核来源、主体、时点和市场确认。')}`),
        el('p',`什么时候降级/撤销：${text(decision.invalidation,'关键证据失效时降级。')}`));
      const components=(card.score_components as JsonObject[]||[]);if(components.length){const details=el('details');details.append(el('summary','查看原分数构成（仅解释，不是BUY分）'),el('p',`${components.map(row=>`${text(row.component)} ${String(row.points)}`).join(' + ')} = ${String(card.research_attention_score)}。`));article.append(details);}
      article.append(el('p',`证据时点：公开 ${text(card.freshest_published_at,'未知')}；系统取得 ${text(card.freshest_acquired_at,'未知')}。两类时间不互相替代。`));
      const missing=(card.missing as string[]||[]);if(missing.length)article.append(el('p',`仍缺：${missing.join('；')}`));
      for(const evidence of (card.evidence as JsonObject[]||[]).slice(0,6))article.append(evidenceDetails(evidence));
      renderRelationships(article,card);
      host.append(article);
    }
  }
  const raw=el('details');raw.append(el('summary','美股原始上涨发现（即使没有合格港股映射也保留）'));
  if(!us){raw.append(el('p','US owner 未绑定/未读取，覆盖未知。'));}
  else{
    raw.append(el('p',`${text(us.coverage_scope)}；状态 ${text(us.status)}；US session ${text(us.expected_us_session)}；筛选语义 ${text(us.selection_semantics,'未声明')}${recheckLabel}。`));
    const industries=us.raw_industry_up as JsonObject[]||[];const individuals=us.raw_individual_up as JsonObject[]||[];
    raw.append(el('h4',`行业代理上涨 ${industries.length} 条`));for(const row of industries)raw.append(el('p',`${text(row.label)}：${String(row.pct_change??'')}% · ${text(row.status)}`));
    raw.append(el('h4',`配置内个股上涨 ${individuals.length} 条`));for(const row of individuals)raw.append(el('p',`${text(row.symbol)}：${String(row.change_pct??'')}% · ${text(row.session_date)}`));
  }
  host.append(raw);
}
