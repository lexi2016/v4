# 本轮工程测试的复现命令与边界

比较前像为本地隔离提交 `e521e8ebb3119e68095e02b1b54858c0dc0756a9`，其实际文件身份来自 b228 及其冻结前序交付，见 `../source_manifest.json`。测试根为 `/workspace/scratch/a154a3323e32/worktrees/issue29`；不是完整 Mac 应用。Python 为既有 `/workspace/scratch/a154a3323e32/test_env/bin/python`，前端依赖复用原候选安装的 node_modules。详细版本见 `../evidence/test_environment.json`。没有升级依赖。

## 主控扩展 Python 回归

工作目录：隔离测试根。

```bash
PYTHONPATH=.:upstreams /workspace/scratch/a154a3323e32/test_env/bin/python -m pytest -q \
  tests/test_manager_announcement_parity_20261008.py \
  tests/test_manager_input_contracts_20261008.py \
  tests/test_manager_daily_dispatch_20261008.py \
  tests/test_manager_workspace_owner_20261008.py \
  tests/test_manager_daily_channels_20261008.py \
  tests/test_manager_research_router_contract.py \
  tests/test_security_master_store_error.py \
  tests/test_manager_us_mapping_isolation_20261008.py \
  tests/test_manager_history_contract_20261008.py
```

实际：160 passed / 1 failed，exit 1。失败是原 `test_missing_original_archive_is_not_empty_connect_selection` 的 READY/PARTIAL 断言；不是本轮新增用例。对独立导出的同一精确前像执行前七个原文件，得到 126 passed / 同一项 failed，exit 1。日志为 `../evidence/tests/backend_final.log` 和 `backend_baseline.log`。新增两个 Python 文件共 34 项在候选批次中全部通过，不能与 160 再相加。

原依赖仅有已知 Starlette/httpx deprecation warning；本轮未改依赖处理该 warning。

## 新 US 隔离红绿测试

新 Python 文件单独的修改前命令：

```bash
PYTHONPATH=.:upstreams /workspace/scratch/a154a3323e32/test_env/bin/python -m pytest -q \
  tests/test_manager_us_mapping_isolation_20261008.py
```

修改前 6 failed / 1 passed，缺原 schema/reviewed 字段。修改后与原 workspace_owner、Mac StoreError 文件合跑为 26 passed，exit 0；此批包含新 7 项和原 19 项。记录见 `us_isolation_red_python.log`、`us_isolation_green_python.log`。

工作目录切换到 `apps/web` 后：

```bash
V4_TEST_PYTHON=/workspace/scratch/a154a3323e32/test_env/bin/python \
  ./node_modules/.bin/vitest run src/api/managerWorkspace.usIsolation.spec.ts \
  --environment jsdom
```

修改前 5 failed / 1 passed，实际错误 `WORKSPACE_SAFETY_INVALID`；修改后 6 passed。该测试启动原 Python manager GET 生成合成 DTO，再交冻结 Mac `validateManagerWorkspace` 校验，覆盖 9/30、10/8 × 缺模块、reader 抛错四种组合。另检验原 request/首屏 renderer 保留公告股票与理由，以及错日/伪空集拒绝。

fixture CLI 仅创建临时 manager store，模拟缺失/失败的原 US reader；检查 GET 前后所有已存在文件字节相同。它不写业务产品、调用真实采集或构造有效 US 关系。

## 主控限定前端与 TypeScript

工作目录：`apps/web`。

```bash
V4_TEST_PYTHON=/workspace/scratch/a154a3323e32/test_env/bin/python \
  ./node_modules/.bin/vitest run \
  src/api/managerWorkspace.usIsolation.spec.ts \
  src/manager-selection/dailyChannels.spec.ts --environment jsdom

./node_modules/.bin/tsc --noEmit --target ES2022 --module ESNext \
  --moduleResolution Bundler --strict --skipLibCheck --types vitest/globals,node \
  src/api/managerWorkspace.ts src/api/managerWorkspace.usIsolation.spec.ts \
  src/manager-selection/dailyChannels.ts \
  src/manager-selection/dailyChannels.spec.ts \
  src/manager-selection/dailyChannels.testHelper.ts
```

分别为 13 passed、tsc exit 0。空的 `scoped_typescript.log` 配合运行回执 exit 0 表示该限定编译无诊断，不代表完整项目通过。

原完整 `dailyChannels.runtime.spec.ts` 经 Mac 父页导入缺少 `managerAnnouncementAnalysis.js`，测试收集失败。完整父页还缺 `announcementAnalysis` 和与 Mac caller 匹配的 research renderer；没有补 stub。该失败与限定首屏测试分开记录，不能把后者称为完整页面验收。

## 历史合同与独立回归

历史新增测试最终为 27 passed；初始 22 项红灯为 21 failed / 1 passed，随后继续加入原 attempt、语义等边界用例。原四文件冻结基线为 54 passed / 1 failed，加新历史测试后的候选为 81 passed / 同一项 failed。失败 `test_exact_panel_selected_without_latest_substitution` 两版本均返回 `PLAN_HK_02_PANEL_LATEST_MANIFEST_UNREADABLE`。

生产稳定后，独立 reviewer 执行的七文件 Python 组合为 114 passed / 该 HK02 失败，exit 1；新 TS spec 单独为 6 passed，exit 0。确切命令、SHA 和完整日志见 `../evidence/review/independent_result.json`。这些批次有重叠，不合计总通过数。

## 补丁和文件身份

`source_delta.patch` 与 `tests_delta.patch` 在临时目录中逐一 `git apply --check` 后应用，七文件与完整 after 字节一致；再应用对应 reverse patch，四个原文件回到前像、三个新增测试回到不存在。原始业务存储和现役源码均未参与该操作。

复用 R1 未修改的只读校验器，通过本包 `--package-root` 分别对隔离前像、后像执行 `--profile all`：全部七个 payload、七个 source 项和九个 preserve 项通过。此为限定字节检查，不解除运行身份、#28 联合集成、真实 API/UI 或自然执行门禁。
