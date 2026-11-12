"""Five user opportunity types: existing facts/clues and explicit UNKNOWN.
No new indicator, threshold, fit or selection gate. Comparisons of volume 1x
and return versus market median are plain descriptive comparisons, not signals.
"""
import json,pathlib,math
import pandas as pd
N=pathlib.Path(__file__).resolve().parents[1]
def finite(x):
 try:return math.isfinite(float(x))
 except (TypeError,ValueError):return False
def yes(x):return str(x)=='True'
def save(p,x):pathlib.Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def main():
 facts=pd.read_csv(N/'outputs/ALL_CANDIDATE_STRUCTURE_FACTS.csv',dtype={'security_code':str},float_precision='round_trip');returns=pd.read_csv(N/'data/FULL_UNIVERSE_D12_RETURNS.csv',dtype={'security_code':str},float_precision='round_trip').set_index('security_code');market=json.loads((N/'MARKET_BREADTH.json').read_text());median=market['median_return_pct'];events=pd.read_csv(N/'outputs/R3_EVENTS_120.csv',dtype={'security_code':str});hist={code:g.sort_values('origin_date').to_dict('records')for code,g in events.groupby('security_code',sort=False)}
 types=['低位早期反转','关键K回踩收回','缩量回调与承接','突破延续','市场调整中的逆势强势股'];long=[];wide=[]
 for r in facts.to_dict('records'):
  code=r['security_code'];ret=returns.loc[code];support=any(yes(r[k])for k in ('A_candidate_key_retest','B_prior_touch_current_recovered','C_later_attack_retest'));relative=float(ret.return_pct)-median if ret.return_status=='EXACT_D_AND_D_MINUS1'and finite(median)else None
  volume_lower=finite(r['D_volume_div_owner_volume'])and float(r['D_volume_div_owner_volume'])<1
  group=json.loads(r['source_engine_group_status_json']);entries=[
   (types[0],yes(r['D_any_turn_proxy']),dict(D_bull_reclaim_prior_bear_body=r['D_bull_reclaim_prior_bear_body'],D_r3_local_turn_proxy=r['D_r3_current_local_reversal_proxy'],return20=r['return_20_bars_pct'],return60=r['return_60_bars_pct'],prior60_low=r['prior60_low']),['低位与早期阶段尚无严格接纳定义；局部反转代理不等于大级别下行已扭转','R3最近120观察行左截断；未把活动高点当原锚']),
   (types[1],support,dict(owner_candidate_key=r['owner_candidate_anchor_date'],A_D_touch=r['A_candidate_key_retest'],B_prior_touch_D_recovery=r['B_prior_touch_current_recovered'],C_management_touch=r['C_later_attack_retest'],support_state=r['owner_support_state'],prior_first_touch=r['owner_first_prior_touch'],prior_last_touch=r['owner_last_prior_touch']),['owner候选K未自动认证独立原始关键K；当前轮归属须逐图','收盘破原候选K低点与未来新事件未决分别保留']),
   (types[2],support and volume_lower,dict(D_volume=r['D_volume'],D_div_owner_key=r['D_volume_div_owner_volume'],D_div_previous=r['D_volume_div_prev_volume'],D_div_prior20_mean=r['D_volume_div_prev20_mean'],D_div_management=r['D_volume_div_management_volume'],prior20_start=r['prev20_volume_window_start'],prior20_end=r['prev20_volume_window_end']),['量较参考K低仅数值事实，不证明吸筹或有效承接','不新增0.7/1.3等量比门；原生量单位未认证']),
   (types[3],group.get('nav_breakout')=='TRUE',dict(original_engine_nav_breakout=group.get('nav_breakout'),source_groups=r['source_groups'],D_close=r['D_close'],prior20_high=r['prior20_high'],D_volume_div_prev20_mean=r['D_volume_div_prev20_mean']),['沿原引擎突破子组事实；非新规则或自动优先','此前大幅拉升/大阴线和当前距离须人工复核，不能以调整日追涨替代好回调']),
   (types[4],ret.return_status=='EXACT_D_AND_D_MINUS1'and finite(median)and median<0 and ret.return_pct>0,dict(D_return_pct=ret.return_pct,market_median_pct=median,excess_over_market_median_pp=relative,return_status=ret.return_status),['正收益/超市场中位是当日描述，不是新正式信号','行业共振仅有限静态NONPIT映射；未知行业不补0，后到信息不倒填'])]
  tags=[]
  for name,clue,evidence,gaps in entries:
   # Each clue is observable, while the semantic opportunity classification
   # remains UNKNOWN until the controller's dated visual/risk review.
   long.append(dict(security_code=code,name=r['name'],trade_date='2026-11-12',opportunity_type=name,existing_fact_clue=bool(clue),confirmed_opportunity='UNKNOWN',evidence_json=json.dumps(evidence,ensure_ascii=False,default=str),gaps_json=json.dumps(gaps,ensure_ascii=False),threshold_or_new_signal_added=False,used_as_selection_gate=False))
   if clue:tags.append(name+'：仅事实线索')
  cases=hist.get(code,[]);prior=[e for e in cases if int(e['origin_date'])<20261112];history=prior[-3:]
  wide.append(dict(security_code=code,trade_date='2026-11-12',opportunity_tags=json.dumps(tags,ensure_ascii=False),opportunity_confirmation='UNKNOWN_NO_AUTOMATIC_PROMOTION',same_stock_R3_120_event_count=len(cases),previous_observed_case_count=len(history),previous_cases_json=json.dumps(history,ensure_ascii=False,default=str),history_scope='last120 observed bars; LEFT_CENSORED; full historical cases not certified',market_relative_strength_pp=relative,root_review_source=str(N/'ROOT_VISUAL_REVIEW.md'),current_risk_review_overrides=str(N/'IDENTITY_RISK_OVERRIDES.json')))
 out=pd.DataFrame(long);out.to_csv(N/'outputs/FIVE_OPPORTUNITY_TYPES_EVIDENCE_LONG.csv',index=False);pd.DataFrame(wide).to_csv(N/'outputs/FIVE_OPPORTUNITY_TYPES_AND_HISTORY.csv',index=False)
 summary={name:dict(existing_fact_clue_count=int(g.existing_fact_clue.sum()),no_clue_established_count=int((~g.existing_fact_clue).sum()),semantic_opportunity_UNKNOWN=len(g),automatic_confirmed_count=0)for name,g in out.groupby('opportunity_type',sort=False)}
 save(N/'FIVE_OPPORTUNITY_COVERAGE.json',dict(status='FIVE_USER_TYPES_FACT_PROJECTION_NO_NEW_SIGNAL',types=types,candidates=len(facts),type_rows=len(out),overlap_allowed=True,counts=summary,shortlist_effective_A_count=0,reason_A_zero='root primary identity/*ST conflict and actual four-chart review; AI role means do not promote',fit_count=0))
 print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
