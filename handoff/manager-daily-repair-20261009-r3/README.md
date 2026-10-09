# 经理每日研究计划 R3：代码修复与 Mac 交接

**代码修复、独立审查和合成合同验收已完成。真实 20261008/20261009 计划是否生成、普通页面是否读回、自然调度是否恢复，仍未验收。** 本包不代表已接入或已部署。

输入是固定提交 [`b98d85c95d19780e2900dce7de9372328e67acf6`](https://github.com/lexi2016/v4/blob/b98d85c95d19780e2900dce7de9372328e67acf6/handoff/manager-daily-failure-20261009-r3/README.md) 的 R3 问题包，沿用共享基线 `66bb05a2e12976775ccb997191ce943bae8cc9a5`。R1/R2 的 API 修复已纳入完整后像；本次新改动集中在 7 个原运行文件。实际源码根、前后 SHA 与来源见 [source_manifest.json](source_manifest.json)。

## 修复结果

| 问题 | 本次行为 |
|---|---|
| 调度 worker 与 API 根不同，binding 不一致 | 同一原始 binding SHA 贯穿请求与回执；显式 `plan_owner_binding` 分别固定 worker 和实际 API 的源码根与完整文件清单。SHA、根、enabled、canary、state/master 门继续校验。 |
| 错误被笼统化、HTTP 200 冒充成功 | 区分 `NOT_TRIGGERED`、`GATE_REJECTED`、`INPUT_NOT_READY`、`OWNER_FAILED`、`READBACK_UNCONFIRMED`、`OWNER_RESULT`，同时核对 parent receipt 与原 owner 的 run/product/input/attempt。 |
| 无合法输入也保存空计划 | 实际入口在第一次计划持久化前检查原通道输入；缺失或未评估保留 CANNOT_CONFIRM 和原因，不造 plan run、product SHA、attempt 或股票。完整合法评估得到零结果可以保存并追溯。 |
| 一个缺失通道阻断独立合法结果 | 已验证的公告等合法通道仍可保存，逐股理由和证据继续绑定；US 源采集成功本身不能代表 daily mapping 完成。 |
| 日期与回读身份 | 10/8 事后 run 用显式 `dynamic`，普通 `auto` 保持原历史资格；10/9 已保存当日计划由默认 `auto` 读回同日期、run、SHA、输入身份及原 cutoff。 |
| 输入后来到齐却不重试 | 未就绪诊断不再被当作成功终态缓存；沿用原有退避与有界预算。已验证成功仍保持幂等，不因重试生成重复计划。 |
| 新双根历史 canary 与事后 URL 冲突 | 新身份的历史 canary 验证精确日期与显式 `view=dynamic`，拒绝重复或额外参数。旧单根 URL 和原迁移校验保持。 |

[绑定与 canary 合同](docs/BINDING_CONTRACT.md)说明规范摘要、生成顺序和配置示例；[输入与日期合同](docs/INPUT_AND_DATE_CONTRACT.md)说明三日期映射、合法零结果及历史兼容边界。

## 已实际完成的验收

| 验证层 | 结果及证据 |
|---|---|
| 最终核心回归 | **235 passed，1 warning，12.38s，退出码 0**；在从清单重新装配的 116 文件测试闭包中执行，原生 CPython 3.14.8/Linux。见 [最终日志](evidence/final_core_py314.log)。 |
| 独立审查 | 初始 3 项发现、4 个复现均关闭；独立合跑三个 R3 文件 **120 passed**。这些用例包含在核心范围内，不重复累加。见 [审查报告](evidence/independent_review.md)。 |
| 邻近原公告回归 | **38 passed / 1 failed**。失败为 `test_missing_original_archive_is_not_empty_connect_selection`：期待 READY、实际 PARTIAL；未修改的 R1/R2 基线与候选均同样失败，原测试和失败保留。见 [邻近日志](evidence/final_adjacent_parity_py314.log)及[基线对照](evidence/r3_existing_archive_baseline_py314.log)。 |
| 源码与补丁 | 12 个 API 运行文件通过原生 3.14 编译；API 12、worker 5、仅 R3 7、测试 8 个文件的补丁均通过正向与逆向字节恢复。见 [补丁验证](evidence/package_patch_verification.json)。 |
| Issue32 保护 | `app.py`、`preselection_router.py`、`preselection_service.py` 三 SHA 与问题包一致；未进入补丁。见 [结果 JSON](evidence/final_test_results.json)。 |

唯一 warning 是 Starlette TestClient 使用 httpx 的弃用提示。最初 RED、依赖装配失败、修复中回归失败及最终结果均保留在 `evidence/`；不能把某轮局部通过当成总体验收。完整命令、依赖版本及复现方法见 [TESTING.md](TESTING.md)。

## 包内交付

- `after/api/`：完整的累计 API 后像，共 12 份；其中包括原 API 内的 HK supplement consumer。
- `after/worker/`：问题包实际 bound worker 的 5 份完整后像，独立前像与补丁，保留其余 worker 依赖。
- `before/`、`diffs/`、`source_manifest.json`：每个根的精确前像、最小正反补丁和 SHA。`r3_only` 只适用于已经达到 R1/R2 精确后像的代码审查，不能直接应用到现役 R1-before 根。
- `tests/`、`test_changes.json`、`test_fixture_manifest.json`：必要实现测试、原测试前提调整、116 份原源依赖的固定提交/路径/blob/SHA。
- `tools/verify_delivery.py`：只读核验包与指定前像/后像。`tools/assemble_test_fixture.py`：从已存在的固定 Git 对象或原快照重建测试目录，目标必须不存在；不下载、不部署。
- [prior_candidates.json](prior_candidates.json)：R1/R2 另外 9 份 web、HK child、HK upstream 候选的精确复用引用。本轮没有这些现役根的完整前像，未把它们混入 API/worker 补丁，未重新声称其 UI/HK 行为验收通过。

包不是完整现役 API 镜像；测试闭包也不能用作 release root。

## Mac 接入仍有明确门槛

现行共享 owner policy 的实测拒绝为 `API_RELEASE_MODULE_PATH_NOT_OWNED`。下列五条必要 API 路径，须由**原共享 owner**依既有流程审查登记并通过实际 ownership 门：

1. `infrastructure/_research_peripheral_store_parts/_namespace.py`
2. `infrastructure/scheduling/manager_announcement_supervisor.py`
3. `ops/render_manager_announcement_binding.py`
4. `ops/run_manager_announcement_cycle.py`
5. `v3_shared_data/shared_data/hk_daily_supplement.py`

调用方填 `shared_paths` 或写一份登记 JSON，不能使现行 policy 自动放行。包中没有修改 policy。原始 15 个只读探针见 [共享路径证据](evidence/shared_owner_scope_audit.json)。现行 builder 未随问题包提供，旧整树装配器还固定到旧根，不能当作当前正式入口。

后续由原 owner 重新固定最新累计 API/worker 根、before/mode、完整 inventory 和 Issue32 保护 SHA，完成上述门禁后建立隔离累计候选；再准备同版本 binding 与真实 owner canary，并按获授权范围另行接入、部署和业务验收。具体步骤和只撤销本增量的回滚要求见 [Mac 接续合同](docs/MAC_INTEGRATION_CONTRACT.md)。

输入包中的公告 NOT_IMPORTED/NOT_RUN、HK authority 缺失、US daily NOT_RUN 仍是待现场确认的输入问题；本次没有补采或生成 live 计划。R1 HK supplement 的既有 P2 限制与 HK child 并行冲突也继续保留。

## 分层状态

`IMPLEMENTED=COMPLETE`；`TESTED=PASS_CORE_WITH_EXISTING_ADJACENT_FAILURE`；`INDEPENDENT_REVIEW=PASS_WITHIN_SCOPE`。

`INTEGRATION_GATE=BLOCKED_PENDING_EXISTING_SHARED_OWNER`；`INTEGRATED / DEPLOYED / API / UI / NATURAL = NOT_RUN`。这里 API 指真实现场 API，合成 route 测试已单独计入 TESTED。

全程保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`；Stage、BUY、Vibe8910 未改。本次未调用真实 owner POST、读写真实 plan/state、补采、启停服务、修改 LaunchAgent/automation 或交易。
