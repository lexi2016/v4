# Issue #30 可携带隔离测试入口

`run_tests.py` 放在交付包根目录，使用根目录 `TEST_INPUTS.json` 指定并校验所有测试输入。它只运行源码测试，不部署、不触及真实服务或业务数据，不安装依赖。发布测试使用临时 Git 仓库；切换脚本测试替换真实 launchd/HTTP 操作；预选池测试加载完整新 router/service 和准确的 app 注册 AST，配合未修改的历史依赖文件及合成池数据。完整现役 R2 `create_app`、线上 API/UI 和自然时段验收仍为 `NOT_RUN`。

## Manifest 合同

根对象只允许 `schema_version`、`files`、`suites` 三个字段。JSON 对象不得有重复 key。

```json
{
  "schema_version": "v4.issue30.portable_test_inputs.v1",
  "files": [
    {"path": "after/ops/api_release_integration.py", "sha256": "<64 个小写十六进制字符>", "size": 123},
    {"path": "run_tests.py", "sha256": "<入口文件 SHA256>", "size": 456}
  ],
  "suites": {
    "release": {"expected_tests": 85},
    "cutover": {"expected_tests": 21},
    "preselection": {"expected_tests": 26}
  }
}
```

上面仅为格式片段，不是可运行的完整清单。`files` 必须包含下表全部输入和入口 `run_tests.py`，按 `path` 升序排列；路径、大小写折叠后的路径均不得重复。只接受相对 POSIX 路径，禁止 `..`、`.`、重复斜杠、反斜杠、软链接、硬链接及特殊文件。所有现存祖先目录也必须直接可打开，不得先解析软链接再接受。输入字节的 SHA256 和长度必须匹配。`TEST_INPUTS.json` 不列入自身清单。

`files` 可以额外列入完整原始 9 件问题包、文档或证据；这些文件同样校验，但不会自动加入 Python 导入路径。下表的运行目录中出现清单外文件，或出现入口无法映射的额外运行输入，都将报错。新增测试可直接列入 `tests/release/*.py`、`tests/cutover/*.py` 或 `tests/preselection/*.py`，冻结后同步更新对应套件的 `expected_tests`。其余运行输入是明确列出的固定依赖闭包，增加文件需要同时审阅并更新入口。

清单同时控制预期收集数。示例计数仅反映最初约定，组包主控必须填入**本轮最终冻结版本**的准确计数；入口不会自动把收集结果写回预期值。

## 交付目录与隔离副本

| 交付包相对路径 | 隔离副本（相对输出目录） | 要求 |
|---|---|---|
| `after/ops/{api_release_integration,build_release_candidate,prepare_api_only_cutover,create_api_module_delta}.py` | `isolated/release/ops/` | 4 个候选发布文件 |
| `test_support/release/ops/{release_candidate_sources,release_candidate_audit,build_release_candidate_stage,release_candidate_ports,stage_service_overlay_contract}.py` | `isolated/release/ops/` | 5 个未修改的真实依赖 |
| `tests/release/*.py` | `isolated/release/tests/` | 扁平目录的冻结测试文件 |
| `after/actual_cutover_reference/api_only_cutover_r2_ready.py` | `isolated/cutover/work/cutover_analysis/candidate/` | 实际 R2 切换入口的候选 |
| `tests/cutover/test_actual_api_cutover.py` 和其他已列入 manifest 的 `*.py` | `isolated/cutover/work/cutover_analysis/tests/` | 冻结的合成切换测试；下行探针有单独映射 |
| `tests/cutover/probe_cutover_boundaries.py` | `isolated/cutover/work/cutover_analysis/` | 旧版失败边界探针 |
| `after/ops/api_release_integration.py` | `isolated/cutover/work/integration_core/candidate/ops/` | 同一候选 core 的第二份已校验副本 |
| `original/issue30/source/actual_cutover_reference/api_only_cutover_r2_ready.py` | `isolated/cutover/input/baseline/source/actual_cutover_reference/` | 精确原版 |
| `original/issue30/source/unreviewed_draft/ops/api_release_integration.py` | `isolated/cutover/input/baseline/source/unreviewed_draft/ops/` | 精确原稿，用作合成基线 |
| `after/apps/api/v35_api/{app,preselection_router,preselection_service}.py` | `isolated/preselection/after/apps/api/v35_api/` | 3 个预选池候选 |
| `tests/preselection/{scope_api_harness,test_preselection_source_root_20261008,test_issue28_preselection_hk_fallback,test_issue30_preselection_module}.py` 和其他已列入 manifest 的 `*.py` | `isolated/preselection/tests/` | 1 个边界组装入口、3 个原测试文件及新增独立审查测试 |
| `test_support/preselection/...` | `isolated/preselection/test_support/...` | 下列 21 个真实历史依赖 |
| `original/r2_app/apps/api/v35_api/app.py` | `isolated/preselection/source/r2_app_byte_match/apps/api/v35_api/` | SHA 精确匹配实际 R2 的 app 单文件 |
| `original/two_hunk_reference/apps/api/v35_api/app.py` | `isolated/preselection/source/two_hunk_reference/apps/api/v35_api/` | 旧两处修复的原样对照 |

21 个预选池支持文件为：`contracts/{stages,trading_calendar,trading_safety}.py`，`domains/preselection.py`，`infrastructure/{data_store,interprocess_lock,isolated_package_loader,market_time,owned_io,owned_path,preselection_pool_readers,preselection_pool_sources,preselection_pool_store,preselection_pool_transactions,review_core_fupan_pool_source,review_core_stage7_pool_source,scope_gate,trading_safety}.py`，`stage_center/{calendar,contracts,selection}.py`。

## 运行

使用已安装依赖的 Python 3.11 或以上环境，并具备 POSIX `fcntl` 和 `O_NOFOLLOW`。发布套件需要 `git`；三个套件均需要 `pytest`；预选池套件额外需要 `fastapi`、`httpx`、`starlette`、`pydantic`、`anyio`。入口会先实际导入并记录版本与来源；缺失时明确报告 `DEPENDENCY_ERROR`，不会安装依赖或替换生产模块。

```bash
python -B /absolute/package/run_tests.py \
  --python /absolute/venv/bin/python \
  --output-root /absolute/new-issue30-test-run
```

省略 `--python` 时使用启动入口的 `sys.executable`。虚拟环境解释器常为软链接；解释器是显式选定的可信执行程序，不属于被禁止 alias 的问题包源码输入，入口保留虚拟环境原路径以维持其依赖环境。

输出目录必须是全新的绝对路径，父目录已存在，且位于交付包之外；不会覆盖已有目录。macOS 的 `/tmp` 通常是软链接，应使用实际祖先路径（例如 `/private/tmp/...`）或用户目录下无别名的路径。入口保留输出，便于查看失败证据；不会修改原始交付包。

每个套件运行单独的 `python -B -m pytest -q -p no:cacheprovider` 子进程，使用明确的空 pytest 配置、测试根和 `--confcutdir`；关闭第三方插件自动加载，清除继承的 Python/pytest/Git 配置、认证和服务环境变量，重新设置已校验副本的 `PYTHONPATH`。临时目录在该输出目录内。子进程 `umask` 固定为 `022`，避免文件权限 fixture 依赖发起者的 shell 设置。预选池保留作者的 warnings-as-errors 规则及指定的 Starlette 弃用警告例外。

`--timeout-seconds` 默认为每套 900 秒；依赖探针最多 60 秒。超时只结束入口创建的新进程组。入口没有网络或真实服务指令，也不会安装依赖；已校验的源码和选定的解释器仍属于可信执行代码，此入口不构成操作系统沙箱。

## 结果判断

输出包含输入验证、精确复制映射、每套环境/依赖版本、原始 pytest 日志、JUnit XML、收集与执行事件 JSON、每套 `result.json` 和总 `SUMMARY.json`。原始包与全部隔离源码在运行后再次验证，避免把变动字节的结果写成冻结候选通过。

只有以下条件全部满足，套件才是 `PASS`：

- pytest 进程正常结束且退出码为 0；
- 实际收集数、唯一 node id 数、call 阶段通过数均等于冻结清单预期值；
- 未发生 deselect、collection error、失败、setup/teardown 错误、skip、xfail 或 xpass；
- JUnit 声明测试数与 `<testcase>` 实际元素数均等于预期值，失败/错误/跳过的属性和元素数均为 0。

任一套件不满足条件，总结果为 `FAIL`；独立套件仍继续执行以保留完整情况。退出码 `0` 表示三套及输入复核通过，`1` 表示已完成测试但结果不满足合同，`2` 表示输入、路径或启动错误。缺失依赖记录为对应套件 `DEPENDENCY_ERROR` 并导致总失败。输入核验失败时不会创建输出目录；执行中的异常可能留下部分证据，不能视作通过。

这些通过结果只证明冻结源码在记录的解释器与合成依赖闭包下通过；不能记为源码已集成到 Mac、已经部署、真实预选池页面已恢复，或港股阶段/历史数据/自然运行已验收。
