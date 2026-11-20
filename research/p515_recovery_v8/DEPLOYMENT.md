# P5.15 V8 部署与外部独立见证

本轮为隔离验证。Mac 工程台在单进程权威服务和独立多进程 Unix 客户端之间实测。宿主当前没有 Docker、Podman、OrbStack、Colima、Apple container CLI 或 Docker socket，真实双容器及共享持久卷保持 BLOCKED。

## 信任边界与正式部署前提

1. 运维以独立服务 UID 固定权威服务目录、Run A 身份、信任根、Unix socket 和数据库卷。客户端只读固定公开连接配置。数据库目录由权威服务专用，磁盘和端点访问由宿主调度、UID 和挂载权限约束。多主机需先独立验收带身份认证的传输与服务发现，当前本地 Unix 部署没有多主机生产传输。
2. 密钥审批方在本项目之外生成及保护真实签名私钥。服务端只固定由部署方验证的 Ed25519 公钥、信任域、签发者和主体。缩小授权到单元、预算与 PRELAUNCH。真实 AUTH-01 和 AUTH-02 分别由主控书面裁定，测试授权无正式效力。正式域的权限验证、部署防回滚锚和真实计划封存应独立验收后才申请准入。本批分支中的正式 FIT 硬阻断没有命令行解除选项。
3. 卷只能从核原字节的 Run A 档案显式初始化。保留旧存储身份；迁移需要隔离旧实例、检查最近已消费事务、外部固定新旧撤销摘要并重新绑定客户端。单实例 SQLite WAL 与外置同级持久围栏是本候选的恢复边界。围栏设备与 inode 在引导时固定，DB 的同 inode 回滚也会阻断。正式历史恢复和高可用切换须把围栏放在独立非回滚保留域，避免 DB 与围栏一起回退。禁止以数据库备份直接恢复消费资格。数据库副本交客户端只能留作证据。
4. 端点不可用和返回未知分别记入审计，客户端按已知事务号或授权号查询权威服务。站点级回滚、服务身份迁移和故障后预算调整交主控裁定。

## 可执行双容器验证

以新 Linux 隔离宿主的 Docker Engine、可写持久卷驱动、Python 3 客户端和 Bash 为前提。先固定镜像 digest 并核取镜像来源。命令从 worktree 根执行。

```bash
bash research/p515_recovery_v8/run_two_container_witness.sh /absolute/isolated/evidence 'python@sha256:<approved immutable digest>'
```

该命令建立一个权威容器以及两个独立 worker 容器。三者使用同一命名卷。只有权威容器挂载为 RW。网络均关闭，RPC 仅经过卷中的 Unix socket。两个 worker 等同一个文件屏障再向权威抢同一合成授权，随后都各自尝试直接 START 和 COMMIT。必须分别记录 container ID、host ID、volume 身份、mount RW、authority ID、数据库及 WAL SHA、授权消费和事务事件、两边 stdout/stderr。脚本要求只有一个消费者和一个提交，直接远端修改均拒绝，真实执行零。运行日志保存在指定证据目录，脚本仅清理该次自建容器与卷。总控在独立回读实际证据后方可裁定跨容器项。
