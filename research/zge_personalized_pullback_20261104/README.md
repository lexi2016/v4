# 个股习惯回调：R4 研究入口

R4 在相同历史事件和时间切分上，比较全局特征与加入个股过去分位特征的同配置 HistGradientBoosting 模型。结果为 `DIRECTION_ONLY`，独立复核状态及完整证据以外部 `HANDOFF.json` 为准。本目录是离线研究源码，不是 V4 API、生产服务或交易入口。

## 运行环境与产物

- 本次训练及模型新进程加载使用绝对解释器：`/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python`。当时 writer shell 未设置 `PANEL_PYTHON`；未来如显式设置项目解释器，应按该设置核对环境与身份。
- Python 3.12.13，pandas 3.0.5，NumPy 2.5.2，PyArrow 25.0.1，scikit-learn 1.8.0，joblib 1.5.3，threadpoolctl 3.7.0；设备 macOS arm64 CPU。
- 外部运行目录：`/Users/lexi/Desktop/学习/agents调试/Z哥方法论/pullback_model_design_20261104/training_v1/`。其中 `HANDOFF.json`、`EVIDENCE_INDEX.json` 和 `EXPERIMENT_CONTRACT_R4.json` 分别记录交接、文件身份与冻结合同；`R4_ENVIRONMENT_AND_RESUME_EVIDENCE.json` 记录解释器和部分权重续跑身份。
- 本代面板 generation 为 `e3ff25234adf18d8f29805a1107b36d61416b7bba3af8f3da9e63f17ee42fe09`。selector SHA `b33c2c90b1a379cd5bd93871dcea1f14f5a0d3fe5c74a732c39bbded127ec29a` 引用 producer 声明，未重新计算大面板文件 SHA；实际路径和来源限制见合同。
- `r4/full/METRICS.json`、`FEATURE_MASK_REPORT.json`、`FEATURE_MASK_TESTS.json`、`ANCHOR_BRANCH_DIAGNOSTIC.json` 是 R4 结果和针对性检查；`r3/full/LABEL_BOUNDARY_TESTS.json` 对同一事件标签与观测日期序列记录边界检查。模型、投影、日志、原始面板及检查点保留在外部运行目录，不提交本仓库。

## 已执行的入口与续跑

以下是本批实际使用的主要入口，**不是要求重新运行已完成训练**。命令会读取本地面板或缓存，并写外部产物；新的实际实验须先按因子工厂合同登记 `RUN_STARTED` 和终态。

```bash
cd '/Users/lexi/.codex/worktrees/zge-pullback-training-20261104/v4_app'
ZGE_TRAIN_PY='/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python'
ZGE_SRC='research/zge_personalized_pullback_20261104'
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 "$ZGE_TRAIN_PY" "$ZGE_SRC/r4_canary.py"
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 "$ZGE_TRAIN_PY" "$ZGE_SRC/r4_features.py"
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 "$ZGE_TRAIN_PY" "$ZGE_SRC/r4_verify.py"
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=12 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 "$ZGE_TRAIN_PY" "$ZGE_SRC/r4_fit.py"
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 "$ZGE_TRAIN_PY" "$ZGE_SRC/branch_diagnostic_r4.py"
```

先读取已完成的 `r4/full/FIT_CHECKPOINT.json`、合同、输入和模型 SHA；身份一致时复用已完成结果，不为换入口重扫面板或重训。仅在恢复同一未完成执行时，核对登记、`R4_CODE_BINDING.json` / `R4_RESUME_BINDING.json`、目标 row group、代码及数据 SHA，并使用已有逐股 correction 检查点。R4 首次拟合在辅助参数比较处中断，fold 1 的两份已保存权重经绑定和新进程预测核验后复用；失败日志与源码留在外部运行目录。输入、代码或合同发生实质变化时另行冻结身份和登记，不能静默覆盖既有产物。

## 已完成的时间外结果

R4 包含 424,604 个事件、422,359 个已知 R10 标签和 2,245 个 UNKNOWN。七只保留旧口径股票已排除，因此这不是完整全 A 样本。四折相同训练/测试行比较如下；分数未经校准。

| 折 | 训练事件 | 测试事件 | 全局 AUC | 个体化 AUC |
| --- | ---: | ---: | ---: | ---: |
| 1 | 127,947 | 73,060 | 0.5085 | 0.5167 |
| 2 | 202,712 | 65,406 | 0.5270 | 0.5266 |
| 3 | 270,917 | 92,726 | 0.5250 | 0.5223 |
| 4 | 363,966 | 50,750 | 0.5381 | 0.5366 |

结果方向不一致，未证明个体化稳定提升。价格目标为 `close(D+10) / open(D+1) - 1` 的方向代理，D+1/D+10 使用全市场面板**观测日期序列**精确匹配；该序列并非已认证交易所日历，缺价及未成熟保留 UNKNOWN。

面板 PIT 未认证，2026 历史已暴露且没有封存集。因本代公式源码身份未匹配，669 只股票的 53,720 个事件在首个无效 OHLC 后，对可能受影响的全局输入和个体分位置为缺失；事件、标签及其上游触发身份并未因此获得认证。未来扰动测试只覆盖已物化触发字段之后的下游逻辑；单股 API 的 107 项知识库样本也不代表面板全市场均有这些字段。

本结果不证明可成交性、扣费净收益、策略有效性或买入资格；`RESEARCH_ONLY=true`，生产、BUY gate 和订单权限均未改变。注册表全局严格语义校验仍因四条既有事件失败，本批登记仅对其精确历史 SHA 使用已记录的兼容范围，不声明全局 PASS。

## 独立复核

独立复核结论：`PASS_BOUNDED_R4_TECHNICAL_SCOPE; PERSONALIZATION_INCREMENT_NOT_ACCEPTED; REMAINS_DIRECTION_ONLY`。复核覆盖 R4 特征缺失遮罩、冻结时间切分及 16 份模型的加载和预测读回；PIT、官方日历、封存评价、概率校准、策略和生产许可仍未确认。

回执：`/Users/lexi/Desktop/学习/agents调试/Z哥方法论/pullback_model_design_20261104/training_v1/review_r4/INDEPENDENT_QA.json`  
SHA-256：`ea54b35e4068f21a909b2a94f3fa707cf9f27eb2c67b207059b6282ebe36a2fa`。
