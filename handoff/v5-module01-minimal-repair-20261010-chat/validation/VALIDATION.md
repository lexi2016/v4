# 实际验证、失败与证据边界

代码 authority：`6daed6271313b5ae5324c8948f163258ab8d1fa3`。原始日志见 [RAW_LOG_INDEX.json](RAW_LOG_INDEX.json) 和 [raw/](raw/)。日志中的 `work/`、`support/frontend/assembled/` 为本次私有测试目录，不是 Mac 运行目录。以下各组存在覆盖重叠，不能相加作为“全工程通过数”。

## 1. 运行环境与来源

Python 为项目要求的 **CPython 3.14.6**；以原 `V5/uv.lock` 执行 `uv sync --frozen --python 3.14.6`。没有安装 pytest 或改依赖以绕过原项目；原入口为 unittest。实际 pandas 2.3.3、pyarrow 24.0.0、numpy 2.5.3。原安装日志为 `python314-install.log`、`python-dependencies.log`。辅助生成 SHA/报告的系统 Python 不作为产品运行身份。

前端使用 **Node 24.19.0、npm 11.9.0** 与未改动的原 package-lock。来源顺序是原 `assemble_web.py` 的 BASE/UI/DEPS/V5 overlay；125 个原来源及134个有效组装文件全部核验。初次拼装遗漏的5份 next-tests 已从固定原文件补齐，首轮不完整 suite 日志保留。没有复制 Mac 大量正文、行情或392决定作为合成 fixture。

## 2. 本批定向测试

| 验证组 | 实际结果 | 原始日志 |
| --- | --- | --- |
| exact product / same-run terminal / latest A→B 竞争 | 14 PASS；真实原 owner 保存，包含独立进程交错 | `exact_run-green-terminal-gaps.log`；在 `python-affected-final.log` 亦通过 |
| 原公告 owner/bridge/manager 合同 | 9 PASS；完整 catalog/body/register/import/read 链，四条明确合成决定 | `announcement-contract-final.log` |
| 发布一次读及预发布 expected-run | 2 PASS | `publish-read-green.log` |
| 最终只读能力 + 原 gateway/module/artifact | 54/54 PASS，其中本批新 HTTP 6 项，包含实际 GET 与独立 POST /refresh 路由 | `http-readonly-review-green.log` |
| 最终 overlay 安装/重复应用/漂移拒绝 | 4/4 PASS | `ui-overlay-final.log` |
| 最终 module01 前端 API/DOM/实收据 | 44/44 PASS，3 份 spec；27 API +14 DOM +3 HTTP | `frontend-module01-final.log` |
| 最终 5 份受影响前端 spec | **85 PASS / 2 FAIL，87 tests；4 files pass /1 file fail**；两项读取原件时 ENOENT | `frontend-final-affected-suite.log` |
| 最终完整 typecheck | exit 0 | `frontend-final-typecheck.log` |
| 最终正式 build | exit 0，120 modules、三个 HTML 入口；经理 bundle `managerSelection-1eJa9jOe.js` | `frontend-final-build.log` |
| 最终来源闭包 | 125 original +134 effective 全部一致 | `frontend-source-closure-final.log` |
| forward / reverse 补丁 | 20 文件全匹配；reverse 后10个新增路径不存在 | [PATCH_VERIFICATION.json](PATCH_VERIFICATION.json) |
| 只读前像检查器 | before与after成功；前像漂移时exit1且所有目标字节不变 | [PREIMAGE_VERIFICATION.json](PREIMAGE_VERIFICATION.json) |

后端例行命令从代码候选仓库根执行（`V5_WEB_ROOT` 为已按原闭包组装的隔离前端）：

```bash
V5_MODULE01_WEB_ROOT="${V5_WEB_ROOT:?填写已核验的隔离 web 根}" PYTHONPATH=V5/src:V5/tests V5/.venv/bin/python -m unittest -v test_module01_ui_overlay
PYTHONPATH=V5/src:V5/tests V5/.venv/bin/python -m unittest -v test_module01_exact_run
PYTHONPATH=V5/src:V5/tests V5/.venv/bin/python -m unittest -v test_module01_announcement_contract
PYTHONPATH=V5/src:V5/tests V5/.venv/bin/python -m unittest -v test_module01_publish_read
PYTHONPATH=V5/src:V5/tests V5/.venv/bin/python -m unittest -v test_module01_http_readonly test_api_gateway test_module_api test_module_artifacts
```

上面的 `V5_WEB_ROOT` 必须是已核验的真实绝对路径；可执行的 Mac 变量版本在落地说明中。前端命令在完整组装根运行：

```bash
npm run test -- src/api/managerWorkspace.module01.spec.ts src/manager-selection/catalystObservationPanel.module01.spec.ts src/api/managerWorkspace.module01.http.spec.ts
npm run typecheck
npm run build
```

HTTP spec 实际运行时明确绑定 `V5_MODULE01_HTTP_RECEIPT=/workspace/scratch/d021d1397d6f/v5_module01/tmp/http-fixture-final/http-receipt.json`。未提供该文件时自身 skip 必须汇总为 NOT_RUN，不能当通过。完整原始 command/runner 输出随日志提供。

## 3. 真实 HTTP 到完整前端校验器

`module01_owner_fixture.py` 仅将网络 transport 改为四条明示的合成输入，执行目标原 owner 的采集持久化、catalog/body、register-handoff、import、reader、manager save/read；没有手拼生产 DTO，也未改 capsule pin。`module01_export_http.py` 复用已保存合成 run，用最终代码只读发布到新私有根，再实际启动 loopback module 与 gateway，分别 GET 后关闭。

最终合成 run 为 `5685e9708c734ddda582338cfd45f849`，plan SHA `687b7f94142c888c10e6de86e29c2372d3037e691461b4420558c0c0b33ca05a`。四项决定为1 selected/1 watch/1 not selected/1 not assessed；普通公告行显示2只股票，candidate/watch/pending计数保留各自含义。这个 run 不是 Mac run。

实际两面 HTTP 200、body一致、READ_ONLY标头一致；GET 前后所有列入输入与manager/module存储的文件字节一致。前端完整 `validateManagerWorkspace` 接受实际返回体并拒绝错误日期binding；实际客户端解析路径再重放同一HTTP body/headers。第二段 fetch transport 被测试截获，因此不能称浏览器直连Python服务的端到端验收。

最终记录见 `http-dto-export-final.log`、`frontend-module01-final.log` 和 [HTTP_CHAIN_RECEIPT.json](HTTP_CHAIN_RECEIPT.json)。该JSON只交元数据、摘要和边界；原大量响应/plan没有上传，完整复现测试源码已交付。它不证明 Mac offline binding、真实392体量、业务分类或自然运行。

## 4. 失败保留与归因

### 行为 RED 和随后修复

- exact-run：最初7个行为FAIL加1测试字段错误，修正测试字段后8个正确行为FAIL；后来同日/终态新增两项RED。见 `exact_run-red*.log`。没有把测试本身KeyError称作全部行为复现。
- 公告测试初始化：第一次尝试pytest不存在；随后合成fixture包含不允许的解析缓存路径、篡改测试选中非实际消费的缓存文件。这些是测试构造问题；改用原unittest、真实消费blob/registered body后9项通过，不描述为生产缺陷修复。三份原失败日志保留。
- HTTP能力、发布双读竞争及manifest矛盾的RED均保留：`http-readonly-red.log`、`publish-read-red.log`、`ui-overlay-red.log`。
- 前端初次12项API、14项面板RED保留；终审发现终态schema/SHA/时间缺口后15项新负例全部行为FAIL，随后27项API通过。原终审反例与复核另见 `final-review-*.log`。
- 旧同日MANUAL_REFRESH删除journal仍consumed的Python断言，以及两个旧前端生成合成断言，与用户的新同run/一次POST合同冲突。原FAIL保留，仅改对应合成断言；真实fixture依赖和skip逻辑没有替换。
- 初版HTTP spec误用不存在的客户端导出，且类型写法错误；初次测试/typecheck日志保留。修正为实际 `requestManagerWorkspace` 和验证后对象断言，未简化产品validator，最终44项/typecheck通过。

### 原 Python 受影响入口

实际执行21个相关模块，见 `python-affected-final.log`：**Ran 222 tests；FAILED(errors=6, skipped=6)**。一个setup error为 `V5_ANNOUNCEMENT_REQUEST_PATH_REQUIRED_NO_SKIP`，需要Mac原request；六项skip是原代码所要求的固定upstream fixture bundle。本批没有用合成新夹具替掉这些原测试。

另五项error来自本地闭包未含 `V5/producers/archive-acquisition-v2/manifest.json`。从固定F取回原blob `ad5d27f127db77a2dcadaab0b3b4795f30aa3c21`（SHA256 `3e0c745c614a0a13127ba053991f4171734f897ce90ccffdbbcb0ebb0dfbc876`），不改源文件，定向执行 `test_manager_archive_reader` **8/8 PASS**。见 `python-archive-dependency-green.log` 与额外来源清单。不为总结数字重复跑此前输入未变的全部模块，也不把原222入口改称通过。

### 原完整前端入口

首轮缺5份next-tests：412 PASS/24 FAIL/3 SKIP，保留 `frontend-full-suite.log`。补齐原依赖后完整执行：**442 PASS/23 FAIL，31 files pass/9 files fail**，见 `frontend-full-suite-complete.log`。其中17项缺原owner/Mac材料，4项缺原显式cloud artifact，2项旧合成断言随后按新合同更新通过。最终受影响组仍含两项原件缺失，因此退出1；没有改skip或喂替身补绿。逐测试分类见 [FRONTEND_REVIEW.md](../review/FRONTEND_REVIEW.md) 与 [NOT_RUN.md](NOT_RUN.md)。

## 5. 独立审查及候选身份

新鲜reviewer复核了原owner验证器、实际diff和反例。两项Important已关闭：完整POST终态准入，以及generic gateway独立refresh路由误标只读。独立API27/27和分离路由反例GREEN在原日志内。完整审查在 [FINAL_CODE_REVIEW.md](../review/FINAL_CODE_REVIEW.md)。

固定代码commit的20个文件已全部从远端读回，与本地被审查字节逐字节一致；Git blob再次与SOURCE_MANIFEST匹配。包、分支与材料提交的完整远端读回将在最终交付回执中另报。**没有执行Mac部署、切换、原件读回或自然周期验收。**
