"""Publish already-computed metrics and attribution; no truth/data/model reads."""
from audit import OUT,STAGES,save,sha
from pathlib import Path
import json,pandas as pd

def publish():
 dest=OUT/'results';b=json.loads((OUT/'snapshots/STAGE_INPUT_BINDINGS.json').read_text());cells=pd.read_csv(dest/'stage_cells.csv',dtype={'trade_date':str});wins=pd.read_csv(dest/'daily_top100_stage_hits.csv',dtype={'trade_date':str,'ts_code':str});rows=[]
 for _,r in wins.iterrows():
  for s in STAGES:
   c=cells[(cells.trade_date==r.trade_date)&(cells.stage==s)].iloc[0];bi=b.get(f'{r.trade_date}/{s}/A_SHARE',{});pool=set(bi['codes']) if 'codes'in bi else None;hit=r[s];hitval=str(hit).lower()=='true';available=pd.notna(c.actual_selected_count)
   inpool=r.ts_code in pool if pool is not None else None
   reason='SELECTED' if pd.notna(hit) and hitval else 'MISSING_SELECTION_EVIDENCE' if not available else 'INITIAL_POOL_MEMBERSHIP_CANNOT_CONFIRM' if pool is None else 'NOT_IN_BOUND_INITIAL_POOL' if not inpool else 'IN_BOUND_INITIAL_POOL_NOT_SELECTED'
   rows.append(dict(trade_date=r.trade_date,stage=s,ts_code=r.ts_code,name=r['name'],daily_rank=r.daily_rank,return_pct=r.return_pct,selected=hitval if pd.notna(hit) else None,bound_initial_pool_member=inpool,known_miss_classification=reason,candidate_binding=bi.get('qualification'),candidate_pool_count=bi.get('candidate_pool_count'),dispatch_mode=bi.get('dispatch_mode'),recorded_at=bi.get('recorded_at'),natural_verified=False))
 assert sum(x['selected'] is True for x in rows)==int(cells.hit_count.fillna(0).sum()),'ATTRIBUTION_HIT_COUNT_CONFLICT'
 pd.DataFrame(rows).to_csv(dest/'stage_miss_attribution.csv',index=False)
 # Strengthen temporal labels using saved receipt identity without upgrading natural verification.
 temporal=[]
 for _,c in cells.iterrows():
  bi=b.get(f'{c.trade_date}/{c.stage}/A_SHARE',{});mode=bi.get('dispatch_mode');qual='SAVED_RECOVERY_DESCRIPTIVE_ONLY' if mode in ['RECOVERY','OPERATOR_RECOVERY'] else 'DECLARED_NATURAL_RECEIPT_NOT_INDEPENDENTLY_NATURAL_VERIFIED' if mode=='NATURAL' else 'RECORD_TIMING_UNKNOWN_DESCRIPTIVE_ONLY'
  temporal.append(dict(trade_date=c.trade_date,stage=c.stage,dispatch_mode=mode,recorded_at=bi.get('recorded_at'),temporal_qualification=qual,selection_state=c.selection_state,natural_verified=False,late_stage_predictive=False))
 pd.DataFrame(temporal).to_csv(dest/'temporal_qualification.csv',index=False)
 # Explicit precision treatment for selected stocks absent qualified truth.
 obs=cells[cells.actual_selected_count.notna()].copy();missing=int(obs.selected_truth_missing_count.fillna(0).sum());sums=pd.read_csv(dest/'stage_summary.csv')
 for i,r in sums.iterrows():
  c=obs[obs.stage.eq(r.stage)];unknown=int(c.selected_truth_missing_count.fillna(0).sum());known=int(r.actual_selection_slots)-unknown;sums.loc[i,'unknown_qualified_return_slots']=unknown;sums.loc[i,'known_qualified_return_slots']=known;sums.loc[i,'known_label_precision']=int(r.hit_count)/known if known else None;sums.loc[i,'observed_match_fraction']=r.hit_precision
 sums.to_csv(dest/'stage_summary.csv',index=False)
 summary=json.loads((dest/'RESULT.json').read_text());summary.update(selected_observations_missing_qualified_return=missing,benchmark_membership_definition='Top100 strict members of qualified available panel; selected codes outside qualified panel are not reference-set hits, actual full-A hit cannot be confirmed',pooled_precision=summary['hit_count']/summary['selection_slots'],pooled_precision_note='Stage observations weighted by actual selected slots; repeated stock/date across stages is counted again; not daily-union recall',known_qualified_return_slots=int(summary['selection_slots']-missing),known_label_precision=summary['hit_count']/(summary['selection_slots']-missing),observed_match_fraction=summary['hit_count']/summary['selection_slots'],full20_allstages_recall='CANNOT_CONFIRM_MISSING_CELLS',first_canary='canary/RESULT.json rejected due writer hashing convention',accepted_writer_canary='canary_r3b/RESULT.json (independent acceptance pending)',exactstage_fullinput_bound_cells=sum('codes'in x for x in b.values()))
 save(dest/'RESULT.json',summary)
 # Preserve original result manifest separately; final publication manifest includes supplement.
 manifest={str(p.relative_to(dest)):sha(p) for p in dest.iterdir() if p.is_file() and p.name not in ['PUBLICATION_MANIFEST.json','OUTPUT_MANIFEST.json']}
 save(dest/'PUBLICATION_MANIFEST.json',manifest);save(dest/'OUTPUT_MANIFEST.json',manifest)
 src=Path(__file__).parent;save(OUT/'SOURCE_MANIFEST.json',dict(source_root=str(src),files={p.name:sha(p) for p in src.glob('*.py')},baseline_commit='55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054',changed_source_allowlist=[str(p) for p in sorted(src.glob('*.py'))],commit='NOT_COMMITTED',push='NOT_PUSHED',canonical_modified=False))
 binding=json.loads((OUT/'snapshots/SAVED_VERIFIER_BINDING.json').read_text());assert all(sha(p)==h for p,h in binding['refs'].items()),'UPSTREAM_VERIFIER_SOURCE_DRIFT'
 save(OUT/'FINAL_INPUT_MANIFEST.json',dict(frozen_input_binding_sha256=sha(OUT/'INPUT_BINDING.json'),calendar_sha256=sha(OUT/'CALENDAR.json'),initial_capture_manifest_sha256=sha(OUT/'snapshots/CAPTURE_MANIFEST.json'),supplement_files={str(p.relative_to(OUT)):sha(p) for root in ['snapshots/runner_receipts','snapshots/candidate_inputs','snapshots/verified_store'] for p in (OUT/root).rglob('*') if p.is_file()},stage_input_bindings_sha256=sha(OUT/'snapshots/STAGE_INPUT_BINDINGS.json'),verifier_binding_sha256=sha(OUT/'snapshots/SAVED_VERIFIER_BINDING.json')))
 total=summary['hit_count'];slots=summary['selection_slots'];days=pd.read_csv(dest/'daily_summary.csv');last=pd.read_csv(dest/'last5_selected_stocks.csv');text=f'''# V4 A股阶段二次选股：最近20交易日描述性审计

范围为2026-09-18至2026-10-23的20个A股交易日，固定7阶段、140个单元。**122个单元有有效保存名单，18个缺失；1220个实际入选席位中247个命中当前可用研究面板的每日收盘收益Top100，已观察Top100匹配比例20.2459%（247/1220）。** 此比率按阶段观察计数，同日同票跨阶段重复计入；不等于20日每日并集召回，也不代表全A或预测收益。

基准全称：`AVAILABLE_CURRENT_RESEARCH_PANEL_TOP100_QFQ_RETURN`。当前权威面板 generation=`e312447244a0b21c003435177645b9ca9910abe12880c7936acf16fa5e7f73e4`、asof=20261023。使用精确A_SHARE记录，排除producer标注的legacy身份/价格基础不明代码；每日有效收益记录5168–5205只，未认证完整全A成员。结果最高为`DIRECTION_ONLY`，完整全A Top100与历史PIT均为`CANNOT_CONFIRM`。

收盘收益复用原producer定义`100*(close/pre_close-1)`：QFQ同一asof价格基础，pre_close由前收盘及XD/R处理产生，不把此字段用作选股特征。按收益降序、ts_code升序确定严格100只；边界同收益以代码打破并列。每个阶段名单来自不可变CSV/manifest/receipt，经当前V4的`SelectionStore.read_verified`验证；API仅为捕获时的显示与状态证据，显示limit不构成输入上限。

|阶段|有效/20|实际席位|命中|观察匹配比例|已知收益席位|未知收益席位|已知标签精确率|有效单元Top100召回|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
'''
 for _,r in sums.iterrows():text+=f"|{r.stage}|{int(r.available_cells)}/20|{int(r.actual_selection_slots)}|{int(r.hit_count)}|{r.hit_precision:.2%}|{int(r.known_qualified_return_slots)}|{int(r.unknown_qualified_return_slots)}|{r.known_label_precision:.2%}|{r.top100_recall:.2%}|\n"
 text+='''
已知合格收益席位1176，未知44；仅已知标签精确率为247/1176=21.0034%。247/1220只表示全部实际席位中已观察匹配比例，未知保留在分母；真实全A精确率不能确认。

全部阶段的Top100观察分母为12200（122有效阶段×100），与每日不同股票Top100分母2000分开。缺失单元保留null，不能按零命中补齐。9月28日全部7阶段缺失；其余缺失见stage_cells.csv。缺失天不从20日日历中删除。

最近5日逐票明细位于`results/last5_selected_stocks.csv`：10月19、20、21、22、23日，340个入选观察及10月23日09:25缺失单元占位。包含代码、名称、原入选名次/分数、收盘收益、全基准日内排名和命中。29个最近5日入选观察缺少合格收盘数据；所有20日共44个，收益/排名/实际全A命中未知，不能编造零涨幅。3个入选观察名称缺失，原始代码完整；这些缺口原样保留。命中247指已证明属于该固定基准Top100的观察；基准外代码不会算为参考集合命中，无法据此判断真实全A表现。

完整初始池与阶段实际行情采集记录分开：62个阶段找回并按candidate_run_id、pool provenance SHA、trio/commit hash链、code去重和数量绑定其原始完整候选codes；其他阶段初始池保持未知，不把stage source_rows或捕获时的展示池冒充原始池。`stage_cells.csv`给出这些阶段的初始池Top100覆盖、screen_retention及越界入选数；捕获时完整分页A池统计单独列示。坏/缺失子池不全局阻断有效codes。`stage_miss_attribution.csv`逐Top100股票×阶段区分“未进已绑定初始池”“进池未入选”“缺失选股证据”“初始池未知”；不归因于未执行的模型分析。未绑定完整上游历史排序，不做同K重排对照。

保存名单包含NATURAL、RECOVERY与OPERATOR_RECOVERY声明；全部natural_verified=false。`temporal_qualification.csv`保留原记录时间和dispatch_mode，不把回补、回看或捕获后状态说成当时可用预测。14:45–15:00阶段仅作同日收盘描述，不能宣称前瞻预测。历史PYTDX错误来自10月23日保存收据；本批只执行GET和本地读，当前GET静态调用链经确认只读，未调用ensure/replay、采集、训练或重选。

验证：6个有意义边界测试通过（missing!=zero、并列严格100、收益、重复、候选成员与实际分母、无效价格）；10月22日单日canary验证7单元/70席位/9命中及已绑定初始池成员约束后才运行20日。首次字符串日期过滤类型错误、首次JSON字节/规范化哈希误判以及一次部署源码布局绑定错误均已保留并登记；无覆盖原始证据、无重复市场抓取。Writer完成不是独立验收。独立Reviewer结论以root保留收据为准。

复现：使用绝对`PANEL_PYTHON`；`audit.py full`只读取本批不可变快照（默认results目录已存在时拒绝覆盖）。原始捕获不需重复。`SOURCE_MANIFEST.json`绑定源码；`FINAL_INPUT_MANIFEST.json`、`results/PUBLICATION_MANIFEST.json`绑定输入/结果。只读审计未改模型、正式池、BUY gate、服务或计划任务；`RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false`。
'''
 (OUT/'REPORT.md').write_text(text);(OUT/'README.md').write_text('读取[REPORT.md](REPORT.md)；数值入口[results/RESULT.json](results/RESULT.json)，逐日/阶段/最近5日CSV见results/。本批为保存名单与可用研究面板Top100的描述性审计，独立验收待Reviewer。\n')
 print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':publish()
