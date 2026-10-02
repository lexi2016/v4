# Work一次接续

固定父提交：7ec9bceedceb56af97f4d365451d8560860cbc09。
本批不重跑Mac已经通过的27项。

1. fetch PR20最新head，在三个独立非活动根按SOURCE_SHA256.json核before SHA。
2. preselection_app、shared_package、stage_app三个patch分别只应用到对应根；不能叠加到错误根。before=after则跳过，第三SHA逐hunk适配并记录。
3. 使用当前Mac Python3.14.6运行本批`tests/test_hk_history_r5_target.py`；设置：
   `HK_R5_SHARED_PACKAGE_ROOT=<隔离shared_package根>`。
4. 追加P2独立负例：复用上轮natural_flag_probe fixture，只将`eligibility_asof.natural_verified=true`，要求R9 store拒绝；再对Stage隔离canary执行同一变异，要求Stage拒绝。不要运行provider。
5. 合成代码通过后，再按RECOVERY_COMMANDS_ZH.md先只读找9/29原authority；只有缺失时才执行existing MANUAL_RECOVERY。此步骤可能调用Futu用于当前完整集合corroboration，必须保存实际时间和官方evidence SHA。
6. 资格成功后再执行historical price mode。保存stdout/stderr/exit、history_provenance、panel manifest、所有before/after SHA。
7. 只有历史来源齐备，才执行原9/30 D-1物化；之后按原Stage/API/UI验收。Chat没有授权直接部署或selection。
8. 回退只回源码patch；不要删除已生成的不可变history/authority证据。若数据恢复失败，保留失败原件并停止。

完成代码验收仍不等于自然运行恢复。A保持冻结，不跑A suite/阶段。
