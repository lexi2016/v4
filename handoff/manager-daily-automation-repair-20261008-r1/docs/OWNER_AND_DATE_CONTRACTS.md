# 原 owner、日期与回执的对应关系

以下是本轮受限接线应遵守的合同；通过情况以 `TESTING.md` 和独立 review 记录为准。它们不证明现场已启用。

## 原 owner 与接续

| 阶段 | 保留的原 owner / 入口 | 本轮连接点 | 成果与拒绝的判断 |
| --- | --- | --- | --- |
| 每日调用 | 现有 AnnouncementCycleHook → 绑定应用根的 `ops/run_manager_announcement_cycle.py` | daily 配置选择目标/时段，调用同一个 8873 注入 service 的 `/workspace/daily-cycle`；旧 scheduled 入口保留兼容。 | binding SHA、source inventory、Python/root、交易日、时段和幂等 trigger 全部验证。每日调用成功不等于每路研究已完成。 |
| US 原数据 | 原 `external_finance` store 与 `ResearchPeripheralUsMarketReader` | 在 MORNING / 有限 SAME_DAY_CATCHUP 调用原 `refresh_us_mapping_research`，使用单独最多5秒预算；PREOPEN 不新增 US owner 调用。 | 精确 completed session 与原 payload/receipt/manifest/registry availability。缺失、忙、超时保持完整 DTO 及 unknown/null；不取另一个日期的 latest。 |
| US 研究保存 | `persist_daily_run` / 原 manager store | 同 target 的不可变 daily run、pointer 和独立 dispatch receipt；同 trigger 重放、同输入复用、未完成写入的受限恢复。 | `us_mapping_research/<date>/runs/<run>.json`、同日 `latest.json`；`us_mapping_dispatch/<date>/` 保存调用阶段。运行结果、artifact验证和最新调用尝试分别记录。 |
| 公告 | 原 capture / reviewed product validator / import / workspace consumer | 合法已审核产品到达后被下一原续算消费；无另一路抓取或合成审核结论。 | target/publication/product/import/source SHA 必须一致；保留原 SELECTED、WATCH、未评估、股票及理由。 |
| HK 同次发布 | actual HK child `07aa9770…` 中的原 HK runner → 已有 capture gate / ensure | 同次 capture 接续 membership/V2、HK02、master、最终读回与原补缺 owner；按阶段返回成果和首个失败点。 | 不以 panel-only READY 当完整资格/主表链。缺旧 capture 不用今日板块集补造历史；available_at 保持真实。 |
| HK 日线补缺 | 原 `shared_data.hk_daily_supplement.capture_daily_supplement`，原 updater `--daily-supplement` | 缓存优先；按原6个证券 sessions 和精确 parent 身份验证，必要时沿原 TDX/tdxpy链补缺。 | 保留实际缺日、volume unit/price basis/finality。价格 sidecar 不替代历史资格或单位证明。 |
| 同日计划 | 原 `ManagerResearchJobService.refresh_workspace_plan` | 原 MORNING/PREOPEN/EVENING_NEXT_SESSION 和有限迟到补算；单路失败与其它有效成果分别保存。 | `workspace_plans/<date>/<run>.json` 与 `latest.json`；`workspace_plan_runs/<date>/<run>.json` 和最新 attempt。保存徽标依据同 run 的封存 attempt 与产品精确读回。 |
| 普通页面 | 原 ManagerSelectionView → catalystObservationPanel → dailyChannels / researchAttention | 显示公告、独立 US daily 映射、超跌各路股票/理由/日期/状态/缺口；保留 HK_CONNECT 为资格通道。 | 必须与请求的 plan/selection/publication 日期全部匹配；后续失败尝试与已保存产品分别显示。 |

## 时间合同

| 时间/日期 | 含义 | 不可混同的值 |
| --- | --- | --- |
| `target_trade_date` | 本次研究计划所属的适用 HK 证券交易日 | 实际执行日或 US session |
| announcement publication date | 原公告及 reviewed 产品的公告日期范围 | 页面 plan date、抓取发生日 |
| US completed session | 按原 US 日历及目标研究 cutoff 能消费的完整交易 session | 当前 GET 可看到的 raw attention session 或另一日期的最新文件 |
| HK securities source session | 原证券日历允许的行情日 | Connect 资格有效日和 publication availability |
| source captured / registry available / V2 available | 原始证据形成及正式可用时间 | 后补推算的盘前时间 |
| research cutoff | 研究可用输入的时点限制，保存在计划中 | 当前 GET 的时间 |
| started / finished | 原 owner 真正执行的 aware 时间 | 目标日期的虚构开始时间 |

目标10/8在10/9事后执行时，US daily research 应仍选目标对应的 US10/7，并按既有来源的时点证据验证；原 raw attention 可能以真实10/9时点看到另一个 session。两者有不同范围，页面要分别标明。若 source/registry 在研究 cutoff 后才可用，保留缺口，不能因现在文件存在就让历史计划消费。

## 时段与续跑

- MORNING：原计划每5分钟时段；US 单独有界调用后才开始原计划 coordinator 的预算。US 使用同目标日/binding 的一个 `MORNING_US` 触发身份，之后 morning 调用会幂等读回该结果；首次 terminal failure 的新触发恢复从10:00 catch-up 开始，不承诺每5分钟重新读取 US 源。已接纳调用跨分钟时，只在原同日有限 grace 内继续；重新请求仍须通过真正时段准入。
- PREOPEN：保留原窗口和完成截止；不把迟到 owner 调用或尾部 US 任务塞进盘前预算。截止后不标盘前完成。
- SAME_DAY_CATCHUP：固定上海/香港本地时间 **10:00、12:30、15:45、18:30、22:30**，每目标日最多5次该阶段尝试。原关闭窗口避让保留。同 target/binding/slot 的重复调用读回同一已完成结果；相同封存输入身份按原 owner 规则复用。不同实际研究 cutoff 可形成新的同日研究版本，即使底层源文件相同，也不删除原时点上下文来强制去重；旧 run 不覆盖。合法新产品到达后必须被随后原评估消费。
- EVENING_NEXT_SESSION：原机制准备下一个合法 HK session，和当日迟到补算分别选择，一次有界 child 不串行执行两次完整 plan RPC。原证券日历决定下一日，不按自然日加1。
- MANUAL / RETROSPECTIVE：显式原 owner 补算入口，真实开始/结束、cutoff 和 source 日可追踪，不算自然运行。

`execution_context.trigger_kind` 与 `timing` 区分调用方式和发生时间；单凭 `SCHEDULED` 字段仍不构成独立自然验收。`natural_run_verified` 没有相应现场观察证据时保持 false。

## 失败与历史

未知数量保持 null；空数组只有在原规则真正评估完成后才可表述为零入选。已有验证成果不因另一通道失败而被清空。US 当前尝试发生在封存计划 cutoff 之后时，仅作为独立状态展示，不进入旧计划或改变其输入身份。

9/30已验修复沿用原封存合同。真实拒绝 `HISTORY_SOURCE_INPUTS_CHANGED` 保持；只读比较组件来源/hash差异，不重新封存、删除或改写历史产品。两项旧修复的复用和本轮新的每日接续是不同证据范围。

研究边界始终为 `RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
