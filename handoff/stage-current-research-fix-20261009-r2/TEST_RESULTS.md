# R2 实际测试结果与证明范围

最终业务文件冻结在 `SOURCE_MAP.json` SHA256 `9ff05ba04a06794a753343780ee7fa890a4d74081a956dfd0b962d8de0ae2b5e`。本页记录新实现的实际执行结果；不使用旧 Linux 287 项或 Mac Writer 14 项代替本轮结果。

## 最终独立 canary 复跑

用交付中的 `stage_patch.py prepare`，从已有归档依赖组合建立全新的物理独立目录并应用完整 after。每个 suite 都启动独立 Python 进程。测试前、后分别核对 18 个 Stage 和 6 个 API/UI 交付文件，并对两个候选根中的全部代码文件记录字节 SHA。

| Suite | 本轮新增用例 | actual Stage + actual API | canonical Stage + actual API |
|---|---:|---:|---:|
| HK config / binding / runner | 29 | 29 passed | 29 passed |
| 原 collector → builder → selector → store | 36 | 36 passed | 36 passed |
| 源码身份与最终 owner writer | 8 | 8 passed | 8 passed |
| 输入 / 原存储 / reader / 既有 API route / Vue | 25 | 25 passed | 25 passed |
| 隔离落地及同 run 探针工具 | 17 | 17 passed | 17 passed |
| 合计 | **115 个不同用例** | **115 passed** | **115 passed** |

这两个 115 是相同用例在两套 Stage 变体上的复跑，不当作 230 个不同用例。没有失败、错误或跳过。

- actual 收据：[`evidence/frozen_canary_actual/TEST_RECEIPT.json`](evidence/frozen_canary_actual/TEST_RECEIPT.json)，2026-10-09 18:01:03–18:01:11（上海时间）；**1,576 个候选代码文件测试前后不变**。
- canonical 收据：[`evidence/frozen_canary_canonical/TEST_RECEIPT.json`](evidence/frozen_canary_canonical/TEST_RECEIPT.json)，2026-10-09 18:00:21–18:00:27；**1,603 个候选代码文件测试前后不变**。
- 两目录均包含各 suite 原 stdout/stderr、JUnit XML、候选代码前后清单、具体命令及完整 after SHA 核对。
- 汇总及各收据 SHA：[`TEST_SUMMARY.json`](TEST_SUMMARY.json)。运行环境 Python 3.14.8、pytest 9.1.1、FastAPI 0.143.0、Node 24.19.0。

另外实际复跑了 **28 个既有 reader 回归**和 **23 个既有 Vue 回归**，全部通过。它们单列在 `components/api_ui/evidence/legacy_reader_regression.log`、`legacy_reader.xml`、`legacy_vue_regression.log`，没有混入新增 115 项。

## 端到端实际覆盖

**A 字段链**使用原竞价读取函数或原 PyTDX HQ probe normalizer / aggregation，生成原 SourceResult，再调用原 builder、原 selector 和原 SelectionStore。相同代码验证有效昨收、真实 0 涨幅、缺昨收的 null＋原因；覆盖 09:25 和后续原 A 分钟阶段。216 个完整输入取得 205 / 206 条报价仍选 Top10，包含第 216 个代码进入选中，排除页面 200 行限制反向截断算法输入。

**可选研究 witness**用原 HourlyResearchStore 发布内部一致的 archive/receipt/manifest，但让其投影与 SHA 匹配的原 source 内容不一致，由原 validator 实际抛出 `RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH`。未 mock validator 或直接假造异常；无效补充项不参与评分，基础输入继续选股，原 witness 文件字节不变。

**HK collector 链**用明确合成的四文件及独立测试 pinset，通过真实研究 binding、原 ExHQ collector/probe 协议、原四路 selector、原 SelectionStore；695 输入取得 684 条合成分钟行情选 10。逐行对照直接调用原四路算法的 code/score/stage_score/rank 等值。证券资料中的伪价格不进入行情，未来/缺失分钟不变成合格报价；STRICT 默认分支的完整 envelope 与冻结前像相等。

**HK runner 到页面**用最终 runner/config/binding/slot、原 stores、最终 immutable writer、当前 consumer/reader、既有 FastAPI route 的原 AST 函数体及真实 Vue SFC 编译/SSR，在同一次测试内核对 selection run、raw/algorithm/source SHA、input binding、三件套、owner history、选中 10、行情 684/695、15:55 分钟、15:38 资料、手动研究标记。输入文件、证券和外部 provider 响应是合成 fixture，生产 SHA 常量未被替换发布。

**A 输入 reader**核对原 selection manifest 的 candidate date/run/current SHA/216 行标记与 owner receipt。成功状态精确为 `OWNER_DECLARED_INPUT_BOUND_TO_SELECTION`，不冒称 reader 重新读了 current 或验证 PIT；伪投影、错误日期/run/SHA/200 行、history 不足均不能升级绑定，已有计算结果继续展示。

**执行证明**覆盖缺 receipt、冲突 history、trio/SHA 不符、source identity 被改、手动外层试图标 NATURAL、已落定旧 run 保留原来源等情况。缺自然证明不抹去可验证的已计算结果。

## 明确使用的归档测试支持

以上完整链路是**候选源码的合成集成测试**，归档依赖不等于 Mac 当前完整 checkout。三处支持均未进入任何 `after/` 或业务补丁：

1. 归档 `raw_store.py` 传入 `allow_temporal_false_observation=False`，其归档 `receipt_identity.py` helper 未接收该关键字。整 runner 参考测试显式启用 `V4_RAW_SIGNATURE_SUPPORT=strict_false`：只接受严格 `False` 并调用原 validator，其他值拒绝；没有放宽时间检查。实际 Mac 两文件当前字节/SHA 未读，详见 `SOURCE_GAPS.md`。Mac 的交付复跑命令默认 **disabled**。
2. 归档拆分源遗漏若干通用 `_namespace.py`；测试加载相同且已固定 SHA 的原通用 helper，SHA 为 `45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1`。来源和清单在 `evidence/TEST_SUPPORT_INDEX.json`。
3. canonical 归档 consumer 的 import 缺少随包 reader。canonical 参考环境补充的是已固定原实际 API reader，SHA `e4c4ea94d892158383620beab1825014f21e926b57907354475f8c9ff382704b`；只为恢复归档 import。该支持没有作为 canonical API 变更交付，来源见 `evidence/EXTRA_TEST_SUPPORT.json`。

API 测试执行既有 route 原函数体与 FastAPI TestClient，没有启动完整 `create_app` 的所有无关路由、Mac API 进程或浏览器。Vue 使用真实 SFC 编译和 SSR，未宣称本机跑过完整生产 Vite build。真实 API 进程、完整前端构建及浏览器核对命令已写入 `MAC_APPLY.md`。

## 补丁、原算法与失败记录

六套 `restored_to_r2` / `r1_to_r2` 补丁全部执行 `git apply --check`、应用、逐字节 after 比对、`--reverse --check`、反向恢复、逐字节 before 比对。结果 **6/6 PASS**，见 [`evidence/FINAL_PATCH_VERIFICATION.json`](evidence/FINAL_PATCH_VERIFICATION.json)。42 个角色/文件记录的 before/R1/after 均匹配 SOURCE_MAP。

[`ALGORITHM_IDENTITY.json`](ALGORITHM_IDENTITY.json) 记录原公式、四路排序、合同、原 provider/normalizer 的字节对照；R1 的 A 输出字段投影修复保留。声明的原算法 SHA 为 `eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2`，没有新建评分权重或 Top10 规则。

开发过程的 RED 和装配失败日志保留，不视为最终通过：collectors before 32 failed / 4 passed，落地工具初版 2 passed / 6 failures / 4 errors；首次 portable API 缺少交付目录下的测试支持路径；旧共享 canonical 测试目录在 collector suite 期间出现四份非补丁 API 文件变化，source/owner suite 因混合 reader import 失败。未确认该外部文件变化的写入进程，因此不归因为业务修复；旧失败日志在 `evidence/final_*` 和 `evidence/release_canonical`。最终采用上述新物理 canary，并由完整前后 inventory 证明最终测试所用候选未变化。归档 API support 初次缺 app.py 的预检 MISMATCH 同样保留，补充已固定 41a 原 app.py 后才建立最终 canary。

## 尚未执行

没有读取用户 Mac 四份 695 行实采文件；真实 OpenD/PyTDX 网络采集为 0 次；没有修改或部署 Mac actual/canonical，没有现役完整 API/UI 或自然触发通过收据。15:50/15:55 两个历史失败仍受“临时改动窗口、加载版本不可确认”的原限制，不能由本轮测试倒推根因。

金融标志：`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。最终代码、可用落地工具、真实测试收据已经交付；实际运行结果须由原采集链在对应 Mac 环境产生。
