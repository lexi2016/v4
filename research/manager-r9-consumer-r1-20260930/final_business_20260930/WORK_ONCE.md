# Work 唯一接续入口

先读 `FINAL_REPAIR_PLAN_ZH.md`。不要再运行旧 runner、旧 cycle_snapshot.patch 或 R3B/API14套件。活动服务、调度、配置、资格数据均不由本命令改变。

在本目录执行一次：

```bash
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" tools/work_once.py \
  --base-app "/Users/lexi/Desktop/学习/agents调试/MANAGER_API_INTEGRATION_20260930/candidate/app" \
  --output "/Users/lexi/Desktop/学习/agents调试/MANAGER_FINAL_BUSINESS_20260930/run1"
```

输出必须是新目录。也接受已精确叠加原B1/US的API6726整体profile，不能混搭单个文件SHA。源码不匹配时仅生成 `ONE_INPUT_GAP_REPORT.json` 汇总所有差异，不修改输入，不要求重传全项目。若API副本尚无已上传RPC/源处理文件，本包可在新inactive副本种入明确固定的源码；`provided_frozen_entries`会记录，不能据此宣称已安装或已绑定。现有不同字节不覆盖。

成功输出 `ISOLATED_BUSINESS_TESTED_NOT_INSTALLED`。`app/`为唯一业务候选，`WORK_RECEIPT.json`记录profile、实际改动、时间、测试计数、未闭环状态；`new_tests.log`、`junit.xml`、`import_receipt.json`必须一起保留。输入API不写，输出源码测试后必须保持相同SHA。

风险定向独立审核只覆盖新增7文件、累计差异的一致性、同tick/截止/重试/原字段来源；重用原B1/US、API14与F0F2已验结果，不固定模型名称作为门。作者测试是Linux/Python3.13.5，不冒充Mac独立结果。

本机应用后仍缺的实物只按最终方案的四组清单一次合并回传；与已有GitHub字节相同仅回身份。R3A由原单写者继续，不能用本包旧资格reader覆盖其新候选；R3A后续与本业务候选合并时只审核真实发生的交互差异。

回退：本命令不碰活动服务，也不写输入API，因此放弃整个新输出候选即可。要验证补丁回放，在新临时目录放置 `before/app/`，`git apply runtime.patch` 后应逐字节等于 `after/app/`；反向应用只在该临时目录恢复前像并删除新增文件。绝不在活动release上反向覆盖。

后续真实验收按方案顺序执行原owner/原reader/API/UI，使用服务端实际时钟，不重标历史日期。没有独立安装/真实运行授权，不启动provider、不POST现场API、不启调度、不合并PR。PR9 Draft；Issue8 Open。
