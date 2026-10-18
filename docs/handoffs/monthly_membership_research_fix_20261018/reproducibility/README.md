本目录保留本轮实际使用的机械构建、受控切换及单次运行脚本；与 local_only 执行副本逐字节相同。

所有命令从 V4 仓库根执行，依赖本机冻结基线、独立验收回执及相应 ROOT_*_PLAN / BUILD 文件；这些含运行状态的本机材料不以原始配置形式上传。脚本不会绕过部署保护条件，不能在其他机器上盲目执行。

顺序：build_manager_web_r2.py → build_releases_r2.py → 独立验收 PASS → activate_api.py → activate_scheduler.py → actual_run_r2.py submit / poll / read。存在提交意图时禁止重复 POST。

必要源码、测试与各运行版本差量另见上级目录及 source_deltas。原始行情、队列、认证、运行日志和 dist 不上传。
