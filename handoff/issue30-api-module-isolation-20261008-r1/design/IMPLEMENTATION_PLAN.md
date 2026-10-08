# Issue #30 API Module Release Implementation Plan

本文件保留实施前的计划与检查框，用于追溯初始任务；检查框不代表交付时的剩余工作。最终执行状态请读交付根的 `README.zh-CN.md`、`TEST_RESULTS.json` 和独立最终审查。正文的 `issue30/` 路径指本次隔离工作目录；包内原输入对应 `original/issue30/`，设计对应 `design/DESIGN.md`。

> For agentic workers: use the existing isolated candidate directories, test-first implementation and a fresh final reviewer. Never change the frozen input or other Issue #28 deliveries.

**Goal:** 实现可审查的 API 模块边界与发布隔离候选，并恢复精确 R2 前像的预选池读取。

**Architecture:** 单 FastAPI 装配，预选池 router/service，当前 active + v2 module delta 候选；实际 publisher 在共享指针锁内复核并切换。

**Tech Stack:** Python 3.14.7、pytest 9.1.1、标准库文件与进程锁；必要 API 测试沿用已有可核对依赖。

**Spec:** `issue30/DESIGN.md`，原需求 `issue30/input/ISSUE30.json` 与 `input/baseline/README.md`。

## Global Constraints

- V4/8873 唯一入口，A/HK 分离，Vibe8910 不动。
- RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false。
- 只写新的隔离候选与新 GitHub 工作分支；不 merge/deploy/启停服务/改业务数据。
- 保留原18基线测试、旧FAIL和实际未执行边界，不将合成测试当真实自然运行。

## Review Focus

- 检查结束后 active plist/manifest/app inventory 改变，写前应拒绝。
- 候选路径/config祖先是symlink，不得写到候选外。
- 另一个任务使用不同evidence目录，仍必须竞争同一API指针锁。
- 回滚必须使用记录前像；恢复过程中不能因为active是candidate而错误阻断。
- app共享文件内其他模块必须保留；预选池source/date/partial语义不退化。

## Task 1：根因与基线

- [x] 读取并验证九文件交接包，冻结源码SHA。
- [x] 检查actual execute/rollback与draft build/prepare函数，定位断开的集成检查。
- [x] 独立复跑原18测试；裸包缺依赖collection ERROR单独保留。
- [ ] 补充真实失败探针，记录预期行为与实际结果。

## Task 2：发布核心与真实入口

Files: `ops/api_release_integration.py`、`ops/build_release_candidate.py`、`ops/prepare_api_only_cutover.py`、实际 `api_only_cutover_r2_ready.py` 及针对性测试。

Interfaces: 保留 `build_integrated_app(...)` / `verify_api_release_candidate(...)`；新增 `module_scope(module, shared_paths=())`。实际mutator必须消费 `shared_api_release_lock()` lease 并在写点 `assert_api_release_lock()`。

- [ ] 先写并运行针对stale/delta/late drift/schema/mode/lock的失败测试。
- [ ] 实现v2严格模块合同和末尾身份复核，保留非delta字节。
- [ ] 修builder/prepare路径检查并去掉可绕过guard的裸launchctl/cp发布提示。
- [ ] patch实际execute/rollback/失败恢复，共享锁和固定字节guard接线。
- [ ] 执行迁移后的原行为回归与新增失败注入，保留完整日志和JUnit。

## Task 3：预选池模块化与恢复

Files: `apps/api/v35_api/app.py`、新 `preselection_router.py`、`preselection_service.py`，相关新测试。

- [ ] 读取精确R2前像和必要依赖，保存来源与SHA。
- [ ] 先复现两处已知读取失败，再施加最小修复。
- [ ] 提取专用router/service，证明经理与其他非目标字节保持。
- [ ] 运行独立API回归并明确完整create_app依赖和真实源canary的未执行边界。

## Task 4：独立审查与交付

- [ ] 新的独立Reviewer检查最终候选及针对性风险，并实际复跑交付测试。
- [ ] 修具体审查失败，冻结before/after SHA和最小patch。
- [ ] 生成只读Mac验收/构建说明、差异生成入口和后续授权发布步骤。
- [ ] 同步新独立GitHub工作分支，read-back commit/tree/关键文件，保留其他树项。
- [ ] 最终报告源码与测试结果、阻塞与未执行项，不宣称页面或自然运行已恢复。
