# 真实输入、依赖闭包与运行验收缺口

依据固定问题包 `09f82ac665e36a002e7f67f949b7e38f4e0598bf` 及其 `source_index.json`，区分下游修复、上游生产条件和正式运行证据。本文中的现场事实来自问题包冻结证据；本轮未查询或更改 Mac 服务。

## 影响每日业务结果的原上游条件

| 原链路 | 已证事实 | 本轮接续边界 | 尚需原 owner 提供的事实 |
| --- | --- | --- | --- |
| US 采集 → 每日映射 | actual scheduler 的 `contracts/runtime_workloads.json` SHA `7389cae30de08cf68c31e5b0bb6f5b17fead403366946496b7a4de148229d0ef` 中，`us_market_digest.enabled=false`；owner 是原 `v35_dispatcher`。actual `infrastructure/scheduling/_executor_registry_parts/us_digest.py` 在索引中为 `MISSING_NOT_SUBSTITUTED`。 | 调用已有 `refresh_us_mapping_research`，按原 US 日历、目标日、真实 cutoff、精确 completed session 和 registry availability 验证、保存、读回；失败独立返回。 | 核 actual 原采集执行器、依赖闭包与绑定；在受保护集成和正式授权下恢复原任务，或证明另一既有原 owner 已持续自然供源。canonical 同名 workload 的 enabled=true 及 v4 owner 不能代替 actual 事实。 |
| 公告抓取 → 审核产品 → 计划 | 原公告 cycle 负责采集，原分析接口消费单独导入并验证的 reviewed product。所给源码与回执没有证明自动 Reader/Reviewer 产品生产链已启用。 | 合法新产品到达后，原 owner 校验 target/publication/SHA，按原 SELECTED/WATCH/未评估语义自动进入后续计划。 | 原 reviewed-product producer 的入口、owner、触发方式及 Reader/Reviewer/import receipts。仅抓取或轮询不能生成审核决定；不能为通过自动化验收而合成研究结论。 |
| HK capture → membership/master/V2 → 超跌 | actual HK child 入口 SHA `07aa9770…` 原先只完成 HK02，未调用已有 gate/ensure。10/8 缺同次完整发布链；10/7 精确历史资格、单位/finality 证据仍有缺口。 | 复用原 capture、gate、ensure、原缓存优先 TDX 日线补缺链，按首个失败阶段返回真实回执；原筛选规则继续执行。 | 原日期、同次 capture 的不可变证据和真实 availability；必要历史价格、合法 membership、单位与 finality。今日报价或板块集合不能充当旧日资格，晚间数据不能回填成盘前已知。 |

10/7 US 源 payload/receipt/manifest 已就绪只支持核验 10/8 对应输入，不能证明之后每天都会供源。固定配置标的范围与 reviewed US→HK 关系范围也不同；UI 数量必须取实际 DTO，不能硬编码历史 33、4、87 等数量。HK_CONNECT 保持资格通道，不计作 US 映射。

## 本云端切片不能证明的完整应用依赖

| 缺口 | 可复现范围 | 结论边界 |
| --- | --- | --- |
| `stage_center._selection_parts._namespace` 未在所给混合源码闭包中找到 | 干净导入 `infrastructure.scheduling.manager_announcement_supervisor` 或 `ops.render_manager_announcement_binding`，经原 scheduling→dispatcher→executor_registry→daily_materialize→Stage 导入链失败。 | `CLOUD_SHARED_IMPORT_CLOSURE_BLOCKED`。可以验证独立原模块和受限接线；不能称完整 renderer CLI、worker 或共享入口已在云端通过。不得新增 Stage shim 或改无关 Stage 来掩盖。此缺失不证明 Mac 实际应用也缺该文件。 |
| 原 binding inventory 要求的 `apps/__init__.py` 没有提供原字节/逐文件身份 | 冻结09树无此路径；现有 aggregate inventory/manifest SHA 无法反推文件内容。`apps/api/__init__.py` 有可追溯的41B canonical原件，但不替代缺失的上级 marker。 | `CLOUD_BINDING_INVENTORY_CLOSURE_GAP`。真实 renderer 对当前装配根的 inventory 验证不能通过；enabled 配置输出的合成 inventory 合同测试须单列。不得删除 required pin 或补造空 marker。实际 app 的完整 inventory 待唯一 owner 核验。 |
| 普通页原父级依赖 `apps/web/src/api/managerAnnouncementAnalysis.ts`、`apps/web/src/manager-selection/announcementAnalysis.ts` 未在提供的冻结树/本地源码中找到 | 原 ManagerSelectionView → catalystObservationPanel 的完整构建。 | 只能按最终实际测试范围报告 renderer、组件/DOM和限定类型检查；不得 stub 原特性后声称完整普通页或现场 UI 通过。唯一集成 owner 须使用实际完整 web 源码核验。 |
| API、scheduler、HK child、web、隔离候选来源不同 | source_index 与逐文件前像。 | 本交付是模块差异，不是完整可部署应用；不能整树复制。 |

## 发布时必须绑定实际根

- API：当前 8873 的受保护累计集成候选，沿用当前注入的 service、reader、store 与源根。
- HK child：原 scheduler 实际选中的 child 应用根；主入口必须匹配 `07aa9770…` 前像，不是 canonical 小入口。
- HK upstream：`resolve(actual V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT).parents[1]` 所属包根，目标为 `shared_data/hk_daily_supplement.py`。必须核实际 updater 路径/SHA，以及真正导入的 supplement `__file__` 和 `5528a6b4…` 前像。当前绝对路径为 `HOST_ROOT_MAPPING_UNVERIFIED`；本地 `upstreams/v3_shared_data/` 目录名不是部署路径。
- Scheduler：原共享入口 owner 的实际应用根。工作配置与调用模块逐项合并，不复制 canonical 整份 workloads，不替换共享 daemon。
- Web：实际普通经理页面的完整源码根；由同一受保护集成构建。

新增 namespace 文件的前像为“提供的切片中缺失”，不等于现场 ABSENT。若现场存在，必须比对并由集成 owner 解决；不能覆盖未知版本。

## 正式验收尚需取得的证据

1. Issue #30 发布保护独立验收、唯一集成 owner 的累计基线与 before/after gate；经理功能与 #28 预选池共同验收。局部文件未改只能证明本轮改动范围，不能证明现场 #28 已保留。
2. 真正的 10/8 事后补算：原 owner、真实执行时间、target/cutoff/source session、run/SHA/immutable attempt、同日计划、API 和普通页面。若执行已在 10/9，US10/8 不能替代 target10/8 应读的 US10/7；结果标 retrospective，不倒签盘前。
3. 跨日隔离回归与至少两个连续适用 HK 交易日的原自然 dispatch → 原输入 → daily owner → 同日计划 → API → 普通页重新加载。两日需由原日历核验；人工 POST、单次成功、健康端口、空 daemon cycle 都不代替此链。
4. 9/30 原 run 的 `HISTORY_SOURCE_INPUTS_CHANGED`：只有拒绝点得到真实读回，尚无原与重验各组件输入摘要，不能判断具体 source 变化或 reader context 漂移。后续只读比较，保持原封存文件和拒绝，不因此阻塞未来日期交付。

本问题包明确当前轮交付代码、测试和 Mac 执行交接，未授权 Mac 补采、POST、启停、启用或部署。正式运行项按实际证据单列；自然时段尚未观察统一为 `NATURAL_SLOT_UNVERIFIED`。

研究边界：`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
