# 20261013 阶段恢复 R10

本轮按用户“直接修复，不用子智能体”的最新指令，由主控直接修复与验收。未追加独立 Reviewer，不标记独立 REVIEWED/TESTED。

原问题：新阶段执行 helper 与旧运行 facade 参数不一致，snapshot_root、research_observation_contract、allow_temporal_false_observation 导致 TypeError；旧 facade 不含可选时间授权函数。修复只在支持参数时传递，缺授权函数时不授予观察合同，保留日期、来源及时间校验。

研究资料的角色审计只接受六位 A 股代码，误拒绝同日资料中的 HK.01888。domains/research.py:189 与 :215 同时接受既有 HK.五位代码；来源文件不改写，排除证据仍保留。部署只把这两处判断应用到当前运行源码，保留其原有缺口计数格式；canonical 的既有详细缺口投影不整体覆盖到旧运行包。

页面读取另误拒绝“有效 A 结果 + 无 HK 产物”的响应。现在允许严格空缺的 HK 占位响应省略身份字段，显式日期/阶段错配及有行的无身份结果仍拒绝。

验收：实际 Stage 包导入回归 13 passed；当天 09:00 原材料读回 24 个代码。实际页面构建源 API 回归 12 passed，构建成功。0930 节点按当前真实时钟补跑 exit 0 / NODES_COMPLETE；API 日期 20261013、阶段 STAGE_0930_0935，A 输入224，来源220，观察候选10，全部 WATCH_ONLY。实际8873刷新页面显示金丹科技、金冠电气等10条及涨幅、支撑、压力、失效位。

HK 未恢复：补采盘口更新在09:35截止后，HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE；未改为当时有效数据。早上原自然时段失败；当前是 RECOVERY/LATE_CATCHUP_REPLAY，NATURAL_SLOT_UNVERIFIED。其他早上阶段没有因此自动追认完成。

运行身份：Stage futu-primary-afternoon-20261013-r2-5-candidate，manifest 159e6f99a830359970e00490f639904ed3bafaa54e016649a50bf8186a841e5c；Gateway research-workbench-stage-partial-display-20261013-r10，manifest 9a0f25deb059d4f855934ff7d45693dcc6bbe35d1ebc0d513b96dcff4d063368。8873入口保持，8910原样。安全标记 RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。

证据位于本机 /Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_PAGE_REPAIR_20261013_R9/runtime_repair_R10：minimal_r2_5/actual_import_tests.log、actual_context_read.log、actual_recovery_stage0930.log；page_r10/frontend_tests.log、frontend_build.log、page_activation_receipt.json、API_STAGE0930_FINAL.json；DIRECT_REPAIR_FINAL_RECEIPT.json。UI截图在该 R9 根下 ui/10_direct_stage0930_recovery.png。

私有 GitHub 同步基线 1bbe03515ff9a063db3360e94ede2c72d0caae70，分支 codex/stage-runtime-compat-20261013-r10；仅必要源码、测试和本文，运行包、dist、原始行情及响应不上送。
