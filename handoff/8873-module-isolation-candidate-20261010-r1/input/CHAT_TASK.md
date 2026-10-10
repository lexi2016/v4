# Chat 实现任务书：8873 同一 API 服务内的模块独立发布

## 唯一目标

更新既有 [lexi2016/v4#30](https://github.com/lexi2016/v4/issues/30)，复用旧交接 commit `a0a0b88dc133d14ee5763569272c174bcd7cc445` 的可用工作，并以本包快照核对当前代码。让经过 owner contract 确认的模块能够在**唯一现有** `com.lexi.v35.api-only` / `127.0.0.1:8873` 服务内单独修改、测试、构建、发布和安全回滚；一个模块的候选或回滚不得替换其他模块/共享面已经发布的版本。实现必须接入真实 8873 原生发布入口。只增加文档、继续整 app 任意 delta、另启应用/端口或替换启动体系均不达标。

本包没有实现这项功能，也不授权生产/公开发布。选股恢复补丁保持暂停；不改 Stage、Vibe、BUY/交易门禁、owner 数据或无关服务。

## 实施前冻结

1. 只读重新绑定当时的 active release id、`release-manifest.json` SHA、完整 app inventory、gateway launch identity、static bundle/build identity 和真实发布命令；本包的 runtime-B 是源快照，不替代届时新读的 active identity。
2. 读取并复用旧 Issue #30 的 `handoff/api-module-release-20261008/` 与当前 `ops/api_release_integration.py`。已有底层 exact-base、显式 delta、lock/CAS 和 non-delta preservation 不能另造第二套。不得把 `service_role`（gateway/stage/manager）当作业务 `module_id`。
3. 每个真实业务模块的 `module_id`、唯一 source owner、共享路径、API route、构建输入/输出、data/state boundary 必须由现存源码/实际构建证据决定。五个工作区目录到业务模块的映射目前 `CANNOT_CONFIRM`，不得凭中文目录名分配代码。
4. 先隔离候选跑合成测试，输出 candidate manifest、base identity、delta receipt、前后文件树和 SHA、测试 receipt、rollback recipe，再交不同 identity 的只读 Reviewer。真实 service reload、launch-agent plist 安装或 8873 发布须走另行授权流程。

## 需要在实现中闭环的问题

- 在现有 gateway 发布路径上添加业务模块 owner/path allowlist、`module_id` 绑定、共享 seam owner 和 fail-closed 冲突；gateway 的任意显式 delta 当前不是已证实的业务 owner allowlist。
- 所有候选从锁内读到的完整 active immutable release 构建，并绑定 release id、manifest SHA、inventory SHA、generation、module id、每个目标路径原/新 SHA。过期 base 的候选必须拒绝并从最新 active 重建。
- 继续复用同一跨进程发布锁、精确 CAS 和完整 app snapshot。串行发布必须累积模块改动；同基线并发候选的第二个提交不能用旧副本覆盖第一个模块。
- `app.py`/route registry、`apps/web/dist`、Vite entry manifest、HTML、静态资源、公共 contracts、config 等列为显式共享面或受限 owner 路径。缺 owner 或跨 owner 修改时在写入/reload 前拒绝，除非生成有批准 owner 的联合集成变更。
- 模块 rollback 必须在**当前 active** 版本上按目标模块 reverse delta 实施，并再次 CAS；禁止回切旧整包。若 shared seam 已被后续模块依赖、无法做模块化反向 delta，则整体拒绝并给出证据。
- 不将 owner state、研究产物、服务凭据、完整环境、Stage data 写入候选源码；外部 Mac 绝对路径作为运行绑定参数/脱敏示例，不作为模块内容。
- 候选构建、plist 计划生成与真实部署/readback要分别记录。当前源脚本 `launchctl_called=false` 的计划不等同 live cutover，也不能证明服务连续。

## 必须自动化通过的验收矩阵

每个用例在独立临时 app、固定 synthetic source/manifest/static fixtures 下执行，开始于明确 base；测试不得访问 live release、service 或 owner state。版本和路径保持可追溯，安全标志不变。

| 场景 | 动作 | 唯一通过信号 |
| --- | --- | --- |
| A/B 顺序发布 | 从 G 发 A，再基于 A 更新后的 G' 发 B；反序再跑 | 当前候选含 A+B 各自指定 SHA；shared seam 只出现一次且 owner 明确 |
| A/B 同基线并行 | A、B 都从 G 生成，A 先 commit，B 后 commit | B 的 G 候选以 `STALE_BASE`/等效码拒绝且当前 A 保留；B 从新 G 重建后最终 A+B 同在 |
| shared file 冲突 | 两模块触碰同一 router/registry/config/static manifest 或缺 owner | 写入/reload 前以稳定冲突码 fail closed；active/app/static/service identity 不变 |
| 过期 release/CAS | base release id、manifest 或 generation 与现行指针不匹配 | 拒绝，没有静默 rebase、覆盖或 reload |
| 单模块 rollback | A、B 顺序发布后只回滚 A | A 恢复指定父版本，B 和当前 shared/static bytes 保持；无法安全分离时明确拒绝 |
| 非目标完整性 | 每类发布/回滚前后列出目标集外 app source、static、config 与 synthetic state hashes | 所有非目标 bytes SHA 完全相同，没整目录静态回退或 state 写入 |
| 发布失败 | 在验证、构建、临时写、atomic replace/cutover 准备、reload/health seam 注入确定失败 | 原 release remains active/healthy，候选无半成品；receipt 定位阶段，实际服务动作只在隔离模拟中验证 |
| 路径和清单负例 | symlink/path traversal、duplicate owner、缺文件、SHA 不符、动态静态文件、过期 rollback source | 每个在 active 变更前拒绝；没有逃逸写入 |

## 停止规则与交付

遇到 active 身份/源码变化、共享 owner 证据缺失、无法确认真实 8873 candidate entry、原子切换失败语义不明或回滚会改变其他模块时，停止切换动作并标 `CANNOT_CONFIRM`，先请求最窄的证据/裁决；不添加新进程/端口绕开问题。

交付实现 diff、隔离测试和 candidate receipts、SHA 变更清单、真实 publisher/launcher call-site 证明及只读 rollback recipe，交不同 identity 的独立 Reviewer 检查实际行为。没有另行授权时不得修改/启停真实 launch service，也不宣称 deployed/API/UI/natural verified。金融安全始终 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
