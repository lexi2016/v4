# 月度观察名单美股映射交付

已部署并通过独立验收。实际手动 run `2e2a1dbb1312422c8b1e21a58d2d44d0` 使用 US20261016 / HK20261020；API、重载页面 AX 与保存产物一致。API 为 `monthly-membership-api-20261018-r4`，scheduler 为 `monthly-membership-scheduler-20261018-r2`。身份、manifest 和证据 SHA 见 ROOT_DELIVERY.json。

严格入选0的根因是既有引擎尚无严格SELECTED规则；旧顶部统计还漏掉行业候选，错误显示观察0。现已正确显示条件观察153，页面明确严格精选未启用。修复没有发明严格选股规则或提升正式资格/PIT。直接来源60记录、36关系、19港股，与全路径去重候选701分别计数。月度方向池698：上行153、下行109、平盘0、待评估436。153/109是当前美股代理收益的研究观察分类，不能解释为未来收益或严格精选。

R3 live 的来源文案单位错误由R4一处文案及对应测试解决；历史FAIL保留。R4独立复跑4项UI测试PASS，部署后live leaf PASS；R3已有12项Python和4项UI验收复用。1246个非delta文件保持，配置及其他入口保持。API响应与R3同字节、同run/input/product/snapshot SHA，显示修复未重跑选股。全web类型检查曾有范围外失败，未声称全仓通过。

调度器经PDF owner协调，在新鲜空闲tick及无子进程/锁的间隙交接，2009文档索引保留，新owner tick已观察，独立PDF批次保持。历史URL失败没有因此全部恢复。

源码提交 `eb4567f8696cc76c8f8d995b3ffbe44874f51467`（基线 `d944648f45de2622447efdc0cb410b60c7f55a8c`）的16个文件已逐SHA256与Git blob读回；早期核心源码与R3阶段各有既有同步receipt。最终精简证据提交由本目录ROOT_FINAL_GITHUB_RECEIPT.json记录，不造自引用提交。仅上传必要源码、测试、复现脚本和小型结果，无凭证/配置内容/运行数据/构建包。

首个自然时段北京时间2026-10-20 04:15，原Issue45监控04:35检查，已更新本阶段口径，状态无变化时保持安静。自然验收、目标日正式资格、生效期及历史PIT仍未确认；截图因隐藏页宽度为0不可用，页面验收依据AX，不宣称像素验收。补齐资料第一批130只/183既有关系已在chat_supplement提交，不代表436待评估全部解决。

本修复范围完成并停止重复测试。保持RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
