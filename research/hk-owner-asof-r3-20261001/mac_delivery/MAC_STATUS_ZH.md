# HK R3 Mac交付状态｜2026-10-02

交付包已收到并验证：1054665字节，95成员，SHA256 fb75e5188b424d6c2a74e68a388b270008349c029c179fd89688f25f6abfe6c7。94个manifest文件hash和36个前后像通过。原Git bundle含cfb7fad359a639f66097db78d597d92ab265c367，直接父提交3ed9e89a1de1616d89ddbe166484227b5fcd42fa；91个候选源码/证据文件与Git tree字节一致。candidate tree=3ef606cf597ea1653889fad591bd9e7cf937a538。连接器无法保留原commit作者/时间，远端Mac交付为派生提交，保留完整原bundle和候选树身份，不能称原cf commit已原样push。

8个canonical/10个活动前像全部匹配；仅非活动隔离副本应用补丁并验证反向恢复字节。修正测试载体误用Stage缓存publisher后，以actual R9 publisher和actual shared reader完成独立验收。活动服务源码、数据及配置均未修改。

独立Reviewer结果FAIL：canonical19/19断言通过，但清理PermissionError使进程exit1；actual R9 12pass/7fail，3项存储合同错误、4项owner夹具错误。Stage独立三项正反例通过，不能覆盖R9写入失败。完整receipt、加载模块路径/SHA和日志在review/；初始错误载体诊断日志亦保留并标明非最终。

状态：DELIVERED候选、REVIEWED=FAIL、TESTED=FAIL；ISOLATED_ASSEMBLY完成；INTEGRATED/DEPLOYED=false；R3 API/UI/NATURAL均未验收。现役API只读诊断确认9/30 A205/HK0，与未部署R3分别记录。A业务冻结，未执行selection/provider或写市场数据。

后续由原Chat修复真实store合同和owner夹具，以及同一原owner自然入口的HK-only行为。历史9/29主档和收盘价格缺口需真实源恢复，不能修改日期假装完成。字段边界保持production_allowed=false、buy_gate_updated=false、orders_sent=false。修复通过后才进入Mac下一轮独立集成/API/UI验收。

官方日历来源：https://www.hkex.com.hk/-/media/HKEX-Market/Mutual-Market/Stock-Connect/Reference-Materials/Trading-Hour,-Trading-and-Settlement-Calendar/2026-Calendar_pdf_e.pdf
