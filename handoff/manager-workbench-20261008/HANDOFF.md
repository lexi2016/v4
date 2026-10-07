# 经理工作台 · 2026-10-08 研究名单与页面交接

交接日期：2026-10-07。用户原话：“那现在我要准备10.8的交易我要怎么看经理工作台选股，我觉得页面挺乱的，我根本看不到选股。”随后要求：“你写个交接文档出来。”

本轮交付仅为交接文档；未生成新计划、未导入10月7日公告、未修改业务代码、未部署或启停服务。下文接手顺序是待办，不代表已经执行。

## 当前结论

公告跨日期修复已完成独立验收；**10月8日统一研究备选名单尚未生成，页面又将研究内容、历史参考和诊断信息混在一起，用户无法直接找到选股结果。** 后续需要同时补齐真实名单和清楚的首屏展示。不能把“研究重点名单（0）”解释成已完整筛选后没有股票。

当前查看入口：

http://127.0.0.1:8873/manager-selection/?date=20261007&announcement_date=20261007&plan_date=20261008

三个日期分别表示：`plan_date` 为计划目标日10月8日，`date` 为阶段参考日10月7日，`announcement_date` 为独立公告发布日期10月7日。不能将三个日期统一替换而不核实合同。

以下状态来自本会话10月7日晚约19:41的页面读取，是观察快照；接手时须核对最新运行身份及数据状态。

| 内容 | 当时实际状态 | 对10月8日的含义 |
|---|---|---|
| 10月7日公告 | 目录 NOT_RUN，分析 NOT_ASSESSED；ANNOUNCEMENT_DATE_CATALOG_NOT_RUN | 尚未导入并分析目标公告日 |
| 10月8日计划 | NOT_MATERIALIZED、未冻结；读取 VERIFIED_WITH_GAPS | 没有已保存并可验收的当日计划 |
| 研究重点名单 | 页面显示（0），owner未返回有效名单 | 未生成/未知，不能冒充有效零结果 |
| 10月8日美股日常映射 | NOT_RUN，来源美股日与cutoff未知 | 旧面板READY不能替代目标日映射 |
| 阶段正式结果 | CANNOT_CONFIRM，目标日资格未知 | 不能把历史参考升格为当日正式选股 |
| 10月7日收盘观察 | 未物化 | 需与负责该链路的会话协调 |
| 超跌与15:30研究槽 | 无法完整判定；槽显示NOT_RUN及未到时段状态 | 不据此生成肯定结论，日期/时段语义待核 |

该次查看只切换目标日期、读取页面，没有点击“用既有材料生成计划”或“更新公告”。

## 已完成成果：复用，不重新从头修

上一批目录：`/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_DAILY_REPAIR_20261007`。

同一 `announcement-daily-20261007-r2` 发布版本已经独立完成两日期存储/API/UI读回：

| 目标日 / 公告日 | 研究入选 | 条件观察 | 未入选 | 未评估 |
|---|---:|---:|---:|---:|
| 2026-09-30 / 2026-09-29 | 23 | 10 | 103 | 4 |
| 2026-10-07 / 2026-10-06 | 7 | 8 | 429 | 80 |

新日目录580篇、30页、584个来源代码关联、524个不同来源代码；540篇API正文完整、40篇不足。这里的“新日”是上一批10月7日目标，不是本交接的10月8日目标。7只研究入选包含风险事件研究，不能当成10月8日可交易名单，也不能等同正面催化或BUY信号。

独立验证记录：39项后端、13项前端、25项运维检查，以及发布身份、回滚生命周期、存储/API/页面两日期读回。保留4条既有spec类型诊断与5条pytest清理警告；不得宣称全量类型检查通过。

上一批的 IMPLEMENTED / TESTED / REVIEWED / INTEGRATED / DEPLOYED / API_VERIFIED / UI_VERIFIED 仅适用于其冻结范围。10月8日名单、计划与新页面行为仍未验收；NATURAL_VERIFIED 不成立。发行人数、港股通资格、首发时间、PIT/盘前可用性、PDF印刷页码仍有 CANNOT_CONFIRM。

## 基线、运行身份与证据

唯一源码根：`/Users/lexi/Desktop/学习/v4_app`。本地canonical有大量既存tracked/untracked及并行修改，不能整体提交、覆盖或当作上一批冻结快照。

上一批私有仓库 `lexi2016/v4`：
- 分支：`codex/announcement-daily-repair-20261007`
- 固定commit：`a7732310a5262b59c95a30fdf5d7bedc9910939f`
- 已记录远端commit及23个必要blob核验。

上一批约19:25—19:34验收时运行身份：
- API release：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-daily-20261007-r2/app`
- PID：13550；manifest SHA：`dffcde634d7eed5c088b202e9128e11296923b93e2053fd184876be85c638b59`
- 保留的Stage app.py SHA：`909bdccecadf36c70f791a2c4c0d818371f4da68762e4cff40f9786e4613f80e`
- 10月6日公告分析产品 SHA：`7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278`
- 目录run：`b640f4477a1c43569f225d139cdf8669`；目录SHA：`b01d28d9c27e511479b7bcdce45c62918895fd6cdaf782631c50eec45361b7a7`

这些是已验收历史身份，**不能保证接手时仍是现役版本**。会话“制定港股阶段修复计划”（`01a0ff4f-2b8f-7311-add9-cba3f560cc4d`）另负责HK收盘链路，已获知上一批发布结束并可继续协调发布。8873为共享入口，接手先核现役API、Stage、manifest及该会话的发布进度，不能盲目回退R2。

优先读取以下精简证据；必要时才沿receipt深入：
- `V4_ANNOUNCEMENT_DAILY_REPAIR_20261007/FINAL_DELIVERY.md`
- `V4_ANNOUNCEMENT_DAILY_REPAIR_20261007/FINAL_CLOSURE_RECEIPT.json`
- `V4_ANNOUNCEMENT_DAILY_REPAIR_20261007/GITHUB_FINAL_SYNC_RECEIPT.json`
- 页面观察截图：`/Users/lexi/.codex/visualizations/2026/10/03/01a0ff4e-909d-7c40-9dd8-0aec40abcb42/manager-workbench-20261008-current.jpg`

上一批首次启动竞态与目录run绑定误判的失败证据已保留，后续修复通过。不要删除失败记录或盲重跑10月7日一次性导入脚本来处理10月8日。

## 接手顺序与验收目标

1. 核实当前运行身份及既有owner。按目标日10月8日、公告日10月7日冻结输入、source/cutoff、run与SHA。核对公告、US映射、收盘观察及计划owner；沿既有链路处理，不能新建producer补缺。
2. 使用10月7日实际公告材料完成可追溯分析；沿既有US映射链确定适用美股交易日和cutoff。晚间初稿与盘前完整材料分别标识，不能预先假设美股收盘数据已到齐或PIT安全。
3. 沿既有计划生成/保存/读取路径，产出并读回10月8日研究名单。复核 `workspace_plans` / `workspace_plan_runs` 的对应关系，以实际owner合同为准。每只股票保留代码、名称、入选原因、来源日期及身份、条件、风险、缺口；不复制上一日结论凑名单。
4. 整理同一经理工作台首屏：清楚显示目标日、名单是否已生成/保存、股票列表和可读理由；来源原文、历史参考及技术诊断放详情。未生成显示“尚未生成”，有效空结果才显示0。首屏不将风险研究入选误导为买入推荐。
5. 独立Reviewer验证目标行为，绑定同一日期/run/SHA完成存储→API→刷新页面读回；旧日参考继续正确。只在实际自然时段有证据后报告 NATURAL_VERIFIED。

上述是待授权实施时的交接顺序。本轮没有实施。实施前按现役差异冻结 GOAL、唯一Luna Max WRITER、独立Luna Max REVIEWER、精确 ALLOWED_PATHS / FORBIDDEN_PATHS、PASS_SIGNAL、STOP_RULE。候选定位入口包括 `v4/manager_research/workspace_plan*.py`、`workspace_actions.py`、`workspace_announcements.py`、`plan_owner_dispatch.py` 及 `apps/web/src/views/ManagerSelectionView.vue`；这些是定位提示，不是已批准的修改路径。

目标PASS_SIGNAL：用户打开10月8日经理工作台，即可看到实际已生成且可追溯的当日研究名单、清楚理由/条件/风险，以及准确缺口；保存结果、API与页面身份一致。若仍未生成，应清楚说明原因，不能以页面可见或HTTP 200代替完成。

## 不可越过的边界

- 保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
- 不建第二面板、第二权威数据层或平行producer；Vibe 8910保持原样。
- 普通历史行情补采沿现有tdxpy/TDX缓存优先路径，并保留日期/市场/来源；不静默消耗Futu历史额度。
- A/HK分离；A股有效可追溯子池可参与汇总，坏来源隔离，不能因partial子池全局阻断，不能用200行显示截断作为选股输入。
- 复用已通过且代码/输入/配置/范围未变的receipt；新目标日期和新页面行为单独验收。
- 发布前协调共享8873；本交接不授权merge、交易或无关服务变更。

本交接文档独立同步分支：`codex/manager-workbench-20261008-handoff`，从上述固定commit建立，仅新增本交接；同步结果与文档SHA另存同目录receipt。业务测试、部署和自然时段检查本轮均 NOT_RUN。

