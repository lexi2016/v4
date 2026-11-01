# 三股 F10 完成事件的现役 owner 绑定

原三股计划从隔离源码树执行时，意外载入旧版 `ops.sync_stock_history_completion`，缺失现役 Main 的锁继承函数，发布在写入前失败。新入口核对运行中 Main 的 plist、PID、工作目录、manifest，以及既有 F10 publisher、锁 owner 和 daily product 模块的精确 SHA；随后从该 Main 载入原模块并执行原计划。它不采集行情，不另建 publisher，真实发布仍使用原锁顺序与 index/event CAS。

原两股 F10 快照不变，理邦使用已捕获的同股快照。真实 publisher 在隔离 index/event 上完成发布并拒绝过期 CAS；现役 index/event 的实际发布仍由主控在独审后执行。此入口固定当前 owner 身份，Main 更新或重启后必须重新核对并绑定，不能绕过失败继续。

具体路径、SHA、检查和发布命令见本地证据根 `f10_three_completion_r1/owner_binding_r3/F10_OWNER_HANDOFF_R3.json`。本次仅供研究；未改全局面板指针、seed、交易门或调度配置。
