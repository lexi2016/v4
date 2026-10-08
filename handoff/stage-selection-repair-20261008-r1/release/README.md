# Issue #28 · 发布两项 P1 的最小源码候选

**状态：作者离线回归 PASS；仍为 `NOT_DEPLOYABLE`。** 本目录只修已复现的外部 guard 未冻结，以及双重 link 失败后 active 缺失、claim 无可追溯恢复入口。没有执行真实 launchctl、API/UI、服务启停或发布；没有改活动 plist、业务数据或任何远端。

基线固定为 `00524e9050fe212f87911b56eea1c2db719dd94b` 的已核 SHA 源码切片。完整实际运行包、候选 identity、manifest、旧失败 receipt 的原始字节均不在本切片中；其现场重冻结和部署独立验收仍是 `NOT_RUN`。

**初次源码候选的独立审查发现了一个 Important：installer 在校验 recovery helper 自身 SHA 前执行了其 import。** 独立 probe 与作者 fresh 复现均观察到漂移 helper 的顶层 marker 先执行、之后才报错。初次候选已撤回；本目录现为修正后的第二轮候选，保留初次 installer、probe 与红灯结果，不把先前 58 项自验通过当作该缺陷不存在的证据。

## 1. 三个产品文件及其身份

| 文件 | 原 SHA-256 | 候选 SHA-256 |
|---|---|---|
| `blocked_candidate_ops/api_candidate_install_r2.py` | `b326d2f68843e1673169bc8d6e36965786f513e19ef2671a64d113284e944200` | `b348859aa5a0e3e94ecb1bc6b431590adc91c7c3346039ea82543f4487fe561e` |
| `blocked_candidate_ops/api_candidate_recovery.py` | `d42975f459858ed697805c3043090a82102cd2e0d6c28eef07bb4c440e955fbb` | `4db1f38580d972ffe40c08a54e54c671023d18391f854f0b2f09d481e311ce24` |
| `external_guard_reference/hk_calendar_candidate_cutover.py` | `264ad2d3f5535e17f6e7471dc12d7e00452104b505795857e9f0637c0a29e816` | `932c1d1e4d6111faba8cee92f9a3ed0014018f71f986c4237346974260e5e69d` |

完整前后像在 `before/` 与 `after/`；`minimal.patch` 的路径相对源码切片根，包含这三个产品文件，以及两个原测试成功 scope 的必要 pin 增补。没有把整个外部 HK guard 改成新的部署框架；仍仅由 API helper 使用其中的 CAS/claim 原语，其他 HK 命令未运行。

### 外部 guard 精确绑定

安装和恢复共同检查新的精确 guard SHA。恢复 identity 必须显式包含绝对 `guard_path` 与 `guard_sha256`；旧无 pin identity 被拒绝。最终 plan 的 `writer_artifacts` 与独立 review scope 都必须绑定同一对字段；原 19 项 scope 保留，变为 21 项，receipt 与 scope 必须完全相等。

载入时通过一个不跟随末级 symlink 的 regular-file descriptor 读取 guard，检查该 byte buffer 的 SHA，然后直接编译该 buffer。不会在检查后重新从路径执行模块或读缓存 bytecode。installer 自己执行 raw guard 校验，不借用未核对的 recovery helper。需要执行 recovery helper 的所有入口均先匹配固定 `recovery_helper_sha256`，再从精确 `RECOVERY` 路径编译同一份已核 bytes；不使用 `sys.path` 搜索结果或已有 import cache。测试在检查后立即把磁盘文件换成带可见副作用的其他模块；安装/恢复均只执行已检查字节，替换模块不执行。

### 可追溯 claim 与不覆盖恢复

候选 link 和自动恢复 link 同时抛普通 `OSError` 时，异常现在携带 active 路径、claim 路径与 SHA、候选 SHA、失败阶段、两次错误类型、drift receipt 路径与 SHA。安装和恢复 CLI 会保留结构化 `claim_recovery` 信息。

在移动 active 前先写入并 fsync 一份绑定目标/原 SHA/候选 SHA/claim 路径的 `CLAIM_RESERVED` receipt；该写入失败时 active 保持原位。后续失败 receipt 无法落盘时，异常仍给出已经保存的 reservation receipt。真实 POSIX 子进程在 rename 后立即退出的测试证明：没有 Python 错误回传也有现存 receipt 与 claim 可恢复。此测试针对进程中断，**没有认证断电或文件系统损坏的持久性**。

新增恢复参数只接受精确绑定的已保存 receipt；验证私有 claim 目录、regular file、SHA、绝对规范路径和 approved API phase 后，再用 exclusive link 发布验证过的字节快照。已存在或插入的其他 active 文件、目录及 dangling symlink 均保留。claim 本身保留；多次失败不覆盖旧 claim 或 receipt。若失败发生在候选→基线的回滚 CAS，先还原 candidate claim，再进入既有受保护的 candidate→baseline 状态机；不会 bootstrap candidate。

## 2. 新 operations 目录与旧 app candidate 的区别

候选 installer 的 `R2` 现在指向新的 operations/evidence 目录：

`/Users/lexi/Desktop/学习/agents调试/V4_A_POOL_SOURCE_FIX_20261008/r2-issue28-release-p1-20261008`

guard 应作为此新目录内的冻结依赖，与两 helper 同目录；**不要覆盖原 HK 包的共享 guard**。原 `.../r2` operations 目录、旧计划和失败记录保持只读。

本源码中的 `CANDIDATE` 仍指向旧 `a-preselection-source-r2-20261008-api` app candidate，用作现有 app/业务 canary 的只读身份参考。这不等于该旧候选获得部署许可，也不等于已经构建新的实际 app 包。新的 identity 必须加入 guard pin，其 hash 已不同于旧 identity；因此代码中旧的完整包 identity/manifest 期望值不能凭空满足新包的验收。`plans/release_candidate_plan.json` 是本次**源码候选**的冻结计划，明确不是可执行的 `r2_candidate_finalplan.json`。

原独立失败证据继续保留：receipt SHA `f1ec7528fea04ab2d26fbb6f7d68f61cabbceae82a187cca9cc6443d0f3d92de`，`REVIEWED=FAIL / DEPLOYABLE=NOT_DEPLOYABLE`，来源为冻结交接 README 第 5 节。本切片没有该 receipt 原始字节，未伪造或覆写它。

## 3. 实际测试与诚实边界

运行环境：Linux x86_64、Python 3.14.7；实际解释器、UID、命令和日志 SHA 见 `RESULTS.json`。

| 验证组 | 基线 | 候选 |
|---|---:|---:|
| 原 install 9 + recovery 17 个行为用例，临时 fixture 迁移 | 26 PASS | 26 PASS |
| 针对两项 P1 的新回归 | 12 FAIL | 12 PASS |
| 新增具体边界：load race、进程退出、receipt 失败、双回滚 link 失败、插入 writer、symlink/FIFO/路径、保留多次 claim | — | 20 PASS |
| 独立审查新增：helper load-order、direct review、路径 shadow、检查后换 helper | 初次候选 5 FAIL | 第二轮 5 PASS |

**原 26 项是原行为断言迁移到临时 fixture 运行。** 它们原本依赖未提供的 Mac 绝对路径及完整 app 包。harness 只重定向路径，以真实临时文件和其真实 SHA 构造最小 package fixture，禁用所有真实 subprocess/service 调用；没有 mock verifier、inventory、guard import 或 CAS。缺失的旧失败 receipt 仅在 fixture 内用显式 `REVIEWED=FAIL` 合成。两处成功 review scope 补充 guard_path/guard_sha256：`test_exact_review_scope_and_hash_are_required` 与 `test_passing_review_must_match_frozen_candidate_scope`。原失败 gate 断言保留。

最终第二轮作者自验合计 63 PASS（26 + 12 + 20 + 5）。独立原 probe 对修正后的 installer 报告 `drifted_helper_executed_before_rejection=false`；其作者重跑结果不替代不同身份 Reviewer 的复审。新的 helper-path 检查后替换测试验证同一 checked bytes 被执行；原 guard race 测试也明确断言安装与恢复两个读取分支各发生一次实际替换。

这些合成 fixture 的 `PASS` receipt 只供测试状态机，不能作为独立 review。完整原 Mac 包验收、1013 文件 app inventory、业务 API canary 和现场发布均未重跑。

保留的初次新增边界测试日志有 1 FAIL：第二次失败正确保留两份 claim，但测试 helper 错误地断言目录总共只有一份。只修正 helper 为“本次新增恰好一份 claim”，产品代码未因该失败改变；最终 20 PASS。基线的 12 项真实 P1 FAIL 日志同样保留。

从本 handoff 根重跑交付文件：

```bash
RELEASE_SOURCE_ROOT=delivery/release/before references/work/test-venv/bin/python -B delivery/release/tests/run_original_suites.py
RELEASE_SOURCE_ROOT=delivery/release/after references/work/test-venv/bin/python -B delivery/release/tests/run_original_suites.py
RELEASE_SOURCE_ROOT=delivery/release/before references/work/test-venv/bin/python -B delivery/release/tests/test_release_regressions.py
RELEASE_SOURCE_ROOT=delivery/release/after references/work/test-venv/bin/python -B delivery/release/tests/test_release_regressions.py
RELEASE_SOURCE_ROOT=delivery/release/after references/work/test-venv/bin/python -B delivery/release/tests/test_release_boundaries.py
RELEASE_SOURCE_ROOT=delivery/release/after RELEASE_INSTALLER_SOURCE=delivery/release/rejected_review_round1/api_candidate_install_r2.py references/work/test-venv/bin/python -B delivery/release/tests/test_recovery_load_order.py
RELEASE_SOURCE_ROOT=delivery/release/after references/work/test-venv/bin/python -B delivery/release/tests/test_recovery_load_order.py
```

第三条预期 exit=1、12 FAIL；第六条预期 exit=1、5 FAIL，验证被独立审查拒绝的初次 installer。它们是保留缺陷的红灯证据。换机器时替换解释器路径为可用 Python 3.12+；已执行的正式作者结果只声明上述 Python 3.14.7 环境。不要直接对 Mac 真实目录运行两个原测试文件；使用此隔离 harness。

## 4. Luna Max 现场最小应用与回退合同

1. 先只读重新核实际 8873 owner、active plist、app manifest/source 和经理台版本。前像不匹配时在**新的**独立候选目录适配，不覆盖旧 R2、活动 release 或并行修改。根据届时实际 owner 决定是否重建 app candidate；本交付未执行这一步。
2. 在新的 operations 目录落三个 helper/guard 的冻结后像，复核上述 SHA。保留 guard 在新目录内；不要把修复写回原共享 HK guard。离线运行交付的临时 fixture；由不同身份 Reviewer 审 source 与实际候选。
3. 本地重新冻结 recovery identity、staged plist、完整 app manifest/inventory、canary、plan 与 review scope；实际路径、identity/manifest SHA、installer `EXPECTED` 必须一致。凡更改 helper 的现场路径或 pin，重新计算 helper SHA 并重新 review。guard 的修复字节不变时其 SHA 必须仍为本表值；recovery helper 改字节时还必须同步 installer 内的固定 `recovery_helper_sha256`，再重新冻结 installer SHA。完整 binding 缺失时维持 `NOT_DEPLOYABLE`。
4. 实际批准发布前，按既有具体服务合同检查精确 label 与 8873，执行 `review-check`、`verify`、`preflight`。这些现场动作及之后安装/启动不属于此次执行记录。源码回退是对独立候选应用 `minimal.patch` 的反向变更；不得将旧有两个 P1 的 helper 作为获批部署回退工具。运行期业务回退仍由新的受保护 recovery helper 还原已冻结基线。
5. 若未来遇到双 link 失败，保存 stderr 中完整 `claim_recovery` 与其指向 receipt，复核 receipt SHA。active 存在时保持原样，不删除、不覆盖他人的文件。active 确实缺失时，后续已获授权的 Writer 可使用如下明确命令；helper 仍会检查精确 label 缺失、端口空闲、身份及 claim：

```bash
python "$OPS/api_candidate_recovery.py" recover-baseline \
  --identity-json "$OPS/r2_candidate_identity.json" \
  --claim-receipt-path "$CLAIM_RECEIPT" \
  --claim-receipt-sha256 "$CLAIM_RECEIPT_SHA256" \
  --confirm RECOVER_API_CANDIDATE_TO_BASELINE_R2
```

其中 `OPS` 必须是新 operations 目录；receipt 路径/SHA 必须来自那次失败或中断前已冻结的 reservation，不按“最新隐藏文件”猜测。receipt 与 claim 无法互证时保留 `CANNOT_CONFIRM` 并交实际 owner 检查。若前次已恢复 active，再传 claim 参数会拒绝覆盖；改用普通恢复前应重新核 active 确为冻结 baseline/candidate。所有 claim 与旧失败 receipt 留作证据。

**交付分层：源码候选/作者离线测试已完成；独立部署验收、实际 owner 重冻结、集成、部署、API/UI、自然时段均未由本作者完成。** `RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
