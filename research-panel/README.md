# 研究面板与个股展示源码快照 · 2026-10-27

本目录是**纯源码归档**，不是可立即部署/自然日更的产品包。尚未上传GitHub；仓库/目录由用户指定后再同步。原源文件逐字复制，详见 `SOURCE_MANIFEST.json`（原路径、SHA256、字节数）。不修改任何生产V4/V5，不修改原公式、日更pins或CURRENT。

## 包含
- 日更 entry/source_probe/acquire 原入口及相应测试；pipeline_v4、volume_contract_v4和测试。
- 原 data/formula engine、用户冻结原公式文本、G4/guard/volume_decode必需代码。
- D27显示分支 canary、batch、event准备、projection和两份独立audit代码。
- history18固定查看模板及当前85/41界面、下拉日历/每日页controller、样式、最终r3与基础QA。
- 固定展示合同、数据包selector及测试。

`pipeline_v4`是研究流水线版本名，不是对现役V4系统的更改。

## 不包含
行情全历史、逐股数据JSON/研究结论、图片、研报与附件、正式输入与事件表、认证config/manifest/reader回执、交易日历、deployment回执、Git目录、凭据、token、用户权限资料、真实hosting配置、第三方知识库原文。原冻结公式是实现必需的用户代码输入，并非新增替代公式。

因此网页的data/chartdata/archive/*.json链接**预期缺失**；不可把空页面当成完整交付。相应QA所需真实fixtures/授权输入也不随包外传。语法检查通过不等于运行、数据准入、独立审计、自然调度或线上发布通过。

## 使用/可移植性边界
- Python使用标准库；Node用于JS/CJS语法检查。浏览器QA依赖环境已有Playwright，未在本包安装或锁定新版本。
- 脚本保留原绝对工作区路径、冻结日期、SHA、scope和文件依赖；克隆后**不可直接用于另一天或新工作区**。需先配置授权输入并完成用途独立审查，不能自动重设hash、改日期或跳过失败。
- pipeline volume gate需要原独审VOLUME_INDEPENDENT_AUDIT.json及匹配SHA；原config/security_master、GBBQ常量/事件、历史基线、交易日历等均未导出。缺件应保持fail-closed。
- D27本批有限展示123只续至D27、3只保留D26/UNKNOWN；不是全市场/全部研究域D27自然日更认证。原式/数据坐标与NON-PIT限制仍生效。
- Site源HEAD为 `dd26e03e7ca8913898d133c6e56503b0fc3d360c`，读取时工作树clean；它不是GitHub上传回执。
- Site官方发布工具依赖现有Sites插件1.1.1的site-workflow.mjs；**不复制插件实现**。`examples/hosting.example.json`仅说明模板，无project ID，不可直接部署。不新增连接或访问权限。

## 来源与权利
原文件头说明及公式SHA保留。上述是本云工作区研究实现/用户指定公式，未为其擅自授予开源许可；未复制整份第三方Wiki或宣称独占公共方法。建议仅同步用户指定的私有仓库，若要公开应另核权利及披露范围。

## 校验
`VALIDATION.json`记录静态AST/Node检查、限定敏感模式扫描及源副本一致性。扫描不构成不存在一切敏感信息的保证。没有执行下载、fit、行情重算或生产任务。`EXPORT_FILES.json`覆盖本导出全部文件；数据不会跟随GitHub上传。

## D27模块角色核对
`CODE_ROLE_BINDINGS.json`逐项核对D27 INPUT_BINDINGS的9项代码/门禁依赖。data/data_engine.py（c717…）是解析/复权模块；formula/formula_engine.py（ae424…）是原式指标解释器；两者不是同一文件的版本差异。所有实文件SHA均与D27绑定一致，未作任何修复或重写。
