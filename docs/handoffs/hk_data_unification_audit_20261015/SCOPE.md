# HK 数据统一审计范围

审计日期：2026-10-15  
仓库：`/Users/lexi/Desktop/学习/v4_app`  
审计基线：`55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`  
分支：`codex/system-consolidation-20260912`

## 冻结范围

| 项目 | 冻结内容 |
|---|---|
| GOAL | 只读核对旧研究池（标识 613）、隔夜池（标识 691）和现役日线池（标识 717）的来源、覆盖、代码差集、重叠冲突及消费者依赖；形成统一 V4 用户面板和唯一权威研究底板的可实施迁移方案；本任务不执行迁移。 |
| WRITER | `/root/audit_report_writer`：只写本文档目录内的审计报告和必要的可复算差集材料。 |
| REVIEWER | 独立身份 Reviewer；首轮两项 P2、第二轮剩余一项 P2 均已闭环；最终 `REVIEWED_PASS` receipt 存于 `REVIEW_RECEIPT.md`，身份和终态由主控登记。 |
| ALLOWED_PATHS | `/Users/lexi/Desktop/学习/v4_app/docs/handoffs/hk_data_unification_audit_20261015/`。仅可在此目录内创建或修改文件。 |
| FORBIDDEN_PATHS | 其余所有路径，包括源码、配置、运行时数据、指针、旧 V3 仓库、共享数据仓库和其他工作区文件。禁止改服务、计划任务、分支或 Git 历史；不安装依赖，不提交或推送。 |
| PASS_SIGNAL | 三套数据与当前消费者依赖有可复算、可追溯证据；报告给出完整代码差集/重叠冲突以及逐阶段 owner、文件、验收、回退和历史保全方案；所有迁移执行状态为 `NOT_RUN`；无业务数据/源码/运行配置改动；独立 Reviewer 对冻结范围给出 PASS。 |
| STOP_RULE | 输入证据缺路径、SHA、字段、代码/日期覆盖或可复算脚本时，标记 `CANNOT_CONFIRM` 并等待主控补充；不得猜测或代跑未授权的生产/迁移动作。若需要扩大允许路径或更改目标，交主控裁决。 |

## 当前材料边界

- 本次只写入本目录的报告、范围文件和可复算审计材料，不包含迁移实施。
- 已通过固定输入 SHA 的只读复算核对 A/B/C 三个 Parquet 的路径、大小、schema、行数、代码数、日期覆盖、集合差异和字段差异计数。`audit_manifest.json` 记录脚本、输入和输出 SHA。
- 运行身份、配置、代码 reader 和 receipt 路径由主控核对后纳入报告；它们不证明任何一个数据集在当前 API 请求中被实际消费。691 的生产和消费绑定仍为 `CANNOT_CONFIRM`。
- 迁移设计目标复用现存 `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/workspace/v3_shared_data/.runtime/data` 与现有 `assets/hk_0_2` 合同；旧 C 根和全部历史资源保留。目标根/配置切换仅为方案，未写入。
- 两个 `V4_MANAGER_*_ROOT` 配置指向完整 manager shared root。切换前必须盘点并核验其全部非 HK/A 资产和证券主表的直接/间接依赖、源/目标 SHA 及消费者读回；任一未知项都阻断 whole-root 切换。未通过时保持旧 manager root，只允许不接入 manager reader 的隔离 HK 版本，不扩大 A 股范围。
- 对外材料仅保留必要的代码/日期/计数/哈希元数据与审计结果；没有复制原始行情行、标签内容、凭证或认证内容。

## 交付物

- `SCOPE.md`：本冻结范围、权限边界和 PASS/STOP 条件。
- `REPORT.md`：证据登记、数据集和依赖清点、差集/冲突结果、迁移方案与回执。
- `recompute_hk_pool_audit.py`：SHA/大小门禁的确定性只读复算器；输出仅为元数据、计数、代码/日期键，不含原始市场行。
- `inventory.json`、`summary.json`、`audit_manifest.json`、五个 CSV：来源清点、复算摘要、输入/输出身份和逐代码覆盖/差异结果。
- `REVIEW_RECEIPT.md`：独立 Reviewer 历史 FAIL 记录、最终 PASS 最小 receipt 及核审/状态归档前后文档 SHA。

## 本轮回执

- 文档和审计材料：`REVIEWED_PASS`（独立 Reviewer 已通过；只读复算 `TESTED`，复用此前独立 `PASS_READ_ONLY_VERIFY` 8/8 回执，本次未重跑）。
- 三套源的当前 consumer 实际读取绑定：`CANNOT_CONFIRM`（缺当前 reader 对应的 manifest/run_id/SHA 消费 receipt）。
- 迁移：`NOT_RUN`。
- 独立 Reviewer：`REVIEWED_PASS`（首轮两项 P2、第二轮一项剩余 P2均已闭环；历史与最终 receipt 见 `REVIEW_RECEIPT.md`）。
