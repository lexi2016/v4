// The names below are display labels for already-computed fields, not rules.
export const KB_LABELS={
  kb_macd_dif_positive:'DIF在零上',kb_macd_dif_cross_zero:'DIF上穿零轴',kb_macd_dif_cross_zero_down:'DIF下穿零轴',
  kb_macd_gold_cross:'MACD金叉',kb_macd_dead_cross:'MACD死叉',kb_macd_gold_fake:'金叉后死叉',kb_macd_dead_fake:'死叉后金叉',
  kb_macd_top_divergence:'MACD顶背离',kb_macd_bottom_divergence:'MACD底背离',kb_macd_veto:'MACD风险否决',
  kb_white_cross_up:'白线上穿黄线',kb_white_cross_down:'白线下穿黄线',kb_bull_rope_status:'牛绳状态',kb_in_bowl:'金碗内',
  kb_breath_n_type:'呼吸N型',kb_needle_20:'单针20',kb_needle_30:'单针30',kb_beidou:'倍量',kb_suoliang:'缩量',
  kb_jiayin_zhenyang:'假阴真阳',kb_jiayang_zhenyin:'假阳真阴',kb_fangliang_yinxian:'放量阴线',
  kb_brick_trend_up:'命值趋势向上',kb_fanbao:'反包',kb_brick_flip_green:'红砖翻绿',kb_brick_action:'砖型源状态',
  kb_b1:'B1',kb_b2:'B2',kb_b3:'B3',kb_sb1:'SB1',kb_sb1_detailed:'超级B1',kb_double_gun:'双枪',
  kb_nana:'娜娜图',kb_rebuild:'灾后重建',kb_ready:'跃跃欲试',kb_didi:'滴滴·双阴阶梯',kb_centipede:'蜈蚣图',
  kb_violence_k:'暴力K',kb_kirin_stage:'麒麟阶段',kb_kirin_position:'麒麟位置',kb_kirin_vol:'麒麟量态',kb_breath_phase:'呼吸阶段',
};
export const CHART_EVENTS=['kb_b1','kb_b2','kb_b3','kb_violence_k','kb_fanbao','kb_sb1','kb_sb1_detailed',
  'kb_double_gun','kb_nana','kb_ready','kb_didi','kb_beidou','kb_needle_20','kb_needle_30','kb_brick_flip_green',
  'kb_macd_gold_cross','kb_macd_dead_cross','kb_white_cross_up','kb_white_cross_down'];
const STATES={exhale:'呼气',inhale:'吸气',none:'无呼吸阶段'};
const oldLabels={user_v1_level1_buy_signal:'原式一级买点',user_v1_level2_buy_signal:'原式二级买点',user_v1_sell_signal_daily:'原式卖点'};

export const SUPPLEMENTAL_UNKNOWN=[
  ['kb_s1','S1','正文与概念卡对阴阳范围存在冲突，高位和巨量尚未统一量化'],
  ['kb_s2','S2','需要已确认的 S1 锚点及顶背离量化定义'],
  ['kb_s3','S3','需要已确认的 S1/S2 锚点及反抽下沿量化定义'],
  ['kb_didi_1455','滴滴·14:55','缺少绑定的 14:55 分钟行情'],
];

export function signalSummary(fields,kb,original,supplemental={}){
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
  return {chips,unknown};
}

export function chartEvents(kb){return CHART_EVENTS.filter(key=>kb?.[key]===true).map(key=>({key,label:'KB '+KB_LABELS[key]}));}

export const HOLD_ITEMS=[
  ['kb_hold_close_up','收盘上涨'],['kb_hold_above_bbi','收盘在BBI之上'],['kb_hold_volume_ok','量能非出货形态'],
  ['kb_hold_trend_up','N型趋势向上'],['kb_hold_j_not_dead','J未处于死叉状态'],
];
export const HOLD_REASONS={RULE_NOT_QUANTIFIED:'规则待量化',INSUFFICIENT_PRIOR_BAR:'前一日行情不足',INVALID_CLOSE_INPUT:'收盘行情无效',
  INSUFFICIENT_BBI_HISTORY:'BBI预热不足',INVALID_CLOSE_WINDOW:'收盘行情不足',BBI_EQUALITY_UNRESOLVED:'BBI相等边界待核',
  INSUFFICIENT_KDJ_HISTORY:'KDJ预热不足',INVALID_HLC_PREFIX:'KDJ行情前缀无效'};
