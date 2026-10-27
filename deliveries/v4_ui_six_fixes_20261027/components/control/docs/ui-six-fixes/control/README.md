# 本批发布控制 R2

本目录仅为已冻结 Main PDF2 与 API12/静态2 的一次发布准备控制。业务 PASS 复用，不重跑业务测试。Writer 未执行发布、launchctl、信号或实际锁操作。

`prepare.py` 必须先收到原 owner 明确交接的 JSON 与 SHA。它只读当前实际 Main/API/Graph、manifest、原锁 metadata、Graph 配置与已审 overlay；在本批证据目录构造不可变候选与精确 CAS 计划。它不获取 live 锁、不写现役 release/plist、不调用子进程。新 API 候选必须采用原 integration helper 支持的标准 manifest；当前已交接的旧 API 按下述精确合同适配。

`controller.py` 默认只输出 PLAN_ONLY。仅主控可在最新基线核对及独立 control PASS 后启用执行模式。它复用原 API integration、API plist rewrite、Graph operator 的 stage/CAS/逆 CAS/readback，以及原 Main LiveOps 的有界只读进程与 Python 绑定方法。不会调用旧 Main guard 的 arm、term_old、Recipe 或要求 PDF pending=0 的 boundary。

原 owner 未交接、任一 owner/锁/baseline 不明或变化时停止实际阶段。原 owner 的 21/76 股接入等非 overlay 字节全量精确复制并核 SHA；同路径 before SHA 冲突停止，由主控做有界裁决，不能覆盖。Main ProgramArguments 中实际 launcher 必须随 release 改写并在 loaded definition 和实际 PID cwd/Python/module SHA 中读回。API 的独立 US ledger 同时写入 `/usr/bin/env` 与 EnvironmentVariables。

执行按固定三 label 获取原 service.owner、A_LONG/DEFAULT lane、PDF ingestion、announcement、共享 API release、collector guards。锁为原 inode，不创建/替换原锁；已有 PDF/其他 Main child 必须自然结束。PDF ingestion 锁已获取后出生、尚未获准处理的 queue tick 可以由原 daemon shutdown 回收；已存在 child 不以此分类。队列和 checkpoint 不改，不要求 pending=0。计划从实际 schedule catalog 提取业务时刻，并至少保护 13:00、13:14–13:16，提前五分钟拒绝进入切换。

service action intent 先落盘；每个动作只发一次。timeout/nonzero/未知结果后保留 guards，明确 RECONCILE、ROLLBACK 或 VERIFY_NEW；不盲重试。逆 CAS 仅识别已知前后字节/loaded identity，已处于旧态的 Main 不重启。旧 PID 退出只读等待，复用 PID 则停。journal 在成功、早期失败及恢复后关闭；原有 ResourceWarning 来源为未关闭 journal，已加 finally 并有 warnings-as-errors fixture。

交接 schema 见证据目录 `HANDOFF_TEMPLATE.json`，状态保留 PENDING；其中所有 identity/SHA/inode/PID 必须由主控在原 owner 完成交接后从实际运行读取。`main_guard_parameters` 的 `/bin/sleep` 和 guard_seconds 仅满足旧 LiveOps 的固定构造范围；本控制不启动该程序。

Control 首审三项 P2 的返修：交接必须含固定 `domain=gui/501`，已用实际 Main helper 的 `initial_old`/`disabled` 接口做无 live 调用 fixture；业务审据采用原始 `review_receipt.verdict=REVIEWED/PASS`，并绑定 combined freeze、API overlay、Main overlay 三个 SHA。完整目录核验复用原 inventory_tree/inventory_digest，在 stage 前、stage 后、服务动作前以及最终读回对三个组件检查；额外未列文件也拒绝，不能只核 manifest 已列出的文件。新增结果和 source SHA 见 `P2_REPAIR_HANDOFF.json`、`CONTROL_SOURCE_MANIFEST_R2.json`；首审 FAIL 原样保留。

现役 Main 的额外 `files` 是 881 项 `app/相对路径 -> SHA256`，与 `app_files` 精确一致。仅 Main 兼容此已核合同：先要求安全相对路径、合法 SHA、双索引一致，再保持既有键集合并按候选完整 inventory 更新值。外部来源/绑定/历史审据保留；未知路径、双索引冲突、键集合变化仍拒绝。API/Graph 遇到该 `files` 字段仍拒绝，不用 Main 索引兼容扩展 API 合同。直接回归以真实 Main manifest 和冻结两项 PDF overlay 验证 881 项索引及全部非 delta 字节。

现役 API 的真实 `v4.runtime_graph_repair_release.v1` 与原 helper 标准合同存在输入缺口。复用原 owner `prepare_api_fresh_r2.py` 的全量 app_files/路径/字节/SHA 合同及 R7 标准候选投影；新 manifest 添加标准 candidate 和完整 inventory（含 entry_count），保留源 manifest 身份与原历史字段。`api_identity_scope` 只对交接中精确的旧 root/id/manifest path/SHA/inventory 提供真实 legacy identity，并绑定原外部 gateway 模块合同/8873/plist label；不把旧 manifest/schema/SHA伪装成标准。它只临时替换本控制私有 helper 实例的 identity 读取，并在 finally 恢复；未知/标准/其他 root 均走原严格方法，原 helper 源码与现役字节不改。

prepare 读取基线、执行前原 verify_api_release_candidate、新 API 指针验证及逆 CAS 后旧身份验证统一使用该作用域；原 receipt/delta/non-delta/shared-lock 核验保留。真实 legacy 形状临时整树 fixture 覆盖 Main881/API1319 及标准 API1320、API非delta1306/Main879、base→candidate→old指针、域外严格拒绝、错误 schema/root/SHA/模块合同与额外文件漂移。不会用 PREPARED_NOT_ACTIVE 历史字段判断当前服务状态，实际 PID/启动路径仍由主控读取核实。

准备命令（只在交接后；占位符不可直接运行）：

```sh
"$PANEL_PYTHON" -B docs/ui-six-fixes/control/prepare.py --handoff HANDOFF.json --handoff-sha SHA256 --output /Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027/controller/publication_control_r2/candidate
```

独立 control PASS 应绑定实际 PLAN SHA、controller SHA、prepare SHA。随后主控从同一终端执行并保留恢复输入通道：

```sh
"$PANEL_PYTHON" -B docs/ui-six-fixes/control/controller.py --plan PLAN.json --execute-reviewed --review CONTROL_REVIEW.json --review-sha SHA256
```

此命令不由 Writer 执行。缺交接时不物化正式 PLAN。执行后仍须另做实际 API/UI 与白天无新 PDF child 的验收；自然 02:00 行为单独保留未验。

针对性 fixture 文件为 `test_control.py`。fixture 仅操作临时树/临时锁，拦截 prepare 的 subprocess，模拟 live service readback；通过不等于实际发布通过。本轮精简 scope、SHA、增量命令及历史失败见证据目录的 SCOPE.json、CONTROL_SOURCE_MANIFEST.json、VALIDATION.json、HANDOFF.md。旧草稿保留在 legacy_not_used，不可执行。
