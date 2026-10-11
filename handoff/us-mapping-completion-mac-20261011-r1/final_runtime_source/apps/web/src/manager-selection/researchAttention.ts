import type { JsonObject, ResearchAttention, ResearchSelectionLedger, UsMappingResearch, UsMarketAttention, SelectionDiagnostics } from '../api/managerWorkspace.js';

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
function renderIndependentObservations(host:HTMLElement, attention?:ResearchAttention):void {
  const box=el('section');box.setAttribute('aria-label','独立公告研究观察');box.dataset.observationOnly='';
  const o=attention?.observation_only;
  if(!o){box.append(el('h4','独立公告观察未提供 · CANNOT_CONFIRM'),el('p','数量未知；不以 scored cards 为空推断没有公告观察。'));}
  else {
    box.append(el('h4',`独立公告观察 ${o.card_count} 条／${o.symbol_count} 股 · ${o.status}`),
      el('p','仅保留原owner的公告研究观察，不进入 scored cards／focus／BUY。来源非穷尽，不能据此断言全市场没有利好。'));
    if(!o.cards.length)box.append(el('p','未保留可展示观察；不等于全市场无正向公告。'));
    // Independent observations are not limited by the existing scored-card display limit.
    for(const row of o.cards){
      const article=el('article','','research-observation-card');article.dataset.symbol=row.symbol;
      const membership=row.target_connect_membership;
      const state=membership.status==='VERIFIED_TARGET_UNIVERSE'?'目标日名单已核（仍仅研究观察）':
        membership.status==='NOT_IN_TARGET_UNIVERSE'?'不在目标日名单（仅研究观察）':'资格未确认 · CANNOT_CONFIRM';
      article.append(el('h4',`${text(row.name)} · ${row.symbol} · 研究观察`),el('p',text(row.title,'公告标题未提供')),
        el('p',`${state}；${text(membership.reason)}。不授予正式选股资格。`),el('blockquote',String(row.support.quote)),
        el('p',`公开时间 ${row.published_at}；retrieved_at ${row.retrieved_at}；available_at ${row.available_at}。只显示原字段，不互相替代。`));
      if(row.research_note)article.append(el('p',text(row.research_note)));
      const proof=el('details');proof.append(el('summary','公告原文与证据身份'),
        el('p',`event_id ${row.event_id}；proposition_id ${text(row.proposition_id)}；document SHA256 ${row.document_sha256}`));
      for(const ref of row.evidence){const link=sourceLink(ref.source_url);if(link)proof.append(link);}
      const raw=el('pre',JSON.stringify(row.evidence,null,2));raw.style.whiteSpace='pre-wrap';raw.style.overflowWrap='anywhere';proof.append(raw);
      article.append(proof);box.append(article);
    }
    renderGaps(box,'独立观察拒绝原因',o.rejections.map(row=>`${text(row.symbol,'未标主体')}：${text(row.reason)}`));
  }
  host.append(box);
}
function renderInputDiagnostics(host:HTMLElement, attention?:ResearchAttention):void {
  const box=el('section');box.dataset.inputDiagnostics='';box.setAttribute('aria-label','研究来源覆盖与缺口');box.append(el('h4','研究来源覆盖与缺口（分来源）'));
  const d=attention?.input_diagnostics;
  if(!d)box.append(el('p','来源诊断未提供 · CANNOT_CONFIRM；覆盖未知，不能将缺字段解释为 READY 或有效零。'));
  else {
    const official=d.official_announcements,c=official.coverage;
    const n=(raw:unknown)=>typeof raw==='number' && Number.isSafeInteger(raw)&&raw>=0?String(raw):'未知';
    box.append(el('h4',`HKEX 官方公告 · ${official.status}`),el('p',`已观察文档 ${n(c.observed_document_count)}；已查询主体 ${n(c.queried_issuer_count)}／来源名单 ${n(c.native_master_count)}。${c.all_official_announcements_captured===true?'原owner声明完整覆盖':'覆盖非穷尽／完整性未确认'}；不表示全部公告均属正向事件。`));
    const coverage=el('details');coverage.append(el('summary','来源覆盖原始字段（不推断未提供项）'));
    const coverageRaw=el('pre',JSON.stringify(c,null,2));coverageRaw.style.whiteSpace='pre-wrap';coverageRaw.style.overflowWrap='anywhere';
    coverage.append(coverageRaw);box.append(coverage);
    renderGaps(box,'HKEX 来源缺口',official.gaps);
    const east=d.eastmoney_selection;
    box.append(el('h4',`东方财富 selection · ${east.status}`),el('p',`范围过滤后的输入文档 ${east.document_count} 条；非穷尽，聚合镜像不是 HKEX 官方目录。不能将旧样本或过窗样本作为当日新利好。`));
    renderGaps(box,'东方财富来源缺口',east.gaps);
    const us=d.us_relations;
    const assessment:Record<string,string>={NOT_EVALUATED:'尚未评估',INSUFFICIENT:'证据不足，数量暂不能确认',ASSESSED_ZERO:'已评估，暂无合格关系',ASSESSED_WITH_RELATIONS:'已有合格关系'};
    box.append(el('h4',`美股关系 · ${us.status} · ${assessment[us.assessment_state]}`),
      el('p',`关系材料完整性 ${us.material_complete?'原owner声明完整':'未确认'}；时间字段定位 ${us.acquisition_field_location}。不以 collected_at／first_seen_at 补造采集时间；发布时间不替代 available_at／retrieved_at，时间合法也仍需独立主体关系证据。`));
    renderGaps(box,'美股来源缺口',us.gaps);
    for(const [name,scope] of Object.entries(d.scope)){
      const s=el('details');s.append(el('summary',`${name==='announcements'?'公告':name==='screen'?'量价':name}研究输入范围 · ${scope.status}`),
        el('p',`目标日 ${scope.target_trade_date}；计数按输入列表，不是去重股票数。`));
      for(const [key,counts] of Object.entries(scope.counts))s.append(el('p',`${key}：输入 ${counts.input}，准入 ${counts.admitted}，拒绝 ${counts.rejected}`));
      for(const [reason,count] of Object.entries(scope.rejection_reasons))s.append(el('p',`${reason}：${count}`));
      renderGaps(s,'范围与资格缺口',scope.gaps);box.append(s);
    }
  }
  renderGaps(box,'研究注意力总体缺口',attention?.gaps);
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
function renderCurrentUsSymbolAssessments(host:HTMLElement, us?:UsMarketAttention):void{
  const box=el('section');box.dataset.currentUsSymbolAssessments='';
  box.append(el('h5','当前工作台行情会话逐代码映射评估'));
  if(!us || !Array.isArray(us.symbol_assessments)){
    box.append(el('p','当前会话逐代码评估未提供 · CANNOT_CONFIRM；数量未知。'));host.append(box);return;
  }
  const identity=object(us.source_identity),evidence=object(us.relation_evidence),coverage=object(us.coverage);
  box.append(el('p',`目标日 ${dateLabel(us.target_trade_date)}；当前 US 行情会话 ${dateLabel(us.expected_us_session)}；cutoff ${text(us.research_cutoff)}；来源 payload SHA256 ${text(identity.payload_sha256)}。报价覆盖 ${String(coverage.assessed_symbol_count??'未知')}/${String(coverage.requested_symbol_count??us.symbol_assessments.length)}；关系证据 ${text(evidence.status,'CANNOT_CONFIRM')}，SHA256 ${text(evidence.artifact_sha256)}；目标日资格仍 CANNOT_CONFIRM。`));
  if(typeof evidence.configured_equity_symbol_count==='number')
    box.append(el('p',`个股关系已链接或有独立缺口评估 ${String(evidence.explicitly_assessed_equity_symbol_count??'未知')}/${String(evidence.configured_equity_symbol_count)}；完整配置覆盖 33 个代码仍未声明，ETF 保持主题代理。`));
  if(evidence.retrospective_relations_present===true)
    box.append(el('p','已收录关系证据晚于目标日；这里只把它与当前工作台 US 会话作回顾性研究对应，不表示目标日当时已知、目标日资格或价格因果。'));
  if(evidence.coverage_complete===false)
    box.append(el('p','当前关系来源没有覆盖全部 33 个代码；无已链接关系的股票数量保持未知，不记为零。'));
  const withheld=Array.isArray(evidence.withheld_candidates)?evidence.withheld_candidates.map(object):[];
  if(withheld.length){
    box.append(el('p',`${withheld.length} 个具名关系候选因身份或来源定位未确认而未计入已链接关系；候选不等于已核实映射。`));
    for(const candidate of withheld){
      box.append(el('p',`${text(candidate.company)} · ${text(candidate.us_symbol)} → 候选 HK.${text(candidate.candidate_hk_code)} · CANNOT_CONFIRM · ${text(candidate.reason)}`));
    }
  }
  const table=el('table');table.className='us-mapping-table';table.setAttribute('aria-label','当前工作台逐美股映射评估');
  const head=el('thead'),hr=el('tr');
  for(const label of ['美股代码与类型','当前会话行情','港股关系与方向','证据与状态'])hr.append(el('th',label));
  head.append(hr);table.append(head);const body=el('tbody');
  for(const row of us.symbol_assessments){
    const tr=el('tr');tr.dataset.usSymbol=String(row.symbol??'');
    const classification=row.instrument_classification==='ETF_PROXY'?'ETF 主题代理（不是发行人）':
      row.instrument_classification==='EQUITY_PROXY'?'个股代理样本':'代理类型未知';
    const symbol=el('td');symbol.append(el('strong',text(row.symbol)),el('p',classification));
    const quote=object(row.quote_evidence);
    const change=typeof quote.change_pct==='number'&&Number.isFinite(quote.change_pct)?`${quote.change_pct>0?'+':''}${quote.change_pct}%`:'涨幅未知';
    const quoteCell=el('td',`${text(row.quote_status)} · ${text(row.direction)} · ${dateLabel(quote.session_date)} ${text(quote.session_time,'时间未知')} · ${change}`);
    const relationCell=el('td');
    const relations=Array.isArray(row.relations)?row.relations.map(object):[];
    if(relations.length){
      for(const relation of relations){
        const direction=relation.relationship_type==='NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER'?'港股客户／集成方 → 美股技术提供方':text(relation.direction);
        const reviewStatus=relation.evidence_review_status==='SOURCE_EVIDENCE_CAPTURED_REVIEW_PENDING'
          ?'来源证据已记录，待人工复核':
          relation.evidence_review_status==='INDEPENDENT_SEMANTIC_REVIEW_PASS_BODY_REHASH_CANNOT_CONFIRM'
            ?'独立语义复核通过；HTTP 正文重哈希未确认':
          relation.evidence_review_status==='RELEASE_PINNED_REVIEWED_RESEARCH'
            ?'按发布登记时间核验的已审研究关系':
          text(relation.evidence_review_status,'来源复核状态未知');
        const sourceLabel=relation.relation_source==='RELEASE_PINNED_REVIEWED_SEED'
          ?'9/30已审种子与发布登记':
          relation.relation_source==='CURRENT_REVIEWED_RELATION_EVIDENCE'
            ?'当前关系证据及独立复核收据':text(relation.relation_source,'来源身份未知');
        const provenance=object(relation.provenance);
        const lineage=[
          provenance.release_id?'release '+text(provenance.release_id):undefined,
          provenance.reviewed_relation_artifact_sha256?'种子 SHA256 '+text(provenance.reviewed_relation_artifact_sha256).slice(0,12)+'…':undefined,
          provenance.evidence_artifact_sha256?'关系工件 SHA256 '+text(provenance.evidence_artifact_sha256).slice(0,12)+'…':undefined,
          relation.review_receipt_sha256?'复核收据 SHA256 '+text(relation.review_receipt_sha256).slice(0,12)+'…':undefined,
          relation.reviewer_identity?'复核人 '+text(relation.reviewer_identity):undefined,
        ].filter((value):value is string=>Boolean(value)).join(' · ');
        const clocks=[
          '证据时序 '+text(relation.evidence_timing),
          '关系可用时间 '+text(relation.available_at,'CANNOT_CONFIRM'),
          relation.source_captured_available_at?'来源捕获 '+text(relation.source_captured_available_at):undefined,
          relation.reviewed_at?'复核时间 '+text(relation.reviewed_at):undefined,
        ].filter((value):value is string=>Boolean(value)).join(' · ');
        relationCell.append(el('p',`${text(relation.hk_code)} ${text(relation.hk_name)} · ${text(relation.relationship_type)} · ${direction}`),
          el('p',`${reviewStatus} · ${text(relation.evidence_timing)} · ${text(relation.maturity)} · target-date eligibility CANNOT_CONFIRM`));
        relationCell.append(el('p',[reviewStatus,sourceLabel,clocks].filter(Boolean).join(' · ')));
        if(lineage)relationCell.append(el('p',lineage));
        const limits=Array.isArray(relation.limitations)?relation.limitations.filter(v=>typeof v==='string').join('；'):'';
        if(limits)relationCell.append(el('p',limits));
        const reviewLimits=Array.isArray(relation.review_limitations)?relation.review_limitations.filter(v=>typeof v==='string').join('；'):'';
        if(reviewLimits)relationCell.append(el('p',reviewLimits));
      }
    }else if(row.instrument_classification==='ETF_PROXY'){
      relationCell.append(el('p','ETF 仅作原有宽主题代理输入；不生成发行人关系或港股直接映射。'));
    }else if(row.relation_assessment_status==='ASSESSED_WITH_GAPS' && row.relation_assessment_evidence){
      const assessment=object(row.relation_assessment_evidence),provenance=object(assessment.provenance);
      relationCell.append(el('p',`ASSESSED_WITH_GAPS · CANNOT_CONFIRM · 候选 HK.${text(assessment.candidate_hk_code)}；关系数量未知。`),
        el('p',text(assessment.reason)),
        el('p',`证据可用时间 ${text(assessment.available_at,'CANNOT_CONFIRM')} · 复核时间 ${text(assessment.reviewed_at,'CANNOT_CONFIRM')} · 目标日资格 CANNOT_CONFIRM`));
      if(provenance.evidence_artifact_sha256 || provenance.review_receipt_sha256)
        relationCell.append(el('p',`评估 SHA256 ${text(assessment.assessment_sha256)} · 复核收据 SHA256 ${text(assessment.review_receipt_sha256)}`));
    }else relationCell.append(el('p',`${text(row.relation_assessment_status)}；${Array.isArray(row.relation_gaps)?row.relation_gaps.join('；'):'关系缺口未知'}；关系数量未知。`));
    const evidenceCell=el('td');
    for(const relation of relations)renderMappingSources(evidenceCell,relation.sources);
    const assessment=object(row.relation_assessment_evidence??{});
    if(Array.isArray(assessment.sources))for(const rawSource of assessment.sources){
      const source=object(rawSource);renderMappingSources(evidenceCell,[source]);
      evidenceCell.append(el('p',`${text(source.source_capture_status)} · HTTP 正文 SHA 状态 ${text(source.source_body_sha256_status)} · ${text(source.source_locator)}`));
      if(typeof source.source_body_sha256==='string')evidenceCell.append(el('p',`HTTP 正文 SHA256 ${source.source_body_sha256}`));
    }
    for(const cell of [symbol,quoteCell,relationCell,evidenceCell])tr.append(cell);
    body.append(tr);
  }
  table.append(body);const wrapper=el('div');wrapper.className='us-mapping-table-wrap';wrapper.append(table);box.append(wrapper);host.append(box);
}

function renderUsMappingResearch(host:HTMLElement, mapping?:UsMappingResearch, us?:UsMarketAttention):void{
  const box=el('section');box.className='us-mapping-research';box.dataset.usMappingResearch='';box.setAttribute('aria-label','美股到港股业务关系研究');
  box.append(el('h4','美股 → 港股业务关系研究（只读研究，不是选股或 BUY）'));
  renderCurrentUsSymbolAssessments(box,us);
  if(!mapping){box.append(el('p','映射数据未提供 · CANNOT_CONFIRM；数量未知，不能解释为零。'));host.append(box);return;}
  const daily=mapping.daily_run;
  const reviewedCount=object(daily.coverage).reviewed_us_symbol_count;
  const dailyScope=typeof reviewedCount==='number'&&Number.isSafeInteger(reviewedCount)&&reviewedCount>=0?`${reviewedCount} 项`:'数量未知';
  box.append(el('h5',`每日 US-HK 已审映射（${dailyScope}）`));
  const currentCompatibility=text(daily.current_context_compatibility,'未与当前会话核对');
  box.append(el('p',`日常流程：${daily.status}；目标港股交易日 ${dateLabel(daily.target_trade_date)}；美股来源日 ${dateLabel(daily.us_session_date)}；cutoff ${text(daily.research_cutoff)}；当前会话一致性 ${currentCompatibility}；关系结果按日期单独保存并要求回读。`));
  if(currentCompatibility==='STALE_INPUTS_CHANGED')box.append(el('p','保存的日常关系产物与当前工作台行情会话或来源 SHA 不同；本页已隐藏该产物的匹配行，保留其历史状态供审计。'));
  if(daily.status==='NOT_RUN')box.append(el('p','该目标日尚无日常映射产物；数量未知，不等于没有匹配。'));
  else if(daily.status==='VALID_EMPTY')box.append(el('p',`已核日常来源在当前已审关系范围（${dailyScope}）内匹配为0；这只表示该已审关系范围为空，不代表全市场或其他关系为空，也不代表美股评估/完整度已完成。`));
  else if(daily.status==='FAILED'||daily.status==='INPUT_MISSING'||daily.status==='CANNOT_CONFIRM')
    box.append(el('p',`来源或回读未闭环，匹配数量未知；${daily.gaps.join('；')||'CANNOT_CONFIRM'}。`));
  else if(daily.status==='PARTIAL')
    box.append(el('p',`输入覆盖不完整，不能把当前行数当作完整匹配数；${daily.gaps.join('；')||'来源部分缺失'}。`));
  else box.append(el('p',`已评估 ${String(daily.matches.length)} 条已审关系命中。范围仅为当前已审关系（${dailyScope}），不代表全市场扫描或美股评估/完整度已完成。目标日Connect资格仍未知。`));
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
  renderUsMappingResearch(host,mapping,us);
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
    const displayedStatus=attention.observation_only && attention.input_diagnostics ? attention.status : `CANNOT_CONFIRM（新增诊断未提供；原始状态 ${attention.status}）`;
    host.append(el('p',`状态 ${displayedStatus}；cutoff ${text(attention.research_cutoff)}。评分配置 ${text((attention.config as JsonObject).version)}，状态 ${text((attention.config as JsonObject).status)}。研究排序先按证据状态，再用既有proposal分数和PIT时点打破同组并列；不写回原rank/Stage/BUY。`));
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
      host.append(article);
    }
  }
  renderInputDiagnostics(host,attention);
  renderIndependentObservations(host,attention);
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
