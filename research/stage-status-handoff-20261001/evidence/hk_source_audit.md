# HK 自然链源码独立只读判断｜2026-10-01

审查者：`/root/handoff_source_audit`（独立 hkconnect-flow-reviewer，Luna Max）。本文件由主控整理其已返回的最终消息；审查者未写业务文件，未运行测试/采集/选股/服务。本报告为源码及血缘判断，不是本轮代码测试或部署 verdict。

## 已确认

- `evidence/api/preselection_20261008.json`：100行、STRICT_0_2_READY，source SHA `ce4e94229a1f1bf44c22a2390d577dbea3c81f588543221fb1ee12b9464cc040`；行 signal_date 为20260930。
- 原 run `20261008-hk-connect-d1-top100-0-2-8a0386afb66b` 的manifest/receipt生成时间均为2026-09-30T17:30:43+08:00，price signal与security_master_trade_date均为20260930；price panel SHA `151fbe...`、master run `49ffde...`（696行，artifact SHA `754794...`）。原manifest/receipt完整字节另存于 evidence/source_provenance，以其完整值为准。它不是10/7自然运行。
- 落盘 `preselection_pools/20261008/hkconnect_d1_top100.json` 缺顶层signal_date、target_date、stage_selection_eligible；API pool_source_bindings的 stage_reuse_status 为CANNOT_CONFIRM。READY是来源artifact状态，不能提升为正式Stage输入验收。
- `source/active/preselection_app/infrastructure/scheduling/executor_registry_preselection.py:263`至307：panel、ensure_hk_security_master --reuse-only、materializer共用request.business_date；物化仅传单个signal-date。
- `source/active/stage_app/stage_center/_runner_parts/hk_input_validation.py:143`以hk_connect推导前一signal日；shared_package/scripts/materialize_hk_0_2.py:16和shared_data/hk_0_2.py:1022也绑定同一价格/master日期。
- 原publisher已存在：preselection_app/ops/run_stage_center_tick.py:605、638、772调用 stage_center.hk_universe_preflight.ensure_hk_connect_universe。preflight:900至918、952至998只接受当前上海日期，读取全HK Connect plates并记录实际captured_at。预选owner没有调用该发布路径，master只reuse-only。
- 当前9/30 HK API具体错误为`HK security-master metadata invalid: '20260929'`。冻结r2的20通过与REVIEWED_WITH_P1保留；新证据只更新旧“10/8 Top100不存在”描述。

## 未闭环与停止边界

- 10/8的价格应来自前一HK证券日10/7；现存9/30信号run不满足此语义。
- 资格来源日期须由真实as-of、有效期、来源身份裁定；r2固定上一Connect日不是已证明唯一合同，不能替换为任意最近日期。
- 10/1尚无10/7自然authority/master可读；NATURAL_SLOT_UNVERIFIED，不能今天补造未来source。
- 历史9/30 union缺source-bound捕获时间，HK_CAPTURE_RECEIPT_CAPTURED_AT_MISSING仍成立。master自身17:20不能借给union；696成员或689价量覆盖均不能替代authority。
- 正式Stage使用该Top100仍CANNOT_CONFIRM。当前UI显示由主控另行观察，截图/DOM在evidence；审查者未验证UI。
- production_allowed=false，buy_gate_updated=false，orders_sent=false。

## 最小编码交接

以冻结r2的13路径为核心，原owner分开传HK证券价格日与经验证的资格source；贯通shared materializer、原V4 projector和Stage。需要成员source时复用原publisher，不新建producer。原publisher/Stage tick并非r2已修改路径，只有证明必要才提交其最小hunk并解释。

目标验收：HK-only owner→publisher（必要时）→shared→projector→Stage，日期/身份/真实capture反例，真实A池seed→HK-only调用→原池字节/内容保全，双方开市兼容。测试不能替代10/7自然来源和正式Stage/UI验收。A继续收尾；不重建9/30authority，不继续扩修旧catalog/status。
