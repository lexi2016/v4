# PR16 A14:45 角色警告投影最小修复

## 业务目标与固定输入

消除同 producer / report_subject_scoring.v1 的 source 审计警告在原归档投影中的遗漏，不跳过最终完整投影比较，不新建日期或股票名单特例。

PR16 父提交 `84264c47a99d464d174b8180375c8701883b2bb5`。新证据提交 `b79d2dfad8cf260bd3288fee5150b8cad19011a9`，入口 `research/stage-pr16-mac-verification-20261001/review/independent_final_review.md` 与 `evidence/a1445/a1445_20260930_1400_projection_witness.json`。

实际运行前像不是 canonical 的旧 context，也不是远端9/28 27码旧补丁：使用 `bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/stage_scheduler/stage_center/research_context.py`，37,596字节，SHA256 `5e759ad9dd5057433d9beae465f6f46d7cf894b9bdf4d1b8fd44beaaca2eb104`，Git blob `ae431bee702465faa4fa7659fdaa9b343d01b953`。

后像36,605字节，SHA256 `e3dce4261dfe27c9d058b062991715f4894a3b309233f028ca62089559017095`，Git blob `116ed99fa00df55de50f57a9d4120426f8c084fc`。

## 唯一运行文件与派生规则

只改 `stage_center/research_context.py`：原日期/source-SHA/股票名单特例替换为同一生产者和策略身份合同；仍核producer/module及原四项源码/策略SHA。动态日期、slot、source SHA沿原来源传递，旧4码、新27码都由source.report_entity_audit给出。

先验证policy_version、affected_codes的原有有序唯一合同、excluded_evidence的research_subject_eligible=false及代码覆盖一致，再从affected_codes原序构造REPORT_ROLE_EVIDENCE_EXCLUDED警告。仅以重建投影已有非角色警告与source派生角色警告形成期望序列。archive只作比较目标，不能复制其警告填缺口；额外、缺失、乱序均拒绝。已经产生角色警告的builder也必须完整序列一致，不能删改它的额外差异。

保留 `_verified_hourly_slot`、source原字节SHA、archive/receipt/manifest校验、`_payload_base_sha`及最终完整投影SHA比较。仍仅去除stage_evidence_v1。其余articles/stock_pool等任一差异仍拒绝。没有修改shared archive builder、selector、R4市场保全、collector/provider、205摘要或授权逻辑。

没有把LATE_RECOVERY变成ORIGINAL_SLOT。15:00:02仍晚于15:00:00；1400来源的14:12:03保持原值。原时间验证函数和例外边界不改。

## 本轮实际原日志

只执行新增 `tests/test_pr16_a1445_role_projection.py`：最终RED 14 pass / 3 fail / 0 error / 0 skip，exit1；GREEN 17 pass / 0 fail / 0 error / 0 skip，exit0。红绿同一测试SHA `013e6abfc77a9762b80840d947735c97af4c4bc8cda1ce0a5fe1c2251a2cdd16`。旧8+2、18不重跑、不累计。

17项覆盖旧四警告/新27警告结构正例、producer/module/oracle/policy身份反例、审计策略/资格/覆盖/顺序反例、额外警告/文章差异/归档乱序、source/receipt/manifest破坏，以及150002拒绝后选14001203。测试使用真实archive builder、完整context、原存储和只读入口，合成source/97篇文章/47股结构不等于原历史数据。

最初两项乱序夹具在临时publish阶段提前被原schema拒绝，已改成先建立合法临时产物、再重封合成乱序，让reader接受测试；没有改产品校验。初始5 fail / 12 pass日志完整保留，不能把其中2项夹具失败当产品缺陷。最终红绿见validation/red.*、green.*。

作者环境Linux Python3.13.5；使用既有snapshot作导入载体。完整context按Git blob核准，builder/contracts/data_store与witness列出的字节SHA一致；其余依赖载体不冒充692文件Mac等价。没有重装依赖或为Linux修改业务规则。最终验收使用Mac当前服务Python3.14.6及现有依赖。

## Work唯一接续

1. 在已组装PR16的非活动隔离目录，读取上位规则，核context实际前像。等于5e759…才直接用本patch；等于e3dce…则复用；其他值逐hunk三方核对，不整文件回退。冻结handoff与活动release不修改。
2. `runtime.patch`仅包含一个运行文件；`complete.patch`包含同一差异和新测试，二选一，不能叠加。先 `git apply --check "$PACKAGE/complete.patch"`，再在隔离目录应用。旧已验的R4/digest文件保持现状。
3. 以原服务解释器执行 `"$SERVICE_PYTHON" -m pytest tests/test_pr16_a1445_role_projection.py -q --tb=short --junitxml="$REVIEW_OUT/a1445.xml"`，保存完整stdout/stderr/退出码。作者环境的`-o addopts='-W error'`只用于本容器不具备的旧warning类别，Mac沿其现有有效配置。按风险审核派生规则和完整比较，不固定模型身份。
4. 只有原source/archive在Mac可读时，再做下述只读回放。它不会启动Stage/provider，不采集、不执行selection、不写任何原件，不生成APPROVED或消耗额度。代码回退只应用rollback.patch，不动数据、receipt、manifest、授权或attempt。

## 原4076 → 811b只读回放

见证明确未复制原source（982,826字节）或archive（151,554字节），只有相等子树摘要和27个差异值。因此本轮未声称真的重放了4076/811b，也不要求上传它们或202行行情。

在Mac隔离源码已核after的前提下，使用原data root执行：

```sh
"$SERVICE_PYTHON" -B "$PACKAGE/tools/replay_a1445_projection_readonly.py" \
  --app-root "$ISOLATED_APP" \
  --data-root "$ORIGINAL_RESEARCH_DATA_ROOT" \
  > "$REVIEW_OUT/a1445_original_readonly.json" \
  2> "$REVIEW_OUT/a1445_original_readonly.stderr.txt"
```

原source：`4076de79920c43cfa57336c23262a491cd77730f29b4e1a530bc5ed9836ef571`。
原archive原字节/canonical/base在这一实例同为：`811b7803b540ec22c8e3f061804229e59fa51179f20a55a56ccc12d946af4af0`。

脚本要求读回1400和14:12:03，原receipt/manifest通过，调用原_bound_source_rows并完成整对象比较，原四件源文件前后SHA不变；结果应为PASS_READONLY_FULL_PROJECTION。回放失败保留具体异常，不修改警告或source凑SHA。脚本本轮没有以真实原件执行，不把提供命令算完成。

## 已验复用与仍缺证据

新独立审查报告：Mac3.14.6 8+2通过，692文件/50pin/5依赖一致。只引用报告，未本轮复跑或逐文件重验。current/run P2没有已证实实际漂移，本批不改guard、不新增放行门、不阻断此投影修复。

只剩这对原件的Mac只读完整回放、新context目标解释器验收，以及后续经批准真实Stage/API/UI读回。历史生产模块字节未知仅限制历史等价声明，不影响冻结源离线研发。部署放行独立，运行清单pin按既有流程核对，不自动全量repin。

原投影通过不是selection已恢复：现有202/205raw要经原Stage流程与明确授权另行验证selection、原consumer、普通API/UI的date/stage/market/run/hash/行序及NO_BUY/NO_TRADE/formal字段。现在均未执行。不跨日延长授权、不用09:25额度补14:45、不重跑五个A阶段、不修改HK归因或已修provider。

RESEARCH_ONLY；production_allowed=false、buy_gate_updated=false、orders_sent=false。PR保持Draft，Issue保持Open。
