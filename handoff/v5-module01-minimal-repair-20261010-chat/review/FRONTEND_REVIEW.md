# V5 module 01 前端交付与验收记录

## 交付结论

在固定 V5 `f7cb731c384ee6890a87d16c19a5b5a621779477` 上完成最小前端修复。生产改动只有 `src/api/managerWorkspace.ts` 与 `src/manager-selection/catalystObservationPanel.ts`。保留既有只读 V5 路由与兼容 V4 POST 函数，没有新增生成或恢复 endpoint。

新增两份 portable 行为测试；独立复核后，经 root 明确授权，只更新两份既有 runtime spec 中各一项合成测试，使旧断言与用户要求一致。`dailyChannels.ts`、原 `dailyChannels.testHelper.ts`、原 `dailyChannels.spec.ts`、原 `ManagerSelectionView.vue` 均保持原字节。真实 Mac、392 条决定、689 行投影等证据没有替代品，也没有被描述为通过。

最终文件 SHA256、Git blob 与长度在 `notes/frontend_frozen_files.json`；精确来源闭包在 `support/frontend/SOURCE_MANIFEST.json`；建议合并映射在 `notes/frontend_source_target_map.csv`。

## 行为修正与理由

1. **完整日期校验进入 POST。** 原两个参数保持兼容，新增可选 `bindings`；计划日、选股日、公告日先按原日期函数校验，所选独立日期进入既有 POST URL 与完整 workspace validator。只有显式提供 expected bindings 时，缺失日期投影才被拒绝；普通旧 GET 不凭空新增日期选择要求。
2. **一次消费实际返回的保存产品。** 成功 POST 经过完整 validator、saved product 与同 run terminal admission 后直接渲染。移除无条件 GET，避免另一请求推进 latest 后替换本次保存的产品。测试同时核对返回研究理由、调用次数及 POST 公告日期。
3. **原终态身份与时间。** 要求成功终态、相同 run/date/input/owner/execution kind、原 attempt schema、SHA256 形状、完整 failure reasons、PARTIAL 与 gaps 一致、显式时区时间及 `started_at <= generated_at <= finished_at`。原 owner 负责验证持久化封印字节；前端检查序列化身份、字段和时间，不能把 64 位十六进制格式检查称为加密验证。
4. **只读入口与历史保护。** 初始、读取失败、缺少合格 read_context、历史默认 auto、以及服务真实标识的 V5 只读响应均关闭生成。事件处理函数重复校验 gate，不能只靠 disabled 按钮。`X-V5-Workspace-Access: READ_ONLY` 由服务身份提供，前端仅在 DTO 完整校验后放入私有 WeakSet，payload 自称可写不能放开权限。历史显式 dynamic 保留实际 cutoff/generated_at，不改写成历史时点。
5. **未知副作用保持未知。** POST 网络异常、错误响应、取消、180 秒停止等待、日期或 view 切换后的迟到结果，都不会冒称原 owner FAILED，不会自动 GET 借 latest 判定，不会自动 POST 重试。显示 CANNOT_CONFIRM，并要求原 owner 按原 run 核验保存产品和终态。缺少可信 run 标识时，不虚构恢复身份。原 sequence/abort/date/view 守卫继续阻止迟到渲染。

## TDD 与命令证据

所有 npm 命令在 `support/frontend/assembled` 执行；依赖是原 package-lock 的锁定结果。日志保存命令与退出结果。

| 阶段 | 实际结果 | 原始日志 |
| --- | --- | --- |
| 原依赖 `npm ci --ignore-scripts --no-audit --no-fund` | 安装 244 包，成功；保留原 lock 的告警 | `frontend-npm-ci.log` |
| POST 日期与成功消费初次 RED | 12 项中 10 fail / 2 pass | `frontend-api-red.log` |
| POST 初次 GREEN | 12/12 pass | `frontend-api-green.log` |
| 面板 RED，修正测试日期投影后 | 14 项中 13 fail / 1 pass | `frontend-panel-red-corrected-binding.log` |
| 初次 API + DOM GREEN | 26/26 pass | `frontend-green-01.log` |
| 终态补审 RED | 新增 15 项全部因错误接受响应而 fail；原 12 项 pass | `frontend-terminal-envelope-red-complete.log` |
| 最终受影响 5 spec，包括 root 实际 HTTP 收据 | **85 pass / 2 原件缺失，87 项；4 文件 pass / 1 文件含原件失败** | `frontend-final-affected-suite.log` |
| 最终 `npm run typecheck` | **exit 0** | `frontend-final-typecheck.log` |
| 最终 `npm run build` | **exit 0**，120 modules、3 个 HTML 入口；日志绑定最终 API SHA | `frontend-final-build.log` |
| 原 assembler 产品 typecheck | exit 0 | `frontend-product-typecheck.log` |

终审前的构建日志 `frontend-build.log` 保留。终审增加 terminal admission 后，先复跑受影响测试与全量类型检查；root 随后指出最终 bundle 必须绑定新 API 字节，因而再次执行原构建。最终日志明确记录 API SHA `478611369d9ee2e82874810def1aaf6618da7fbd337d4709199cc872f5a9c0b8`，经理选股 bundle 从旧 `managerSelection-uq5rCjHJ.js` 变为 `managerSelection-1eJa9jOe.js`。没有重新执行全部无改动 spec。

最后一次受影响命令包含 `managerWorkspace.module01.spec.ts`（27 项）、`catalystObservationPanel.module01.spec.ts`（14 项）、`dailyChannels.runtime.spec.ts`（22 项）、`catalystObservationPanel.runtime.spec.ts`（21 项）及 root 的 `managerWorkspace.module01.http.spec.ts`（3 项），使用 `--maxWorkers=2`。HTTP spec 绑定 `V5_MODULE01_HTTP_RECEIPT`，由 root 的原 owner/真实 module API/真实 gateway 导出，明确是 synthetic owner inputs，不是 Mac 商业证据。

## 全量 suite 的准确边界

首轮全量入口尚未加入原清单中的 5 份 next-tests，记录为 412 pass / 24 fail / 3 skipped，不能作为完整闭包结论；日志 `frontend-full-suite.log` 原样保留。随后按原清单补齐 5 份文件、保持全部原 SHA，并绑定 root HTTP 收据，以 2 workers 完整执行：**442 pass / 23 fail，40 文件**，日志 `frontend-full-suite-complete.log`。首轮无关页面等待超时在该次资源有界执行中消失，没有修改那个页面或测试。

该次 23 个失败分为：

| 原文件 / 测试来源 | 数量 | 原因与状态 |
| --- | ---: | --- |
| `managerWorkspace.currentRecovery.spec.ts` | 3 | 缺 `../evidence/manager-read-publication.json` 原 saved run/SHA；业务验收 NOT_RUN，runner 实际报 ENOENT |
| `managerWorkspace.announcementReview.spec.ts` | 4 | 缺原两个公告日完整已保存 payload；NOT_RUN |
| `catalystObservationPanel.runtime.spec.ts` 两项原证据测试 | 2 | 缺原 manual observation fixture binding 与原 Eastmoney workspace；NOT_RUN |
| `researchSelectionLedger.spec.ts` | 6 | 缺原 `issue8R2.ownerObservations.json`；NOT_RUN |
| `actualResearchSelectionProjection.spec.ts` | 1 | 缺原 689 行 owner projection；NOT_RUN |
| `workspaceAfterReadback.spec.ts` | 1 | 缺原 Eastmoney workspace；NOT_RUN |
| `cloudRecoveryContract.spec.ts` | 3 | 未提供其指定的 synthetic empty owner response；NOT_RUN，不用本批非空响应充当它的 fixture |
| `cloudActualReadback.spec.ts` | 1 | 未提供其指定的原 cloud auto response；NOT_RUN |
| 两项旧合成生成断言 | 2 | **已随后按新合同修正并通过受影响套件**；旧 daily 断言强制二次 GET；旧 catalyst 的无 read_context 历史 fixture 却要求开启生成 |

17 项缺原 owner/Mac 证据与 4 项缺显式 cloud artifact 的测试均未改数据来源、未添加 skip、未换合成替身。最终受影响套件仍直接执行其中 2 项，runner 退出 1 的原因只有原件缺失。没有把总体 suite 描述为全绿。

## 精确来源、依赖和组装

使用目标已有 `V5/tools/cloud_preview/assemble_web.py` 的层次：BASE `164c010...` canonical → UI `8342862...` repair/completion → DEPS `7d2b71a...` 四文件 → V5 overlay manifest → 原脚本 HTML/config/cloud-test 生成语句。首次取到的 UI canonical 与 BASE **全部 110 个 Git blob 相同**；两个公告分析依赖与较早 `9dfa503...` 也 blob 相同，清单以原 assembler 指定 DEPS 为准。

`support/frontend/verify_source_closure.py` 是离线审计器：核对 125 个原来源 blob，再按上述覆盖次序核对全部 134 个有效文件；HTML 和产品 tsconfig 的期望字节由未改动的原 assembler 语句在临时目录生成。它不代替产品 helper、不改原 npm 配置、不绕过 installer 校验；真实 installer 测试由 root 单独负责。原始下载影像、Git SHA、SHA256 和支持路径均写入 SOURCE_MANIFEST。

Node `v24.19.0`，npm `11.9.0`；锁定包为 Vitest `4.1.10`、Vue `3.5.40`、jsdom `28.1.0`、TypeScript `5.9.3`、Vite `7.3.6`、vue-tsc `3.3.8`、Testing Library Vue `8.1.0`。保留原 `http-proxy` 配置告警及 glob deprecation，没有改依赖清单。测试中只有 HTTP transport 被替换为明确 synthetic 数据；本批新测试没有替换原产品 validator、panel 或 helper。

最终闭包重核使用 root 冻结的 overlay manifest SHA `b1d109a0c7342bd98053f8cc508d95645d69e3a680b3771d980f8f3a5799eab8`，结果仍为 125 个原来源、134 个有效文件全部一致，日志 `frontend-source-closure-final.log`。

完整交付请包含支持源与清单，排除 `node_modules` 和 disposable `dist`。重复下载批次 JSON 只是取回日志，不是产品依赖。未执行远端提交、部署、真实服务调用或 Mac 浏览器验收。
