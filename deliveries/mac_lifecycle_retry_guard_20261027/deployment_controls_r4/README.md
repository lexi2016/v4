# Mac lifecycle deployment controls · R4

状态：待自然空闲部署。Root 在唯一 PTY8456 持原 Main control owner 等自然 idle；本包是该时点的源码交付快照，不证明服务已经切换或自然日更完成。

controller、probe、对应7份测试、ROOT_EXECUTE及最小证据均逐字节复制当前已审版本。R4独审PASS；10个新用例及真实只读lazy-loader/四目标checkpoint证据复用。本次仅整理复制，没有执行controller、pytest、probe、锁、服务、CAS、Git提交或推送。

执行仍使用原research capsule与Root的真实回执/PLAN/CASE；不要从本目录独立执行。DEPENDENCIES只保存必要hash/pointer，未复制PLAN、完整config、plist、行情、secrets或旧失败快照树。Root当前运行capsule及六个既有untracked依赖副本均未修改。

ALLOWLIST给出source→Git路径、SHA256与Git blob SHA1；只有列出的payload文件属于本次同步范围。清单自身因hash循环不内嵌自身摘要，其SHA256/blob由交接另给。Root按原分支CAS同步，不覆盖其他改动。
