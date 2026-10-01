# 给原Chat的唯一接续任务

请基于本Draft分支及research/hk-owner-asof-r3-20261001中的冻结R3修复，Mac仅负责交付、独立测试和后续接入。先读mac_delivery/MAC_STATUS_ZH.md、mac_delivery/review/REVIEW_RECEIPT.json、mac_delivery/CURRENT_PAGE_CAUSE_ZH.md和actual_dependencies/ACTUAL_DEPENDENCIES.json；完整源码、活动前像/后像、补丁、原bundle均已交付，不需再上传全项目。

唯一目标：使原HK owner→原publisher→主档/D-1产物→活动R9池存储→Stage链可执行，并覆盖港股开市而港股通休市的自然日期。A股已冻结，不追加A修复或重跑阶段，不另造producer/面板，不修改BUY。

本地独立验收FAIL。最小返修：1）R3 active projector无条件加入historical_provenance，并可能加入source_manifest_sha256/source_receipt_sha256，actual R9 PreselectionPoolStore拒绝这些顶层字段，实际19项12pass/7fail中3项是此合同错误。请协调真实存储合同并保留Stage要求的完整来源身份，禁止删掉provenance绕过校验。2）4项owner测试在setup失败：对actual executor_registry monkeypatch不存在的load_isolated_package_module；改为真实R9 facade/seam，并完成publisher调用和A池字节不变的测试。3）canonical19断言通过，但pytest只读合成快照清理PermissionError导致exit1；修复测试生命周期，使命令干净结束。

当前9/30页面的直接错误另有历史源缺口：主档索引没有20260929，原件run和完整universe当日目录未找到；9/29晚间receipt报HK connect close snapshot missing。现有9/29 Top100实际signal_date=20260928，用于目标9/29，不能挪用于9/30。请给出通过既有权威源恢复9/29真实价格/资格数据的最小入口；旧publisher限制采集当前日期，禁止伪造now/captured_at回填。当前missing目录证据只覆盖已配置权威根，不能证明整个Mac或既有上游的历史源都不存在；请先沿已确认owner定位原始历史价格/成员证据，再恢复。若历史来源无法提供，明确剩余原件缺口，不把代码通过写成数据已恢复。

日期规则：9/29开市；10/2、5、6、7港股开市、南向休市；10/3、4周末。价格D-1按HK证券日历；资格数据记录真实asof/capture，港股通休市不停止HK价格/预选研究。核对原publisher从自身app/upstreams/v3_shared_data加载严格universe reader，保持实际依赖身份。

请一次返回：固定commit和父提交、canonical/活动完整前后像及精确patch/rollback、变更manifest、可复现针对测试、能在Mac离线跑的同入口脚本、实际缺口。Mac实际加载的store/registry/loader/publisher/shared reader源码已随mac_delivery/actual_dependencies交付。保持Draft，不部署、不改原数据、不做selection；原件恢复及普通API/UI读回由Mac下一轮完成。
