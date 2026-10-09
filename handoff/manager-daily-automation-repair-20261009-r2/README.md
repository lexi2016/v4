# 经理每日自动化接续修复 R2：默认计划读回与生成入口

本包继续原 [经理每日自动化问题包](https://github.com/lexi2016/v4/blob/09f82ac665e36a002e7f67f949b7e38f4e0598bf/handoff/manager-daily-automation-problem-20261008/README.md) 的目标：公告、US 映射、超跌沿原 owner 每日运行，按日期保存计划，并在普通经理页面显示股票、理由、数据日期与状态。

**R2 修复了完整普通父页面测试新发现的两个实际代码断点，并补齐原页面依赖与独立验证。业务总目标仍等待真实输入、受保护部署、真实 10/8 补算和连续自然日证据。** 本包继承 R1 整条每日调用、输入接续和计划保存的实现，没有将两个局部修正当作业务完成。

## 本次具体修复

| 断点 | 原失败 | 修复后行为 |
| --- | --- | --- |
| 普通页默认 `auto` 读取已保存计划 | POST 已保存，但几秒后的默认 GET 重新计算研究 cutoff，输入 identity 漂移，显示“来源已变化”。R1 的定向 dynamic 测试没有覆盖此入口。 | 同日或未来目标、完整三日绑定相同的 auto/dynamic 读取复用原封存研究上下文，再走原来源校验；另记真实 read_at。真实来源或日期变化继续拒绝。 |
| 显式选择日期后生成计划 | 原请求对象引用未定义的 `selection_date` 局部变量，按钮没有发出 POST。 | 传入现有 `selectionDate`，原 POST 带精确日期绑定；随后默认 auto GET 与当前 DOM 对上同一个 CURRENT/VERIFIED run。 |

两项都保留修复前真实 RED 日志，修复后经过原 owner、store、FastAPI 路由和完整 `ManagerSelectionView.vue` 中经理研究区域的测试。没有手写成功 DTO 或仅改状态文案。合同与保留条件详见 [修复决定](docs/REVIEW_CONTRACT_DECISIONS.md)。

## 继承的完整链路

R1 固定交付为 [008649895054cb24f1d1c3df37e215d307615db3](https://github.com/lexi2016/v4/blob/008649895054cb24f1d1c3df37e215d307615db3/handoff/manager-daily-automation-repair-20261008-r1/README.md)。其原 MORNING/PREOPEN/EVENING_NEXT_SESSION、同日有限 catch-up、独立 US 预算、单通道失败隔离、不可变 dated run/attempt、公告原成果消费、HK 同次发布与跨日读回，以及页面三路投影继续复用。

R2 的生产修改只涉及其中两个已有文件，不新建调度器、数据 producer 或页面。源码清单包含 **2 份生产增量、3 份实现测试/fixture**；另提供 **2 件恢复的原 web 依赖**，后者用于隔离测试装配，不是新生产补丁。[逐文件前后 SHA 与补丁](source_manifest.json)、[原依赖](required_dependencies.json)、[源码范围检查](evidence/package/source_scope_audit.json) 和 [补丁正反向检查](evidence/package/patch_verification.json) 可逐项复核。

## 测试和独立复核

详细命令、环境、原始日志、作者与独立结果在 [TESTING.md](TESTING.md)。实现测试覆盖默认 GET、完整日期绑定、真实来源变化、owner 新评估 cutoff、生成按钮 POST→GET、刷新当前 DOM、日期切换晚到响应、US INPUT_MISSING 保留公告，以及 auto 历史/显式 dynamic 的区别。

经理生产入口 `main.ts` 与完整 Vue 父组件的真实 import 闭包通过严格类型检查。全项目 typecheck、Vite build 和一个 HK 历史基线失败另列，不将限定通过改称全应用通过。原父组件中无关请求明确不可用，页面整体可能保持 ERROR；本包验证的是其中经理研究区域的完整本地请求与渲染链，不是已部署 8873 的实际页面验收。

[独立验收报告](independent_tests/final_review.json) 与 [分层状态](acceptance_status.json) 区分 IMPLEMENTED、TESTED、REVIEWED、INTEGRATED、DEPLOYED、API_VERIFIED、UI_VERIFIED、BEHAVIOR_VERIFIED、NATURAL_VERIFIED。API/页面中的本地合成测试通过与正式现场验收分开。

## 已查清的原输入接续

- **US 原采集任务已有。** 应复用原 V4 四槽任务与已修复 runner，核实际 data root 与经理 reader 同根；R1 已接 daily mapping 调用。不能根据另一份 V35 disabled 配置再启一套 producer。
- **公告还有外部执行合同缺口。** 原 capture/import/消费都已有；提供的源码未包含 06:30 heartbeat 实际执行 Reader 和独立 Reviewer 的调用合同。不能以一次固定导入或虚构审核结果替代。
- **HK 实际 owner 已有来源时间。** 不应修改旧 canonical 来代替它。原单位与全六日尺度仍未证明，超跌维持 unknown/CANNOT_CONFIRM；新 capture 成功不会自动补足这个合同。

固定原链接、SHA、版本区别与最小待核事实详见 [来源接续](docs/SOURCE_AND_INPUT_RECONCILIATION.md)。原 registry/研究 seed 没有重新打包上传，真实历史结果没有补造。

## 如何接续执行

1. 由 Issue #30 唯一集成 owner 核当前累计基线和模块 ownership，先保留并合入 R1，再核本包精确前像、应用 R2 两个有限增量。API 与 web 分属实际不同根，不能整树覆盖。
2. 按 [现场接续入口](docs/HOST_CONTINUATION.md) 核实际 US 任务、公告 heartbeat 合同和 HK updater 导入身份。现 #30 源码 policy 对 R1 四个必要路径的 ownership 尚需协调，本包没有改该 policy。
3. 沿原 owner 完成带真实执行时间的 10/8 事后补算，分别记录能消费的通道和真实缺口。过去日期默认 auto 仍要求当时历史；本次事后产物用显式 dynamic 核验，不改历史资格。
4. 在至少两个连续适用交易日观察原调度自然触发，逐日核 owner receipt→dated run→计划→API→普通页面重载，并验证第二日后第一日 exact 产物仍可读。

## 直接回答验收问题

- **真实 10/8 是否补选完成？** 本轮没有新的正式执行证据，保持未验收；合成测试不作回答依据。
- **以后是否每天自动，无需人工催跑？** 原每日接线已交付，R2 修正了普通页面默认消费路径；实际供源、受保护部署/启用与连续自然链仍须现场证据。
- **还有哪些具体阻断？** 原公告外部执行合同、超跌量纲/合法历史资格、当前 US/HK 任务与输入身份、共享集成，以及真实补算/连续自然验收。各项独立留缺口，不清空已验证通道，不将未评估计作零入选。

当前自然状态为 `NATURAL_SLOT_UNVERIFIED`。固定问题包本轮授权 Chat 交代码、测试与本机执行交接，不包含 Mac 补采、POST、启停、启用或部署；本包提供上述准备，不冒充正式运行回执。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
