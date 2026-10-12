# 源码与 Vibe 参考地图

## V4 源码根与快照布局

Canonical 根：`/Users/lexi/Desktop/学习/v4_app`。声明的 8873 R6 根：`/Users/lexi/Desktop/学习/agents调试/V4_ISSUE35_AUTOCONTINUE_MAC_20261011_R1/E/integrated_release/issue35-manager-autocontinue-20261012-r6-integrated/app`。基线远端 commit `b123f8a49f60f3c8d0db4348a997fa59e8a32537`，原冻结分支 `codex/issue35-mac-integration-20261012-r1`；本 handoff 目标分支/目录见 `SCOPE.md`。目录与运行身份由任务输入声明；本批没有连接 8873、核对 PID 或检查 launchd，因此运行时 source identity 保持 `CANNOT_CONFIRM`。

`source/canonical/` 与 `source/r6-8873/` 各自逐字保存下表 13 个源码文件；每个副本 SHA 等于对应根原文件 SHA。两树不要合并。hash/bytes/line 数逐项在 `manifest.json`。

### 选定源码差异

下列文件在 canonical 与 R6 根的 SHA 不同，应由 Chat 按目标运行根分别理解：

| 文件 | canonical SHA-256 | R6 SHA-256 |
|---|---|---|
| `ops/run_manager_daily_announcement.py` | `47f7fabf43c8acb7dbf1d784396d093c2835e15b23d1d90d294824a3303b7057` | `5e3eb65b3d758082010ba4cc367d03d3b4225e99a1394147a8e09ce9715ec45e` |
| `ops/run_manager_announcement_cycle.py` | `7f552cafca130557d96a26dd8c6aa83ee1545b3cefd8e5716431739a0d6a54fc` | `01b93a8985bc43f8f08ae5c6d97637abc2273fb20987fb27c6a78c6fc5b59d44` |
| `infrastructure/scheduling/manager_announcement_supervisor.py` | `58ffe0af96222ded75cdaea4f105e63dcb78cd7bea113cd3743f8cbe4b38161f` | `2c624cc324c3120bda9e4917717b9cfe2b4244e34410b508781e60c5f3841a7b` |
| `v4/manager_research/announcement_analysis.py` | `5c9980a5fc4d4b7315756d241ed23a63b99cd469f285f4c8f0b8f7756346fa9e` | `04f95eaf26b2e0e38a61ddcb112ceab93a0d5b3390ec0c5368ec2c7ab378103a` |
| `v4/manager_research/announcement_observation.py` | `f86f2f0ac90b4e4490a74a27984c84f9c632075c47862d3627493282afef17ed` | `8e58cab8e9e398d7c628c2f994a5005442d3a6c5ba5f218a155d949b8af74f54` |
| `v4/manager_research/workspace_announcements.py` | `ba3849913eb768ae166e6fa796246d27742a76ce7fd8469356470570dacc3e73` | `de1948b09578a75e65e775a5ab6f6b2399eb3bce688f77b3ec8be6f5246bdf5a` |

完全一致的选定模块：`ops/manager_announcement_body_batch.py`、`v4/manager_research/announcement_source.py`、`announcement_catalog.py`、`announcement_selection.py`、`announcement_autorun.py`、`announcement_materials.py`、`workspace_daily_channels.py`。全列表和精确字节数见 manifest。

### 原码覆盖与入口

- `ops/run_manager_daily_announcement.py`：capture、continue/review、显式处置、analysis product 组装和 owner readback 命令路径。
- `ops/manager_announcement_body_batch.py`：严格绑定日期的正文批量捕获、完整目录核验和正文 corpus/receipt。
- `ops/run_manager_announcement_cycle.py` 与 `infrastructure/scheduling/manager_announcement_supervisor.py`：周期策略、binding 和有界 worker hook。R6 supervisor 有额外 `AnnouncementSupervisor.tick()`/child runner；canonical 对应源文件 SHA/结构不同。源码文本本身不证明类由当前心跳实例化。
- `v4/manager_research/announcement_{source,catalog,analysis,selection,autorun,materials,observation}.py`、`workspace_announcements.py`、`workspace_daily_channels.py`：来源目录、读取/语义合同、显式选择、owner product/readback 与 workspace summary。

`hooks/<root>/` 保存以下原文件逐行精确片段，并在 manifest 记录原文件路径、行号、原文件 SHA、片段 SHA：公告 API 路由（router 345–479）、Service 公告 owner 方法（service 423–464）、`plan_owner_dispatch.py` 的 `execute_bound_plan_cycle` / `request_bound_plan_cycle` 函数（函数起止行由 AST 定位）、R6 `run_bound_child` 与 `AnnouncementSupervisor` 类、R6 daemon 341–355 心跳循环。API hook 包含明确的 `/announcements`、`/announcements/analysis`、`/announcements/analysis/import`、`/announcements/refresh` 和 `/workspace/scheduled-cycle` 路由。

静态入口候选是 `POST /workspace/scheduled-cycle` → `execute_bound_plan_cycle`，以及 supervisor child → `ops/run_manager_announcement_cycle.py --binding`。R6 daemon 循环每分钟启动一次既有 one-shot scheduler；本次代码定位未找到其直接调用 `AnnouncementSupervisor.tick()` 的本地静态调用点。它究竟如何进入当前 8873 每日公告链，仍需后续运行级 receipt 证实；不能据此称已自动化。

依赖闭包刻意未展开。原码直接/间接引用但未随包复制的关键模块包括 `v4/manager_research/workspace.py`、`workspace_plan.py`、`workspace_projection.py`、`workspace_read_control.py`、`store.py`、`workspace_plan_autorun.py`、`plan_owner_dispatch.py` 的完整实现、`service.py` 的完整实现、`hkex_provider.py`、`materials.py`、`pdf_parser.py`、`material_transport.py`、`contracts.py`、`evidence_identity.py`、`infrastructure/owned_io.py` 及相关 scheduler registry/依赖。API、service、dispatcher 只携必要 route/方法/函数原文片段。请在实现仓库内用指定目标根补齐最小闭包。包不是可执行闭包，也没有携带原有 tests；SOURCE sha 与本地图路径在 manifest 中。

相关现有测试参考（未复制、未运行）：`tests/test_manager_announcement_daily.py`、`test_manager_announcement_daily_flow.py`、`test_manager_announcement_analysis.py`、`test_manager_announcement_selection.py`、`test_manager_announcement_api_and_integrity.py`、`test_manager_announcement_supervisor.py`、`test_manager_announcement_targeted_one_day.py`、`test_manager_announcement_autorun.py`。新需求需要补 script exception coverage、token usage、cache/singleflight、date-bound readback 等针对性回归。

## Vibe 精确参考片段

来源根：`/Users/lexi/Desktop/学习/vibe-astock`，任务输入称 8910 PID 1093；本批只读源码，没有核验服务进程。片段逐字保存在 `vibe-reference/snippets/`。raw file SHA 与 `start`/`end` 的 SHA-256 列于下表和 manifest。

| Vibe 原文件 / 行 | 参考内容和边界 | rawfile SHA-256 | snippet SHA-256 |
|---|---|---|---|
| `vr/astock.py:316–337` | 单只 A 股接口最多 15 条公告元数据；不是完整目录。 | `9f09c396523b232acf69a942eba6d07066535f21fb54bdb0475e32154abb4f6b` | `6f7d3e1faf5f57d5f4cf943fff36bd9e1603539b7a793aa52d2839f36e589441` |
| `vr/app.py:479–493` | `/api/announcements` 按代码缓存 900 秒；不是 bodySHA+模型版本语义 cache。 | `ed6c99f8081dc9aa8bf1467a0d9d6827ebcca6c93cfa096b9c4087e71aada889` | `4d83355738557785ff5989199afd098fa60c143495e36562c44b1065d931906b` |
| `frontend/src/pages/Intel.tsx:269–340` | 关注股 A 公告/新闻聚合排序并全局显示前 60；HK 明确未接公告源。60 是展示上限，不是分析目录。 | `3404c2dc4668a7357b1ce170b94f0de773c2813e10f1a12f80f571c570a493e4` | `42217570251fd534ace3d6e5768a0a72d996b740edbd14039f1b38976bbdb827` |
| `frontend/src/pages/Intel.tsx:119–135` | 用户触发当前行业最多 25 条标题/摘要后生成要点。 | `3404c2dc4668a7357b1ce170b94f0de773c2813e10f1a12f80f571c570a493e4` | `7b8021b04cd01bff83e9456f55ffeb06719790b7345c76634a6b03a446a001d9` |
| `frontend/src/pages/StockData.tsx:178–185` | 个股 AI 上下文附带最近 5 条公告标题。 | `cf8fef396a3332ac37419962153ad24100006c6e659ec36b851bf2b88e736722` | `ed2f6d9d7008cb61ac819ece4717e2e608230f90023613f9a1d8f8e7536c7dcb` |
| `vr/newsradar.py:110–151` | 独立 RSS 资讯模块：日期、红线词与 160 字摘要。 | `7fc09c855bbc36bf1df161b4d18965e5d588a1381d825197d3760d1b7d7d5e1b` | `796bee6d3780bac8db1037f2f8afa605c5d856092fdc3fa0f85af59aa4375b1e` |
| `vr/newsradar.py:520–581` | 翻译默认 12、最大 20，成功 cache；不等于 Qwen 公告正文分析。 | `7fc09c855bbc36bf1df161b4d18965e5d588a1381d825197d3760d1b7d7d5e1b` | `b1b1b39b9f400b05277a1d391eb4e0a81c3b220c5c09ee08c9f86ea0cd76eb8e` |

Vibe 可借鉴轻量元数据读取、界面聚合、缓存和边界展示。它不是完整港股重大事件筛选方案，不能把 15/5/60 或行业 25 当全量池边界、召回阈值或自动判断。

## 冻结本地证据（未随包上传）

本地 evidence 目录：`/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/announcement_agent_runs/6557712adca825b670f28c5169655db1/evidence`。`body_corpus_manifest.json` SHA-256 `4a314445b6531728e86c5f4488af1cd80ee7b3e15766d48921b0e5c73d1607a2`；`capture_receipt.json` SHA-256 `afbe77870eb0c09899102f98efc3348365af76532d695f08e589a8d84626fe13`；`body_batch/batch_receipt.json` SHA-256 `f26bff4900447c901cabf2c1679bc485cbe6e23a54345c172dbfa7964620545b`。原始 `body_corpus.json` SHA-256 `cc8f005184ad205cacf77b4df3c918345f9cdd8bb9e9c07477a375b74f90a8f1` 仅记 hash，不复制内容；目录响应同样未复制。

语料 issuer completeness 在 manifest 中为 `CANNOT_CONFIRM`；语义未审阅。模型 identity/token usage、独立 label/阈值、API import/readback、活动调度链、自然时段结果均需后续实际验收。
