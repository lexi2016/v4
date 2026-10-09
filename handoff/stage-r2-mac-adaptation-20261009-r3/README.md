# Stage R3：适配本机准备阻断与当前 Vue

这份候选直接修复 Mac 回传的三个准备阻断，并补齐精确测试门禁。Stage 16 / API 2 的业务 after 保持 R2 字节；当前 Vue 基于此次上传的实际前像制作最小补丁。完整可执行步骤在 [MAC_APPLY.md](MAC_APPLY.md)。

基线：`7a9c94d43a296372488541b02e8e35a0f763dc1a`。反馈：`3112c1ee8ed2826c5d77b5d0a4f1e2cd5fc95e45`，其父为原始反馈 `4db264512b71723cb13680c4f7554deef401ef44`，后续提交加入独立验收报告。Git 关系与反馈文件对象已记录在 [evidence/GIT_INPUT_IDENTITY.json](evidence/GIT_INPUT_IDENTITY.json)。

## 本轮代码变化

| 阻断 | 修复与保留边界 |
|---|---|
| Stage prepare 见 symlink 即失败 | 固定 SHA 绑定的 `CANARY_SOURCE_POLICY.json` 明确允许内部 `v3_shared_data -> upstreams/v3_shared_data`；仅记录并隔离那条精确外部 v3.5 链接。未知链接、改指、内部逃逸仍拒绝。外部目标内容与元数据均不通过遍历读取。 |
| API 副本 0555/0444，无法建临时文件 | 原根不改权限；仅临时调整新副本中必要目录的 owner 写/遍历位，写完恢复原目录及文件模式，核对字节/模式与源不变。旧 partial copy 保留，新目标必须不存在。 |
| UI 与旧包前像不匹配 | App 使用此次完整 27,412 字节前像，补丁 `+51/-3` 行；runtime 原 1,540 字节前缀完整保留；组件明确新增。UI 源集合限 `apps/web`，根目录 pytest 残留不属于依赖。 |
| prepare 后 canary 再卡链接/权限 | 驱动使用同一政策与候选 manifest，接受固定内部别名，正确处理只读 shared 副本。R3 政策候选缺失/篡改 manifest 会在写输出或执行 owner 前拒绝。 |
| 测试少跑也可能 PASS | Stage/API/adaptation 检查 JUnit 实际 testcase/outcome 与声明总数；Vue 两套检查完整 TAP 计数。每套数量固定，skip/failure/error/cancel/todo 必须为 0；缺报告或缺套件均失败。 |

来源清单由 prepare 在完整所选源集合上生成，记录原路径、字节 SHA、模式、链接身份、政策 SHA 与候选树 SHA；canary 将对应 manifest SHA 与 SOURCE_MAP SHA 带入运行收据。它不是对未读取外部 release、数据派生路径或所有 collector 子进程的完整证明。相关动态依赖仍明确为 CANNOT_CONFIRM，不把静态“没直接引用”夸大成已完成实盘依赖验收。

## 结果展示

新 App 从当前 `stageWorkbench.execution_evidence` 读取证据，没有新增 HTTP 请求或 producer。概览、市场列和证据组件共用同一读回状态；校验 date、stage、market、run、artifact、algorithm SHA、raw SHA 和实际结果行数。身份冲突只降级对应市场，缺自然执行证明不隐藏已经绑定的研究结果。

页面分别展示“已计算数量”“行情取得/请求/缺口”“研究来源限制”“回补/执行证据”。HK 沿用 R2 的真实资料研究合同：名单日期 20261008、采集时间 2026-10-09T15:38:41+08:00、stale universe、港股通成员资格 CANNOT_CONFIRM、CURRENT_DAY_RESEARCH_ONLY。证券资料不变成报价；分钟价格继续来自原 PyTDX 链，研究结果不冒充正式 D1/PIT。

经理入口、原日期/阶段事件、研究/任务/复盘导航、候选卡片与血缘结构保留。`useAppShell` 和当前 views 并未替换。本次测试对当前 App/组件做真实编译与 SSR，shell 状态/动作及其他 view 使用明确 fixture/stub；经理测试证明入口 wiring，不能声称经理整个业务或现役浏览器已验收。

## 交付内容

- [SOURCE_MAP.json](SOURCE_MAP.json)：21 个应用文件的当前 before/after SHA、实际根与反馈来源。组件以 `operation:add` 声明，before path/SHA 为 null。
- `after/stage`、`after/api`、`after/ui`：完整 after；它们是明确文件覆盖层，不能直接当作完整 app 启动。
- `patches/stage-before-to-after.patch`、`api-before-to-after.patch`、`ui-before-to-after.patch`：针对各自应用前像的最小补丁。当前 UI patch 不基于 R2 旧大 App。
- `tools/prepare_canary.py`、`canary_sources.py`、`run_current_research_canary.py`：可直接运行的本机准备/研究驱动。
- `tools/run_checks.py`、`verify_package.py`、`TEST_EXPECTATIONS.json`：包字节与完整测试门禁。
- [TOOLS_SOURCE_MAP.json](TOOLS_SOURCE_MAP.json)、[R2_DELTA.json](R2_DELTA.json)：R2 工具与交付包源码变化的前后 SHA；`patches/r2-package-to-r3.patch` 是包源码增量，不用于任何现役 app 根。
- [EVIDENCE.md](EVIDENCE.md)：最终真实测试、反例、独立复跑及未运行项。

`checks/api/before` 是继承的历史负例测试参考，不是本次 UI 的应用前像。当前 UI 的唯一应用前像在 `before/ui`，对应固定 Mac 附件 SHA；新增组件没有 before 文件。

本次所需前像已齐，[REQUESTED_PREIMAGES.json](REQUESTED_PREIMAGES.json) 的 required_now 为空。实际 source 在反馈后又变化时，prepare 会一次输出具体不匹配；不会将旧字节回盖 dirty canonical。

## 恢复范围与验收

Mac 已独立复跑的 R2 275 项完整测试仍是有效的旧基线证据；它不能替代 R3 的最终测试，也不能替代真实行情、当前 HTTP/UI 或发布验收。R3 的执行顺序是：新目录 prepare → 独立复跑 → 给定四文件的真实研究 canary → 同 run consumer/API/UI → 既有发布链与原页面验收。自动自然时段另行验证，手动回补保持 CURRENT_DAY_RESEARCH_REPLAY / RECOVERY。

本轮没有访问 Mac 的 695 行真实附件，没有启动真实 PyTDX、当前 API/浏览器、服务发布或自然时段任务；不能据离线通过宣布现役阶段选股恢复。交付范围是能直接落地执行的适配代码、完整 after、补丁与证据。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。原算法、权重、Top10、STRICT 默认、A 完整输入与 nullable 字段修复、HK 显式研究模式和 A/HK 隔离保持 R2；API/模块拆分不是前置条件。
