# 当前进度审计（只读，2026-10-01）

范围：canonical 工作树、活动 API plist/release、指定 handoff 和验收目录；不运行测试、抓取、部署或改源码/配置/服务/数据。本文件只记核到的事实。

## 当前 API 与源码身份

- 活动配置：`/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist`，SHA256 `2ba6b17639d769fe8adf977707b099ec1de1587c65b81eb0675d3ad81323996b`。`V35_APP_ROOT`/`WorkingDirectory` 指向 `r4-stage-merged-c3e5357d07f068e79296790e0b968934c34541d579c586282c5e83f56f6a3875/app`，plist 固定 manifest SHA256 `ec5c62cd8a9935c6c2838afd3c02a98ea9fe9d2aaefdae27fb5d462a8c65e3b5`；磁盘 manifest 与该 SHA 一致。端口参数为 8873。
- 当前 repo `HEAD=55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`。本审计的 Manager 源文件在 `git status` 中为 untracked (`??`)，因此这些 canonical 字节没有由当前 HEAD 提供 Git commit 绑定；以下 SHA 是文件字节核对值。
- canonical 与活动 release 中，下列缺陷相关文件字节一致：`workspace_announcements.py` `e57fe8b0…70a18`、`announcement_observation.py` `f86f2f0a…ef17ed`、`apps/web/src/api/managerWorkspace.ts` `139d9e4c…b19c9`、`workspace.py` `35c9292d…a6168`、`workspace_discovery.py` `ed9188a4…c5c1a`、`issuer_us_relations.py` `ac3b3e22…f0b7d`、`research_attention.py` `141d95c3…b3969`、`research_evidence.py` `6a0075ae…c6ec2`、`workspace_history.py` `d2ad875f…9bdca`。
- 关键差异：canonical `connect_selection.py` SHA `ccc65ccb…1ad5b0`，活动 release SHA `945acad0…9488d3b`；canonical 有 D-1 fallback，活动 release 的 `read_scope` 在 V2 失败后直接返回，且活动 release 缺 `connect_capture_adapter.py`（canonical SHA `6a87b77c…fc2604b`）。canonical `us_market_bridge.py` SHA `18d4ede4…18de06` 含已存同日报价重投影，活动 release SHA `46fcf3fc…bf0ae` 没有该逻辑。`workspace_plan.py` 也不同（canonical `c015b7f3…0411e`，release `0721e90f…4023f9`）；diff 是 HK 日线补充投影，未找到它提供 `SCHEDULED_MORNING` reader 兼容性的证据。

## BI-01 公告实例 ID

- 实际入口为 `manager_research_router.read_manager_workspace` (`apps/api/v35_api/manager_research_router.py:169-178`) → `ManagerResearchJobService.get_workspace` (`v4/manager_research/service.py:393-403`) → `workspace.get_workspace`。过去日期的 `view=auto` 走 `workspace_history.read_history`，动态视图走 `_compute_workspace` (`v4/manager_research/workspace.py:270-288`)。
- `_project_eastmoney_hk` 对每份 document 生成 `event_id=digest(['EASTMONEY_HK', row['art_code']])`，同时输出 `symbol`、`body_sha256` (`v4/manager_research/workspace_announcements.py:600-649`)。因此同一 art_code 的异正文或多发行人仍会得到相同 ID。`event_lane` 逐份保留窗口内文档，没有按该 ID 合并 (`v4/manager_research/announcement_observation.py:48-76`)。
- 普通前端 `requestManagerWorkspace` 对 GET 响应调用 `validateManagerWorkspace` (`apps/web/src/api/managerWorkspace.ts:731-734,838-857`)；validator 对 Eastmoney `event_id` 做唯一性检查，重复即抛 `EASTMONEY_HK_DOCUMENT_IDENTITY_INVALID` (`:251-269`)，该检查发生在工作台整体校验路径。
- **状态：SOURCE_DEFECT_PRESENT**，上述 Python/API 与 TS 文件均与活动 release 同 SHA。当前页面快照显示 Eastmoney `NOT_RUN`、读回 0 条逐篇公告 (`page_evidence/manager-current.txt:108-111`)，本次 GET 没有证明重复实例已经触发；实际当前数据触发为 `CANNOT_CONFIRM`。
- GitHub PR18 (`PR18.json:2-13`) 为 open、draft、`merged=false`，内容范围只标 BI-01。其 body 报告远端原 Store→TS validator→DOM 的 before/after 测试，但明确没有 Mac runtime、完整 HTTP/整页浏览器验收；本地活动 release 仍未包含该候选。`API_VERIFIED/UI_VERIFIED/BEHAVIOR_VERIFIED` 对该 PR 在本机均 `CANNOT_CONFIRM`。

## BI-02 美股映射合同

- US 关系成功时，`research_attention` 把“美股关联原文方向…”追加到 `decision.why_now_readable` (`v4/manager_research/research_attention.py:179-198`)；前端要求此数组逐项等于固定 lane 标签 (`apps/web/src/api/managerWorkspace.ts:639-642`)。两端源码与活动 release 同 SHA。
- 个股关系由 `material_us_relations` 形成的 `hk_relation` 不包含 `semantic_status` (`v4/manager_research/research_evidence.py:193-235`)；普通前端个股 validator 要求 `relation.semantic_status === 'ACCEPTED'`，并把发布时间限制在当前短窗口 (`apps/web/src/api/managerWorkspace.ts:527-539`)。行业 validator 也要求 issuer 发布时间落在该短窗口 (`:496-510`)，没有消费 standing validity / mirror-observed 的分支。
- **状态：SOURCE_CONTRACT_MISMATCH_PRESENT**。现场 GET 的 `mapping_eligible=true`，但 `source_material_card_count=0`，故目前没有成功的非空 US relation 可供该 validator 作 runtime 验收；BI-02 页面触发为 `CANNOT_CONFIRM`，静态不兼容仍在活动字节中。

## source_material_card_count=0 的当前直接原因

- 当前 API 保存读回：`page_evidence/workspace-20261002-auto.json`，SHA256 `dfbe40071d4cf986ba36e9bb4f3a04726d11be50f81c71e4187a308bf52cef17`。JSONPath `.existing_material_coverage.material_count=2016`；`.material_discovery_evidence.coverage` 为 `material_record_count=2016`、`identity_row_count=696`、`mapped_stock_count=16`、`target_connect_card_count=0`；`rejected_relations` 中 67 项的拒因是 `TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED`。
- 调用链：`workspace._compute_workspace` 读取现有材料与公告 body 材料并合并为 `selection_materials` (`v4/manager_research/workspace.py:315-334`)；`read_material_discovery` 投影卡片 (`:335-342`; `v4/manager_research/workspace_discovery.py:205-318,321-372`)；紧接着 `filter_cards(..., connect_scope)` 按 Connect 权限过滤。**投影先得到 16 个发行人/67 张候选卡，随后 67 张全部被 membership gate 排除**，所以传给 `build_research_attention` 的 `material_cards` 是空列表 (`workspace.py:436-447`)。
- `.selection_diagnostics.membership` 为 `CANNOT_CONFIRM`，缺口 `HK_CONNECT_TARGET_AUTHORITY_UNVERIFIED:HK_UNIVERSE_V2_ARTIFACT_MISSING`；诊断所指 artifact 为 `universes/20261002/HK_CONNECT_FULL_MARKET.json`，producer owner 记录为 `v35_dispatcher.research_panel_daily_hk`。活动 `connect_selection.py` 只读目标日 V2 authority (`release/.../connect_selection.py:49-76`)；目标 artifact 缺失时没有 candidate 的 D-1 adapter fallback。活动 plist 也没有 `V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT` / `V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT` 两项。
- 关系层拿到过滤后的空列表后如实输出 `source_material_card_count=0`、`missing_input=FULL_VERIFIED_MATERIAL_CARDS_REQUIRED`、`relation_gate=TWO_SOURCE_PIT_VERIFIED_REQUIRED` (`v4/manager_research/research_evidence.py:444-453,494-500`)。因此当前 0 个 accepted mapping 的直接原因是**Connect membership 未核实导致材料卡被过滤**，不是仅由 US quote 的 `PARTIAL` 状态解释。GET 同时记录 6 个行业与 9 个个股原始 mover、`mapping_eligible=true`、accepted mapping 0；`PARTIAL` 仍是独立质量状态。
- `.selection_diagnostics.source_capture_dates=["20260929"]` 来自 announcement selection inputs 的 capture 列表 (`connect_selection.selection_diagnostics`, `:213-219`)，不能与 2,016 条 existing material count 混为一组日期证据。页面 Eastmoney `NOT_RUN` 也表示当前 capture/attempt 未运行；本 GET 的腾讯历史正文在 selection diagnostics 中另被 `EASTMONEY_HK_DISPLAY_TIME_OUTSIDE_CONSUMER_WINDOW` 拒绝，二者不是矛盾状态，也不证明公告总数为零。

## BI-04 morning 历史 reader

- 当前 canonical 与活动 release 的 `workspace_history.py` SHA 相同：`d2ad875f639e7018e06498fbafb8c379808576425dedf6cfbed590155309bdca`。`_read_candidate` 白名单仅 `MANUAL_REFRESH` / `SCHEDULED_PREOPEN` (`v4/manager_research/workspace_history.py:42-65`)；`select_plan` 先读 `latest.json` (`:92-99`)；保存项不合法会继续到历史读取失败路径 (`BUSINESS_REVIEW.md:180-186`，reader catch 在 `workspace_history.py:232-234`)。
- 已有静态 handoff 指出 API6726 writer 曾允许并写入 `SCHEDULED_MORNING` (`BUSINESS_REVIEW.md:176-184`)；但该 writer 与活动历史 reader 的最终组合是否真实运行/是否已触发，**CANNOT_CONFIRM**。当前 release 中 reader 缺口明确存在，不能据此宣称自然运行失败。

## R4 US mapping 候选与未闭环状态

- 当前 plist 仍指向基线 `r4-stage-merged-c3e535…`；候选 `r4-us-mapping-6e1538c6804ba0bc0a15a9c60564601c1677de3915849afc22ba589081a72850` manifest SHA `55618356e7014fe458e50c75b2af380b5b214e0a8df68f021cb9cb647e7916dc`，handoff 状态 `NOT_ACTIVATED`。候选 `source.us_mapping_overlay.base_release_id` 错指向候选自身；其 `base_manifest_sha256` 却是活动基线 SHA `ec5c62…`。writer_handoff 的 candidate base id 指向活动基线，存在字段冲突；该候选当前不具备一致的 base identity。
- 候选中 canonical `connect_selection.py` / `connect_capture_adapter.py` 承载 D-1 fallback，尚未进入活动 release。现存 handoff 报告候选目标日映射范围为 `source_date=20260930` 的 696 个码；该候选输入与当前活动 GET 的缺失 V2 artifact 是不同证据层。
- `writer_handoff.json:53-54` 报告实际服务 Python 3.14.6 下两项聚焦测试 `9 passed`（Writer receipt）。此前扩大运行 `43 passed, 3 failed` (`:193-200`)：两项 `test_us_map_freshness.py` 使用旧 PARTIAL fixture，与同日秒差后 READY 的候选行为不一致；另一项 `test_manager_us_market_bridge.py` fixture 缺 `relation_origin=NATIVE_MATERIAL_PROPOSITION`。handoff 记录 Writer 当时尚未改前两项旧 fixture (`HANDOFF…:90-99`)。
- 当前候选独立最终回执：指定候选目录 `us_mapping_repair/evidence/` 只有三个 `.overlay.diff` 文件，没有 reviewer final receipt；`writer_handoff.json:202-207` 的 `independent_review=PENDING`，`API_VERIFIED/UI_VERIFIED/NATURAL_VERIFIED=CANNOT_CONFIRM`。handoff `:98-99` 记录独立 reviewer 仍在核 pins/完整候选验收，最终 PASS/FAIL 未交付。`rollout/evidence` 中已有 review 文件绑定的是旧基线 release 或公告第 6 次修订；其范围不等于当前 US mapping 候选最终验收。
- 日线补采：handoff `:102-115` 记录检查 9 个地址，均未取得任何日 K 样本；其中 `112.74.214.43:7727` setup 后日线调用报错，后续 `get_markets()` 5 秒超时。`API/UI` 无补采发布产物，真实日线可达仍 `CANNOT_CONFIRM`。

## 状态、owner 与下一证据

| 项 | 当前状态（证据层） | 未闭环项 / 下一 owner |
|---|---|---|
| BI-01 | `SOURCE_DEFECT_PRESENT`；PR18 是 open/draft、未合并；当前 Mac 触发与浏览器行为 `CANNOT_CONFIRM` | 指定 Chat 的修复 owner 接收本审计；确切 thread ID 未出现在本证据集中。主控收到交付后负责本地实际 Python、API、普通 UI 反馈。 |
| BI-02 | `SOURCE_CONTRACT_MISMATCH_PRESENT`；当前 API 关系输入为空，非空映射 API/UI 行为 `CANNOT_CONFIRM` | 指定 Chat 的修复 owner 接收端到端证据；本地接受和 API/UI 验收由主控后续承担。 |
| materials → Connect → relation | `API_VERIFIED` 到字段值：2016 输入、16 发行人/67 候选卡、67 因缺 membership 全部被过滤、0 到关系层 | authority artifact 责任字段指向 `v35_dispatcher.research_panel_daily_hk`；当前 target V2 artifact 缺失。candidate D-1 adapter 未上线，candidate reviewer/manifest 尚未闭环。 |
| BI-04 | 当前 source reader 白名单不含 morning；实际 writer-reader 组合/自然触发 `CANNOT_CONFIRM` | designated repair owner/独立 reviewer 完成代码与最终组合核对；运行状态由主控后续读回。 |
| R4 US mapping candidate | Writer 报告的聚焦测试 `9 passed`；`INACTIVE`；manifest base 字段冲突；独立 final review `PENDING` | handoff 记载 `/root/r4_actual_capture_writer` 负责 candidate/fixture，`/root/r4_independent_reviewer` 负责独立最终 verdict；两者当前生命周期不由本次静态读取确认。 |
| 日线补采 | 9 地址诊断无日线样本；未发布 | 旧连接调查 owner `/root/r4_us_selection_trace` 在 handoff 中记为已完成且 0 样本；只有新连接/来源证据时才有后续状态。 |

本次 GET 字段保留 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。本轮未运行测试，未改源文件、配置、服务或业务数据。
