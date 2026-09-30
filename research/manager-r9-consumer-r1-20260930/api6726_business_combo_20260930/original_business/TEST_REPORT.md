# 作者定向测试记录

最终命令与开始/结束时间见 logs/verification.json；实际stdout见 logs/*.txt；JUnit见 logs/junit.xml。

| 面 | 原前像 | 修改后最终同一次完整运行中的范围 |
|---|---|---|
| B1 | 9 failed（六个测试函数，含四种篡改参数） | 20 passed |
| B2 | 4 failed / 4 passed（B1已修输入树、原worker） | 8 passed |
| US | 7 failed / 6 passed | 13 passed |
| 总修改后 | 不合并不同前像计数 | 41 passed / 0 skipped / exit 0 |

最终41项在 runtime.patch + cycle_snapshot.patch 真正应用后的全新临时源树运行。两份源码补丁反向回放后逐字节还原；tests.patch另由verify_delivery重放。protected workspace.py(R3B)、connect_selection.py(R2)、preopen autorun SHA保持不变。

B1用原 refresh/MaterialStore/ManagerResearchStore、原响应envelope和PDF/source校验。PDF为极小明确合成文档。旧引用存在但同一URL最新索引变化的场景可复现；新索引见证存同一MaterialStore，无第二采集器。含default两批/轮转/singleton、重复/双capture身份、legacy/crossday、失败/提交中断/存储失败、cutoff、body/refs/raw/snapshot篡改、GET无写与预算拒绝。

B2用原worker main、原autorun、原workspace _compute/refresh/readback和真实临时磁盘事务。验证两批股票进入原saved workspace、last tick采后消费、跨09:30不回补、同一input identity不重产；没有重新运行R3B诊断测试。collection回调在测试里调用原镜像owner，不声称snapshot的schedule分支现场已接到Eastmoney。

US用原原生发行人分类和relation层、原两源join；未映射ticker仍留在诊断/raw列表。非名字别名、非静态受益名单。

环境：作者Linux / Python3.13.5，不是Mac3.14.6。上游HTTP、master、资格、US输入为合成边界，未执行真实资格/公告/行情/API请求。所有socket connect路径在fixture禁止。B2 main版本检查/资源限制/信号边界由测试隔离，交付源码的原>=3.14/资源限制不放宽。

依赖来源：AUTHOR_REFERENCE_INVENTORY.json列出关键原依赖及完整作者参考树清单的SHA（不宣称完整依赖闭包）；其来源为旧交付参考依赖清单，不是完整Mac候选、更不能部署。该参考provider未提供R9的_safe_eastmoney_hk_url时，fixture明确安装只容许原三个host的测试边界；现场必须确认实际provider/dispatch源。pypdf缺的空py.typed和LICENSE按既存manifest恢复并核SHA，没有修改解析器或验收门。原来源/磁盘/分类方法未用假实现替换。

适用结论：作者代码定向通过。独立Mac复验、活动service接线、真实API/UI/natural均未执行，不由41个合成测试代替。
