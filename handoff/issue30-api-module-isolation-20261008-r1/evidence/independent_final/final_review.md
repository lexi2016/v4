# Issue #30 独立最终源码审查

**结论：PASS；仅针对 SOURCE_CANDIDATE。** 本报告列出的八个产品文件通过本轮独立复审。七项已确认 Important（R1–R7）及已知经理目录归属补正 P1 均已关闭；该源码范围内没有未关闭的 Critical／Important。

独立最终回归为 **112 + 30 + 76 = 218 项通过**。原始失败探针保持原 bytes；修订前 RED、修订后 GREEN、命令、环境、日志和 JUnit 均保留。最终八文件补丁另经独立正向／反向 `git apply`、SHA、Git blob、source mode 与新增文件消失校验，通过。

本结论不批准 merge、部署、运行真实服务或自动切换。它也不证明完整当前 R2 的业务验收；具体边界见文末。

## 精确审查身份

输入 commit：`a0a0b88dc133d14ee5763569272c174bcd7cc445`。Reviewer 未修改候选产品源码，所有执行均写在自己的临时合成目录。以下路径以交付包 `after/` 为根，包内 bytes 已逐项与受审源码及冻结 SHA 对齐。

| 产品文件 | 最终 SHA-256 |
|---|---|
| `actual_cutover_reference/api_only_cutover_r2_ready.py` | `389be853923a72066472ad229129a9a41ef9e9785f1b729aa468ed3e58df19f5` |
| `apps/api/v35_api/app.py` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` |
| `apps/api/v35_api/preselection_router.py` | `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae` |
| `apps/api/v35_api/preselection_service.py` | `91eba3ad5d005161d876f9c2f1a69ff51db56f129267cde29394d4581d1a4c95` |
| `ops/api_release_integration.py` | `1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050` |
| `ops/build_release_candidate.py` | `81f4290a6f51e5958048d782c2d4b1eecfc42f892e387e6c1a22bb71912abef6` |
| `ops/create_api_module_delta.py` | `04e67a3ce948eecf9dac04083277bd919c7ec8880ec5814bbe57e7a5ba8d0072` |
| `ops/prepare_api_only_cutover.py` | `0fee40c13bdb76d8d4d7b5b0068eb8b6e7cade9187a5f3c3154b7d6238a1af4c` |

最终 ownership policy SHA：`c55f4f09269661e0db05fa566aa1be9a96b2aa681912223c38fb802c4127e1b6`。

最终实际切换脚本硬编码的 core SHA 精确等于包内 `ops/api_release_integration.py` 的 `1f4afc70…9dd050`。`SOURCE_MANIFEST.json` SHA 为 `baac33ad9e1f8b2d89f1817d00dd3c6e28c612a00c37586773dc50dadb6bada1`，八文件 `all_product_changes.patch` SHA 为 `6caf2d02546e17aabfeb06c721fa3ac8748aaf0e1f73aeb13ffd7c9de3dfc86e`。之后若源码或补丁变化，本结论不自动沿用。

## 七项问题的关闭证据

| ID | 初始具体失败 | 最终处理及独立复验 |
|---|---|---|
| R1 · Important | Git-tracked 的合法模块新增无论是否传 include-untracked 都无法构建。 | Git tracking 与 receipt membership 分开。Tracked 新增可直接交付；冗余 tracked 标志仍受 receipt 范围限制。实际 untracked 须显式批准，复制前全部 delta 路径须属于 tracked ∪ 已批准 untracked。原两参数探针在最终 core 上 PASS。 |
| R2 · Important | 安全 prepare 后把 candidate/config 换成 symlink，后续 scheduler staging 写到 candidate 外。 | API builder 自己的 staging 复用 prepare 的目录 fd 与 exclusive 写，晚到别名在外部写入前拒绝。原探针 PASS；历史 Stage helper bytes 未改。 |
| R3 · Important | 非 delta 目录 chmod 0755→0777 后候选验证仍通过。 | 新 directory proof 绑定 app 根、目录集合、空目录及 modes，并同时比较实际 base／candidate 与 manifest proof。新目录仅允许合法新增文件必要祖先，固定 0755；原模式探针与新增边界回归 PASS。 |
| R4 · Important | legacy SHA recovery 把 market=US 的 A 代码，或 HK symbol + A code，误当有效 A 行。 | 对 market 和每个非空代码别名分别检查同一 A 身份，并继续核对日期及 pool。坏池隔离，其他有效 A 池保留；原两场景 PASS，源文件 bytes 不变。 |
| R5 · Important | 自动 bootstrap 与恢复 rename 连续失败后，原像完整但公开 rollback 无法续恢复。 | 公开 rollback 支持完整 prepared contract 的 PREPARED／ABORTED／INCOMPLETE／已恢复状态。原始完整 contract 与 backup 一次写入并按 raw SHA 引用；每次尝试记录原 receipt 快照与显式当前 SHA 或字面量 ABSENT，始终持同一共享 lease。原失败探针、九种已知 pointer/runtime 组合、重复失败续做及未知状态拒绝均 PASS。 |
| R6 · Important | 新恢复读取器接受重复 JSON status，canonical checksum 仍合法并执行恢复。 | 全部 actual JSON 读取统一为保序且拒绝任意层级 duplicate keys／非标准常量的入口；用于字节切片的 raw decoder 先验证同一完整 raw。原公开入口探针、嵌套 receipt／plan／binding／readback 回归 PASS。 |
| R7 · Important | active 原字节但 mode 漂为 0777 时，恢复报告成功却未还原 backup 的 0644。 | 原字节 metadata 不同也通过同 lease、精确 SHA CAS 原子还原。Bootstrap 前与成功前核全 metadata；末尾漂移记录 INCOMPLETE。原 mode 探针、已加载原版时无服务操作的修复及 bootstrap 后漂移拒绝均 PASS。 |

R1–R5 的初审 `review.md/json` 保持 **CHANGES_REQUESTED** 原样；R6／R7 的 `revision_1f41_review.md/json`、两项 RED 与 1f41 冻结 source 也保留。本最终报告关闭问题，不改写历史失败事实。

**P1 · 已知归属补正已验证。** Exact R2 app 的 manager loader 与固定 manager router 的 imports 明确引用 `v4/manager_research/`。最终 core 只给 manager 增加该前缀，没有开放整个 `v4/`，也未改经理业务服务。与已审 f79 core 的唯一差异见 `final_manager_policy.diff`；manager 合法正例与 preselection 跨 owner 拒绝例均包含于 112 项通过。

## 关键实现审查结论

### 模块边界与非 delta 保留

构建来源是当前 active app 加声明并绑定前／后 SHA、mode 的模块 delta。未知路径、未知模块、越过明确 shared 范围及不符合 receipt 的变化拒绝。Git 状态只决定来源文件是否需要额外 untracked 批准，不再错误地决定合法新增能否存在。

文件非 delta 库存与目录 proof 分别核对。App 根、只读目录、空目录、目录集合及 mode 被保留；新目录的范围与 mode 明确。Builder／prepare 的候选写入使用目录 fd 约束，并在关键阶段重新核身份。测试包括晚到 plist／manifest／root 变化与 symlink 别名拒绝。

本次 shared `app.py` 的具体内部变化另有静态保留证明。Receipt 的哈希和路径规则提供完整性证据，不能代替对未来 shared 代码差异的实际审查，也不是用户授权票据。

### 实际切换的 pin、共享锁与恢复

实际脚本从唯一硬编码路径读取 guard，检查 SHA 后执行同一份 raw bytes；没有通过第二次 import loader 打开未核字节。Guard 与实际脚本的 imports 均为标准库。历史 builder 只用于核 provenance，受审实际入口不执行它的未 pin imports。绑定到当前 lease 的 verified module 一直用于该次切换和恢复。

末尾验证、active plist 的 CAS／原子替换与服务动作在同一 persistent shared flock lease 内。已知／缺失指针使用精确当前状态约束；缺失只能显式表示为 `ABSENT`，不能成为覆盖任意文件的通配符。未知 pointer 或加载身份拒绝。失败 receipt 保留 before／after／base／integration／backup 完整 contract，多次恢复各写自己的 receipt，并继续引用同一原像。

最终恢复成功不仅要求原版 bytes 与已知原版 runtime，还要求原 metadata 相同。测试验证了 Linux mode 与 metadata 合同；Mac 特定行为的判断边界仍保留。Prepared receipt 的一次写入、self checksum 与 raw SHA 链条属于事务完整性，未声称是密码学签名授权机制。

## 独立测试与证据

| 最终运行 | 结果 | 证据 |
|---|---:|---|
| Release 全套，最终 core 1f4／builder 81f | 112 / 112 PASS | `final_release112.log`、`.xml`、`_run.json` |
| Preselection 最终 app／router／service 91e | 30 / 30 PASS | `final_preselection.log`、`.xml`、`_run.json` |
| Actual 最终 389be，最终 core 1f4 | 76 / 76 PASS | `final_actual76.log`、`.xml`、`_run.json` |
| 原始 release 探针单独复跑 | 4 / 4 PASS | `final_original_release112_probes.*` |
| 原始 preselection 探针单独复跑 | 2 / 2 PASS | `final_original_preselection_probes.*` |
| 原 R5／R6／R7 三探针 | 3 / 3 PASS | 保持原 bytes，已计入 76；不另行累加。 |

**218** 是三个最终套件的执行数；85／26／21 的初始回归、110／63 的中间修订回归和探针重复运行不加到这个数里。每个主运行均有完整命令、cwd、环境、Python／平台、退出码及 JUnit。运行前后 source／test SHA 的核定见对应 `_run.json`；预选五个 test/harness 和 21 个历史支持文件的相同身份见 `final_preselection_identity.json`。

使用 Python 3.14.7，禁用第三方 pytest 自动插件和 bytecode 写入。实际切换所有 launchctl／HTTP 操作均被显式模拟或禁止，fixture 只使用临时目录。预选套件仅出现已有 Starlette TestClient deprecation warning。没有执行真实 API 业务、Mac 服务或真实用户路径。

## 共享 app 与经理保留证明

独立脚本 `verify_shared_app_preservation.py` 只解析 exact R2 before SHA `90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7` 与最终 after SHA `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`。

只移除明确允许的预选 imports、迁移 helper 和 inline route／新 router registration 后，剩余整体 AST 相同。`create_app` 内其余 **54 个 statements 的 AST 和逐项源码文本都相同**。新 router registration 的参数也与预期逐项匹配。

经理完整 section 到文件末尾逐字节相同，SHA `13c00931d4a3b33371e292cb732a8cb292f2f1723d2ac9704bd2ad787a2dac0b`。经理 state／service 初始化 suffix SHA `23c0ffdad6d54d7b508cd48b3846f15a86b0a770c88c66c247e3426b2a410d55`；作者声明的 wiring suffix SHA `022417f603c182a870e8e64f3f7efcbad649c6a2b3a2d78825008c84d6b5b0db` 也独立匹配。完整逐项结果、脚本命令与日志保存在 `final_shared_app_preservation.*`。字节保留不代表已经执行经理业务回归。

## 最终补丁包往返

独立 `verify_final_package_roundtrip.py` 使用固定受审 before／after SHA，在新临时 Git 目录运行正向 `git apply --check` 与 apply，逐项比较八个后像 bytes、mode 和 Git blob；再反向 check／apply，比较五个原文件并确认三个新增文件消失。没有额外产品路径。声明 source mode 均为 0644，脚本固定自己的 umask 0022 并在结束恢复。

结果、逐文件记录、Git 命令、脚本环境与输出见 `final_package_roundtrip.json`、`.log`、`_run.json`、`_script.log`。Script 可以对交付包独立重跑；它不 import 产品代码或运行服务。包内八个 after 文件的身份与受审源码精确一致，actual 的 core pin 和 policy SHA 同样匹配。

## DeclinedToJudge

以下内容未被本次源码通过结论覆盖：

- 完整当前 R2 的 1016 项应用闭包；只取得 exact R2 app 单文件和 bounded 历史支持，没有重建完整现行 R2。
- 完整 `create_app` 启动、真实 A=178／HK=100 canary、经理公告／工作台／日期隔离业务、真实 API/UI reload 以及自然时间执行，均 **NOT_RUN**。
- Mac launchd 运行，以及 Mac 特定 flags/xattrs 行为；本次运行是 Linux 合成 fixture。
- 三个新增文件在当前 Mac 是否确实不存在、当前部署 mode 是否一致。补丁往返证明的是声明的 source baseline 与 Git source mode。
- 未列入候选的所有旧发布入口是否已迁移；共享 flock 只协调遵守该协议的发布者。任意 Python 代码猴补丁或绕过锁也不属于这里的 OS 隔离保证。
- 可直接用于新 release 的运行时 pins 或 R3 适配器。Actual 除 core pin 外仍保留历史 R2 task pins；独立 AST 对比也已核定这一点。需要对应新 release 的计划和身份才能另行实际切换。
- Merge、部署、交易／BUY、producer／数据修复及 Issue #28 的其他 PIT／数据问题，本次均未执行或批准。

精确必要证据清单和文件 SHA 见 `FINAL_EVIDENCE_INDEX.json`，复制列表见 `FINAL_EVIDENCE_FILES.txt`。完整结构化 finding、关闭位置、历史与最终运行索引见 `final_review.json`。
