# V4 Issue #28 修复交付 · 2026-10-08 R1

**源码候选与离线回归已完成，独立源码审查的两项 Important 已按精确 SHA 复核关闭。
当前结论为 `PASS_WITH_DEPLOYMENT_GAPS`；实际发布仍为 `NOT_DEPLOYABLE`。**

本包供 Luna Max 在 Mac 的真实 owner 上适配、冻结和验收。它不是完整运行 app，也不是
已批准的安装包。实际 caller/运行依赖、真实 HK 来源、完整应用、Mac 服务、8873 API/UI
以及自然时段证据仍需现场闭环；本轮没有切换 release、启停服务、补采或改写业务数据。

## 1. 固定输入与交付入口

- 工单：[lexi2016/v4 #28](https://github.com/lexi2016/v4/issues/28)。
- 冻结输入：[`00524e9050fe212f87911b56eea1c2db719dd94b`](https://github.com/lexi2016/v4/tree/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/stage-selection-issues-20261008)。全部 27 份输入已核对字节数、SHA-256 和 Git blob SHA-1。
- 本轮独立分支：`chat/issue28-repair-20261008-r1`；目录：`handoff/stage-selection-repair-20261008-r1`。
- GitHub 交付文件身份：[DELIVERY_MANIFEST.json](DELIVERY_MANIFEST.json)；产品前后像与 owner 映射：[BEFORE_AFTER_SHA256.json](BEFORE_AFTER_SHA256.json)。清单不包含自身，提交后生成的同步记录随下载包另附。
- 未完成事项和本机逐项验收：[OPEN_ITEMS_AND_LOCAL_ACCEPTANCE.md](OPEN_ITEMS_AND_LOCAL_ACCEPTANCE.md)。

原冻结目录及并行工作保留。GitHub 提交只增加本次 handoff；本轮没有 merge、deploy 或 issue 状态变更。
最终同步 commit 和远端逐文件读回结果见下载包根目录另附的 `GITHUB_SYNC_RECEIPT.json`；该记录在提交后生成，不在 GitHub 源码清单内。不要用 branch 名替代精确 commit。

## 2. 已实现的修复

| 批次 | 具体结果 | 交付 |
| --- | --- | --- |
| A 股 09:25 竞价 | 两个不同 owner 的 builder 保留真实昨收；selector 不再把缺值写成假 0；最终字段避免被通用 last/open 投影覆盖 | [auction/README.md](auction/README.md)、两个 owner 的补丁、3 份不同后像 |
| HK 日期与来源 | 在原运行 monolith/ops 上绑定目标、价格、资格三日期；复用原 calendar/reader 验来源链；坏 HK 单独 CANNOT_CONFIRM，所有 A lane 继续物化且旧 HK 槽保留 | [hk/README.md](hk/README.md)、2 文件主补丁及前后像 |
| 发布两项 P1 | guard 路径/SHA 纳入安装、恢复、identity、plan/review；核验后执行同一份字节；双 link 失败留下可核验 claim/receipt 并能受保护恢复 | [release/README.md](release/README.md)、3 产品文件与2原测试的补丁 |
| 预选池读取 | 复用既有已审修复；新增 HK fallback、损坏来源隔离、完整计数与分页指纹回归 | [pool/README.md](pool/README.md)；本批无新增 pool 产品修改 |

### A 股取值、持久化与排名

合成 `prev_close_price=100 / auction_price=105` 已经经过真实冻结 adapter、selector、
历史 store/consumer 和精确 GET route 的 HTTP 测试，读回涨幅 **5%**。有效平盘仍为 0；
缺失、非正值、非法或非有限昨收输出 null，并保留明确缺值原因。

所验证的 store 在 SHA 绑定的 manifest 中保存完整 `selection_envelope`，固定列 CSV 只是投影；
所以本次不扩 CSV/schema/codec，也未凭空增加 API 改动。当前运行 owner 的完整 store/consumer
尚未提供，Luna 仍须确认同一持久化合同。

评分公式、Top10 规则与 tie-sort 没有改写；补回真实 gap 后，新结果的**分数和排名会改变**。
例如三行合成 95/100、105/100、100/100 的分数从旧版均为 50.25，变为 0.25、100、50.25。
新结果使用新 run identity；同槽冲突校验保留，不能用本补丁覆盖已存的 10/8 结果。

### HK 仍需补齐的实际链路

10/8 的合法合同是目标 **20261008**、HK securities 价格日 **20261007**、
HK Connect 资格来源日 **20260930**。三者由原 calendar 校验，日期或来源无法证明时保持失败状态。

这两个源码文件单独部署不能解除现场 HK 阻断：实际 scheduler caller、共享 owner、calendar/store
加载身份和真实 10/7 价格/9/30 资格三件套均未闭环。包中只读 canonical 支持文件不能冒充
当前 owner，合成 capture 不能作为历史 PIT。保留的旧 HK 槽仍可能无法通过严格 Stage 校验；
本轮只证明拒绝它不会阻止有效 A 写入。

### 发布失败与审查发现的修正

guard 与 recovery helper 均先核精确路径和 SHA，再执行**同一份已核字节**，避免检查后换文件、
import cache 或同名模块 shadow。新的 review scope 为原19项加 guard_path/guard_sha256，共21项。

active 移走前先写入 `CLAIM_RESERVED` receipt。候选 link 和自动回退 link 双双失败后，恢复入口
能用绑定的 receipt 找到并核验原 claim；通过 exclusive link 发布已核快照，不覆盖其他 writer
的文件、目录或 dangling symlink。真实子进程在 rename 后退出的测试已执行，但这不是断电耐久性认证。

原 R2 `REVIEWED=FAIL / NOT_DEPLOYABLE` 保留。新 `release/plans/release_candidate_plan.json`
只是源码候选计划，不能直接作为现场 finalplan：当前完整 identity、inventory、manifest、
路径 pin、canary 和新独立部署 review 必须重新冻结。

## 3. 实测、独立审查与证据

最终候选的作者/协调方离线测试共 **191 个通过实例**，按 owner 或测试组计数，重复复跑不累加，
也不包含旧历史收盘的既有51/70通过数。

| 验证组 | 保留的反证 | 最终 after |
| --- | --- | ---: |
| A 竞价 canonical builder | 24 FAIL / 7 PASS | 31 PASS |
| A 竞价实际 Stage builder | 24 FAIL / 7 PASS | 31 PASS |
| HK 三日期/来源/A 隔离 | 原 before：3 FAIL / 2 PASS；被拒首版 reuse：8 FAIL | 55 PASS |
| 发布原 install/recovery 行为 | before 26 PASS | 26 PASS |
| 发布两项 P1 | before 12 FAIL | 12 PASS |
| 发布故障边界 | 首次1项测试辅助断言错误保留原日志，修正后通过 | 20 PASS |
| recovery helper 载入顺序 | 被拒首版 5 FAIL | 5 PASS |
| 预选池读取 | 复用7例＋新增4例 | 11 PASS |

环境为 Linux x86_64、Python 3.14.7、pytest 9.1.1；API 测试使用现成 FastAPI 0.142.4、
Starlette 1.7.0、httpx 0.28.1、anyio 4.15.1。保留既有 Starlette TestClient 弃用警告，未升级依赖。
Mac Python 3.14.6、完整 `create_app` 和实际网络服务均 NOT_RUN。

独立审查记录分两部分保存，不覆盖初次失败：

1. [初次 REPORT.md](verification/independent_review/REPORT.md)：独立复跑182个当时已有实例全部通过，仍通过自写 probe 发现2项 Important；原结论 CHANGES_REQUIRED 保留。
2. [定向 CLOSURE.md](verification/independent_review/CLOSURE.md)：针对最终 installer `b348859…` 和 HK ops `e8f412a…`，独立原 probe、5项 helper 测试、8项 HK reuse 测试和6场景真实 CLI/store probe 通过。HK probe 验证全部6个 A 产物均写入，包括 HK 后面的 WeChat A lane；旧 HK artifact/receipt/manifest entry 保留。结论仅关闭这两项源码缺陷。

另有一个协调方发现的低级 runner 问题：相对输出目录导致 JUnit 计数为空，现已将输出路径先转绝对路径；
同命令复跑得到31项准确计数，见 [HARNESS_RELATIVE_OUTPUT_FIX.json](verification/HARNESS_RELATIVE_OUTPUT_FIX.json)。
产品字节未因 runner 修正改变。

四个 owner 主补丁及一个审查证据增量均已正向/反向重放到精确 SHA，见
[FINAL_PATCH_REPLAY.json](verification/FINAL_PATCH_REPLAY.json)。发布最终打包字节再次从包根运行63项通过，
见 [release_packaged_runs](verification/release_packaged_runs/)。

## 4. 解压后的离线复跑

以下命令从本 README 所在目录运行，使用已具备上述依赖的 Python；包中不携带 venv。
输出写到临时测试目录，所有业务输入均为合成 fixture。`hk --mode all` 会保留预期红色 before。
子目录 README 中的 `/workspace/...` 是本轮原始命令记录，换机器以此处的相对入口为准。

```bash
python -B verify_delivery.py
python -B verification/replay_patches.py
python -B auction/run_focused.py --owner canonical --phase after --output /tmp/issue28-auction-canonical
python -B auction/run_focused.py --owner active_stage_reference --phase after --output /tmp/issue28-auction-stage
python -B hk/run_tests.py --mode all --log-dir /tmp/issue28-hk
RELEASE_SOURCE_ROOT="$PWD/release/after" python -B release/tests/run_original_suites.py
RELEASE_SOURCE_ROOT="$PWD/release/after" python -B release/tests/test_release_regressions.py
RELEASE_SOURCE_ROOT="$PWD/release/after" python -B release/tests/test_release_boundaries.py
RELEASE_SOURCE_ROOT="$PWD/release/after" python -B release/tests/test_recovery_load_order.py
python -B pool/harness/run_isolated_pool_tests.py
```

不要直接运行 `release/after/blocked_candidate_ops/test_*.py`：它们是原 Mac 专用测试，
本包通过上面的临时 fixture harness 迁移行为断言。`verify_delivery.py` 只核本包完整性，
不会证明当前 Mac 前像、服务或独立部署审批有效。

## 5. Luna Max 的下一步

Luna Max 继续担任 Mac 唯一 Writer；实际部署由另一身份 Reviewer 验收。本包已经完成可交付的源码工作，
剩余现场顺序如下，详细逐项条件见 [OPEN_ITEMS_AND_LOCAL_ACCEPTANCE.md](OPEN_ITEMS_AND_LOCAL_ACCEPTANCE.md)。

1. **先冻结当前 owner。** 分开核 canonical、API、Stage、pool scheduler 与外部 guard 的真实加载根、路径、SHA；保留经理台R3、Vibe8910和现有并行修改。只有精确 before 匹配的隔离候选可直接应用相应补丁；漂移前像只移植最小差异。
2. **先关闭发布门禁。** 在新 operations 目录保留本批 guard，重建完整 identity/manifest/plan/review；旧 R2 的 FAIL 不能被本包自验替代。恢复 helper 若变更字节，installer 内固定 helper pin 也必须同步并重新 review。
3. **在完整 owner 验证 A 与 pool。** 跑100/105、缺昨收、旧 run只读、全量分页指纹；既有 pool 修复按当前R3小改动适配，不用旧大 app.py 覆盖当前版本。
4. **接通 HK 原 caller 和真实来源。** 三日期、run/artifact/manifest/receipt/SHA/capture 均通过后，使用新目录/新 run_id 做单阶段 canary；旧输入绑定失败仍是 null 和缺失 run，不是真0选。
5. **分层读回。** 记录集成、Mac、独立审批、发布、API、重载UI和自然时段状态；手动/恢复运行不升格为自然运行。

本轮继续开放的 P2 包括 A 缺失6–7只来源的逐证券原因、研究/新闻数值 quality 合同和权威归属、
不可变逐run执行证据、8/25与9/30与10/7历史来源缺口，以及原历史校验器的三项已知P2。
原始证据不在此包中，不能用填0、字段别名、补写capture或重标状态消除这些缺口。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
