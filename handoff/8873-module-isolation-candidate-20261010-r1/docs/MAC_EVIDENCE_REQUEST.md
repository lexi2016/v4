# 给当前 Mac 执行者的最窄证据请求

当前交付已有可复核代码、正反向补丁、106 项隔离测试及独立审查；请求下面证据是为了完成尚未成立的现场绑定，**不授权切换或启停服务**。

可直接转交以下任务：

> 请继续 Issue #30。先只读收集下列 4 组事实，输出一份带时间、命令、退出码、证据文件 SHA 的本地证据包。不要修改/安装 plist，不调用 bootout/bootstrap/kickstart，不运行历史 reference switch，不写 owner state，不改 Stage/Vibe/BUY/交易门禁。安全标志保持 RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
>
> 1. **当前唯一 gateway 身份。** 确认 `com.lexi.v35.api-only` / `127.0.0.1:8873` 的实际 plist、运行程序/解释器、当前 release id/root、release-manifest SHA、完整 app inventory SHA（含 static）、现有 generation 或明确尚无该字段。记录读取前后 plist/manifest SHA，变化则停止并重读。只提供必要身份字段，不导出完整环境、凭据或真实业务产物。
> 2. **实际正在使用的发布命令及调用闭包。** 给出真实命令入口路径、源代码 SHA、其 launcher/readback/CAS/失败恢复函数；尤其从 inactive candidate 到最终 immutable release 的 staging/copy/manifest 重写步骤。指出当前调用是否仍是 2026-10-08 reference，以及是否存在使用另一把锁或全量旧 rollback 的旁路。把对应源码作为只读证据提供；不要用一份“相似脚本”代替实际命令。
> 3. **最先一个真实业务模块的最小 owner 审核。** 只选择能确认的一项，不按五个中文工作区目录猜 owner。列 module_id、唯一 source owner、精确可改文件、完整 import/route/consumer 闭包（method/path）、共享 seam owner、构建输入/输出和所有外部 data/state roots、读写方式与 rollback 兼容证据。无法确认项保留 CANNOT_CONFIRM。不得直接把合成 alpha/beta 或 PROPOSED 模板批准为真实模块。
> 4. **共享/静态和失败语义裁决。** 固定当前 dist 全量 inventory、HTML 到 hashed assets 的引用图、Vite entry/build identity，并判断本次候选是否能保持全部共享 bytes 不变。解释实际 publisher 在 loaded-but-not-running / identity-unverified 情况下如何在不影响未知进程的前提下恢复；没有可靠恢复证据则保持 ROLLBACK_INCOMPLETE/CANNOT_CONFIRM，先停止切换。
>
> 收到证据后，先重新核对本包 before/copied SHA 与当前源码；有差异就重建具体候选并重审，不能强行套补丁或直接沿用旧发布 pins。完成 owner 契约、当前原生入口接线和 staging/失败语义后，先交不同 identity Reviewer；真实 service action 留待另行授权。

## 为什么必须有这几项

任务明确要求接入“真实 8873 原生发布入口”，而输入 publication chain 只证明历史脚本和 source snapshots，未给出届时当前命令/immutable staging 的完整可用绑定。输入 MODULE_MAP 也明确真实 owner/source/build/state 映射 CANNOT_CONFIRM。缺这些事实，继续写一个“当前已接通”结论会超出证据；增加服务或绕过旧启动体系同样违反原目标。

本请求要求必要的源码、标识和摘要，不要求复制真实 state、全量环境、研究产物或凭据。即使收到这些证据，也不自动构成 live 发布授权。
