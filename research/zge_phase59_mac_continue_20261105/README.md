# Phase 5.9 Mac 续训（A 股研究）

本目录是独立研究训练入口；最终 T5 权重在目录外，原云端包和旧模型保留。最终模型仅用于 `DIRECTION_ONLY` 研究，不能用于 BUY、订单或生产。

## 已完成与模型链

- 原 CPU T5：SHA-256 `522cdb4f704c227fa61c8cc702a46f57fe3b2249a8ae78b386ebf258e20f2548`。原包样例 2,500 × 87 特征重建与原模型同输入预测通过。
- 历史 replay：303,161 行输入中，295,916 个成熟标签、5,572 股真实续训。模型 SHA-256 `63c66f90badd425dcc2607fced5b6d378856be5605beb6184204dcca64d20708`。这些历史已经暴露，非新日期或封存评估。
- 本地标签增量：既有 10/09–10/15 特征键中，6,602 行、5,530 股以本地 11/04 同代行情补齐成熟 T5 标签并真实续训，原 parent 训练键重叠为 0。剩余 62 行为未知或明确排除；z11 在本批无可绑定观测，保留 parent 先验。树 42 → 52，其余 11 维按可用结构观测更新，各维实际变化的股数见回执。最终模型：
  `/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105/local_increment_v1/model_t5_local_increment.pkl`  
  SHA-256 `ba3553516af05dec467299579dccc7d8c418882dbd4cc89433b4722c2df9dd43`。
- 父模型和最终模型对全部 6,602 个相同输入键的新进程加载预测误差均为 0。比较是在训练行上计算，只供复现，不能推断未来表现或提升。

独立审阅结论为 `PASS_BOUNDED_TECHNICAL_EVIDENCE_ONLY`；模型接受未授予，复核范围及未执行项见 `/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105/review/INDEPENDENT_QA.json`（SHA-256 `e8a55a59a03921979197170a805c61153c437571a9f26b51cb2d30d386dcac81`）。

## 环境和入口

训练 Python：`/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python`；Python 3.12.13、NumPy 2.5.2、SciPy 1.18.0、pandas 3.0.5、PyArrow 25.0.1。子进程须使用同一解释器。仅用 `runtime.py` 的限制类白名单与固定 SHA 加载模型；不要直接对外部 pickle 使用无限制加载。

- `reconstruct_fidelity.py`：按已锁定 STEP7 源复原 87 列；`build_candidate_hard.py`：对已确认或未证的字段做 UNKNOWN 掩码。完整输入和训练合同见外部 `FIDELITY_87_REPORT.json`、`HARD_CANDIDATE_REPORT.json`、`FULL_HARD_FIT_CONTRACT.json`。
- `fit_hard_replay.py`：云端历史成熟收益秩、κ=0 的受控续训；`verify_hard_replay.py`：新进程权重/预测回读。
- `local_v1_canary.py`、`build_local_label_overlay_r3.py`：本地版本标签与原始键分离；`fit_local_increment.py`、`verify_local_increment.py`：新增成熟键拟合和回读。R1/R2 失败及修复记录保留以对应注册表；R3 复用已验证价格投影 checkpoint。
- `registry.py` 通过原锁和 builder 追加本批执行；全局历史登记仍为 `FAIL_PREEXISTING_SEMANTIC_DEBT`，只有本批新链在精确四条旧事件兼容条件下通过。每次真实 fit 或推理前需冻结新合同、输入/代码/模型 SHA 并登记 `RUN_STARTED`；不能复用已终结的 execution ID。

产物和可机器检查的摘要位于：

```
/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105/HANDOFF.json
/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105/full_hard_replay_v1/FIT_RECEIPT.json
/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105/local_increment_v1/FIT_RECEIPT.json
/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105/local_increment_v1/FRESH_PROCESS_VERIFICATION.json
/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105/inputs/HARD_CANDIDATE_87.parquet
/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105/inputs/LOCAL_LABEL_OVERLAY_R3.parquet
```

只读查看已完成回执，无需重新训练：

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python -m json.tool '/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105/HANDOFF.json'
```

训练脚本会保护现有输出目录；新实验必须使用新合同、execution ID 与输出位置，并优先复用匹配 SHA 的 87 列和价格 checkpoint，不重扫历史指标。数据、模型、checkpoint 和运行日志不放 Git。

## 研究边界

本地标签 `LOCAL_PANEL_QFQ_ASOF_20261104_OPEN_TO_OPEN_T5_V1` 使用相同本地 generation 的 D+1 与 D+6 open，要求两端正成交量，停牌/缺价不顺延；7 个旧复权口径股按合同排除。日期使用全 A 面板观测日序代理，非已认证交易所日历。云端与本地来源/asof 不同，价格和收益的完全等价 `CANNOT_CONFIRM`；用户已裁决两位显示精度差 `USER_ACCEPTED_PRECISION_NONBLOCKING`，两侧原值及旧 exact-parity 失败均保留，不以 round 修改训练价格。

云端样例与主投影的 `rev_r2_engulf_flag` 有 6 行差异；复原按 STEP7 使用第二源，差异的上游业务语义仍 `CANNOT_CONFIRM`。

原权重、预处理器和先验已有历史暴露；新 posterior 用不依赖教师、旧骨干预测或旧 imputer 的结构收益秩及暴露先验做正则续更，不能称为精确贝叶斯更新或 PIT 清理。11 个 teacher 输入保留 UNKNOWN，行为画像和 P53 已知未来区间屏蔽。来源实际首次可用时间、完整 PIT、评分校准、封存测试和策略有效性均未认证。T1/T2 只恢复/样例验证，未在本批增量训练。11/04 面板只发现 4 个同名列、83 个名称不匹配；同名也未证实语义，未生成 11/04 的 87D 新特征。
