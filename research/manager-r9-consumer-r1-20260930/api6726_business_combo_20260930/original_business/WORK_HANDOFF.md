# 一次 Work 接续：只做隔离应用、差异复验和现场读回

## 冻结分工

GOAL：验收本批 B1 多批正文消费、B2 本轮采集后盘前消费和 US 简繁体匹配，禁止用资格预检代替业务验收。
WRITER：普通 Chat 已完成本包代码；Work 只做精确前像核验、隔离应用/必要机械适配。发生实际源漂移则回传该文件及 SHA，由 Chat 返修，不让 Work 重新设计。
REVIEWER：原独立 Mac Reviewer，不能把作者测试改称独立通过。
ALLOWED_PATHS：SOURCE_PINS.json 中三个业务路径；B2 仅匹配其单独快照前像后采用 ops/run_manager_announcement_cycle.py；本批 tests/logs。
FORBIDDEN_PATHS：活动 releases、原 R1/R2/R3B 包/manifest、workspace.py、connect_selection.py、workspace_plan_autorun.py、资格生产/门禁、A/Stage/BUY/F5/Vibe、配置/启调度。
PASS_SIGNAL：相应新回归通过、保存/读回的原 run 与正文 refs 可追溯、集合不扩大、BUY 为 false。真实业务通过还须原 authority 与目标 cutoff 合格后原 API/UI 逐股证据。
STOP_RULE：任何前像漂移/不完整原依赖闭包/越 cutoff/资格缺证/来源 SHA 错误，拒绝升级结果。不得改历史时钟或回填 manifest。

## 1. 包与隔离源

在包根执行 `"$PY" tools/verify_delivery.py`。该命令只校验本包和临时 patch 正反回放，不读取活动资料。

`$PY` 使用本机已验 Python 3.14.6 原解释器；`$PKG` 为本包绝对路径；`$APP` 为从“已验 R1+R2+R3B”的完整 app 创建的全新隔离副本，不能是 canonical 或活动 release。不要从 AUTHOR_REFERENCE_INVENTORY 组装 Mac 应用。

先核 `$APP/v4/manager_research/workspace.py` 为 `8a1ce512...e7c190`、connect_selection 为 `b6c53001...8a6248`，再核每个变更前像的完整 SHA（SOURCE_PINS.json）。不重复 R3B 10 项或 R1/R2 未变部分验收。

```bash
(cd "$APP" && git apply --check "$PKG/runtime.patch")
(cd "$APP" && git apply "$PKG/runtime.patch")
"$PY" "$PKG/tools/run_tests.py" --app "$APP" --surface business \
  --output "$PKG/../work-business-new-run"
```

业务范围本批 33 项（B1 20、US 13）。必须核对新 helper 已进入候选源清单和原依赖/构建清单，不直接手改原运行绑定或旧 manifest。

## 2. B2 单独采用

先检查隔离 app 中 cycle 的实际前像。只有完整 SHA 等于 `d3e5a0b3...13faec6`，autorun 等于 `ec257948...7ee6d3a8`，且 service 签名匹配时，才执行：

```bash
(cd "$APP" && git apply --check "$PKG/cycle_snapshot.patch")
(cd "$APP" && git apply "$PKG/cycle_snapshot.patch")
"$PY" "$PKG/tools/run_tests.py" --app "$APP" --surface cycle \
  --output "$PKG/../work-cycle-new-run"
```

B2 8 项运行原 main / autorun / workspace 原保存流程。测试中的 provider/service 构造、资源隔离与上游输入是明确测试边界；不能算活动 worker 接线证据。

若现场 cycle 已有旧修复、签名或分支不同，只回传当前 `ops/run_manager_announcement_cycle.py` 完整字节/SHA，以及其调用的 `ManagerResearchJobService.refresh_announcements` 和 `refresh_workspace_plan` 方法/原构造绑定的脱敏片段。保留 B1/US 复验结果，Chat 做最小 B2 rebase；不要覆盖现场改动，也不等 17:20 F0。

## 3. 一次现场业务材料需求（能复用现有证据就不重抓）

B1：原镜像 owner 的两批 committed product + 对应 named terminal journal；相应 MaterialStore refs/envelope/blob/本次 index observation；原查询 scope、capture 时间。仅需可核的两批，不要整库或整项目 ZIP。若旧 index 已覆盖且无历史见证，记录具体 run/ref 缺失，不能借最新 index 伪造旧时间。

US：选一条确实包含发行人业务动作的原文章完整行、原 body/原引用、原 source/receipt/manifest 身份、文章级 published_at/retrieved_at/available_at；若只有 first_seen/crawl_time，回传定义该字段的原生产/转换方法及其绑定的原响应 receipt，不让 Work 任意改名补时钟。若要验证 standing，须已有的源内有效期合同及其独立原文来源引用；不存在就保留缺口。无需为了验收硬找 09969→LLY 正例。

当前服务调用关系：仅提供原 `apps/api/v35_api/manager_workbench_router.py` 中 service 构造/GET workspace/POST refresh 的相关方法和实际 binding 的脱敏字段（根/源SHA/source_scope，绝不回传密钥值）。B1 的 source_scope=EASTMONEY_HK 手动入口和 B2 snapshot 中 schedule 路由不是自动等同关系，要分别读回确认。

## 4. 真实业务验收的次序

资格原 reader 接受、符合目标选择时点后，沿原 API 刷新/读回；逐股核代码、名称、资格、入选理由、原文 span、镜像显示时间、真实取得时间、US 关系及 US 当前信号引用。零候选时保留具体拒因与未映射 raw movers。普通 UI 验同一批 API 返回的候选、原文与时间，不能只看 HTTP 200 或旧正文面板。

本批本身不授权部署、启调度或新真实请求。已有输入不足或原 authority 不合格时，停止真实业务升级；不拿 17:20 面板成功替代公告/映射验收。

## 5. 回退

仅在隔离 app：确认所有本批后像 SHA 后，先 `git apply --check -R cycle_snapshot.patch` / `git apply -R cycle_snapshot.patch`（仅已采用 B2 时），再反向 runtime.patch。核所有前像 SHA，新 helper 应消失。保留测试/失败证据；不用删除任何旧 run、index observation 或历史产品作为回退。活动服务和配置未改，无需重载。

每个面分别记录 IMPLEMENTED/TESTED/REVIEWED/BEHAVIOR_VERIFIED/DEPLOYED/API_VERIFIED/UI_VERIFIED/NATURAL_VERIFIED 与证据路径；缺证写 CANNOT_CONFIRM。PR9 保持 Draft、Issue8 Open。
