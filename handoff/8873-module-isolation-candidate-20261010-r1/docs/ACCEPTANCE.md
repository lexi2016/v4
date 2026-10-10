# 验收矩阵与结论范围

最终代码测试：`logs/final-locked-suite-r2.log`，106 PASS / exit 0；环境：`review/test_environment.json`。这是本包可用源码闭包上的完整测试发现结果，不是整个 V4 运行闭包或现场验收。

| 任务要求 | 实际验证与测试入口 | 结果 |
| --- | --- | --- |
| A→B / B→A 累积 | `test_sequential_module_releases_preserve_other_bytes`，实际 builder/verify + 临时 plist；合成 evidence 同时保存逐文件树 | 隔离 PASS |
| 同 G 的 A/B，第二个 stale，重建 B | `test_same_base_second_candidate_rejected_then_rebuilt`；`test_two_processes_same_base_commit_cannot_overwrite_first_module` | 隔离 PASS；两个提交进程确为独立 OS process |
| 使用原有跨进程锁 | `test_real_process_lock_blocks_builder_before_candidate_write`；native lock/lease tests | 隔离 PASS；锁忙前不创建候选 |
| 跨 owner / 无 owner / shared 冲突 | cross_owner、owner_binding_negative_cases、shared_or_static_change、shared_contract tests | 隔离 PASS；稳定拒绝码，真实 owner 仍未批准 |
| 基线 id / manifest / generation / CAS | negative_cases、same_base、stale_inverse、native before-replace drift | 隔离 PASS；实际 Mac CAS 未运行 |
| 只回滚 A，保留 B/current static | `test_reverse_delta_rolls_back_only_alpha_and_preserves_beta`（含新增文件反向删除） | 隔离 PASS |
| 不安全回滚拒绝 | later_same_module、later_dependent、unrelated_target、forged_inverse、stale_inverse | 隔离 PASS |
| 非目标全量 bytes/mode 保留 | 每次 core `_verify_delta_files`；顺序/回滚完整 inventory 比较；state sentinel | 隔离 PASS；不读取真实 owner products |
| 构建/manifest/plan 注入失败 | `test_builder_failure_cleans_candidate_and_preserves_current` | 隔离 PASS；移除自有半成品，记录 failure phase |
| 原生 pre-/post-replace、bootstrap/health 失败 | `test_native_switch_failure_recovers_immediate_preimage` | 对 fixture 可辨认状态 PASS；真实服务未运行 |
| 已加载但未运行/身份不足 | `test_native_nonrunning_candidate_reports_incomplete_recovery_honestly` | **PARTIAL / CANNOT_CONFIRM**：测试确认 ROLLBACK_INCOMPLETE 的真实返回，不能称旧服务健康已恢复 |
| 路径/清单负例 | source symlink、traversal、missing file、SHA、duplicate delta/owner/route、dependency cycle、static new file | 隔离 PASS；Mac 特有大小写/Unicode 文件系统行为 NOT_RUN |
| receipt / retained release / owner products / config symlink | 独立 Reviewer 4 个 P1 原始复现共 8 分支 + 新回归 | 修复后独立复核 PASS |
| shared wildcard / ancestor overlap | 独立 Reviewer P2 + `test_review_shared_contract_cannot_hide_registry_ownership` | 修复后 PASS |
| 原生 guard 未经验证代码不能先执行 | missing pin、changed dependency、wrong cached origin、forged pyc、actual closure pin tests | 隔离 PASS；fresh standalone 假设见架构 |
| 保持 launch/safety/state bindings | core launch digest、staged identity/parser、历史 allowlist、原有断言 | 隔离 PASS；所有测试 safety flags 固定 |
| 真实业务模块及共享前端联合发布 | 所供 MODULE_MAP 标记 CANNOT_CONFIRM，实际 dist/build 输出不在输入中 | **未完成**；只实现拒绝，不伪造批准 |
| 当前原生命令、正式 immutable staging、服务 readback | 历史参考 call-site 证明可读；当前 Mac 身份无证据 | **CANNOT_CONFIRM / NOT_RUN** |

## 不能把 PASS 的总数转换成什么

106 项中包含“必须正确拒绝”的负例，也包含“必须如实报告恢复不完整”的用例。该数字不表示所有业务需求已部署完成，更不表示当前 8873 已健康、UI 已验证或金融动作已授权。

默认安全字段保留：RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。没有访问或写入 live owner state，没有外部服务 reload；测试中的 launchctl/HTTP/clock seam 是可确定的合成替代。

独立审查初始 REQUEST CHANGES、所有复现和修复后的复核都保留在 review/；最终结论以其中最后的 re-review 节和准确源 SHA 为准。
