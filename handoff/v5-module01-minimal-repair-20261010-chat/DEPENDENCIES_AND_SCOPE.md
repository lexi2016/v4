# 依赖、manifest 与本批范围

## 固定目标和依赖闭包

唯一代码候选 `6daed6271313b5ae5324c8948f163258ab8d1fa3` 直接基于 `f7cb731c384ee6890a87d16c19a5b5a621779477`。固定来源共核验678份文件（初始677，加实际 archive-reader 所需的原 producer manifest 1份）；其中668份保持原字节，10份旧文件在本批明确改动。另新增10份测试/支持源码。完整记录在 [FINAL_SCOPE_VERIFICATION.json](provenance/FINAL_SCOPE_VERIFICATION.json)。没有更改 vendor 或 contracts。

Python 保持原 `V5/pyproject.toml`、`V5/uv.lock` 和 Python >=3.14 要求，实测3.14.6。没有新增产品依赖。`V5/producers/archive-acquisition-v2/manifest.json` 是固定F已存在的原文件，只补进本次本地测试闭包，不属于代码提交新增或修改。源码未执行其采集 producer；此文件是 archive reader 的实现身份依赖。

前端保持原 package.json/package-lock；实际使用目标既有 `V5/tools/cloud_preview/assemble_web.py` 复建顺序：

| 固定对象 | 原依赖角色 |
| --- | --- |
| `164c010c7eaa1659db9bfed0ff5f123c7a39eefc` | canonical web，含原锁文件、主视图和 businessStatus |
| `8342862f05ca9f6516f51b3164b6110651e5af77` | workbench repair / Mac completion |
| `7d2b71a91ad4d54f85fe03f5973248af686d7a87` | managerAnnouncementAnalysis、announcementAnalysis、researchAttention、dailyResearchRun 四个固定 TS 依赖 |
| 本批固定代码候选 | V5 overlay 及其manifest；原脚本生成HTML入口、产品typecheck配置和指定原cloud测试 |

[FRONTEND_SOURCE_MANIFEST.json](provenance/FRONTEND_SOURCE_MANIFEST.json) 给出125个原输入blob、134个有效文件、覆盖次序、SHA和字节数；原核验记录 [frontend-source-closure-final.log](validation/raw/frontend-source-closure-final.log)。其中 `local_module01_candidate_against_f7cb731` 表示提交前被测试的本地字节标签；20条修改/新增文件已由 [CODE_REMOTE_READBACK.json](provenance/CODE_REMOTE_READBACK.json) 精确解析到唯一C，不能把该标签当另一个提交。其余V5 overlay原文件由C的固定父提交继承。

本包复用已有Git对象和原assembler，不重复复制整套未修改依赖或携带node_modules、venv、dist。Mac对象缺失时从已确认origin取上述固定commit，再按原脚本组装；不得改固定ref或替换helpers。原依赖下载/安装告警在日志中保留，没有升级锁文件。

## 唯一修改的源 manifest

`V5/ui/manager-workbench/overlay-manifest.json`：

- 删除 `unchanged` 里重复的 `dailyChannels.ts` 旧SHA要求；同文件仍在 `changes` 下以严格before/after SHA准入，生产字节未变。
- 更新两份生产TS和两份旧合成runtime测试的after SHA；其previous_candidate明确为固定F真实前像。
- 增加三份新module01前端测试，before为不存在、after为精确源SHA。
- 其余三项unchanged依赖pin保留。完整manifest有23个changes，所有after SHA已核对，原安装器已用真实文件验证重复应用和拒绝漂移。

没有改动任何Python capsule/source manifest、package锁或原有owner的业务封印规则。实现身份由原 `_identity` 包括适配器字节，如实随源码变化；没有手改保存产品身份。

## SOURCE_TARGET_MAP 的决定

[41行映射](SOURCE_TARGET_MAP.csv)覆盖V4的11条逻辑路径/28个变体，不把它们当作11个V5必改文件。真实目标是V5适配器、原读接口及两份前端。下列既有或未命中事项保持原字节：

| 项目 | 当前V5事实与处理 |
| --- | --- |
| 原公告 owner / catalog / body / handoff / receipt validators | 现有reader已接原消费合同；四条合成原链验证通过，无阻断非空公告的生产缺陷，不重建owner/store。Mac offline binding happy path仍需原件验收。 |
| A semantic identity helper | V5不存在 `workspace_identity.py`，不能宣称完整等效A；保留现有更保守的全输入digest和来源验证。本批无证据需要放宽无关registry-wide SHA。 |
| FOUR US prepare / exact read | V5已有独立 current_us_research/us_mapping_daily 原owner链和精确run文件校验，经理从已固定输入消费；本批不移植V4 HTTP writer或拼service参数，未声称US业务完整验收。 |
| D 冻结 catalyst 局部重放 | 目标仍比较完整selected，尚不等效D；但实际manager catalyst为NOT_BOUND、roots=None。本批非空公告不进入该重放，延期，不广泛删SHA。 |
| C attention 两行 | 不是本批必修，保留原R3前端/owner依赖，不为少几行重复先重构。 |
| d659ff0 公告最终SHA顺序 | 历史runner的build-reviewed分支在V5旧副本仍未等效；实际已保存结果重用不调用它，原register-handoff有效，不整套换historical runner。 |
| d659ff0 CLI完整readback | 历史CLI旧helper仍未等效；活动read_owner使用完整owner响应和原validator。未混为同一个运行基线。 |
| d659ff0 rebound Decimal | 实际screen分支仍float，不因另有Decimal helper宣称已修。经理本批消费独立committed rebound或保留缺源screen，该边界没有阻断公告，正式超跌准入另验。 |

公告COMPLETE_EMPTY、旧US receipt兼容、超跌正式准入、自然时段、完整三策略及18模块为后续独立事项。性能优化仍需测量后决定，本批没有引入服务拆分或新数据层。
