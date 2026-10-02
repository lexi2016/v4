# HK R3 独立验收

**结论：FAIL，冻结 PASS_SIGNAL 未满足。** 当前 active R9 路径在写入 HK D-1 池时被实际 `PreselectionPoolStore` 拒绝。另有四个 active owner 用例在夹具准备阶段失败，因此 owner 分支的完整行为仍为 `CANNOT_CONFIRM`。

## 发现

### P1：active R9 池合同拒绝 R3 投影字段

实际 active 投影器在 [domains/preselection_materializer.py](../isolated/active_owner_composed/domains/preselection_materializer.py#L492) 写入 `source_manifest_sha256`、`source_receipt_sha256`，并始终写入 `historical_provenance`（第 513–522 行）。实际 R9 池存储器的可选字段仅列于 [infrastructure/preselection_pool_store.py](../isolated/active_owner_composed/infrastructure/preselection_pool_store.py#L47) 第 47–59 行；三者均不在该名单中。验证器第 687–689 行对其他顶层字段报 `invalid preselection-pool fields`。

独立 active 测试的两组完整投影链和 HK-only CLI 都在该存储器处失败，错误为 `ValueError: invalid preselection-pool fields`。这是可复现的 active 集成缺陷，阻止候选 HK 池写入，因而 Stage 无法从此路径消费它。报错没有列出运行时 `unknown` 字段集合，故该集合的确切内容为 `CANNOT_CONFIRM`；但 `historical_provenance` 是投影器无条件加入且存储器未允许的字段，已足以证明合同不兼容。Stage 校验器又在 [hk_input_validation.py](../isolated/active_owner_composed/stage_center/_runner_parts/hk_input_validation.py#L171) 第 171–194 行要求该历史 provenance 及其 D-1 来源身份，修复不得通过丢弃这些身份字段来绕过存储器。

### P2：active owner 四组用例没有进入被测代码

测试夹具 [test_hk_owner_asof_r3.py](../package/tests/test_hk_owner_asof_r3.py#L207) 对实际 R9 的 `infrastructure.scheduling.executor_registry` 设置 `load_isolated_package_module` 属性，但该模块没有此属性。四个参数化 owner 用例均以 `AttributeError` 在第 207 行终止，未调用 owner 行为。A 池字节保全和 owner 对 publisher 的调用结果因此为 `CANNOT_CONFIRM`；应将夹具绑定到实际 R9 导入/复用 seam 后再声称这些行为通过。

## 测试与目标行为

| 验收面 | 结果 | 证据 |
|---|---|---|
| Canonical 19 项回归 | 19/19 断言通过；pytest 进程退出码 1 | [stdout](canonical_hk19_test.stdout.txt)、[stderr](canonical_hk19_test.stderr.txt)、[JUnit](canonical_hk19_test.xml)。退出发生在 pytest 临时目录清理阶段：只读合成快照导致 `PermissionError`，不是测试断言失败。故断言面通过，整条命令不能记为干净 PASS。 |
| Active R9 19 项回归 | 12 通过，7 失败，退出码 1 | [stdout](active_owner_hk19_test.stdout.txt)、[stderr](active_owner_hk19_test.stderr.txt)、[JUnit](active_owner_hk19_test.xml)。3 项为上面的存储合同错误；4 项为上面的夹具属性错误。 |
| 独立 Stage 校验 canary | 3/3 预期结果通过 | [receipt](stage_standalone_canary/receipt.json)：V4 Stage 发布包上的有效合成池被接受；错误 capture 日期和错误 D-1 manifest 身份分别被拒绝。只写入 `ROOT/review` 下的合成文件。 |
| Active owner 完整路径 | FAIL / 部分 `CANNOT_CONFIRM` | 投影链在持久化前失败；owner 专项测试则在夹具 setup 失败。没有 active 端到端通过证据。 |
| 当前 live API、UI、自然运行 | `CANNOT_CONFIRM` | 它们不是此隔离候选测试的证据层。本 reviewer 未重查 live API；不将 parent 于 2026-10-01 报告的当前 HK 页面错误归因于未部署的 R3 候选。 |

## 实际加载来源

所有测试和 canary 使用 `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`（Python 3.14.6）。完整导入路径及每个模块 SHA 见 [canonical_dependency_receipt.json](canonical_dependency_receipt.json)、[active_dependency_receipt.json](active_dependency_receipt.json) 和 [Stage canary receipt](stage_standalone_canary/receipt.json)。

Active carrier 加载的关键来源：R9 publisher `stage_center/hk_universe_preflight.py` SHA `2a0cc677…`; R3 active projector `domains/preselection_materializer.py` SHA `661f78ea…`; 实际 R9 store `infrastructure/preselection_pool_store.py` SHA `e5ead3a5…`; active shared reader `hk_0_2.py` SHA `1ffa950c…`（对应活动包前像 `45a5091c…`）；`hk_security_master.py` SHA `08510caf…`（前像 `a5e93375…`）；`scripts/live_acquisition/universe.py` SHA `b586f0bd…`。publisher 和 `universe.py` 来源与 R9 实际文件一致，没有用 author 的 651 行缓存替代。

独立 Stage canary 使用 Stage release 的 `stage_center/runner.py` SHA `648fe7af…`、候选 `_runner_parts/hk_input_validation.py` SHA `5f3d4cf5…`、Stage release store SHA `a640d28e…`、calendar SHA `584f28d1…`。这项 canary 验证 Stage 接收合同本身，不能覆盖 active R9 writer 的持久化失败。

## 结论边界与修复方向

最小修复由 Chat writer 处理：使 active R9 写入合同与 Stage 所需 provenance 字段兼容，并将 owner 测试夹具绑定到真实 R9 seam；之后由独立 reviewer 复验。此报告没有修改业务代码、活动服务或实际市场数据，也没有执行 provider、网络或交易动作。安全字段保持 `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
