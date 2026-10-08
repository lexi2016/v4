# Issue #30 独立最终复审检查点

**状态：CHANGES_REQUESTED（仅针对 SOURCE_CANDIDATE）。** R1–R5 的原始失败及主控补正 P1 已独立复验关闭。actual 1f41 的原 21 + 新 41 + 原 R5 探针合计 63 / 63 PASS；新增独立验收探针又确认 R6、R7 两项 Important，仍需修正。最终补丁包尚待新 actual 冻结后核验。

## 精确复审身份

输入 commit：`a0a0b88dc133d14ee5763569272c174bcd7cc445`。Reviewer 未修改候选源码。初审 `review.md`、`review.json` 和三个原始探针均已逐字节确认保留。

| 文件 | SHA-256 |
|---|---|
| `candidate/ops/api_release_integration.py` | `1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050` |
| `candidate/ops/build_release_candidate.py` | `81f4290a6f51e5958048d782c2d4b1eecfc42f892e387e6c1a22bb71912abef6` |
| `candidate/ops/prepare_api_only_cutover.py` | `0fee40c13bdb76d8d4d7b5b0068eb8b6e7cade9187a5f3c3154b7d6238a1af4c` |
| `candidate/ops/create_api_module_delta.py` | `04e67a3ce948eecf9dac04083277bd919c7ec8880ec5814bbe57e7a5ba8d0072` |
| `work/preselection_revision/after/apps/api/v35_api/app.py` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` |
| `work/preselection_revision/after/apps/api/v35_api/preselection_router.py` | `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae` |
| `work/preselection_revision/after/apps/api/v35_api/preselection_service.py` | `91eba3ad5d005161d876f9c2f1a69ff51db56f129267cde29394d4581d1a4c95` |

actual 已复审至 SHA `1f41fe707ee7a24c0e2ba2143431d6c7c628ef9631b7b05e06f09fed415ff4c9`；该版本通过 R5 原问题恢复探针，但暴露下述 R6／R7。其冻结副本保留于 `frozen_final/`，后续修订不得覆盖该副本。

## 初审问题闭合

| ID | 等级 | 当前结论 | 独立证据与原因 |
|---|---|---|---|
| R1 | Important | CLOSED_VERIFIED | Git-tracked 的合法新增现在无需 untracked 标志；冗余 tracked 标志仍必须属于 receipt。实际 untracked 要显式批准，复制前所有 delta 来源必须属于 tracked ∪ 已批准 untracked。原两参数失败探针在最终 core 上均 PASS。 |
| R2 | Important | CLOSED_VERIFIED | API 自己的 scheduler staging 使用 prepare 的目录 fd 与 exclusive 写；原 late-config-symlink 探针现在在写出界前拒绝。历史 Stage helper 未改。 |
| R3 | Important | CLOSED_VERIFIED | 新目录 proof 绑定 app 根、目录集合、空目录和 mode；非 delta 目录保持原 mode。新目录只允许合法新增 delta 必要祖先且为 0755。验证同时比较实际目录与记录；旧 mode 篡改探针现 PASS，18 条目录／source 修订回归包含于最终套件。 |
| R4 | Important | CLOSED_VERIFIED | legacy SHA recovery 逐项核对 market 与所有非空代码别名，并保留日期／pool 约束。矛盾 A/HK 身份不能被另一个合法 code 掩盖；坏池隔离而另一个有效 A 池仍保留。原两场景均 PASS，源文件未被修写。 |
| R5 | Important | CLOSED_VERIFIED | 公开 rollback 已能从完整 prepared contract 续恢复；完整原像、plan/base 绑定、显式 current SHA／ABSENT、同一共享 lease、未知状态拒绝和多次失败保留均有测试。原始失败探针 PASS。完整恢复验收仍受 R6／R7 限制。 |

主控补正 **P1 已复验**：精确 R2 app 的 manager loader 和固定 manager router 明确使用 `v4/manager_research/`。新增该 manager 前缀是既有归属补正；与已审 f79 core 的唯一差异已保存为 `final_manager_policy.diff`。manager 正例和 preselection 跨 owner 拒绝例均通过，没有扩为整个 `v4/`。

## 新增实际恢复验收问题

**R6 — Important：重复字段 receipt 被接受。** `_signed_receipt` 使用普通 `json.loads`。合法 receipt 前插一个 `status=FOREIGN_UNREVIEWED_STATUS`，后面的合法 `status` 覆盖它，原 canonical checksum 仍有效。公开 rollback 未在任何动作前拒绝这种歧义 JSON。独立原样探针 `test_actual_duplicate_receipt_probe.py` 实际 **1 FAIL**，日志／JUnit／环境记录为 `actual_duplicate_receipt_probe.*`。需要所有层级 object 都拒绝 duplicate keys，并统一交易 JSON 读入语义。

**R7 — Important：原字节指针未恢复原 metadata 却报告成功。** 在已有原版 active plist 字节、完整 0644 backup 和未加载运行状态下，将 active mode 改为 0777。恢复函数因 SHA 已等于 before 而跳过写入，随后返回 `ROLLED_BACK_TO_PREIMAGE`，权限仍为 0777。独立探针 `test_actual_preimage_metadata_probe.py` 实际 **1 FAIL**；其余五个 metadata 字段相同，仅 mode 不同，证据为 `actual_preimage_metadata_probe.*`。需要该分支恢复或拒绝元数据差异，并在成功前核定完整原像 metadata。

两个新增探针与 1f41 冻结 source 都已保留，未改初审五个 ID 或原始 bytes。它们测试的是本轮已有严格解析／原像合同，不是扩展业务 suite。

## 独立执行结果

| 运行 | 结果 | 说明 |
|---|---:|---|
| 最终 release 全套 | 112 / 112 PASS | `final_release112.log/xml`；运行前后全部 ops 与 tests 的 SHA 相同。 |
| 最终 preselection 全套 | 30 / 30 PASS | `final_preselection.log/xml`；实际 router/service 加固定历史支持。 |
| 原始 release 探针另行复跑 | 4 / 4 PASS | `final_original_release112_probes.log/xml`；原 bytes 未改，最终 1f4 core。 |
| 原始 preselection 探针另行复跑 | 2 / 2 PASS | `final_original_preselection_probes.log/xml`；日志核定导入的 revision service 91e 与 router。 |
| 实际切换恢复回归 | 63 / 63 PASS | `final_actual63.log/xml`；旧 21 与新增 41，以及原 R5 探针。 |
| R6 新增探针 | 1 FAIL | `actual_duplicate_receipt_probe.log/xml`；等待修正。 |
| R7 新增探针 | 1 FAIL | `actual_preimage_metadata_probe.log/xml`；等待修正。 |
| 共享 app 静态独立证明 | PASS | `final_shared_app_preservation.json` 与独立脚本；未 import 或执行完整 app。 |

原始探针是已有断言的独立复跑，不累加成新的唯一用例数量。每个执行均有 `*_run.json` 保留完整命令、cwd、环境、Python／平台与退出码，JUnit 和日志一并保存。Python 3.14.7，禁用自动第三方 pytest 插件；所有 fixture 仅写临时合成目录，无真实服务或 Mac 路径操作。预选测试仅出现已有 Starlette TestClient deprecation warning。

## 共享 app 与经理保留证明

独立脚本仅解析 exact R2 before SHA `90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7` 与最终 after SHA `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`。

删除明确允许的预选 imports、三个迁移 helper 与 inline route／新 router registration 后，剩余整体 AST 相同。`create_app` 内其余 **54 个 statements 的 AST 和逐项源码文本都相同**，新 registration 参数与预期完全一致。

经理完整 section 到文件末尾逐字节相同，SHA `13c00931d4a3b33371e292cb732a8cb292f2f1723d2ac9704bd2ad787a2dac0b`。经理 state／service 初始化更大 suffix SHA `23c0ffdad6d54d7b508cd48b3846f15a86b0a770c88c66c247e3426b2a410d55`，作者声明的 wiring suffix SHA `022417f603c182a870e8e64f3f7efcbad649c6a2b3a2d78825008c84d6b5b0db` 也独立匹配。字节保留不代表已执行经理业务验收。

## 判断边界

完整当前 R2 的 1016 项应用闭包、完整 `create_app` 启动、真实 A=178／HK=100 canary、经理公告／工作台／日期隔离业务、真实 API/UI reload 和自然时间执行均 **NOT_RUN**。仅有精确 R2 app 文件与 bounded 历史支持；新旧 21 个支持文件逐字节相同，它们不是完整现行 R2。

共享 persistent flock 及 exact-byte pinning 只支持合作发布者与受审入口；没有证明所有外部旧入口已迁移，也不是任意 Python 代码对抗的 OS 隔离。实际切换脚本故意保留 R2 运行时 pins，不是可直接发布新 release 的适配器。此审查不操作 launchd，不判定 Mac 特定 flags/xattrs 行为，不授权任何 merge、部署、交易或数据修复。

初审的 5 类 Important、7 次失败执行及初审所有证据保留在 `review.md/json` 和原始 RED 日志。完整结构化结论、精确 SHA、每项闭合位置与证据索引见 `final_review.json`。
