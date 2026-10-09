# Stage / 经理工作台独立模块发布问题包

GOAL: 查清并隔离 Stage 与经理工作台的运行及发布耦合，交付可直接交 Chat 实施的最小拆分问题包；保留 8873 统一用户入口、原算法和权威数据 owner。
WRITER: isolation_package_writer，Luna Max，唯一 package/evidence/tools 写入者。
REVIEWER: 独立 Luna Max Reviewer，源码只读。
ARCHITECT: 原共享发布 owner 会话已派的唯一 architect，架构材料写 architecture/ 或其本轮目录；本会话不重复派架构。
ALLOWED_PATHS: 本目录 package/、evidence/、tools/、manager_evidence/、review/、architecture/和本批ZIP；主控 coordination/、交付元数据。
FORBIDDEN_PATHS: canonical业务代码、现役release、LaunchAgents、共享state、Stage和经理既有候选、Vibe8910、凭证、全局hooks。此批问题包不执行服务拆分或发布，不改算法、数据owner及BUY门禁。
PASS_SIGNAL: 实际耦合点证据→明确独立模块边界→按文件有限变更→可证伪交叉发布验收→回退；源码快照SHA、机读manifest、ZIP与GitHub固定字节齐备；独立Reviewer PASS。
STOP_RULE: 边界/owner冲突先协调，不双写包、不发布共享根；不足明确CANNOT_CONFIRM，不把文档描述算作运行隔离完成。

用户本轮明确优先：先解决两个模块互相覆盖、相互影响，再接续业务候选集成。经理R3和Stage候选保留，均暂停共享发布。
研究标志：RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false。
