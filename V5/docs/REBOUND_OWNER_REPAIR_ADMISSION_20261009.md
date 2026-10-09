# 超跌原owner回填与证据准入

本轮延续 `2d8e38ec61792b3e75581f96318e9c284f72b7ba`，仍在
`v5/rebound-owner-20261009`。P1/P2不变；V4源码、冻结vendor、经理、UI、现有daily代码均不改。
父已反馈2d8的recovery25+daily11在Mac单次36/36通过、550源码未变；这不是本轮新测试结果。
真实原生695文件中的2671计划缺口全部NOT_PRESENT，10/5–7各缺695；
10/5/6缓存各覆盖692目标，10/7只有HK00001收盘后。
Mac于2026-10-09T16:33:41.158289–16:33:41.165456Z仅补查一次配额：ret=0、used=99、remaining=1；
原返回明细96条、其中93码属695目标，保留差异。回执SHA
`74f9a1e38a01691a0f9942df2fc35b490b3c86fb180cd7506ea45767b5e806fc`。
OpenD服务正常，首次失败是异步连接脚本问题；历史请求仍0，694批量HOLD。
本轮不根据缓存旧×100结果或上述测试通过推断可正式选股。

## 已实现的实际调用链

原HK02 updater同根修复发布 → 私有child/parent/receipt快照 → 明确repair reader分支 →
原冻结两门数值计算 → 逐码源证据与目标资格准入 → 主分支共享账本持久化 → 经理消费。

`rebound_panel_repair.py` 是原updater调用点的扩展，不是第二面板producer。
普通append调用原 `update_hk_0_2_panel_from_vipdoc`；显式repair调用同一原模块的
`load_frozen_hk_0_2_assets`、`_read_vipdoc_increment`、`_enrich_vipdoc_increment`。
原源码SHA固定 `27da90f0e623e45fa1a27af7dcc3b6e5e1ff2320bae1c61bd903ed82050beb89`，
运行函数、同文件helper/globals/常量及原capsule内导入函数代码同时校验。
没有改V4文件或绕过真实model/name资产验证。

新增repair分支确实会写原asset root下的不可变revision和 `panel_latest.json`；
云端没有调用它。Mac先在完整owner资产的隔离副本执行，安装与真实authority切换另由父整合。
所有原writer的append/repair调用必须统一经过该wrapper，才有共享 `.hk02-updater.lock` 互斥与CAS。
若旧writer仍绕行原函数，单靠此锁不能防止外部写入；不能宣称已完成并发保护或允许激活。
这把锁只保护原owner面板发布，不是业务每日调度/运行账本。

## 原调用点的最小接线

在父接管的V5原owner调用点持有已验证原模块 `original_hk02`：

```python
from v5_shadow.rebound_panel_repair import (
    OwnerRepairAuthority, update_hk_0_2_panel_from_vipdoc,
)

# 普通更新：同一个原函数、同一个原asset_root，统一经过发布锁。
result = update_hk_0_2_panel_from_vipdoc(
    original_hk02, configured_asset_root,
    tdx_root=configured_tdx_root, through_date=signal_date,
)

# 显式内部补行：authority来自原owner部署绑定，不从HTTP/job JSON构造。
result = update_hk_0_2_panel_from_vipdoc(
    original_hk02, configured_asset_root,
    tdx_root=configured_tdx_root, through_date=signal_date,
    repair=approved_exact_request,
    authority=configured_owner_repair_authority,
)
```

已有 `hk_preselection._source_bytes()` + `_HKLoader` 能在新子进程隔离加载冻结原模块
`upstreams.v3_shared_data.shared_data.hk_0_2`。正式调用也可传现役原模块，但其源码/函数必须匹配固定SHA；
若Mac现役版本不同，先固定差异与依赖，不能把新版本说成已经验过的版本。

repair请求 `v5.hk02_internal_gap_request.v1` 精确字段：

```text
schema_version, through_date
parent_pointer_sha256                  # panel_latest.json实际raw SHA
parent_manifest_relative, parent_manifest_sha256
parent_panel_relative, parent_panel_sha256
keys: [{code: HK.00001, date: 20261005}, ...]
native_files: {vipdoc/ds/lday/71#00001.day: actual_raw_sha256, ...}
```

`keys`只能位于原 `rebound_history_sessions(through_date).prior60`，不得已有、重复、休市日、
目标日或未来日；窗口函数本身从原冻结源码提取执行，日期语句不改。每个key都须有原始记录，
部分可用时调用方只能提交真实可补的精确子集，不能填0补满。未补成员仍pending。

部署绑定 `OwnerRepairAuthority` 包含：

```text
asset_root, approved_request_sha256
capture_root, capture_relative, capture_sha256
```

capture文件 `v5.hk02_native_capture_binding.v1` 必须实际存在且由原owner审核绑定：

```text
schema_version
native_files                            # 与request完全一致
repair_keys_sha256                      # sha256_json(request.keys)
native_layout: <IfffffII
scale_applied: 1
conversion_applied: false
clock_basis: ACTUAL_CAPTURE_NOT_BAR_LABEL
capture_started_at, capture_finished_at # 实际有时区时间；不可晚于现在
```

该绑定只授权真实native字节补行，不证明SHARES/HKD/复权/完整日或所有旧历史的口径。
不能由缺口审计工具自签，也不能自动把请求自己的SHA当作部署审批。
原owner可信适配器可在验证实际来源后产生绑定；不要求每天重新向用户弹确认。
当前原生记录全缺时，这条分支不会凭空成功。已有缓存使用下面的显式raw分支。

## 已存PyTDX raw小样本适配

`rebound_raw_repair.py` 冻结原 `hk_daily_supplement.py`，SHA
`fa7dcbce4ee026b0a02c47220820d0407af183553d3304afcc5db425dce33cbd`；
源码来自已读提交 `74478a0e62be215c8527ccc9a14b89b51042d014` 的canonical handoff。
只提取原 `_finite/_bar_date/_decode_bar` AST，不导入或调用原采集器。
原decoder读取 `open/high/low/close/trade`；amount可缺，trade保持原值和scale1，
不转换成float32 `.day`，不使用原缓存中未经证明的×100结果。

同一publisher的raw请求除以下差异外与native请求相同：

```text
schema_version: v5.hk02_pytdx_raw_repair_request.v1
sources: [{relative: raw_capture.json, sha256: ACTUAL_RAW_SHA,
           record_pointer: /records/0}, ...]  # 替代native_files
```

`tdx_root`参数在这个明确分支指向已保存raw根。`record_pointer`是由原owner绑定的精确RFC6901位置，
必须指向原fetch的单个record；不猜容器、不把wrapper和sidecar默认互换。
record必须含原 `code/request/request_sha256/source_rows/response_sha256/returned_count/status/error_code`
及 `request_started_at/response_acquired_at/request_finished_at`。
request market=71/category=4、代码、start/count与SHA全部校验，source_rows响应SHA和记录数校验；
三时点有时区、有序、不晚于现在。重复来源/日期、未来行、缺key或单位替代字段volume均不能补行。

raw的authority.capture绑定文件为：

```text
schema_version: v5.hk02_pytdx_capture_binding.v1
raw_sources_sha256: sha256_json(request.sources)
decoder_source_sha256: fa7dcbce4ee026b0a02c47220820d0407af183553d3304afcc5db425dce33cbd
repair_keys_sha256: sha256_json(request.keys)
scale_applied: 1
conversion_applied: false
clock_basis: ACTUAL_CAPTURE_NOT_BAR_LABEL
capture_started_at, capture_finished_at  # 严格等于真实records的request start/finish包络
```

新增行继续交同一个原 `_enrich_vipdoc_increment`，发布到同一asset root的
`panels/<signal>-raw-repair-<sha12>/`，source contract末段为 `+pytdx_internal_gap_repair`。
回执为 `REPAIRED_RAW_ROWS`；lineage绑定parent、raw文件SHA、record pointer、原source row index/SHA和decoderSHA。
单位和价格依据仍未证，不能据此宣称选股成功。

Mac已给HK00001的10/5、10/6、10/7原trade=`45276/38090/47348`，capture为
2026-10-07T22:07:41.136988–22:07:41.160969Z，rawSHA
`0f45a1f19a0882e2c96ff0c2c0d94d8cabcd26f7305dc0c1e292130c35de5ddf`。
该raw文件不在云端仓库；仍须Mac只读确认实际record pointer及上述原record字段。
若文件实际没有这些字段，不允许现场编造包装或采集时点使其通过；保留具体合同缺项。

## 回填保证与明确边界

- 原parent parquet先稳定SHA复制为私有文件；model/name继续原loader验证。
- 仅复制白名单 `.day` 中精确缺失key的原始32字节记录，再交原reader解析。
  单码重复日期、残缺记录、SHA漂移、非有限/非法OHLC拒绝；trade=0是实际值，不是填0。
- 逐缺行按严格历史prefix调用原enrich，非连续缺日也会看到中间已有原行。
  不让10/8收盘成为10/5前收盘。旧行全部保留；后继原行派生字段没有重算，manifest显式标注。
- 新parquet写入后反读，检查新增数量和所有旧行值；parent pointer/model/panel再次校验。
  new manifest、receipt均写完并验证后才CAS切pointer；原panel不改。
- 同请求在pointer已切后重试读回已有结果；pointer尚未切的完整/半成revision可按同一请求继续，
  不重写原manifest时间。不同请求碰同内容而lineage不同会拒绝覆盖。
- 输出是 `REPAIRED_NATIVE_ROWS`、`formal_eligibility_verified=false`。
  `NOT_EVALUATED`与原生未知单位保留，不能当成全历史准入。

新source contract为
`tdx_vipdoc_71_day+verified_zero_trade_repairs+native_internal_gap_repair`，
不是旧 `+futu_history_gapfill`，不会伪造后者的provider/coverage字段。
revision位于 `panels/<signal>-native-repair-<sha12>/`，包含parquet/manifest/receipt。
**先安装消费者的新reader分支，再激活writer。** 原V4 reader不识别这个新合同，
本轮没有悄悄修改它或把新revision伪装成已兼容旧合同。

## 修复面板接入原计算

`rebound_observation.py` 仅增加这个明确source contract的读取分支，仍复用原数值AST。
已有legacy panel路径不变，旧 `ecf247…` 实现产物仍可只读回看；新准入要求当前实现的新观察。

新观察请求仍是 `v5.rebound_observation_request.v1`，`paths` 指向child manifest/panel；
`files`精确绑定以下5份文件（均带 `assets/hk_0_2/` 前缀）：

1. child manifest
2. child parquet
3. child receipt
4. parent manifest
5. parent parquet

读取器验证child/parent/receipt SHA、实际发布时序、原updater身份、精确修复key及原行定位/SHA，
并实际反读两份parquet，核唯一key差集、旧行逐值完全一致（check_exact=True）及SHA复检。
只证明修复字节与谱系，不将其标成HKD或FULL_DAY_CLOSE。
两门原计算完成后，再进入下面的有证据准入路径。

## 逐码准入与经理/每日主分支

完整合同见 [admission候选文档](evidence/rebound-admission-candidate-20261009.md)。
每个正式研究输入需67个原owner证明的cell：前60个精确session high、signal close、六个精确full-session trade。
逐cell与私有panel一致；价格基准/尺度、六日量单位/尺度一致，实际provider capture和可用时间不晚于cutoff。
已审核日线产品合同加实际session完成后的capture可证明用途，不要求不存在的provider final字段。
金额、股本、市值、上市日、手数、20条背景、natural验收不成为新的两门条件。

可信源合同、原decoder/document/owner身份、attestation与当日资格原帧SHA从独立部署配置读取；
请求只能选择已绑定证据ID。有证据的代码可进入strict/near/excluded，其evidence返回
`status=OWNER_VERIFIED`、`scope=ONE_CODE_EXACT_60_PRICE_AND_SIX_VOLUME_SESSIONS`；
其余逐码pending，不把一个代码的证明变成整面板或full-master VERIFIED。
698目标成员中缺signal行情的代码也计入pending，不能静默以695为完整目标范围。
15:00:08资格记录只表示该真实时间的资格，不冒充盘前；历史股本主档不能替代今日资格。

父主分支共享账本调用顺序：

```python
# shared ledger claim/input identity already includes source, proof and membership refs
observed = run_rebound_observation(bound_panel_request, observation_root)
selection = admit_rebound_observation(
    observation_root, observed['reference'], authority=deployment_authority,
    attestation_id=approved_owner_evidence_id, membership_id=approved_membership_id,
)
# shared ledger persists selection + selection_sha256, commits and independently reads back
selection = manager_admitted_selection(
    ledger_readback, target_date=target_date, signal_date=signal_date,
    research_cutoff=manager_cutoff,
)
# manager stores this exact saved reference in its input identity/payload
```

不要调用本分支旧 `rebound_daily` 再包一层相冲突账本。新代码不新增每日scheduler/ledger。
主账本应把native计算成功、研究准入PARTIAL/READY、最后成功引用、最近失败尝试分开；
失败不清旧成功，坏超跌lane不阻断公告/US，GET不重算。未有本轮真实Mac证明前不标自然成功。
当前观察日期语义仍为实际HK当天target、前一完整session signal；收盘同日/次日草稿不在这次升级内。
实际云端时钟已到2026-10-09T16:46:03Z，即HK10/10，不能新建10/9 CURRENT并通过准入。
10/9隔离修复不受此限制；若要正式回看消费，须由父明确接入回看合同，不能回拨系统时间。
后续normal append仍执行原函数，父消费者须沿parent SHA保留修复证据，不能因旧source_contract重新出现而恢复旧虚假标签。

## Mac独立测试

```bash
PYTHONPATH="$PWD/V5/src:$PWD/V5/tests" "$PY314" -B -m unittest \
  test_rebound_panel_repair test_rebound_raw_repair test_rebound_admission test_rebound_observation -v
```

`test_rebound_raw_repair` 的合成缓存测试不代表Mac真实raw已经匹配。
repair synthetic候选使用固定源AST的原reader/enrich；真实model loader/源模块校验在synthetic中明确mock，
不能声称真实owner资产通过。native真实模型与隔离副本用 `V5_REBOUND_REPAIR_ORIGINAL_TESTS=1`，
加 `V5_REBOUND_REPAIR_REAL_INPUT=/absolute/path/binding.json`（完整字段在测试文件头部）。
raw真实路径用上述绑定请求调用同一wrapper，在完整owner资产副本执行；本轮未执行。
admission候选明确stub已提交观察和panel接口，验证可信配置、cell范围与正负准入；不冒充真实供应商证据。
原算法差分继续用 `V5_REBOUND_OBSERVATION_ORIGINAL_TESTS=1` 执行既有测试。

本轮云端仅AST/compile/源码SHA/白名单diff检查，所有新产品测试 **NOT_RUN**。
需要Mac回传：真实缓存字段/解析器SHA、当前行情服务能力、可补原始行、原owner回填前后SHA和差分、
逐码准入证明、主账本/经理同run读回。尚无10/7全覆盖或可信量价证据时，继续保留具体pending，不改规则凑候选。
