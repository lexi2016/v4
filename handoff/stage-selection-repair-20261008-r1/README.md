# V4 Issue #28 — 源码修复候选 R1

**本包完成 A 股竞价昨收、HK 物化双日期与来源绑定、两项发布 P1 的源码候选，复用已冻结的 A 预选池读取修复。状态为候选源码验收；尚未集成、部署或证明实际阶段恢复。**

任务：[Issue #28](https://github.com/lexi2016/v4/issues/28)。输入固定于
[`00524e9050fe212f87911b56eea1c2db719dd94b`](https://github.com/lexi2016/v4/tree/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/stage-selection-issues-20261008)。
27 个原始源码／测试文件均已核 SHA256、字节数和 Git blob；完整原件仅作为
`test_support/frozen_repo/` 中的测试支持保留，不充当可部署应用。

## 交接入口

| 目的 | 文件 |
| --- | --- |
| Luna Max Writer 适配、独立 Reviewer 验收及回退顺序 | [LUNA_MAX_NEXT_STEPS.md](LUNA_MAX_NEXT_STEPS.md) |
| 尚缺的实际 owner／来源证据、P2 与历史边界 | [OPEN_ITEMS.md](OPEN_ITEMS.md) |
| 独立源码审查及拒绝作出结论的范围 | [review/INDEPENDENT_REVIEW.md](review/INDEPENDENT_REVIEW.md) |
| 全包文件清单与 SHA | [FILE_MANIFEST.json](FILE_MANIFEST.json) |
| 全部源码前后身份及复用身份 | [SOURCE_CHANGES.json](SOURCE_CHANGES.json) |
| 本包实际执行的六组命令与原始输出 | [evidence/packaged_focused/results.json](evidence/packaged_focused/results.json) |
| 27 原件与四份补丁的正反向核验 | [evidence/PATCH_ROUNDTRIP.json](evidence/PATCH_ROUNDTRIP.json) |

## 修复内容和结果

### 1. A 股竞价昨收与涨幅

根因是两种 owner 的 builder 未将 `prev_close_price` 传给 09:25 selector；
通用卡片的 last/open 回退还会覆盖缺失状态，使未知涨幅表现成 0。
本包分别修改 canonical 与 active Stage 的 builder，并提供明确映射的共同 selector 后像。
缺失、非有限数或非正数昨收输出 `null` 涨幅与具体原因；真实昨收 100、竞价 105
得到 5%，100／100 仍是合法 0%。

持久化核查修正了初始疑点：V2 字段集已经包含 `current_change_pct`；正常发布的
12 列历史 CSV 配合 `manifest.selection_envelope` 保存完整行，receipt 绑定 manifest SHA。
真实 `SelectionStore` 发布／验证读取及 consumer 回归证明字段完整保留，篡改会拒绝。
因此 schema、codec 和历史 CSV 格式保持原字节。

评分公式和系数没有修改，恢复真实输入会改变分数与排名。合成控制中，昨收 100、
竞价 95／105／100 的分数由 50.25／50.25／50.25 变为 0.25／100／50.25。
已有合法昨收的直接 selector 控制，其完整 envelope 前后 SHA 相同。
**真实 171 行重新排名 NOT_RUN；没有重写 10/8 已存结果。**

完整差分、后像、计分与持久化证据见 [auction/README.md](auction/README.md)。

### 2. HK 行情日期、资格日期与 provenance

实际 producer 的单文件实现不能表达行情日和资格日分离，也没有完整投影严格
Stage 验证器需要的来源绑定。为该实际参考版本新增独立可选参数：
`--hk-signal-date` 与 `--hk-eligibility-source-date`；A 日期合同独立保留。
默认等日路径保持兼容，分日路径向原共享 reader 传递相应资格日期。

回归使用目标日 20261008、HK 行情日 20261007、资格日 20260930，验证真实临时
三件套发布／读回、来源 manifest/receipt SHA 及原严格 validator；错误日期、
缺 provenance、过晚捕获与篡改均被拒绝。来源捕获时间取原记录，不补造时间。

**实际 scheduler 参数接线、真正加载的 shared HK 模块及 producer store 依赖未随切片提供。**
本次 canonical 支持模块测试不能证明实际加载身份；10/7 原始行情可用性也仍未证明。
因此仍为 `CANNOT_CONFIRM_ACTIVE_DEPENDENCY_CLOSURE`，两个候选文件不可直接激活。

完整差分、后像与缺失输入见 [hk/HK_ROOT_CAUSE_AND_CANARY.md](hk/HK_ROOT_CAUSE_AND_CANARY.md)。

### 3. 发布流程两项 P1

安装、恢复 identity、最终计划及独立审查 scope 现在都绑定 guard 的精确路径和 SHA。
加载器读取普通文件并校验，然后编译执行同一个字节缓冲区，避免哈希后重新打开文件
或命中未绑定字节码。原 19 字段 scope 被拒绝，新合同为 21 字段。

安装／回滚的双 link 失败现在保留结构化 claim 身份和绑定回执；恢复会核回执、
服务、目标路径及冻结 SHA，以独占方式恢复快照。已有或插入的他人 active 路径
不可覆盖；恢复再次失败保留原可重试回执。回执写入也失败时仍保留 claim 路径及 SHA。

这涉及外部共享 guard、installer、recovery 以及必要的测试 pin 迁移。
**旧 final plan、旧 identity 和旧失败审查不被重新标记为可用。**
Mac Writer 需从届时真实字节重建 identity／helper pins／plan 和完整 21 字段 scope，
再由不同 Reviewer 出具精确包审查。Linux 合成测试不授权实际安装。

完整差分、后像与合同迁移顺序见 [release/RELEASE_REPORT.md](release/RELEASE_REPORT.md)。

### 4. A 预选池读取：复用已有修复

复用 [`4ad7cc52257b49470b3004ebfee9649af43189dd`](https://github.com/lexi2016/v4/tree/4ad7cc52257b49470b3004ebfee9649af43189dd/handoff/a-preselection-source-20261008)
中已经完成的修复，本批没有新增第二套业务实现。新增四场景回归验证精确日期 HK
fallback、分页／完整计数、重复读取稳定以及 manifest／receipt 篡改拒绝，始终保留
有效本地 A，来源三件套原字节不变。真实经理台 R3 或更新 owner 仍需按实际前像适配。

完整说明、冻结引用和隔离路由支架见 [pool/README.md](pool/README.md)。

## 已执行验证

环境是 **Linux x86_64、CPython 3.14.7、pytest 9.1.1**；完整版本记录见
[evidence/TEST_ENVIRONMENT.json](evidence/TEST_ENVIRONMENT.json)。目标 Mac 3.14.6 未执行。

| 测试批次 | 未修改前像 | 最终交付后像 | 实际覆盖范围 |
| --- | --- | --- | --- |
| 竞价 canonical | 18 FAIL / 6 PASS | **24 PASS** | 21 个真实模块支架用例 + 3 个局部 API 投影 AST 用例 |
| 竞价 active Stage | 18 FAIL / 6 PASS | **24 PASS** | 同一 24 场景，在另一种 builder 前后像执行 |
| HK 双日期与来源 | 针对性 4 场景：2 FAIL / 2 PASS | **19 PASS** | 实际参考 producer、原共享支持模块、临时存储及严格 validator |
| 发布原有测试 | 26 PASS | **26 PASS** | 保留原 17 recovery + 9 install 断言，使用明确合成的包夹具 |
| 发布新增 P1 测试 | 25 预期 FAIL | **25 PASS** | guard 字节绑定、竞态、双 link、claim、回执及重试边界 |
| 池 fallback 新回归 | 已有业务修复；本轮无前像修改 | **4 PASS** | 原路由／helper AST、真实 domain/store，局部测试 app |
| 完整性 | 27 冻结原件 | **27 PASS；4 份补丁双向 PASS** | 正向逐字节匹配 14 个后像；反向还原 11 个前像并移除 3 个新增测试文件 |

两种竞价 owner 重复执行同一批场景，不将它们说成 48 个独立场景。旧版失败是预期
行为断言，初始切片导入失败与修复过程中的中间失败也保留在各批日志中。
池测试保留项目允许的 1 条 Starlette TestClient 弃用警告。

切片缺 `_namespace.py` 等完整依赖；竞价／池支架的通用名查询替身、HK 的 canonical
支持模块、发布的临时包及 fake service runner 均有显式标记。它们没有替换被测业务
算法，但也不能证明完整 app 启动、真实服务或活动依赖闭包。
独立审查另行重新执行测试、检查支持文件来源，并补充故障生命周期探针；结论边界
以 [独立报告](review/INDEPENDENT_REVIEW.md) 为准。

## 从本包重现

在解包根目录，准备隔离 Python 3.14 环境并安装 [requirements-test.txt](requirements-test.txt)
中本轮实际环境版本。该依赖快照仅用于重现测试，不修改生产依赖。
使用新的输出目录，避免覆盖包内原始证据：

```bash
python3.14 -m venv .review-venv
.review-venv/bin/python -m pip install -r requirements-test.txt
.review-venv/bin/python -B run_focused_suite.py --log-root /tmp/v4-issue28-review-logs
.review-venv/bin/python -B verify_patch_roundtrip.py --receipt /tmp/v4-issue28-patch-roundtrip.json
```

`run_focused_suite.py` 执行六个隔离测试进程；`verify_patch_roundtrip.py` 仅在临时目录
应用与反转补丁，需要本机 `git`。这两者都不是安装或 Stage 运行入口。
各批目录保留单独命令和原始失败重现方法。

## 状态边界与下一步

| 验收层 | 本轮状态 |
| --- | --- |
| 冻结源码身份、修复候选、针对性回归与补丁完整性 | PASS，见上述绑定证据 |
| 独立源码审查 | 范围内未发现未解决的 Critical／P1／P2 候选代码缺陷；不替代真实 Mac 包审查回执 |
| 当前 Mac 完整 owner／依赖、真实新 release plan 与 scope | NOT_RUN / CANNOT_CONFIRM |
| 集成、部署、实际 launchd 安装／恢复、8873 API/UI | NOT_RUN |
| HK 真正 10/7 来源、逐 run 执行原件、自然时段 | CANNOT_CONFIRM / NOT_RUN |
| 行情缺 6–7 个代码、研究数值评分合同、历史 PIT／来源缺口 | 保留，见 OPEN_ITEMS.md |

Luna Max 下一步按 [交接顺序](LUNA_MAX_NEXT_STEPS.md) 完成实际前像和依赖核对，
独立验收发布工具，复用池修复，逐批适配竞价／HK，再分别验 API、重载页面与自然时段。
不能把已存在选股、人工 canary、RECOVERY 或离线 PASS 计作自然运行证明。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
本轮没有部署、采集行情、运行真实 Stage 或修改业务数据；经理台、模型、BUY 与 Vibe8910
没有业务增量。本包只包含必要源码、测试支持、差分、SHA 和精简证据。
