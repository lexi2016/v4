# Issue #30：API 模块发布隔离与预选池恢复源码交付

本交付以 `a0a0b88dc133d14ee5763569272c174bcd7cc445` 的九文件问题包为输入，完成模块差异构建、真实发布入口接线和预选池 consumer 的源码候选。**它是可以逐文件审查和在隔离目录复跑的源码交付；当前线上页面恢复没有在这里建立证据。**

优先阅读 [本机处理提示词](PROMPT_FOR_MAC.md)、[最终测试记录](TEST_RESULTS.json)、[独立最终审查](evidence/independent_final/final_review.md) 和 [剩余事项](OPEN_ITEMS.md)。原问题单为 [Issue #30](https://github.com/lexi2016/v4/issues/30)，原九文件完整保留在 `original/issue30/`。

## 为什么一个模块发布会丢失另一个模块的修复

8873 从一个 app release 启动。原发布工具验证候选 manifest 与候选库存相符，再切换整个 API 的 app 根；这些检查不能证明候选包含届时 active 中的所有已接受修改。因此，经理模块可以没有编辑预选池代码，却通过发布一个缺少预选池修复的旧整包使它回退。任务私有 evidence 锁还无法协调其他任务对同一 API 指针的发布。

本次保留单 API 与统一 8873 入口，将隔离落实到源码所有权和发布差异合同：**经核验的当前 active app + 本模块明确列出的 after 字节 → 新集成候选。** 非 delta 文件从 active 复制并逐项核对，不从 source checkout 整树打包。没有引入新端口、第二面板、平行数据 producer 或微服务。

## 八个产品文件与实际作用

| 文件 | 作用 |
| --- | --- |
| `after/ops/api_release_integration.py` | v2 active/base/delta 合同、模块 ownership、文件/目录保留证明、descriptor 路径校验、共享 API 指针锁 |
| `after/ops/build_release_candidate.py` | 从已验证 active 构建，按真实 Git tracking 状态控制额外纳入，完成前复核身份，候选配置写入保持目录边界 |
| `after/ops/prepare_api_only_cutover.py` | 安全生成未激活的 API 配置与计划，验证前后身份，不输出可绕过 guard 的裸发布命令 |
| `after/ops/create_api_module_delta.py` | 将固定的模块 change set 绑定到本机当前 active；生成一个新的、可审查的 v2 delta receipt |
| `after/actual_cutover_reference/api_only_cutover_r2_ready.py` | 对实际经理 R2 publisher 的精确补丁，execute/rollback 自身持共享锁，写前复验，恢复沿同一 guard |
| `after/apps/api/v35_api/app.py` | 只调整预选池专用装配与抽取位置，保留其他模块代码 |
| `after/apps/api/v35_api/preselection_router.py` | 原 GET 路由、请求日期、分页与返回元信息 |
| `after/apps/api/v35_api/preselection_service.py` | 来源绑定、空本地池修复、严格 HK 补充、限定旧 SHA 故障的逐池隔离 |

精确 before/after SHA、大小、mode 与源码 owner 见 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。`patches/` 保留对原输入的完整差异，`PATCH_VERIFICATION.json` 记录实际正反往返结果。新增 router/service 的前像是“集成时必须确认不存在”，不是声称已经取得当前 1016 项库存中的不存在证明。

## 发布合同与不可越过的边界

v2 delta 绑定 active release id/root、manifest SHA、app 文件库存 SHA/数量、active plist 路径/SHA、每个目标文件的 before/after SHA 与 mode、文本 diff 证明和静态 module policy 摘要。未知字段、重复 JSON key、跨模块路径、多余共享文件声明、未声明增删改、错误前像和过时 active 均拒绝。目录集合、空目录、app 根和目录 mode 另由 `directory_preservation` 绑定；新增目录只允许新增 delta 文件的必要祖先，并固定为 `0755`。

“相对 active 新增”与“Git 未跟踪”分别处理。已经提交到 Git 的合法新增模块无需再声明 untracked；确实未跟踪的 source 文件必须明确纳入，且仍在 receipt 中。正式 builder 将 tracked 与已批准 untracked 的并集传给 core，复制开始前拒绝其余 source 文件。允许列表中的非 delta 文件也不会被复制。

实际 R2 脚本的公开 execute/rollback 函数内部获取同一 active API plist 旁的 persistent flock；写入与恢复帮助函数都要求本次有效 lease。固定路径的 guard 先核固定 SHA，再执行同一份已经核验的 bytes。下一次事务重新读取并检查磁盘；当前事务保留已经核验的 guard，避免文件替换令故障恢复也失效。bootout 前及 active 写入前都会复核集成基线。

切换前另写一份只读 `prepared_receipt.json`，保存原始 base、备份与完整事务合同。自动恢复中断时，公开 rollback 可在同一 guard 与共享锁内继续；只接受已知原指针、候选指针或明确的 `ABSENT`，以及已知或确认未加载的 runtime。普通 launchctl 查询错误不能充当“服务已卸载”。所有 JSON 读入统一拒绝重复字段和非标准常量；恢复成功前同时核原 plist 字节及 metadata，权限漂移不能被记录成完整回滚。

**原脚本的 47 个 R2 顶层赋值保持原值。** 它依赖原 staged 目录层级与 R2 证据，不能搬到中央 `ops`，不能拿它直接发布新的恢复 release。新版本的 plan、staged plist、候选 pins 和运行身份必须在本机基于当时 active 重新冻结和审查。原 R2 包缺 v2 delta 时应被拒绝，没有补造历史 receipt。

共享 flock 只协调已经迁移、遵守同一锁的发布者。本次已覆盖所提供的实际 R2 入口和 canonical build/prepare 源码；没有证据证明本机其他 publisher 已退役或已安装此补丁。全机入口盘点、禁止旧路径继续发布和实际安装由本机集成验收完成，详见 `design/MODULE_OWNERSHIP.md`。

## 预选池修复与附加兼容语义

在仓库固定旧快照中取得的 app 单文件 SHA 为 `90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7`，与 Issue #30 晚间 R2 记录相同。在这个精确前像上恢复既有两处修复：传入 `preselection_source_root=resolved_pool_source`；仅在 `local_pools` 非空时进入保留本地 A 并补 HK 的分支。再抽出 router/service。没有将旧 canonical 整文件覆盖到经理运行版本。

测试还复现了历史 domain 的独立缺陷：resolver 的 `read_all` 只捕获 `FileNotFoundError`，单池 SHA `ValueError` 会冒泡并使整个日期 `DATA_BLOCKED_EMPTY`。旧未拆分 `435d...` 在相同历史依赖下也有四项相同失败。service 新增一条限定恢复路径，只匹配这个已复现的唯一错误，使用原 exact-date owner、source lease、import lock 与严格 trio snapshot 逐池核验。pending 不交给可能执行恢复的 reader；未知错误保留原阻断。只有实际隔离坏 SHA 子池且最终仍有有效 A 行，才返回部分结果。

在新增的旧 SHA 故障恢复路径中，每个拟恢复的 A 行都必须同时满足日期、pool、市场和全部已提供代码字段的一致性。`market=US` 或 `symbol=HK.00700` 不能被另一个 A code 掩盖。坏池被隔离，其他有效 A 池继续保留。配置来源补 HK 的分支及上述恢复路径中的 HK 继续使用原完整 100 行、来源、日期与 split-date provenance 检查；物理存储 trio 与上游 run trio 分开记录。原 domain 的其他路径没有因此获得全面行身份验收结论。

此项是两处既有修复和机械抽取之外的新增 consumer 语义，单列差异供审查。没有修改 producer、Stage validator、BUY 门禁或历史产物。分页只影响展示，完整计数与输入 fingerprint 保留；这些 API 测试不证明 Stage 实际已消费完整池。

## 证据如何阅读

各阶段记录与作者路径映射见 [证据索引](EVIDENCE_INDEX.md)。

最终交付测试由根 `run_tests.py` 执行：SHA/大小核对 → 全新目录复制 → 清洁环境 → 三个独立 pytest 进程 → JUnit 与实际收集事件核对 → 再核原包与隔离源码身份。它要求预期收集数完全匹配，禁止 skip、deselect、xfail 或 collection error 被计作通过。具体命令、解释器/包版本、结果与边界见 `TEST_RESULTS.json` 及 `evidence/portable_final/`。

初审虽然分别复跑了 85、26、21 项回归且通过，随后仍发现五项 Important，产生七个失败执行：Git 已提交新增、晚期 config 链接、目录 mode、A/HK 行身份与中断恢复。初审 `CHANGES_REQUESTED` 和全部失败证据保留在 `evidence/independent_initial/`，没有覆盖成绿报告。R5 续恢复通过 63 项后，独立复核又发现重复 JSON 字段与原像 metadata 两项 Important（R6/R7）；该检查点、两项失败探针和对应源码保留在 `evidence/independent_revision/`。修订后的关闭结论以 `evidence/independent_final/` 为准。最终包在全新目录实际复跑 **218/218**：发布 112、切换与恢复 76、预选池 30，skip/deselect/xfail/collection error 均为零。重复运行与 24 项 runner 控制检查不累加成新增产品测试数量。

预选池的 21 个支持文件来自固定的、未改写的历史 domain/storage 闭包。完整新 router/service 被实际导入，app 仅执行其精确注册 statement；完整当前 R2 `create_app` 未启动。`evidence/preselection_initial/evidence/PRESERVATION_PROOF.json` 与最终独立证明核对非预选 AST、其他 54 个 `create_app` statement 和经理装配后缀。代码字节保留不等于真实经理业务行为已复验。

`test_support/` 只用于复现。**不要将其中历史文件覆盖到 Mac canonical、API、Stage 或 scheduler**，否则可能再次丢掉已完成的历史 P2 等修改。外部 venv 与非 delta symlink 目标内容也不在文件库存证明内，必须另核运行依赖。

## 实际状态

本轮完成情况、独立审查结论和 GitHub 固定提交由最终交付记录给出。当前没有实机部署、服务启停、业务数据改写、真实 API/UI 或自然时段通过证据。晚间 A=178/HK=100 是 Issue #30 的历史源快照要求，不能用本轮合成测试里的 A=2/HK=100 替代。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。V4/8873 唯一入口、A/HK 合同分离；Vibe 8910 保持原样。
