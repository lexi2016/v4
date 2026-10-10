# M12验收与回滚

本包未运行测试/媒体/部署。状态统一为：代码接入、真实数据通过、页面可用、自动接续、完整验收。五项分别登记；工程测试单列证据，不替代真实数据、页面或自然自动接续。

## 原回归与失败矩阵

在完整隔离原闭包和既有Mac依赖中保留：
- tests/test_bilibili_fupan.py：日期/上传信息绑定、flat shortlist不能代full metadata、工具缺失、有阻断不当有效空
- tests/test_bilibili_capture.py：日期未锁不调用工具，locked capture/音频/ASR仍保留review-required
- tests/test_bilibili_stockdict.py：本地精确名称、不模糊改写、缺ASR不读取无关面板
- tests/test_video_ocr_alignment.py：原角色/news/板块/TDX语义、缺spotcheck保持CANNOT_CONFIRM、缺ASR先退出
- tests/test_video_gap_audit.py：原字段/矩阵、模型不改、缺ASR不读review

以上为真实存在测试，未在本包运行。Review Core生产测试需在完整原闭包定位；不能只跑旧临时fixture路径就宣称真实Review Core通过。新增V5 test_video_fupan_daily.py必须覆盖：真实route/fixture不混、节点失败与重启、SHA漂移、并发单写、媒体零重复下载、ASR不重复、失败ASR可按原规则新run、GET零写、旧成功不丢、晚到/错视频/错日拒绝。

## Mac逐步业务证据

1. 核活动Review Core唯一producer、source/config/tool摘要、数据根与原节点索引；先读取已有节点和真实成功缓存，不批量重下视频。只交run/状态/SHA索引，无需外传媒体正文。
2. 对同一真实BV/目标日核discover→capture→ASR→session→字典→对齐→gap→发布/读回，真实节点未完成明确列缺。只读ALREADY_MATERIALIZED_READ_ONLY与新生产分开。
3. 从实际失败节点恢复，记录media/ASR execution_count、缓存SHA和前成功SHA不变；未批准/未支持恢复则原拒绝。另一输入新run，不覆旧目录。
4. 独立consumer读同manifest/receipt/SHA，M05/M09使用同引用；原独立事实摘要不变。ASR/OCR缺口、未spotcheck和空结果在API/页面都可见。
5. 真实V5浏览器进入原时间线/复盘FUPAN，切日、刷新、返回、看各节点、重复动作/取消或中断读取；页面读取不触发任务。记录URL、截图、代码版本与run。后台真正取消若合同未支持不能假装完成。
6. 下一真实适用触发验自然接续；无新视频是有证有效空，访问阻断是阻断。不要为周末或无视频造业务结果，也不强加日任务。当前固定全套及依赖构建由集成者另跑，不能用旧225项或历史调度摘要替代。

## 隔离回滚

单一发布者保存M12旧/新版本与generation，独立worker先核身份再CAS切模块引用。失败仅回M12旧指针/进程；保留失败节点、新run和缓存，绝不删除前成功或切V4源。回滚后M09原独立模型、M04归档、M05已提交来源及其他API版本不变。

反馈同一Chat：固定commit/patch SHA、活动owner摘要、BV/目标日/节点、输入/输出SHA、精确命令和错误、网络/工具/审核阻断类别、缓存计数、API/UI证据和回滚结果。所有没跑步骤NOT_RUN；不虚构媒体、出处或时点。
