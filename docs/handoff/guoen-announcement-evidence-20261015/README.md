# 国恩科技两条公告：证据问题与修复结果

日期：2026-10-15。范围仅限原始两条公告的拒绝原因、校验器及固定事实解析器；独立 Reviewer 为 simple_review_resume。

## 查明的结果

- 收购完成公告（AN202610141830470256）：原文支持收购完成、持有 80% 权益及纳入合并报表；不足以支持原模型关于经营正面催化、业务扩大或经济回报的推断。保留 SEMANTIC_FAIL。
- 业绩预告（AN202610141830469348）：归母净利润 9.5–11 亿元、增长 54.45%–78.84%；扣非净利润 9.2–10.7 亿元、增长 54.14%–79.27%，原文均有支持。模型复合断言仅引用 U000016 / U000023，未覆盖区间上限和增幅所在的其他单元，保留 CITATION_INCOMPLETE。未补写旧答案或自动扩大旧引文。
- 两条共同遭遇校验器误拦：prompt 允许未披露的 confirmation_conditions / counter_evidence 为空，而旧 guard 强制所有证据数组非空。修复为入选必须有 facts 与 changes；CONDITIONAL_WATCH 仍必须有条件；所有已提供引用继续严格核验。
- 固定事实解析漏识别 PDF 的字间空格、繁体页眉法定名称和报告期间。已修复，并限制发行人名称来自开头身份区或明确发行人标签，防止后文标的/子公司名称被当成发行人。

## 独立验收

独立复跑 33 项测试通过：17 项合同测试、6 项既有公告选股测试、10 项固定事实解析测试。两条原始 raw 机械重放通过；14 项旧产物 SHA 保持不变。修复范围无 P0/P1/P2。机械通过不代表上述两条语义/引用质量通过。

实际命令与环境：

- canonical 根 /Users/lexi/Desktop/学习/v4_app：PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_guoen_announcement_evidence_contract.py；17 passed。
- 同根：PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_manager_announcement_selection.py；6 passed。
- pipeline_canary 根：PYTHONDONTWRITEBYTECODE=1 /Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python -m unittest test_simple_fixed_facts -v；10 passed。

## 来源与发布状态

本目录是交接快照，不是运行入口。canonical/ 对应 V4 唯一源码根；pipeline_canary/ 对应既有隔离公告调试路径。准确路径、文件前后 SHA、基线 commit、原始答案 SHA 和状态见 summary.json。只同步必要源码、测试和本摘要，未上传原始公告正文、队列、模型响应或凭证。

IMPLEMENTED / TESTED / REVIEWED；BEHAVIOR_VERIFIED 仅指此次 parser/guard 目标行为。未重启 8873，未发布选股结果，DEPLOYED=false；API/UI/NATURAL 为 NOT_RUN。旧答案、旧拒绝记录和旧队列保持原状。

后续跨多单元范围引用已有独立实现可复用，但本轮未迁移协议；现有协议已要求拆分原子事实，不能把模型不合规引用当作校验器误拦。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
