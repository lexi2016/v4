# M12：视频FUPAN

日期：2026-10-10。原总计划M12/P4，早期编号同12。Chat写具体代码；嘻嘻负责固定候选在真实Mac的独立验收、V5预览接线和问题回传。本包只准备文档，不运行媒体、测试或部署。

## 业务与边界

保留原视频发现/日期锁定、媒体下载与ASR、session、股票字典、OCR对齐、差距、发布及结果核验链。每节点独立状态和恢复，后续失败不抹前置成功。依赖原媒体/ASR/OCR与字典、独立市场复盘事实；向M05/M09提供正式材料引用。M04只归档可用材料，不吞M12全节点；A价格模型、研究日总结不替代视频链。

## 已核实现事实

固定f7cb731c384ee6890a87d16c19a5b5a621779477完整树尚无V5/src/v5_shadow/video_fupan_daily.py。原canonical拥有旧close node与upstreams/review_core producer/consumer，见SOURCE_MAP。

重要：原run_v35_close_review_node对真实运行根优先走Review Core只读投影；临时fixture可走旧本地producer。read-only节点的SUCCESS可能仅表示ALREADY_MATERIALIZED_READ_ONLY，不能当“重新下载/转写/完整生产”。原Review Core producer.acquire_video有日期锁、媒体SHA缓存、ASR缓存及不可变run线索，必须继续沿活动唯一owner，不能同时开启旧producer和Review Core两个采集者。

原旧receipt复用条件只核node/date/SUCCESS与文件存在，不等于完整SHA验证；V5封装必须补自身输入/代码/产物完整身份，不能宣传旧函数已校验字节。原ASR完成仍可ASR_REVIEW_REQUIRED，没spotcheck不能强改绿色。原独立事实不被视频观点覆盖。

旧20:30—21:15配置、21:10步骤成功/21:15上游缺失是历史报告，未证明本次全链或当前活动时刻。媒体依赖、完整owner闭包、实际导航/API及自然触发待Mac核。

## 本Chat唯一写根

拟新增：V5/src/v5_shadow/video_fupan_daily.py、V5/src/v5_shadow/video_fupan/（确需拆分时）、V5/tests/test_video_fupan_daily.py、V5/contracts/video_fupan_source_manifest.json、V5/vendor/video_fupan_baseline/。这些不是当前已实现路径。先固定确切活动Review Core donor闭包和授权依赖，不能整复制canonical，也不能改M04或M09闭包。

运行根仅M12私有media/asr/cache/runs/evidence与发布引用；原V4及Review Core活动数据只读复用经过摘要核的副本。成功媒体/转写不得因下游失败删除重做。共享前端、gateway、调度和其他模块只交接口请求，由唯一集成/发布者接线。保留V4/8910，不交易、不改BUY门、不新增凭据访问或安全权限。

活动producer/现场绑定未知仅阻断真实生产、安装和启用，不阻断基于固定Review Core源码交最小静态代码候选及契约测试。Chat仍须交代码与精确缺件，禁止双producer采集。
