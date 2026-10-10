# V5 article identity：完整原 source 绑定修复候选

本包交付可评审的 V5 补丁、完整修改后文件、逐文件前后 SHA 与独立 Mac 验收命令。**产品测试全部 NOT_RUN；Mac 离线；真实同批 builder source 来源证明仍未闭合。** 不把静态审查、合成 fixture 或可重放性写成自然验收成功。

## 固定来源与范围

- 输入 commit：`cdd430e4dcd8d3e8c5949baff21a4831b4689444`。
- 必须保留候选：`7115f65267a1496d0ca8214cc14130f8c2b65d87`。两者 V5 tree 均为 `7479da8099077f40cb53534de505d6168972d292`，已从远端核对。
- 原要求：[START_HERE](../v5-article-identity-20261010/START_HERE.md)、[REPAIR_REQUIREMENTS](../v5-article-identity-20261010/REPAIR_REQUIREMENTS.md)。原交付目录原样保留。
- 新交付分支：`chat/v5-article-identity-repair-20261010-r1`；以交付时远端读回的 commit 为准。本包不声称本地必要文件快照是完整 Git checkout。
- 工程补丁包含 18 个 V5 路径：6 个已有文件修改、12 个新文件。另增本 handoff。原 owner、V4、采集 producer 和既有 frozen capsule 不修改。

## 核心变化

1. 新 `archive_builder_v1.run_build` 仅接受显式 `capture_root,capture_files,receipt,status`。原 collector/normalizer 从本批绑定的 status/summary 生成完整 source；V5 只约束 IO 和记录原时钟，保留原字段及序列化格式。SHA 取实际落盘并读回的 source bytes。
2. 原 incoming source、按 SHA 命名的完整 source witness、原 owner result、owner receipt 及全部 capture 文件进入同一精确文件清单。owner receipt 绑定 run/date/status、固定源码身份与时间链。
3. 原 importer 和每一次独立 v2 reader 都重放原 owner 的**完整 source 字节**，再调用原 `domains.research.build_research_archive` 比较**整个 v1 对象及规范 SHA**。缺 source、SHA/run/date 不符、只改身份键或同时伪造 source/archive 都有拒绝候选。v1 继续显式交回原 validator。
4. 原正文/URL/主体、微秒发布时间、显式 group、status 路径和 PIT 检查保留。完整 v2 再按规范字节比较；owner source 可用时间必须不晚于导入生成时间。
5. 新 source 的实际写入经原 `SafeRoot` 的 no-follow/no-replace 边界。原可预测临时文件 writer 不接触真实 Path；已有 source 或部分尝试不被恢复/覆盖。

## 阅读与使用

| 文件 | 用途 |
|---|---|
| [REPAIR_REPORT.md](REPAIR_REPORT.md) | 原 owner 接口、完整 source 合同、序列化与时钟语义、拒绝边界 |
| [STATIC_REVIEW.md](STATIC_REVIEW.md) | 独立静态审查发现、已修改项、验证限制 |
| [MAC_ACCEPTANCE.md](MAC_ACCEPTANCE.md) | 固定旧版本 RED、候选 51 项、相关回归、落地和回退步骤 |
| [runtime.patch](runtime.patch) | 18 个 V5 路径的精确补丁，基于固定输入 commit |
| [SOURCE_SHA256.json](SOURCE_SHA256.json) | 补丁路径的 before/after SHA-256、Git blob SHA 和字节数 |
| [STATIC_CHECKS.json](STATIC_CHECKS.json) | 实际静态/工件检查结果；不等同产品测试 |
| [PACKAGE_SHA256.json](PACKAGE_SHA256.json) | zip 内每一交付文件的字节数和 SHA，自身除外 |
| [DELIVERY_SHA256.json](DELIVERY_SHA256.json) | zip 的外部 SHA、CRC/逐项读回结果；不在 zip 内，避免自引用 |
| [v5-article-identity-repair-20261010-r1.zip](v5-article-identity-repair-20261010-r1.zip) | `after/` 完整修改后文件、补丁、说明和校验清单；不含真实材料 |

## 状态不可混用

| 阶段 | 本次结论 |
|---|---|
| 合同/接线与测试候选编写 | 已完成候选，包含 51 个测试方法 |
| 独立源码审查、AST、字节/SHA、补丁应用/逆向复原、zip 校验 | 实际结果见 STATIC_CHECKS；仅静态/工件验证 |
| 原三项漏洞 RED | NOT_RUN；须先控制成功，且两变异在 unexpected acceptance 处失败 |
| 51 项候选与相关产品回归 | NOT_RUN |
| 原 store → reader → 材料/主体 → manager → 同 run plan 动态闭环 | NOT_RUN |
| 真实同批 source、当前 US session、真实 HK 身份输入 | CANNOT_CONFIRM，缺本次真实证据 |
| 自然时段、集成、部署、API/UI | NOT_RUN；本包未执行 |

没有执行真实采集、部署、交易或系统配置变更。所有新增 receipt/result 的 `natural_verified`、`historical_pit_claimed`、`production_allowed`、`buy_gate_updated`、`orders_sent` 固定为 false。下一步由原独立 Mac 任务按验收文档执行；不需要上传真实 source 或原始材料到本仓库来证明接口。
