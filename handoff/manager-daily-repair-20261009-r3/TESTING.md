# R3 测试记录与复现

## 最终结果及环境

最终核心：**235 passed，1 warning，12.38s；退出码 0**。邻近原公告 parity：**38 passed / 1 failed，1 warning，2.49s；退出码 1**。不得把两组写成“全测试通过”。

执行环境为原生 CPython **3.14.8**，Linux x86_64/glibc 2.39。运行时原有 `PYTHON_314_REQUIRED` 门保留。早期 3.12 RED/诊断不替代最终 3.14 运行。全部安装版本、解释器信息和测试树身份见 [test_environment.json](evidence/test_environment.json)。原生编译核对 12 个 API 运行文件，没有替换产品依赖或用 stub 修补 import。

最终测试树是 `r3-work/reproduced-final`：交付 helper 从固定提交来源重新装配 **116 件**源文件，全部通过文件 SHA 和 Git blob 身份核对。它不同于开发过程中陆续装配的 candidate。测试 fixture manifest SHA 为：

```text
084ada0c27392ec606fe3927303727f04bc3fe8e466e3a5d463d9fa6650b9be3
```

该闭包只包含针对性合成测试需要的原模块，**不是完整可部署应用**。缺失的其他 owner、Stage 或 updater 依赖不会被模拟成真实部署通过。

## 重建测试目录

在任意有原生 Python 3.14 的隔离环境中，先核验本包。以下 `python3.14` 需指向实际 3.14 解释器，路径变量需替换成自己的绝对路径。

```bash
python3.14 /absolute/path/to/bundle/tools/verify_delivery.py
```

若已有 `lexi2016/v4` 的本地 Git 克隆，且具有问题包固定提交的对象：

```bash
python3.14 /absolute/path/to/bundle/tools/assemble_test_fixture.py \
  --repository-root /absolute/path/to/existing-v4-checkout \
  --output /absolute/path/to/new-isolated-r3-test-tree
```

也可使用按仓库相对路径保存的原快照：

```bash
python3.14 /absolute/path/to/bundle/tools/assemble_test_fixture.py \
  --snapshot-root /absolute/path/to/verified-original-snapshots \
  --output /absolute/path/to/new-isolated-r3-test-tree
```

二者择一。helper 不发网络请求、不读取凭证、不改原源码；所有来源校验通过后才创建输出根。目标已存在、来源缺失、blob/SHA 不符都会拒绝，没有旧日期或旧源码 fallback。缺源失败及篡改拒绝已实际验证。

在隔离虚拟环境中安装 [requirements-test.txt](requirements-test.txt) 的测试依赖。它记录本次实际版本，不要求替换 Mac 现役环境；Mac 原 owner 应使用其批准的解释器和依赖策略另行核验。

## 实际核心命令

以下命令在重建目录中执行。最终原始 argv、cwd、输出和退出码见 [final_core_py314.log](evidence/final_core_py314.log)，结构化结果见 [final_test_results.json](evidence/final_test_results.json)。本次实际解释器为 `/workspace/scratch/6168fe203da9/r3-venv314/bin/python`。

```bash
python3.14 -m pytest \
  tests/test_manager_r3_binding_identity.py \
  tests/test_manager_r3_dates_inputs.py \
  tests/test_manager_r3_cycle_outcomes.py \
  tests/test_manager_daily_dispatch_20261008.py \
  tests/test_manager_daily_automation_20261008.py \
  tests/test_manager_us_daily_automation_20261008.py \
  tests/test_manager_workspace_owner_20261008.py \
  tests/test_manager_workspace_exact_page_binding_20261008.py \
  tests/test_manager_history_contract_20261008.py \
  tests/test_manager_daily_channels_20261008.py \
  tests/test_manager_owner_namespace_contracts.py::test_research_peripheral_namespace_resolves_facade_then_builtins \
  -q
```

其中三个新 R3 测试文件为 **91 + 15 + 14 = 120 项**。独立审查另起进程实跑相同三个文件得到 120 PASS，含在上述范围中，不重复计数。审查四个问题的同一组探针修复前后证据见 `independent_review_red.json`、`independent_review_green.json` 和 `independent_review_probes.py`。

## 明确保留的邻近失败

```bash
python3.14 -m pytest tests/test_manager_announcement_parity_20261008.py -q
```

最终结果为 **38 passed / 1 failed**。节点 `test_missing_original_archive_is_not_empty_connect_selection` 要求 `selection_diagnostics.status == READY`，实际为 `PARTIAL`。该测试未经过新增保存门；在未经 R3 修改的累计 R1/R2 baseline 与本次候选均复现同一断言失败。

主控基线证据为 [r3_existing_archive_baseline_py314.log](evidence/r3_existing_archive_baseline_py314.log)，最终候选证据为 [final_adjacent_parity_py314.log](evidence/final_adjacent_parity_py314.log)。独立审查也另外确认了同样结果。原测试没有改为 xfail、删除或放宽断言。该既有相邻兼容问题仍未关闭；R1 另有 HK supplement P2 的现场行为限制，也没有因本次核心通过而转为 PASS。

唯一 warning 为 Starlette TestClient 对 httpx 的弃用提示。它不是本次门禁、计划或回读失败。

## 为什么调整旧 fixture

R3 实际入口不再用“全无输入”保存成功空计划。旧 dispatch/daily、exact-page、explicit-context owner 正向测试原来缺少已评估输入，本轮补入原公告 builder、import route 和 consumer 产生的真实合成 `NOT_SELECTED` 前提；没有修改原产品保存/回读实现来伪造测试成功。

原重试、并发、重复运行、run/SHA、日期、cutoff 和历史产品字节断言保留。R2 来源漂移测试在已有 immutable 公告产品后模拟新 catalog run，明确要求覆盖 import 返回 409、原产品字节不变，然后原计划变 stale。新的正向选中及合法空结果由独立 fixture 覆盖。

这些改动的完整差异见 `test_changes.json`、`diffs/tests.patch` 与 `before/fixture/`。数据全部为临时合成输入，无真实公告、行情、账户或业务 state 上传。

## 失败与 RED 证据解释

- 最初 binding 和日期输入 RED 复现身份不匹配、缺输入仍造计划等问题；修复后的 GREEN 有对应日志。
- 独立审查的 retry、过窗/未确认分类、historical dynamic canary RED 先保留，再修复并以同一探针复验。
- 早期缺 `interprocess_lock`、缺测试辅助文件或命令路径写错，是隔离来源装配/命令问题；原始日志保留，没有计作生产通过或生产新缺陷。
- 最初 assembler 导入 verifier 生成 `__pycache__` 导致闭包拒绝；已通过禁止该 sibling import 写 bytecode 修复，实际 116 文件重建成功。未通过忽略额外文件来放松闭包。

最终清单和新鲜最终日志是当前源码验收依据；各阶段日志的通过数不可相加。

## 源码、补丁与 live 边界

[package_patch_verification.json](evidence/package_patch_verification.json)记录了临时根中实际 `git apply --check`、正向应用、逐文件字节比对、逆向恢复、原文件集合恢复以及篡改拒绝。四组为 API 12、worker 5、R3-only 7、实现测试 8；API 前后另保留三个 Issue32 SHA。

Mac 原 builder、最新 before/mode/完整运行时 inventory、共享 ownership、真实 canary、生产 binding、实际 API/UI 和自然调度均不在上述合成结论内。状态始终是 `INTEGRATED / DEPLOYED / API / UI / NATURAL = NOT_RUN`。本轮没有发真实 POST、采集、补采或写 live plan/state，也没有部署、服务重启、LaunchAgent/automation 或交易动作。
