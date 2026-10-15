# HK next-day pool recovery · 20261015

目标：恢复20261016港股D-1预选池的既有生成和自动重试链路。

已确认并最小修复：缺失目标池被误判成坏缓存，阻止自然重试进入既有producer。真实shared reader与运行版reader分别按其精确缺失信号处理，已有run缺artifact、SHA或history校验失败继续隔离。Luna Max独立目标行为PASS，原FAIL_P2保留。

评分的独立隔离复现为严格历史隔离后覆盖不足：信号日62，历史代理截面最多70，低于既有80门槛；未降低门槛。原17:30输入身份缺失，不把隔离复现等同原始trace。复杂诊断由6.1 Sol High完成；既有TDX修复owner继续负责评分数据链，本会话不重复生产。

当前：候选未部署；等待并行owner最终运行身份后CAS整合。API/UI与自然验收NOT_RUN。明日池未确认生成。

精确交付模式PATCH_ONLY，不代表完整运行快照。状态和SHA见result.json，独立回执见evidence。仅补丁、必要测试和精简证据可同步私有工作分支。
