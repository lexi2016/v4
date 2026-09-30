# 17:20 owner 最小前向对齐方案（供裁决，未实施）

## 证据结论与停止反复比较

依据不可变目录 `852708f6f210f3e7e9abcc065d7826815c8f39f2/research/manager-r9-consumer-r1-20260930/r3_local_preflight_20260930/`：
- R3_REVIEW.md、owner_source_release_mapping.json：canonical HEAD 为 55a5ba...，实际工作树包含修改与未跟踪拆分模块；HEAD 不能代替这些字节的身份。
- release_provenance_summary.json：配置包文件与其 inventory 匹配，前置 manifest SHA 也匹配。但 source 指向旧 release/overlay，唯一所查 manager_1555_source_freeze.json 的 scope 是 15:55 fupan 路由，没有 17:20 构建映射或 canonical 工作树身份。
- current_launchagent_summary.json：配置根/进程存在，不等于正式激活。原 manifest 的 NOT_ACTIVATED / CANNOT_CONFIRM 保留。
- owner_source_release_mapping.json 的 captured_at=null 保留；不以 GitHub 提交时间、文件 mtime 或本次阅读时间补写。

因此，**所检查证据没有覆盖 17:20 的历史构建证明**。这不是“已查遍所有历史记录并证明记录不存在”。本批不再请求重比相同文件，不重传原始 plist。若本机已有一份不同的、具体可定位的 17:20 构建收据，可核一次；否则转前向建立新来源，不继续无界搜旧记录。

## 已有定位（对应候选不是历史转换证明）

| 职责 | canonical 候选 | configured release 参考 |
| --- | --- | --- |
| 任务目录 | contracts/runtime_workloads.json | 同路径，SHA 不同 |
| dispatcher adapter | infrastructure/scheduling/executor_registry.py | 同路径，SHA 不同 |
| 17:20 dispatcher 实现 | infrastructure/scheduling/_executor_registry_parts/panel_execution.py 及 _namespace.py | executor_registry_review.py；尚无 split→monolith 证明 |
| HK lane 入口 | ops/macos_research_panel_daily.py | 同路径，SHA 不同 |
| HK 采集 | ops/_macos_research_panel_daily_parts/hk_market_capture.py 及 _namespace.py | ops/macos_research_panel_daily_collectors.py；尚无转换证明 |
| capture/gate | canonical 已有入口的实际调用链，须在前向 scope 中逐文件冻结 | ops/macos_research_panel_daily_gate.py；不能猜同路径实现 |
| 共享主表发布 | ops/ensure_hk_security_master.py | 同路径，SHA 不同 |

完整已知 SHA 复用原 owner_source_release_mapping.json。本表不新造 SHA，不把 _namespace.py 与某个 monolithic 文件宣称等价。静态扫描集合仍不等于实际执行闭包。

## 推荐裁决：保留 canonical 的拆分结构，建立新的前向构建链

不要用当前整个 dirty canonical 直接替换 release，也不要整树复制 release 回 canonical。二者各有未证差异。最小合法增量先是“17:20 行为对齐”，不是 provenance 功能本身：

### F0：冻结新的唯一源码事实，不编造旧谱系

唯一 Luna Max Writer 在独立隔离 worktree 中，固定本机此刻的 owner 相关已修改/未跟踪字节、mode、SHA 和 Git 状态。以原入口/dispatcher/catalog、拆分实现、namespace、capture/gate、发布 owner、它们的真实配置/动态加载依赖为 scope。原 release 只读参考，原工作树用户修改保留。

动态 import、subprocess -m、路径注入等须由原入口的无网络 canary/import trace 补齐到具体文件和源码 SHA。trace 必须覆盖原 17:20 路由而不是手工直接调用 collector。新工具只辅助发现静态依赖，不代替这个步骤。closure 未冻结，不修改 collector。

### F1：仅将已存在的 17:20 行为对齐到该 canonical scope

逐函数对照 configured release 的同任务 capture→gate→ensure_hk_security_master 流程，保留 canonical 拆分接口；缺失能力仅以明确的小 diff 带回已有 owner。不引入第二任务、第二 producer、shadow 服务或兜底全市场入口。

用同一组 provider 返回夹具分别跑只读冻结参考与隔离 canonical 原任务入口，核任务路由、两次 plate 调用的次数/参数/顺序、完整 membership 与行情过滤边界、现有 capture/发布错误传播。除 UUID/墙钟等逐项声明的非业务差异外，其余差异全部交 Reviewer，不用粗略“语义一样”消除。

仅比较源码 SHA 或函数名不证明行为等价。20260928 的成功只能作历史回归参考，不能变成 configured release 的本批运行证明。涉及共享 dispatcher 文件时，只动已冻结 HK 任务分支，核 A股/15:55/Vibe/BUY 原分支字节不变。

### F2：从冻结 canonical 构建全新隔离候选，记录前向来源

用项目已有构建工具，不自建构建器。新 receipt 明确 schema/scope 为 FORWARD_RECONCILIATION，记录：canonical 工作树文件集合/字节/mode/SHA、dirty/untracked 身份、前向对齐 patch SHA、构建脚本/命令/依赖身份、目标新目录、逐文件 source→output 映射、生成转换及输出 SHA、完整 owner 执行依赖集合、Writer/Reviewer 独立回执。

只有本次实际构建才可填 build_started_at/build_finished_at；只允许对本次新候选声明前向来源成立。旧 release/旧 manifest/旧1555收据不改写。历史绑定继续 CANNOT_CONFIRM。

独立 Reviewer 确认来源集合完整、实际产物与映射一致、F1 无网络原路由 canary 的断言通过后，可以批准“该新候选上的 R3-A 修改入口”；不因此批准部署、真实 Futu 或激活。

### F3：来源门通过后才实施 R3-A（另批、另提交）

在现有两次 get_plate_stock 调用内保留逐板块成功/失败结果、归一化前 membership、请求开始/完成与 acquired_at、raw row count、serialization_version、payload SHA、capture_run_id。先核原 reader 的完整合同，再从同一个 immutable capture 经已有发布流程形成 qualification authority。

不能把有效报价 687 行当完整 membership，不能把历史 694 或原旧合同 651 当今天的真值，不能缩小集合过门。部分 plate 失败须留失败原件，不发布“完整资格”。序列化数据帧的返回值必须写明是 SDK 结构化响应，不伪称 wire 原始网络字节。

availability 至少受真实查询完成及可验证持久化时点约束；effective_date、target_date、publication_at、acquired_at 分别记录。17:20 后取得的数据不得用于同日更早 cutoff。次日使用也必须满足原 reader 的目标日期/生效期合同，不能通过改标签自动延续资格。合同不兼容则提交具体 reader/publisher 合同变更审查，不能伪造旧 producer 身份或时间。

## 本批边界与责任

GOAL：修复取证工具并提供前向来源决策材料，不宣称历史绑定通过。
WRITER：本批为 Chat 工具作者候选；本机采用/F0–F3 使用项目既有唯一 Luna Max Writer。
REVIEWER：独立 Luna Max Reviewer；本轮未调用，不生成伪造 PASS。
ALLOWED_PATHS：新 r3_preflight_fix_20260930 下工具、测试、补丁、文档、回执。上述 canonical 路径仅为未来候选，尚非准写 allowlist。
FORBIDDEN_PATHS：现有 business source、release、配置/凭证、Stage/BUY/Vibe、R1/R2 与原证据。
PASS_SIGNAL：工具确定性测试及本机独立复验通过；前向映射另须 F0/F1/F2 的真实生成和独立 receipt。
STOP_RULE：未知动态依赖、未固定工作树、行为差异未解释、无授权 build/canary，均不推进。不能以新工具 exit 1/字节相同作准入。

R3-B 保持独立，未在本批改动。R3-A、资格发布、原 API/UI、自然运行和 09969→LLY 真实证据仍 CANNOT_CONFIRM。PR #9 保持 Draft，Issue #8 保持 Open。
