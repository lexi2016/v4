# 经理选股工作台：现役 UI/API 问题包

本包记录部署中的三通道经理工作台在 2026-10-09 目标日期、2026-10-08 公告 publication 日期下的真实页面与 API 读回问题。页面和 API 在 2026-10-10 被回看；这不是目标日自然运行，也不是修复后的验收。

包内运行时证据把两次读取分开保存：部署后 owner 刷新紧邻的两个 GET 对同一计划返回 CURRENT；后续独立 API/浏览器读取却对同一 run 标记 STALE_INPUTS_CHANGED、consumed=false。计划的日期、语义版本和 research cutoff 相同，但 saved/current input_identity 不同。具体哪一输入字段造成变化仍为 CANNOT_CONFIRM，不能靠强制标记 CURRENT 绕过。

本包包含真实截图、独立的发布后 API/视觉检查、独立前端边界审查及 receipt、独立后端 identity-coupling counterfactual review 与机器 receipt、修正了 V3.5 authority root 的隔离 owner 复核、固定 fused release 的源文件快照，以及原 announcement capture/Reader/Reviewer/import/readback CLI 源码。后端结果确认全局 manifest SHA 是 P2 过宽 identity contributor，但不证明唯一 live stale 原因。前端审查确认三路 renderer 未挂载、上下 US scope 不同，并定位到研究结果 section 的渲染顺序。它不含 15 MB live response body、原始行情行、完整 manager state、真实 LaunchAgent plist、凭证、dist、venv 或 node_modules。

## 包内验证

从 ZIP 解压后的 package 根目录运行：

    python3 tools/verify_package.py
    python3 tests/check_evidence_contract.py

第一条校验固定源码、证据和 package-file manifests；若旁边有生成时的 ZIP，还会核对完整 ZIP 成员与 SHA。干净解压目录通常没有旁边的 ZIP，此时脚本会打印 ZIP_CONSISTENCY=NOT_AVAILABLE 并以退出码 0 完成包内清单校验。需要独立检查原 ZIP 文件本身时，在 ZIP 所在目录运行 python3 -m zipfile -t V4_MANAGER_LIVE_UI_API_PROBLEM_20261010.zip。第二条检查包内真实 receipt 的证据关系。这些命令不运行 Mac owner、不访问 API，也不等于修复、部署、UI、自然运行或金融业务验收。

## 关键文件

- PROBLEM_REPORT.md：真实症状、期望行为、Chat 修复任务和 CANNOT_CONFIRM 边界。
- ONE_DAY_OWNER_REUSE.md：既有单日 owner 命令入口、日期配对与哪些结果可以复用。
- SOURCE_SNAPSHOT_MANIFEST.json：现役 fixed 16 source refs 和 UI/API 上下文的逐文件 SHA。
- evidence/live_ui_api_problem_projection.json：从真实机器 receipt 与独立前端 receipt 导出的无 raw-response 证据投影。
- evidence/frontend_boundary_report_20261010.md / receipt：三路摘要未挂载、上下 US scope 与候选 bundle 的独立定位；browser-loaded bundle SHA 仍 CANNOT_CONFIRM。
- evidence/root_cause_report_20261010.md、reproduce_global_manifest_identity_coupling.py、global_manifest_identity_counterfactual_receipt.json：P2 全局 manifest identity coupling contributor 的独立证据；不含 live root 唯一性结论。
- evidence/：视觉截图和元数据 review/receipt。
- code/current_fused_app/：部署候选的源码快照。
- code/previous_reference/：旧单日 owner 和 R1/R3 reader/consumer 的已审查参考快照。

当前发布身份为 stage_r4_manager_r2_owner_input_r1_fused_r1，API PID 10321，候选 manifest SHA-256 fd7f21af0205b9d25a8ab5d33592aff42bf76c0419799b7c1724b94a286aeb86。源码快照来自已部署候选；运行时 API/UI 仅证明到原始 receipt 所述范围。
