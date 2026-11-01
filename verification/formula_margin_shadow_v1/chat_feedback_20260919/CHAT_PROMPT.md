# 请 Chat 裁决修正方案：V4_FORMULA_MARGIN_SHADOW_V1

用户明确要求：Codex 落地执行、测试、反馈问题，由 Chat 给出修正办法；Codex 已停止自行修复。请先审阅问题和实际代码，给出一个冻结的最小修正方案与验收用例，不要增加第三条选股规则或开启新模型研究。

## 用户 DECISION_LOCK
主目标是命中“当日全部港股通股票的收盘涨幅前20”。不加市值过滤，不限D1池，不排除已大涨股票。D1 Top100仅为选股输入。旧73/150与221/450基于条件正市值truth，不能用作本轮全港股通基线。

实验为真实V4基线与公式辅助的shadow双臂：保持实际comparator的score前类别与同lane，只在rank10周围score模糊区H优先，非H保持顺序；tau来自原rank6..15中同类别相邻有效gap，缺数不放宽。三阶段09:35:05/10:30/15:00。5日工程canary、20日pilot、40日新样本验证均未开始。未创建自动任务，未更改BUY或交易。

## 状态与版本务必区分
第一版独立Reviewer：10项测试通过，但审查FAIL（5个P1及preflight P2）。第一版核心SHA=f8fa416dcbaf220ff0f871b4875d26c822db5bcc13867ac32c0f849e71aef735。
Codex之后错误地自行开始修复，已向用户承认并停止。本包源码是停止时的第二版checkpoint，不是第一版，尚未经过独立复验。Writer报告最近13项focused tests通过；此后还改了docs/ops，不能把它当当前完整独立PASS。包内旧engineering_canary_receipt属于旧版，特意不附，以免误认。

## 第一版独立验收的可复现问题（需要核对当前checkpoint是否仍存在）
1. P1：truth只检查自报universe_count、coverage_ratio、20个codes、任意tie_break/gain_definition、64位hash，没有实际校验全港股通成员/close全集或计算涨幅排名。任意HK.X01..HK.X20可READY，真实D1以外全市场rows反被LABEL_NOT_IN_D1_POOL拒绝。要求真实全集生成Top20再join选股池，而非相信Top20声明。
2. P1：production/formula provenance只校验SHA格式，artifact可选且与input_sha可无关。aaaa/bbbb/cccc/dddd等常量假SHA被接受。需实际字节、manifest与每行原排序/公式状态绑定，不能靠verified布尔值。
3. P1：仅缺currency/adjustment/price_source就把整体labels变CANNOT_CONFIRM，baseline_hit_count=None。命中与markout应独立：完整真实Top20有效则算hit，价格语义缺失只影响markout。
4. P1：shadow显式bucket_weight/no_trade_gate覆盖生产candidate_bucket/status，别名冲突时排序改变。示例candidate_bucket=FOUR_LANE_OBSERVATION,bucket_weight=2,trade_status_contract=WATCH_ONLY,no_trade_gate=0,stage_score=90,pct_chg=1,volume_ratio=1：shadow(2,0,90,1,1)，真实(1,1,90,1,1)。需遵守真实comparator或拒绝冲突。
5. P1：freeze_snapshot默认require_full_pool=False，15行短池可FROZEN。所有持久化前瞻入口应强制原100成员。工程receipt声称100行，但原focused fixture只有15行，独立验收未见100行证据。
6. P2：preflight空rows或畸形rows仍PASS forward_eligible=true，直到freeze才失败。预检须与实际准入一致。

## 已写但未独立验收的第二版checkpoint
Writer称已添加真实selector的默认关闭、失败隔离full-rank capture hook（selection.py）；真实source/hash与公式逐行校验；强制100行；全港股通close Top20计算；hit/markout分离；alias拒绝；capture CLI及负例测试。请看包内实际源码，不凭这些陈述认定修好。
最近Writer测试：.venv/bin/python -m pytest -q tests/test_formula_margin_shadow.py --basetemp /tmp/formula-shadow-pytest-review8 --tb=short →13 passed in0.16s。独立Reviewer尚未复验。
现有系统只保存Top10，本包hook默认关闭，无runner/scheduler接线，无真实前瞻输入或自然样本，不能宣称上线。现存历史池/收盘快照不能被包装为前瞻。

## 请给出具体回复
A. 先对上述问题逐项裁决：当前代码已解决/未解决/需要何种证据。
B. 明确唯一最小修正批次：文件/函数、输入合同、失败处理、必须通过的反例，不扩大研究目标。
C. 裁决真实全港股通成员定义、权威收盘涨幅字段/复权/同涨幅tie-break和停牌处理应如何绑定既有源；信息不足明确缺字段，禁止猜或另抓平行底板。
D. 明确哪些修复必须先做、哪些仅影响markout、哪些使整个命中单元无效。
E. 实际runner未接线且不创建自动任务的情况下，如何做最小真实手动canary；不得把合成测试当自然样本或宣称提升。

RESEARCH_ONLY=true; shadow_only=true; production_allowed=false; buy_gate_updated=false; orders_sent=false; automation_created=false; natural_sample_count=0.
