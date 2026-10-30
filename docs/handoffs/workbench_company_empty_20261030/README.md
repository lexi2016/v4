# 公司资料不再被图表刷新清空

复现：首次进入D29工作台，688816.SH公司GET成功并已渲染；约5秒后已保存统计完成事件触发同股loadInteractive，OriginalFullChart.clear把公司两栏擦空，该路径没有重新loadCompany。重复点击首行可触发同类竞争。

沿原宿主/构建入口，图表clear只清图表状态；公司请求使用独立序号和股票、源日、观察日、generation、input SHA身份，当前股同源统计刷新不使公司回包失效。切股、切日、空筛选和source重绑使旧公司请求失效。两栏均显示当前股loading、missing或error，缺失保留CANNOT_CONFIRM，不编数据。

仅改bootstrap.mjs、company-local.mjs及原build_mac_workbench.py中公司渲染seam；输出恰好三个mjs变化。workbench.html及已通过的筛选布局不变；API、资料producer、公式、池、图表算法、调度和8910不变。

验证：原host/build测试22 passed，最后source-rebind增量的两项构建/确定性检查2 passed。真实8873只读API加三文件候选覆盖，初始、重复同股、统计刷新、688816.SH→920706.BJ→688057.SH切股、双栏加载/缺失/错误、迟到回包、source/date重绑共16项记录PASS；1440/694截图无pageerror。缺失/503/迟到由隔离浏览器路由注入，未改业务数据。原布局PASS复用。独立Reviewer与安装读回另记。

源码交付基线为前轮独立分支commit ad9b171da82309bae0ce3939c76997bb14baf264；固定46外部输入仍为0ae4a66d90c12a0d0335b5f7f65b528879c5e9cf，按上一轮DEPENDENCIES.md原命令构建。

回退保留上一轮workbench-filter-layout-20261030-r1-api与本次原API plist，通过既有owner lease/CAS/atomic-plist API-only路径恢复。不改Main或scheduler。RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false。

用户本轮决定：主营、财务与股东基础资料按季度更新，日常复用已有版本，并保留报告期、披露日和实际采集时间；切股、翻页和图表刷新只读取本地资料，不触发重新采集。已只读确认现役company GET经ResearchWorkbenchHost.company进入ResearchLaneSource.read_a_daily_company_materials，只读取本地index/manifest及已收到的单股shard并校验身份/SHA，不调用外部资料采集。本批没有新增季度定时器，也没有改现有producer或调度；季度自动更新是否已配置仍待其owner核验，不宣称本批已安装该任务。

这段季度约定是独审之后按用户决定追加的纯文档；三项业务JS SHA与REVIEW冻结值保持一致。
