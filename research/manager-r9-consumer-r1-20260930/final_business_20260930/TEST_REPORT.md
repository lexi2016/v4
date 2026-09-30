# 新增业务风险测试报告

本批新增27项：RPC/原计划15项，US原字段链12项。未运行旧API14、R3B10、B1/US33、F0–F2或旧snapshot B2套件；原支撑fixture函数沿用，不收集它们的旧test函数。

## 原始结果

- `logs/original_red.log/xml`：相同新增测试在本批未修前像运行，21 failed / 6 passed，exit 1。缺路由、同tick先后、原字段丢失等失败可复现，没有collection/import setup error。
- `logs/new_tests.log`、`logs/junit.xml`：交付的 `tools/work_once.py` 创建全新隔离app、写入精确后像、执行原27项，27 passed / 0 failures / 0 errors / 0 skipped，exit 0。
- `logs/WORK_RECEIPT.json`：本次作者实际命令、输入输出路径、起止时间、完整文件应用映射与结果。`logs/import_receipt.json`记录实际导入文件和SHA。
- `logs/PATCH_AND_PRESERVATION.json`：累计 runtime.patch 正向等于after全部字节，反向等于before并删除新增文件；API6726未变化pin保持，原 `_stage_evidence` 函数逐字节相同。

## 范围

真实执行本地原MaterialStore/ManagerResearchStore、原PDF与response校验、计划事务/保存/读回、ASGI router、RPC请求/响应序列化和服务端分发、原ResearchArchiveStore发布/receipt/manifest读回。测试中的HTTPConnection替换为进程内ASGI传输，socket连接全局拒绝；无外部API/8873/Futu调用。替代的是HTTP响应、master/资格/US行情、安装inventory和受控时钟；不是伪造真实供给。

场景包括：最后盘前同tick、第二批输入、重复input不写、采集失败保留成功正文、关闭采集、错误binding/跨源/body/full readers拒绝；采集后/排队后跨cutoff不建计划；生成过程跨cutoff保留真实已保存计划字节（允许原失败attempt记录）；手动公告POST沿已有服务器binding触发/无binding不启用。

US包含显式原时间/引用/ticker透传、缺失不由crawl补值、非法/未来值保留拒绝、礼来名称不推LLY、长期合同不升级研究观点、同源冲突/跨股票原件不借时钟、排名/Stage投影不变、原磁盘archive引用篡改拒绝、元数据不能覆写claim_type或验证状态。

作者环境Linux/Python3.13.5，参考依赖不是完整Mac已验app。本轮未执行新Mac独立审核、部署、普通API/UI或自然运行。已有Mac14/10等按原范围复用，不能并入本轮通过数。

开发初次搭建中发现作者参考树缺原包声明的 `pypdf/py.typed` 和 LICENSE，导致正文进入pending；已从原上传完整源码包恢复，原package_tree及license SHA校验通过，未修改验证器。另修正测试时避免全局伪改sys.version_info影响AnyIO；仅替换被测CLI的版本检查对象，生产代码不改。上述环境/fixture失败未计作业务通过证据。
