# M11：盘中研究与研究复盘

日期：2026-10-10。原总计划M11/P4；早期盘点也为11。此包仅文档交接。Chat写具体代码，嘻嘻在真实Mac独立测试、接V5预览和回传问题；不平行写两版。

## 业务目标与依赖

使用M04已提交研究材料及当时可用的市场/阶段证据，保留原盘中六slot与原每日研究总结的日期、时点、引用和读回。六slot固定为北京时间09:25、09:35、10:00、11:30、14:00、15:00。M01/02/07/08等证据只读消费，不能由本Chat重采它们；若原M11独有采集请求仍有需要，先明确同源唯一writer及已存在快照复用合同。

M11不接管M04归档、M09/M10价格收盘模型、M12视频FUPAN或M18经理计划。日总结不是六slot成功证明，收盘后材料不能当盘中已知。

## 当前事实

- 固定V5：f7cb731c384ee6890a87d16c19a5b5a621779477；递归完整树未有独立research_review_daily.py，不能把经理attention投影当本模块实现。
- 原入口存在：ops/run_intraday_research.py→domains.intraday_research.capture_intraday/read_intraday_day；ops/run_research_review_generation.py→assemble_runtime/run_generation。
- 原intraday窗口为同上海日期slot后0—8分钟，使用精确输入绑定，存在成功即复核复用。只有FAILED_NO_REQUEST状态可按原规则重试；REQUEST_ATTEMPTED、未知/旧marker不得自动重采。
- 日总结原assembly懒加载：在原同日任务锁及精确产物缺失检查后才运行数据/模型。snapshot模式不隐式collect。配置、profile、source manifest必须外部固定摘要；不自签配置。
- 旧盘点日文件/六slot缺口和归档运输记录是既有报告，不是本包重测；当前完整生产、实际绑定、页面和自然触发仍待Mac确认。

## 本Chat独占写入

拟新增且当前未实现：V5/src/v5_shadow/research_review_daily.py、V5/tests/test_research_review_daily.py，以及明确本模块私有实现目录V5/src/v5_shadow/research_review/（如确有拆分需要）。建议冻结donor闭包V5/vendor/research_review_baseline/及专属V5/contracts/research_review_source_manifest.json；这些均为候选新增路径，先给实际闭包manifest再落地，不复制全部canonical。

运行只写M11私有state root，按原结构分intraday与reviews；cache是本模块state子目录，代码根与state不重叠。保留原输入副本和成功产物，不写V4，不写M04根。shared frontend、gateway、调度、运行账本及其他模块只交接口请求，由单一集成者串行接线。已有凭据绑定只由现有原owner按已授权范围使用，不新增访问、导出或复制秘密。

先读PROMPT_FOR_CHAT.md和SOURCE_MAP.md；验收与回滚见ACCEPTANCE.md。当前未执行代码修改、测试或部署。
