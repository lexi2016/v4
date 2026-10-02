# PR20 R4 独立验收

结论：**REVIEWED=FAIL（P2 provenance 边界缺口）**。指定 active reported 套件在当前服务 Python 下 **27/27 通过**，7 个旧失败用例和 20 个 R4 用例均通过；R3+R4 的目标链路在合成数据与隔离服务边界下 **BEHAVIOR_VERIFIED=PASS**。P2 发现是另一个可复现的 provenance 不一致边界，见下文。

实际活动隔离副本为 ROOT/isolated/active_r9_app。R4 的两份运行文件 SHA 与 SOURCE_SHA256.json after 值一致：R9 store 为 aae429b1…fc05d3，owner helper 模块为 9a9f633e…c757a969。本次使用 /Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python，版本 3.14.6，macOS 26.6.2 arm64。精确命令只运行一次，完整结果在 [result.json](active_reported_20261002/result.json)、[JUnit](active_reported_20261002/junit.xml)、[stdout](active_reported_20261002/stdout.txt) 和 [stderr](active_reported_20261002/stderr.txt)。

**P2：store 和 Stage 会接受 natural_verified=true。** R4 store 扩展只检查 production_allowed、buy_gate_updated、orders_sent 三项为 False（isolated/active_r9_app/infrastructure/preselection_pool_store.py:129-131），没有约束 provenance 中的 natural_verified。实际 shared eligibility reader 明确将此值设置为 False，并说明仍需要原 parent scheduler receipt（isolated/active_r9_app/upstreams/v3_shared_data/shared_data/hk_security_master.py:299-301）；Stage 的 provenance 检查同样只验证 SAFETY_FLAGS，不检查 natural_verified（isolated/active_r9_app/stage_center/_runner_parts/hk_input_validation.py:182-194）。我把 R4 合成 artifact 中该字段单独改成 True，实际 R9 store 成功物化，实际 Stage _validate_hk_d1 也通过。反例收据在 [natural_flag_probe_r4.json](natural_flag_probe_r4.json)。这证明边界可保存并放行与当前来源语义相反的自然验证声明；**不能据此声称正常 producer 会产出 True**。建议 R9 store 与 Stage strict boundary 都要求 natural_verified is False，并加负例回归。若另有允许 True 的正式 producer 合同，本次未找到，状态为 CANNOT_CONFIRM。

我另行检查了真实 R9 facade 的 helper 重绑定：真实 FixedExecutorRegistry._preselection_pools 函数的 __globals__ 指向 facade 模块，code object 与 owner source 相同；在空的合成数据根上执行实际 facade 方法及嵌套 owner 方法后，两个显式 helper import 均可解析，调用在 producer/subprocess 之前按预期 fail-closed。收据见 [dependency_probe_r4.json](dependency_probe_r4.json)。

依赖探针记录了实际加载路径和 SHA：R9 publisher stage_center/hk_universe_preflight.py 为 2a0cc677…a0f4ec；shared hk_0_2.py 为 1ffa950c…eb145a4，hk_security_master.py 为 08510caf…17d654，store.py 为 87042083…b52a16，managed scripts/live_acquisition/universe.py 为 b586f0bd…3040b。套件实际执行了 publisher、shared reader/projector 和 Stage 验证代码，但 Futu quote、源行、membership 与 subprocess 都是合成边界；因此这是**真实代码 + 合成数据/外部边界**验收，不是实际市场来源读取。完整真实 provider 组合、历史原件恢复、API/UI、自然运行均为 CANNOT_CONFIRM，不由这次 27 项测试推出。

未发现 P0/P1。未改业务源码或测试，未调用真实 provider、selection 或服务；新增探针和输出都在 ROOT/review，金融安全标志保持 False。
