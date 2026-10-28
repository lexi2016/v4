# 8873 系统基线入口

## 当前状态（2026-09-13）

- 用户研究任务统一从 `/Users/lexi/Desktop/学习/00_研究入口/8873-研究入口.webloc` 打开 `http://127.0.0.1:8873/`；该目录只是稳定导航，不是第二面板或新服务。
- 快捷入口不固定日期；页面按交易日选择。当前导航基线为 `/?date=20260914`，周日默认日期仍是 `20260911`，记录基线为 A D-1 主池 11、Stage7 10、观察 39、HK 100。
- 唯一源码仓库是 `/Users/lexi/Desktop/学习/v4_app`，当前分支为 `codex/system-consolidation-20260912`，HEAD 为 `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`。
- 运行版本必须实时读取 `com.lexi.v35.api-only.plist`、`com.lexi.v35.scheduler.plist` 和 `runtime-baseline.json`；本次核对记录 API 为 `20260913-global-industry-compact-no-flat-v1/app`、scheduler 为 `20260913-a-panel-entrypoint-fix-v16/app`。两者仍是分层绑定，不能仅凭路径视为同一已部署版本。
- 当前 A 数据指针由运行时 `state/workspace/数据`、实际 API/scheduler 绑定和来源合同解析；学习根下 `数据/` 的旧 pointer 只能作导航材料，不能直接冒充运行权威。
- 其他研究目录和旧面板属于后台、历史或待迁能力；完成 owner/依赖盘点与 V4 验收前，不作为可自由启动的替代面板。
- `8910`、`8872`、`8771` 仍在运行；`8898`、`8899` 当前无监听。停服、切换和回退须由后续独立复核与主控操作完成。
- M2 工具已独立 PASS，证据为 `.../reviewer_m2_p1/reviewer-m2-p1-verdict.json`；旧 candidate 不可直接激活，需按 receipt 新建候选。
- M3 reader/display 已独立 PASS，证据为 `.../reviewer_m3_p1/reviewer-m3-p1-fix-verdict.json`，尚未部署；真实 generation candidate 尚未审查或接入。
- 实时状态 receipt `.../cleanup-20260913/runtime-status.json` 显示 8873 `/api/v3/review?date=20260911` 尚无 `research_review` 字段，3A 仍为 `11/39/10`；因此 M3 仍是已审源码而非已部署能力。
- 资讯雷达合并、底层抓取去重、完整独立 V4 验证和旧系统退役均未完成；优化 ZIP 不重新应用。
- 本次清理已移出未接入且审查发现不适合激活的官方 TDX 全包候选及其测试；删除前的精确 bytes 保存在 `.../cleanup-20260913/pre-cleanup-source-rollback-20260913.tar`，正式数据、release 和调度绑定未改。
- 清理记录中的 local-only patch 仅是历史回退步骤；当前 `a_share_daily_sync.py` 的增量、预算和 wrapper 修复已由独立 reviewer PASS，candidate-r2 尚未激活，证据为 `.../alignment-20260913/sync-increment-budget/review/final-review.json`，不能写成已部署。
- `research_review_generation` 五个候选文件仍未审查、未接入；持续生成 owner 归属保持 `CANNOT_CONFIRM`，不能把历史读取或候选代码当作接管。

本目录是 8873 应用的唯一源码基线。运行 release、LaunchAgent、API、scheduler、数据根和页面是不同证据层，必须分别记录；未通过对应门禁时保持 `CANNOT_CONFIRM`。

## 精简 bug 修复约定

这是项目执行约定，当前不是由程序自动强制的流程：

1. 从实际服务的 command、cwd、env 和最近成功 run 复现，再定位第一处差异。
2. 每批冻结一个缺陷和一个主要变更；保留用户修改与可回退输入。
3. 用同一可部署候选验证真实公开入口及下游行为；子模块、mock、`--help` 只能辅助，不能单独替代端到端验收。
4. 先做有界小样本，PASS 后才做必要全量；同一 SHA 已 PASS 的检查不重复运行。
5. 废弃方案在同批移出源码，保留精简回退说明；源码、部署、API、UI 和自然运行状态分开记录。

本次约定变更的过程 receipt 只写入 `/Users/lexi/Desktop/学习/agents调试/system_consolidation_20260912/cleanup-20260913/`。

## 规范边界

运行源码范围固定为：

- `apps/api`
- `apps/web/src`
- `domains`
- `infrastructure`
- `v4`
- `ops`
- `contracts`
- `stage_center`
- `upstreams/v3_shared_data` 中受 Git 管理的共享数据组件代码

`stage_center` 是阶段采集与消费所需组件；`upstreams/v3_shared_data` 是共享数据的必要上游。`v3_shared_data`、`upstreams/review_core`、`upstreams/v3.5` 的符号链接身份和目标字符串属于运行绑定，校验时只读取链接元数据，不递归读取或复制目标数据。

`apps/web/dist` 是生成的前端资产，当前源码树没有对应的受 Git 管理目录。源码与 release 的选定范围可以通过工具重复确认；生成资产、release manifest、runtime inventory、外部 upstream 目标内容仍需各自的证据门，未具备时保持 `CANNOT_CONFIRM`。

历史 `v3.5` 目录只作为只读归档和语义参考，不是 8873 的源码 fallback、producer 或运行时依赖。本轮不改该目录，也不从其中复制业务实现。

## 重跑同源校验

从本目录执行；这是只读示例，执行前重新读取当前 API plist/runtime-baseline 的 release root，不沿用历史 release 路径：

```bash
/Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac/bin/python ops/verify_source_release.py \
  --source-root "/Users/lexi/Desktop/学习/v4_app" \
  --release-root "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260913-global-industry-compact-no-flat-v1/app" \
  --receipt "/Users/lexi/Desktop/学习/agents调试/system_consolidation_20260912/source-release-compare.json" \
  --git-snapshot-dir "/Users/lexi/Desktop/学习/agents调试/system_consolidation_20260912/git-snapshot-after-writer"
```

退出码 `0` 表示选定源码范围的文件字节、文件类型、权限模式与符号链接身份均一致；退出码 `1` 表示选定范围有缺失、多余或不一致；退出码 `2` 表示输入或 Git 读取失败。receipt 中的 `selected_scope_status=PASS` 只证明选定范围同源，`deployment_status` 在未补齐生成资产和 runtime inventory 证据前保持 `CANNOT_CONFIRM`。

工具默认从 Git 选取受管理和未被忽略的文件，并排除本批加入的三个治理/部署辅助工具：`ops/verify_source_release.py`、`ops/build_release_candidate.py`、`ops/prepare_api_only_cutover.py`。它们是在既有 release 之后加入的证据与候选准备工具，不改变固定运行源码范围。`--git-snapshot-dir` 只在证据目录写入 Git 状态、diff、diff stat 和未跟踪文件摘要，不写入源码或 release。

## 本批回退证据

证据根目录为 `/Users/lexi/Desktop/学习/agents调试/system_consolidation_20260912/`。其中 `launchagents_before_20260912/` 保存了四个相关 plist 的原始副本，供后续依赖审查和回退核对；本轮只读备份，不执行 `launchctl`。

源码基线锚点为 `main@55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`，当前工作分支为 `codex/system-consolidation-20260912`。不提交、不推送；reviewer 应在实际 diff、receipt、测试和 release 路径上独立复跑。

历史基线观察：默认日期 `20260911`；预选池 `279` 行（A179/HK100，状态 `PARTIAL`）；`STAGE_0925` 20 行、`SHARED_STAGE_CENTER_READ_ONLY`；manager 10 行、状态 `PARTIAL`；review contract `v3_5.review_envelope.v1`。运行图 app root 可验证，但缺 inventory/dependency manifest 时总状态仍为 `CANNOT_CONFIRM`，这些观察值不升级为部署或自然运行结论。
