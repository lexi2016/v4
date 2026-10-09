# R3 最终验证证据

## 结论与固定源码

Writer 与独立 Reviewer 分别执行完整 `tools/run_checks.py`，最终均为 **352 passed / 0 skipped / 0 failed**。两轮都重新生成 695 行合成输入的原 runner/store → API reader/consumer → 当前 App/组件 SSR 全链；不是复用 R2 的 275 项或某个旧 UI 页面测试。

最终 SOURCE_MAP SHA256：`3ec3e7774119bd106185c03be0b5c572b6fe2ca4148b93379d8b116a72994457`。

- Writer：[evidence/final/RESULTS.json](evidence/final/RESULTS.json)，2026-10-09T12:32:34.540327+00:00 至 2026-10-09T12:33:13.903031+00:00。
- 独立复跑：[evidence/independent/RESULTS.json](evidence/independent/RESULTS.json)，2026-10-09T12:33:32.310641+00:00 至 2026-10-09T12:34:10.756714+00:00。
- 环境：Linux、Python 3.12.14、Node 24.19.0、Vue/compiler/server-renderer 3.5.13；没有访问或启动 Mac 运行环境。

| 套件 | 固定期望 | Writer | 独立复跑 | skip |
|---|---:|---:|---:|---:|
| Stage 原业务及工具回归 | 148 | 148 | 148 | 0 |
| API 原 reader/consumer 回归 | 82 | 82 | 82 | 0 |
| 适配/权限/来源/测试门禁 | 50 | 50 | 50 | 0 |
| 原 Vue 测试语义 | 45 | 45 | 45 | 0 |
| 当前 App 编译/SSR/事件接线 | 27 | 27 | 27 | 0 |
| 合计 | 352 | 352 | 352 | 0 |

Stage/API/adaptation 的真实 JUnit testcase、结果与声明同时核对；Vue 的 tests/pass/fail/skipped/cancelled/todo 全部核对。期望数量由 SHA 绑定的 TEST_EXPECTATIONS 固定，不能按当次结果自行降低。原 Vue 45 中有 8 个旧 App 函数抽取测试改为当前 App 的真实编译与 SSR，语义和数量保留；legacy_presentation 文件字节未改。原 driver fixture 只调整合成包搭建，不放宽生产 policy。

## 实际反例与修复

1. **只读 API 的真正非 root 复现。** 原 R2 在 EUID 65534 子进程里因 candidate/stage_center 下无法建临时文件而 COPY_FAILED / Errno13；同一源、新目的目录用 R3 返回 CANARY_PREPARED，源 bytes/mode/uid/gid、旧 partial inventory 不变，最终 0555/0444 恢复。Writer 和独立 Reviewer 各自重新执行；见 [NONROOT_API_REVIEW.json](evidence/review/NONROOT_API_REVIEW.json) 及 tool_red_green 下原始收据。Linux 使用局部 user namespace，不用 root 可绕过 DAC 的结果冒充非 root 成功；Mac 普通用户路径不依赖 unshare。
2. **链接精确处理。** 已知内部链接保留；已知外部链接省略并记录身份；未知链接、内部逃逸、映射文件链接、改指另一 release、源复制过程中变化均拒绝。UI 仅扫描 apps/web，保留其现有文件，根 pytest 残留排除。
3. **外部链接分类读取。** 最初 os.walk 即使 followlinks=False 也可能在目录分类时 stat 目标；已改为显式目录描述符/scandir/lstat 遍历。新增反例覆盖整个 prepare 的 Python 文件系统 API 调用；独立探针亦通过，见 [EXTERNAL_LINK_API_REVIEW.json](evidence/review/EXTERNAL_LINK_API_REVIEW.json)。容器 ptrace 禁用，native strace 未运行，未把 API 探针写成原生系统调用追踪。
4. **manifest 删除绕过。** 独立审查先真实 prepare，然后移走 manifest、增加非 mapped 依赖；中间版错误地执行 owner 并生成 HK10。最终版同一反例在输出创建/owner 前报 CANDIDATE_SOURCE_MANIFEST_REQUIRED。修前记录 [manifest_bypass.json](evidence/review/manifest_bypass.json) 与修后 [MANIFEST_BYPASS_FIXED.json](evidence/review/MANIFEST_BYPASS_FIXED.json) 均保留。
5. **少跑/skip 门禁。** 真实微型 pytest/Node 子进程全部退出 0，但少跑或 skip 时旧工具写 PASS；最终每套均拒绝。另独立核验 19 项格式探针，包括 JUnit 声明不符及 TAP 缺失/歧义。
6. **当前 UI RED/GREEN。** 同一 27 项测试对本次实际 before 是 8 pass / 19 fail / 0 skip；after 是 27 pass，原45另全过。两个独立源 patch replay 都从“组件缺失”的真实 before 起步，3 个 after SHA 全部一致。经理入口测试证明 wiring；其完整业务页面不在该 stub 范围内。

发现后的中间 350 项通过收据只留在隔离工作区，最终包只以当前 352 项作为最终基线；原 R2 包和 Mac 原失败回执仍在原固定 commit 中保存。

## 同 run 合成链

最终 fresh fixture 的 run 为 `run-2c40a8d057e1beffde847ab1`、date 20261009、STAGE_0930_0935、HK_CONNECT；选中10、行情695/695是**明确合成外部行情 I/O**的测试数据。它检验原计算/写入/读回/页面，不代表用户真实695行都已取得行情。

API 检验 OWNER_HISTORY_SHA_BOUND 与 BOUND_TO_VERIFIED_SELECTION_TRIO；页面从同一 workbench 展示“已计算10只”、覆盖/缺口、名单日20261008、真实资料采集时间标签、研究限制和 CURRENT_DAY_RESEARCH_REPLAY / RECOVERY。natural_verified=false，未把A缺结果换成HK身份。断言见 final/full_chain 和 independent/full_chain 的 api_readback_assertions.json、vue_readback_assertions.json；两份 SSR HTML 一并保留。没有上传合成 raw 全树或用户真实市场数据。

App/组件直接编译生产 after；shell 状态、动作和其他 view 是显式 fixture/stub。API 投影使用已取得的原函数，未测试当前 HTTP 服务。两种测试边界都写入机器收据。

## 已验证与未运行项

| 层级 | 本轮状态 |
|---|---|
| 当前 App/runtime 前像、组件缺失事实 | 固定 Mac 附件/记录；字节与 Git blob 独立核对 |
| Stage16/API2 与 R2 after | 18/18逐字节未变；Mac before匹配证据保留 |
| 候选准备/权限/链接与源变化反例 | Linux真实文件系统/非root进程验证通过 |
| 完整源码及合成原链 | Writer与独立Reviewer各352通过 |
| UI当前源码最小patch、R2包源码delta | apply成功，after SHA逐项一致 |
| Mac真实prepare、真实HK PyTDX四文件canary | NOT_RUN |
| 现役API HTTP、完整UI Vitest/vue-tsc/Vite build、重载浏览器 | NOT_RUN |
| 既有发布链/服务部署 | NOT_RUN |
| 自然时段自动执行 | NOT_RUN，手动/合成不标NATURAL |

没有新必需前像请求。实际依赖树通过 prepare 保留；未提供的当前 shell、API factory/config 和真实ExHQ源码不被冒充已读。若实际执行产生特定接口冲突，其精确收据决定后续代码修复范围，不预先制造API拆分前置条件。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
