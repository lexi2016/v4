import type { JsonObject, ResearchAttention, ResearchSelectionLedger, SelectionDiagnostics, UsMappingResearch, UsMarketAttention } from '../api/managerWorkspace.js';
import { researchExecutionLabel } from './dailyResearchRun.js';

const text=(value:unknown,fallback='未知')=>typeof value==='string'&&value.trim()?value:fallback;
const dateLabel=(value:unknown)=>typeof value==='string'&&/^\d{8}$/.test(value)?`${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6,8)}`:text(value);
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

function renderGaps(host:HTMLElement, label:string, gaps: string[] | undefined):void {
  const box=el('details');box.append(el('summary',`${label}（${gaps===undefined?'未提供':gaps.length+' 条'}）`));
  if(gaps===undefined)box.append(el('p','缺口未提供，覆盖仍未知。'));
  else if(!gaps.length)box.append(el('p','此字段未返回额外缺口；不代表全市场覆盖完整。'));
  else for(const reason of gaps)box.append(el('p',reason));
  host.append(box);
}
function renderFormalSelection(host:HTMLElement, diagnostics?:SelectionDiagnostics):void {
  const box=el('section');box.dataset.formalSelection='';box.setAttribute('aria-label','正式港股通选股状态');
  const f=diagnostics?.formal_selection;
  if(!f){box.append(el('h4','正式选股状态未提供 · CANNOT_CONFIRM'),el('p','旧payload或未读取，不能解释为当日适用或有效零结果。'));}
  else {
    const label=f.status==='NOT_APPLICABLE'?'正式选股当日不适用（港股通休市）':
      f.status==='CANNOT_CONFIRM'?'正式选股状态未确认 · CANNOT_CONFIRM':
      f.status==='READY_EMPTY'?'已核目标日资格，候选 0 条（研究结果，不是 BUY）':`已核目标日资格，候选 ${f.candidate_count} 条（研究结果，不是 BUY）`;
    box.append(el('h4',label),el('p',`目标日 ${f.target_trade_date}；原因 ${f.reason}。休市不表示 Stage 已成功执行。`),
      el('p',`港股证券 ${text(f.calendar.hk_securities_state)}；港股通 ${text(f.calendar.hk_connect_state)}；日历身份 ${text(f.calendar.calendar_sha256)}。`),
      el('p',`目标日资格状态 ${f.membership_status}，与是否开市分开判断；不以 D-1 资格替代。`));
    const membership=object(diagnostics?.membership);
    renderGaps(box,'目标日资格缺口',membership.gaps as string[] | undefined);
    renderGaps(box,'正式选股来源缺口',diagnostics?.gaps);
  }
  host.append(box);
}
function renderResearchSelectionLedger(host:HTMLElement, ledger?:ResearchSelectionLedger):void{
  const box=el('section');box.dataset.researchSelectionLedger='';
  const dateMatch=ledger?.target_trade_date.match(/^\d{4}(\d{2})(\d{2})$/);
  const dateLabel=dateMatch?`${Number(dateMatch[1])}/${Number(dateMatch[2])}`:'';
  box.setAttribute('aria-label',dateLabel?`${dateLabel}研究候选与筛选理由`:'研究候选与筛选理由');
  box.append(el('h4',dateLabel?`${dateLabel}研究候选`:'研究候选'));
  if(!ledger){
    box.append(el('p','逐股研究选择台账未提供 · CANNOT_CONFIRM；不能解释为0只候选。Connect正式资格与研究观察分开。'));
    host.append(box);return;
  }
  const c=ledger.coverage as JsonObject;
  const n=(raw:unknown)=>typeof raw==='number'&&Number.isSafeInteger(raw)&&raw>=0?String(raw):'未知';
  box.append(el('p',`状态 ${ledger.status}；目标日 ${ledger.target_trade_date}；筛选来源交易日 ${text(ledger.source_date,'未知')}；事后研究投影，不代表目标日当时可见或可交易。`),
    el('p',`唯一台账 ${n(c.unique_decision_count)} 条／输入 ${n(c.input_row_count)} 行：研究入选 ${n(c.selected_count)}，近条件观察 ${n(c.near_watch_count)}，明确排除 ${n(c.excluded_count)}，未决 ${n(c.unresolved_count)}。`),
    el('p',`原筛选身份 ${text(ledger.source_input_identity)}；决策身份 ${text(ledger.decision_identity)}。来源交易日的Connect字段不代表目标日资格；正式资格仍按上方独立状态显示。`));
  if(c.input_row_count===null){
    box.append(el('p','筛选输入未提供；各项数量未知，不能解释为零条结果。'));
    host.append(box);return;
  }
  const sections:[string,string][]=[['SELECTED','研究入选'],['NEAR_WATCH','近条件观察'],['EXCLUDED','原筛选明确排除'],['UNRESOLVED','未决']];
  for(const [status,label] of sections){
    const rows=ledger.decisions.filter(row=>row.decision_status===status);
    const group=el('details');group.dataset.selectionGroup=status;
    if(status==='SELECTED')group.open=true;
    group.append(el('summary',`${label}（${rows.length}）`));
    for(const row of rows){
      const article=el('article','','research-selection-decision');article.dataset.symbol=row.symbol||'';article.dataset.decision=row.decision_status;
      article.append(el('h5',`${text(row.name)} · ${text(row.symbol,'代码未确认')} · ${row.decision_status}`),
        el('p',`${text(row.decision_reason_code)}：${text(row.decision_reason)}`));
      const m=row.source_metrics as JsonObject;
      if(row.decision_status==='SELECTED'||row.decision_status==='NEAR_WATCH'||row.decision_status==='EXCLUDED'){
        article.append(el('p',`收盘 ${text(m.close===undefined?undefined:String(m.close))}；60日高点80%门槛 ${text(m.oversold_cutoff_80pct_prior60_high===undefined?undefined:String(m.oversold_cutoff_80pct_prior60_high))}；前5日量比 ${text(m.volume_ratio_5d===undefined?undefined:String(m.volume_ratio_5d))}（准入门槛 ≥1.5）。`));
      }
      if(row.decision_status==='NEAR_WATCH')
        article.append(el('p',`未通过门：${text(m.near_failed_gate)}；实值 ${text(m.near_failed_value===undefined?undefined:String(m.near_failed_value))}；原门槛 ${text(m.near_gate_value===undefined?undefined:String(m.near_gate_value))}。此项仍是near观察，不算strict入选。`));
      if(row.decision_status==='UNRESOLVED'&&m.history_unknown_reasons)
        article.append(el('p',`历史缺口：${text(m.history_unknown_reasons)}`));
      const priority=row.research_priority as JsonObject|null;
      if(priority){
        const d=object(priority.decision);
        article.append(el('p',`既有研究优先级第 ${String(priority.priority_rank)} 位 · ${text(d.group_label)} · proposal ${String(priority.research_attention_score)}分（仅研究排序，不是收益分或BUY分）。`));
      }else if(row.decision_status==='UNRESOLVED')article.append(el('p','未分配研究优先级；避免对来源或时点不确定的行造排序。'));
      article.append(el('p',`目标日 ${row.target_trade_date}；来源交易日 ${text(row.source_date)}；规则 ${text(row.source_rule_version)}。来源日成员信息只描述来源日，不代替目标日Connect资格。`));
      const refs=el('details');refs.append(el('summary',`原owner来源引用（${row.source_refs.length}）`));
      if(row.source_refs.length){const raw=el('pre',JSON.stringify(row.source_refs,null,2));raw.style.whiteSpace='pre-wrap';raw.style.overflowWrap='anywhere';refs.append(raw);}
      else refs.append(el('p','来源引用缺失；该行保持未决。'));
      article.append(refs);group.append(article);
    }
    box.append(group);
  }
  if(ledger.gaps.length){
    const gaps=el('details');gaps.append(el('summary',`台账缺口（${ledger.gaps.length}）`));
    for(const gap of ledger.gaps)gaps.append(el('p',gap));box.append(gaps);
  }
  host.append(box);
}

function usMoveLabel(row:JsonObject):string{
  const moves=Array.isArray(row.us_moves)?row.us_moves.filter(value=>value&&typeof value==='object') as JsonObject[]:[];
  if(!moves.length&&typeof row.us_symbol==='string'){
    const pct=typeof row.change_pct==='number'&&Number.isFinite(row.change_pct)?`${row.change_pct>0?'+':''}${row.change_pct}%`:'涨幅未知';
    return `${row.us_symbol} ${pct}`;
  }
  if(!moves.length)return text(row.theme_label,'未指定单只美股驱动或涨幅');
  return moves.map(move=>{
    const pct=typeof move.change_pct==='number'&&Number.isFinite(move.change_pct)?`${move.change_pct>0?'+':''}${move.change_pct}%`:'涨幅未知';
    return `${text(move.symbol)} ${pct}`;
  }).join('；');
}
function renderMappingSources(host:HTMLElement, sources:unknown):void{
  if(!Array.isArray(sources))return;
  for(const raw of sources){
    const source=object(raw);const link=sourceLink(source.url);
    if(link){link.textContent=`${text(source.title,'官方来源')}（${text(source.published_at,'日期未提供')}）`;host.append(link);}
  }
}
function renderMappingRows(host:HTMLElement, rows:JsonObject[], label:string):void{
  const table=el('table');table.className='us-mapping-table';table.setAttribute('aria-label',label);
  const head=el('thead'),header=el('tr');
  for(const name of ['研究优先级','美股线索','港股代码及名称','关系类别','理由与产品阶段','目标日资格','官方来源'])header.append(el('th',name));
  head.append(header);table.append(head);const body=el('tbody');
  for(const row of rows){
    const tr=el('tr');
    const priority=row.research_priority==='PRIORITY'?'PRIORITY · 优先核验':row.research_priority==='WATCH'?'WATCH · 观察':'CANNOT_CONFIRM · 未标记';
    const tier=el('td',priority);
    const us=el('td',usMoveLabel(row));
    const code=typeof row.hk_code==='string'?row.hk_code:typeof row.hk_symbol==='string'?row.hk_symbol.match(/^HK\.(\d{5})$/)?.[1]:undefined;
    const hk=el('td',`${text(code)} ${text(row.hk_name)}`);
    const relation=el('td',text(row.relationship_type));
    const maturity=el('td');maturity.append(el('p',text(row.reason)),el('p',text(row.maturity)));
    const limitations=Array.isArray(row.limitations)?row.limitations.filter(v=>typeof v==='string') as string[]:[];
    if(limitations.length)maturity.append(el('p',limitations.join('；')));
    const eligibility=el('td',`CANNOT_CONFIRM · ${text(row.target_date_eligibility,'资格未知')}`);
    const evidence=el('td');renderMappingSources(evidence,row.official_sources);
    for(const cell of [tier,us,hk,relation,maturity,eligibility,evidence])tr.append(cell);
    body.append(tr);
  }
  table.append(body);const wrapper=el('div');wrapper.className='us-mapping-table-wrap';wrapper.append(table);host.append(wrapper);
}
function renderUsMappingResearch(host:HTMLElement, mapping?:UsMappingResearch):void{
  const box=el('section');box.className='us-mapping-research';box.dataset.usMappingResearch='';box.setAttribute('aria-label','美股到港股业务关系研究');
  box.append(el('h4','美股 → 港股业务关系研究（只读研究，不是选股或 BUY）'));
  if(!mapping){box.append(el('p','映射数据未提供 · CANNOT_CONFIRM；数量未知，不能解释为零。'));host.append(box);return;}
  const daily=mapping.daily_run;
  const coverage=object(daily.coverage);
  const coverageCount=(raw:unknown)=>typeof raw==='number'&&Number.isSafeInteger(raw)&&raw>=0?String(raw):'未知';
  const readback=object(daily.run_readback);
  const context=daily.execution_context;
  box.append(el('p',`日常关系映射：${daily.status}；目标港股交易日 ${dateLabel(daily.target_trade_date)}；美股来源日 ${dateLabel(daily.us_session_date)}；此映射来源 cutoff ${text(daily.research_cutoff)}。`),
    el('p',`已审阅关系范围 ${coverageCount(coverage.reviewed_us_symbol_count)} 个；配置美股范围 ${coverageCount(coverage.configured_us_universe_count)} 只；可用美股范围 ${coverageCount(coverage.available_us_universe_count)} 只；匹配关系 ${coverageCount(coverage.matched_hk_relation_count)} 条 / 美股 ${coverageCount(coverage.matched_us_symbol_count)} 只。范围不是全市场。`),
    el('p',researchExecutionLabel(context)),
    el('p',`映射 owner 读回 ${text(readback.status,'未提供 · CANNOT_CONFIRM')}；运行 ${text(daily.run_id)}；产物 SHA256 ${text(daily.artifact_sha256)}；回读于 ${text(readback.read_at)}。`));
  if(context)box.append(el('p',`原 owner 执行时间：${text(context.started_at,'开始时点未提供')} 至 ${text(context.finished_at,'结束时点未提供')}；自然运行核验 ${context.natural_run_verified===false?'未核实':'未提供'}。`));
  if(daily.status==='NOT_RUN')box.append(el('p','该目标日尚无日常映射产物；数量未知，不等于没有匹配。'));
  else if(daily.status==='VALID_EMPTY')box.append(el('p',`完整来源已核，当前${coverageCount(coverage.reviewed_us_symbol_count)}个已审阅关系范围匹配为0；这不代表全市场或其他关系为空。`));
  else if(daily.status==='FAILED'||daily.status==='INPUT_MISSING'||daily.status==='CANNOT_CONFIRM')
    box.append(el('p',`来源或回读未闭环，匹配数量未知；${daily.gaps.join('；')||'CANNOT_CONFIRM'}。`));
  else if(daily.status==='PARTIAL')
    box.append(el('p',`输入覆盖不完整，不能把当前行数当作完整匹配数；${daily.gaps.join('；')||'来源部分缺失'}。`));
  else box.append(el('p',`原 owner 报告匹配港股关系 ${coverageCount(coverage.matched_hk_relation_count)} 条、涉及美股 ${coverageCount(coverage.matched_us_symbol_count)} 只。目标日 Connect 资格仍由独立通道确认。`));
  if(daily.matches.length)renderMappingRows(box,daily.matches,'按日美股到港股研究映射');
  const reviewed=mapping.reviewed_research;
  if(reviewed){
    const sub=el('section');sub.dataset.reviewedUsMapping='';
    if(reviewed.status==='REVIEWED_RETROSPECTIVE_RESEARCH'){
      sub.append(el('h4',`${dateLabel(reviewed.target_trade_date)} 已审阅回顾（事后研究；原盘前计划未消费这些关系）`),
        el('p',`港股目标日 ${dateLabel(reviewed.target_trade_date)} / 美股来源时段 ${dateLabel(reviewed.us_session_date)} / 审阅于 ${text(reviewed.reviewed_at)}。报告 SHA256 ${text(object(reviewed.report).sha256)}。原计划 ${text(object(reviewed.source_scope).original_workspace_plan_status)}，美股 owner lineage ${text(object(reviewed.source_scope).original_us_owner_lineage_status)}；固定样本 ${String(object(reviewed.source_scope).requested_us_symbols)} 只，不是全市场。`),
        el('p','这份回顾和原盘前计划失败并列展示；报告中的涨幅不补写成 V4 已验证的历史行情 lineage，也不代表目标日可交易。'));
      renderMappingRows(sub,reviewed.cards,'9月30日已审阅事后研究五项港股映射');
    }else sub.append(el('h4','已审阅回顾不可读取 · CANNOT_CONFIRM'),el('p',Array.isArray(reviewed.gaps)?reviewed.gaps.join('；'):'研究卡片未知。'));
    box.append(sub);
  }
  renderGaps(box,'日常映射缺口',daily.gaps);
  host.append(box);
}

export function renderResearchAttention(host:HTMLElement, attention?:ResearchAttention, us?:UsMarketAttention, selection?:SelectionDiagnostics,
    mapping?:UsMappingResearch):void{
  host.replaceChildren();host.setAttribute('aria-label','证据优先研究');
  host.append(el('h3','证据优先研究（只读，不是原筛选／focus／BUY 排名）'));
  renderUsMappingResearch(host,mapping);
  renderFormalSelection(host,selection);
  renderResearchSelectionLedger(host,attention?.research_selection);
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
  const raw=el('details');raw.append(el('summary','美股原始上涨发现（独立于上述日常关系映射；即使没有合格港股映射也保留）'));
  if(!us){raw.append(el('p','US owner 未绑定/未读取，覆盖未知。'));}
  else{
    raw.append(el('p',`原始US行情通道：${text(us.coverage_scope)}；状态 ${text(us.status)}；US session ${text(us.expected_us_session)}；此通道 cutoff ${text(us.research_cutoff)}；筛选语义 ${text(us.selection_semantics,'未声明')}${recheckLabel}。它与上方目标日关系映射分别保留各自来源日期和时点。`));
    const industries=us.raw_industry_up as JsonObject[]||[];const individuals=us.raw_individual_up as JsonObject[]||[];
    raw.append(el('h4',`行业代理上涨 ${industries.length} 条`));for(const row of industries)raw.append(el('p',`${text(row.label)}：${String(row.pct_change??'')}% · ${text(row.status)}`));
    raw.append(el('h4',`配置内个股上涨 ${individuals.length} 条`));for(const row of individuals)raw.append(el('p',`${text(row.symbol)}：${String(row.change_pct??'')}% · ${text(row.session_date)}`));
  }
  host.append(raw);
}
