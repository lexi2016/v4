# R3 独立审查与最终复跑

**结论：冻结实现范围内通过，未留下可复现的 P1/P2。** 可进入最终包整理和单独的 Mac 执行验收。

## 最终测试证据

独立运行 `tools/run_checks.py`，输出位于 `r3_review/final_checks`，精确 **352/352**：Stage 148、API 82、adaptation 50、Vue 45、当前 App Vue 27。所有 suite 退出码为 0，skip/failure/error/cancelled/todo 为 0。新生成的 fixture_runner、fixture_api、fixture_vue 均退出 0。

- SOURCE_MAP SHA-256：`3ec3e7774119bd106185c03be0b5c572b6fe2ca4148b93379d8b116a72994457`
- 期望文件 SHA-256：`37fe3362233af9bbb5f2d7cf54090e634e43ce4951ec81c3b346946fb5c29c7c`
- source policy SHA-256：`47fb035202d7cf8b8e087aef2abfc567066ac7c68f7302ca41f259e24638d1b5`
- 三份准备/driver 工具、SOURCE_MAP 和期望文件的冻结 SHA 在此次运行前后相同。

新 fixture 独立生成 695/695 行合成行情输入、10 行选股结果，使用原 runner/store/reader/consumer 与真实当前 App/组件 SFC 编译渲染。run_id 为 `run-2c40a8d057e1beffde847ab1`，历史回执与选股三件套绑定通过；execution_verified 与 natural_verified 都是 false。

## 已收口的审查发现

1. **P2：删除 prepare manifest 可绕过完整候选树绑定。** 独立反例曾在删除 manifest、加入未映射依赖后实际执行原 owner 并写出 HK10。修复后同一候选返回 `PREFLIGHT_FAILED / CANDIDATE_SOURCE_MANIFEST_REQUIRED`，owner 调用次数为 0，输出目录未创建。
2. **P2：os.walk 的目录分类可能跟随隔离链接进行 stat。** 已改为 no-follow 目录打开、scandir 取名称和 lstat 分类。独立 API 层探针对真实准备过程验证，仅发生允许的链接元数据/readlink 调用，未调用跟随目标的 stat/open。原生系统调用追踪因环境禁用 ptrace 未运行，不声称系统调用级验证。

## 关键合同核查

API 权限已独立完成真实非 root RED/GREEN：euid 65534 下旧 R2 报 Errno13，新 R3 使用新目标成功准备并恢复 0555/0444；source 字节、mode、uid/gid 不变，旧 partial copy 保留。精确内部链接、外部隔离、未知/改指/逃逸链接、有效配置与相关环境变量门禁均纳入最终测试。

UI 补丁从实际回传的两份源码和缺失组件状态干净应用，产生三份精确 after SHA。原 runtime 1540 字节前缀与 legacy 测试原字节保留；经理入口及既有操作事件仍连接到原 action。日期、阶段、market、run、artifact、SHA 和计数冲突拒绝计算标签，研究结果不会因自然验收缺失而被抹掉。

16 份 Stage 与 2 份 API after 文件逐字节等于冻结 R2；没有算法或 API 实现扩张。10 份反馈文件在本地重算 Git blob 身份后全部与 root 的远端读取记录一致，3112 反馈提交建立在 4db 父提交之上。

## 明确边界

真实 Mac prepare、真实 PyTDX、现役 HTTP API、重新加载的浏览器 UI、部署和自然时段验收均未执行。完整动态依赖闭包保持 CANNOT_CONFIRM。UI 测试的当前 App 与面板是真实源码，缺失的 useAppShell 和其他视图使用明确的合成测试边界；经理测试证明 action 连接，不证明现役目的页面。

`RESEARCH_ONLY=true`，其余三项生产/买入门禁/订单标记均为 false。此前 350 项复跑仅保留为修复前中间收据；最终验收使用此次 352 项结果。root 尚在整理的最终文档和派生包清单不包含在这一冻结实现审查范围内。

详细证据、文件 SHA、发现与边界见同目录 `FINAL_REVIEW.json`。
