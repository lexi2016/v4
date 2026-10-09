# Mac 接手提示词：最小 Stage 候选集成与同链验收

先读 `ROOT_CAUSE.zh-CN.md`、`README.md`、`SOURCE_MAP.json`、`MAC_ACCEPTANCE.md`，再看各组件补丁与独立 REVIEW。固定目标仍为 20261009。原问题包 commit 为 `28ab2d35020adf031f10f38c1040514fc81b6d66`；上轮预选 API/scheduler/shared 已由 Mac 部署，保留它们。

请完成以下工作，并按实际证据分项报告：

1. 先对当前 actual Stage、actual API、canonical、8873 前端、plist argv/config/解释器及实际 import 根做定点身份核验。实际与 canonical 的 runner/slot/receipt 字节不同；不得用一方覆盖另一方。`SOURCE_MAP` 的条件件只有 10/5 历史前像，当前不匹配就移植最小 diff 并补现场定向验收，不替换旧整文件。
2. 在现役完整 app 的隔离副本中集成各匹配最小补丁，保留全部未改文件、依赖、公告/经理/预选修复与原安全位。`support/`、`references/` 是测试资料，不能部署。复跑交付测试，再做当前完整 owner 的定向测试和独立审查。
3. A 的最终投影只透传实际同源已取得的昨收，缺项为 null＋原因，真零不丢。当前 provider → SourceResult → builder/qmt → selection 的昨收在哪层丢失必须实测；若当前 builder 确有旧断点，只在匹配当前源码上做原值透传。未取到数据不填零、不新增来源、不修改原算法或价位规则。保留完整 216 输入、坏子池隔离和 A/HK 分离。
4. HK 缺真实 20261008 资格主表是 BLOCKED_DATA；沿已部署原 owner 寻找真实三件套，合法原件可按原 restore/reuse-only 路径恢复。今日快照、9/30 旧池、10/8 价格观察均不能替代。原件缺失就给具体缺口，不改 READY、不走 10/9 不适用的 Connect-closed 观察 lane。
5. 按 `MAC_ACCEPTANCE.md` 用原 `ops.run_stage_center_nodes` 跑隔离单节点，使用真实当前时钟。保留原 raw/selection/receipt owner、原 store 验证与幂等。不得清除 settled slot，不给旧回执补造时间；上午的手工补验只能标恢复/回看，不能称自然。
6. 依现有已授权发布流程，将通过本机独立验收的必要 delta 发布；保留可回退旧 release 和非改动文件 SHA 清单。API consumer 必须实际使用现役 `self.store` 才能核三件套。确认 8873 实际加载所验 backend 与 bundle，验证同日期/阶段/market/run/algorithm/raw/selection 身份和可见结果；Vibe 8910 保持原样。
7. 自然时段另验真实调度来源、入口/实际调用时钟、行情 cutoff/PIT、原算法及落盘/8873 同一 run。NATURAL/DUE 自述、owner 历史文件、SHA 或新 recorded_at 均不足以单独确认自然运行。

回传：每项 IMPLEMENTED / TESTED / REVIEWED / INTEGRATED / DEPLOYED / API_UI_VERIFIED / NATURAL_VERIFIED 的真实状态；前后 source/runtime/bundle/config 身份、命令、选股三件套与回执引用、原始失败证据、必要回退步骤。未执行用 NOT_RUN，真实缺数据用 BLOCKED_DATA。完成标准是原链在 8873 同一产物的实际闭环，不以单元测试或进程健康替代。
