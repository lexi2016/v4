> 完整源码、证据和逐文件清单在本目录 V5_BLOCKERS_20261010.zip 中，解压后阅读相对路径。US最新11/11结果见同目录 US_STATUS_APPENDIX.md，优先于ZIP冻结时的NOT_RUN记录。

# V5 三项阻断：交给 Chat 的具体任务

另见 ADDITIONAL_INTERFACE_AND_PROGRESS.md：第四项 Reader/独审提交返回合同缺口，以及独立US修复的待验进度。A的318项冻结索引与实际文件已核对齐备。

请以本包冻结源码与已执行证据为起点，修复以下三项问题。不要重做392条公告阅读或语义独审，不要修改V4、旧计划、历史PIT、BUY/Stage或正式量价准入。提交新的固定源码增量与针对性测试，再由Mac执行验收。本包整理期间没有运行测试、重采数据或部署；证据来自之前真实执行。

1. **跨日经理保存/页面读取不一致。** 3d9541ac原链测试，目标20261009、真实时间2026-10-10：保存返回CURRENT/consumed=true，普通view=auto却转历史路径，返回NOT_MATERIALIZED、HISTORY_QUALIFIED_SAVED_PLAN_MISSING、run_id=null。需要明确当前恢复/回看研究身份，保存与普通页面读回保持同一run/SHA；禁止把迟到材料回填旧计划、冒称10/9历史可用或只改测试日期掩盖问题。
2. **独审缺少不可变修订绑定。** 冻结reviewer文件没有decision_revision，e06d create_revision要求该字段与revision ID、父产品/回执、原recovery、source run精确匹配。请原独审对这些绑定补充真实审查并交付新文件SHA；不得由集成器伪造PASS或改392条决定。本包含既有独审与哈希，未打包392正文/全文决定，修复此结构门禁无需重读它们；真实导入继续使用Mac现有冻结文件。
3. **超跌合法源码被marshal身份检查拒绝。** ebe5944e原loader加载正确SHA源码，_verify_owner报REPAIR_OWNER_FUNCTION_MODIFIED。code属性递归相等；原始marshal序列化受docstring引用状态影响。见DIAGNOSTIC_ADDENDUM及docstring-reference-diagnostic。请修复兼容性，同时保留对函数替换、helper/global/constant/layout等实质篡改的拒绝能力；不得删除身份门禁或凭相等co_code放行。

## 已有结果（不是本轮重测）

- 3d9541ac：43单元PASS；原链2项中1PASS、1FAIL，完整trace见evidence/announcement/original-chain.log。
- e06d：10项修订与7项既有链测试PASS，见evidence/e06d。
- ebe5944e：新增68=66PASS+2SKIP；含既有13项共81=77PASS+4SKIP。四项均因未设置显式opt-in，不是Python不足；实际CPython3.14.6。真实私有repair另行执行，并在owner校验阻断。

## 阅读顺序

1. REPRO_AND_ACCEPTANCE.md：复现与验收边界。
2. evidence/announcement/：回执、完整失败栈、跨日合成返回。
3. inputs/reviewed-decisions/：既有独审与缺字段证据。
4. evidence/rebound/：完整真实栈、code属性、marshal版本/引用诊断、skip原日志。
5. sources/：固定代码、依赖清单、测试。3d9541ac、e06d、ebe5944e各自隔离，勿混用同名模块。

FILE_LIST.tsv列出每个文件与用途；SHA256SUMS校验包内字节；PROVENANCE.json区分原SHA与脱敏后SHA。源码Python保持原字节；少数文档/元数据路径脱敏后不再声称原始哈希相同。e06d的UPSTREAM_SHA256SUMS是脱敏前来源清单，不能作为本包整体验证命令。不要把合成诊断产物用作业务输入。

依赖安装需要在独立环境按各源码根pyproject.toml/uv.lock执行；包内不含Python运行时、第三方依赖、模型、私有panel资产、凭据或账户数据。Mac真实资产路径不随包分发。完整列表与扫描结论见SENSITIVE_SCAN.json。
