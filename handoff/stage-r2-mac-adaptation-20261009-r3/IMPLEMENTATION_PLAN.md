# R3 最小适配范围

基线是 R2 `7a9c94d43a296372488541b02e8e35a0f763dc1a`；反馈是 `3112c1ee8ed2826c5d77b5d0a4f1e2cd5fc95e45`。原包、反馈、Mac partial copy 均保留。

1. 按实际内部/外部链接制作精确源政策；UI 仅选 apps/web，排除根目录测试残留。
2. 仅对新候选所需目录临时增加写入权限，原 source 不 chmod；写完恢复最终模式并核验字节/权限/链接身份。
3. 用明确 add 合同创建缺失的新组件；当前 App/runtime 两份前像局部接线，保留 useAppShell 和经理入口。
4. 将同一候选 policy/manifest 接入研究 canary，避免准备后再被内部链接或只读 shared 副本卡住。
5. 冻结每套测试的精确数，检查真实 JUnit/TAP 结果与零 skip，并拒绝缺失或不一致报告。
6. 完整复跑原 Stage/API/Vue 与新增适配测试，独立审查；生成当前源补丁、R2 包增量、after、SHA 和 Mac 命令。

Stage 16 / API 2 的 R2 业务 after 保持原字节。HK 显式研究模式、STRICT 默认、既有行情和原算法、权重、Top10、A/HK 分离、研究输入与回执合同均保持。RESEARCH_ONLY=true；production_allowed/buy_gate_updated/orders_sent=false。

验证层级分开记录：隔离文件系统复现、源码测试、合成原链、Mac 真实行情、现役 HTTP/UI、发布、自然时段。后四项必须以实际收据为准。
