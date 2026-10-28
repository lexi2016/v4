# 8873 第二阶段：可重建候选 release

本文记录第二阶段的候选构建约束。候选只用于独立审阅和回退准备，不代表已发布或已激活的 8873 服务。

## 构建范围

`ops/build_release_candidate.py` 从当前唯一 `v4_app` Git checkout 读取全部 tracked 文件，并显式加入当前 `apps/web/dist`。候选目录同时保存每个文件的 SHA-256、聚合树摘要、源码 commit、tracked diff 摘要和未跟踪文件摘要。`dist` 当前是 Git 忽略目录，因此没有把它从来源清单中默认为已存在；构建会在缺失或为空时失败。

候选不会复制 `state`、`runtime`、`runtime-data`、`.runtime`、`artifacts` 或任何市场数据。`upstreams/v3_shared_data` 的代码文件按 Git 清单复制，`v3_shared_data`、`upstreams/review_core` 和 `upstreams/v3.5` 的符号链接保留原链接文字，只记录目标存在性，不递归读取链接目标。

当前 persistent-minute 入口和 M3 reader/display 有三个未跟踪但被 tracked 入口直接使用或 import 的文件，只有显式重复传入以下参数时才加入候选：

- `--include-untracked-path ops/run_v35_macos_scheduler_daemon.py`，由 `ops/launch_v35_macos_scheduler.sh` 的 persistent-minute 分支证明；
- `--include-untracked-path domains/daily_research_review.py`，由 `apps/api/v35_api/review_router.py` 的 `load_daily_research_review` import 证明。
- `--include-untracked-path apps/web/src/components/review/DailyResearchReviewPanel.vue`，由 `apps/web/src/views/ReviewView.vue` 的组件 import 证明。

工具只接受这三个固定路径，并要求它们当前确实是 regular untracked files；不会自动复制其他 untracked 文件。`domains/research_review_generation/` 等未审查候选必须继续留在候选之外，但仍会在 Git snapshot 中记录为未跟踪。

一次构建示例（使用新的证据目录；目标已存在时工具拒绝覆盖）：

```bash
VENV="/Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac"
EVIDENCE="/Users/lexi/Desktop/学习/agents调试/system_consolidation_20260912"
SOURCE="/Users/lexi/Desktop/学习/v4_app"
python="$VENV/bin/python"
candidate="$EVIDENCE/candidate_release_20260912_v4app_8873_m2"

"$python" "$SOURCE/ops/build_release_candidate.py" \
  --source-root "$SOURCE" \
  --candidate-root "$candidate" \
  --api-plist "/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist" \
  --scheduler-plist "/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist" \
  --python "$python" \
  --release-id "20260912-v4app-8873-candidate-m2" \
  --backup-plist "$EVIDENCE/launchagents_before_20260912/com.lexi.v35.api-only.plist" \
  --legacy-repo "/Users/lexi/Desktop/学习/v3.5" \
  --legacy-evidence-root "$EVIDENCE/legacy-v35-git-snapshot" \
  --include-untracked-path "ops/run_v35_macos_scheduler_daemon.py" \
  --include-untracked-path "domains/daily_research_review.py" \
  --include-untracked-path "apps/web/src/components/review/DailyResearchReviewPanel.vue"
```

`release-manifest.json` 是候选的机器可读清单；`config/com.lexi.v35.api-only.plist` 是只写在候选目录中的暂存配置；`config/api-only-cutover-plan.json` 只有未来的 bootout/bootstrap 和回退命令文本。工具不会调用 `launchctl`，不会写 `~/Library/LaunchAgents`，不会写正式 release 目录，也不会修改 scheduler plist。候选根和 receipt 已存在时均拒绝覆盖。

## API-only 与 manager state

暂存 API plist 保留当前 `V35_RUNTIME_ROOT`、`V35_DATA_ROOT`、共享数据根、stage-center selection 根、解释器和四个研究安全旗；只替换候选 app/release/manifest 身份，并加入：

```text
V4_MANAGER_RESEARCH_STATE_ROOT=<candidate>/state/manager_auto_research
```

当前 manager state 根是 `~/Library/Application Support/com.lexi.v35.local/state/manager_auto_research`。新结果的权威提交布局记录为：

```text
<manager-state>/.commits/<YYYYMMDD>/<input_identity>.json
```

旧 `products/`、`jobs/`、`receipts/` 不在本阶段迁移或重算。候选 state 只创建空的 `.commits` 目录，不复制历史文件；清单记录 `candidate_state_copied=false`。未来切换前必须先让旧 API writer 离开当前根，再启动候选 API；新旧进程不得同时写同一个 manager state 根。回退计划恢复当前 plist 和原 manager root。

## scheduler 审计结论

工具只读比较 `com.lexi.v35.scheduler.plist` 当前绑定的 release 与 v4 checkout 的 scheduler launcher、scheduler module、`run_scheduled_slot.py`、`collect_runtime_graph.py`、`contracts/runtime_workloads.json` 和 HK 0.2 launcher，并检查当前路径绑定与安全旗。

本次观测中 launcher、scheduler module、`run_scheduled_slot.py` 和 workload contract 均有字节差异；当前 release 还有 v4 source 缺失的 `ops/launch_hk_0_2_python_nosite.sh`。当前绑定的运行路径与 safety flags 可继续作为现有后台 owner 保留，但这些差异无法证明 v4 重绑定的时序和语义等价。因此候选结论是 `RETAIN_CURRENT_BINDING_ONLY` / `semantic_parity=CANNOT_CONFIRM`，本阶段不自动重绑 scheduler，也不改变其职责。

## 验收边界

- `candidate_status=READY_FOR_REVIEW` 表示候选复制、当前 dist 清单和依赖探针完成；它不等于部署。
- 依赖探针记录解释器、模块实际 `find_spec` 目标、存在性、版本和代码 SHA；没有把探针伪装成正式 runtime inventory 或 dependency manifest，后者保持 `CANNOT_CONFIRM`。
- `activation_status=NOT_ACTIVATED`、`deployment_status=CANNOT_CONFIRM` 在候选清单和 cutover plan 中固定记录。
- `source.explicit_untracked_paths_copied` 和 `source.explicit_untracked_provenance` 记录本次受控 M3 include；未传参数时为空，未审查 untracked 不会进入 `app`。
- 8873 API、重新加载 UI、自然调度和自然数据修复不在本阶段；这些状态需要后续独立验收。
