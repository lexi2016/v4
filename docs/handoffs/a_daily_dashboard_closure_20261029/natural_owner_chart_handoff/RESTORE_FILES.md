# 本批必要恢复文件 / 未部署依赖

本批精确提交：ops/research_panel_daily_product.py、ops/render_original_formula_projection.py、infrastructure/research_lane_source.py、apps/api/v4_api/research_lane_router.py；两新 tests；本专属handoff中的 SHA/差异/独审/SOP/单股复现入口。四源码本轮前字节均等于6bfb1ce7e829bf521e9a9c12bbd37b2fc5d1277f，提交只含本批hunks。

运行恢复还要复用6bfb已有C3：apps/api/v4_api/research_router.py、research-panel/numeric283-panel.js、既有daily.html和静态依赖；原 SourceContext 的SOURCE_CONFIG和已pin engine/formula/admission/core/census/原行情双pointer+generation/snapshot/native原件；既有SafeRoot/research-store/日更调度owner。R19 renderer 必须是 helper OWNER_RENDERER 的固定path/SHA，Node/Playwright/Chrome必须是已验证现成安装。未知或缺失时typed gap，不能另抓或另建producer。所有行情/大产物仍在合同目录，不纳入Git。

**明确未提交的既有脏依赖：** ops/macos_research_panel_daily_gate.py:586 已有的 materialize_daily_product 调用与结果隔离hunk是此前dirty，本轮没有改动、没有提交。它是自然owner入口接入依赖，Root需沿此前已审的精确字节备份/将来集成；不可把整个脏gate文件带入。本地preimages/ops/macos_research_panel_daily_gate.py记录本轮接手字节；与现文件SHA相同。ops/macos_research_panel_daily.py及任何其他dirty、app.py/untracked integration均未纳入本提交。当前运行release是否含该调用不能由本commit推定。

同owner durable恢复输入为 daily_products/a_share/{index.json,events/latest.json,checkpoints/.../original_retained/*.json.gz,versions/.../{product.json,manifest.json,original_charts/*}}；sidecar固定引用数字manifest，数字字节不引用sidecar，不存在循环hash。初始FAIL与before-fix diff/receipt及preimages本地原样保留；Git只纳入必要精简失败/修复证据，不上传备份全文。

安装/切换/自然运行是独立授权和验收阶段，本轮未启停服务/计划、未改pins/CURRENT、未push。15:40runtime、自然D30、历史同事件收益仍NOT_RUN；研究四旗true/false/false/false。
