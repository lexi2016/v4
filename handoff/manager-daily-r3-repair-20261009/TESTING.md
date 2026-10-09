# R3 定向测试、复现命令与保留失败

## 环境和证据等级

本轮运行在 Linux 的隔离源码装配，Python **3.14.6**、pytest **9.1.1**、FastAPI **0.141.1**、Starlette **1.6.0**、httpx **0.28.1**。实际解释器为 `/workspace/scratch/a154a3323e32/test_env/bin/python`，源码根为 `/workspace/scratch/21926b793c00/candidate`。这是已存在的环境，本轮没有安装依赖。最初默认解释器缺少 pytest 的错误保留于 `evidence/baseline_receipt.json`。

固定原源码只有在 Git blob 与问题包所在提交一致后才用于装配。R1/R2 after、R3 三个 Issue32 保护文件与当前 shared scheduler 按实际角色覆盖测试上下文。装配故意没有补造缺失的 `apps/__init__.py`、`ops/daily_materialize.py` 等生产文件；旧测试采用其原有的限定模块 loader，新 binding fixture 在临时目录生成明确标注的惰性合成文件，以测试真正的清单校验。它们不能证明完整应用启动或实际 Mac 导入闭包。

所有测试数据均在 pytest 临时目录；没有真实 owner POST、采集、plan/state 读取或写入、服务启停、配置变更或部署。HTTP 路径由 FastAPI TestClient 在进程内执行，不是访问 8873。一次既有 `StarletteDeprecationWarning` 与环境中 httpx 兼容提示有关，原样保留。

## 本轮实际结果

各组有重叠，**不把分组 PASS 数累加为独立用例总数**。最终三份 R3 新测试合并结果和文件身份在 `evidence/final_scoped_receipt.json`，最终补丁回放在 `evidence/patch_replay.json`。

| 范围 | 实际结果 | 证据 |
| --- | --- | --- |
| 固定 R1/R2 daily / US / exact-page 基线 | 24 passed | `evidence/baseline_scoped.log`、`baseline_receipt.json` |
| 最终三份 R3 新测合并 | **66 passed**：binding 44 / product 9 / HK 13 | `evidence/final_scoped_after_review.log`、`final_scoped_receipt.json` |
| 双根 binding 与 dispatch 最终组 | 86 passed：44 新合同 + 36 既有 daily dispatch / automation + 6 独立真实路径探针 | `evidence/binding_green_final.log`、`binding_identity.log` |
| R3 两日产品、来源指针、合法空与缺输入 | 9 passed | `evidence/product_contract_green.log` |
| 真正 API nested HK consumer、child 入口、合成原 owner 链 | 13 passed | `hk_validation/final_scoped.log`、`HK_TEST_EVIDENCE.json` |
| 五条 exact path 发布政策候选 | 9 passed | `evidence/release_policy_green.log` |
| 验包工具原六项与独立闭集三项 | 9 passed | `evidence/package_verifier_hardened.log` |
| 独立产品 / 原 daily channels / 政策 / 验包断言第一组 | 43 passed | `independent_review/frozen_contracts.log`；后续发现及修复以最终独立报告为准 |
| 验包工具加固后独立复验 | 15 passed | `independent_review/verifier_hardened_independent.log` |
| 完整 Mac app、web typecheck/build、真实 API/UI、自然时段 | NOT_RUN | 不引用 R1/R2 以前的本机结果为本轮重新测试 |

### 本轮确实出现、没有抹去的失败

- **产品相邻组 98 passed / 1 failed。** `test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection` 期望 `selection_diagnostics.status=READY`，实际为 `PARTIAL`。将被改的 daily-channel 模块恢复为本轮前像，在独立进程同样复现；见 `product_preexisting_failure_baseline.log`。该旧测试、原业务状态逻辑均未改。
- **binding 相邻组 39 passed / 4 failed。** 四项旧 `test_manager_announcement_plan_refresh_only.py` fixture 的 `SimpleNamespace` store 缺少既有 `_transaction` 合同；本轮未改该事务函数。同文件使用 `c973cbc` 的前像 cycle 在隔离进程得到相同 **4 failed / 3 passed**，见 `binding_preexisting_confirm.log`。没有去掉锁，也没有修饰旧断言。
- **原 HK supplement 组 13 passed / 2 failed。** `test_screen_uses_master_universe_sidecar_volume_and_missing_only_price_overlay` 与 `test_complete_panel_history_skips_sidecar_and_preserves_canonical_baseline` 是已记录的 screen 失败，日志 `hk_validation/original_supplement.log`；原测试字节仍等于固定 R1。单位 / inherited scale / 六日 finality 仍 `NOT_PROVEN`，不得为通过测试伪造证明。
- **首次 HK scoped 11 passed / 2 failed** 及第二次依赖错误保留。原因是四文件 child 测试根缺少物理邻接的原 `hk_universe_preflight.py`，随后还缺原 `live_acquisition/contracts.py`。最终测试只在临时装配补入有来源 SHA 的纯测试依赖，原 owner 断言不变后 13 passed。两个 live-acquisition 源仅放 `reference/test_dependencies`，不在运行补丁内。
- **有效 RED 与装配错误分开。** 产品来源指针 RED、binding 合同与失败分类 RED、owner 清单 / malformed receipt RED、旧政策拒绝 RED、独立 verifier 三个 fail-open RED 都保留。`binding_red.log` 最初全失败是测试装配缺包入口，不能当成已证明全部生产缺陷；后续 `binding_red_contract.log` 才是有效合同 RED。产品第一个 US fixture 因未固定 source-generation clock 失败，修正的是 fixture，真实 cutoff 校验未削弱。
- **最终独立审查补出真实 PREOPEN 包装层缺口。** 旧 safe wrapper 将超时误归普通失败，且全大写异常消息能成为原因；前三份新测的初版 61 passed 没覆盖这个真实包装层。独立三项异常 RED 与 writer 四项 RED / 一项原 PARTIAL PASS 保留。最终只在原 `workspace_plan_autorun.py` 捕获处按异常类型识别超时，有限枚举保留原 gate 原因，未知文本归稳定 code；新增五项真实路径病例，最终三份新测为 66 passed。原 PARTIAL/gaps 不过滤。

独立最后一组首次额外预装测试 namespace loader，产生 85 passed / 1 fixture 失败；按本文原始 `-m pytest` 命令去掉该额外装配后独立 86 passed。该中间日志也保留，未修改任何 loader、生产源码或断言。

没有将任何失败改成 xfail / skip。详细独立审查附本轮发现、修复后复验及原失败的证据边界。

## 在本轮装配重现

先设置实际存在的隔离根与解释器，保持所有命令只面向测试根。不要把下例变量改为现役 app 或业务 state。

```bash
export manager_r3_test_app=/workspace/scratch/21926b793c00/candidate
export manager_r3_python=/workspace/scratch/a154a3323e32/test_env/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$manager_r3_test_app:$manager_r3_test_app/upstreams:$manager_r3_test_app/tests"
export V4_R3_HK_CHILD_ROOT=/workspace/scratch/21926b793c00/hk_child_candidate
export V4_R3_INPUT_PACKAGE_ROOT=/workspace/scratch/21926b793c00/input/remote/handoff/manager-daily-failure-20261009-r3/package
export V4_R3_OWNER_TEST_DEPENDENCY_ROOT=/workspace/scratch/21926b793c00/hk_validation/test_dependencies
cd "$manager_r3_test_app"

"$manager_r3_python" -m pytest -q -p no:cacheprovider \
  tests/test_manager_r3_binding_contract.py \
  tests/test_manager_r3_product_contract.py \
  tests/test_manager_r3_hk_continuation.py

"$manager_r3_python" -m pytest -q -p no:cacheprovider \
  tests/test_manager_daily_dispatch_20261008.py \
  tests/test_manager_daily_automation_20261008.py
```

以下命令用于重现保留的失败，预期 exit code 非零，不能据此声称新 R3 合同失败或整个应用通过：

```bash
"$manager_r3_python" -m pytest -q -p no:cacheprovider \
  tests/test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection
"$manager_r3_python" -m pytest -q -p no:cacheprovider \
  tests/test_manager_announcement_plan_refresh_only.py
"$manager_r3_python" -m pytest -q -p no:cacheprovider \
  tests/test_hk_daily_supplement_r4.py
```

原来源的前像复验记录了内存模块装载命令和结果；只在测试进程替换被查模块，未将源码树 reset 成旧版。

## 从交付包在 Mac 隔离环境复验

本包 `tests/app/` 保存三份 R3 新测与所需原 helper / 定向回归测试。`test_source_manifest.json` 记录每个测试文件的来源与 SHA。原 helper 必须处于隔离测试 app 的 `tests/` 下，以保持其 `__file__.parents[1]` 的真实相对导入；只将本包列出的测试源装入隔离副本，不把整包当完整 app。其余真实依赖从已核源码继续复用。

原测试输入包的 HK02 三件只读源码已包含在 `reference/r3/package/source_snapshot/hk02_updater_actual/`；如果重用原 R3 包，也必须先核其固定身份。HK after 三件需与 `reference/preserved/hk_child_conflict/ops/_macos_research_panel_daily_parts/_namespace.py` 在独立 child 副本中组合；namespace 仅为保留原字节，不是新增的运行补丁。

```bash
export manager_r3_package=/absolute/path/to/manager-daily-r3-repair-20261009
export manager_r3_test_app=/absolute/path/to/verified/isolated/api/app
export manager_r3_python=/absolute/path/to/verified/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$manager_r3_test_app:$manager_r3_test_app/upstreams:$manager_r3_test_app/tests"
export V4_R3_HK_CHILD_ROOT=/absolute/path/to/verified/isolated/hk/child/app
export V4_R3_INPUT_PACKAGE_ROOT="$manager_r3_package/reference/r3/package"
export V4_R3_OWNER_TEST_DEPENDENCY_ROOT="$manager_r3_package/reference/test_dependencies"

cd "$manager_r3_test_app"
"$manager_r3_python" -m pytest -q -p no:cacheprovider \
  tests/test_manager_r3_binding_contract.py \
  tests/test_manager_r3_product_contract.py \
  tests/test_manager_r3_hk_continuation.py

cd "$manager_r3_package"
export V4_R3_POLICY_SOURCE="$manager_r3_package/release_policy_review/after/ops/api_release_integration.py"
export V4_R3_REVIEW_APP_ROOT="$manager_r3_test_app"
export PYTHONPATH="$PYTHONPATH:$manager_r3_package/independent_review"
"$manager_r3_python" -m pytest -q -p no:cacheprovider \
  tests/test_manager_r3_release_policy.py tests/test_r3_delivery_verifier.py \
  independent_review/test_verifier_manifest_closure.py
```

独立复验对 Issue32/shared scheduler 保护源码的检查，需要 `V4_R3_REVIEW_APP_ROOT` 指向相同保护身份的隔离测试装配；它不说明当前 API 根中存在一个正在运行的 scheduler。完整本机应用的 import、既有 web typecheck/build 和 UI 验证另按原 owner 流程执行，不加载为缺失导入准备的测试惰性文件。

## 通过测试仍不能声称的事情

真实公告 import、US 当日 mapping、HK V2 membership / master / PIT / 六日单位来源尚待原 owner 确认。实际 HK02 updater 仍缺 supplement producer module/CLI，不能把 API consumer 的通过写成 producer 已恢复。没有真实两日 plan run / product SHA，也没有当前 API/UI 或连续自然日成功收据。

研究 flags 始终为 `RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
