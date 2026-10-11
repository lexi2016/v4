# Issue #36 — R7 同身份恢复入口最小修复（独立分支）

## 结论和适用范围

固定基线 Git commit: \`a2fd6cf25aef8c06ed6ba2edb67c6797d5ef07c3\`；当前七源码、original R7 controls、resume_v2 controls 全部**不改字节**。新添一个仅作调用接线的 \`r7_resume_launcher.py\`，源码完整 SHA256 \`24f62b0c8cbdb01cb0c32d86cd0c9f125df65c2835406364000ece2d8b97c29f\`。

直接实证缺陷：基线 \`run_f5_breadth1.py:2359–2378\` 的 CLI 只接受 \`--registered-real-chain\`，且总调用 \`run_registered_real_chain()\` 不传现有 resume authorization。旧原 R7 action key 的 admission debit 已经消费，因此该命令无法进入已有的 \`_preflight_registered_r7_resume\` 和 \`resume_context\` 分支。

本文件只打开已有分支调用，不改模型、原 64 列、BREADTH1、BCE、标签、对照、评价、门槛。既有 original grant、失败 START 和 TERMINAL、resume_v2 controls、preflight01/02 及 probe03 合同均不修改，且不释放额度。现有科学源码及绑定的 SHA 不会发生连锁变化。新增入口自身必须从本固定提交安装并验证 SHA；它不替换七模块中的 runner。

## 读取链和安全要求

启动器先校验锁定的 Python 3.13.12 原始二进制 SHA、七个源码文件完整 SHA、恢复授权文件路径与完整 SHA，再加载固定的 \`run_f5_breadth1.py\`。不允许用户从 CLI 输入新合同、新授权路径、新执行 ID 或新预算。

\`--target-free-preflight\` 实际调用当前 runner 的 \`_preflight_registered_r7_resume\`，该函数使用原 \`OfficialRegistryAdapter\` 和 \`BREADTH1OfficialActionAdapter\`，检查真实完整官方 registry、旧 R7 START/失败 TERMINAL、准入 debit=1、fit/predict/truth 的动作未消耗、原失败文件、当前合同/绑定和原 R7 read release 的四字段规范化。成功时仅回机器 JSON，**不 claim、不打开目标数据、不写 registry、不创建运行目录**。如果完整 registry、真实 builder/validator、锁定 Python 或已保存 Mac 失败文件缺失，则 fail-closed，不给 PASS。

\`--registered-r7-resume\` 将固定 authorization 路径+SHA 传入现有 \`run_registered_real_chain\`；是否继续、如何生成新收据和模型/真值物理次数，由原封存代码和官方适配器管理。任何失败保留 R7 debit 和旧失败原件；不自动重试。

## 本轮实际预检查证据：严格范围

1. 原始 GitHub 固定80文件清单、当前七个源码、original/resume controls 和官方 six-line event excerpt 已实际读取。12项静态控制字段检查中11项成立。resume read release 对原 R7 release 正好只有合同SHA、绑定SHA、输入绑定路径和输入绑定描述SHA四项变化，完全符合 authorization 正规化列表。
2. 发现一项遗留一致性差异：\`resume_v2/read_plan.json:pre_admission_binding_sha256=129c83d15258ae3fce6a325cab84ee1648ff8bdac574d16c02b1ca1a9783531c\`，而当前 \`resume_v2/pending_binding_resume_02.json\` 实际SHA为 \`97d221d475a56aad99964b911d6c98b0ab886b43b017be62bed3f6abc8836be1\`。原 runner 仅按固定 SHA 身份处理这个只读历史 plan，实际数据读取由 authorization 正规化后的精确 read release 约束；不能把二者误称为相同。独立 Reviewer 应明示此为历史计划引用还是需要版本化更正，不能静默改旧文件。
3. 隔离 Python 实际导入与固定 SHA 一致的 \`registry_adapter.py\` 和 \`execution_guard_core.py\`，直接调用真实 \`OfficialRegistryAdapter._validated_profile\` 成功，并核对真实方法入口。但这一检查**没有**调用 adapter constructor/builder/validator、没有加载完整官方 registry，也没有执行当前七模块的真实预检。机器收据明确 \`PASS_REAL_ADAPTER_PROFILE_AND_SIGNATURES_ONLY\`。
4. 本地云端锁定 Python 与 Mac 不同，实际用启动器 \`--target-free-preflight\` 获得 \`CANNOT_CONFIRM_TARGET_FREE_PREFLIGHT / LOCKED_PYTHON_VERSION_MISMATCH\`，无任何目标读取或登记。**不宣称远端已经获得完整预检 PASS**。原 probe03 仍是 \`CONTRACT_ONLY_NOT_COUNTED\`。

## Mac 使用（先独立预检，不重训、不重复准入）

将本 Git 文件完整拷入项目外、未被七源码代码清单覆盖的独立目录，例如 \`/Users/lexi/Desktop/学习/因子工厂/handoffs/issue36-r7-resume-entry/r7_resume_launcher.py\`。不覆盖 R7 原模块/controls。独立 Reviewer 先核固定 sha:

\`\`\`bash
PY='/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/.venv_locked/bin/python3.13'
ENTRY='/Users/lexi/Desktop/学习/因子工厂/handoffs/issue36-r7-resume-entry/r7_resume_launcher.py'
printf '24f62b0c8cbdb01cb0c32d86cd0c9f125df65c2835406364000ece2d8b97c29f  %s\n' "$ENTRY" | shasum -a 256 -c -
"$PY" -I -B "$ENTRY" --target-free-preflight
\`\`\`

**只在机器输出 \`PASS_TARGET_FREE_R7_RESUME_PREFLIGHT\`、独立 Reviewer 复核并解决 read_plan 引用的语义后，才执行下列唯一真实链命令：**

\`\`\`bash
"$PY" -I -B "$ENTRY" --registered-r7-resume
\`\`\`

后续实际过程沿当前 runner 的同进程流程：已扣费旧 R7 claim/失败终态精确确认 → 已批准 resume read release → admission cache → fit 一次 → S 全量 predict 一次 → 不可变 seal → 精确 truth release → 一次 sealed evaluation → 新总终态。不会重新 claim 原 R7 admission；不允许改 action key、execution_id、grant_id、清理旧目录、退款或另开 R7 grant。

任一返回 \`CANNOT_CONFIRM_*\`、已有目录、registry/身份不符，即停止并保留 stdout/stderr、入口SHA、原/本次物理计数和实际终态，不重新调用。新执行物理调用数必须按真实回执报告，不能由历史 \`fit=0\` 推断本次也为0。

## 冻结研究边界

\`RESEARCH_ONLY=true\`、\`production_allowed=false\`、\`buy_gate_updated=false\`、\`orders_sent=false\`。

远端提供的是**代码修复与受限预检查**，不是本机成功登记或 F5 效果结果。完整官方 registry 从未上传；在能执行本地真实 adapter 预检前，当前工程身份整体仍是 \`CANNOT_CONFIRM\`。