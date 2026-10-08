# 港股预选池只读迁移候选

本批复用冻结 V4 reader 和 build，保留 Top100 全部行及原始次序。它读取既有池，不调用行情 SDK、不重训或加载模型权重、不生成真实新池、不切换生产。

## 输入合同

目标日 target_date、价格信号日 signal_date、资格来源日 eligibility_source_date 必须分别显式提供。价格信号日按香港证券交易日历取上一交易日，不能按 A 股日历。Connect 开闭市单独报告。资格日期可与信号日期不同，甚至为目标日，但资格采集时间必须不晚于池采集与研究截止时间。

输入根、每个文件 SHA256 和带时区 research_cutoff 必须绑定。非默认独立资格根、名称补充参数当前原 reader 不支持，明确拒绝，不能默默忽略。

## 验证

原 reader 校验数据与固定模型来源身份；外层要求 receipt 和 verification 均 READY、temporal_cutoff_safe 为 true、100 行、每个代码属于已核主表、概率有限且在 [0,1]、三个日期身份正确。

主表 captured_at <= 池 captured_at <= receipt finished_at <= research_cutoff。原始 manifest 不要求新增 role 字段；role 校验沿用 receipt 和原 reader 路径合同。

通过子进程运行闭包源码和 Python 读写/网络限制，输入前后重核；这不是已证明的 OS 沙箱隔离。所有产物 research_only，formal_eligibility_verified/natural_verified 为 false。固定权重 SHA 字段不等于重新核验权重文件。

## 当前证据

- d39a3c64 的原始 10 项测试已在 Mac 实际运行：10 ERROR，缺模块，业务断言未执行
- 本批增加采集时间、目标日资格、概率、temporal=false、全100行保真用例，待同一 Mac 任务实际执行
- 此前 A 预选 294f6f3 的 17 项与全套145项通过不覆盖本候选
- 尚无真实新池生成、真实行情接入、页面或自然调度验收
