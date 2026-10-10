# 实际执行记录与未执行事项

## 工作流和技能

明确选择 Superpowers 后，读取并采用 using-superpowers、systematic-debugging、dispatching-parallel-agents、writing-plans、test-driven-development、brainstorming、executing-plans、requesting-code-review、using-git-worktrees、verification-before-completion 及 Codex 工具映射。用户任务已有明确目标、架构和隔离测试授权，因此先完成可复核候选；没有因通用设计审批建议再次中断，也没有把它解释为 live 发布许可。

可选 `writing-good-tests.md` 和 reviewer template 子资源未成功取得，未声称执行了不可用模板。完整计划保留于 review/IMPLEMENTATION_PLAN.md；原进度记录、只读 owner/native 审计和独立问题复现均保留。

## 按证据推进

1. 读取固定 Issue/任务书/README/模块图/发布链/manifest，全量校验输入；核对历史原生脚本，确认业务 owner 与当前 publisher/staging 证据缺口。
2. 在独立本地 Git 基线开发。原有 20 个测试先实际通过；新增业务 owner 测试产生18个失败，再实现严格 owner enforcement。原有测试断言没有修改。
3. 实现原入口 module_id、同锁全快照 delta 和 current-base inverse delta。反向回滚最初8个用例失败，其后绿态通过；保留全部日志。
4. 并行 native 实现复用原 cross-process lock/lease和common verifier，原公开整包 rollback 改为明确拒绝。测试捕获 staged argv/env release身份冲突并加写前检查。loaded-but-not-running仍如实保留恢复不完整。
5. 独立 Reviewer实际发现4个P1和1个P2。逐个用合成场景复现、修复、原始攻击形状重新验证，10个独立分支PASS；最终候选审查ACCEPT，生产执行不获该审查批准。
6. 保护依赖固定5个SHA，47原始历史部署常量AST不变。最终106个测试在全新精确依赖环境通过；构建候选和真实service action分别记账。
7. 生成可重放合成证据、完整前后文件、正反向补丁和逐文件SHA，独立打包/远端readback。

## 中间失败和环境更正

记录中保留了一次 Stage role传错lease的中间失败，修复后原有断言恢复通过。新增边界测试也曾有“预期错误文本不符”和“READY/READY_FOR_REVIEW”测试预期笔误；更正测试预期符合实际契约，没有把这些笔误当成生产bug证明。缺失文件仍按原 FileNotFoundError 语义拒绝。

初始测试环境把4个直接依赖固定到uv.lock，但部分传递依赖是后来的版本。一次uv降级后留下重复dist-info；最终环境复核发现并记录于 `review/test_environment_pre_final_mismatch.json`。没有删改旧日志冒充一致，而是建立全新的 `testenv_final`，一次安装19个精确locked依赖，检查无重复/不兼容，重跑全套。最终准据是 `review/test_environment.json`、`logs/final-locked-suite-r2.json/.log`。

`native-original-replay-blocked` 保存了旧script按历史import方法重放遇到模块注册KeyError的失败；它不被作为新bug的验证依据。`native-flow-red` 通过仅旁路common business verifier的瞬时副本检验测试敏感性，两个owner-drift用例按预期失败；该旁路未写入交付代码。

## 从未执行

未运行真实 Mac 命令/launchctl，未联系 live 8873，未读取真实owner state/研究产物/凭据/完整环境，未安装launch plist，未改变default branch或合并PR，未宣布deployed/API/UI/natural verified。本包记录中的state、HTTP、launcher行为均有synthetic-only标识，不能外推成运行事实。

最终 synthetic evidence runner 首轮自身的 syscall 文件审计误判 SafeRoot 的 dir_fd 相对操作，exit 1，未进入候选构建；完整失败日志保留。更正 runner 后全新 run2 产生 3 场景、9 候选、8 次临时提交、1 次 stale 拒绝和 1 次 rollback preparation，17 个保留性判据均 PASS；导出 157 文件，未导出 fixture app/dist/plist。
