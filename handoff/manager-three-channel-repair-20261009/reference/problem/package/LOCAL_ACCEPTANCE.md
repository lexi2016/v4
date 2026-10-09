# Chat修复返回后的本地验收

仅在临时工作副本验收，不部署、不改现役服务或计划任务、不写真实业务state。

1. 核对源码base与文件清单。冻结候选ref为 ca01c4d0260fecf7aae3c89e96899f36901bf8f7；逐文件核对Chat返回完整after、patch、before/after SHA，解释所有额外路径。
2. 在临时副本运行Chat给出的三路定向测试，记录实际命令、退出码与输出。必须覆盖公告handoff/import、US daily触发/物化/消费、exact-date screen reader缺输入与有效输入分支。不得放宽US筛选阈值。
3. 16:01结果只以本包保存的历史receipt/projection作为已验历史证据；历史latest.json原件未打包，因此重放该历史输入为 CANNOT_CONFIRM。若在本机运行 tools/reproduce_screen_reader.py，它读取的是运行时当前latest.json，必须记录本次latest SHA、条目数、最新日期、目标日期键是否存在及异常，不能称为16:01历史重放。Chat修复回归使用独立临时合成fixture，明确标注为synthetic regression，不补造历史输入；不向真实authority root写入。
4. 隔离候选测试只能证明隔离代码。现役服务发布/重启、API/UI重载读回与自然时段验收需另行授权和证据。

本包writer只验证文件SHA、manifest、ZIP与loader只读失败；未复跑历史业务suite，未验收Chat未来代码。
