"""Deterministic summary projection of saved comparison outputs; reads no raw truth."""
import argparse,csv,json
from pathlib import Path
from compare import load,rows,save,write,sha,FLAGS
UNION='RECOVERABLE_A_SUBPOOL_UNION_RETROSPECTIVE'
LABELS={'a_d1_premarket_pool':'保存的V4盘前子池','a_d1_fupan_watchlist_pool':'复盘观察子池','a_d1_stage7_fenshi_review_pool':'Stage7尾盘复盘子池','a_share_research_recommendation_pool':'研报文章实体提及池',UNION:'可恢复A子池离线并集（回看）'}
def main(root,slim_path):
 root=Path(root);base=root/'comparison';res=load(base/'RESULT.json');summ=[r for r in res['summary'] if r['valid_day_count']]
 assert next(r for r in summ if r['pool_id']==UNION)['N']==1627 and next(r for r in summ if r['pool_id']==UNION)['H']==95,'FIXED_REPORT_COUNTS_DRIFT'
 assert next(r for r in summ if r['pool_id']=='a_share_research_recommendation_pool')['N']==1413 and next(r for r in summ if r['pool_id']=='a_share_research_recommendation_pool')['H']==62,'FIXED_REPORT_MENTION_COUNTS_DRIFT'
 members=rows(base/'FULL_MEMBERSHIP_HIT_MISS.csv');cov=rows(base/'OLD387_COVERAGE.csv');names={(r['selection_date'],r['code']):r['name'] for r in cov}
 new=[{**r,'name':names[(r['selection_date'],r['code'])]} for r in members if r['pool_id']==UNION and r['old387_covered']=='True']
 write(root/'NEW387_COVERED_ONLY.csv',new,list(new[0]) if new else ['selection_date','code','name','sources'])
 agg={}
 for r in rows(base/'SOURCE_CONTRIBUTION.csv'):
  if r['pool_id']!=UNION:continue
  s=r['source'];a=agg.setdefault(s,dict(source=s,days=0,N=0,H=0,unique_N=0,unique_H=0,old387_covered=0,unique_old387_covered=0));a['days']+=1
  for k in ('N','H','unique_N','unique_H','old387_covered','unique_old387_covered'):a[k]+=int(r[k])
 ar=list(agg.values());write(root/'SOURCE_AGGREGATE.csv',ar,list(ar[0]) if ar else ['source'])
 daily=rows(base/'DAILY_POOL_SUMMARY.csv');ud=[r for r in daily if r['pool_id']==UNION]
 slim=dict(status='RETROSPECTIVE_DESCRIPTIVE_ONLY_INDEPENDENT_VERDICT_SEPARATE',valid_historical_premarket_dates=0,benchmark='Existing5533-code research Top100; not certified historical all-A',summary=summ,union_daily=ud,source_contribution=ar,excluded_entity_rows=res['excluded_entity_rows'],raw_entity_membership_rows=res['raw_entity_membership_rows'],new_old387_stock_dates=len(new),new_old387_distinct_codes=len({r['code'] for r in new}),gaps=res['gaps'],historical_summary='CANNOT_CONFIRM_NO_SAVED_CANONICAL_A_ALL_RESPONSE_API_TIMEOUT',formal_research_selection='NOT_MATERIALIZED_ALL_FIVE_DATES_NOT_ZERO_HIT',report_pool_semantics='Hourly research article-entity mention pool; not explicit analyst recommendation or formal shortlist',information_set='Saved pool may use overnight articles/review information; prior-close model information sets differ',**FLAGS)
 save(slim_path,slim)
 lines=['# 五日V4池回看对照','', '可恢复 A 子池的可解析股票代码子集（离线回看）precision 为 95/1627=5.84%，略高于原192的17/299=5.69%，高于主图十路的113/3894=2.90%；recall为95/500=19.0%，高于192的3.4%，低于主图十路的22.6%。这不是已证明的历史盘前胜率提高：盘前可验证日期数为0。','', '股票主分母按控制方授权排除13个原始名称明确含ETF的实体×日期：并集原实体N=1640、股票代码子集N=1627；研报实体原N=1426、股票代码子集N=1413。原实体完整名单保留于comparison/RAW_ENTITY_MEMBERSHIP.csv；EXCLUDED_ENTITY_LEDGER.csv逐项保留代码/日期/原名/原文article refs/来源SHA。未知身份隔离为CANNOT_CONFIRM，本批未知身份数为0。该修复仅身份分类与分母，未改输入/池/分数/阈值。R1旧FAIL和原输出保留在父目录及r1_preserved。', '', '五日为2026-10-16/19/20/21/22；原榜单仅既有5533代码研究池，不是认证历史全A。离线并集只读取同runtime store已保存且SHA/receipt一致的子池，不写回V4，不冒充历史a_all_pool_rows。10/20只有研报文章实体子池；其他日四个可用子池，白猫/公众号缺失未补零。','', '| 名单 | 实存日期数 | 股票×日N | 命中H | precision H/N | recall H/(100×天数) | 补原387 |','|---|---:|---:|---:|---:|---:|---:|']
 for r in summ:lines.append(f"| {LABELS.get(r['pool_id'],r['pool_id'])} | {r['valid_day_count']} | {r['N']} | {r['H']} | {r['precision']:.2%} | {r['recall']:.2%} | {r['old387_covered']} |")
 lines += ['', '四日子池只与同四日模型比较：192为11/221，主图为77/3029；四日recall分别11/400、77/400。完整逐日及同日期比较见comparison/RESULT.json和DAILY_POOL_SUMMARY.csv。','', '可恢复并集补到原387共同漏选中的49个股票×日（逐股日期表 NEW387_COVERED_ONLY.csv），各源贡献有重叠，不能直接累加；SOURCE_AGGREGATE.csv同时给独有新增。','', '研报文章池的可解析股票代码子集五日62/1413=4.39%，precision低于192、高于主图十路；recall12.4%，高于192、低于主图十路。它来自小时研报文章归集的股票实体，文章提及不代表正式看好或推荐。','', '正式研报选股接口五日均NOT_MATERIALIZED，不能当空池/0命中。汇总池精确API请求超时，没有拿到保存的canonical A-all响应；当前离线并集与正式历史汇总证据分开。文章first_source_dt仅最早贡献文章时间，不能证明完整名单09:25前可用，文件mtime未作为时间证据。Stage7标签仅作展示/来源字段，未作为本次成员筛选或打分，原producer完整PIT仍未认证。','', '保存池可能包含隔夜信息，前收盘量价模型信息集不同；五天回看不支持因果优越、稳定优势或生产晋升。D23没有收盘Top100，本批不编结果。','', '完整成员/HIT/MISS：comparison/FULL_MEMBERSHIP_HIT_MISS.csv；原387覆盖与缺口：comparison/OLD387_COVERAGE.csv、GAPS.csv；输入与时点：POOL_INPUT_MANIFEST.json、COMPARISON_CONTRACT.json、lineage_static/lineage_review_20261023/。','', 'research_only=true; production_allowed=false; buy_gate_updated=false; orders_sent=false。','']
 (root/'REPORT.md').write_text('\n'.join(lines))
 save(root/'REPORT_OUTPUT_SHA256.json',{str(p):sha(p) for p in [root/'REPORT.md',root/'NEW387_COVERED_ONLY.csv',root/'SOURCE_AGGREGATE.csv',Path(slim_path)]})
 return slim
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('root');a.add_argument('slim_path');x=a.parse_args();print(json.dumps(main(x.root,x.slim_path),ensure_ascii=False))
