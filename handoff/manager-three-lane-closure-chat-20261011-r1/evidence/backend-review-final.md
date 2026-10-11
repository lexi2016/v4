# 独立后端审核最终报告

## 1. 报告身份与形成方式

- Reviewer：`/root/backend_review`，不同于唯一 Writer `/root`。
- 审核工作目录：`/workspace/scratch/81f12368319d/work/candidate`。
- 比较基线：`2152496bf288b696c5c7eb6e9e2abc08962ca33d`。
- 最终候选 commit：`d3145a537e93b3533a93601bff4fec80648ea01d`，由 Writer 在审核完成后告知。Writer 声明业务源码与本报告所审查版本一致，提交时另规范化测试 fixture 末尾换行并补充实施计划记录；本报告不把该声明改写成 Reviewer 在提交后重新测试的证明。
- 本报告根据已经执行的只读源码审核、工具结果和独立复跑记录整理。**创建本报告没有再次运行测试，也没有修改候选源码或测试。**
- 附属记录：`backend_final_recheck_record.txt`、`backend_final_recheck_record.json`，位于本报告同目录。它们根据已观察的工具执行 transcript 补写，包含精确命令和 stdout；原执行没有用 tee 保存 stdout，不能将这些文件称为执行时生成的原始日志。

## 2. 最终结论

**准予作为明确标记 `PARTIAL` 的工程候选交付。当前已审查后端差异没有已确认且未解决的 Critical／Important 问题。**

本次独立审核发现的两项 Important 回归均由唯一 Writer 修复，修复后通过独立验证。该准予结论仅覆盖本地代码候选与可执行的隔离回归，不构成 Mac 8873 部署、三路真实选股完成、历史 PIT 或下一实际交易日自然运行通过的结论。

| 等级 | 最终状态 |
|---|---|
| Critical | 0 项已确认问题 |
| Important | 发现 2 项；2 项均已关闭 |
| Minor／非阻断备注 | 旧 dynamic 测试口径不一致；混合引用数组排序的未证实可达覆盖边界 |
| 整体业务状态 | `PARTIAL／未完成`，真实 A/H/O/I/R/D/N 验收不能由工程 PASS 替代 |

## 3. 审核范围

重点检查以下后端文件相对基线的差异及其真实调用路径：

- `v4/manager_research/workspace_history.py`
- `v4/manager_research/workspace_identity.py`
- `v4/manager_research/research_attention.py`
- `v4/manager_research/announcement_analysis.py`
- `v4/manager_research/service.py`
- `apps/api/v35_api/manager_research_router.py`
- `v4/manager_research/workspace_daily_channels.py`
- `v4/manager_research/workspace.py`
- `stage_center/consumer.py`
- 五个 `tests/test_three_lane_*_20261011.py` 文件，以及与实际风险相关的原 saved-plan 回归。

需求依据为问题包 `README_提交给Chat.md` 和 evidence。审核关注并发、PIT、相关输入变化、保存身份、lane 隔离、未知与有效零、完整 owner payload 和只读边界。审核没有新增算法或 producer，没有添加依赖 shim，也没有通过放宽原校验使测试通过。

## 4. Important 发现与关闭证据

### I-1：缺少 Stage 来源时，新投射曾阻断原 owner 保存——已关闭

**修复前问题：**`stage_selection_readback()` 无条件使用 `stage.get(key)` 复制安全键。在原 Stage reader 未绑定或失败的正常缺数据路径上，它生成 `RESEARCH_ONLY=None`。该对象嵌入 workspace 后，原 `assert_manager_safe_tree` 在 `refresh_workspace_plan` 保存时抛出 `unsafe manager research research state`。这会让一条缺失来源阻断其他结果的 PARTIAL 归档。

**独立复现：**原现有用例 `tests/test_manager_workspace_targeted_r2.py::test_original_service_future_plan_refresh_does_not_run_catalyst_producer` 使用真实 `ManagerResearchJobService` 和 `ManagerResearchStore`，没有 Stage reader。修复前 candidate 保存失败；同环境对应 baseline 快照的该用例为 **1 passed**。已核对 baseline 快照中的 workspace、daily channels 和对应原测试文件与指定 Git baseline 的字节一致。

**修复：**`workspace_daily_channels.py` 的 `stage_selection_readback()` 仅复制 Stage 对象实际存在的键，不再为缺失安全标记生成 None，也不为缺失来源补造 VERIFIED 身份。

**关闭证据：**新增真实 service 回归 `test_missing_stage_does_not_invent_null_safety_flags_or_block_partial_save` 已纳入最终独立 68 项复跑。它验证原 owner 可以保存 PARTIAL、精确 product attempt 状态正确、HK 数量仍为 None、保存产品 SHA 与原 owner 读回一致。

### I-2：合法历史计划曾丢失每日摘要需要的 execution context——已关闭

**修复前问题：**新 `_execution()` 复用 `owner_plan_readback()` 做完整验证，但 `read_history()` 成功分支只投射精确 attempt，没有将保存产品的 `execution_context` 投射到 `plan_product`。带 execution context 的合法历史产品因此被摘要 gate 误判为未验证，OVERSOLD run／SHA 清空，合法有效零降为未知。

**独立复现：**同一原 ledger 和 sealed attempt，product 带一致 context 时得到 `READY_EMPTY`、count 0 和原 run；按修复前历史投射省略 context 后得到 PARTIAL、count None、run None，并增加 `RESEARCH_SELECTION_OWNER_PLAN_NOT_VERIFIED`。

**修复：**`workspace_history.py` 的历史成功分支投射 `deepcopy(saved.get('execution_context'))`，不修改归档原件。

**关闭证据：**新增 `test_history_preserves_execution_context_for_original_saved_research_ledger` 经过真实 `read_history()`、保存产品、精确 attempt、历史准入和 PIT gate；只有外部来源重读使用保持不变的合成输入。最终独立复跑验证原 run／产品 SHA／有效零保留，保存 JSON 字节不变。

该历史 fixture 初稿声明 ON_TIME 却没有合法 scheduled_for，被原历史准入拒绝；Writer 修正 fixture 后重跑通过，没有放宽生产准入规则。

## 5. 核心边界核查

### 公告原 owner 与并发

注册引用继续通过原 handoff、judgment 和产品 validator。receipt 读、检查、写入、读回处于同一原 store 事务；重复导入保留首次实际 available_at，冲突或损坏的既有 receipt 不会被覆盖。HTTP 和直接 service 调用使用同一原 owner。

legacy 产品可以读取，但不会因本补丁自动获得 reviewed owner receipt。没有将界面观察的 55 只硬编码成完成结果，也没有把公告风险事件升格为 BUY 输入。

### 历史扫描与 PIT

优化仅使用精确 run 的合法终态原 attempt 排除在历史 cutoff 之后才开始的运行，不据此准入产品。缺少 journal 时回到原正文校验；损坏 journal 不证明历史缺席；latest 的产品 SHA 校验保留。

64 MiB 扫描上限和 32 MiB 单计划上限未提高，没有删除归档或产生第二索引 owner。该优化对真实 10/09 的效果仍需原正文与精确 journal 验证，不能仅根据元数据 inventory 报真实 R 验收通过。

### HK 原选股与完整身份

消费 canonical selection market，而非截断到 50 行的 UI 别名；保留原顺序、rank、原 run 和 SelectionStore manifest／artifact／receipt 身份。backfill、错日期、缺三件套或行数不一致均拒绝。

执行和实际可用时间尚未核实，因此可展示的正数保存结果仍为 PARTIAL；空读回不能报有效零；历史模式的选股 rows 不准入未核实可用时间的结果。原 0935 reader 不能被描述成原 0925 daily owner 自然执行完成。

### 超跌原 ledger

摘要重新调用原 `build_research_selection_ledger()` 校验完整 decision ledger，没有重新发明选择规则。strict 桶不能绕过原 ledger；判定或相关引用变化会拒绝摘要。未保存预览不能报完成或有效零，其他 lane 的缺口不会被无条件加入本 lane。

### 语义身份与相关输入变化

新增 peripheral 识别器与原 adapter 的实际输出合同一致。仅在受限引用位置且完整 owner 合同成立时排除全局 manifest SHA；payload、receipt、路径、日期、额外取得时间及原 source content 仍参与身份。

辅助只读 identity spotcheck 未见新增阻断。其纯函数探针确认仅全局 manifest 变化不改变 attention identity，payload／receipt／路径／session／manifest_path／available_at 变化会改变 identity。该辅助探针使用现有 Python 3.12，不计入本报告的 Python 3.14 项目测试数。

### 显式当前回看与 auto

新增 dynamic 行为使用当前时钟进入原 owner 重读；auto 继续使用保存 cutoff。current_review 只改变返回投射基底，原保存产品、精确 attempt、SHA 和相关输入比较门禁保留。没有把当前回看转换为历史或自然运行证明。

## 6. Minor／非阻断备注

1. **旧 dynamic identity 断言不再匹配新口径。**原 `test_original_service_future_plan_refresh_does_not_run_catalyst_producer` 现在可以成功保存；其末尾使用默认 dynamic GET 的 identity 相等断言仍与推进当前 cutoff 的新语义冲突。该旧用例不在最终 68 项命令中，不能报为 PASS。新增 review-clock 文件分别验证有／无精确 attempt 的当前回看和 auto 保存 cutoff。
2. **引用排序覆盖边界。**规范化排序仅针对全员为完整可识别 owner binding 的数组。构造混合其他引用的数组时，原 JSON 排序仍可能因全局 manifest 改变而重排部分引用。目前没有证明真实 owner 可达输入会形成该组合，不列 blocker，也不据此扩大修复；不能宣称已穷尽任何引用形态的 manifest churn。

## 7. 实际独立执行记录

| 执行范围 | 实际结果 | 解释 |
|---|---|---|
| 最初四个新增三路文件 | 62 passed | 修复前工程单项测试，未覆盖后来发现的两项集成缺陷 |
| 修复后五个新增三路文件＋两个原 saved-plan 回归 | **68 passed，1 warning，4.26s，exit 0** | 最终 Reviewer 独立复跑 |
| git diff --check | exit 0，无输出 | 候选差异格式检查 |
| 扩展原套件，修复前 candidate | 59 passed／22 failed／1 skipped | 三个原测试文件 |
| 同扩展原套件，对应 baseline 快照 | 62 passed／19 failed／1 skipped | 用于识别候选新增失败 |
| 两个 business completion 文件 | 2 个 collection errors | 缺 `tests.r3_scoped_loader`；未执行测试主体 |

扩展原套件为 `test_manager_research_selection_ledger.py`、`test_manager_workspace_targeted_r2.py`、`test_manager_plan_readback_issue24.py`。基线失败涉及未附 app、旧 calendar／recovery／identity fixture 契约等；没有把它们全算作本次回归，也没有加 shim、放宽门禁或删断言使它们变绿。修复前 candidate 相比 baseline 新增的三项失败均指向 I-1 缺 Stage 保存问题；其保存路径修复后通过，新增集成用例也通过。旧 dynamic identity 断言按第 6 节独立记录。

最初一次运行因为 Reviewer 尚未建立 basetemp 父目录，出现 20 个 setup errors 和 42 passed；建立独立临时目录后同一四文件命令为 62 passed。这不是产品缺陷，也不被掩盖为未曾发生。

### 最终精确命令

工作目录：`/workspace/scratch/81f12368319d/work/candidate`

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/workspace/scratch/81f12368319d/work/candidate:/workspace/scratch/81f12368319d/work/test_support uv run --offline --no-project --python 3.14 --with pytest --with fastapi --with httpx python -m pytest -q -p no:cacheprovider --import-mode=importlib tests/test_three_lane_history_20261011.py tests/test_three_lane_identity_20261011.py tests/test_three_lane_daily_20261011.py tests/test_three_lane_announcement_20261011.py tests/test_three_lane_review_clock_20261011.py tests/test_manager_workspace_targeted_r2.py::test_tampered_saved_plan_not_presented_as_success tests/test_manager_workspace_targeted_r2.py::test_exact_date_saved_plan_cannot_hide_new_owner_failure --basetemp=/workspace/scratch/81f12368319d/work/reviewer_backend_tmp/final_recheck
```

两个原回归完整 nodeid：

```text
tests/test_manager_workspace_targeted_r2.py::test_tampered_saved_plan_not_presented_as_success
tests/test_manager_workspace_targeted_r2.py::test_exact_date_saved_plan_cannot_hide_new_owner_failure
```

最终结果：

```text
68 passed, 1 warning in 4.26s
```

工具 session：`2914`；完成 chunk：`ff924f`；exit code：`0`。唯一 warning 为 FastAPI／Starlette 对 httpx TestClient 的弃用提示。测试产物位于 `work/reviewer_backend_tmp/final_recheck`。

运行使用指定 Python 3.14、真实 pytest／FastAPI／httpx 和固定来源 test_support，设置 `PYTHONDONTWRITEBYTECODE=1` 并禁用 pytest cache。test_support 是本次隔离运行依赖，不能充当现役生产身份。

## 8. 未运行／无法确认范围

- 当前匹配版本的 `stage_center.execution_evidence` 未取得；已知旧固定版本缺 `research_source_projection`，也不支持当前两个 SelectionStore keyword。没有降级或补 shim，完整现役 Stage consumer 集成未运行。
- 两个 business completion 文件因缺原 `tests.r3_scoped_loader` 没有运行测试主体。
- 真实 10/09 七份计划正文、对应精确 attempt journal、公告原 owner receipt、精确 HK 输入及 rebound 行情／量价输入未附，未执行真实业务闭环验收。
- 未证明旧 10/12 sealed identity 已恢复 CURRENT；缺少原预映像及真实重算证据。
- Mac 8873 不可达，未核 PID、loaded-module、部署回执、重载页面或下一实际交易日自然运行。
- 前端不属于此后端 Reviewer 的独立执行范围。Writer 后续告知提交后后端 68 项又通过 4.27s、前端独立 43 项通过及 1 项 skip；这些仅为 Writer 提供的交付信息，不计入本报告的 Reviewer 独立测试数。

## 9. 已审查业务文件 SHA256

以下 SHA 来自最终独立复跑后的只读取证，绑定本报告的业务源码审查版本：

| 文件 | SHA256 |
|---|---|
| `apps/api/v35_api/manager_research_router.py` | `d6e5df4b8d34c735838bffb3908c60a68fba646068877ae29400e2962d3df5c8` |
| `stage_center/consumer.py` | `6b1b54f6633baeaa13e66cd9bea21bf23e7b0ae68b02c390211b6ceff8578619` |
| `v4/manager_research/announcement_analysis.py` | `cc4fdeb7485e4736d9a66289f6fe4ec3fefaef9acd6ea9c8c9ab6401f0425729` |
| `v4/manager_research/research_attention.py` | `c40eace0dc0de7606ff4ca2e1b5e74846a4f6191091385b35f91d8eb4f4dc6db` |
| `v4/manager_research/service.py` | `72a26be99e2bdcd86f826ed5f35deecf97ec2bff4564d5061e18b7553ac8fd42` |
| `v4/manager_research/workspace.py` | `e1282f724c387529134add6d69630452127f960c5727314295d3f50b452847ff` |
| `v4/manager_research/workspace_daily_channels.py` | `72dce6c3db358eb3d7d058443ec720ebd88ea4bc63f4873cd2c3e90caf253bd6` |
| `v4/manager_research/workspace_history.py` | `1b4e1e7d0070c6e6a6352a0f13533c6d9ba5fe3f215dc8d941a954841bb31344` |
| `v4/manager_research/workspace_identity.py` | `e1c2dbf68f3104508ceec32988aa8c1cad4465b50b8bfd739f93bfaf1276faca` |

**最终交付措辞：后端候选工程回归通过；整体业务保持 PARTIAL／未完成。两项 Important 已关闭不等于真实三路闭环已完成。**
