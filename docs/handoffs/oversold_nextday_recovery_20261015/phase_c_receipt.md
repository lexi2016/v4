# 超跌次日恢复：阶段 C 实际 API 交接

状态：DEPLOYED + API_VERIFIED（Writer 自检）；独立 live Reviewer PENDING，UI 由主控验收。业务源码、release、manifest、scheduler、其他 lane、旧 run 均未改。

- 新 job/run：`5cb9b603e183428cab8de8990abcb7e3`，实际状态 PARTIAL。
- 真实请求：POST `/api/v4/manager-workbench/runs`，`{"target_date":"20261016","phase":"MANUAL","lanes":["OVERSOLD"]}`，未传 cutoff。
- 实际 cutoff：`2026-10-16T00:16:30.206652+08:00`；HK价格日 `20261015`，目标 `20261016`。
- 全部689个唯一证券分页读回并核其OVERSOLD lane_decisions：21入选、171观察、373未入选、124未评估。
- 未评估API原因：111 UNIT_ADJUSTMENT_OR_CURRENCY_UNKNOWN、13 HK_HISTORY_FIELD_QUARANTINED。
- 推荐API默认只返回192个正向结果（21+171），其lane counts为21/171/373/124。days API顶层aggregate将373个lane NOT_SELECTED归入顶层UNASSESSED，aggregate为21/171/0/497；本次据底层lane验收，聚合代码未改，不能把497冒充来源缺口。
- 21个名称均来自API的SAVED_RUN_SECURITY_MASTER投影，source_date=20261015，未猜名称。
- 原失败run `18425e50e6294f15a6bc02ac881c5af2` 在POST前后API字节SHA相同，仍为原NEXT_DAY/16:30/PARTIAL。

## 激活身份与回滚记录

候选配置：`/Users/lexi/Library/Application Support/com.lexi.v4.local/config/oversold-nextday-recovery-20261015-r1.json`，SHA `f4bc5c37fb08d57766bf3cd596f9fe4abdc6c32a327e09bc99c5f555822c7158`。旧v9保持原SHA `48fd88d8bc8921181a67c059af7907a56c6a78ef20bec480338409e553e60a9d`。

- 现役release仍为 `us-hk-mapping-finish-20261015-r2/app`，manifest SHA `5c6e18640443c65d647e5072ce82472de2f813ef35d245065006ba44a1fe8684`，最终PID7415。
- plist唯一语义变化为EnvironmentVariables.V4_MANAGER_WORKBENCH_CONFIG_PATH。旧SHA `579d18f1d3fa5cde7b26787936fe0e43969a9f826485f55ca39deb8eb910916e`；新SHA `45ec4e5fa94d3f4237983c1ccd841fc57e1cdbe6c62dbb05acb66078833dc653`。
- 使用既有 `.com.lexi.v35.api-only.release.lock`；每次确认旧PID退出、label消失并settle2秒后bootstrap。
- 首次切换的健康检查误要求/readyz返回RESEARCH_ONLY；该端点只返回三个false安全标志，因此脚本触发精确回滚。旧plist恢复相同字节；PID7153与/readyz确认健康。修正检查后fresh CAS该PID，再切换成功。失败证据phase_c_activation.json，成功phase_c_activation_r2.json。
- 研究模式由原ProgramArguments.RESEARCH_ONLY=1与新API envelope/snapshot.RESEARCH_ONLY=true确认；production_allowed=false、buy_gate_updated=false、orders_sent=false。

## 21只实际入选（API原样名称）

| 代码 | 名称 |
|---|---|
| HK.00100 | MINIMAX-W |
| HK.01347 | 华虹宏力 |
| HK.01377 | 鼎泰高科 |
| HK.01384 | 滴普科技 |
| HK.01609 | 天星医疗 |
| HK.01672 | 歌礼制药-B |
| HK.01779 | 天辰生物-B |
| HK.02249 | 晶合集成 |
| HK.02477 | 经纬天地 |
| HK.02513 | 智谱 |
| HK.02583 | 西普尼 |
| HK.02590 | 极智嘉-W |
| HK.02631 | 天岳先进 |
| HK.02697 | 真健康医疗-B |
| HK.02715 | 埃斯顿 |
| HK.02858 | 易鑫集团 |
| HK.03200 | 大族数控 |
| HK.03277 | 长光辰芯 |
| HK.03625 | 傅里叶 |
| HK.06651 | 五一视界 |
| HK.06809 | 澜起科技 |

## 只读复验入口

```sh
curl -s 'http://127.0.0.1:8873/api/v4/manager-workbench/runs/5cb9b603e183428cab8de8990abcb7e3'
curl -s 'http://127.0.0.1:8873/api/v4/manager-workbench/days/20261016/recommendations/OVERSOLD?phase=MANUAL&run_id=5cb9b603e183428cab8de8990abcb7e3&decision=SELECTED&offset=0&limit=200'
```

机器证据phase_c_receipt.json包括真实source pin、父身份、cutoff、全部计数、安全字段、旧run前后SHA、21名单名称和metrics。product SHA `caa7b28579f0a8e7b8f9229dcfac6c006318f656d80c7d29147751578f67b9ce`。

本阶段无业务源码变化，不追加业务单测。实际重载、health/readiness、POST、run状态、全689分页、21名称、124原因和旧run保持均已验证；支持脚本AST通过。API调用保留在phase_c_run.py，激活调用保留在phase_c_activate.py。不得重跑激活或POST；现有保存run供只读复验。

同源比例通过不代表绝对价格单位、币种或成交量单位已核，相关指标仍null。NATURAL_VERIFIED=false，本次为凌晨补运行。

GitHub仅同步必要helper与精简结果。phase_c_preimage.local.plist、phase_c_candidate.local.plist为本地精确回滚资料，禁止上传整份运行plist/配置或原始行情。主控继续独立live验收、UI与GitHub同步。
