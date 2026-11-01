# V4 剩余代码：实际实现、测试与交付边界

**状态：IMPLEMENTED_CODE_CANDIDATE / NOT_ACTIVATED。** 本次继续完成显式装配、V4 自有数据/缓存、真实提供商工厂、证据链和任务锁代码，并补上单独授权的 A 历史异常精确绑定。没有重新实现图或算法。当前容器不是本地生产/自然运行验收环境；缺失依赖和未提供的原始历史数据没有被计为通过。

## 1. 精确基线与根因

唯一基线是新附件 `V4_REMAINING_CODE_FOR_CHAT_20260913.zip`，SHA-256 `e2860717154e45449e227a4de327f62096cb7cf28d0f0fec24e2d194f9ff7b29`。89个原 manifest 项全部匹配；附件共90个文件，其中 V4 源码子树49个文件。没有叠加此前整库优化包，没有访问用户机器。

上一候选真正未闭合的是：CLI没有装配；高层输入有摘要而实际raw/receipt未验证；混合计算仍属于旧应用；缓存和反思没有显式所有权；模型身份只是标签；任务锁晚于后端执行。当前把这些接在原 `run_generation` 内。数据所有者是原取数边界的迁移，不是独立运行的第二个producer。

包内本地 Reviewer 记录原候选31边界通过、真实LangGraph 2/2通过。这些是用户提供的本机证据，不是本次新代码已经在本机通过。图及原分析师、裁判、提示词、serializer整个 `vibe_core/` 均逐字节保留。

## 2. 实施范围

V4子树原49文件全部保留。修改11个既有文件，新增29个文件，合计78个；38个原文件字节不变。新增主要是原计算模块迁移、边界适配及测试，不是新服务。基础设施、reader、router、UI、scheduler、BUY、公式计算不改。

### 已实施的七项

| 边界 | 实现与行为 |
|---|---|
| 原公开CLI | `ops/run_research_review_generation.py` → `assemble_runtime` → 原 `run_generation`；collect/snapshot明确选择；坏配置/缺证据exit2，不隐式加载旧Vibe |
| 任务锁 | 调用共享 `owned_interprocess_lock`，锁在destination check、模型构造、数据物化、graph之前；同日并发/顺序重复不再次生成已发布产物 |
| 计算模块 | `data_core/` 中七模块及util/fetchers/Fuyao共10个实质模块；仅移除旧状态/网络初始化、自动写入，计算依赖通过ctx显式传递 |
| 单一raw所有者 | `owned_authority.py`，原始请求按provider/endpoint/session/完整语义参数复用成功和失败；保留原重试上限和分页；缓存池raw可直接复用 |
| V4缓存与历史 | `_cache.py`，显式cache_root在state内；80文件逐文件bytes/SHA批准；缺失/漂移/软链接拒绝；全部可见reflection参与原scoreboard |
| 实际模型工厂 | `model_provider.py`读取显式CC-Switch SQLite确切行并构造真实ChatOpenAI；profile与实际client属性一致；无MiMo/CLI回退，无源码凭证 |
| 证据校验 | `_evidence.py`实际读raw/source/receipt及cache原字节；source/runtime manifest由调用方pin；日期、值、源闭包、安全旗、反思manifest和运行中漂移均校验 |

`_owned_io.py`现在只是共享SafeRoot的领域适配，不再重复底层open/fsync/link代码。合法的研究`order`矩阵仍保留，三个能力旗递归拒绝非false；没有放松全局交易守卫。

### 精确文件清单

| 相对v4_app路径 | 操作 |
|---|---|
| `contracts/a_known_history_gaps.json` | 新增 |
| `contracts/vibe_runtime_profile.json` | 新增 |
| `domains/research_review_generation/HISTORICAL_CACHE_MANIFEST.json` | 新增 |
| `domains/research_review_generation/OWNED_SOURCE_MANIFEST.json` | 局部修改 |
| `domains/research_review_generation/__init__.py` | 局部修改 |
| `domains/research_review_generation/_cache.py` | 新增 |
| `domains/research_review_generation/_evidence.py` | 新增 |
| `domains/research_review_generation/_owned_io.py` | 局部修改 |
| `domains/research_review_generation/assembly.py` | 新增 |
| `domains/research_review_generation/data_core/__init__.py` | 新增 |
| `domains/research_review_generation/data_core/breadth.py` | 新增 |
| `domains/research_review_generation/data_core/data.py` | 新增 |
| `domains/research_review_generation/data_core/emotion_metrics.py` | 新增 |
| `domains/research_review_generation/data_core/fetchers.py` | 新增 |
| `domains/research_review_generation/data_core/fuyao_sources.py` | 新增 |
| `domains/research_review_generation/data_core/market_facts.py` | 新增 |
| `domains/research_review_generation/data_core/stats_context.py` | 新增 |
| `domains/research_review_generation/data_core/theme_tree.py` | 新增 |
| `domains/research_review_generation/data_core/trade_calendar.py` | 新增 |
| `domains/research_review_generation/data_core/util.py` | 新增 |
| `domains/research_review_generation/generation.py` | 局部修改 |
| `domains/research_review_generation/model_provider.py` | 新增 |
| `domains/research_review_generation/owned_authority.py` | 新增 |
| `domains/research_review_generation/owned_runtime.py` | 局部修改 |
| `ops/a_formula_increment.py` | 局部修改 |
| `ops/run_research_review_generation.py` | 局部修改 |
| `tests/test_a_known_history_keys.py` | 新增 |
| `tests/test_vibe_assembly.py` | 新增 |
| `tests/test_vibe_calculation_parity.py` | 新增 |
| `tests/test_vibe_cli_real_graph.py` | 新增 |
| `tests/test_vibe_data_owner.py` | 新增 |
| `tests/test_vibe_evidence_chain.py` | 新增 |
| `tests/test_vibe_last_boundary_gates.py` | 新增 |
| `tests/test_vibe_model_factory.py` | 新增 |
| `tests/test_vibe_owned_inputs.py` | 局部修改 |
| `tests/test_vibe_owned_nodes.py` | 局部修改 |
| `tests/test_vibe_task_lock.py` | 新增 |
| `tests/vibe_ownership_fixtures.py` | 局部修改 |
| `verification/vibe_ownership/IMPLEMENTATION_20260913.md` | 新增 |
| `verification/vibe_ownership/run_offline.py` | 局部修改 |

完整before/after SHA及bytes见交付 `V4_REMAINING_CHANGE_MANIFEST_20260913.json`。所有修改均落在本次允许范围。A文件只改变 `_audit_existing_history` 并增加一个绑定helper；其他原A函数AST均相同。

## 3. 原计算与历史行为

保留 `data / market_facts / emotion_metrics / breadth / stats_context / theme_tree / trade_calendar` 及必要fetchers/Fuyao/util。固定原始响应对照真实新代码；原参考函数用AST隔离旧导入副作用，不运行旧应用。七模块有**84个函数**在仅去除新ctx参数/传递后AST相同。另实测原涨停池和情绪文本、封板质量、5类涨跌幅制度。这个结果不代表所有市场数据分支已全量回放；逐函数变更和排除清单在source_audit.json。

保留完整facts：breadth、stats_context、day_diff、trend、theme_tree、seal_quality、loss_effect、feedback_matrix、theme_structure、event_ledger、by_board；保留派生指标、龙头近五日谱系和原历史窗口。历史资金/宏观缺少真实目标日快照时仍降级，不以当前行情或其他面板替代。

### 状态布局

```text
STATE/
  data/                         # 示例cache_root，可用其他显式子目录
    cache/market_facts/YYYY-MM-DD.json
    cache/zt_summary/YYYY-MM-DD.json
    cache/prev_pool/YYYY-MM-DD.json
    cache/breadth/YYYY-MM-DD.json
    cache/zt_reasons/YYYY-MM-DD.json
    leaders/YYYYMMDD.json
    reflections/YYYY-MM-DD.json
    .ownership/generated-cache.json
  raw/<sha>.json                # HTTP原字节或明确标记的SDK返回frame，不冒充wire bytes
  cache_evidence/<sha>.json     # 原缓存字节的封装
  sources/<sha>.json
  receipts/<sha>.json
  inputs/YYYY-MM-DD.json
  news/<explicit-file>.json     # 既有共享资讯的批准输入，只读
  reviews/YYYY-MM-DD.json       # 原唯一writer；没有latest
  reviews/.generation/...      # 原共享锁实现的任务锁
```

内置迁移manifest含72份六类数据缓存和8份reflection。没有把用户历史内容放进源码；这些80份内容未上传，本次不能独立核对本机迁移后的真实数据。构造owner时会实际核对每份已批准文件，缺失绝不当空历史或自动回到旧根。新生成缓存单独ledger绑定；已批准历史内容不同则拒绝覆盖，不自动升级/修复旧内容。

反思仍按 `prediction_date < target` 且 `eval_date <= target` 可见；最近5条喂prompt，全部可见历史进scoreboard，保留30样本阈值。没有新增反思写入、回评、用户verification写入或旧server/main。历史缺失明确CANNOT_CONFIRM。

## 4. 原始请求与来源身份

同provider/endpoint/session/semantic params的成功和失败由一个owner复用。只有时间戳cachebuster `_` 从key剔除；代码、窗口、分页、fields、fid、fs、日期均保留。Fuyao的date_ms还单独解析回UTC+8请求场次，不能把历史请求标成当前目标日。

实际离线证明：

- 旧两次独立高层池读取需要6次fixture SDK调用；新情绪+市场事实+情绪指标同日三池共3次，输出不变。
- 16个线程请求同一raw key，底层fixture仅1次；不同日期/窗口不共用。
- HTTP失败重试3次后复用失败，第二高层请求不再发3次。
- Fuyao两页响应重复读取，物理fixture HTTP共2次；错日期第一页就拒绝，不启动问财回退。
- 已批准market_facts schema3含raw时，三池读取0次新transport；不把不含raw的旧摘要当完整原始响应。

这里SDK边界计数是 `physical_transport_calls`，**AkShare内部HTTP请求数/重试数仍CANNOT_CONFIRM**。HTTP直接适配路径的计数是实际fixture HTTP调用。不能将它们合并声称全平台流量减半。

每个source文件保存该输入的**保守全集**raw/cache依赖，不声称已细分到每个字段。18个source引用由receipt绑定，prepare和graph结束时实际重读bytes/SHA/身份。raw中acquired_at是owner捕获时钟；请求/返回日期验证不等于供应商签名，不是PIT预测证明。缺少返回日期回显的来源明确标 `CANNOT_CONFIRM_WHERE_PROVIDER_OMITS_DATE_ECHO`。

共享资讯仅消费显式日期/查询/时点/SHA输入；没有检索CLI或额外新闻抓取。其schema为 `v4.vibe_news.v1`，target_date、data_as_of、query、text、status及source_id必须由现有authority绑定；缺失时保留原可选输入降级。

## 5. 模型工厂与独立运行

实际选型来自附件：DeepSeek 1M，selector=cc-switch-deepseek，provider_id=deepseek-claude-code，app_type=claude，quick/deep均deepseek-flash、temperature=0.6、timeout=180、max_retries=2、内置research prompt。没有改选型。

工厂实际读取显式SQLite数据库中该行，核对model slot与base URL，用原选择转换出的OpenAI兼容base URL构造两个ChatOpenAI客户端。它检查实际client.model_name/openai_api_base/temperature/request_timeout/max_retries，不只相信调用方标签。模型调用与错误脱敏代码已实现，不是TODO。

凭证仅在内存里交给SDK：源码、profile、source manifest、receipt均无token。数据库按bytes读入内存SQLite查询，避免SQLite在原目录创建journal/shm；**非空WAL会拒绝**，需数据库owner提供一致只读快照/已检查点版本，本代码不执行checkpoint或写凭证库。

Fuyao支持显式只读 `{"api_key":"..."}` 配置文件，内容不进证据；未提供时可读批准原因缓存。旧Iwencai client协议实现未随附件提供，不猜接口；其既有列日期校验与分页函数已迁入，可注入已审client，但公共CLI不偷偷加载旧应用/问财CLI。Fuyao或已批准原因缓存可用路径均已有实现。没有此可选来源时说明题材缺口，不换数据定义。

依赖没有换版本、未修改pyproject/uv.lock；真实LangGraph/langchain_openai/akshare由本地已审核V4运行环境提供。本容器安装尝试DNS失败，未假装安装成功。

## 6. 调用方明确配置

此配置是**非秘密示例，不是运行默认值**，所有路径和SHA由唯一Writer在隔离候选中填入并交Reviewer批准：

```json
{
  "schema": "v4.vibe_assembly.v1",
  "state_root": "/ABSOLUTE/V4_STATE/vibe",
  "cache_root": "/ABSOLUTE/V4_STATE/vibe/data",
  "cache_manifest_path": "/ABSOLUTE/V4_CODE/domains/research_review_generation/HISTORICAL_CACHE_MANIFEST.json",
  "cache_manifest_sha256": "92720cc3a6346afaba0efa995452da1304848ed0a52345c667682cd1775ed54d",
  "profile_path": "/ABSOLUTE/V4_CODE/contracts/vibe_runtime_profile.json",
  "profile_sha256": "1081c31d4f12e5ae62cbfe651c413c124d80794089a923c15e807e90170c249d",
  "credential_db": "/ABSOLUTE/READ_ONLY/provider-consistent.db",
  "data_mode": "collect",
  "data_as_of": "2026-09-11T15:05:00+08:00"
}
```

这是exact-date复盘来源as-of，不是把当前采集时间伪造为历史预测时点。data_as_of需随选定场次显式填写。可选 `news_binding={path,bytes,sha256}`、`fuyao_credential_file`、非秘密 `market_proxy`；`snapshot`模式必须增加caller批准的snapshot_sha256，不能隐式转collect。

本候选代码manifest SHA为 `0e3246057dfb1f0d5316f585d84f916afca68748e9ac1cb71ffc94342c3572b1`。这是**候选值**，需Reviewer批准；程序不会自行算一个新hash便把变更当已批准。配置文件SHA也必须独立传入。代码与state必须分离、cache是state子目录；不会改HOME或全局函数。

```bash
cd <隔离候选>/v4_app
python3.14 -m ops.run_research_review_generation \
  --date 2026-09-11 \
  --config /ABSOLUTE/APPROVED/assembly.json \
  --config-sha256 <APPROVED_CONFIG_SHA256> \
  --source-manifest-sha256 0e3246057dfb1f0d5316f585d84f916afca68748e9ac1cb71ffc94342c3572b1
```

成功exit0返回原writer回执，拒绝exit2返回三个false旗和安全原因码。已经存在产物时在构造模型或抓取前拒绝。`--replace`是明确重新生成授权，不在重复去重承诺内。崩溃发生在LLM收费后、artifact提交前时，重跑可能再次调用模型；这里不声称跨崩溃exactly-once或幂等计费。

若inputs已经存在，验证后原样复用，不重新抓取；配置/历史/源身份改变时拒绝，需显式新版本/新隔离state，不删缓存“解锁”。snapshot/collect没有第二个writer或后台任务。

## 7. A历史异常精确绑定（独立小补丁）

`contracts/a_known_history_gaps.json`直接来自附件exact-key证据，运行时文件SHA也固定；每个role同时要求批准seed SHA和完整354键集合，不能只比较354的数量。每个seed历史HK186/HK_FUND168。额外、等数量替换、缺失、全部消失、wrong seed和role全部拒绝。无异常的新干净seed不获得任何历史例外。

真实 `_audit_existing_history` 由函数级AST harness加载，以避开附件未包含的A框架；8例通过。原严格新增行门禁、key/value保留hash、atomic generation发布的原函数AST未变。没有修复或删除旧行，historical_health/full_seed_health仍CANNOT_CONFIRM。

用户本机既有12例、real9、accepted5147仅属附件证据，**不是本轮独立原始Parquet重放**。本容器缺upstreams等完整A依赖，相关原测试collection失败保留。

## 8. 本轮实际测试和证据

环境Linux/Python3.13.5。所有命令的完整参数/依赖版本/pytest exit在对应result.json，日志和JUnit同时保留；没有skip真实图或伪造StateGraph。

| 范围 | 结果 | exit |
|---|---|---:|
| 原始本次附件，baseline suite | 41 passed / 4 failed / 1 collection error | 1 |
| 候选boundary（含原31及本次新回归） | 88 passed / 0 failed | 0 |
| 候选真实graph（原2+新增CLI2） | 0 passed / 4 failed | 1 |
| 候选all | 98 passed / 6 failed / 1 collection error | 1 |

原46个案例/collection项没有缺失、结果状态逐项相同；新增59项：57通过、2个新增CLI图失败。状态一致不等于所有原行为证明；3个原测试/fixture文件明确修改以验证真实receipt、绑定后的client及新的安全合同，没有移除旧失败。

四个graph失败的当前环境原因是缺真实LangGraph。新增CLI确实先执行实际collector和receipt输入发布；相同CLI装配的公开入口probe记录19次合成raw transport、0次LLM、inputs存在、review未发布，随后明确 `real LangGraph dependency missing`。不能称为正向graph成功。原两个额外失败分别是个人旧Vibe目录不可见和API缺contracts.stages；A collection首个缺upstreams。

独立的已通过链：实际原计算/单一raw owner → 18source与真实receipt → snapshot → 原preflight；原五分析师/裁判函数链 → serializer → writer → exact reader；SQLitefactory真实行查询与client配置检查；同日锁前拒绝重复、并发singleflight、目录外写入拒绝、approved cache消失不可伪装miss、非有限计算值拒绝等。节点函数链不是LangGraph编排替代品，两者分别报告。

```bash
python3.14 verification/vibe_ownership/run_offline.py --suite boundary --evidence-dir /ABSOLUTE/ISOLATED/evidence/boundary
python3.14 verification/vibe_ownership/run_offline.py --suite graph --evidence-dir /ABSOLUTE/ISOLATED/evidence/graph
python3.14 verification/vibe_ownership/run_offline.py --suite all --evidence-dir /ABSOLUTE/ISOLATED/evidence/all
```

fixture只替换raw provider与最终LLM SDK响应；不会改HOME或生产模块全局函数。网络/子进程由测试audit hook拒绝。该hook不是操作系统沙箱；SDK自身真实外写、内部HTTP、DNS与网络出口仍需本机live审计。

## 9. 合并、复验与回退

交付ZIP是**附件范围完整源码**，不是全部canonical系统：49个原V4文件全部保留并含新增文件，参考源码和本地只读证据同时保留。不得整包覆盖本地唯一Writer的工作树。`previous_candidate.patch`仅历史参考，本次基线已经应用它，严禁再应用一次。

1. 使用 `verification/vibe_ownership/check_preimage.py --mode before` 对本次CHANGE_MANIFEST逐文件确认；任何已有文件SHA漂移/新增路径已存在都停止。特别是本地Writer并行改A时，不覆盖它、不reset；由唯一Writer逐hunk协调。
2. 在隔离副本 `git apply --check` 后应用本次统一patch；用 `--mode after`核对。候选所有代码manifest SHA须由Reviewer重新认可；不能沿用上一轮source manifest批准值。
3. 本地完整canonical环境重跑全部命令、两个原真实图和两个新CLI图；再核对80份真实历史缓存、实际SQLite模型配置及共享news。A在本地真实Parquet/完整authority上复验新增例外绑定和未变新行门禁。
4. scheduler最终接线、唯一owner盘点、自然分钟/并发服务验证及激活由本地Writer/独立Reviewer执行。本轮不改plist、服务、正式data或运行状态。

回退时先验证全部after SHA，再 `git apply --reverse --check` / `git apply --reverse`。源代码回退不自动删除本轮state/raw/cache/input；state与代码manifest成对留存。旧代码未审懂新输入receipt时不要共写同一个state。不得改HOME、删除历史缓存、清账本或同时运行两个生成器来“恢复”。

## 10. CANNOT_CONFIRM / 非本轮声明

- 本次新代码在本机Python3.14、实际LangGraph和真实ChatOpenAI上的全链成功：待独立Reviewer；已有旧图2/2证据保留但不冒充新代码验收。
- 80份真实迁移后历史内容、本地provider凭证、真实SDK/网络响应、全平台重复请求量及自然运行：本容器未取得。
- AkShare内部HTTP重试/外写；Iwencai原client实现未包含；新CLI不偷用旧服务替代。
- 完整A public/Parquet路径、用户real9/5147重新计算：未执行，原测试缺依赖保留。
- 不声明部署、停服、安全生产放行、自然验证或独立Reviewer已验收。本轮是实际已写代码、可逐文件复验的候选，而不是后续实施承诺。
