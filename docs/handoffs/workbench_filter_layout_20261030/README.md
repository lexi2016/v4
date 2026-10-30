# 工作台先筛选再看股票

范围与分组置于列表前并始终可见，默认全部候选；列表明确总候选、当前范围、筛选后、本页条数与第几页/共几页/每页容量。空结果清空当前选择并提示调整筛选。原40条页容量、247只冻结候选、API、公式、图表与研究边界保持原身份。来源覆盖说明移到已有来源详情，列表至少240px，可纵横向滚动。

源码基线为69d31e8971f38a00b4e76f84c48b45f08a3e4cb2，加现役workbench-rectification-20261030-r2-api已接受但尚未进入该commit的build/host依赖。实际差异只涉及ops/build_mac_workbench.py和mac-host/bootstrap.mjs，以及针对性浏览器回归tests/workbench_filter_layout.cjs；完整来源身份保留在本地handoff。固定46个vendor文件保持不变。

验证：既有test_mac_framework_host.py 22 passed；新增真实页面回归在694×869、1440×869、390×869使用三文件静态候选覆盖与8873真实只读API，通过scope/全部分组/search/分类/数量/跨页/切股/列头排序/空结果/日期保留，无pageerror。候选验证不等于部署；独立review和实际GET读回另记。

复现：提供现存Playwright位置至WORKBENCH_PLAYWRIGHT_MODULE，运行node tests/workbench_filter_layout.cjs。可选WORKBENCH_CANDIDATE_ROOT覆盖恰好三个候选asset，WORKBENCH_TEST_OUTPUT写截图和JSON；省略candidate变量时验证实际8873页面。

回退：保留旧release和com.lexi.v4.api.plist的SHA及字节，按现有API owner启动SOP原子恢复plist后仅重启该API，核验旧cwd和旧三文件SHA。不改Main、scheduler、数据或第三方服务。

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false。
