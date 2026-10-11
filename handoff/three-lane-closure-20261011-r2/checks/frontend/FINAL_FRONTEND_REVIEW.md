# Frontend R2 与省略 view 兼容性独立只读审查

## 结论

本次复验范围内，R2 的 exact product-attempt 绑定、未归档超跌空集拒绝、未映射源代码与原始风险首屏呈现均通过；独立发现的未映射引用风险备注缺口已由唯一 Writer 修正，并保留了修改前 RED 证据及修改后 GREEN 结果。

**最终前端结果：50 PASS / 3 FAIL。整体测试门禁并非全绿。** 三项 FAIL 都来自未改动的原 dailyChannels.runtime.spec.ts；原附件控制组为 16 PASS / 6 FAIL。另以相同当前测试定义、R1 API/面板源码和 R1 dailyChannels 原字节构造只读审查对照，结果为 19 PASS / 同三项 FAIL；将路径规范化后，三项失败消息与最终 R2 完全相同。因此这三项失败不是此次 R2 dailyChannels 修改引入。类型检查仍有六条错误，候选和原附件控制组在统一最新新增测试及 fixture 定义后，错误文本逐字一致。

服务端已有原 owner/store/API 集成 6 项通过，独立补充的省略 view / 逆序读取 / HTTP 默认模式 / 日期绑定边界 4 项通过。测试使用合成输入与原应用代码，不能据此宣告真实行情、实机加载、自然时段或真实 10/12 产物闭环已核实。

审查者没有修改 candidate、原附件、原控制组或远程仓库。所有镜像、独立测试、运行缓存和日志均在 review_history/frontend。候选源码变更仅由 Writer 完成。最终 53 项前端测试运行前后，记录中的全部 candidate 前端源文件 SHA256 一致。

## 最终逐组结果

| 测试组 | PASS | FAIL | 判断 |
|---|---:|---:|---|
| threeLaneReadbackR2.spec.ts | 5 | 0 | 两份完整原应用 API fixture 经 validator 与 DOM；exact attempt；未归档空集；源代码/风险纯文本 |
| threeLaneDateBindings.spec.ts | 8 | 0 | R1 日期与视图绑定回归；本次 runner 实际计数为 8 |
| dailyChannels.spec.ts | 7 | 0 | 原三路合同与安全显示回归 |
| dailyChannels.runtime.spec.ts | 19 | 3 | 既有三项失败，R1 独立对照同名且同失败消息 |
| reviewer independentR2Review.spec.ts | 11 | 0 | 新增独立边界，包含已修复的未映射风险首屏显示 |
| **前端合计** | **50** | **3** | **保留真实 FAIL，未重写为通过** |
| 原 test_manager_three_lane_owner_readback_r2.py | 6 | 0 | 原 owner/store/import/API 集成 |
| reviewer test_view_compatibility_independent.py | 4 | 0 | 省略 view 与显式动态/HTTP auto 的兼容边界 |

## 独立复核的关键合同

### Exact attempt 与归档空集

当 `workspace_plan_product_attempt` 存在时，validator 使用该精确记录；其 run、target date、input identity、owner、state、execution kind 任一不匹配均拒绝，即便 `workspace_plan_attempt` 的 latest 记录恰好匹配，也不会回退。显式 null exact 记录同样拒绝；只有字段不存在时才保留旧 latest-attempt 回退合同。另验证 plan product SHA 与 channel SHA 不一致时拒绝，后续 latest FAILED 记录在精确归档成功被接纳时保持原样，不被覆盖或改写。

OVERSOLD 的 READY_EMPTY 必须带归档运行身份，run_id 为 null 的未归档只读回放不能显示为已核空集。原 owner 集成还覆盖保存后空集的精确 product/run 绑定与后续失败运行并存。

### 未映射代码与风险

最终 API fixture 的 H5354 保持原源代码，渠道状态 PARTIAL，候选数量未知；DOM 不制造 `HK.05354` ticker。映射成功行与未映射源引用的原风险均按纯文本显示；新增 Writer 测试覆盖 `<script>literal</script>` 字面内容保留而 DOM 无 script 元素。

独立检查先在最终完整 API fixture 的副本中为 `unmapped_references[0].risk_notes` 加入合成风险文本，运行真实 validator 与 renderer。修改前 H5354 可见而该风险首屏不可见，得到 10 PASS / 1 FAIL。Writer 仅补充未映射条目的经 strings 检查的风险纯文本节点；同一独立测试修改后 11 PASS。测试未更改原 fixture、原产物或 candidate。

### 省略 view

`ManagerResearchJobService.get_workspace(..., view=None)` / 省略 view 继续使用旧内部保存 cutoff 读取；显式过去日期 `view='dynamic'` 使用当前时刻回溯。独立测试先读 explicit dynamic 再读 omitted/None，仍分别得到当前 cutoff 与保存 cutoff，未发生读取模式串用。

HTTP 路由自己的省略 view 默认仍为 auto；过去日期 GET 进入 HISTORICAL_AS_OF，保持保存 cutoff。改变公告日期绑定时，省略 view 也不会挪用不匹配保存上下文；同一香港日显式 dynamic 仍使用保存 cutoff。以上读取均比较 owner store 前后文件快照，未产生数据写入。

## 保留的三个 runtime FAIL

1. `binds the publication alias deterministically through the actual GET: publication_date=20261006`
2. `rebinds one legacy default GET when a new backend returns different display/publication dates`
3. `renders stock, original reason, data date, run and status without expanding diagnostics`

原附件控制组还失败的另外三项，在当前候选通过：同时含两个公告日期别名的读取、手工生成后重载、legacy 重绑定进行中取消。比较使用同一个未改动 runtime spec，SHA256 `c300e175a184a6a9e365c5d99a2977ea8cc8c8eed27fbedb3291785a83bd640e`。

为了避免“同一个用例在更早断言失败”掩盖因果判断，本次额外隔离 R2 dailyChannels 单文件变化：API/面板源码与已核 R1 相同，将 dailyChannels 恢复为 R1 原 SHA256 `c4983a1bb3f23ea4ee3cfc598b805f2dc765a525b263156a4d7f6428767d24c4`，维持同一测试文件与数据。此 R1 前端对照同样 19 PASS / 3 FAIL，最终 R2 三项 failureMessages 在路径归一化后完全相同。此对照只存在于 reviewer 目录，没有回写 candidate。

## 保留的六条 typecheck 错误

```text
src/App.vue(6,26): error TS2307: Cannot find module './views/ResearchView.vue' or its corresponding type declarations.
src/manager-selection/__tests__/fixtures/issue8R2.fixture.ts(3,26): error TS2307: Cannot find module './issue8R2.ownerObservations.json' or its corresponding type declarations.
src/manager-selection/__tests__/fixtures/issue8R2.fixture.ts(13,49): error TS7006: Parameter 'row' implicitly has an 'any' type.
src/manager-selection/__tests__/fixtures/issue8R2.fixture.ts(26,38): error TS7006: Parameter 'row' implicitly has an 'any' type.
src/views/ManagerSelectionView.spec.ts(4,1): error TS2578: Unused '@ts-expect-error' directive.
src/views/ManagerSelectionView.spec.ts(6,1): error TS2578: Unused '@ts-expect-error' directive.
```

候选与原附件控制组最终错误文本完全一致。控制组只在 reviewer 镜像中统一了最新 threeLaneReadbackR2.spec.ts 和两份新 fixture，以保证比较使用同一测试定义；没有修改控制组生产源码或原控制目录。源 tsconfig 保持 noEmit。

## 最终源与 fixture 身份

| 文件 | SHA256 |
|---|---|
| dailyChannels.ts | `790ed5b485d2b6dc7649f654f692f1fe612778839fd508ee5c4eefa61f23a599` |
| threeLaneReadbackR2.spec.ts | `b653d6cfe9df82ffe4a64ea07788832bbf46d44acc13e43bacb339cf5ed97e83` |
| 完整 H5354 API fixture | `8db8b87e45cb107324d156e1216f5f8694a3f75b10a77d98596837be060a4a9e` |
| 完整 retrospective API fixture | `0dd7b4f1362f05eee471c238b598c5fcfc5ef3daadda1ed690b9c70d5337b71d` |

风险修正前 dailyChannels 为 `339ee7ebe15b36d97c45ec07db9bed781bb4db5127d258206bb913c4b5a4f35d`。修改前两个源码文件保存在 unmapped_risk_red_source/；原 RED 日志和 JSON 未覆盖。

## 证据索引

- final_summary.json：最终逐组数量、类型检查比对、源码前后稳定性。
- candidate_final_results.json / candidate_final_vitest.log：53 项前端测试真实结果。
- independent_boundary_results.json / independent_boundary_vitest.log：未映射风险缺口的修改前 10 PASS / 1 FAIL。
- control_runtime_results.json / control_runtime_vitest.log：原附件 runtime 16 PASS / 6 FAIL。
- r1_counterfactual_runtime_results.json / r1_counterfactual_runtime_vitest.log：隔离 R2 增量的 R1 对照 19 PASS / 3 FAIL。
- comparison_result.json：失败集合、最终失败消息和 typecheck 文本比较。
- candidate_final_typecheck.log / control_final_typecheck_uniform_tests.log：真实六条旧错误。
- python_owner_result.xml / python_owner_pytest.log：原 owner/store/API 6 PASS。
- python_view_result.xml / python_view_pytest.log：独立省略 view 4 PASS。
- source_snapshot_before.json / source_snapshot_final_before.json：镜像建立与最终复验源码 SHA。
- test_harness_notes.json：只用于 reviewer 镜像的 cacheDir / config loader 适配说明。

首次使用 runner 配置加载时遇到原 vite.config.ts 的 `__dirname` bundler shim 缺失，尚未执行测试。仅在 reviewer 配置将该构建路径改为同一镜像绝对路径后运行；原启动错误日志保留为 *_runner_startup_error.log，不作为产品测试失败统计。
