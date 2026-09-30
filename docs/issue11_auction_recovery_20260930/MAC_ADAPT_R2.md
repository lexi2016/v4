# A09:25 Mac 三方适配 R2（不执行恢复）

冻结 PR12 `cb33d2fe2241079f46ae5e09e605f11a2fd5462f`；现场证据 `a60fbd8c55aa1fad637d8706ceada0db251ffb97/research/pr12-pr13-mac-evidence-20260930`。本批只修改 dispatch，补两份持久回归，不更改已经独立验收的 node_entry 授权合同。经理/F5不在范围。

## 已实现

把证据包 BASE_TO_MAC_ACTIVE 中的两个完整 helper、settled-partial 未耗尽恢复分支、decision.same_day_late_observation_recovery 标记与 PR12 一次恢复额度组合。先机械重建现场 dispatch，SHA 精确等于 `dcb4784d1374fbe8f9076646b6befba4b48331826a7f07a82c25e497820689d4`；再适配，不用PR12旧前像覆盖现场。HK分支只用原剩余额度，A授权仍原三次+额外一次，不清零计数。原六个attempt和205输入合同未改。

源身份：
- dispatch现场前像：`dcb4784d1374fbe8f9076646b6befba4b48331826a7f07a82c25e497820689d4`；后像：`955630c90ee8f7836597d8acf515eca2b2dcd240632823c6f552acfdafa76231`。
- node_entry现场前像：`54defb0f45adbafcf4b661611f41d0b43d89abf492d89d587c28962eff9b36fe`；本批复用PR12后像：`e8707873a23284626f5af44aa7ede9b273e464f1d66bf79dd608099abf451dba`，未再修改。
- 现场已修collector：`728fa6e64914942e651e62442caa83becbc6aef4705ebea59e17a544b36ea00d`；provider：`02d7505614b66768f6c3f6b86e4e606f0df9f4fabb6aaad5ea8f8a0fa3738260`。来自指定现场源码差分/身份，不宣称本容器加载了现场文件；本PR不回装旧collector/provider。

## 验收

复用本机独立反馈：冻结PR12在实际服务Python下58项通过，另一次公开入口探针通过。此结论不自动扩展到本批新组合。

本批实际执行：
`python -m pytest -o addopts='-W error' tests/test_issue11_public_entry.py tests/test_issue11_mac_dispatch_adaptation.py -q`
结果 **10 passed in 0.12s，exit0**（作者Linux，合成边界，非Mac/行情验收）。未改产品PR12上新增Mac分支测试先2失败/7通过；组合后通过。公开入口测试去掉fixture的私有sentinel，经真正run_nodes创建能力，并验证一次消费、旧字节保全、不变调用者config与拒绝第二次。Mac分支测试验证late标记和原剩余额度，错误/日期/状态/安全位负例拒绝。没有重跑58项或五个实际A阶段。

## Work一次接续

在非活动隔离目录读取本PR与现场证据。核上述两个ops前像；node_entry复用PR12最小差异，dispatch使用本批合并后像/针对现场前像的diff。不要更改现场已修collector/provider、slot_execution或其他有效阶段。发布pin若存在仍须按原审核流程绑定新源码，不取消检查。

以实际服务Python执行上述10项新回归；保留原58项独立回执引用，仅对修改交集做必要回归。核原六个attempt的相对路径/字节SHA（证据包attempts_metadata.json），通过原candidate reader分别核current、artifact和原序codes SHA；它们绑定不同对象，不要求相等。小证据包不是完整canonical/release统一快照。

本轮不构造APPROVED记录，不执行205只恢复、不部署、不API/UI实测。20260930日期硬界保留，过期后拒绝，禁止伪造wall clock或默认延长。真实补跑需另行明确批准；Issue11保持Open，PR保持Draft。

状态：源码适配/新增合成测试已完成；不同身份新组合审查、Mac隔离集成、部署、真实run、8873 API/UI、自然运行未执行。
