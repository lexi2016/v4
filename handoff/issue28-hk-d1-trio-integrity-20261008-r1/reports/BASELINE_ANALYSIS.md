# 原交接测试与 owner 差异

原测试 `harness/tests/test_hk_prior_observation_source_binding.py` 来自固定提交 `30ad7bb633f715f30c4e10eb67e9041de92cf036`，SHA256 为 `6a48bd3357a97690d5886c03dff9e31fc84ae1a0357087bcca3f4168841cd930`。共 19 项，文件原样保留，没有筛除失败、skip 或 xfail。

| Owner | 原像 | 候选后像 | 比较 |
| --- | --- | --- | --- |
| actual_stage_owner | 12 PASS / 7 FAIL | 12 PASS / 7 FAIL | 失败名称逐项一致，0 新增失败。 |
| canonical | 17 PASS / 2 FAIL | 17 PASS / 2 FAIL | 失败名称逐项一致，0 新增失败。 |

实际 Stage 的七项均发生在 `20261007` 港股通休市的观察分支。旧 runner 未具备 canonical 的 exact-target 优先、目标出现后重探、坏目标拒绝及相应 binding-mode 标记：两项为 role / evidence 不符，五项为未抛出预期异常。这些是保留的版本/行为缺口，不能当作通过。10/8 港股通开放，两个 owner 进入本轮共同 HK validator 分支；本候选没有替换 runner 或扩展休市观察策略。

canonical 两项是 `test_real_calendar_prefers_verified_exact_target_pool_as_research_observation` 与 `test_split_date_provenance_captured_after_eligibility_date_is_rejected`。旧 fixture 缺少现行合同要求的 `d1_source_artifact_relative`，在物化阶段就被拒绝。late-capture 用例没有到达它意图验证的 Stage 层，不能解释为 Stage 接受过晚 capture。本轮新增测试单独构造完整合成 fixture 后分别验证 capture、旧行日期等条件；原 fixture 未改，合成数据不等于真实来源恢复。

前像原始日志：[actual](../evidence/original_before/actual_stage_owner.log)、[canonical](../evidence/original_before/canonical.log)。后像日志：[actual](../evidence/author_after/actual_stage_owner_original.log)、[canonical](../evidence/author_after/canonical_original.log)。逐项对照：[BASELINE_COMPARISON.json](../evidence/BASELINE_COMPARISON.json)。独立 reviewer 读取并比较这些 JUnit，全部失败名称见 [review](../review/review.md) 与 [KNOWN_BASELINE_FAILURES.json](../review/KNOWN_BASELINE_FAILURES.json)，没有把读取日志称为独立重跑原 suite。

两棵 owner 各 13 份精确源码，有 6 对相同、7 对不同。测试确实分别加载 runner、calendar、Store、reader、resolver 和共同 HK helper；ops 入口与完整 slot 仅静态检查。17 份补充导入中的 16 份是固定 SHA 的历史 canonical 参考，一份 namespace 使用已核验的通用 `read_global` 字节作为明确的测试包装别名。补充导入不能冒充完整当前 Mac runtime 身份。见 [INPUT_MANIFEST.json](../harness/INPUT_MANIFEST.json)。

本包可移植入口为 `harness/run_regressions.py`，参照 [README](../README.zh-CN.md)。`--suite original` 保持非零退出；`--suite targeted` 为 13 项新增用例加 reviewer 的 2 项目录身份用例，每个 owner 单独执行 15 项。
