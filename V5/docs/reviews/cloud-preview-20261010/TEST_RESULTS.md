# 云端增量测试账

源码固定 `5f96689b52f6b5150e0fddccf6b5cae409915b2c`，基线164c010；报告后续提交只含证据文档。全部时间为UTC。数据/日志留本环境，不把Mac旧结果计作新执行。

| 执行范围 | 实际结果 | 日志/exit文件前缀 |
|---|---|---|
| A/HK与真实UTC guard | 45项通过，128.158秒，exit0 | a-hk-green |
| manager membership/panel合成时钟 | 29项通过，33.615秒，exit0 | manager-clocks-2 |
| current recovery/plan/revision工程 | 25项通过，83.384秒，exit0 | recovery-engineering |
| recovery含真实公告组 | 28项执行，另setUpClass错误1，exit1；缺V5_ANNOUNCEMENT_REQUEST_PATH，不跳过 | recovery |
| 经理UI目录 | 146通过/3失败；15文件通过/4失败（含2suite缺JSON），149项，exit1 | ui |
| 全量UI | 403通过/20失败；29文件通过/6失败（含2suite缺JSON），423项，117.03秒，exit1 | ui-all |
| 全量typecheck | exit2，缺issue8R2.ownerObservations.json及2个派生any错误 | typecheck |
| 产品专用typecheck | exit0；排除tests，不能替代全量 | typecheck-product |
| Vite build | exit0；11静态文件逐SHA等于运行清单 | build |
| 原经理既存产物再次独立read | exit0；同run/同SHA/consumed=true | existing-read |

以上套件重叠，不相加。完整Python回归：**613 tests，0 failures、19 errors、0 skipped，exit1，523.606秒**。19错误均缺真实请求：公告桥17个setUp错误+经理公告1个setUpClass，共18个`V5_ANNOUNCEMENT_REQUEST_PATH_REQUIRED_NO_SKIP`；US 1个setUpClass `V5_US_MAPPING_REQUEST_PATH_REQUIRED_NO_SKIP`。不能简单用613-19计算通过数（含class级错误）。原Linux边界、周末/跨日、归档依赖及revision工程错误已消除。

完整Python命令（在/workspace/v5-cloud）：

```bash
PYTHONPATH=V5/src:V5/tests \
V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/workspace/v5-runtime/archive-owner \
V5_ANNOUNCEMENT_REVISION_TEST_BUNDLE=/workspace/v5-runtime/revision-tests/V5/handoff/announcement-budget-red-20261009 \
V5_ANNOUNCEMENT_OFFLINE_TEST_BUNDLE=/workspace/v5-runtime/V5/handoff/announcement-budget-red-20261009 \
V5_REBOUND_OWNER_ORIGINAL_TESTS=1 V5_REBOUND_OBSERVATION_ORIGINAL_TESTS=1 \
V5/.venv/bin/python -B -m unittest discover -s V5/tests -v
```

前端在/workspace/v5-build/apps/web：`V5_CLOUD_WORKSPACE_RESPONSE=/workspace/v5-runtime/http-workspace.json npm run test`；目录检查再加`-- src/manager-selection`；`npm run typecheck`；`./node_modules/.bin/vue-tsc --noEmit -p tsconfig.cloud-product.json`；`npm run build`。每个程序退出码独立保存，不使用后续tail命令退出码充当测试退出码。

当前业务验收分账：合成工程测试如上；已存真实成功原批重放NOT_RUN（无完整合法392/超跌等原件）；新真实采集仅首轮US/公告失败产物，不重复采集；原经理真实失败源的PARTIAL保存/同run链已证；UI仅jsdom/HTTP，内置浏览器视觉NOT_RUN；自然接续NOT_RUN；Mac完整验收NOT_RUN。

09:25:53仅重启已核原三个云端进程，固定源码5f96689，配置不变，新PID manager6919/announcement6920/gateway6921。09:26:04逐字节核全部5个HTTP响应与首轮相同：health/page/manager200、公告analysis/selection503。重建11静态文件SHA也全部相同。进程/配置SHA/命令见increment-process-identity.json；响应hash见increment-http.json。原配置release标签保留首批产品身份；实际进程源码版本以本次记录为准，不以标签推断。

Mac迁移时同步此固定源码及overlay，重组独立候选并独立测试；原61796/V4不切换。回滚只停本候选或用原CAS回切已核旧generation；任何真实采集恢复均先解决源权限/输入准入，保留BLOCKED历史，不重置失败policy。01—18及P0—P5逐项缺口详见RESULT.md和INCREMENTAL.md。
