# Issue #36｜R7 V3 同身份原始 TERMINAL 字段合同返修

**基线**：\`lexi2016/v4@d05afe94110c6fe6d171a99b7e4ccb1e15248c9f\`（含 2026-10-11 Mac 真实失败）。**状态**：\`SOURCE_FIXED / V3_CONTROLS_STATIC_BOUND / MAC_REAL_PREFLIGHT_NOT_RUN / REAL_RUN_NOT_RUN\`。

## 1. 真正的根因，不能再误判为原 R7 action ID 问题

Mac 本地独立 target-free 预检对旧 V2 PASS，随后唯一真实同身份恢复在 \`input_admission\` 拒绝：
\`FIRST_PASS_FIXED_INPUT_ADMISSION_ACTION_NOT_PRESENT_IN_OFFICIAL_REGISTRY\`。该错误不是实际登记行丢失。当前 \`f5_breadth1_inputs.py:400\` 的原义是：

\`\`\`python
or resume_terminal.get("registry_event_id") != resume_failure.get("terminal_event_id")
\`\`\`

原 V2 \`AUTH.preserved_original_failure\` 只有 \`terminal_event_sha256\`，**没有** \`terminal_event_id\`，因此真实官方 ID 与 \`None\` 比较导致拒绝。官方固定事件确认为：

\`\`\`text
original_execution_id:
F5_PLUS64_BREADTH1_R3_FROZEN_INPUT_20261011_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_20261011_ONE_SHOT

original RUN_STARTED SHA:
c5d660d80d5c0ddfefde59e25736b9c696599ed8802d87a3fc82906278d770da

original TERMINAL ID:
F5_PLUS64_BREADTH1_R3_FROZEN_INPUT_20261011_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_20261011_ONE_SHOT_TERMINAL

original TERMINAL SHA:
3be54f120860676d09b2b7c9f3130e97f9fac3919de3dddf68a7426c34609907
\`\`\`

原始 R7 START/TERMINAL/debit=1/0 没有修改、删改、退款或重新 claim。已存在的 \`r7_recovery_05/resume_invocation_02\` 和其新失败 TERMINAL 原字节 SHA \`254e63c23c0b9b11b2685725796b4ebcfcafc234fd1eb5b2d086f04e655e76bd\` 也不覆盖。该失败 occurred before target reads；\`input_read_observation=null\` 保留未知，pretarget checkpoint 的 \`target_input_reads=0\` 只在其适用边界使用。fit/predict/model-load/truth 为 0，效果 \`NOT_TESTED\`。

## 2. 修复：字段补正且保留严格校验

新增 \`controls/resume_v3/R7_RECOVERY_06_RESUME_AUTHORIZATION_V3.json\`：

- \`preserved_original_failure.terminal_event_id\` 精确固定为上述原官方事件 ID；
- 同时固定原 TERMINAL SHA、START SHA、old R7 grant/execution/action key 及 debit=1；
- \`previous_engineering_attempt\` SHA 锁住 \`resume_invocation_02\` 的 NO_FIT 失败；
- 只使用单独的第三次**物理**尝试目录 \`r7_recovery_06/resume_invocation_03\`；**不重新申请原 R7 逻辑准入**；
- V3 read release 与原 R7 read release **仅四处**身份差异：contract SHA、pending binding SHA、\`files.input_binding.path\`、\`files.input_binding.sha256\`。所有冻结目标 data descriptors、读取上限、科学参数、原标签及评价门均保持不变；
- 当前 read plan 引用活动 pending binding；probe02 旧 SHA \`129c83...\` 保留为历史，不冒充当前活动 SHA。

原 \`f5_breadth1_inputs.py:400\` 的真实 ID 比较**没有删除**；\`f5_breadth1_budget.py\` 的独立 TERMINAL ID 与 SHA 检查也仍保留。对三个源码的改动只涉及 versioned controls、物理续接目录、元数据 ID 与索引 3；冻结核心、特征、worker、evaluator 完全不动。

## 3. 交付物和 SHA

- [完整 after/ 源码三个文件](after/workspace/f5_breadth1_r3_frozen_input_20261011/src/)
- [三个文件统一补丁](patches/ISSUE36_R7_V3_SOURCE_MINIMAL.diff)，原 R7 源码 before SHA 前置
- [五份新 V3 controls](controls/resume_v3/)，**新增、不可覆盖旧控制**
- [V3 launcher](launcher/r7_resume_v3_launcher.py)，SHA256 \`6879dce51eee81adf194a021b9d50a8c23dc399a164be7e758b6d685003d6ba0\`
- [只读 guarded 安装工具](tools/install_v3_candidate.py)，SHA256 \`8ccbc1c6e03cb2fa540091a3352382c21ad58c149ac22f58c6fa2490e5c1be08\`
- [SHA 重绑定清单](SHA_REBIND_AND_SCOPE.json)
- [GitHub 原官方事件 13 项+四负例静态核对](evidence/STATIC_V3_OFFICIAL_EVENT_CHECK.json)

三源码前后 SHA256：

| 当前 canonical 文件 | before | after |
|---|---|---|
| \`f5_breadth1_budget.py\` | \`0746398c572ec070f96cfbb27826b3ae6ab5ae7a7839792dd01b0324ebf393cb\` | \`fca2feceeb829b16a80dd54b87c224e2cb2a50a4a1ef4e1546734e53e454746d\` |
| \`f5_breadth1_inputs.py\` | \`86d7eb720469da17cebf2d05f06e5572dd0365b3e5d96efa6b1deeded5818383\` | \`215a528d89a718cda2f3f8c7a9e1275b637425dc23e32da11233cb30b819a742\` |
| \`run_f5_breadth1.py\` | \`49b7d01ab6dff04ed5130a55466826804589569b2ccd13d698a7dfe8df61b673\` | \`5e4b7a782d6b76b606ac312767203c1f56f92dd0ef4d5cfa3218666b8acbef25\` |

V3 五份控制 SHA 见 \`SHA_REBIND_AND_SCOPE.json\`；GitHub branch 固定字节读回是本次交付身份。

## 4. Work／Mac 实施（严格顺序，不运行旧 V2 命令）

Work 从独立分支下载本目录全部文件到 Mac 临时位置；下面 \`PKG\` 指本目录根（含 \`after/ controls/ launcher/ tools/\`）。**先停止其他本地研究执行，并让独立 Reviewer 验证完整目录身份。**

\`\`\`bash
PKG="/实际下载位置/research/f5-breadth1-r7/issue36-fix-r3"
PY="/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/.venv_locked/bin/python3.13"
"$PY" -I -B "$PKG/tools/install_v3_candidate.py" --bundle-root "$PKG" --check
\`\`\`

要求：\`READY_FOR_INSTALL_FILES_ONLY\`；先验三原 SHA、三 after SHA、五新 controls SHA、prev02 receipt SHA、且第三次输出目录和新 final binding 均不存在。文件不符 **STOP**，不靠更改 ID、备份删除、SHA 覆盖继续。

审核通过后**安装一次**，只改三 canonical 业务源码、另新建五份 V3 controls 与一个薄入口，并保留不可变 backups：

\`\`\`bash
"$PY" -I -B "$PKG/tools/install_v3_candidate.py" --bundle-root "$PKG" --apply
\`\`\`

期望：\`INSTALLED_FILES_ONLY_NOT_TESTED\`。并非真正执行了 admission/fit。

之后只运行**一个 target-free Mac 真实接口预检**（读取真实官方 registry、guard、builder、validator、controls、原事件及失败字节，不触发 target/fit/predict/truth）：

\`\`\`bash
ENTRY="/Users/lexi/Desktop/学习/因子工厂/handoffs/issue36-r7-v3/r7_resume_v3_launcher.py"
"$PY" -I -B "$ENTRY" --target-free-preflight
\`\`\`

期望 \`PASS_TARGET_FREE_R7_RESUME_PREFLIGHT\`；需独立 Reviewer 读取实际 stdout/terminal 并核对 V3 auth SHA、原 R7 START+TERMINAL/debit、旧 resume02 SHA、最新 V3 contract/binding/release/plan、以及新 physical invocation03 尚未存在。若失败，即 STOP，保留失败与已写文件、不跑下句。

**只有在上述 Mac 真实预检实际 PASS 且 Reviewer 独立验收后，方可执行本轮唯一真实续接命令：**

\`\`\`bash
"$PY" -I -B "$ENTRY" --registered-r7-resume
\`\`\`

它进入当前同进程固定流程：严格验证旧 R7 claim 与失败终态 → V3 read release → admission cached inputs → 一次 fit → 一次完整 S predict → 不可变 seal → seal-bound truth release → 一次评价 → 终态。**不能**独立调用 admission，也不能通过脚本退还既有逻辑 debit。真实物理调用与额度由官方 registry / receipts 读回确认。

已完成的 \`resume_invocation_02\` 不可清理、改名或覆盖。发生新错误不得重试；保存新 attempt03 的完整证据并停。

## 5. 已取得与尚未取得

**已取得**：从 GitHub 真实冻结 source、原官方 6 事件摘录及 \`d05afe94\` Mac 失败 receipt 逐项比对；实现 v3 严格身份字段合同；源文件完整 after；五份 versioned controls；四字段 release 等价；13 项真实存档 event/control 静态检查及四个字段负例的机器收据；补丁按源文本差分可重构验证。

**没有取得**：此云端无法使用 Mac 锁定 Python 3.13.12、用户完整官方 registry、已保存本地完整 artifacts 的实际字节；因此新的 V3 \`--target-free-preflight\` 未执行，真实 OfficialRegistryAdapter + 原 claim→audit 全链未实际跑通，合成 84 项不是这次 V3 验收。预检/运行/效果保持 \`CANNOT_CONFIRM\`，不得宣称本机 PASS 或把此 Issue 关闭。

安全：\`RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false\`。
