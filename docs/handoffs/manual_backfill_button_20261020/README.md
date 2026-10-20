# 手动补采按钮：Writer 交接

状态：IMPLEMENTED，Writer 定向检查通过，独立 Reviewer 待验收。未部署、未现场采集、未更改服务或业务数据、未提交推送。

冻结目标：当前阶段页显示“补采集”，仅阶段8可执行；HK 收盘区有同名入口。按钮 POST 固定日期/目标/阶段，读取有限次进度，完成后按原日期刷新。其他阶段明确不可用。

## 实际行为

- 阶段8当日15:50–15:55：真实调用 owner 的 `StageCenterRunner._prepare_hk_active_snapshots` → `prepare_due_snapshot` → `prepare_hk_active_snapshot`。成功只称“阶段快照已采集；尚未生成阶段选股”。
- 阶段8过窗：先核对固定 replay 根下精确文件 `YYYYMMDD/STAGE_1545_1555/hkconnect_rtdata_stage_replay_YYYYMMDD_STAGE_1545_1555.csv`。缺文件直接返回具体缺口，零行情请求。存在时复用 owner 的 `tick(...historical_backfill=True, historical_markets=('HK_CONNECT',))`，其既有校验和独立 backfill namespace 保留。结果显示 BACKFILL/历史观察、行数和 run id，不升格原自然阶段。
- HK 收盘：API release 既有 `collect_close_snapshot` → `build_close_review`。完整缓存优先复用；历史缺缓存不请求 Futu；缺 review 才生成，已有有效 review 只读复用，来源 SHA 必须与当前快照一致。无效原记录保留。真实 `MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE` 显示“已有产出，仍有缺口”。
- 同目标运行中/成功重复点击返回原 job；失败后仅显式点击、间隔至少30秒、最多3次。全局 owned mutex 保证单个补采执行，无队列。任务进入下一步前检查5分钟预算；慢的健康 owner 不被杀掉，后台工作线程继续持锁等其真实结果。页面每轮最多20次、每次1.5秒查询，然后显示“查看进度”。
- 日期/目标切换和组件卸载会停止页面查询，不取消后端。父页面仅在事件日期/阶段仍匹配时刷新。
- 服务重启时，持久 owner PID 和 child PID 防止把遗留任务重新执行。child 收到 JSON 前先持久登记其 PID；父进程退出但 child 存活时其他任务拒绝，child 已退出且未取得最终回执则 `recovery_required`，不把退出当成功，不自动重放。

## 运行补丁与基线

工作分支 `codex/manual-backfill-button-20261020-r1`，本地基线 `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`。

该 Git 基线是旧单体 App；worktree 的 app.py/App.vue 仅加小接线。**集成必须使用 runtime.patch**：它以实际 `announcement-daily-workflow-20261020-r8/app` 为基线，包含4个新增生产文件及 app.py/App.vue 小 hunk。实际 HK 收盘刷新使用 `loadCloseReview('HK', true, false)`，保证跳过页面读取缓存；仅 HK 复盘显示该按钮。未复制 canonical 的并行修改，未修改 AppShell。

runtime.patch 已在独立临时目录对 r8 及远端固定 `3a3891414469d826aaaaa9bfdb8f95191e2af739` 两份 app.py/App.vue 做 `git apply --check` 和临时应用。部署前主控仍须核最新字节及绑定。

## 服务端绑定（主控负责配置）

注册 close 数据根使用 `V35_REVIEW_CORE_CLOSE_ROOT`，不是默认 API 的 `V35_DATA_ROOT`。该配置应指向现役 v35 `state/data`。job receipt 默认放在该数据根的同级 `manual_collection/`；不上传运行 receipt/行情。

`V4_MANUAL_COLLECTION_STAGE_CONFIG` 指向一个**服务端** JSON 文件。仅允许以下字符串绝对路径键，extra keys 拒绝，不能原样复制包含其他调度字段的 tick 配置：

| 键 | 要求 |
|---|---|
| candidate_acquisition_root, raw_root, selection_root, receipt_root, hk_d1_root, shared_data_root, python_path | 全部必需，沿用现役 stage owner 根；selection_root 必须与 API 读取绑定一致 |
| preselection_source_root, hk_second_filter_root, hk_full_universe_root, hk_auction_root, hk_stage_replay_root, v4_research_data_root, v4_morning_news_root | 可选，只能按现役 owner 配置填写；未配置 replay 时不能恢复过窗阶段8 |
| stage_owner_root, stage_owner_python | 必须成对出现；部署到 r8 时必须提供，使用下列已确认 owner |

当前确认的 owner：

```text
stage_owner_root=/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-stage8-network-20261020-r1/app
stage_owner_python=/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python
权威配置=/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-stage8-network-20261020-r1/app/stage_center_tick_config.json
```

从权威配置逐项选取上述 runner keys，加上 owner 两键，生成新的固定 binding 并记录 SHA。不改变原配置。服务加载时冻结 JSON 和 SHA。固定 subprocess argv 为 `[stage_owner_python, '-c', 固定程序]`，`shell=False`，cwd 固定 owner 根，输入只通过 JSON stdin。实际时间由 owner 读取；浏览器不接收根、python、脚本、provider、force 或 now 参数。

## Writer 验证与边界

最终后端目标环境：r8 只读依赖 + 新 service/router；窗口内 owner 为上面的真实修复 owner，离线 canary 仅替换 quote transport、D1 fixture 和时钟。真实 API→service→subprocess→owner runner→precapture→snapshot 函数路径执行，产物只写 pytest 临时目录。

```sh
V4_MANUAL_COLLECTION_DEPENDENCY_ROOT='/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-daily-workflow-20261020-r8/app' \
V4_MANUAL_COLLECTION_STAGE_OWNER_ROOT='/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-stage8-network-20261020-r1/app' \
V4_MANUAL_COLLECTION_STAGE_OWNER_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' \
/Users/lexi/Desktop/学习/v4_app/.venv/bin/python -m pytest tests/test_manual_collection.py --import-mode=importlib --basetemp=/tmp/v4-manual-collection-review-UNIQUE -q -k 'not test_real_stage8_precapture_path_with_fake_transport'
```

已执行目标环境结果：20 passed / 1 deselected。排除项是 **API 进程直接 import StageCenterRunner 的旧 canary**；此前未适配 r8 完整运行18项得到17 passed/1 failed，错误为缺 `stage_center._runner_parts.configuration` 等。r8是读取包，不能直接执行完整 runner。新增实际 owner subprocess canary替代这条部署路径，原失败保留，不复制业务依赖。

canonical 早期同进程路径18项通过，仅支持其自身依赖，不据此称 r8 兼容。

前端仅4个新增候选文件及两份 spec复制到临时测试 overlay，node_modules只读链接现有依赖；`vitest run src/api/manualCollection.spec.ts src/components/ManualCollectionControls.spec.ts`：10 passed。`vue-tsc --noEmit -p tsconfig.json` 对此同范围 overlay 通过。未运行全仓前端 build/全仓回归。

已覆盖：真实收盘采集和复盘、真实 owner 快照采集、缓存复用、原记录不变、双击去重、其他目标不排队、窗口/日期/休市/Origin/额外参数拒绝、过窗缺回放零请求、PARTIAL保留、错误/进度展示、迟到日期响应隔离、限次查询、服务中断回执。历史 replay 正向测试验证隔离调用合同和来源 SHA；没有真实合规 replay fixture，完整历史选股的实际产出仍 CANNOT_CONFIRM。

初次 pytest 另遇共享系统 pytest 临时清理的既存 PermissionError；改用本任务独立 `--basetemp` 后消失。没有删除/清理其他任务临时目录。

NOT_RUN：独立 Reviewer、集成、部署、现场补采、实际 API/UI readback、自然时段、GitHub同步。主控接续；Writer 检查不等于独立验收。

## 当前 owner 的完整服务端 binding 示例

以下 JSON 仅供主控在候选 release 内保存；writer 未创建运行配置或改服务。

```json
{
  "candidate_acquisition_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data",
  "hk_auction_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/opening_second_filter",
  "hk_d1_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data",
  "hk_full_universe_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data",
  "hk_second_filter_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/opening_second_filter",
  "hk_stage_replay_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/stage_references",
  "preselection_source_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data",
  "python_path": "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python",
  "raw_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/raw",
  "receipt_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/receipts",
  "selection_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection",
  "shared_data_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-stage8-network-20261020-r1/app/upstreams/v3_shared_data",
  "v4_morning_news_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data",
  "v4_research_data_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data",
  "stage_owner_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-stage8-network-20261020-r1/app",
  "stage_owner_python": "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
}
```

环境示例：`V4_MANUAL_COLLECTION_STAGE_CONFIG=<候选 release 内该 JSON 的绝对路径>`；`V35_REVIEW_CORE_CLOSE_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data`。

子进程 PYTHONPATH 固定为 owner/upstreams:owner，V35_APP_ROOT 固定 owner，两个 REVIEW_CORE_PACKAGE_ROOT 固定 owner/upstreams，release id 从 owner 权威配置核对；不继承 API 的旧依赖身份。job 记录 binding SHA、owner 权威配置 SHA 及 runner/snapshot/precapture SHA，执行前重核，变化即拒绝。
