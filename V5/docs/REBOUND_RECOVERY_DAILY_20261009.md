# 超跌14恢复与每日执行交接

基线 `2edcc42204f6e319da9df8cad7578d9f6eaf13b3`，分支
`v5/rebound-owner-20261009`。保留原 P1 三条经理业务链、P2 来源准入顺序。
本轮只增加独立恢复工具、每日入口、Mac 回归候选与文档；不改 V4、冻结 vendor、
`manager_plan.py`、UI、行情 producer 或现役调度。云端产品测试、数据采集均 **NOT_RUN**。

## 结论与真实边界

当前父反馈的695条原生观察，完整输入0/695，不能交付为选股。
恢复需要处理三个不同的问题：面板内部日期缺行、价格/成交量口径证据、reader 的可准入代码路径。
根目录已绑定或数值已补齐都不足以解决全部问题。自然运行验收另列，不作为手动研究选股的算法条件。

| 根因 | 可定位证据 | 最小恢复动作 |
|---|---|---|
| append 不能修内部缺日 | `handoff/v4-running-source-20261005/canonical/upstreams/v3_shared_data/shared_data/hk_0_2.py:599`，through_date<=max直接already_current；618只读after_date=max | 既有owner增加显式内部gap repair，不能继续仅运行append |
| 10/5–7价格和量缺失 | 父反馈现有面板/观察，具体code×date以本工具读回生成 | 先读本地原始VIPDOC与未转换capture，未满足的字段才提出受限补采 |
| 较新reader无可达量证明分支 | `V5/vendor/manager_plan_baseline/v4/manager_research/workspace_plan.py:918`和961始终NOT_PROVEN；1266要volume_proven才计算比较 | 有真实跨六日口径证明后才增加明确reader合同，任意manifest字符串不准入 |
| 原入口先读精确日主档 | `V5/vendor/rebound_baseline/v4/manager_research/workspace_plan.py:862` | 原完整owner仍需真实10/8主档/receipt；独立数值观察已不需要伪造主档 |
| 每日缺独立调用和前置去重 | 本分支基线无rebound_daily；观察每次生成新UUID | 新rebound_daily供既有Mac dispatcher调用；安装/自然触发另验收 |

原两门仍为 `close <= 0.8 * max(prior60.high)` 与
`current_volume / mean(previous5_full_sessions.volume) >= 1.5`。
60天是原HK日历精确日期，前5天只取完整交易日。不能last60可用行、填0或改阈值。
旧两门screen的金额、低价反弹、pre_close、20条背景和3/5条涨跌都是观察项。
股本、总市值、上市日、每手数量不参与这两门；缺它们不等于量价不能计算。
但698条资格/名称不能假冒缺失的完整10/8主档、旧Futu snapshot或历史capture时间。

## V4单日入口新证据已核对

只读获取 `74478a0e62be215c8527ccc9a14b89b51042d014` 中
`handoff/manager-four-functional-gaps-20261009/package/`，未运行其脚本。
`actual_owner_runner_20261009/source/v4/manager_research/workspace_plan.py` SHA为
`c734f3e986af81b39bf11c09d93caf7a205526c8b4df940a4beeb011f74e0ebb`，
与本分支 `vendor/manager_plan_baseline/.../workspace_plan.py` 相同。
该版本仍没有量证明成功分支；runner只绑定 SCREEN_ROOT 后刷新原经理，未补历史。

其历史摘要保留run `ca77f41d26cd4c19b8a64237498f4256` 的READY_WITH_GAPS、
实际9月29日生成，以及其它计划的PARTIAL/CANNOT_CONFIRM。
10/9 isolated plan是PARTIAL、0股票、主档缺失；readback VERIFIED代表产品读回校验。
这些材料不能证明三路同日完整成功，也不能否定尚未定位到的其它历史入口。
本checkout仍未找到 `v4.hk_history_price_recovery.v1` 实际writer或其真实数据包。
一次性 `compose_historical_hk_0_2_seed` 不是当前authority修复入口，不能借用冒充。

## 本轮可执行工具

`rebound_recovery.build_recovery_plan(readback)` 先调用既有观察artifact验证，产生：

- `cells`：缺行的代码、精确日期及high/trade字段，去重合并；没有补采请求。
- `duplicate_cells`：原panel重复日期，交原owner冲突调解，不选择first/last，也不自动补采。
- `unlocalized_numeric_gaps`：已有非数值/当前值/零分母等仍需逐字段复核的问题。
  原观察仅有聚合计数，工具不会虚构这些问题的具体日期。
- source run、artifact/panel/manifest/calendar SHA、60/5窗口、业务要求与非门槛分项。

`audit_vipdoc_candidates(plan, request)` 仅打开显式列出的原始文件，
使用原 `<IfffffII` 布局、uint32 trade offset24、scale=1；不glob、不写输入。
SHA、同fd读取稳定性、记录长度、OHLC有限正值/区间均检查；同日重复拒绝选取。
真实trade=0保留；非有限amount单独保留为unknown，不把它加成两门门槛。
输出匹配record offset/SHA、原生值和四类结果，始终不证明单位、复权、终态或PIT。
最多2000个明确文件，单文件8MiB、总256MiB，云端不读取真实市场数据。

生成精确计划（Mac，已有观察root/reference）：

```bash
PYTHONPATH="$PWD/V5/src" "$PY314" -B -m v5_shadow.rebound_recovery \
  --observation-root "$OBSERVATION_ROOT" --reference "$OBSERVATION_REFERENCE" \
  > "$ISOLATED_OUTPUT/recovery-plan.json"
```

本地原始文件审计请求，SHA由Mac读取实际文件计算；只列plan cells涉及的代码：

```json
{
  "schema_version": "v5.rebound_native_audit_request.v1",
  "input_root": "/absolute/original/tdx/root",
  "files": {"vipdoc/ds/lday/71#00001.day": "ACTUAL_64_HEX_SHA"}
}
```

上述命令增加 `--native-request "$NATIVE_REQUEST"` 即可同时输出native_audit。
原文件晚于历史cutoff的读取只证明现在能看到这些字节，不能反推旧时可用。
`EXACT_NATIVE_ROW` 只是原生记录候选，不是正式owner准入、可发布面板或选股成功。

## Mac源恢复的顺序和请求界限

1. **零网络请求**：读计划与已有698资格原帧/manifest/receipt；核清其真实15:00:08获取时间。
   从原owner配置确认真正VIPDOC根，审计缺口code的 `.day` 10/5、10/6、10/7记录。
   查询10/5/6缓存的原始未转换响应、解析器源码与hash；现有×100派生值不能准入。
   10/7 HK00001的postclose记录只能覆盖自己，不能推成694代码完整。
2. **最多一次只读能力/额度请求**：在现有已授权OpenD连接使用
   `get_history_kl_quota(get_detail=True)`，保存ret、实际请求/响应时间、used/remain/detail及SDK身份。
   官方API明确返回历史K线额度及代码记录：[Futu额度接口](https://openapi.futunn.com/futu-api-doc/quote/get-history-kl-quota.html)。
   过去额度0不代表现在仍为0；零剩余额度也不能直接推断已在明细代码是否可复用，需按现连接实际返回核验。
3. **仅提出有界canary，不自动执行**：若当前来源授权/额度可用，父在原采集owner内先选最多3个
   `cells` 涉及且能力允许的代码，一码一次历史日线请求，日期仅缺口最早日到2026-10-08，
   显式K_DAY、AuType.NONE、无自动翻页/无限重试；保存完整原始字段和起止时间。
   [Futu历史K线接口](https://openapi.futunn.com/futu-api-doc/quote/request-history-kline.html) 支持日期与复权参数；
   此链接不证明当前Mac有额度，也不证明TDX和Futu可直接混量。
   原值最低必需code/date/high/trade及signal close/trade；保留OHLC用于原格式一致性校验。
4. **扩批由父根据canary证据决定**：剩余请求代码必须是缺口集合扣除有效本地/缓存记录；
   上限=min(已授权批量界限、当前来源能力、剩余缺码数)，每码最多一次本批请求。
   当前694码计划仍HOLD/0请求；本工具不升级它。分母六日必须同已证实量口径，
   不能只拿3个新日的Futu量混入未知旧量；必要时明确申请完整六个日期的同源量证据。
5. 原pytdx supplement固定start=0,count=6，10/9会挤入当日bar并漏掉10/8所需最早一日，
   `_decode_bar`会拒绝future row。不能直接作为10/8恢复命令。
   若父选择该源，日期范围/offset/count必须显式升级并验收；不能调用后悄悄删掉当日行冒充固定六bar合同。

## 原owner最小补丁方案（交父整合，本轮没有修改或运行）

**A. 内部gap修复。** 在既有HK02 owner而非新V5 producer新增独立repair操作：
读取已绑定parent panel与原始证据、显式missing code/date集合；重复/冲突行拒绝覆盖；
只增加缺行；旧行逐列不变；保留原name/source/continuity语义，不用未来记录回填pre_close。
输出新的不可变revision，以parent SHA、source raw SHA、修复row keys/字段、实际prepared_at闭合；
复算面板SHA、原60/5覆盖及新旧差分后由原owner更新pointer。
append的already_current仅代表最大日期；不可再等同窗口完整。
不能借用现有 `+futu_history_gapfill` 字符串：该reader合同要求固定provider、row_count、requested_code_count、
coverage1.0、时间顺序等；部分恢复或VIPDOC内部修复需明确新合同并同步reader解析，不伪造旧字段。

**B. 口径准入。** 修改原reader的两个证据函数时，只接受原owner发布、字节闭合的新增正式合同。
至少绑定具体panel SHA、每码exact60价/6日量覆盖、字段定义/复权方式、单位/scale、
来源与转换链、有效日期范围、capture/publication时间；跨源转换必须有显式依据。
当前始终NOT_PROVEN的函数要有真实证据可达的成功分支；缺项仍逐码unknown。
不得修改冻结vendor或把本观察的native comparison布尔值直接改成正式strict/near。

**C. 终态与PIT。** 业务要求是完整HK日线与实际可用时间，不是必须出现某个provider `final` 布尔字段。
可按确切日线产品合同、真实请求/响应在该session完成后的时间和owner校验来证明；
日历已到收盘、pytdx合成15:00、文件mtime或今天重读稳定均不能单独证明这一点。
无证据不能盖FULL_DAY_CLOSE章；有文档与实际capture证据时，不再以不存在final字段永久拒绝。
现在补回10/5–7数据只能用于现在及以后的cutoff，不能写回历史PIT成功。

**D. 主档/资格。** 原HK capture gate把同一capture交ensure master；优先恢复该原始capture路径。
`ensure_hk_security_master`无capture会重新OpenD请求，Mac不得误将其当纯读取。
若继续原完整owner，要真实精确日主档及receipt；若明确拆为数值计算+独立资格owner，
需分别绑定名称/资格的真实日期与capture，不把698成员投影伪造为全主档。

## 每日入口与经理接线

```bash
PYTHONPATH="$PWD/V5/src" "$PY314" -B -m v5_shadow.rebound_daily \
  --request "$TODAY_PANEL_REQUEST" --output-root "$OBSERVATION_ROOT" \
  > "$ISOLATED_OUTPUT/daily-result.json"
```

请求沿用 `v5.rebound_observation_request.v1`、RECORDED_INPUT_CURRENT，实际HK当天target；
禁止caller clock。原日历必须解析到指定signal；该模式不支持晚间next-session target。
输出根仍用现有 `.v5-rebound-observation-root` marker，新增daily/key中的claim/attempt/commit。
身份绑定request、输入SHA、原owner/capsule/adapter代码和实际Python/依赖环境。
同输入成功数值观察（即使0完整）不反复计算；source字节变化仍拒绝旧SHA请求。
失败产物保留且可由外部账本退避重试。并发同key立即BUSY；中断留下claim，不自动重算。
已有成功或失败trio可加 `--reconcile-reference "$ORIGINAL_REFERENCE"` 显式调解；
不运行owner。可跨日读回，但须保持原输入、实现/环境及claim身份；来源消失或实现已变，
交父按原运行环境核对，不删除claim或伪造引用。失败调解保留记录后允许合法当日重试。

此模块是每日**调用入口**，没有安装scheduler，仍没有正式选股准入。
父既有dispatcher先解析原owner日期和manifest，再调用此入口，保留P0退避/尝试限次/跨lane隔离。
不要把17:20源面板槽当超跌选股已完成；盘前迟到不能补成SCHEDULED_PREOPEN。
正式准入升级完成后，在相同账本后接正式owner，另验其same-run结果与receipt。

经理最小接线继续使用已交 `read_rebound_observation` + `manager_observation`；
引用应在原经理保存之前进入payload/input identity，随后发布同一saved product。
GET只读。正式screen与观察字段分开，不能将0/695或未证量比投影成有效空选股。
此分支经理未接线，父当前页面dabcfbee的集成情况以其Mac证据为准。

## Mac验收命令与成功标准

```bash
PYTHONPATH="$PWD/V5/src:$PWD/V5/tests" "$PY314" -B -m unittest \
  test_rebound_recovery test_rebound_daily -v
PYTHONPATH="$PWD/V5/src:$PWD/V5/tests" V5_REBOUND_OBSERVATION_ORIGINAL_TESTS=1 \
  "$PY314" -B -m unittest test_rebound_observation -v
```

新增测试隔离验证planner/native字节及daily账本；不冒充原算法真实运行。
既有原算法差分仍由后一个命令完成。真实数据验收需提供恢复前后panel SHA、差分行集、
完整/待确认计数、口径证明覆盖、strict/near/excluded/unknown分组与原算法差分，
之后才验经理同run API/UI与自然时段每日触发。当前数据接入、正式选股、部署和自然验收均未完成。
