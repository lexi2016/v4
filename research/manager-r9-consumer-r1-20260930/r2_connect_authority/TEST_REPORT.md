# R2 作者验证（不是独立Mac验收）

运行环境：Linux，CPython 3.13.5。声明范围是包内3个测试文件中的27个测试实例，不是全V4工程。

- 原R1消费端上，新绑定测试：7 failed / 9 passed。失败验证了未转发显式owner参数、未拦截部分/非法绑定及未保留结构化diagnostic。
- 最小1文件改动后：16 passed。
- 工具测试最初在fixture处报告9 setup errors（工具尚未交付），原始日志保留；将存在性检查移入测试体后为9 failed，不把setup error当作产品行为失败。
- 工具完成后，组合25 passed。
- 增加两项真实CLI子进程测试后，完整27 passed / 0 skipped。使用的authority数据均由原owner纯构造函数生成并显式标为SYNTHETIC，没有网络或生产写入。
- 用最终提供的`tools/run_offline_tests.py`再次构建临时read-side app并执行27项，stdout/stderr/JUnit/命令时间和SHA保留在evidence/final_declared_tests/。
- runtime.patch正反回放及辅助tools/tests patch回放，由verify_delivery.py核对完整后像/前像；包内归档身份另验。

测试覆盖：根缺失、成对root/SHA传递、不注入clock/as_of、相同输入identity稳定、缺一参数/非法SHA/相对路径/符号链接拒绝、原diagnostic保留、原owner四件套成功只读、旧日期/坏SHA/坏manifest/缺receipt/不满足数量/普通master拒绝、过cutoff拒绝、双根冲突不自动选、未选择根不fallback、证据目录不写入app或data，以及CLI无真实API/UI/启用声明。

本机R1通过范围按原独立收据复用，不把47再次加到27组成“74全绿”。原回归132/6双方同样失败，不删除6个失败，也不把作者此前混合环境的14失败当作这次Mac回归结果。
本次没有在完整实际r9 app运行新R2，故完整r9新回归和独立Mac验收仍NOT_EXECUTED。原6个失败ID见evidence/input_feedback/receipts/independent_review_receipt.json，原字节保留。
