# 既有快照请求的被动记录适配

状态：代码候选，测试未执行。用户要求在原 Mac 测试接续阻塞期间继续补充模块；本批未实际调用 Futu 或修改 V4。

现有 capture 只保留九个主表字段，丢失证券类型与快照每批完成时间，不能为 V5 新准入合同提供足够证据。本模块保留已有 owner 真正发起的原始调用，而不新建采集器。

## 用法与边界

由未来获准的 V5 owner 在其既有批次调用位置，用 SnapshotRecorder 包住已有 get_market_snapshot callable。每次调用恰好透传一次原请求，不多发请求、不自动重试，返回同一个 SDK response 对象；provider 原异常重新抛出。记录失败仍返回原 SDK response，但后续 seal 拒绝完整回执。

保留整个 SDK row（包含 equity_valid 等类型字段）；deepcopy 后绑定每批请求代码、供应商返回代码顺序、raw记录SHA、真实请求/响应时刻。对供后续处理的行按请求序排列，原返回顺序另行保留，不篡改SDK返回对象。

seal 返回进程内 records 与可序列化 receipt；available_at 是实际封存时间。原 owner 自己决定的重试可补齐先前失败请求，失败attempt仍保留；未补齐、代码重复/范围不符、记录异常或时钟异常均拒绝。

本模块仅证明记录层捕获了什么，不会创建信任配置，不宣称成员资格、自然成功或独立网络真实性。调用方核准的 producer身份、完整成员来源和输入SHA仍需独立绑定。后续将records/receipt送现有prepare_futu_master，保持同一来源/日期/时间边界。

尚未把该适配安装进现役collector，未执行任何真实采集、主表写入或调度。旧不可变capture不重写、不补猜丢失的证券类型或时间。

## 验证

初始10项测试固定a5e90ce；后来增加原owner重试保留失败证据场景，当前17项。测试用内存Frame替身，含一次完整600行到主表prepare的合同连接，不联系SDK。测试均待Mac执行，不声称通过。
