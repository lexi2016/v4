# 本地 Codex 一次接续

## 应用并执行本批测试

先由本地单写者将当前完整源码/应用复制为**新隔离副本**。不能将 `configured_release_reference/` 整树覆盖 source，不能将此包的参考导入依赖覆盖现场 app。对 SOURCE_PINS 中五文件核前像；当前 R3A 及其他文件原样保留。不要再叠旧 BI 包或重跑未改变的历史全量测试。

在本交付目录中执行一次（路径替换为实际完整隔离副本及新证据目录）：

```bash
python tools/work_once.py --app /absolute/path/to/isolated/app --output /absolute/path/to/new/evidence
```

使用本机实际 Python，不要求某固定 Python 小版本或模型身份。测试依赖：pytest、Python playwright、`tsc`、可用 Chromium。`CHROMIUM_PATH` 可指定本机 Chrome/Chromium；不设置时尝试 PATH 的 chromium，再使用 Playwright 默认浏览器。本工具不安装包、不启动服务、不联网采集。缺依赖会保留实际 stderr/退出码，不能以跳过测试计通过。`BI_OUTPUT` 中保存浏览器截图和实际 Python JSON。

命令校验五个精确前像/已应用后像，在隔离 app 内应用 `runtime.patch`，运行新增 39 项，输出 `WORK_RECEIPT.json`、pytest.log、JUnit、逐例 JSON、TS 编译日志、导入 SHA、DOM 截图。全新输出目录防止覆盖原验收；混合/漂移前像不盲改，集中报告差异。

## 独立审核范围

另一审核者核五文件差异与 SOURCE_PINS；复跑本批跨端测试，验证合法多正文/多发行人/重复去重、native 个股/行业、standing/mirror 公司材料整卡、来源/时钟/失效/错 issuer 负例。保持既有资格过滤器和安全标志，不因零映射修改准入。不要要求全量旧 R1/R2/R3B/API14 重跑。

## 实际业务验收（此命令不执行）

依照原发布授权流程单独做候选构建/安装放行。真实 API/UI 验收检查实际加载 SHA；原资格 reader 对目标时点接受后，再用真实公告/关系材料检查普通 8873 页。不把本包合成零/非零结果或 Chromium fixture 页当成真实恢复。未获部署授权时止于隔离验收。

当前数据前提按交接审计复用：2016材料→16发行人/67候选卡→membership门排除67→关系层0；US有33/33报价、mapping_eligible=true，PARTIAL是另一质量状态。补齐资格之后仍须验证真实主体、双来源和原时钟，不能保证必有非零映射。

## 回退

仅在新隔离副本：确认五个 after SHA，再 `git apply --reverse --check /path/to/runtime.patch` 和 `git apply --reverse /path/to/runtime.patch`；确认 before SHA。保留测试回执；不改服务/调度，不清除原 run 或业务数据。放弃隔离副本也可，不影响活动版本。

## 最小依赖与后续事项

本包 source 未含 `workspace_plan_autorun.py`，所以 BI04 自然调用未核；不要因此阻塞 BI01/BI02。测试用到的非 SOURCE_INDEX 导入在 `evidence/IMPORTED_SOURCE_IDENTITY.json` 标明：本地用完整真实依赖，不用作者参考依赖拼装发布。UI 验收须同时更新原 Python/TS 对应版本，不能只改一端。
