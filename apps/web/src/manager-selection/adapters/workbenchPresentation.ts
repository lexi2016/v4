import type { ManagerWorkbenchCandidate } from '../../contracts/managerWorkbenchResearch';

const CONDITIONS = [
  ['turnover_gt_100m_hkd', '成交额'],
  ['verified_volume_expansion', '放量依据'],
  ['verified_oversold_or_breakout', '超跌或突破'],
  ['new_direct_pit_catalyst', '新催化'],
] as const;

const REBOUND_RULE = '20260921_REBOUND_V3_1530_OBSERVATION_V1';
const REBOUND_CONDITIONS = [
  ['amount_100m_lt_le_200m_hkd', '截至15:30金额(1亿,2亿]'],
  ['oversold_le_80pct_prior60_high', '60日原始高点超跌'],
  ['volume_ge_1_5_previous5_full_days', '前5完整日均量1.5倍'],
  ['last_price_ge_1_03_low_so_far', '截至快照低点反弹3%'],
  ['final_close_confirmation', '最终收盘确认'],
] as const;
function isRebound(candidate: ManagerWorkbenchCandidate | null): boolean {
  return Boolean(candidate?.predicates.some(p => p.rule_version === REBOUND_RULE));
}

export function conditionIndicators(candidate: ManagerWorkbenchCandidate | null) {
  return (isRebound(candidate) ? REBOUND_CONDITIONS : CONDITIONS).map(([id, label]) => {
    const value = candidate?.predicates.find(p => p.predicate_id === id)?.value;
    return { id, label, state: value === true ? '已确认' : value === false ? '未满足' : '待补资料' };
  });
}

export function conditionGaps(candidate: ManagerWorkbenchCandidate | null): string {
  const missing = conditionIndicators(candidate).filter(x => x.state === '待补资料').map(x => x.label);
  return missing.length ? `待补：${missing.join('、')}` : '四项资料已齐；仍须核对条件与交易边界';
}

export function candidateHeadline(candidate: ManagerWorkbenchCandidate): string {
  if (isRebound(candidate)) {
    if (candidate.data_status === 'STRICT_ASOF_OBSERVATION') return '15:30四项数值满足，待收盘确认';
    if (candidate.data_status === 'NEAR_ASOF_OBSERVATION') return '15:30近条件观察，非严格合格';
    return '15:30反弹依据待核，不计近条件';
  }
  const complete = CONDITIONS.every(([id]) => candidate.predicates.some(p =>
    p.predicate_id === id && p.value === true && p.rule_version === 'manager-close-rework-r2-v1'));
  if (candidate.qualified === true && complete) return '完整条件候选';
  if (candidate.qualified === false) return '条件未满足';
  return '成交额观察待核';
}

export function readableStatus(status: string): string {
  const labels: Record<string,string> = {
    NOT_RUN: '未见执行记录', PENDING_SLOT: '等待时段或执行中',
    INPUT_MISSING: '尾盘资料缺失', PARTIAL: '覆盖不完整，观察待核',
    FAILED: '研究执行或读取失败', READY_EMPTY: '已完成，完整条件候选为0',
    READY: '研究结果已生成', STALE: '结果已过期，请核对时间',
    NOT_APPLICABLE: '本交易日不适用', CANNOT_CONFIRM: '资料尚未核实',
    LOADING: '正在读取，旧结果已清除', IDLE: '尚未读取',
  };
  return labels[status] || '状态待核';
}
