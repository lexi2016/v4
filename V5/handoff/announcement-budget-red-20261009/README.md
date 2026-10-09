# 公告预算、HTTP 门禁与 V5 私有 owner 候选

当前阶段：874 Mac 55 PASS 后发现真实字节序列化缺陷；只做离线恢复，见 [OFFLINE_RECOVERY.md](OFFLINE_RECOVERY.md)。原 55 项不变，新增 7 项候选，共 62 项；新测试尚未执行。旧 BLOCKED 与证据必须保留，禁止重采。以下为历史交付背景。

最新为 db871765 之后的三项静态审查修复，见 [ISOLATION_REVIEW_FIX.md](ISOLATION_REVIEW_FIX.md)。原 47 项测试未改，新增 8 项，总计 55 项待 Mac 验收。当前五个完整候选包含新增原 CLI IO 接缝；以下为前轮背景。

状态：**IMPLEMENTED_MAC_REVALIDATION_PENDING**。云端只写代码并做静态语法、来源和哈希核验；未执行产品测试、未采集或部署。当前完整交付及 Mac 命令见 [HTTP_OWNER_FIX.md](HTTP_OWNER_FIX.md)。

父任务报告：79fcdf81be908169ca4f1db331899f07d94a0f65 的既有 31 项 Mac 回归通过；8124c9f6cb35ca4385c2e73bcd55482ee8a7bfa8 的 HTTP RED 为 1 PASS / 8 FAIL / 0 ERROR，exit 1。本轮基于该实际 RED 实现 HTTP 策略，既有 40 项测试文件逐字未改，另加 7 项离线私有 owner 验收候选。不能把这些待跑用例写成已通过。

完整生产候选位于 `candidate/`：原 body_batch、announcement_source、hkex_provider 三文件及新增 `ops/run_v5_private_announcement.py`。`pinned/` 和 SOURCE_MANIFEST.json 保持不变，固定原源 0fd5eb374cb155232ed003d5fc4d0d3594252491；OWNER_SOURCE_MANIFEST.json 和 OWNER_DEPENDENCIES.json 固定 0382f753929365048d231a7252d9c328d40f8522 的原成功链依赖，不读取 main 当前版本。

仅修改独立 handoff 目录。未修改主任务 manager_plan、workspace、UI 或 V4 运行文件；owner_dependencies 中 workspace 文件是按清单复制的原样依赖，不是主任务源码变更。V5 初始开发基线 945b89d7c3411a4913f50c4472514a61676c621e；本轮候选差异基线 8124c9f6cb35ca4385c2e73bcd55482ee8a7bfa8。本轮不推分支，由父任务转移固定候选。

历史材料 REVIEW_RED.md、REVIEW_FIX.md、HTTP_POLICY_RED.md 记录对应阶段，当前命令和状态以 HTTP_OWNER_FIX.md 为准。
