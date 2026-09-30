# Issue #10：全量分钟输入只读诊断；观察模式尚未接入

Refs #10。基线 `3d03ca4ade08ac4c5f3f049756997d3934c782e3`，base `codex/stage-selection-mac-resume-20260929`。本 PR 与 A 股 #11 分离。

**本次只交付可执行的完整输入记账检查和合成测试。港股盘中观察池、runner模式、预选池/API/UI接入仍 NOT_IMPLEMENTED，本PR不能关闭 #10，也不能作为生产准入。** 没有改原D-1验证器、collector、materializer、Stage runner或任何页面。

## 已知断点与证据边界

issue报告：9月29日原Futu采集失败，9月30日所需严格D-1池缺失；本日12:55左右成功的原collector canary不是昨日收盘池。用户只批准20260930下午的“盘中恢复、仅观察”例外。原D-1缺失状态应继续可见，不能改名旧池或伪造STRICT_0_2_READY。

原HK链：原Futu capture → 原materializer/预选池 → runner._build_hk_stage_binding → hk_input_validation（D-1日期/100行/身份）→ hk_candidate_authority → 原ExHQ下午分钟 → 原RawStore/selector/SelectionStore → 原API与UI。

当前有两个独立缺口：

1. 现有runner的prior-pool observation只适用于HK开市而Connect关闭，不是本次Connect正常日的盘中授权。必须实现明确的一日授权binding，不能删D-1校验或复用另一种授权。
2. 64代码canary仅保存3条sample。即使摘要称missing=0、每只14bars，也不能从摘要恢复完整输入。必须由既有owner保留全部实际SourceResult.rows及原manifest/receipt/hash；不能让诊断器另抓同源或补造其余61条。

GitHub现有源码/issue标识不包含实际12:55capture原件、64行完整输出、最新部署采集wrapper及两个部署owner的全部差分。这里没有取得用户本机closeout文件，没有复核真实686报价或64行历史分钟；下述64/3/61是确定性合成复现，不是新的行情验收。

## 已实现：ops.inspect_hk_observation_rows

输入必须是两个明确路径、分别以字节SHA绑定的JSON文件：序列化的原SourceResult对象和请求代码list。通过已有SafeRoot只读读取，不遍历目录、不用latest/mtime、不连接行情服务、不写池或数据。

SourceResult字段：`source_id`、`status`、`requested_rows`、完整 `rows`、`missing_symbols`、`cannot_confirm`；行内使用原 `code` 和完整日期时间 `update_time`。不读取sample代替rows。无法直接匹配本机wrapper时先在现有owner边界作无损投影并保留原件SHA；不得猜字段、伪造更新时间或将摘要变成完整数据。

验证：

- 限20260930、STAGE_1300_1315或STAGE_1445_1500的ExHQ行记账。AM、其他日期、Stage8均不纳入此检查；Stage8应保留自己的RT_DATA合同。
- 请求代码非空唯一、HK格式；请求数与明确list长度一致。
- 行代码唯一且属于请求集；显式缺失集合唯一、在请求范围且不与已有行交叉。
- 每个请求代码必须在完整rows或明确missing中得到解释。请求64、保存3、missing空 → `unaccounted_code_count=61` 并列出差集，状态INCOMPLETE_OR_INVALID。
- 行时间必须有完整日期，落在准确下午窗口；13:15:00.001不能按秒截断后变成合法。原完整naive时间按香港时区解释并明确报告数量/假设，不假装输入已有时区证据。
- 保留原cannot_confirm。63有效+明确1缺失允许记账完整，但不提升成完整行情或准入。

输出只有 `ROW_ACCOUNTING_COMPLETE` 或 `INCOMPLETE_OR_INVALID`。即使全部64行记账完整，以下字段始终false：`bar_series_verified`、`pool_membership_verified`、`observation_pool_admitted`、`stage_selection_generated`、`api_ui_verified`、`write_performed`及全部交易安全位。**它不核每根bar顺序/数量/价格，不证明producer/PIT/授权，也不表示Stage恢复成功。**

已有本机证据、明确路径及SHA具备后，可由owner在隔离源码环境只读执行：

```sh
"$SERVICE_PYTHON" -m ops.inspect_hk_observation_rows \
  --root "$EXPLICIT_EVIDENCE_ROOT" \
  --source-relative "$FULL_SOURCE_RESULT_JSON_RELATIVE" --source-sha256 "$SOURCE_FILE_BYTE_SHA256" \
  --codes-relative "$EXPLICIT_CODES_JSON_RELATIVE" --codes-sha256 "$CODES_FILE_BYTE_SHA256" \
  --trade-date 20260930 --stage-id STAGE_1300_1315
```

这里只是检查命令，不会生成缺失数据。代码文件/输入原件仍放隔离目录，不复制到活动release。

## 实际测试

```sh
python -m pytest -o addopts='-W error' tests/test_issue10_persisted_rows.py -q
```

作者Linux Python3.13.5 / pytest9.0.2实际 `17 passed in 0.07s`，exit0。覆盖64/3不完整、全量仍不准入、真实声明缺失、重复/越界/错误日期/AM/亚秒越截止/sample/失败源、字节SHA变化及只读不修改文件。全部是SYNTHETIC JSON，不是Mac行情。新诊断函数缺失时的初始失败不作为旧产品真实故障数量统计。

与 #11 共用隔离测试依赖缓存，两个新文件按最终远端blob核对；没有修改仓库pytest配置、依赖、CI或服务。Linuxoverride仅处理容器缺少仓库warning filter类别，仍warnings-as-errors。目标Python>=3.14、完整Mac环境、真实业务和浏览器均未验收。

源码SHA256：`ops/inspect_hk_observation_rows.py = 0a4887d21e5bfbfd9921a03c6b251888490290a713157bcd540a196d001e5409`；测试SHA256：`tests/test_issue10_persisted_rows.py = ed0781fde5a10523d4fe1aa544e36e12b6d981ea30f0b77300ad095bef2c2029`。

## 尚未实现的接入与最小缺口

不能仅为让页面出行而绕过严格D-1。下一步仍需在已有owner链完成：一日授权的真实capture绑定 → 原预选池单独标注观察角色/来源 → 原runner明确模式分支及HKauthority语义 → 全量分钟不可变保存 → 原selector与store → 原API/UI同run/hash和观察标签。A股、正式D-1和其他日期保持原合同。12:55才获得的池不得用于上午时点，快照价格不得代替下午分钟指标。

为避免与本机隔离候选或部署后的修复冲突，最小补充可直接提交到现有GitHub分支，不要源码ZIP：

1. 当前两个owner（Stage scheduler、8873 API）的release/入口/模块相对路径与SHA，以及和3d03基线有差异的本次涉及函数；尤其 runner输入绑定、HK authority、collector wrapper、预选池投影。无需上传整个项目。
2. 原12:55capture manifest/source wrapper的字段名、类型、真实captured_at、source_date、row_count、raw/source/manifest SHA及producer身份关系，给脱敏结构即可，报价可留本机。不能仅给SHA字符串而不说明它绑定哪种序列化对象。
3. 原64请求代码list及其字节SHA、是否存在完整SourceResult或原始输出文件、其路径/字节SHA/行数/明确missing。完整行情留Mac；若确实只有3条sample，必须由原owner进行一次获准的完整保存，不能从3条重建64条。
4. 现有观察池隔离候选的合同/相关最小diff（如有），避免重造producer或覆盖本机新修复。

issue报告的raw/source/manifest SHA是接续核对标识，不等于本PR已经读取这些文件。独立Reviewer须先核原来源/授权/全量输入，再单阶段canary，最后API/UI；不得用17项诊断测试替代。#10保持open/NOT_IMPLEMENTED，#11不混入本PR。

RESEARCH_ONLY；production_allowed=false；buy_gate_updated=false；orders_sent=false。没有新producer、正式记录修改、部署、真实采集、选股或API/UI验收。
