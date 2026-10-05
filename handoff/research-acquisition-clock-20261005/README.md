# Research acquisition clocks：限定前向修复候选

状态：云端源码和合成行为 TESTED；Mac 接入、部署、自然运行、真实 US 关系恢复 CANNOT_CONFIRM。未连接 Mac、未部署/合并、未重写旧档案、未采集真实行情。PR26 已有本机验收不在本轮修改范围。

## 身份与边界

Git 基线 `09a987cec75760aa6665e5529a555af9c3e2e785`，源码来自其中 `handoff/v4-running-source-20261005` 的 API snapshot（881 个源文件）；不是 main，也不是完整当前 R13。canonical snapshot 是另一拆分结构，不可用本包 monolithic research_hourly.py 覆盖 canonical。

父线程只读 Mac 回报的 R13 `domains/research.py` SHA `2ad669ea58f08338605885547ec065921ec63cc0047460bb2acd153151fb214b` 与 `ops/run_hourly_research.py` SHA `58e23282617195116ec69835c14dd419b8f88861464ced0714a4a5ca0934824b` 均与本次 API 前像相同。其余三个修改目标尚无活动本机 SHA；文件存在和两处相等都不能证明哪个定时 job 在生产当前 archive。

仅五个 runtime 文件改变，详见 changes.json；before/、after/ 为完整前后像，runtime.patch 为最小差异。既有 R14 的 router/service/announcement_analysis/三个公告前端投影及 businessStatus 共七个文件均未触碰；R13、Stage、BUY、资格、自然预算、US consumer gates 和 run_hourly_research.py 未修改。881 文件基线其余 876 原字节保留，新添测试另计。

## 复现与修复

原 ZSXQ `fetched_at` 在分页请求前生成，不能当完成取得时间。正常化数据结构和 build_research_archive 丢失 acquisition pair；既有 US consumer 按合同报告 ACQUISITION_TIME_MISSING，不能靠 event_time/mtime/当前时间修补旧材料。

本候选沿已有链：run_zsxq_hourly_delta → collect_hourly_research_input → research_hourly → 原 run_hourly_research → build_research_archive → 原不可变 archive store → existing_materials → issuer_us_relations/research_evidence → research_attention。

- 分页 CLI 全部完成后记录 retrieved_at；原摘要持久化完成后记录 available_at。后者精确定义为 DERIVED_SUMMARY_PERSISTED，不表示官方首发或 Manager 入库时刻。批次完成时刻对每条材料是保守上界。
- 新 receipt 绑定 run_id、摘要路径/原字节 SHA；输入 reader 再绑定 status 路径/原字节 SHA 并检测读取竞态。缺少、损坏或时序非法凭据保留原材料，采集时间仍 unknown。
- 三字段完整扩展 `{retrieved_at, available_at, acquisition_provenance}` 穿过原标准化和档案合同；旧字段集合仍合法，不升级旧 archive。去重合并遇到不同凭据时剥离扩展，防止较晚句子借用较早时钟。
- 新时钟进入既有 slot PIT 校验，未改变原截止或原明确 verified-late-recovery 规则。新有凭据输入声明原 runner 必需的 slot pit_cutoff（选择边界，不是 acquisition clock）；真实 runner 测试曾因缺该声明失败，见 runner-pit-red.log。
- 不直接升级建议；合成正例经过现有双源、主体、时间门槛才形成关系；生产/订单开关仍 false。

此为兼容旧数据的读取扩展，但旧版严格字段 reader 不能读新版扩展文章：未来采用时五文件须按同一版本组合，在实际 producer 与 reader 所属根验证兼容后接入。不能只装 producer，也不能用本包整树替换当前 release。

## 云端验证

Python 3.12.14 / pytest 9.1.1；工程声明 Python >=3.14，Mac 原生版本待验。测试中的题材、股票、US 来源和时钟全部合成，不是历史/真实行情；只替换外部 CLI 与 analyzer lookup port，其余使用原保存、runner、SHA、archive reader、关系及 Manager 函数。

最终六套：**124 passed，1 个 Starlette deprecation warning**，含新增 19 项。red-final.log 保存最初三项有效 RED；runner-pit-red.log 保存原 runner 缺 PIT 声明的 RED；core-final.log 为最终 GREEN。覆盖真实函数链到 Manager、缺钟/逆序/迟到/坏 SHA/错路径/错 run/错主体/第三方句子、旧 archive、旧 status 重用、来源 SHA 拒绝、重试字节不变、扩展字段完整性与合并不同凭据。

```sh
python -m pytest -q tests/test_research_acquisition_clock_pipeline.py tests/test_research_archive.py tests/test_hourly_research_runner.py tests/test_research_hourly_regressions.py tests/test_us_relation_pipeline_r2.py tests/test_us_relation_assessment_state.py
```

扩展检查不是全绿，且早于最终 PIT 声明配套修改：regression-final.log 为 132 passed / 7 failed；另一次 graph 相关扩展为 124 passed / 1 failed。缺 `tests/fixtures/research/manifest.json`、原 decisions manifest、`docs/evidence/phase6-hourly-research-idempotency-20260801.json`，以及 dry-run 发布 RELEASE_IDENTITY 缺口，在未改的 API 基线复跑相同三套也出现，共 10 passed / 8 failed（baseline-blocked-tests.log）。没有刷新 release pins 或伪造 fixtures。该扩展不代表最终版本全仓回归通过。

原前端两套检查 18 passed / 2 failed：失败是既有公告 NOT_RUN/NOT_MATERIALIZED、Eastmoney owner 两个断言与更严格 official proof 状态不一致；前端字节完全未改。US 四态及 unknown 与 zero 的已有断言通过，另精确 US 四态筛选 1 passed / 9 skipped。未复现 US unknown-as-zero 的新问题，所以不改 UI。详见两个 frontend 日志。

patch 正向、反向分别 5/5 SHA 一致，见 patch-check.log。未运行全仓、333MB 回放、真实数据采集、完整前端构建/typecheck、服务/API/UI、自然时段；云端合成成功不证明真实 84 条输入修好。

## Mac 接续：先身份，再隔离验证

仍缺的最小现场证据：实际 archive producer job/plist 的入口参数与 source root/data root（去除凭证），本五文件及 runner 的真实路径/SHA；一条原 archive 的 source_input_sha256、对应原 source witness，以及那次 capture 的 status/summary/receipt 路径与 SHA。US digest label/runs=0 不能替代此绑定。只读收集这些信息即可，不需要全量 archive/原始行情上传。若 producer 是 canonical 拆分版，按函数差异适配并独立验证，禁止直接覆盖。

本包不包含自动部署脚本。仅在全五前像一致的**新隔离候选根**执行，以下 PACKET、CANDIDATE 均应设置为绝对路径：

```sh
python "$PACKET/verify_sources.py" "$CANDIDATE" before
cd "$CANDIDATE"
git apply --check "$PACKET/runtime.patch"
git apply "$PACKET/runtime.patch"
python "$PACKET/verify_sources.py" "$CANDIDATE" after
cp "$PACKET/tests/test_research_acquisition_clock_pipeline.py" tests/
# 用候选原生 Python 执行上方六套命令；不调用自然采集，不重写历史。
```

任何前像不一致立即停止覆盖，仅适配本最小差异。五文件同版本还不等于已证明生产入口；验收前应先补齐 producer 绑定。

隔离候选回滚（确保 after SHA 仍全部一致，无他人新改动）：

```sh
python "$PACKET/verify_sources.py" "$CANDIDATE" after
cd "$CANDIDATE"
git apply -R --check "$PACKET/runtime.patch"
git apply -R "$PACKET/runtime.patch"
python "$PACKET/verify_sources.py" "$CANDIDATE" before
```

回滚只处理这五个源码文件；不删除测试或任何数据，不改运行包、plist、端口。对已产生新扩展数据的生产切换/回退必须另行审核 reader 兼容性，本轮未执行或授权此操作。
