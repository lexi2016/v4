# 给Chat补齐美股映射的问题包

本地交付：US_HK_667_gap_packet_20261015.zip，6,113,382 bytes（约6.1MB），SHA256 afd38328ad934a57ec67b006a632a9871c6b0eb42e253378b2c96aed185466cd。
独立REVIEWED/PACKAGE_VERIFIED PASS；不是关系事实或收益预测验收，也未替用户发给Chat。

上传这一个ZIP即可，包内原始材料齐全：667股票、1003关系、790组原始资产组合；首批20真实关系优先。请复制payload/02_Chat开场语_可复制.txt给Chat；详细要求见CHAT_COMPLETION_REQUIREMENTS.md（与包内01逐字节一致）。

目标是补证据、当前适用性、具体触发/反例和严格时序验证所需数据，不是重写667报告或增加映射数量。没有数据不得编回测；保留未核/历史/弱关系和断点。新回包仍需后续实际验收。

GitHub同步只含补齐要求、可复制说明、构建脚本、精简校验/独立验收和范围记录。ZIP、原始研究报告、CSV/XLSX队列和其他完整数据仅本地保留。GitHub分支不能替代这个完整本地ZIP下载。
源根/基线: /Users/lexi/Desktop/学习/v4_app，codex/system-consolidation-20260912，55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054。
同期业务代码和服务未在本批修改；本批只在新交接目录内新增产物。

工具限制：构建器用直接python命令重建，--help也会重建，不用于只读帮助。用户上传ZIP不需要运行构建器。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
