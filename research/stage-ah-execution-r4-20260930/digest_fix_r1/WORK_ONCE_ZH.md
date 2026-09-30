# PR16 增量：205 原序摘要格式修正

## 业务目标与固定输入

代码父提交 `da09905c4d5d86ee5ffc3879fb618c9188f4ec52`；新证据 `e0cfa0f9901adaa11c052aa8796c72ee6784bf18`。只修复 `after/ops/_run_stage_center_nodes_parts/node_entry.py` 的 codes 摘要计算，不改 R4 dispatch/slot_execution/runner_receipts、selector、collector/provider、日期/预算/锁、A/HK结果保全或正式历史数据。

前述“同算法不匹配、205原序仍缺失”的结论撤回：真实同一原序205数组已取得且独立复算。
- UTF-8 LF join、无末尾LF：1844 bytes，80f5a1c0bbed293b637d1a2bb25585de932ce5b235dd3ff0236fcb9a99d8eb69。
- 紧凑JSON：2256 bytes，ed7370dd8a81ddc621d606c61b8df95095cdc2c9def7909ab8be5e02b214b073。
- 证据格式化JSON文件：2873 bytes，cf16619116f85832c9bf1ba80c60a6166f37afee52f3ed4b379e76b6e708b71c。

原 expected 80f5 常量不变。guard digest_mode 明确为 `ORDERED_CODES_UTF8_LF_JOIN_NO_TRAILING_LF_V1`。旧授权不要求新增字段，canonical授权摘要算法不变；若显式声明不同模式则拒绝。只给新返回的内存reservation增加模式字段，不读取后改写旧授权/回执。current/artifact/文件bytes摘要仍各按原合同，不要求相等。

## 前后像和增量应用

node_entry before：e8707873a23284626f5af44aa7ede9b273e464f1d66bf79dd608099abf451dba。
after：f8817fee6b89205476fa0c226505dc139f9ec16d30353dace7f7998bb6b3683e。

在已经组装的R4非活动隔离目录核before后应用 `runtime.patch`，它只改一个运行文件；after相同则跳过，第三值先适配。不将本包before/after写到活动release，不与旧R4四文件安装patch重复叠加。`rollback.patch`只回退该运行文件，不删除或修改数据、attempt和consumed marker。

新增测试和真实代码数组分别复制到 `tests/test_pr16_issue11_codes_digest.py` 与 `tests/data/a0925_candidate_codes_original_order.json`。另外 `test_fixture_alignment.patch`仅把旧R4测试中一处合成codes pin改用LF摘要；没有改断言或场景，本轮未重跑该18项。需要一次应用源码和测试时用 `complete.patch`，不要再叠加runtime/test_fixture_alignment patch。

本轮8项新增只读guard合同：RED 6 pass/2 fail/0 error/0 skip exit1；GREEN 8 pass/0 fail/0 error/0 skip exit0。真实输入仅205代码数组；receipt、六attempt、candidate reader、加载身份和授权上下文均为明确合成替身。未调用dispatcher/runner/collector，也未保存或消费真正APPROVED。代码常量80f5未被测试替换。所有临时文件和内存授权前后不变。

作者Linux Python3.13.5，载体是原源码缓存，目标node逐字节与PR16核对。仅执行完整guard函数及其只读路径，未声称缓存所有依赖等同Mac。未变化日期/预算及R4保全沿用此前限定结果，不重跑18项、不将8+18累计为新组合验收。最终目标仍为Mac现有SERVICE_PYTHON及依赖。

Work一次验证（只运行新增8项）：
```sh
# 在非活动的已组装R4项目根；文件已按上述前像检查和复制。
"$SERVICE_PYTHON" -m pytest -c /dev/null -W error \
  tests/test_pr16_issue11_codes_digest.py -q --tb=short \
  --junitxml="$REVIEW_OUTPUT/pr16_digest.xml" \
  >"$REVIEW_OUTPUT/pr16_digest.stdout.txt" 2>"$REVIEW_OUTPUT/pr16_digest.stderr.txt"
# 单独保存真实退出码；不要用后续echo的0代替pytest退出码。
```
原完整after、patch、SHA、新增原stdout/stderr/JUnit/result均随包和固定GitHub提交提供。read-only eligibility返回并不是执行授权或额度消费。

## A1445 唯一最小只读取证请求

请原Stage Work只对20260930 / STAGE_1445_1500实际使用的1400对输出一份 `a1445_20260930_1400_projection_witness.json`：source原字节SHA必须为4076de79920c43cfa57336c23262a491cd77730f29b4e1a530bc5ed9836ef571；archive的既有stored_payload摘要为811b7803b540ec22c8e3f061804229e59fa51179f20a55a56ccc12d946af4af0。先明确该stored_payload摘要的原合同口径，不要求raw文件SHA、完整canonical、去扩展canonical摘要相等。

同一只读结果包含：这对原件的相对路径/字节数/原字节SHA、archive完整canonical SHA和去stage_evidence_v1后的base SHA；实际加载的research_context、build_research_archive及调用兼容helper的相对路径/模块SHA；实际serializer参数/编码/末尾换行约定；1400生成时间、1500的15:00:02及15:00:00 cutoff判定；按原调用顺序重建、经过原兼容helper后，仅移除stage_evidence_v1，再输出完整JSON-pointer差异（双方类型、长度和值），以及对应source输入字段和source_manifest的producer身份。相同字段只给canonical长度/SHA，不发完整无关内容。不要预设只有cannot_confirm不同，也不要在比较前删警告或重排数组。隐私字段可在本机算SHA后脱敏，注明导出不再等同原始bytes。

现包只有source/archive摘要和错误，无投影字段原件；不足以做字段级修复。保留已存202/205raw，无需发202行行情或全项目。读取1400正确，15:00:02不能越过15:00:00。旧helper仅绑定20260929 source506c947c…，不是本次source4076de…资格。本批research_context未修改，不扩展旧四码/二十七码特例，不猜历史owner或引入commit。

## HK及真实完成标准

按新证据分别记录9/28–29 active-snapshot cutoff拒绝与9/30严格D1 sentinel缺失；其他日期有成功结果，准确引入commit仍未知，不全局归因。本批HK代码未改。

代码修正不等于真实恢复。部署/真实补跑仍未授权且本轮均未执行；不得跨日延长9月30日额度。后续真实API/UI完成标准：原date/stage/market/run/hash一致，完整205原序未变，旧安全位及A/HK兄弟市场保全未变，有合法产物后才核普通页面实际行序/限制字段。不得以本8项通过替代真实原件、实际加载和页面验收。六attempt原文及实际加载仍须Work按原合同确认，但不能再把205双算法误称未解决。
