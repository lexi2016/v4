# V5 私有快照主表适配批次

用户于 2026-10-08 15:51 明确要求继续补充模块，承接此前已说明的独立数据接入范围。dot 实现代码，原 Mac 测试会话独立执行；不再重复询问该范围。原 V4 及正式 writer 不接管。

## 目标

真实完整 Futu SDK snapshot 与已获准来源绑定 → 规范化 → 原主表 publisher 写独占 V5 generation → 原 verified loader 校验读回。测试 fixture 只在临时测试目录验证这一实现，不成为真实业务产物。

## 接口

- MasterBinding：调用方可信配置提供私有根、trade_date、cutoff、完整成员 codes/来源 SHA、producer code SHA、原 records SHA、receipt SHA。输入不能自己决定“已可信”。最小完整范围600只。
- prepare_futu_master(records, receipt, binding)：返回仅当前进程可发布的 PreparedMaster 能力对象，禁止JSON反序列化伪造授权。绑定 raw 与 receipt；检查每批请求/结束时间、代码全集和批次 raw hash，日期按 Asia/Shanghai；available_at 不得越过 cutoff。快照结束时间与 plate 时间分离。必须明确普通股类型，必填字段不完整拒绝；股数、市值未知保留。
- publish_futu_master(prepared_bytes, binding)：只允许已初始化的V5私有root；固定字节加载原8文件writer/reader依赖，写新generation；先核旧writer输出与预期每个字段，再将全部文件哈希封入commit receipt；原子发布目录，重复请求使用独立保存的原reference核完整性后复用，损坏拒绝覆盖。
- read_futu_master(reference, binding)：先核V5 receipt、文件集合和SHA、配置/输入身份，再核原reader及字段，返回原数据加未知状态。

SOURCE_BOUND_REPLAY仅表示与调用方预先信任的配置逐字节对应，并非独立网络来源认证。没有部署可信输入配置时，不能对真实来源自发准入。正式成员资格与自然运行始终不在此模块中升级。

## 隔离和失败

源代码从固定canonical闭包逐字节读取并compile，独立模块命名空间，不导入活动V4或缓存pyc。只读写V5私有根及新generation，拒绝symlink/越界；同根锁串行发布。失败pending目录保留便于审计，不成为成功引用；成功目录不覆盖。root初始化是获准环境配置步骤，业务输入不得自动创建授权标记。

## 执行顺序

1. 首批12项测试候选已发布 f562462。原Mac两次接续服务请求失败，未确认运行，RED标NOT_RUN；按用户此前连接阻塞时先写后测的授权继续实现。静态审查后当前测试扩展到22项。
2. 实现私有模块、冻结8文件闭包及描述清单，root不在云端执行测试。
3. Mac针对性测试通过后一次全套，保留警告与失败原件；必要修复由dot处理。
4. 将结果与固定提交同步GitHub。真实采集、owner切换、rebound真实输入准入、页面与调度另有验收，不凭此批通过宣称完成。


验收更新：固定3b321022b118e94f828d2f810a622a0a44b23950在Mac全套128项通过，主表22项及记录器17项已有对应回执。历史未执行说明是当时状态，详见ACCEPTANCE.md；并无真实采集或生产上线结论。
