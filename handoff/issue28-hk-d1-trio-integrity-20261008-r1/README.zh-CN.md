# Issue #28：HK D1 物理三件套复核候选 R1

**本轮完成了一个可复现的源码完整性修复，尚未恢复 `20261008 / STAGE_0930_0935 / HK_CONNECT` 的现场故障。** 候选在返回成功前重新核对物理 artifact / manifest / receipt 及目录身份，已分别适配问题包内 canonical 和实际 Stage 的精确源码。当前池缺少拆分日期来源证明、上游 manifest/receipt 身份，且所报 100 行价格日期仍为 9 月 30 日；这些输入继续保持 `CANNOT_CONFIRM`。

固定输入：[30ad7bb633f715f30c4e10eb67e9041de92cf036 的完整问题包](https://github.com/lexi2016/v4/tree/30ad7bb633f715f30c4e10eb67e9041de92cf036/handoff/hk-stage-failure-chat-20261008)。原包 52 个文件与 GitHub 附加同步说明均已读回，53 个 Git blob/字节数及 51 项 SHA256 全部匹配。本轮没有取得原 ZIP 字节，不将解压文件核验写成原 ZIP 核验。证据见 [输入核验记录](input/REMOTE_PACKAGE_VERIFICATION.json)。

## 1. 修了什么，以及没有修复的现场阻断

旧校验器在流程前段核对完整物理三件套，末尾却只检查池 artifact 哈希和日期 owner 路径。若 manifest / receipt 在较早读取后发生变化，或者同一路径被换成含相同字节的新目录，旧校验器仍可能返回成功。

本候选在返回前通过原 resolver 或保留的 Store 再读完整 snapshot，对比 payload、artifact digest、语义 digest、三份物理文件哈希、物理根和三份相对路径；读取错误转成 `RunnerError`。无 resolver 的 canonical 物理池路径复用较早创建的 Store，保留它捕获的 SafeRoot 目录身份。公共 `(path, sha)` 返回合同保持原样。这个检查只证明此次末尾复读的一致性，不保证之后所有消费者之间具备跨流程原子性。

候选保留原来的固定 D1 Top100、日期、市场、行级价格日期、来源身份和 capture-time 约束。物理三件套身份与上游 D1 身份分别校验，不增加 runtime provenance 字段，也没有将物理哈希塞进缺失的上游字段。

| 证据层 | 本包已有观测 | 当前结论 |
| --- | --- | --- |
| 本地池物理三件套 | artifact `62d7716c…`、manifest `cc476019…`、receipt `1871468d…`；摘要记录三者一致 | 证明的是本地物化池身份；本轮候选补足校验末尾的一致性检查。 |
| 上游 D1 价格来源 | payload 的 `source_sha256=ce4e9422…`；顶层 source manifest / receipt 字段缺失 | 与本地 artifact 是不同来源层，不能拼用两层哈希。真实价格来源三件套仍需核实。 |
| 日期 | 日历要求价格日 `20261007`、资格日 `20260930`；所报 100 行价格日均为 `20260930` | 即使只补 provenance，行级日期仍会被拒绝。没有改标旧行。 |
| 资格来源 | 缺少独立、可追溯的资格 artifact / run / capture 链 | 不能从 D1 池 SHA、run 或当前时间推造资格证据。 |

以上为问题包的冻结观测。本轮没有访问 Mac 原业务数据，也不断言缺失的权威文件在其他地方绝不存在。完整原因见 [Mac 接续说明](acceptance/MAC_READONLY_ACCEPTANCE.md) 和 [独立审查](review/review.md)。

## 2. 最小产品文件与两个 owner

只有一个逻辑文件发生变化，分别面向两个明确 owner：`stage_center/_runner_parts/hk_input_validation.py`。两个前像完全相同，两个后像也完全相同，因此交付一份公共后像和一份 diff，通过两项 owner 身份清单映射；没有用整棵 canonical 替换实际 Stage。

| Owner | 冻结源码根 | 适配证据 |
| --- | --- | --- |
| canonical | `~/Desktop/学习/v4_app` | 使用包内 13 份 canonical 前像，单独加载其 runner / Store / resolver 进行测试。 |
| actual Stage | `~/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app` | 使用包内 13 份实际 Stage 前像，单独加载其 runner / Store / resolver 进行测试。 |

两棵源码的 13 对文件中有 6 对相同、7 对不同；调用链和差异见 [owner 对照](reports/OWNER_SOURCE_DIFFERENCES.json)。测试动态加载了相关 binding / Store 模块；ops 入口与完整 slot 只做源码检查，没有执行完整 Stage。17 份补充依赖来自明确记录的历史参考，其中一份是已披露的通用 namespace 字节别名；它们不能冒充完整当前 Mac runtime 身份。[输入清单](harness/INPUT_MANIFEST.json) 记录了逐文件来源和 SHA。

| 文件身份 | SHA256 / 大小 |
| --- | --- |
| 两个 owner 的前像 | `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735`，23,786 字节 |
| 两个 owner 的后像 | `b20baa18d0ee9748971db835f6fb3dd9a0e1d66aabd8da8d450aee3a4a528a8e`，25,460 字节 |

可审查文件：[diff](patches/hk_input_validation.patch)、[完整后像](after/stage_center/_runner_parts/hk_input_validation.py)、[owner 前后像清单](candidate_identity.json)、[变更元数据](CHANGE_MANIFEST.json)。

## 3. 实际测试与独立审查

运行环境为 Linux x86_64，Python **3.14.7**、pytest **9.1.1**。实际命令、解释器路径、stdout、JUnit 和模块导入 SHA 均保留。没有安装依赖、连接行情服务或运行 Mac 服务。

| 测试集合 | actual Stage 前像 → 后像 | canonical 前像 → 后像 |
| --- | --- | --- |
| 作者新增 13 项 | 9 PASS / 4 FAIL → 13 PASS | 9 PASS / 4 FAIL → 13 PASS |
| 独立 reviewer 新增 2 项目录身份 probe | 0 PASS / 2 FAIL → 2 PASS | 0 PASS / 2 FAIL → 2 PASS |
| 最终可移植入口合并的 15 项 | 9 PASS / 6 FAIL → 15 PASS | 9 PASS / 6 FAIL → 15 PASS |
| 原交接 19 项，文件保持原样 | 12 PASS / 7 FAIL → 12 PASS / 7 FAIL | 17 PASS / 2 FAIL → 17 PASS / 2 FAIL |

15 项是独立参数化用例数；在两个 owner 上运行后像共有 **30 次 PASS**。作者运行、独立复跑和打包后复跑不是新增唯一用例，不能累计包装成更多测试。所有新增失败回归的前像失败均为未抛出预期 `RunnerError`；后像无 error / skip。

新增用例分别覆盖：现场日期/字段形状的缺 provenance；补全合成 provenance 后仍为 9/30 的旧行价格；本地三件套不能补位缺失上游哈希；缺失、无时区或过晚 capture；完整合法合成输入；primary / secondary 路径末尾 manifest / receipt 变化；以及三份字节相同但根目录 inode 被替换。

原交接测试的既有失败没有掩盖：实际 Stage 的七项属于 10/7 港股通休市日观察分支的版本差异；canonical 的两项在旧 fixture 物化时因缺 `d1_source_artifact_relative` 被拒绝。它们不由本候选引入，也未被本候选修复。见 [基线比较](evidence/BASELINE_COMPARISON.json)、[基线分析](reports/BASELINE_ANALYSIS.md) 和 [独立逐项确认](review/KNOWN_BASELINE_FAILURES.json)。

独立审查结论是 **`TARGETED_SOURCE_INTEGRITY_PASS_WITH_KNOWN_BASELINE_AND_DEPLOYMENT_GAPS`**，没有发现此限定补丁新增的 Critical / Important / Minor 问题。原 19 项整套回归并未全绿，也没有发布批准。

另有只读身份审计工具的 **5 项烟测**，与 HK 产品回归分别统计。测试入口的打包检查还核对了允许清单、未列入清单的 initializer、外部 pytest 配置与插件影响；这些也不计为 HK 产品用例。

## 4. Mac 可直接运行的隔离验收入口

先阅读 [PROMPT_FOR_MAC.md](PROMPT_FOR_MAC.md)。在 Mac 设置 `ISSUE28_BUNDLE` 为本交付的实际解包目录，使用冻结 Stage 配置中的 V4 解释器，并先核对它与实际配置一致：

```bash
: "${ISSUE28_BUNDLE:?请设置本候选交付的实际解包目录}"
ISSUE28_PY="$HOME/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"

"$ISSUE28_PY" -B "$ISSUE28_BUNDLE/harness/run_regressions.py" \
  --owner both --phase after --suite targeted
```

预期两个 owner 各 **15 PASS**。入口只把允许清单内各 owner 的 13 份源码复制到新临时目录，并在后像测试时覆盖那里的一个候选文件；合成数据和结果也在新临时目录。它记录实际导入 SHA，不接受现场 app 根作为目标，也不运行 ops / launchd / API。原有 pytest 外部选项、插件和上级 conftest 不参与本次选择。结果路径写在 stdout 最后一行，便于原样留档。

若要复现 RED，分别执行以下命令，保留非零退出码和日志：

```bash
"$ISSUE28_PY" -B "$ISSUE28_BUNDLE/harness/run_regressions.py" \
  --owner both --phase before --suite targeted
```

预期每个 owner **9 PASS / 6 FAIL**，退出码 1。若运行 `--suite original`，前后像均保留上述 7 / 2 项基线失败和非零退出码；这不是全绿验收入口。不要用 `xfail`、过滤失败或改原 fixture 来改变结论。

只读 Mac 源码/配置/回执身份盘点，以及审计工具的 5 项烟测，按 [接续说明](acceptance/MAC_READONLY_ACCEPTANCE.md) 执行。此包的 `input/` 可作为其中的 `ISSUE28_PROBLEM_DIR`，本包根可作为 `ISSUE28_CANDIDATE_DIR`，`acceptance/` 可作为 `ISSUE28_ACCEPTANCE_DIR`。完整当前 API app 不在输入包里，离线盘点会保留缺项，不能补空文件获得通过。

## 5. 上线与阶段恢复还缺什么

包内 API GET 的 HTTP 200 只是失败状态的只读投影。Stage 精确错误保留在 HK 市场回执中；HK 无 selection 写入，A 有行使总体为 `PARTIAL_WITH_ROWS`。当前 API 完整 consumer / override 字节没有提供，因此没有把历史参考实现当作当前 API 独立验收。

实际调度将 `SETTLED_PARTIAL` 视为 settled。当前 provenance 错误不符合现有特定 cutoff 恢复分支，替换校验器不能保证旧槽自动重跑。不得删除失败回执、attempt/rearm 或已有 A 结果来获得成功；人工补跑也不能记为自然时段成功。

后续闭环需要：读取并核验真实 10/7 价格原来源和 9/30 资格来源及 capture 链；在实际 Mac owner 的完整依赖环境中完成独立测试；形成针对具体服务版本的发布与回滚清单；另行审查旧槽恢复方案；最后核对 Stage 回执、selection 身份、API/UI 和自然时段证据。当前没有执行这些动作，也没有创建新的 producer 或改写业务数据。

| 状态 | 本轮结论 |
| --- | --- |
| 候选实现 | IMPLEMENTED：末尾物理三件套及目录身份复核 |
| 针对性 Linux 测试 | TESTED：两 owner 各 15/15 |
| 独立源码审查 | REVIEWED：限定范围通过，保留基线与部署缺口 |
| 实际 owner 适配 | SOURCE_SLICE_ADAPTED：两份精确前像分别加载；不是完整运行环境验收 |
| canonical / 实际 Stage 本机集成 | NOT_RUN |
| Mac 完整运行、部署、API/UI、自然时段 | NOT_RUN |
| 旧槽恢复、业务源重建 | NOT_RUN；现场仍 CANNOT_CONFIRM |
| 嵌套字段历史 P2、历史缺失数据 | 本候选未解决，沿用未完成状态 |

两项已由用户报告在 Mac 38/38 通过且已集成的历史 P2，继续保留原有完成状态；它们不能替代本次候选的 Mac、部署或恢复证据。

## 6. 交付与同步范围

本交付保存必要源码前像、公共后像、补丁、测试、来源清单、脱敏输入摘要和精简执行证据；不包含行情行、股票名单、账号、凭证、完整 API 响应、虚拟环境、缓存或合成临时池数据。输入切片说明见 [input/SCOPE.md](input/SCOPE.md)。独立审查原始命令保留用于追溯；本包的 Mac 可移植执行入口以 `harness/run_regressions.py` 为准。

本轮新分支同步依据固定仓库 [AGENTS.md 的既有用户授权](https://github.com/lexi2016/v4/blob/30ad7bb633f715f30c4e10eb67e9041de92cf036/AGENTS.md)；问题包本身没有扩大发布权限。只向新的独立 handoff 分支同步，不 merge、不部署、不切换服务。远端 commit 与文件读回结果以最终交付回执为准。
