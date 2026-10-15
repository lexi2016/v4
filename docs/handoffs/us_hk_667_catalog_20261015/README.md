# 美股→港股667只研究目录交付

已完成：原始资料核验、667股票/1003关系可追溯目录、现有经理工作台只读查询实现；独立Reviewer对目录功能REVIEWED PASS / BEHAVIOR_VERIFIED PASS。

本地完整报告与Excel在source/；派生目录在v4/manager_workbench/research_data/us_hk_667_catalog_20261015.json。所有来源自述状态保留，独立全量事实核验PENDING、预测UNTESTED、历史PIT NOT_VALIDATED、旧997边比较NOT_RUN。

原研究方分类为410只有具体候选、218只仅弱观察、30只无可靠关系、9只候选证据不足。这是原研究方分类，不是本轮独立事实验收数量。649只有B表关系记录、18只无关系行，不等于649只有当前有效映射。

独立一级来源抽查10边：8条日期事实腿支持、0冲突、2条当前适用性CANNOT_CONFIRM，见PRIMARY_SOURCE_SPOTCHECK.md。目录工程验收见REVIEW_RECEIPT.md。非阻断P2：468条数组形式URL暂仅原文显示、不能直接点击。

现有入口源码已接入GET /api/v4/manager-workbench/mapping-catalog和“美股映射资料库”页。未部署至8873，现役API/UI和自然时段未验收。源码测试不等于在线入口已更新。Writer全项目类型检查仍有5条既有范围外诊断，目标测试和scoped类型检查由Reviewer复跑通过。

## GitHub同步内容与复现边界

私有仓库lexi2016/v4；独立分支codex/us-hk-667-catalog-20261015；冻结远端基线b76d064cf1c5626a03969225ed7e509a96673390。

本分支同步精确源码差分SOURCE_DIFF.patch（5个既有文件改动+3个新增实现/测试）、rebuild_catalog.py、源文件SHA清单及精简研究/验收记录。ZIP、完整原始研究报告/表格、6.8MB派生数据、preimage原文件均仅本地保留。对应输入由用户实际回包提供，不声称分支自包含全量数据。

远端Workbench.vue/types.ts与本地本批前像有并行行业映射改动差异。为保存双方既有成果，不把整份本地文件覆盖远端。源码以精确patch交付，未将patch自动应用到远端应用文件；因此远端分支不是已集成可部署版本，远端集成/运行测试NOT_RUN。其他接口文件也统一以patch交付，避免半套接入。

复现需在与preimage_manifest.json一致的应用源码上核对前像，应用SOURCE_DIFF.patch，再运行rebuild_catalog.py生成本地目录，随后按IMPLEMENTATION_RECEIPT.md运行目标测试。若前像不同，应先按当前owner集成，不能覆盖或把本地验收冒充新基线验收。rebuild_catalog.py默认使用本机已提供ZIP和固定名单；可通过--help查看自定义输入路径，依赖现有Python运行时和openpyxl。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
