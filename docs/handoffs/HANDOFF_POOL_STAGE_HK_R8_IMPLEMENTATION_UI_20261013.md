预选池、阶段选股与港股复盘：R8 实施与验收记录（2026-10-13）

本轮代码整理已分批实施并通过独立 Luna Max 复核。实际 8873 的稳定加载页面和 API 读回已通过限定目标验收；自然时段仍为 NATURAL_SLOT_UNVERIFIED。代码通过不代表港股历史观察数据已满足 PIT 或正式入选条件。

| 批次 | 实际结果 | 独立验收 |
|---|---|---|
| 0 运行绑定 | 固定 API、预选池/复盘调度、阶段调度、deadline 的不同源码根、数据根与文件指纹 | 运行身份核对；保留原版本与回退记录 |
| 1 预选池 | 有效、可追溯 A 池完整汇总进入阶段输入；逐池隔离缺失/空/partial/明确损坏，目录与锁错误仍阻断 | 20 项针对性测试；WATCH_ONLY、缺口与来源保留 |
| 2 阶段执行 | 被覆盖的重复 builder 构造删除，只构造一次 | 5 项；算法、过滤、保存次序及路由保留 |
| 3 港股复盘 | 收敛收盘采集入口；明确缺失/损坏/过期与旧文件兼容；富途时间不采用缓存 mtime | 31 项；研究标记与来源安全保留 |
| 4 页面读取 | 请求集中到 api/pool_stage.ts；校验日期/阶段/研究安全；页面分页与完整候选输入分离 | 客户端与分页验收；实际 market-map 格式误判另补 10 项回归 |
| 5 无调用代码 | 删除确认无调用的合并函数和重复包装，共 127 行 | 静态/动态调用核对；29 passed、1 skipped 及运行 canary |
| 6 集成 | 补齐实际 owner 所需依赖，保留非本轮字节；新前端重建；四个服务绑定已接入 | 6A 55 项与 5 个 fail-closed 探针；调度 13+20 项；新包准备 16 项；落盘身份 14 项 |

唯一源码为 /Users/lexi/Desktop/学习/v4_app。8873 入口与 Vibe 8910 保留；A/HK 分离，HK 仍采用精确前一交易日港股通 Top100。RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。

实际页面验收由主控在原用户浏览器执行，另一 agent 独立核对接口、文件指纹和截图。20261012 的八个阶段稳定加载后均显示正确阶段及 PARTIAL_WITH_ROWS；前七阶段 A10/HK10，末阶段 A0/HK10。14:45–15:00 与 15:45–15:55 港股涨幅、支撑位、压力位、失效位与同日期 API 一致。来源展开保留 run_id/SHA/截止时间与缺口，观察行没有升为正式可用。

预选池页面验证：20261012 共 371 行，第二页 171 行；20261013 共 224 行，第二页 24 行；日期切换重置分页。页面每页 200 行不改变后台完整输入。

20261012 收盘 Top20 为 20；0.2 正式候选 100 行、命中 8/20；正式七阶段并集缺证，仍显示不可用；部分研究观察并集为 70 行、26 个去重代码、命中 7/20。20261013 未生成复盘明确显示 CLOSE_REVIEW_ARTIFACT_MISSING，没有显示为 0 命中。新资产 main-BJEBfXeV.js 的实际服务字节与候选一致。

保留的缺口：

- 独立 Reviewer 认定两项页面 P2 不阻断本轮稳定加载目标：20261013 尚未生成阶段的具体 API 缺失原因被简化为通用重试提示；快速切换日期并立即点击阶段时，曾停在旧阶段，重选后正常。延迟网络下是否持续出现尚未验证。
- 自然时段验收未执行；本轮页面读取属于手动历史/当日缺失核对，不冒充自然选股。
- 全量类型检查仍有 4 项范围外诊断，App 测试仍有 1 个 0.2 文案断言失败；补充旧锁测试有 4 个 fixture 在行为执行前 AttributeError，相关旧 store 路径 CANNOT_CONFIRM。本轮针对性独立验收通过，不声称全量测试全绿。
- 调度候选最初放桌面，后台脚本遭 macOS 拒绝访问并退出 126；已精确恢复旧版本，再将同一已复核候选放到现有 Application Support 服务目录。新版本已有运行心跳，未修改系统权限。
- 调度构建报告有一项过时 missing_rebound_paths 提示；实际启动配置经独立校验正确。该项 P2 保留。
- 港股历史盘口和 PIT 等原数据缺口仍保留；本轮整理没有新增历史行情采集或第二 producer。

源码基线：55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054。私有对应分支 codex/pool-stage-hk-review-implementation-20261012-r8 的源码同步提交 c9231d066e3b0080c806d599f19af8944012920b：34 个必要源码/依赖文件及 208 个 diff 区段的行号清单，远端 35 个文件 blob 一致，3725 个未涉及的父提交文件保留，5 个关键文件 UTF-8 内容逐字节读回一致。未上传原始行情、运行数据、凭证或 dist；不声称仓库整体运行依赖全部闭环。

详细证据：

- [机器交付记录](/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_IMPLEMENTATION_20261012_R8/FINAL_DELIVERY_RECEIPT_R8.json)
- [修改行号与前后指纹](/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_IMPLEMENTATION_20261012_R8/REVIEWED_CHANGE_LINE_MAP_R8.json)
- [独立 API/页面验收](/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_IMPLEMENTATION_20261012_R8/batch6b_review_final/live_ui_adjudication/PHASE_POSTDEPLOY_API_UI_REVIEW_R8.md)
- [来源代码远端读回](/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_IMPLEMENTATION_20261012_R8/BATCH6B_SOURCE_SYNC_RECEIPT_R8.json)
- [实际浏览器证据](/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_IMPLEMENTATION_20261012_R8/ROOT_LIVE_UI_REACCEPTANCE_R8.json)

![20261012 15:45–15:55 港股阶段实际页面](/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_IMPLEMENTATION_20261012_R8/ui/live_r8/25_final_date12_stage8_loaded.jpg)
