// The names below are display labels for already-computed fields, not rules.
export const KB_LABELS={
  kb_macd_dif_positive:'DIF在零上',kb_macd_dif_cross_zero:'DIF上穿零轴',kb_macd_dif_cross_zero_down:'DIF下穿零轴',
  kb_macd_gold_cross:'MACD金叉',kb_macd_dead_cross:'MACD死叉',kb_macd_gold_fake:'金叉后死叉',kb_macd_dead_fake:'死叉后金叉',
  kb_macd_top_divergence:'MACD顶背离',kb_macd_bottom_divergence:'MACD底背离',kb_macd_veto:'MACD日线风险条件',
  kb_white_cross_up:'白线上穿黄线',kb_white_cross_down:'白线下穿黄线',kb_bull_rope_status:'牛绳状态',kb_in_bowl:'金碗内',
  kb_breath_n_type:'呼吸N型',kb_needle_20:'单针20',kb_needle_30:'单针30',kb_beidou:'倍量',kb_suoliang:'缩量',
  kb_jiayin_zhenyang:'假阴真阳',kb_jiayang_zhenyin:'假阳真阴',kb_fangliang_yinxian:'放量阴线',
  kb_brick_trend_up:'命值趋势向上',kb_fanbao:'反包',kb_brick_flip_green:'红砖翻绿',kb_brick_action:'砖型源状态',
  kb_b1:'B1',kb_b2:'B2',kb_b3:'B3',kb_sb1:'SB1',kb_sb1_detailed:'超级B1',kb_double_gun:'双枪',
  kb_nana:'娜娜图',kb_rebuild:'灾后重建',kb_ready:'跃跃欲试',kb_didi:'滴滴·双阴阶梯',kb_centipede:'蜈蚣图',
  kb_violence_k:'暴力K',kb_kirin_stage:'麒麟阶段',kb_kirin_position:'麒麟位置',kb_kirin_vol:'麒麟量态',kb_breath_phase:'呼吸阶段',
};
export const CHART_EVENTS=['kb_b1','kb_b2','kb_b3','kb_violence_k','kb_fanbao','kb_sb1','kb_sb1_detailed',
  'kb_double_gun','kb_nana','kb_rebuild','kb_ready','kb_didi','kb_beidou','kb_needle_20','kb_needle_30','kb_brick_flip_green',
  'kb_macd_gold_cross','kb_macd_dead_cross','kb_white_cross_up','kb_white_cross_down'];
const STATES={exhale:'呼气',inhale:'吸气',none:'无呼吸阶段'};
const oldLabels={user_v1_level1_buy_signal:'原式一级买点',user_v1_level2_buy_signal:'原式二级买点',user_v1_sell_signal_daily:'原式卖点'};
export const CONFIRMED_GAP_FIELDS=[
  ['kb_brick_trend','砖型颜色'],['kb_brick_action_desc','砖型来源说明'],['kb_yidong_above_60d','异动位置相对60日线'],
  ['kb_double_gun_vol1','双枪第一根量比'],['kb_double_gun_vol2','双枪第二根量比'],['kb_double_gun_gap_days','双枪间隔交易日'],
  ['kb_violence_k_type','暴力K类型'],['kb_violence_k_body','暴力K实体幅度'],
];

export function confirmedGapPresentation(row){
  const values=row.confirmed_kb_fields,diag=row.confirmed_kb_diagnostics,reused=row.confirmed_kb_reused;
  if(!values||!diag||!reused)return null;
  const status={kb_brick_trend:'kb_brick_trend_reason',kb_brick_action_desc:'kb_brick_action_desc_reason',
    kb_yidong_above_60d:'kb_yidong_above_60d_status',kb_double_gun_vol1:'kb_double_gun_components_status',
    kb_double_gun_vol2:'kb_double_gun_components_status',kb_double_gun_gap_days:'kb_double_gun_components_status',
    kb_violence_k_type:'kb_violence_k_components_status',kb_violence_k_body:'kb_violence_k_components_status'};
  const reason=value=>value==='NOT_APPLICABLE_NO_SIGNAL'?'当日未命中':value==='NOT_APPLICABLE_SOURCE_PRECONDITION'?'源前置条件未满足':
    value==='INSUFFICIENT_HISTORY'?'历史预热不足':value?.includes('WARMUP')?'砖段起点处于预热期':'输入或来源待核';
  const list=CONFIRMED_GAP_FIELDS.map(([key,title])=>{
    const value=values[key],state=diag[status[key]];let text=value==null?(state?.startsWith('NOT_APPLICABLE')?'不适用 · ':'待核 · ')+reason(state):
      value===true?'是':value===false?'否':value==='RED'?'红砖':value==='GREEN'?'绿砖':String(value);
    if(key==='kb_brick_action_desc'&&value!=null)text+='（来源描述，仅供研究）';
    return {key,title,text};
  });
  const bowl=diag.kb_bowl_components_status==='OBSERVED_SOURCE_LINES';
  for(const [key,title] of [['bowl_white','金碗白线'],['bowl_yellow','金碗黄线']]){
    const value=reused[key];list.push({key,title,text:bowl&&Number.isFinite(value)?value.toFixed(2):'待核 · '+reason(diag.kb_bowl_components_status)});
  }
  return list;
}

export function brickCountPresentation(row){
  const reason=row.confirmed_kb_diagnostics?.kb_brick_count_reason;
  return reason?'待核：'+(reason.includes('WARMUP')?'砖段起点处于预热期':'砖型输入或来源不足'):null;
}

export const SUPPLEMENTAL_UNKNOWN=[
  ['kb_s1','S1','正文与概念卡对阴阳范围存在冲突，高位和巨量尚未统一量化'],
  ['kb_s2','S2','需要已确认的 S1 锚点及顶背离量化定义'],
  ['kb_s3','S3','需要已确认的 S1 或 S2 锚点，先跌离再反抽；数值条件待核'],
];

export function signalSummary(fields,kb,original,supplemental={},yidong=null){
  const chips=[],unknown=[];
  for(const [key,label] of Object.entries(oldLabels))if(original?.[key]===true||original?.[key]===1)chips.push({key,label,source:'原式'});
  for(const field of fields){
    if(!Object.hasOwn(KB_LABELS,field.name)||field.group==='组件/诊断')continue;
    const value=kb[field.name],label=KB_LABELS[field.name];
    if(value===null||value===undefined||value==='未知'){unknown.push({key:field.name,label,reason:field.unknown_reason||'行情或预热不足'});continue;}
    if(field.arrow_type==='bool'&&value===true)chips.push({key:field.name,label:'KB '+label,source:'KB'});
    else if(field.arrow_type==='string'&&typeof value==='string')chips.push({key:field.name,label:'KB '+label+' · '+(STATES[value]??value),source:'KB'});
  }
  for(const [key,label,reason] of SUPPLEMENTAL_UNKNOWN){
    const value=supplemental[key];
    if(value===null||value===undefined)unknown.push({key,label,reason});
    else if(value===true)chips.push({key,label:'KB '+label,source:'KB'});
  }
  if(yidong?.kb_yidong_is===true)chips.push({key:'kb_yidong_is',label:'KB 异动 · '+(yidong.kb_yidong_type??'等级待核'),source:'KB'});
  else if(yidong&&yidong.kb_yidong_is==null)unknown.push({key:'kb_yidong_is',label:'KB 异动',reason:yidong.kb_yidong_status==='INSUFFICIENT_65_BARS'?'不足65根历史':yidong.kb_yidong_status==='INVALID_PRICE_OR_VOLUME'?'价格或成交量输入无效':'来源或输入待核'});
  return {chips,unknown};
}

export function chartEvents(kb){return CHART_EVENTS.filter(key=>kb?.[key]===true).map(key=>({key,label:'KB '+KB_LABELS[key]}));}

// Format and validate stored action values; business decisions are produced upstream.
export function actionPresentation(action,contractSha){
  const fields=['kb_action_no_position_status','kb_action_with_position_status','kb_action_reasons','kb_action_rule_sha256'];
  if(!action||fields.some(key=>typeof action[key]!=='string'||!action[key])||action.kb_action_rule_sha256!==contractSha)throw Error('单股行动规则身份冲突');
  const choices=['买入','卖出','持有','放飞','等回调',null];
  if(!choices.includes(action.kb_action_no_position)||!choices.includes(action.kb_action_with_position))throw Error('单股行动枚举无效');
  const reasons=JSON.parse(action.kb_action_reasons);
  if(!Array.isArray(reasons)||!reasons.every(value=>typeof value==='string'))throw Error('单股行动依据无效');
  return {flat:action.kb_action_no_position??'待核',held:action.kb_action_with_position??'待核',reasons};
}

export function signalExplanations(row,facts={}){
  const macd=row.kb?.kb_macd_veto,macdState=macd===true?'触发':macd===false?'未触发':'待核';
  const out=[`MACD日线风险条件 · 本日状态：${macdState}。规则说明：DIF低于零且程序按日线60日窗口未检出当日底背离；知识库正文也强调周/月周期，不能视为完整正文认证。MACD不属于持股评分的五个分项。`];
  const y=row.yidong;
  if(y){const fmt=v=>Number.isFinite(v)?v.toFixed(2):'待核';
    out.push(`异动：${y.kb_yidong_is===true?'已命中':y.kb_yidong_is===false?'未命中':'待核'}；较前5根均量 ${fmt(y.kb_yidong_vol_ratio_5)} 倍，近5根阳线 ${y.kb_yidong_bullish_count_5??'待核'} 根；詹姆斯级 ${y.kb_yidong_james===true?'已命中':y.kb_yidong_james===false?'未命中':'待核'}。`);
    out.push(`当日距黄线 ${fmt(y.kb_yidong_yellow_distance_pct)}%，距MA60 ${fmt(y.kb_yidong_ma60_distance_pct)}%；近5根量峰/此前20根量峰 ${fmt(y.kb_yidong_peak_ratio_5_20)} 倍；近5根收盘和成交量均高于前一根 ${y.kb_yidong_price_volume_up_days_5??'待核'} 日（描述性比较，非已认证放量定义）。起涨/回调锚点和再次突破条件待核。`);
  }
  const f=facts[String(row.trade_date)];
  if(!f){out.push('该日期的未触发组件尚未绑定，不能套用其他日期的原因。');return out}
  if(f.volume_ratio!=null)out.push(`倍量：较前一日 ${f.volume_ratio.toFixed(2)} 倍，固定实现要求至少2倍；这是与昨量比较。`);
  const b=f.kb_b3_components;
  if(b)out.push(`KB B3：锚点${b.anchor_date}，相距${b.trading_bars_since_anchor}个交易日，不在2～5日范围；较锚点量${b.today_anchor_volume_ratio.toFixed(2)}倍，未小于0.8倍。`);
  const x=f.breakout_components;
  if(x)out.push(`原式突破：收盘${x.close_above_previous_20_high?'高于':'未高于'}前20日高点 ${f.prior_20_high}，涨幅 ${x.pct_chg.toFixed(2)}%，原式还要求严格大于4%。`);
  const v=f.violence_k_python_components;
  if(v)out.push(`KB暴力K：较前5日均量 ${v.relative_previous_five_mean_volume.toFixed(2)} 倍，量能条件已满足；实体相对昨收 ${v.body_pct.toFixed(2)}% 未达代码5%，低点也未满足代码位置条件。5日、5%和1.05为固定实现参数，不是正文独立指定的窗口。`);
  return out;
}

export const HOLD_ITEMS=[
  ['kb_hold_close_up','收盘上涨'],['kb_hold_above_bbi','收盘在BBI之上'],['kb_hold_volume_ok','阳线得分（收盘>开盘）'],
  ['kb_hold_trend_up','N型趋势向上'],['kb_hold_j_not_dead','J未处于死叉状态'],
];
export const HOLD_REASONS={RULE_NOT_QUANTIFIED:'规则待量化',INSUFFICIENT_PRIOR_BAR:'前一日行情不足',INVALID_CLOSE_INPUT:'收盘行情无效',
  INVALID_OHLC_INPUT:'开高低收行情缺失或无效',INVALID_VOLUME_INPUT:'当日成交量缺失或无效',
  INSUFFICIENT_BBI_HISTORY:'BBI预热不足',INVALID_CLOSE_WINDOW:'收盘行情不足',BBI_EQUALITY_UNRESOLVED:'BBI相等边界待核',
  INSUFFICIENT_KDJ_HISTORY:'KDJ预热不足',INVALID_HLC_PREFIX:'KDJ行情前缀无效',
  INSUFFICIENT_CONFIRMED_SWINGS:'尚不足四个已确认转折点',INVALID_INPUT:'当日行情无效',
  AMBIGUOUS_SAME_BAR_PIVOT:'同一日同时出现高低转折，先后次序待核',
  STRUCTURE_NOT_RISING:'高点或低点未同时抬高',BROKEN_BY_CLOSE:'收盘跌破最近确认低点'};

export function nStructurePresentation(row){
  const score=row.hold_score,n=row.confirmed_kb_diagnostics?.kb_n_structure;
  if(!n||!score)return null;
  const state=score.kb_hold_trend_up,reason=score.kb_hold_trend_up_reason;
  const status=state===true?'趋势向上 · 1分':state===false?'趋势不向上 · 0分':'待核';
  const explanation=HOLD_REASONS[reason];
  const points=['L1','H1','L2','H2'].map(key=>{const p=n[key];return p?.event_date&&p?.confirmed_at?`${key} ${p.price}（${p.event_date} 形成，${p.confirmed_at} 确认）`:null}).filter(Boolean);
  return [`N型趋势：${status}${explanation?' · '+explanation:''}`,...(points.length?[points.join('；')]:[])];
}
