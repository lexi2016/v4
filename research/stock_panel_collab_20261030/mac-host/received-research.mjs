// Received explanations only. No selection, qualification, ranking or BUY logic.
const identityKeys=['symbol','source_date','observation_date','generation','input_sha256'];
const compact=value=>String(value??'').replaceAll('-','');
const safe=value=>value?.RESEARCH_ONLY===true&&['production_allowed','buy_gate_updated','orders_sent'].every(key=>value[key]===false);
const number=(value,digits=2)=>typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits):'待核';
const percent=value=>typeof value==='number'&&Number.isFinite(value)?number(value)+'%':'待核';
const roleLabel={technical_observe:'技术观察',wait_for_trigger:'候触发',NOT_SELECTED:'未列本批六只重点'};

export function safeSourceUrl(value){
  try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch{return null;}
}

export function receivedView(value){
  const material=value?.received_materials,fund=material?.received_fundamentals;
  if(!fund)return null; // Preserve all previously accepted older company views.
  const summary=material.received_batch_summary,secondary=material.secondary_screen,perf=material.daily_performance;
  const classification=fund.research_main_classification,v2=Boolean(classification),v3=summary?.return_schema==='V4_RECEIVED_RESEARCH_IMPORT_V3';
  const lifecycle=value.material_lifecycle,origin=lifecycle?.material_identity;
  if(lifecycle&&(!origin||lifecycle.current_candidate_identity?.data_date!==compact(value.source_date)
    ||lifecycle.current_candidate_identity?.source_generation!==value.generation
    ||lifecycle.current_candidate_identity?.input_sha256!==value.input_sha256
    ||origin.data_date!==material.data_date||origin.source_generation!==material.source_generation
    ||origin.input_sha256!==material.input_sha256))throw Error('RECEIVED_RESEARCH_IDENTITY_CONFLICT');
  const date=origin?.data_date??compact(value.source_date),target=summary?.target_date??compact(value.observation_date);
  const materialGeneration=origin?.source_generation??value.generation,materialInput=origin?.input_sha256??value.input_sha256;
  if(!origin&&target!==compact(value.observation_date))throw Error('RECEIVED_RESEARCH_IDENTITY_CONFLICT');
  const v3SecondaryValid=v3&&safe(secondary)&&secondary.status==='PARTIAL_RECEIVED_MODULE'
    &&secondary.role==='RESEARCH_MAPPING_ONLY'&&secondary.received_record?.symbol===value.symbol
    &&compact(secondary.received_record?.source_date)===date&&compact(secondary.received_record?.observation_date)===target
    &&String(secondary.received_record?.industry_research_rank_is_trade_rank).toLowerCase()==='false';
  const v1SecondaryValid=secondary?.status==='CANNOT_CONFIRM'
    &&secondary.received_record?.full_chain_status==='CANNOT_CONFIRM';
  const v2SecondaryValid=v2&&safe(classification)&&classification.symbol===value.symbol
    &&classification.source_date===date&&classification.observation_date===target
    &&classification.source_generation===materialGeneration
    &&secondary?.status==='NOT_RUN_FOR_20261105_GENERATION'
    &&secondary.role==='NOT_RUN'&&secondary.reference_status==='NOT_RUN'
    &&secondary.received_record?.industry_secondary_status==='NOT_RUN_FOR_20261105_GENERATION'
    &&secondary.received_record?.full_chain_status==='NOT_RUN_FOR_20261105_GENERATION'
    &&secondary.received_record?.theme==null
    &&summary.themes?.length===0&&summary.technical_observe_count===0&&summary.wait_for_trigger_count===0
    &&Object.values(secondary.reference_fields??{}).every(item=>item===null);
  if(!safe(value)||!safe(material)||!safe(summary)||!safe(perf)||material.symbol!==value.symbol
      ||material.data_date!==date||material.source_generation!==materialGeneration||material.input_sha256!==materialInput
      ||summary.source_date!==date||summary.target_date!==target||summary.generation!==materialGeneration||summary.input_sha256!==materialInput
      ||secondary?.source_date!==date||secondary.target_date!==target
      ||summary.strict_full_chain_certified_count!==0||!(v3?v3SecondaryValid:v2?v2SecondaryValid:v1SecondaryValid)
      ||perf?.symbol!==value.symbol||perf.source_date!==date||perf.target_date!==target||perf.source_generation!==materialGeneration
      ||perf.current_target_day_return_pct!==null||perf.current_target_day_performance_status!=='NOT_MATERIALIZED_NOT_READ')throw Error('RECEIVED_RESEARCH_IDENTITY_CONFLICT');
  return {material,fund,summary,secondary,perf,date,target,v2,v3,classification};
}

export function renderMaterialTiming(value,host,doc=document){
  const timing=value?.material_lifecycle;if(!timing)return;
  const line=doc.createElement('p');line.className='notice';
  const historical=timing.freshness_status==='HISTORICAL_NOT_REVIEWED_FOR_CURRENT_CANDIDATES';
  line.textContent=`${historical?'历史资料 · 当前候选当日未复核':'本来源日收到的研究'} · 原资料日 ${timing.material_source_date} · 接收 ${timing.received_at??'UNKNOWN'} · 当前候选日 ${compact(value.source_date)}。首次可用时点/PIT未认证；不参与选股评分。`;
  host.append(line);
}

export function renderReceivedResearch(value,doc=document){
  const data=receivedView(value);if(!data)return false;
  const {material,fund,summary,secondary,perf,date,target,v2,v3,classification}=data;
  const add=(host,tag,text)=>{const node=doc.createElement(tag);if(text!==undefined)node.textContent=String(text);host.append(node);return node;};
  const company=doc.getElementById('companySummary'),metrics=doc.getElementById('companyMetrics'),evidence=doc.getElementById('companyEvidence');
  company.replaceChildren();metrics.replaceChildren();evidence.replaceChildren();
  const batch=add(company,'section');batch.id='receivedBatchSummary';batch.className='notice';
  renderMaterialTiming(value,company,doc);
  add(batch,'strong',v3?`公司研究与行业二筛已接收 · ${summary.scope_count}只原池 · PARTIAL`:v2?`公司研究接收 · ${summary.scope_count}只原池 · 行业二筛：今天尚未运行`:`${summary.themes?.length??'待核'}主题二筛 · ${summary.scope_count}只原池 · 完整链0已确认`);
  add(batch,'p',`行情截至${date.slice(4,6)}/${date.slice(6)}收盘 / 目标观察${target.slice(4,6)}/${target.slice(6)}${v2?'。':`；${summary.technical_observe_count}技术观察 + ${summary.wait_for_trigger_count}候触发。`}`);
  for(const theme of summary.themes??[]){
    const names=role=>(theme[role]??[]).map(item=>`${item.name??''} ${item.symbol}`).join('、')||'未列';
    add(batch,'p',`${theme.theme}：技术观察 ${names('technical_observe')}；候触发 ${names('wait_for_trigger')}`);
  }
  add(batch,'small',v2?'研究主营分类只作研究参考；小市值及完整量价结构仍待核。':`二筛接收时点 ${summary.secondary_recorded_at??'待核'}；行业是研究参考。B1动态引用缺陷、历史换手等缺口保留，候触发不计合格信号。`);
  add(company,'h4',v2||v3?'公司研究已接收，仍有资料待补':'收到的公司研究');
  add(company,'p',`${value.symbol} · ${fund.verified_name??fund.screened_name??''} · 原包状态 ${fund.status??'UNKNOWN'} · 截至 ${fund.research_as_of??fund.as_of??'待核'}`);
  add(company,'p',fund.business??'主营原文待核');
  if(v3){
    add(company,'p',`本次研究层级：${fund.received_source_record?.research_priority??'UNKNOWN'}（原序 ${fund.received_source_record?.priority_order||'UNKNOWN'}）；行业研究层级：${secondary.received_record.industry_secondary_tier??'UNKNOWN'}`);
  }
  if(v2){
    add(company,'p',`研究主营分类（依据收到的主营描述）：${classification.research_main_industry??'UNKNOWN'}`);
    add(company,'p',`主营/产业链位置：${classification.industry_chain_position_received??fund.industry_chain_position??'CANNOT_CONFIRM'}`);
    const priority=classification.user_resource_priority;
    if(priority)add(company,'p',`研究资源优先级：${priority}`);
    else add(company,'p',`原始研究层级：${classification.research_tier_received??fund.research_tier??'UNKNOWN'}`);
  }
  for(const [key,label]of [['profit_driver','利润驱动'],['growth_quality','增长质量'],['cash_debt_quality','现金与负债'],['bottleneck_evidence','产业卡点'],['customer_commercialization','客户商业化'],['orders_capacity','订单与产能'],['key_risks','主要风险']]){
    if(v2||v3||['profit_driver','growth_quality','cash_debt_quality','key_risks'].includes(key))add(company,'p',`${label}：${fund[key]??'CANNOT_CONFIRM'}`);
  }
  add(company,'small',`原包自报 ${Object.entries(summary.original_producer_status_counts??{}).map(([key,count])=>key+' '+count).join(' / ')}；仅${summary.specified_primary_page_check_count??'待核'}只官方指定页另有复核，其余为收到的研究。全部历史PIT未认证。`);
  const detail=add(company,'details');add(detail,'summary','估值、催化与反证原文');
  for(const [key,label]of [['valuation_method','估值方法'],['valuation_date','估值日期'],['valuation_assessment','估值判断'],['catalyst','催化跟踪'],['counter_evidence','反证'],['evidence_summary','原包依据范围']])add(detail,'p',`${label}：${fund[key]??'CANNOT_CONFIRM'}`);
  if(v3){
    const raw=fund.received_source_record??{};
    add(metrics,'h4',`收到的财务摘要 · ${fund.latest_financial_period??'期间待核'}`);
    add(metrics,'small',`原包字段，单位人民币元 / 同比%；状态 ${raw.current_financial_semantic_read_status||'UNKNOWN'}。PARTIAL，不补算空值或认证原包全部财务。`);
    for(const [key,label]of [['current_normalized_revenue_ytd_cny','年初至今营收'],['current_normalized_revenue_ytd_yoy_pct','营收同比%'],['current_normalized_recurring_profit_ytd_cny','年初至今扣非净利润'],['current_normalized_recurring_profit_ytd_yoy_pct','扣非同比%'],['current_normalized_cfo_ytd_cny','年初至今经营现金流'],['current_normalized_cfo_ytd_yoy_pct','经营现金流同比%']])add(metrics,'p',`${label}：${raw[key]||'UNKNOWN'}`);
    add(metrics,'p',`原文阅读范围：${raw.root_current_financial_read_scope||raw.current_primary_read_scope||'UNKNOWN'}；研究截至 ${fund.research_as_of??'UNKNOWN'}`);
  }
  add(metrics,'h4',`当日表现 · 截至 ${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6)} 收盘`);
  add(metrics,'p',`收盘 ${number(perf.close)} 元 · 涨跌 ${percent(perf.day_return_pct)} · 昨收 ${number(perf.previous_close)} 元`);
  add(metrics,'p',`开 ${number(perf.open)} / 高 ${number(perf.high)} / 低 ${number(perf.low)} 元；成交额 ${typeof perf.amount_yuan==='number'?number(perf.amount_yuan/1e8)+'亿元':'待核'}；成交量 ${typeof perf.volume_shares==='number'?number(perf.volume_shares/1e4)+'万股':'待核'}；换手率 ${percent(perf.turnover_rate_pct)}`);
  add(metrics,'p',`Canonical D量/含D近5交易日均量：${number(perf.volume_to_current_MA5,4)}；窗口 ${(perf.volume_ratio_dates??[]).join('、')}。`);
  add(metrics,'p',`全历史收盘价分位 ${percent(perf.all_history_percentile_pct)}（${perf.all_history_sample_count??'待核'}样本）；近250日 ${percent(perf.near250_percentile_pct)}。`);
  add(metrics,'p',`目标${target.slice(4,6)}/${target.slice(6)}盘中未读取，涨跌为空；不是实时量比。财务期间 ${fund.latest_financial_period??'待核'}；财务数值未从原文推算。`);
  const screen=add(metrics,'section');screen.id='receivedSecondaryScreen';
  if(v3){
    const record=secondary.received_record;
    add(screen,'strong',`行业二筛 · ${record.industry_secondary_status??'UNKNOWN'}`);
    add(screen,'p',`原资料日 ${date} · 观察日 ${target} · ${record.industry_secondary_theme??'UNKNOWN'} · ${record.industry_secondary_tier??'UNKNOWN'}`);
    for(const [key,label]of [['product_mapping_type','产品映射'],['industry_to_domestic_product','行业至国内产品'],['company_profit_transmission','公司利润传导'],['profit_growth_assessment','增长判断'],['cashflow_assessment','现金流判断'],['failure_and_counterevidence','失效与反证'],['industry_external_evidence','外盘依据与缺口'],['current_setup_qualification','当前形态限制']])add(screen,'p',`${label}：${record[key]||'UNKNOWN'}`);
    add(screen,'small','原包行业研究映射；完整策略链未认证，不是交易排名，不更新BUY门。');
    const raw=add(screen,'details');add(raw,'summary','完整收到的行业二筛行');add(raw,'pre',JSON.stringify(record,null,2));
  }else if(v2){
    add(screen,'strong','行业二筛：今天尚未运行');
    add(screen,'p',`研究主营分类按收到的主营描述；源日 ${date} · 观察日 ${target} · 二筛状态 ${secondary.received_record.industry_secondary_status}`);
    if(secondary.received_record.gap)add(screen,'p',`保留说明：${secondary.received_record.gap}`);
  }else{
    add(screen,'strong',`行业二筛 · ${roleLabel[secondary.role]??secondary.role} · 完整链 CANNOT_CONFIRM`);
    add(screen,'p',`${secondary.received_record.theme??'三主题外'} · 行情源日 ${date} · 目标 ${target} · 接收 ${secondary.recorded_at??'待核'}`);
    const fields=secondary.reference_fields??{};
    add(screen,'p',`P5外部参考：关键K ${fields.p5_key_type??'待核'} / 日期 ${fields.p5_key_date||'待核'} / 距D ${fields.p5_key_age??'待核'}；风险 ${fields.p5_risk_label??'待核'}。`);
    add(screen,'p',`P5 D量/含D近5均量 ${number(fields.volume_to_current_MA5,4)}；P5 D量/此前5均量 ${number(fields.volume_to_prior_MA5,4)}。原二筛当前5均量阈值0.92；参考快照不覆盖Canonical。`);
    add(screen,'p',`B1：${secondary.received_record.b1_status??'CANNOT_CONFIRM'}；原市场门：${secondary.received_record.market_gate_status??'CANNOT_CONFIRM'}。`);
    if(secondary.errors?.length)add(screen,'p',`P5隔离 / 缺口：${secondary.errors.join('；')}。参考值留空，Canonical行情单列。`);
  }
  const missing=add(evidence,'details');add(missing,'summary','收到的来源、指定页复核与缺口');
  add(missing,'p',`本股证据等级 ${perf.fundamental_evidence_level??fund.evidence_status}；原状态 ${fund.status??'UNKNOWN'}。原文声明与分析推断依原包保留，不认证全部内容。`);
  for(const gap of fund.missing_inputs??[])add(missing,'p','研究缺口：'+gap);
  for(const gap of perf.missing_inputs??[])add(missing,'p','行情/策略缺口：'+gap);
  for(const source of fund.sources??[]){const row=add(missing,'p',`${source.title??source.source_id} · ${source.financial_period??'期间待核'} · ${source.page_or_section??'章节待核'} · ${source.access_status??'读取状态待核'} `),url=safeSourceUrl(source.url);if(url){const a=add(row,'a','原始来源');a.href=url;a.target='_blank';a.rel='noopener noreferrer';}else add(row,'span','来源链接待核');add(missing,'small',`来源SHA ${source.sha256||'UNKNOWN'}；披露 ${source.disclosed_at||'UNKNOWN'}；接收 ${source.retrieved_at||'UNKNOWN'}`);}
  for(const audit of fund.specified_primary_page_checks??[])add(missing,'pre',JSON.stringify(audit,null,2));
  const claims=add(missing,'details');add(claims,'summary',`原声明分类 ${fund.claims?.length??0} 条`);for(const claim of fund.claims??[])add(claims,'p',`${claim.statement_class??claim.basis??claim.type??'分类待核'} · ${claim.field??''}：${claim.statement??claim.claim??claim.text??''}`);
  if(v2||v3){const source=add(missing,'details');add(source,'summary','完整收到的原始研究行');add(source,'pre',JSON.stringify(fund.received_source_record,null,2));}
  const refs=add(missing,'details');add(refs,'summary','绑定来源与原始二筛字段');add(refs,'pre',JSON.stringify({source_refs:material.source_refs,secondary_screen:secondary,performance:perf},null,2));
  return true;
}

// Reuse company-local's request ticket: a later stock/day request invalidates
// this fetch even when the user switches away and back to the same symbol.
export function createReceivedCompanyRefresh({getContext,begin,isCurrent,validate,fetchCompany,apply,onError}){
  return async event=>{
    const context=getContext();if(!context||!event?.company_materials||event.data_date!==compact(context.source_date)
      ||event.source_generation!==context.generation||event.input_sha256!==context.input_sha256)return false;
    const ticket=begin(context),identity={...context};
    const current=()=>isCurrent(ticket)&&identityKeys.every(key=>getContext()?.[key]===identity[key]);
    try{
      const value=await fetchCompany(identity);
      if(!current())return false;
      validate(value,identity.symbol);if(value.status==='NOT_MATERIALIZED'||(!receivedView(value)&&!value.business?.summary))throw Error('RECEIVED_COMPANY_REFRESH_MATERIALS_MISSING');
      apply(value);return true;
    }catch{if(current())onError(identity);return false;}
  };
}
