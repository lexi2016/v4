# 既有 owner 接续：公告覆盖与目标日港股通资格

固定输入：`research/manager-local-feedback-20261002/CHAT_FEEDBACK.md`，提交 `34e1dc6912100830f42cf0fc90eec72f624afc9a`。本文件不新增抓取器、producer、scheduler 或数据架构。

## B. 公告采集覆盖

### 已确认代码事实

- 唯一 owner：`ManagerResearchJobService.refresh_announcements`；实现位于 `v4/manager_research/workspace_announcements.py`。
- 官方 HKEX 路径在 `source_scope is None` 时执行。`BATCH_SIZE=3`；无待处理正文时，每次调用最多把 `next_index` 推进 3 个 issuer；有 `pending_documents` 时优先继续正文，issuer index 不前进。
- `resume=True` 必须读取同一目标日 `workspace_announcements/<date>/latest.json`；范围和窗口在同一 manual scan session 内保持不变。
- 停止条件来自 readback 的 `coverage.can_resume`。只有 `next_index == len(scope)` 且 `pending_documents` 为空后才停止继续；此时再次 `resume=True` 会触发 `ANNOUNCEMENT_SCAN_DRAINED_START_NEW_CURRENT_WINDOW`。
- 即便 issuer scope 全部跑完，代码仍固定保留 `directory_exhaustion='UNVERIFIED'` 与 `all_official_announcements_captured=false`。因此验收结论只能写“696 个 issuer 的 bounded official owner 查询范围耗尽/失败项显式记录”，不能写“HKEX 全部公告已经穷尽”。
- 当前现场 15/696 与 `BATCH_SIZE=3` 一致：它表示 `next_index=15`，即已完成 5 个 issuer-advancing batch；期间若有 pending-document continuation，实际 owner 调用次数可能多于 5。

### Codex 接续步骤

1. 先在当前活动 service 上只读 `service.get_announcements('20261002')`，保存回执；必须确认 `coverage.native_master_count=696`、当前 `queried_issuer_count=15`（若现场已变化，以实际值为准，不回写成 15）、`coverage.can_resume=true`。
2. 继续调用同一 owner：`service.refresh_announcements('20261002', resume=True)`。每次调用后保存 `product_identity.run_id/revision/sha256`、`coverage.queried_issuer_count`、`pending_document_count`、`failed_issuers`。
3. 仅当返回 `coverage.can_resume=true` 时再次调用；当其变为 false 时停止。不要 `resume=False` 重开窗口，也不要修改 `BATCH_SIZE`。
4. 最终验收：`queried_issuer_count == native_master_count == 696`、`pending_issuers=[]`、`pending_document_count=0`、`can_resume=false`。`failed_issuers` 允许非空，但必须逐项保留，不能把失败解释成“无公告”。
5. 至少抽取一个有公告 issuer，核 `official_documents` 的正文/原始 source ref/issuer 一致；对无结果 issuer 必须用 query receipt 区分 `OBSERVED empty`、`FAILED` 与未查询。

### Eastmoney 当前 NOT_RUN

- Eastmoney 是同一 owner 的显式 source-scope 分支，不会被官方 HKEX `resume` 自动带起。
- 要把当前目标日从 `NOT_RUN` 变成实际 bounded mirror capture，只调用一次现有入口：`service.refresh_announcements('20261002', source_scope='EASTMONEY_HK')`。
- 该分支默认只查询 verified master 排序后的前 3 个 issuer；返回合同明确标记 `MASTER_OWNED_BOUNDED_HK_ISSUERS_NOT_FULL_MARKET`、`exhaustive=false`。不要把它当 696 家官方覆盖。
- 只有排查指定发行人时才使用 `issuer_code='HK.xxxxx'`；这会更新该分支 latest product，不用于伪造全市场聚合。
- 历史 `20260929` capture 原件继续保留；当前 source-scope 执行不会把历史 capture date 改成 `20261002`。

### B 面结果

`OWNER_CONTINUATION_READY / CHAT_NOT_EXECUTED`。不需要改抓取代码。若 `get_announcements` 当前产品已不再是 15/696，Codex以现场 readback 为准继续，不回滚数据。

## C. 目标日港股通资格输入

### 已确认 consumer 合同

- Manager `connect_selection.read_scope()` 已优先调用现有 `domains.manager_research_evidence.read_universe_evidence(..., date='20261002', require_v2=True)`；Manager 侧无需再写 reader。
- 目标日 authority 必须满足：`source_date='20261002'`、`market='HK_CONNECT'`、`role='HK_CONNECT_FULL_MARKET_AUTHORITY'`，`acquired_at` 与 `available_at` 均不晚于当前 `research_cutoff`，codes 非空且 canonical。
- 目标语义必须是 `TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2`，input identity 为现有 `digest([target_date, codes, source.sha256])`。
- 当前直接缺口：`universes/20261002/HK_CONNECT_FULL_MARKET.json`；诊断 producer owner=`v35_dispatcher.research_panel_daily_hk`。
- 当前 pinned authority owner root：`/Users/lexi/Desktop/学习/agents调试/MANAGER_R3_BUSINESS_FIX_20260930/r3a/build/r3a-r9-import-closure-20260930T193024Z/app`；source ref=`stage_center/hk_universe_preflight.py`；source SHA256=`9d3d2c2d5ff3bd1c7713a9485e88000ae882f58b0a457b734656094606ba2941`。

### Codex 接续步骤

1. 不改 Manager reader。先核本机上述 `stage_center/hk_universe_preflight.py` 实际 SHA 必须等于 `9d3d...2941`；不一致立即停止。
2. 从本机现有 dispatcher 注册表/工作负载定义中定位 `v35_dispatcher.research_panel_daily_hk` 的原生执行入口，按原参数执行目标日 `20261002`。禁止用 689 行价格有效列表、security master 行数或 D-1 696 码手工拼 `HK_CONNECT_FULL_MARKET.json`。
3. owner 必须按原 V2 contract 写入当前 `V4_MANAGER_UNIVERSE_ROOT` 下的 `universes/20261002/HK_CONNECT_FULL_MARKET.json`，并保留原 source SHA / acquisition / availability 元数据。不要 backdate。
4. 使用现有 `read_universe_evidence(..., '20261002', require_v2=True, authority_owner_root=<pinned root>, authority_owner_sha256='9d3d...2941')` 独立读回。记录 artifact SHA、code count、source_date、acquired_at、available_at。
5. 再只读 8873 workspace。验收必须看到 `membership.status='OWNER_VERIFIED'`、`membership_semantics='TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2'`、`source.source_date='20261002'`，并且原 67 张材料卡不再因为 `TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED` 整批被拒。仍可按真实资格产生 `NOT_IN_TARGET_HK_CONNECT_UNIVERSE` 或后续双来源/PIT 拒绝；不得为得到非零映射放宽门禁。

### C 面当前缺输入

GitHub 集中反馈包没有包含 pinned `stage_center/hk_universe_preflight.py` 的文件字节，也没有包含 `v35_dispatcher.research_panel_daily_hk` 的实际本机注册命令/入口文件；只有 owner root、source SHA 和缺失 artifact 诊断。因此 Chat 不伪造 producer CLI。Codex 本机只需读取现有注册并用原入口执行；如果该注册项/入口不存在，停止并回传其实际缺失路径，不改 consumer。

### C 面结果

`CONSUMER_READY / TARGET_V2_INPUT_MISSING`。Manager 代码无需修改；下一有效证据只能是原 owner 生成并通过 V2 reader 的 20261002 authority 产物。

## 明确不做

不处理日线、BI04、日历、调度、新架构、第二 producer，也不部署服务。
