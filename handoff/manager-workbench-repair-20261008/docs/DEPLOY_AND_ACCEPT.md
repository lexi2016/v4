# Mac 部署、回滚与自然运行验收

本轮只完成 Linux 候选实现与隔离验证。以下供 Mac 执行者在实际源码、release 与运行环境中继续工作；没有在本会话执行其中任何服务动作。依据冻结问题包的现役配置记录与 [scheduler 闭合说明](SCHEDULER_CLOSURE.md)，不得把仓库根或旧候选冒充当前运行树。

## 1. 形成真实前像记录

从当前实际进程重新取得 API 与 scheduler 的 PID、启动参数、WorkingDirectory、解释器调用路径及 resolved executable SHA、环境里的 app/release/manifest/binding 身份。使用既有进程取证/运行身份工具确认**真正服务进程**加载的关键模块路径和文件 SHA。单独启动一个 Python import 或只读取 plist，不能证明服务进程加载版本。

冻结记录仅供比对：

| 记录 | 冻结身份 |
| --- | --- |
| API app | `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r3-api/app` |
| API release manifest SHA | `946c49b9c34bd09fbca04644556de3acba1635eb240fa9293f6391e9d46b40e9` |
| API app inventory SHA | `07ff61bc18f66f7e92eb45f57a20aecf3885eaa79c1bdb705b8f805fdbb95bd8` |
| API plist SHA | `72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5` |
| Scheduler app | `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/hk-research-calendar-all-r1-20261007-scheduler/app` |
| Scheduler plist SHA | `c478c87e7866fa50154df674ea7cb570197251aaa5da3014b3666e7f22914da2` |

核对源代码三种根：当前 canonical、实际 R3 API release、实际 scheduler release。对 `source_manifest.json` 的各 profile 运行只读验证。源清单之外的模块、private PDF 依赖 manifest、native 库、Mac frontend 入口与既有 fixture 仍需要完整原始 inventory 的证明。

保存所观察的各源码 SHA、manifest/inventory、plist SHA 和对应进程身份；原文凭证、认证文件、账户/持仓和大体积行情留在既有私有数据边界内。交付记录使用身份摘要。

## 2. 在实际 release 的隔离副本集成

用已确认的实际 API/scheduler 完整树形成新的隔离候选。保持各自原解释器、依赖、symlink、mode 和数据根，不复用本包的组装树作为完整 release。

API 只集成 `api` profile 的改动与新增 `workspace_daily_channels.py`。前端只集成三个生产 TS 文件；保留当前 `businessStatus.ts`。scheduler 只叠加明确的 daemon 前置增量，保留现役 launcher、runner、due.py、HK02 no-site launcher 与所有既有 Stage/行情配置。

使用现有原 release 工具和本轮明确允许路径更新候选 inventory；旧工具里写死的 R2/C1 根、SHA、allowlist、输出目录必须先与新观察到的前像对齐并独立审查，不能直接运行旧脚本。每个拟集成源文件需要通过 before SHA，再核对 after SHA。两组 patch 用于审阅及在对应隔离副本应用，不能跨 API/scheduler 根一次性盲贴。

保持总 binding `enabled=false` 完成候选准备。更新原 `binding_inventory(new_api_root)`，固定实际 Python invocation/resolved SHA、cycle SHA、API root、原 manager/security-master 数据根。明确加入：

```json
{
  "policy": "BALANCED_V1",
  "morning_plan": {"enabled": true, "interval_seconds": 300, "status": "PROPOSAL_ONLY"},
  "preopen_plan": {"enabled": true, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
  "plan_material_refresh": {"enabled": true, "start_local": "16:00", "end_local": "23:00", "max_attempts_per_target_date": 3, "retry_backoff_seconds": 600, "status": "PROPOSAL_ONLY"}
}
```

此片段不是完整、可加载或已经启用的配置。完整 plan-only 契约包括 `plan_material_refresh_only=true`、`announcement_collection_enabled=false` 及 fresh exact-root plan canary；总 enabled 在准备阶段仍为 false。既有 06:30 heartbeat 保持公告获取和真实 reader/reviewer 的 owner，不能用 scheduler 多开一个公告 producer。

## 3. 代码和完整构建验收

使用 Mac 原运行解释器和冻结依赖，在候选根执行：

```sh
PYTHONPATH=.:upstreams python -m pytest -q \
  tests/test_manager_announcement_parity_20261008.py \
  tests/test_manager_input_contracts_20261008.py \
  tests/test_manager_daily_dispatch_20261008.py \
  tests/test_manager_workspace_owner_20261008.py \
  tests/test_manager_daily_channels_20261008.py \
  tests/test_manager_research_router_contract.py
```

在 `apps/web` 执行：

```sh
npm test -- src/manager-selection/dailyChannels.spec.ts src/manager-selection/dailyChannels.runtime.spec.ts
./node_modules/.bin/tsc --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --strict --skipLibCheck --types vitest/globals src/api/managerWorkspace.ts src/manager-selection/catalystObservationPanel.ts src/manager-selection/dailyChannels.ts src/manager-selection/dailyChannels.spec.ts src/manager-selection/dailyChannels.runtime.spec.ts src/manager-selection/dailyChannels.testHelper.ts
npm run typecheck
npm run build
```

最后两个命令在本包组装源码里并未通过：缺原入口/fixture 和既有诊断已记录。Mac 应从当前原源码恢复完整闭包再运行，不能编造市场 fixture、删除断言或新增假的入口来宣称原生产构建已验证。

## 4. 候选 canary 与服务切换

沿原 exact-root historical owner canary 检查候选 API → 原 HTTP owner → immutable plan → 同 run attempt → GET 读回。canary 必须对应本轮新的源 inventory 和真正的解释器，旧 R2 receipt 不能激活本次变更。历史/人工 canary 必须保持自己的执行类型，不改写成自然触发。

把候选 API/scheduler plists、完整 manifest/inventory、binding、canary、前像备份和允许差异形成可审阅结果，再由具有现役控制权的 Mac 主控在已协调窗口执行受控切换。原 Stage scheduler 和 Vibe8910 不在切换范围。切换后重新确认真正服务进程身份及静态 bundle 身份，不只看磁盘文件或 HTTP 200。

本轮没有生成凭证或发布可直接启用的绑定，也没有实际运行 launchctl。所需的真实前像和 fresh canary 尚不存在于本会话，因而没有声称完成部署。

## 5. 公告同产品 API 验收

先只读既有产品。冻结复现组合的原 canonical 路由示例：

```text
GET /api/v4/manager/research/announcements/analysis?date=20261008&publication_date=2026-10-07
GET /api/v4/manager/research/workspace?date=20261008&selection_date=20261007&announcement_date=20261007&view=dynamic
```

现场报告的 `/api/v4/manager/workspace` 简写路由需在实际 app 中确认其 alias/handler 身份；本轮保留源码现有 research 路由，没有臆造新 producer 或 app 入口。

逐项比较 analysis 的 `consumption_validation` 与 workspace 的 `announcement_reviewed_analysis.products`：

- target/publication pair；product/source manifest/catalog SHA。
- evidence run、judgment receipt SHA、handoff manifest SHA、owner import receipt SHA。
- owner 可用时间、阅读/判断时间、每条 source 的获取时间及计划 cutoff。
- 原 SELECTED / CONDITIONAL_WATCH / NOT_ASSESSED 数量与原始理由；不得从空 refs 推导全部已评估。
- 无效旧产品的日期对、产品 SHA、失败阶段和原错误码；成功产品继续可读。

如果现有产品仍有效，保持原字节和 run，不为让页面变绿重复导入。测试当前已有产品的只读 parity 与观察下一次真正自然导入是两项不同验收。

## 6. 港股通与超跌输入验收

港股通分别保存目标日 HK_UNIVERSE_V2、上一完整日 capture、D-1 Top100 三种身份。固定 D-1 pool 的原 Stage 消费者、manifest/receipt/model/run 和 split-date provenance 已定位于 [输入 owner 说明](INPUT_OWNER_MAP.md)，本轮未改变 Stage。

超跌核对 `market_screen.data_context`：原 planning session 与实际 completed-full-HK session 分开；16:10 后可读已完成的目标日面板，半日保留原完整日比较合同。验证原 panel manifest、panel SHA、security master、源发布时间与 cutoff，再核补充 sidecar 的同一 panel 时间身份。

量纲必须由原 owner 的权威来源证明，包括单位、任何倍率及跨来源一致性。本包没有该正向证明；当前量和前五日均量即使有数字，`NOT_PROVEN` 时数量门仍不能判断通过或失败。0.80/1.5 的阈值及等号边界不变。

## 7. 页面与自然运行验收

用实际部署页面重载：

```text
/manager-selection/?date=20261007&announcement_date=20261007&plan_date=20261008
```

另用真实自然运行目标日的三个明确日期重载，记录页面 URL、加载时间、static bundle/release 身份和截图 SHA。首屏逐路核对股票代码、原理由、实际数据日、生成时间、run 与 API；未判断、缺资格、缺量纲必须保持待核。切换日期、取消等待和刷新后不得显示上一请求的迟到结果。

随后在下一个真实 HK 交易日观察：早间 07:00–09:25 前的五分钟 ticks；盘前 09:27–09:30 前完成；晚间对下一原生日历 HK session 的计划准备。分别保存真实 scheduler trigger、父 trigger/branch、API dispatch receipt、immutable plan、同 run sealed attempt、source/input/product SHA、开始和最终完成时间。晚间产物仍保留原 `MANUAL_REFRESH` owner 类型，父调度身份单列。

公告另需原 heartbeat 的自然 capture → 原 reader → 独立 reviewer → register-handoff → owner import → analysis/workspace → 页面。只有两条证据链都存在，才可把自动化验收升为通过。`PENDING_SLOT`、手动一次结果、历史 canary 或静态截图均不能代替。

## 8. 回滚与中断处理

保留切换前 API/scheduler plist、binding、manifest 和 immutable app 根。若验收失败，使用原受控切换工具在精确匹配当前前像后恢复原 release/binding；回滚后重新读回进程、API 和页面身份。源文件 reverse patch 只适用于隔离候选，不是在运行目录中逐文件回滚的方法。

保留所有 owner 产品、失败 attempt 和 dispatch receipt；不删除或覆盖来制造成功。持久 RUNNING 的中断歧义须先沿实际产品/run/attempt 做 reconciliation，本包不会盲重试。已错过自然窗口时等待下一合法窗口或明确记录人工恢复类型，不能改时间回填自然证据。
