# 经理三通道集成候选：现役校验恢复 R1

**代码返修已完成。原 76 项 Issue8 R2 校验/展示测试恢复全部通过，原 25 项三通道及每日流程测试全部通过。生产补丁只涉及一个文件，+119 / -0。** 本包用于新候选集成；Mac 新包验收、发布切换、实际 API/UI 和自然时段验收尚未执行。

固定输入为 [63e75b7af02866c2d19a484b9561416cb13efd84 的 FIX_REQUEST](https://github.com/lexi2016/v4/blob/63e75b7af02866c2d19a484b9561416cb13efd84/handoff/manager-three-channel-deploy-20261009/chat_validator_regression/FIX_REQUEST.md)。返修包清单内 11 个文件的大小和 SHA256 全部核对一致。

## 改了什么

目标：`apps/web/src/api/managerWorkspace.ts`。

| 恢复内容 | 目的 |
| --- | --- |
| 四个接口类型及 `ResearchAttention` 两个可选字段 | 恢复独立观察、输入诊断的类型合同；历史缺字段仍可读 |
| 原 `observationTime` | 保持显式时区、合法日期/时分秒和原 PIT 语义；不以其他时间字段或较宽松 helper 替代 |
| `validateIndependentObservations` | 校验观察容器/计数、只读安全标志、主体/文档、引用、资格身份及时间窗口 |
| `validateResearchInputDiagnostics` | 校验各来源诊断、输入/准入/拒绝数量、完整性和正式资格范围 |
| `validateResearchDisplayConsistency` | 约束日历、资格证据与展示字段的一致性 |
| 三个调用点 | 让上述检查在成功返回 workspace 之前实际执行 |

恢复的函数和接口均直接取自冻结现役源码。候选原有行完整保留，包含三通道日期绑定、未知筛选数量、运行和计划回读、长期关系发布时间分支。生产变更未涉及 API 进程、页面发布入口或选股算法。

## 精确身份

| 文件角色 | SHA256 |
| --- | --- |
| 现役参考 `active-reference/` | `6bd208174c650beb1b089058de458643beb601a97455ff472330984e88dd6d7d` |
| 失败集成候选 `before/`，本补丁唯一前像 | `35a879624032cfffb1c3e4afba3c4ae6298df7d5dffb5db90d9ad42142f496ee` |
| 修复候选 `after/`，119,467 字节 | `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f` |

`active-reference/` 用于对照；本增量补丁应应用到 `before/` 身份的集成候选。

## 验证结果

| 范围 | 修复前 | 修复后 |
| --- | --- | --- |
| 原 Issue8 R2，76 项 | 现役 76 通过；候选 31 通过、45 失败 | 76 通过 |
| 原三通道及每日流程，25 项 | 候选 25 通过 | 25 通过 |
| 新增共存测试，8 项，单独计数 | 候选 4 通过、4 失败 | 8 通过 |
| 严格 TypeScript 检查 | 本轮未将旧类型缺口单独计数 | 通过，退出码 0 |

45 个候选新增失败的测试身份与 Mac 冻结反馈逐一相同。原三个 spec 和两份 Issue8 fixture 字节未改变。新增 8 项将旧观察/来源诊断与不同计划日、选股日、公告日、未知数量筛选放入同一 payload，验证合法组合可读，以及安全标志、US 完整性、日历 SHA、日期错绑、未知数量伪零和非法时间仍被拒绝；所有 payload 保持不变。

实际环境：Linux x86_64，Node 24.19.0，Vitest 4.1.10，TypeScript 5.9.3，Vite 7.3.6，jsdom 28.1.0；Python 3.12.14、pandas 2.2.3、pyarrow 24.0.0。Python 只生成临时合成 DTO；与 Mac Python 3.14.6 环境的差异明确保留。

交付工具另有 3 项防误用检查通过，覆盖前像失败时停止应用/回滚及临时路径边界，详见 `review/HANDOFF_FIX_CLOSEOUT.md`；不与109项前端测试累加。

`evidence/validation_summary.json` 保存结果和失败身份；`evidence/logs/` 保留实际测试日志；`review/` 保存独立审查。原 Mac 229 项矩阵另有 14 项既存失败，本轮没有重跑完整矩阵，也没有宣称这些问题已关闭。

## 测试支撑的两次修正

首次复跑沿用旧候选展示副本，产生两边共有的 11 项 DOM 失败，另有候选独有的同一 45 项失败。之后仅在隔离测试副本中使用冻结仓库的 API 展示源码 `handoff/v4-running-source-20261005/api/apps/web/src/manager-selection/researchAttention.ts`，SHA256 `9b9ea7aef33e504da7d99f2b16b1e632448a63dfe0971ae275730e6311c5ce3a`，得到精确的 76/76 与 31/76 对照。该文件在 `test_support/` 供复现参考，不在生产补丁或测试覆盖安装目录中。

25 项首次运行的另外 2 项失败发生于 Python 缺少 Parquet 引擎、尚未生成 DTO。按仓库锁定版本在任务独立环境补充 pyarrow 24.0.0 后，原测试全部通过。这两类初次失败均保留日志和说明，没有删除用例、替换断言、手造成功 DTO 或合并分拆结果凑数。新增 8 项的错误断言收紧为完整 Error 比较后，最终字节重新执行修复前后测试；早期版本日志保留但不计入最终验收。

## 使用本包

1. 阅读 [MAC_APPLY_AND_ROLLBACK.md](MAC_APPLY_AND_ROLLBACK.md)，在新候选副本核对前像。
2. 用 [runtime.patch](runtime.patch) 应用单文件增量，核对完整 [after 源码](after/apps/web/src/api/managerWorkspace.ts)。
3. 在新副本安装 `tests/` 内的测试资产，执行原 76、原 25 和新增 8；严格类型检查并按既有发布流程重新构建。
4. 重建该源码对应的前端产物及发布清单，再验共享 API/页面入口及经理、阶段两个使用路径。旧 dist、旧源码 SHA 和旧发布回执不适用于新源码。

离线验包及正反补丁重放：

```sh
python3 tools/verify_delivery.py
```

此命令在临时目录验证补丁及回滚，检查交付清单，不改传入源码。指定 `--source-root` 和 `--expect before|after` 时额外只读核对目标身份。实际生产部署继续由 Mac 执行、独立验收并记录新回执。
