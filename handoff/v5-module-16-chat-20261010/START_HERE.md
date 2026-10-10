# M16：经理候选公开资料任务

日期：2026-10-10。沿原总计划M16/P4；早期盘点编号17。独立Chat写具体代码，嘻嘻在真实Mac固定候选上独立验收、接V5预览和回传缺陷。本包仅文档。

## 本模块做什么

面向原固定候选的公开财务/资料研究job，提供提交、排队/运行、结果、失败重试、取消及独立事件更新；保留原候选身份、来源、日期、cutoff、研究资格与原推荐语义。依赖已提交候选/阶段证据及M04资料，结果交M18消费，不自行更换候选、重算Stage或创建公告全市场扫描。M13公告生产、M17持续跟踪和M18计划各自独立。

## 当前静态事实

- 固定代码f7cb731c384ee6890a87d16c19a5b5a621779477的完整树未有manager_jobs.py。
- canonical原ManagerResearchJobService确有ensure/ensure_events/retry/job/cancel；原store有attempt/generation fencing与原子product/job/receipt commit。
- 修正旧计划表述：V5/vendor/manager_plan_baseline已有store/contracts/ports等，但此固定树没有service.py。不能说“完整job service已在V5闭包”，须补本模块完整owner闭包。
- 原GET缓存迁移明确为纯投影，不发布迁移；但原ManagerSelectionView在NOT_MATERIALIZED且can_ensure时自动POST ensure，V5读取页必须由共享集成移除此隐式执行或改成明确动作。
- 原store构造会创建jobs/products/receipts目录，不能在每个只读请求临时构造写store然后宣称GET绝对零写。
- ensure_events复用财务产品，只更新催化事件，不重抓PDF。取消按job+generation/attempt屏障阻止晚到发布；不表示底层已阻塞调用能立即杀掉。
- 旧任务状态HTTP500、部分公告材料接通均为历史报告，未证明M16生命周期完成。当前实际队列、provider/worker绑定和真实job回执仍待Mac核。

## 独占写入边界

候选新增V5/src/v5_shadow/manager_jobs.py、V5/src/v5_shadow/manager_public_jobs/（确需拆分）、V5/tests/test_manager_jobs.py、V5/contracts/manager_jobs_source_manifest.json、V5/vendor/manager_jobs_baseline/。这些尚未实现；先固定最小完整原闭包，不改共享manager_plan_baseline，也不把原service里公告/计划/US等入口一并接管。

运行仅M16私有jobs/products/receipts/attempts与不可变发布根。M18计划与M13公告输出根不可共写。前端、gateway、全局调度、manager_plan.py及共享contract仅交INTEGRATION_REQUEST，由唯一集成者处理。不新建认证、不读复制秘密、不扩大provider授权；保留V4及8910、不交易、不改BUY门。

先读PROMPT_FOR_CHAT、SOURCE_MAP和ACCEPTANCE。当前产品代码修改、测试、部署均未执行。
