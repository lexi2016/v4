# 固定路由合同

此表是 8873 分流目标。`/api/v4/manager/research` 的 17 个方法/路径由 2026-10-09 当前 Manager router AST 提取；完整源 SHA `84f65a...`。不得用任意方法、任意子路径通配替代。Workbench router SHA `95ccda...`。Stage 所有权按唯一 architect 交接；首次迁移时对目标代码与当前路由注册做逐项复核。

## Stage API

| 方法 | 路径 | 目标后端 |
|---|---|---|
| GET | `/api/v3/meta/stages` | Stage |
| GET | `/api/v3/preselection-pools` | Stage |
| GET | `/api/v3/workbench/stage` | Stage |
| POST | `/api/v3/workbench/stage/ensure` | Stage |
| GET | `/api/v3/stage-center/selection` | Stage |
| POST | `/api/v3/stage-center/selection/ensure` | Stage |

## Manager API

| 方法 | 完整路径 | 当前 router handler | 目标后端 |
|---|---|---|---|
| GET | `/api/v4/manager/research` | `read_research` | Manager |
| GET | `/api/v4/manager/research/status` | `read_research_status` | Manager |
| POST | `/api/v4/manager/research/ensure` | `ensure_research` | Manager |
| POST | `/api/v4/manager/research/retry` | `retry_research` | Manager |
| POST | `/api/v4/manager/research/events` | `refresh_research_events` | Manager |
| GET | `/api/v4/manager/research/jobs/{job_id}` | `read_job` | Manager |
| POST | `/api/v4/manager/research/jobs/{job_id}/cancel` | `cancel_job` | Manager |
| GET | `/api/v4/manager/research/catalyst-observations` | `read_catalyst_observations` | Manager |
| POST | `/api/v4/manager/research/catalyst-observations/refresh` | `refresh_catalyst_observations` | Manager |
| GET | `/api/v4/manager/research/workspace` | `read_manager_workspace` | Manager |
| POST | `/api/v4/manager/research/workspace/refresh` | `refresh_manager_workspace` | Manager |
| POST | `/api/v4/manager/research/workspace/scheduled-cycle` | `run_bound_workspace_cycle` | Manager |
| GET | `/api/v4/manager/research/announcements` | `read_announcements` | Manager |
| GET | `/api/v4/manager/research/announcements/analysis` | `read_announcement_analysis` | Manager |
| POST | `/api/v4/manager/research/announcements/analysis/import` | `import_announcement_analysis` | Manager |
| POST | `/api/v4/manager/research/announcements/refresh` | `refresh_announcements` | Manager |
| GET | `/api/v4/manager/research/{target_trade_date}` | `read_research_by_path` | Manager |
| GET | `/api/v4/manager/workbench-research` | `read_workbench_research` | Manager |
| GET | `/api/v3/manager/stage-selection` | `manager_stage_selection` | Manager, read-only StageSelectionConsumer |

## 代理行为

- 固定 loopback 上游；请求不可指定 upstream URL。保持原方法、路径/query、body、status、content type 和必要响应头，移除 hop-by-hop headers。
- 设有界 connect/read timeout；不得自动重试可能产生写入的 POST。
- 已知分流路径上的错误方法返回 405；已知后端离线返回 503/504，不回退旧 handler。此隔离合同内未知 API 路径 404；平台原有其他合法路由行为保持不变，不做全局 API 拦截。
- Manager 的 `/api/v3/manager/stage-selection` 只能透传已有只读 consumer。不能将 Stage selection state 的 ownership 或写入权移交给 Manager。
