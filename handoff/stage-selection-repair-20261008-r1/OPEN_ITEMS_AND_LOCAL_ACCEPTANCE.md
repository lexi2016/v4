# 仍需真实来源与本机验收的项目

基线：Issue #28 固定提交 `00524e9050fe212f87911b56eea1c2db719dd94b`，现场观测
时间为 **2026-10-08 09:50:54 +08:00**。以下计数是工单冻结证据，本次没有连接 Mac
重新读取，也不能自动外推为修复交付时的实时状态。

## 1. HK 来源及实际调用方

原 target=20261008 的 100 行 HK 池仍采用 signal=20260930，缺少合法的分日期
provenance。价格日要求 20261007，Connect 资格来源日要求 20260930。

本次可修复 supplied actual scheduler/materializer 的传递与拒绝逻辑，但源码包
没有 actual scheduler executor 与它加载的 shared owner 完整身份，也没有实际
10/7 原始行情。不能把 canonical 的较新实现或 10/5 历史支持文件当成当前 owner。

Luna Max 应先补齐实际 caller 与被加载模块的路径、SHA、调用参数和现行 pin，
确认原 producer 接收 target/price/eligibility 三个明确日期；随后使用原共享数据
reader 核对源 run、artifact、manifest、receipt、SHA 和真实 capture。
只允许合法来源产生 READY；找不到原来源时继续 CANNOT_CONFIRM。

单阶段 canary 必须用新目录、新 run_id 和准确模式，不覆盖 10/8 既有结果。
随后读回 Stage、8873 API 与页面引用的同一 run/SHA；合格后真空选才可以记为 0。
旧输入绑定失败仍应是 selected_rows=null、run/artifact 缺失。

## 2. A 行情覆盖：逐证券原因尚未给出

冻结观测：09:25 为 171/178；随后三个盘中阶段各 172/178。缺失证券清单与逐个
请求/返回明细未包含在本包，故本次逐证券排查 **NOT_RUN**，恢复覆盖 **CANNOT_CONFIRM**。

在原 TDX/tdxpy 链路保存每个缺失证券的规范化代码、请求市场、请求日期/窗口、
返回行数、供应商错误/空页原因以及相关现有回执 SHA；先确认到底是映射、窗口、
停牌/证券支持范围、连接还是资料缺口，再改对应单点。只回传最小脱敏诊断，
不上传原始价格、账户资料或完整业务响应。

178 个请求完成不等于 178 个有效来源。继续保留 PARTIAL_WITH_ROWS；有效、可追溯
的 A 汇总池可继续进入阶段，坏来源单独隔离，不能被空子池全局阻断。

## 3. 研究/新闻分数：语义与权威身份待定

工单的 09:00:25 小时归档有 9 个 stock-pool rows 和 9 个 article rows，不能
直接推导“178 候选里恰有 9 只被覆盖”：精确代码交集本次 **NOT_RUN**。

当前代码明确要求研究条目的数值 `quality_score`，不把 stock-pool 的
`research_score` 作为别名；类别 `item_quality` 不能直接转换成数值。源码位置为
`stage_center/research_context.py::load_research_context`、`_stage_rows` 及
`_stage_rows_need_source_fallback`。同时保留 witness 中 morning-news article_count=0。

下一步先核既有 producer 的权威归属、schema、数值定义、trade_date、取得时间与
不可变源 manifest/receipt，再计算候选交集和每个代码的缺失原因。
只有该合同确认后才能决定最小字段修复。当前不增加别名、不填 0、不增第二 producer。

## 4. 运行身份与自然时段证据

前四阶段 NATURAL/RECOVERY 只是声明，冻结消费者均为 execution_verified=false、
natural_verified=false。两项不能因为选择结果存在或本次离线测试通过而自动改 true。

逐 run 必须同时绑定输入、实际加载代码/配置、执行回执、记录时间和独立 receipt SHA。
历史 Stage 记载的 manifest SHA 与当前可变路径不同，应寻找那次执行的不可变原件，
不能把现文件或重建内容重新标成历史原件。原始自然证据不存在时保留
NATURAL_SLOT_UNVERIFIED；晚跑与恢复不能冒充自然时段。

API runtime_identity 的 process_status=CANNOT_CONFIRM 只表示未证实。
定时任务采样时无 PID 也不能单独判停服，应结合真实触发时间、退出状态和相应回执。

## 5. 历史来源与既有三项 P2

既有历史收盘适配三个源码文件保持不变，复用工单所载 51 focused PASS；扩展
70 PASS / 3 FAIL 的三项在基线也失败。这些都是已有证据，本次未计入新增通过数。

| 日期/风险 | 本次保持的结论 | 下一项真实证明 |
| --- | --- | --- |
| 20260825 缺来源 manifest/receipt/provenance | CANNOT_CONFIRM | 原始来源身份与 capture/PIT 证据；不可补造 |
| 20260930 capture 晚于目标收盘 | 不能判当时可用 | 原时点可取得的不可变源；后补只标恢复 |
| 20261007 在原查验根未找到上游原件 | CANNOT_CONFIRM | 定点核原 owner/缓存/运行路径；没有时如实报缺 |
| provenance 日期上界未在池 store 强制 | 保留已知 P2 | 在独立小批中证明未来来源日期拒绝且旧合法样本可读 |
| 嵌套 provenance 未严格拒绝未知字段 | 保留已知 P2 | 先冻结嵌套 schema 允许键，再做非法键回归；不得臆造白名单 |
| 8/25 输出缺显式 source/PIT 不确定标记 | 保留已知 P2 | 绑定实际输出 owner，补明确缺证标记并验证未升格 READY |

这些 P2 不属于本次已完成的源码修复，当前也没有证明它们导致已封存 canary 被升格
READY。保持现有严格 Stage validator；不以默认值、跳过校验或重写历史产物消除缺口。

## 6. 本机验收顺序

1. Luna Max 冻结届时四类 owner：API、Stage、池 scheduler 与外部发布 guard；
   按本包 before/after SHA 逐文件确认适用性。前像漂移时只移植最小差异到新候选。
2. 独立 Reviewer 先核发布工具的 guard pin、双 link 故障与 claim 恢复；生成新候选、
   新 review、完整 scope 与新计划。旧 FAIL/NOT_DEPLOYABLE/旧 finalplan 原样保留。
3. 在完整候选 app 跑 A 竞价链路和预选池回归；先单例，再扩大日期/阶段。
4. 接通并验证 HK 原 caller 的三个日期、shared owner 与真实来源，再做单阶段 canary。
5. 分别记录集成、Mac 测试、独立审查、发布、API、重载 UI 和自然时段状态。
   实际发布后核 `/api/v3/preselection-pools?date=20261008&limit=200`、
   `/api/v3/workbench/stage?date=20261008&stage=STAGE_0925&limit=10`、
   `/api/v1/runs/date-list?date=20261008`，再重载
   `http://127.0.0.1:8873/?date=20261008&stage=STAGE_0935_0940`。

本轮不操作活动 release、业务数据、采集、Stage 重跑或服务。Luna Max 是本机
唯一 Writer；独立 Reviewer 另行验收。保持 RESEARCH_ONLY 与三项 false 交易安全状态。
