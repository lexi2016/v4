# Issue #35 — 2026-10-12 三路自动接续：独立最小补丁交付

**状态：PATCH_PROPOSED / EXACT_CONTEXT_SHA_VERIFIED；Mac 独立测试、合入、发布、8873 API、V4 页面、目标 20261012 自然运行与三路正式名单均 NOT_RUN / CANNOT_CONFIRM。**

固定上游：[Issue #35](https://github.com/lexi2016/v4/issues/35)；
任务书 `handoff/three-lane-autocontinue-20261012-r1/DAILY_AUTOCONTINUE_TASK.md`；
本次固定源 `da35e5a331e914d8dd1cf2d8e98954612885d1c5`。
本分支 `codex/issue35-autocontinue-fix-20261011` 只增添 handoff 文件，没有触碰现役代码目录、发布锁、配置、交易门禁、任务或服务。

## 修复边界与原 owner

1. **计划新输入、幂等、保存/读回**：保留 `ManagerResearchJobService.refresh_workspace_plan` 原主入口、SafeRoot Store、日期交易日与 cutoff 原合同。在持有同目标日事务锁时，只有保存产品 `CURRENT + consumed=true`、输入身份一致、同 run 终态 owner attempt 独立核验，才可复用已存成果（`ALREADY_MATERIALIZED`）。真实输入变化自然生成新 run、run/product SHA 与终态 attempt；旧产物按 run_id 保留。修复 canonical R2 的“成功 attempt 尚未封存就先要求完整 readback”循环；按 `exact immutable run → exact SHA readback → terminal attempt/sha → latest pointer → original full readback` 顺序验证。失败记录在独立失败 attempt，恢复旧成功指针，不得把失败变有效零。
2. **调度接续**：`plan_owner_dispatch._execute_serialized_cycle` 原来对相同 evening trigger 的此前成功 `prior.response` 直接 replay，不验证新材料。在原受限事务下使用原 `get_workspace(include_saved=True)`、已存产品和 `verified_plan_attempt` 独立读回确认 `CURRENT` 后才允许重放。若真正 stale，则走现有 backoff/budget、`run_scheduled_plan_target` 与原 owner，保留原时窗、交易日历及 dispatch 回执。仅更改 EV​ENING_NEXT_SESSION 的有歧义重复触发判断；其它独立分时槽暂不更改。不修改超跌或公告原筛选公式。
3. **API 原 Stage 执行消费者**：现役 API 已构造 `shared_selection_consumer`，但旧 runtime ManagerService 缺注入。补入 `workspace_stage_selection_reader`，只复用原 `StageSelectionConsumer.get(...,allow_backfill=False)`；不将 observation、UI 或空对象当正式阶段产物。canonical R2 `service.py` 已接受该参数，仅需 API 注入小 hunk。
4. **绑定和三路原算法**：只提供 Mac 需要核验、可回退的 wiring 补丁。**未伪造新的 binding、activation receipt、owner/product、US daily、公告 analysis、超跌量纲证据。** 原 manager binding 必须由 Mac 唯一 Writer 基于实际 8873 加载源码根、同根 closed inventory、绑定 SHA 和既有 canary/CAS 重新签发并验证；不得整体切换 HK scheduler 或强制启用 `announcement_collection_enabled`。公告注册/导入、TDX 超跌采集及 US daily 原 owner 须保留各自独立时窗/上下游因果。

## 精确互斥补丁模式

**模式 A：`canonical_r2`**（Mac 已三方合入候选 R2、`workspace.py` SHA256 为 `b372deab943079efae4c45a9f6528c9b577112898b78fa0721d685dfb73d1a76`）：

- `patches/canonical_r2_workspace.patch`
- `patches/common_app_stage_consumer.patch`（共享 ACTIVE R1 app 文件上的单 hunk）
- `patches/runtime_r1_dispatch_input_refresh.patch`（上游公共 `plan_owner_dispatch.py` 原字节）

**模式 B：`runtime_r1`**（原三路 R1 工作副本，workspace SHA256 为 `e1282f724c387529134add6d69630452127f960c5727314295d3f50b452847ff`）：

- `patches/runtime_r1_owner_and_stage.patch`（原 runtime workspace + service + active app）
- `patches/runtime_r1_dispatch_input_refresh.patch`

**两种模式不能混用 workspace patch，也不能整文件覆盖 Mac 正在合入的并行修复。** 全部 5 目标路径、Git blob、逐路径 before/after SHA256、增删行、来源位于 `PATCH_SHA_MANIFEST.json`。已通过只读 JS 独立重放每个 unified diff hunk、逐行上下文比较以及 original/after SHA256；这属于静态可应用性证据，**不是** Python 编译/pytest/Mac 真实验收。

## Mac 唯一 Writer：严格核 SHA、再补丁

先将本 handoff 放在独立 checkout，把候选应用根变量设为实际上游源码根（**不能指向现役 8873 加载目录**）：

```bash
HANDOFF="/path/to/checkout/handoff/issue35-autocontinue-fix-20261011"
APP="/path/to/isolated/candidate/app"
python3 "$HANDOFF/scripts/check_or_apply.py" --root "$APP" --mode canonical_r2
# 只有上一步返回 PATCH_APPLICABLE_READ_ONLY_CHECK，且 Writer 已确认隔离根后：
python3 "$HANDOFF/scripts/check_or_apply.py" --root "$APP" --mode canonical_r2 --apply
```

如候选确实是 R1，两个命令中的 `--mode` 改成 `runtime_r1`。checker 拒绝不匹配的源 SHA、目标缺失、符号链接及 git apply 不通过；成功应用会验证全部 after SHA，**但不会合并其它并行修改**。Mac 若已产生三方合并后的不同 SHA，必须先人工逐 hunk 评估重做小补丁，不能关掉 SHA 校验强行覆盖。失败后保留原源和原日志，不能宣称可部署。

## Mac 定向验证（待执行，不预报绿灯）

在采用正确 Python 环境及已打补丁的候选根执行：

```bash
cd "$APP"
PYTHONPATH="$APP" python3 -m pytest -q \
  "$HANDOFF/tests/test_issue35_owner_autocontinue.py" \
  tests/test_three_lane_r2_mac_20261012.py \
  tests/test_manager_plan_identity_r2.py
```

如果第三方测试路径不同，用上游真实路径，不要修改其断言去求绿灯。新增 6 个合成定向测试覆盖：①新 run terminal-first readback；②同输入只读复用、变输入新 run/旧归档；③失败后旧 latest 保持；④ evening 同 trigger stale 重算判定；⑤正式 Stage reader 注入；⑥原 HK 冻结日历周五→周一跨日目标、周日不得自然触发、周一合法 catchup 槽。必须按 RED→GREEN、全套目标 owner/test 与 Mac 第二 Reviewer 复跑验证；目前这里**未运行**，故对可通过性不作保证。

**binding、API/UI 与真正 10/12 自然槽需另做三段验证**：

- **binding 读取阶段**：独立只读核 active API loaded code/root、Manager child `APP_ROOT`、python/source inventory、`manager_state_root`、policy、bound SHA、开关及原 scheduler 进程；若不同根或 SHA，保持不切换。Mac 以既有绑定/canary/共享发布锁/CAS 原程序重新签发，保留原 HK 外调度及回退指针。旧 `announcement_collection_enabled=false` 说明 Manager 计划任务本身未运行公告采集；须证明**另一个原 announcement owner** 被自然调度，不能把它强置 true 冒充激活。
- **真实数据与页面**：严格分别获取目标日三路 original owner `run_id/product_sha/input_identity/terminal receipt`，输入/公告/US 真实 source date，逐股名称/代码/理由/可核状态；经 `/api/v4/manager/research/workspace?date=20261012&view=auto` 和 `view=dynamic` 以及 V4 原页面重载对照，每路缺值保持 NOT_RUN/PARTIAL/NOT_IMPORTED，而非 0。原 PR #37 的 GET-only `handoff/issue35-20261012/issue35_canary.py` 可辅助收据保存，但它此前 11 项是纯合成，不能代替独立 Reviewer。
- **自然时段**：2026-10-11 为港股休市周日，原 `daily_cycle_branch` 会拒绝周日自然插单；必须等目标日 2026-10-12 HK 原 morning/preopen 或 catchup `10:00,12:30,15:45,18:30,22:30` 等精确合法槽才能判自然触发。通过原 scheduler→Manager child→bound HTTP→owner→terminal store→API/UI 跨进程读取全证据，`natural_run_verified` 不得由人工复盘写 true。10/12 evening 的 next-session 目标按原交易日历滚动，不复用 12 名单。

## 尚未闭环、不得冒充

公告 target12/publication2026-10-09 原 catalog 383 条/21 页 COMPLETE/VERIFIED；正文 319 条 COMPLETE、64 条失败，语义 `NOT_REVIEWED`、original analysis `NOT_IMPORTED`。旧 target08/09 33/55 入选不得复制。须由 Mac 原正文 owner/原缓存有界恢复，完成 semantically reviewed、registered/imported、exact owner selection。

超跌现有 214 研究候选、34 待核；原 60+5 历史、权威 TDX 量纲、原 run/product 缺口未消，不能把候选数当股票名单。

美股 18 上涨行业/23 个股 READY 是原始发现，不是 US daily run；target12 `daily_run NOT_RUN`，须由原 `refresh_us_mapping_research` 在原允许时段执行并封存。计划失败/缺源不能阻断另两路可验证读回。

本分支**仅修复已定位的计划、dispatcher 与 Stage 接线 P1，并提供可应用及 SHA 证据。三路名单生产、真实部署及自然 10/12 验收仍由 Mac 原 owner 完成**。没有更改 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`，没有调用交易接口，没有新增提醒。
