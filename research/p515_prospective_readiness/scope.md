# READINESS_COMPLETION_V1

目标为隔离的 R2 恢复、协调和来源证据补齐。R2 Writer 与协调器 Writer 各自独占其模块和测试，主控独占证据、交付与集成，独立 Reviewer 只读。
允许改动仅 research/p515_prospective_readiness/ 和 tests/test_p515_readiness_*.py、tests/test_p515_r2_resume.py。原 R2 文件、在用 V4、生产 A/B/C/D、旧工件和选股流程不得写入。
唯一技术验收信号是冻结范围内针对性零模型测试与独立复核通过。任何缺少的真实状态、授权、PRE_STUDY 或受管实盘接入保持 NO_GO。只跑合成或既有批准的小件校验。无 FIT、预处理 FIT、模型 API、新概率、静态新评分、新采样和旧七股终点更新。
