# 实际命令与执行范围

## Writer 最终提交字节：Python

工作目录：`/workspace/scratch/81f12368319d/work/candidate`。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/workspace/scratch/81f12368319d/work/candidate:/workspace/scratch/81f12368319d/work/test_support uv run --offline --no-project --python 3.14 --with pytest --with fastapi --with httpx python -m pytest -q -p no:cacheprovider --import-mode=importlib tests/test_three_lane_history_20261011.py tests/test_three_lane_identity_20261011.py tests/test_three_lane_daily_20261011.py tests/test_three_lane_announcement_20261011.py tests/test_three_lane_review_clock_20261011.py tests/test_manager_workspace_targeted_r2.py::test_tampered_saved_plan_not_presented_as_success tests/test_manager_workspace_targeted_r2.py::test_exact_date_saved_plan_cannot_hide_new_owner_failure --basetemp=/workspace/scratch/81f12368319d/work/final_committed_backend_tests
```

结果：`68 passed, 1 warning in 4.27s`，exit 0，原 stdout 见 `backend-committed-final.log`。Warning 是已有 FastAPI/Starlette 的 TestClient/httpx 弃用提示。本轮未为该提示替换产品依赖。

独立 Reviewer 使用另一个 basetemp 实际复跑 `68 passed, 1 warning in 4.26s`，精确命令、原工具返回记录性质与 nodeid 见 `backend_final_recheck_record.txt/json`。这是根据实际已观察工具结果写出的记录；不冒充当时用 tee 保存的日志。

新增文件分布：history 11、identity 21、daily 23、announcement 9、review-clock 2，共 66；另 2 个原保存门禁回归。history/daily 的数据是测试构造的保存产品和精确 attempt；其中真实 service/history 原入口与原 validator 照常运行。未采集或补造实际业务数据。

## Writer 最终提交字节：前端

```bash
node /workspace/scratch/81f12368319d/work/web_toolchain/node_modules/vitest/vitest.mjs run --config /workspace/scratch/81f12368319d/work/web_toolchain/vitest.config.mjs src/manager-selection/__tests__/threeLaneDaily20261011.spec.ts src/manager-selection/__tests__/threeLanePanel20261011.spec.ts src/manager-selection/catalystObservationPanel.runtime.spec.ts -t '^(?!.*renders the actual Eastmoney owner workspace)'
```

结果：`43 passed | 1 skipped`，exit 0。新增 34 + 原 runtime 9。独立 Reviewer 同一目标集 `43 passed | 1 skipped`，exit 0，4.90 秒，原日志见 `independent-final-green.log`。

唯一 excluded test 是 `renders the actual Eastmoney owner workspace readback instead of reporting a network failure`，要求未提供的实际 Mac 绝对路径 `workspace_after.json`。这个限制一直保留，未伪造 fixture。

Vitest 配置使用现有 Vue plugin、jsdom 和单 worker；root 是隔离的 `work/web_test_app/apps/web`。三份生产源、两份新测试和 JSON fixture 与最终 candidate 的字节已由 Reviewer 比对一致。依赖恢复链见 `dependency_provenance.json`，没有把已恢复的 cache 工具链当成完整 Mac 应用。

```bash
node /workspace/scratch/81f12368319d/work/web_toolchain/node_modules/typescript/bin/tsc --noEmit -p /workspace/scratch/81f12368319d/work/web_test_app/apps/web/tsconfig.three-lane-check.json
```

结果 exit 0，无诊断。配置副本见 `tsconfig.three-lane-check.json`；覆盖三个修改模块和它们实际导入的源码，未执行完整前端 build。

## 最终补丁和语法

- Python 3.14 AST 解析全部 15 个交付 `.py` 业务/测试文件通过；两个只读交接 helper 也解析通过。
- `git diff --cached --check` 在提交前通过；独立 Reviewer 的最终 `git diff --check` 通过。
- 初次 staged check 发现**从固定源复制的测试 fixture 末尾多一个换行**；仅移除这 1 个字节，不改测试内容。原始/交付 SHA 均保留在 `SHA_MANIFEST.json`，提交后 68 项再通过。原 test_support 仍保留固定源原字节。
- 在独立 before 目录对实际 `source.patch` 执行 `git apply --check`、apply；之后 22 个文件全部等于 after SHA。插入一次合成源漂移后 preflight exit 2，未改动该漂移文件；全过程记录见 `verification.json`。
- `collect_readback.py` 本轮仅运行 `--help` 和语法核查；HTTP 执行 NOT_RUN。

## Mac 复跑方式

以下仅为交接命令，**不是本轮执行记录**。在已按 SHA/三方合并验证的完整候选根，使用现场原 Python 和依赖运行同一相对测试集合。不要使用本会话的 `/workspace/...` 路径，也不要将隔离支持目录覆盖进 app。

```bash
"$V4_PY" -m pytest -q -p no:cacheprovider --import-mode=importlib tests/test_three_lane_history_20261011.py tests/test_three_lane_identity_20261011.py tests/test_three_lane_daily_20261011.py tests/test_three_lane_announcement_20261011.py tests/test_three_lane_review_clock_20261011.py tests/test_manager_workspace_targeted_r2.py::test_tampered_saved_plan_not_presented_as_success tests/test_manager_workspace_targeted_r2.py::test_exact_date_saved_plan_cannot_hide_new_owner_failure
```

`V4_PY` 应是现场原 v3.5-mac Python，完整绝对路径见 README。前端按原 lockfile 恢复项目依赖，在原 web 根通过既有 Vitest 入口运行相同三份文件；如实际 Mac fixture 存在，恢复该测试并独立验证其真实 owner 证据。

此外必须补上当前配套 Stage execution module 的完整 consumer 集成、实际三路输入/owner运行/归档、真实 8873 API与浏览器重载、实际旧 10/12 identity 前像重算，以及自然 scheduler receipt。上述 68/43 不能替代这些项目。
