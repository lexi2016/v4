# 默认页面读回修复的合同

本轮续接 R1 固定交付 `008649895054cb24f1d1c3df37e215d307615db3`。完整普通经理父组件在真实 TestClient 路由传输中暴露了 R1 定向 `dynamic` 测试未覆盖的缺陷：同一计划 POST 成功，几秒后的默认 `auto` GET 因重新计算研究 cutoff 而改变 input identity，被判为 `STALE_INPUTS_CHANGED`。这里的来源字节没有发生变化。

## 最小生产变化

第一处生产修改位于 `v4/manager_research/workspace.py` 的 `get_workspace`：未进入历史分支时，`include_saved=True` 的 `auto` 和 `dynamic` 均可调用已有 `_saved_plan_context_for_bindings`，取得精确三日绑定的原封存研究上下文，然后继续原来源读取和 identity 核验。代码不跳过 source validator，不直接返回旧成功 DTO，不修改状态文案。

R1 前像 SHA256：`58a471c5ce7ece837c66948392ec2e6d73459343515225e19d694749c45ab1a4`。最终后像见 `source_manifest.json` 和独立复核报告。

第二处生产修改位于原 `catalystObservationPanel.ts` 的生成计划请求：显式日期对象中的 `selection_date` 简写引用了不存在的局部变量，导致错误在原加载层被处理而 POST 根本没有发出。改成 `selection_date: selectionDate`，传递原页面实际选择的日期。R1 前像 SHA256：`516b20050a9c4911415f8d5d9b94e5f58aa74c6b01711ec728edbe7582b351c6`。其余日期与请求控制逻辑不变。

这两个问题都存在于 R1 后像。本轮分别保存默认读取和生成按钮的真实 RED，再修复代码，验证原 POST→默认 GET→当前 DOM 的关联。生成动作使用独立测试 store，避免改变其他只读用例的计划指针。

## 保留的判断

| 场景 | 应有行为 |
| --- | --- |
| 同日普通页默认 `auto`，完整 selection/publication/plan 绑定相同 | 原封存 cutoff 重验同一保存 run；实际 `read_at` 单独记录。 |
| 晚间下一交易日目标，尚未进入历史分支 | 同样允许完整绑定的封存上下文读回；不能额外限制为仅今天。 |
| 过去目标日的默认 `auto` | 原历史分支先返回，仍要求合格当时计划；不把事后补算冒充当时已知。 |
| 过去目标日显式 `dynamic` | 原“现在回看”语义；可读取事后研究，不能提升历史资格。 |
| selection 或 publication 变化 | 完整绑定不匹配，不复用另一绑定的上下文。 |
| 原来源内容、引用或可验证身份确实变化 | 继续拒绝旧计划对应关系。 |
| owner 新评估 `include_saved=False` | 使用实际新评估 cutoff；晚到输入由后续合法 cycle 消费。 |

US 请求上下文限制、原 `read_contract`、历史原件、选股阈值和研究安全边界保持原代码。这个默认路径修复补充 R1 的范围；R1 的定向 `dynamic` 通过不能被重述为默认普通页已经通过。

## 测试证据的边界

实现和独立 API 测试都在隔离目录使用明确合成的研究/行情/审核输入，经原 owner、store 和路由实际生成 DTO。全父组件测试实际 mount 原 `ManagerSelectionView.vue`，经理研究区使用原请求、校验与投影代码；HTTP 传输桥接到真实 FastAPI TestClient。

这证明普通父组件中经理研究区域的本地集成行为。与本轮无关的页面请求明确返回不可用，原页面可能保留整体 ERROR；缺失的原 HTML 入口没有被新造。不能将这些测试写成全应用构建成功、现场 8873 页面验收或连续自然交易日成功。

完整原 `npm run typecheck` 另保留未提供的原 `issue8R2.ownerObservations.json` 和原旧 spec 的编译问题；该 JSON 引用真实保留 owner observations，不新造替身。经理生产入口的限定类型检查以原 `main.ts` 和完整 `ManagerSelectionView.vue` 为入口，遍历真实生产 import 闭包，其具体结果与全项目检查分开报告。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
