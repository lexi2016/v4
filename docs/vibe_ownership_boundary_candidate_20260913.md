# V4 Vibe 复盘生成器：边界候选与最小接管方案

**裁决：保留 generation.py 的单一入口和 exact-date writer；删除外部应用装载，不重写研究图。当前交付为 PARTIAL_CANDIDATE / HOLD，不是完整数据接管或可激活 release。**

输入仅为 `V4_VIBE_OWNERSHIP_HELP_20260913.zip`，SHA256 `21bc0af2001a1265a4b473bd437811fcf7888c3a25c500668375a383929c10f5`；41 个 MANIFEST 条目字节与 SHA 均核对一致。冻结输入未修改。本文的旧代码定位均相对于该 ZIP，而非用户目前继续变动的本机 worktree。审查报告内“限制五个候选文件”等是待裁决建议，不用它强迫保留已证实有副作用的外部装载器。

## 1. 根因，而非再造面板

1. **只替换末端 writer，未完成代码所有权。** 原 `v4_app/domains/research_review_generation/generation.py:45–57,255–312` 只审 11 个 seed 文件，`354–403` 实际装载 main、trade_calendar 和递归依赖。附件审查的本地闭包是 32 个模块；11 个哈希不是全路径证明。`vibe_reference/duanxian/__init__.py:6–17` 还修改环境和全局 tqdm 构造器，`data.py:15` 改全局 socket 默认超时。
2. **“观察缓存”不是绑定缓存。** 原 generation.py:202–216 只记录 HOME 路径。`data.py:314–364,368–427` 写 leaders/prev_pool；`market_facts.py:12,125–166`、`emotion_metrics.py:330–376`、`theme_tree.py:51,66–97`、`breadth.py:18,186–240`、`stats_context.py:96–152` 继续访问旧树。仅把输出 JSON 移入 V4 不会移走这些依赖。
3. **八个高层函数复用不等于底层一次抓取。** generation.py:406–467 在模块全局临时替换函数；不同日期会回落原函数。`data.py:51–70,314–364` 都调用 fetch_zt_pool；`emotion_metrics.py:58–73` 有自己的缓存；`market_facts.py:125–166` 独立请求三种池。不能凭八个包装调用的次数宣布原始 API 去重。
4. **图外存在未显式绑定的执行/请求。** `analysts.py` 的题材节点调用 `tools.py:17–51`，启动 PATH 中的 mcporter；`prompts.py:95–138` 可执行 HOME 或环境指定的本地 Python；`config.py:20–73` 根据 selector→CLI→MiMo 顺序选择模型并读取凭据。上述代码、选择和数据缺失，不能默默换默认并称“历史行为相同”。
5. **原桥接已有可保留的正确边界。** generation.py:598–636 不调用 main.main、review_store.save 或 reflection.auto_evaluate_prior；原 writer:528–584 已输出 exact-date、无 latest。因此保留此 public facade 比推倒重做更小。
6. **历史身份有两个不同时间。** 原 review_store.py:221–222 同用当前时间表示 data_as_of/generated_at；候选仅将数据时点绑定输入证据，生成时点仍单列。反思严格保留原 `prediction_date < T` 且 `eval_date <= T`（reflection.py:126–149），没有改成别的日期边界；它只是日期级可见性，不能证明盘中 available_at。

## 2. 必须进入 V4 的最小图闭包

目标前缀统一为 `domains/research_review_generation/vibe_core/`。只选 16 个实质来源模块，外加两个无副作用的包初始化文件；不是复制 32 个依赖模块，更不是整库复制。

| V4 目标文件 | 冻结来源与保留部分 | 处理依据 |
|---|---|---|
| review_graph.py | duanxian/review_graph.py，整张六节点图 | 显式注入 data、quick、deep、search、pack；原顺序、边不变 |
| analysts.py | duanxian/analysts.py，五节点工厂 | 保留节点逻辑和 prompt；去掉 data/PACK/tools 全局依赖 |
| synthesizer.py | duanxian/synthesizer.py | 保留事实守卫、结构化收敛和条件 verification 补提取 |
| roles.py | duanxian/roles.py | 原字节，五角色 key/标题/顺序 |
| helpers.py | duanxian/helpers.py | 原字节，报告汇总 |
| state.py | duanxian/state.py | 原字节，图状态 |
| schemas.py | duanxian/schemas.py | 原字节，结构与事实单位守卫 |
| structured.py | duanxian/structured.py | 原字节，两次 JSON 尝试及自由文本回退 |
| llm_errors.py | duanxian/llm_errors.py | 原字节，配置/传输错误分类 |
| deepdive/schemas.py | duanxian/deepdive/schemas.py | 原字节，只为 PromptPack 既有默认字段闭合；不引入 deepdive 服务/引擎 |
| prompts.py | duanxian/prompts.py:35–92 | 仅 PromptPack、RESEARCH_PACK；不加载 HOME、动态 .py 或 PACK 单例 |
| preflight.py | duanxian/preflight.py | 原七检查/三核心门，显式同一个 data 快照和 settled 声明 |
| verification.py | duanxian/verification.py:22–104,271–336 | 指标菜单/描述/提取；不带自动评价、用户 items 写入 |
| util.py | duanxian/util.py 的 is_degraded_report | 仅降级识别；不复制日期、目录、保存工具全集 |
| serializer.py | duanxian/review_store.py:32–42,147–231 | usable、HTML、prefix、serialize；时点、pack、reflection 参数化，不带文件读写 |
| reflection_context.py | duanxian/reflection.py:126–149,446–597 | 日期过滤、latest、scoreboard、近五次上下文；接收 records，不含文件访问/自动回评 |

`main.initial_state` 的字段移入 `owned_runtime.initial_state`，无需复制 main.py。七个完整纯模块与来源逐字节一致；五分析师和裁判的内部 node，经仅 PACK→pack、agent_reach_search→search 名称归一化后 AST 相同；RESEARCH_PACK 赋值 AST 相同。这不是模型输出或真实历史样本等价证明。

### 明确排除

不纳入 main.py 的 CLI/run/main、旧 server/UI/账户、旧 duanxian/__init__.py、tools.py 的 mcporter 子进程；不纳入 config.py/cc_switch_llm.py/cli_llm.py 的自动发现、HOME 凭据和外部 CLI；不纳入 prompts.load_pack；不纳入 review_store 的 save/load/latest/rejected 写入、reflection 的 evaluate/auto_evaluate_prior/_save_reflection、verification 的用户 items 写入。排除自动反思生成不等于删除已有历史；本轮只读历史，不承诺持续自动更新反思闭环。

## 3. 数据能力不能被“排除旧模块”顺便删掉

下列文件是混合计算、缓存和抓取，不应作为原样 import 的图依赖；但其**现有计算/文本能力必须由唯一 shared authority 原样保留或证明已有等价实现**。当前附件没有该 authority 实现，不能给它编造一个已集成的目标文件。

| 来源 | 必须保留的行为/函数 | 最小改法（本候选未实施） |
|---|---|---|
| data.py | 八个 get_*；render_market_facts；leader 最近五日历史；fetch_prev_pool 语义 | 在既有 authority 装配一次；依赖显式 provider/cache；输出八个完整文本/结构值 |
| market_facts.py | pools、seal_quality、loss_effect、feedback_matrix、theme_structure、event_ledger、by_board 及辅助口径 | pools 改为共享原始响应读取；保持原计算，不用阶段池代替原样本域 |
| emotion_metrics.py | promotion_rates、money_effect、consec_premium、ladder_gap、day_summary、cycle_position、build/render | 同一 pool/settled 引用；保留 coverage、历史统计、不可用语义 |
| breadth.py | 原市场广度、缓存回读、原渲染 | 复用 authority 的原始行情；不要新增并行抓取 |
| stats_context.py | READINGS、series/trend/percentile/context_for/diff/render | 注入真实 V4 历史目录，保留窗口、样本不足和原缓存 fingerprint 语义 |
| theme_tree.py | read_cached/build/render、题材状态 | 保留 read_cached 的明确 cache_dir 能力；缺缓存不能令 reader 自动联网；capture 只由原 owner 执行 |
| trade_calendar.py | 原交易日与已收盘判定 | 由既有 authority 给已审核日历结果；不要以日期字符串代替交易日历 |
| fetchers.py、fuyao_sources.py | 本场实际使用的公开 endpoint、Fuyao/Iwencai 选择及失败规则 | 由原共享 provider adapter 拥有；不复制 sys.path/env 修改。Iwencai 外部 client 本体不在附件，CANNOT_CONFIRM |

尤其 `get_market_facts` 不止八个面板字段：原代码:102–114 还包含 stats_context、day_diff、trend、seal_quality、theme_structure、by_board。候选不会裁掉这些额外字段；但提供它们的真实数据适配器尚未迁入。本候选并未完成全量旧缓存接管，也不能据此停止旧 Vibe 生成能力。

## 4. 显式目录和一次抓取

设一个经过本地审核的、与代码分开的绝对路径 `STATE`，禁止 `~` 展开、改 HOME、全局替换模块函数：

```
STATE/inputs/YYYY-MM-DD.json         # 唯一 shared authority 发布；生成器只读
STATE/reflections/YYYY-MM-DD.json    # 历史 prediction_date 文件；生成器只读
STATE/reviews/YYYY-MM-DD.json        # 原 generation.py 唯一 exact writer
```

完整数据接管时还需将 leaders、cache/prev_pool、cache/market_facts、cache/zt_summary、cache/zt_reasons、cache/breadth 及 stats_context 实际依赖的历史目录显式绑定到 V4 authority 所有的根。保持原文件的日期格式、内容、窗口和来源；使用逐文件迁移清单，旧原件不变，不冷启动补抓整个历史。**这些目录迁移没有在本轮执行或假造。**

候选的 snapshot 只物化一次八个值，preflight/节点取副本；正常路径合计 15 次高层读取（七函数各两次，market_facts 一次），settled 一次，news 一次。结束时额外读 input/reflection 进行漂移核对，所以磁盘读取不是严格一次，更不能将它当作网络请求计数。

真正的去重在既有共享 authority：按 `(provider_id, endpoint, target_session, universe/schema_version, canonical semantic params)` 定义 key，保存一次成功原始响应，所有消费者读取同一不可变值；失败结果也复用，重试由该 owner 统一记录。URL cache-buster 与语义参数不能未审就任意删。需分别记录逻辑读取、物理 HTTP 尝试、重试、命中、回退源。不能把 generation.py 的八个 wrapper、内存 Counter 或原始 JSON 自报计数称为物理去重证明。

本候选不 import fetchers/akshare/mcporter，所以生成器层的行情/检索抓取为零；**这不能证明缺失的 shared adapter 原始请求只发生一次**。源回执 SHA 当前只是随输入保留的声明，`authority_receipt_independently_verified=false`，故不能凭候选宣称生产来源验证完成。

## 5. generation.py 保留部分与新接口

只修改两个既有文件：generation.py 与包 __init__.py 的说明。CLI、reader、reader 测试、既有生成器测试及旧说明原字节保留。新增三处边界实现：

- `_snapshot.py`：exact-date/source_role/aware data_as_of/section available/CANNOT_CONFIRM/新闻查询身份；不抓取；拒绝 CURRENT_ONLY 冒充历史。
- `_owned_io.py`：本生成器的 POSIX directory-fd、NOFOLLOW、有界 JSON、no-clobber 原子发布；不是对任意注入 Python client 的 OS 沙箱。
- `owned_runtime.py`：源码 manifest 的调用方 SHA pin、输入 SHA、只读反思、显式 quick/deep/pack、真实图和 serializer 调用及计数。

接口为：

```python
runtime = VibeRuntime(
    state_root=approved_state_root,
    snapshot_sha256=approved_input_sha,
    implementation_manifest_sha256=approved_code_manifest_sha,
    quick=existing_quick_client,
    deep=existing_deep_client,
    quick_identity=approved_quick_identity,
    deep_identity=approved_deep_identity,
    pack=RESEARCH_PACK,
)
receipt = run_generation(
    target_date,
    review_root=approved_state_root / "reviews",
    runtime=runtime,
)
```

变量必须来自既有 V4 authority/profile 的审核绑定，不能启动时对任意文件现算 SHA 便把它当作“批准”。LLM identity 不含凭据；两个 `.invoke` 客户端由 V4 明确构造，不由本模块读 HOME。原 selector→CLI→MiMo 的已选 profile、quick/deep 模型、温度、超时、重试应核对后迁入 V4 配置，**本轮未选择/更改模型，也未读取实际配置**。

候选仅接受显式内置 RESEARCH_PACK。自定义包不在附件；不假设用户旧部署使用内置，不静默回退；自定义历史行为为 CANNOT_CONFIRM，需补充该冻结包后单独绑定。内置 PromptPack 仍保留已有 deepdive 默认字段，不开启新的单股功能。

原 inspect_generator_source 降为 REFERENCE_ONLY，不再返回外部执行许可。原 `backend=` 仅保留离线测试入口，标记 mock_or_injected_backend，不被当作所有权证明。**原 CLI 没有新的 runtime binder，合入候选后其默认生成路径将 fail-closed；本轮没有擅改 CLI/配置来激活。** 本地 Writer 必须先接好唯一 V4 入口的依赖装配，再切换；不能直接覆盖活动运行目录。

## 6. 历史行为保留与差异

保留五角色、裁判、宏观事实块、事实单位守卫、完整 facts/metrics、两次结构化尝试及自由文本 fallback、缺 verification_items 时补提取、usable 判断、原三核心预检门、近五条反思与全历史 scoreboard（30 样本阈值）。不能把已有 30+ 天历史截成五条再算 scoreboard。

正常成功是 quick=5/deep=1；缺 verification_items 是 quick=5/deep=2；连续两次 JSON 失败再文本回退可以是 quick=5/deep=3。invoke 次数仍不等于 SDK 内部 HTTP 尝试，后者未接入测量。

反思读取接受原保存的 ISO prediction-date 文件；缺目录拒绝，空目录明确标历史连续性 CANNOT_CONFIRM；坏 JSON 保留 SHA 与排除警告，不重写。目标日以后可见的记录不进 prompt。自动回评与新反思生成未接管。

旧历史资金/宏观 current-only 路由已在 `data.py:209–214,246–251` 提前拒绝。不能为补齐面板而恢复“抓今天行情、附个历史口径警告”。历史新闻也不能仅凭 query 中含日期就算可用，shared authority 需校验实际来源日期。

消费者 `domains/daily_research_review.py` 原字节不变，仍报告 EXTERNAL_SOURCE_READ_ONLY 和原生成缺口。不能用其 READY 读取状态表示新 generator 已被 UI/owner 审核；本轮不修改 UI 或 reader 标签。

## 7. 离线验收与实际结果

提供的 fixture 是显式合成数据，不是历史行情。替身仅为 LLM 响应与 shared input；真实图测试不替换 graph、node、serializer 或 run_generation。离线工具拒绝网络、子进程及按文件名访问旧 HOME 状态；不修改 HOME。这个测试 audit hook 不是生产隔离方案。

命令（使用本地批准的依赖环境，不临时安装未审版本）：

```bash
PYTHONDONTWRITEBYTECODE=1 python3.14 verification/vibe_ownership/run_offline.py \
  --suite all --evidence-dir /absolute/isolated/evidence/vibe-all

PYTHONDONTWRITEBYTECODE=1 python3.14 verification/vibe_ownership/run_offline.py \
  --suite graph --evidence-dir /absolute/isolated/evidence/vibe-graph
```

本轮 Linux/Python 3.13.5：原 12 例为 **10 passed / 2 failed，exit=1**；最终全部 **41 passed / 4 failed，exit=1**；新增可执行边界/真实节点链 **31 passed，exit=0**。无 skip。

四个失败：两个真实 LangGraph 用例缺 langgraph，两个原失败分别为个人旧 Vibe 路径不在容器、附件没有 apps/api 路由树。原 12 个测试结果状态保持不变；未删改它们。旧路径测试在本地后续还要按 REFERENCE_ONLY 的新语义明确审订，而不是继续期待外部 seed 审查 READY。

**已实际执行**：真实五节点+裁判函数、原结构化重试/补提取、原 serializer、原 exact writer 与原 exact reader；返回 receipt/artifact/reader SHA 一致；源日期、来源字段、未知状态、history 可见性、same-day eval、全历史 scoreboard、额外 facts、root/symlink/traversal/no-clobber、既有产物在 LLM 前拒绝、嵌套安全旗校验。

**尚未实际完成**：LangGraph build/compile/invoke。两例会真正调用它，但本轮在实际 import 处失败，不用假 StateGraph 或 skip 伪装。这是激活阻断。完整公开入口→真实图→artifact/reader 的正向验证为 CANNOT_CONFIRM。模型真实 transport、真实共享原始请求去重、真实历史数据结果一致性、macOS/Python3.14 以及当前完整应用集成也均未验证。

本地补齐后：两个图用例必须通过并记录真实 compiled graph 类型；再加 provider adapter 原始响应 fixture，验证共同涨停/炸板/跌停 endpoint 在全部消费者中各一次、失败/重试次数明确、第二次顺序生成不抓取且不重跑模型、错日期/错 raw SHA/错 authority receipt 拒绝、未配置路径不读取旧 HOME。需增加整个实际 graph 调用的目录边界审计及真实 SDK transport 计数，不能用 get_* 次数替代。

## 8. 激活、并发、回退

现在只能进入独立研究 worktree，不改活动 V4_DAILY_REVIEW_ROOT，不停旧服务。步骤是：本地唯一 Writer 核 preimage → 应用最小补丁 → 在现有 authority 完成数据/缓存迁移和 profile 装配 → 本地真实图与共享 provider fixture 全通过 → 独立 Reviewer 复核 → 再允许唯一 V4 owner 激活。不得新建第二 scheduler、面板、producer 或 8910 入口。

现有 artifact 会在模型调用前拒绝，发布也 no-clobber；这不等于并发启动时图/LLM 只运行一次。真实运行仍须复用现有 owner/任务锁；本候选未新增跨进程任务协调系统。未提供的 authority 调用点及唯一 owner 绑定，均是停旧前必须闭合的依赖。

回退仅限两个修改文件和新增候选路径：先核所有 after SHA，`git apply --reverse --check` 后逆向应用；存在后续编辑必须停止并由唯一 Writer 协调。不能 git reset/整库覆盖、删除新输入/产物、改 HOME 或写旧缓存。运行级回退恢复经批准的旧代码和绑定，保证不并行写入；本轮没有运行级变更可称“已回退/已部署”。

候选自检不等于独立 Reviewer 已复验。最终状态：PARTIAL_CANDIDATE / HOLD / NOT_ACTIVATED。
