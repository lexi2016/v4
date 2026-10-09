# 经理R3共享发布接续约束

状态：只读准备完成，政策独立审查PASS_POLICY_ONLY；候选未发布。核查时间及SHA见SHARED_OWNER_CURRENT_IDENTITY.json。

- 唯一共享发布owner：制定港股阶段修复计划，chat 01a0ff4f-2b8f-7311-add9-cba3f560cc4d；经理会话继续独占本批候选装配及业务独立验收，不另起发布者。
- 当前API：issue32_preselection_api_actual_r4，PID78617；当前scheduler：issue32-preselection-scheduler-mac-20261009-r1，PID83677。API/scheduler/Stage三个manifest实际SHA均匹配配置pin。
- API旧经理绑定路径仍为c1_plan_only的disabled.final-d1-r2；scheduler公告绑定为manager-plan-binding-r2。不得把两者当已一致，需新双根binding真实canary后生成，API与scheduler核同一原始JSON SHA。
- 仅在独立Reviewer提交完整候选路径、actual-base/after清单、保护文件一致、根对应和定向行为PASS后进入发布准备；Chat侧测试不是本机PASS。
- api_current与api_r2_increment二选一。当前应匹配Issue32现役前像；worker5/HK child3/web4分别核对各根，不混根、不整树替换API。
- Issue32三保护文件apps/api/v35_api/app.py、preselection_router.py、preselection_service.py保留现役字节；scheduler daemon/launcher保持，不因新业务改动回退已发布修复。
- 原API发布工具为V4_ISSUE32_MAC_20261009/tools/api_only_cutover_issue32_r4.py；上次receipt的guard来自V4_ISSUE30_MAC_20261008/package/after/ops/api_release_integration.py，不能将canonical未经核验工具自动替代现役协议。
- 原共享锁/Users/lexi/Library/LaunchAgents/.com.lexi.v35.api-only.release.lock为空、lsof无持有者。这只是观察，不是持锁授权或预约；不删除空锁。后续采用实际发布guard原协议，在锁内重新核active plist、manifest、inventory、delta receipt和共享文件前像。
- 只按独立政策审查的五条exact path应用政策增量，不允许通配、删保护或跳过delta。政策PASS不等于候选BEHAVIOR_VERIFIED，更不等于发布授权票据。
- 除本会话和经理候选会话外，最近15个非置顶chat未观察到另一个活跃共享发布任务；非全局互斥证明，以实际锁和基线CAS为准。本会话未申请发布锁、未切换服务。
- 待发布时按配套identity/binding回退边界形成一次受控切换；保留10/8 dynamic、10/9 auto真实计划/同run/输入身份/API/UI及自然槽分别验收。缺输入仍明确BLOCKED/CANNOT_CONFIRM。
- Stage定时服务当前不运行、last exit code=3，仅作为现场身份记录；此次不扩大为Stage修复或重跑。

本轮IMPLEMENTED/DEPLOYED均NOT_RUN，研究及交易安全边界不变。

## 独立政策裁决

独立Luna Max Reviewer已确认五条exact path增量PASS，无P0/P1，详见SHARED_OWNER_POLICY_REVIEW.json。当前guard SHA与固定包before及Issue32发布回执一致。锁为原guard的持久fcntl.flock协议，空锁正常，不应改用canonical通用.mutex协议或删除inode。

保留P2：本范围未包含政策定向测试receipt及最终经理候选差异证明。待经理独立验收提供后，再判接入条件，不将政策PASS升级成候选TESTED、BEHAVIOR_VERIFIED或部署完成。
