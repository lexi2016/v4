# Issue #8 · R3-B saved-plan 诊断小修

**范围：仅当前动态 saved-plan 读回的绑定诊断。不是 R3-A、F0 或经理业务恢复。**

输入为 `cf306997359dfadedb162033554c092d740eca33` 的冻结 R1+R2；适用 `workspace.py` SHA256 `ec9c7ba68c93061fa035747ba08c6e71fc7c167c322db2e225963542c72cd2d7`。该前像由远端 Git blob `0ba83d7c628855e073ad62196163d5c42a9bd090` 和该提交的 `writer_freeze_receipt.json` 双重定位。R2 `connect_selection.py` 仍为 `b6c5300172f59b6979dbab15927036ff1ab3599a2adae2b4f0e5a1e4868a6248`，未修改。

已检查 Issue #8 的现有回执及经理相关分支；所见最新 preflight 工具修复为 `a6ade9d919608a1954bbdf367bf16302465808cc`，没有在这些入口找到已完成的同项 R3-B 修复。它保留在原分支，本次不重做工具、不推断 F0 已上传或通过。

## 选择与改动

选择 **readback 修正**，不改 identity。`workspace._readback_plan` 在 `same` 分支已覆盖当前 lanes / owner_chain 等诊断，却漏了 `selection_diagnostics`。将后者加入同一 deep-copy 覆盖列表：一个源码文件，`+4/-1`（其中三行解释注释）。

- owner pin 改变、日期/资格集合/数据 SHA 和 input_identity 不变：仍复用保存计划；`plan_product.status=CURRENT`、`consumed=true`，但返回本次原 reader 结果中的诊断。
- binding 未变：正常复用；原 witness `available_at` 仅更新为本次读取值，不参与 identity，绝不改成网络采集时刻。
- 不调用写入，不重签历史产物；原 plan run_id、product SHA、计划正文和磁盘所有文件保持不变。响应中的 product SHA 指向保存产物，当前诊断是既有动态读回覆盖层，不应对整份响应套用该 SHA。
- 不修改名单过滤、公告分类、业务关系、BUY、历史视图、pre-open 生成/冻结路径。历史视图仍按其原有 read_contract 校验，代码变化可能要求原规则下重新核验，不绕过；本补丁只作用于当前动态 `_readback_plan`。
- 资格变化、错误日期/截止时间、原件破坏仍沿原逻辑拒绝复用或拒绝候选。

## 分工与范围合同

GOAL：修复 R2-P2-STALE-OWNER-BINDING-DIAGNOSTIC，不依赖 R3-A。
WRITER：普通 Chat 研发和交付；原经理 Work 只做 Mac 隔离应用/必要平台适配。
REVIEWER：原 Work 的独立 Reviewer，另进程/身份复验；本交付不冒充已调用它。
ALLOWED_PATHS：运行仅 `v4/manager_research/workspace.py` 的 `_readback_plan`；另为本目录测试、文档、交付工具。
FORBIDDEN_PATHS：其余 R1/R2 业务代码、preflight 工具、collector/publisher、Stage、BUY、F5、Vibe、原发布/配置/数据；禁止抓取、合并、部署。
PASS_SIGNAL：changed-pin 经原 writer/真实临时磁盘 store/原动态读回得到当前诊断，未变 binding 复用，文件不重写，名单不扩大、安全标志不变；独立 Mac 复验另立回执。
STOP_RULE：适用前像漂移或缺实际 R2 app 依赖时停止覆盖并回传精确路径/差异，不以旧源码替代；不升级为宽泛研发，不索要整个项目或原始 plist。

## 内容与证据

`after/api/` 为完整改后源码；`before/api/` 为精确前像；`runtime.patch` 相对 app 根。
`tests/test_r3b_saved_diagnostics.py` 为完整 10 项定向测试；`tests.patch` 相对空交付测试根。
`SOURCE_PINS.json` 和 `MANIFEST.json` 记录字节身份。`logs/` 是本次实际运行日志。
`evidence/changed_pin_witness.json` 来自作者测试真正的磁盘计划写入/读回，**上游资格/行情/材料均合成，不是 Mac 或真实 API 证据**。

原 R1 47/47、R2 27/27 和历史独立结论仅引用既有验收，不重复运行、不相加成新全绿。作者运行环境含历史 reference 依赖；实际交付前像及 R2 scope 与冻结版本一致，但不称整个作者 app 等同 Mac 完整候选。

采用/验收/回退看 `WORK_HANDOFF.md`；R3-A 一次 F0 最小源码需求看 `F0_MINIMUM_INPUT.md`。
PR #9 保持 Draft，Issue #8 保持 Open；这里只交付 R3-B，不宣称经理恢复。
