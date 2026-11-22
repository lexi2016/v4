# PFT 纯 S V1.1 固定对照

CODEX_MAC 按 2026-11-22 签发标准执行。研究入口为 `ops/pft_s_first_baseline.py`，对应实现提交 `6b9ec29b2dc8af08aeb66b6aa68c86a55b3a1fda`。当前 V4 A 股前复权面板代次为 `4ed1e1e3ccc2f1045a83527a470f111b81d96771b105ba92e8348bf7f967b268`，所有属性按各自观察日截断。

G1 要求白线严格高于黄线。G2 对触发签发条件的高位滞涨或宽幅反抽给出硬拒绝。近五棒连破与较早破位的双线修复分列。关键 K 锚低守位、前 10/20 棒高点及缩量回踩、放量再推进的交互特征进入固定配置。缺线作为数据缺口处理。

共同表签名 `f6c24afed7fc021f1ec376e1b28874134e0a9691d11e3c9f2e63a9c2da9f12b6`，预检覆盖 54/54。27 条已定训练行用于 StandardScaler 和 balanced L2 LR 各一次拟合，阈值 0.5，超参搜索 0 次，B 拟合 0 次。固定验证 16 条定见中 G1 拒绝 6 条、G2 拒绝 2 条，均为共同负例。门控拒绝行在整体策略指标中使用判定 FALSE，LR 概率为空。11 条 UNKNOWN 保留原标签并排除拟合及评价。

| 固定验证 | TP | FP | TN | FN | 平衡准确率 | F1 | ROC-AUC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| R1 | 0 | 0 | 13 | 3 | 0.5000 | 0.0000 | 0.7949 |
| V1.1 | 1 | 1 | 12 | 2 | 0.6282 | 0.4000 | 0.7949 |

601019.SH 2026-11-19 转为真阳性。300094.SZ 2023-02-13、601019.SH 2026-11-16 仍漏报，000610.SZ 2026-11-19 新增误报。300308.SZ 2023-03-22 的签发训练正标签与 G2 拒绝存在分歧，训练沿用原标签。八个新提名只供后续共同样本裁定。固定验证属于已曝光开发诊断。研究结果待 CHAT 审核。

`tests/test_pft_s_first_baseline.py` 33 项通过。权重重载在 18 条实际 LR 概率上最大差 0。冻结 R1/R2 提交保留原版本入口。 [签发标准](https://docs.google.com/document/d/1pFSH3amu2FZNRZncvkAsBWUGvFlcjcn9l6sbBfd6oSg/edit) · [成果目录](https://drive.google.com/drive/folders/16sjGLi3-UjILcV0VJbiIN0MrnqJO-voQ)
