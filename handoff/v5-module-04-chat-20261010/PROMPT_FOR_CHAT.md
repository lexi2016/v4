# 给Chat的M04独立任务

## 必须使用用户指定的 Superpowers 插件

用户明确指定已安装的 Superpowers（plugin://superpowers@openai-curated-remote）。本会话须实际选择并使用该插件的相关技能，不能只在正文写插件名称当作已调用。先按 using-superpowers 判断应使用的流程；修复按 systematic-debugging，必要设计/计划在本模块范围内完成，再按 test-driven-development、requesting-code-review 与 verification-before-completion交代码和可核验证据。复用既有总体计划，不再发起全仓设计或仅交第二份计划。

如果本会话无法访问该插件，说明实际入口/可见限制，不声称已启用；把这一问题回传嘻嘻。仍如实区分候选、静态检查、实际测试和Mac验收，禁止伪造执行。


请在既有V5范围完成“研究情报与归档”的具体最小代码候选。保留V4，调用原owner，禁止另造研究算法。以本包固定代码与SOURCE_MAP为起点，先核真实前像再改；嘻嘻在Mac对你交付的固定候选独立验证。不要只回建议或重新规划18模块。

## 首先给出精确映射

逐lane列 V4 donor/函数/固定SHA → V5已有或拟新增路径 → 输入 → 私有输出 → API/页面消费者。已有路径与拟新增路径明确分栏，未找到完整writer闭包写缺口。小时、早报、公众号、图片/OCR分别核真实入口与状态，不把目前知识社区候选当全研究覆盖。M12视频和M13公告生产不迁入本模块。

当前已核主链是原采集候选→显式同批status/pages/recent/summary→`archive_builder_v1.run_build`→原collector/normalizer→完整原source及owner回执→原`build_research_archive`→`archive_article_v2.run_import`→原store→独立`archive_reader.read_private`。沿原入口修复，不从article反推丢失的claim_type、article_id或dedupe_key。

## 本轮优先交付

1. 保存已有r1身份修复与fixture修正；从固定f7cb源码核前像，不能再次套旧9fb整包或用历史manifest SHA覆盖当前文件。最小补丁SHA256、每文件before/after SHA256和Git blob逐项列明。
2. 明确真实同批输入缺口，先接一份有完整原文/原取得回执的真实材料。不存在的历史retrieved_at/available_at不得填入。既有成功源只读复用，不重采。认证阻断单独报告，不能读钥匙串/令牌或换路绕过。
3. 补M04自己缺失的生产编排/失败恢复：按原lane合同逐步提交，失败不抹前置成功，latest_attempt与latest_success分开；重复同身份不重复抓取/归档。当前builder对已有同slot source拒绝复用，这是已核现状；不能宣称自动续跑已有。如需要恢复，应显式设计并验证owner可接受的断点/新attempt，不能降低no-overwrite与source重放门。
4. 保持正文、图片状态、OCR缺口、出处、发布时间、真实取得时间、可用时间、目标消费cutoff和原始span绑定。原v1仍按原规则；附件无正文、重复topic歧义、错页/错group/错主体、时序倒置、重算外层SHA仍应拒绝。
5. 向M11/13/15/16/18只交已提交artifact/receipt引用。consumer按自己的cutoff/资格判断，不把“材料可读”升级为有效关系或正式推荐。三篇知识社区材料无US对手方时不得补US关系。

## 共享接线请求

不得直接修改前端、gateway、调度、M15或M18。另交 `INTEGRATION_REQUEST.md`：提出只读查询字段、显式执行入口、错误/过期/缺图展示、expected-generation发布合同、消费者受影响测试及最小共享diff建议。GET与页面刷新不得运行采集/导入/生成。服务实现和按钮前缀须以真实挂载为准，不能猜已上线URL。

## 交付物

- 精确可应用补丁或固定提交，基线/候选SHA与文件before/after SHA；只列本模块变化
- 原owner依赖清单、运行所需既有环境绑定、真实输入合同与未解决项
- 原测试及新增失败用例；命令、退出码和完整日志位置，未跑必须NOT_RUN
- 与ACCEPTANCE对应的Mac步骤、单模块回滚和不变量检查
- 需要共享集成的接口请求；不要把本Chat候选自行部署到V5预览

若真实输入缺失，先交可审查代码与精确缺件，不伪造PASS，也不让本模块阻断其他独立lane。
