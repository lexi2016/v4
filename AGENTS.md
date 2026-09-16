# V4 项目工作边界

先读README、docs/project/SOURCE_LINEAGE.json和本次明确工单。新分支/隔离worktree修改；禁止直接在main或正式release写入。保持Vibe8910，不重启8872。保持A/HK固定池、Stage8 HK-only、模型、评分、BUY和订单边界；不训练、不用当前网络资料补历史时点，不创建第二producer。

数据和凭证不进Git。只读缺源返回准确reason，不造quality_score/READY。提交前运行本任务红绿用例、受影响旧回归、源身份检查；前端更改必须原生typecheck/test/build，函数回归不能冒充浏览器验收。测试失败分源码/缺依赖/缺私有输入记录，不删除或宽松跳过造绿。

本次候选不是Mac现役。保留新的runner，未知SHA先看差异；禁止整树覆盖和自动部署。不得照旧docs/superpowers历史文字执行已撤销的迁移/退役任务。
