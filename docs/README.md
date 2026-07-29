# 文档导航

本文档目录以当前 `main` 分支代码为准，面向部署维护人员、系统管理员和开发贡献者。

## 按使用场景选择

| 场景 | 文档 | 内容 |
| --- | --- | --- |
| 了解系统组成 | [系统架构](ARCHITECTURE.md) | 请求链路、视频处理、聊天实时链路、数据与安全边界 |
| 首次安装或升级 | [裸机部署手册](DEPLOYMENT.md) | MySQL、Redis、FFmpeg、systemd、Nginx、HTTPS、升级和回滚 |
| 初始化与维护数据 | [数据库手册](DATABASE.md) | 初始化SQL、Django迁移、备份、恢复和主要数据表 |
| 使用管理后台 | [管理员操作手册](OPERATIONS.md) | 菜单、视频、授权码、聊天室、系统设置和排障 |
| 查看昵称来源 | [聊天室备用昵称库](NICKNAME_LIBRARY.md) | 22组备用昵称及维护规则 |
| 参与开发 | [贡献指南](../CONTRIBUTING.md) | 本地环境、测试和提交要求 |
| 处理安全问题 | [安全策略](../SECURITY.md) | 漏洞报告、敏感数据和部署安全基线 |
| 自动化开发 | [代理约定](../AGENTS.md) | 仓库级开发、测试和部署规则 |
| 查看版本变化 | [变更记录](../CHANGELOG.md) | 尚未发布的功能、修复与安全变化 |

## 文档与代码的事实来源

- URL入口：`private_video/urls.py`、`videos/urls.py`、`chat/urls.py`
- WebSocket路由：`chat/routing.py`
- 数据结构：`videos/migrations/`、`chat/migrations/`
- 环境变量默认值：`private_video/settings.py`
- 环境变量样例：`deploy/private-video.env.example`
- 服务定义：`deploy/*.service`
- Nginx代理与内部媒体路径：`deploy/nginx-private-video.conf`
- 数据库初始化：`deploy/mysql/init.sql`
- 安装及验证脚本：`deploy/configure_secrets.sh`、`deploy/finish_install.sh`、`deploy/smoke_test.sh`

若文档与代码冲突，应先确认当前部署版本和迁移状态，再修正文档或代码，不要直接对生产数据库做推测性修改。

## 生产环境重要约束

- 不使用 Docker；生产数据库必须为 MySQL 8。
- 原视频默认位于 `/video`，HLS默认位于 `/var/lib/private-video/hls`。
- `/etc/private-video.env` 和 `/root/private-video-admin.txt` 只保存在服务器。
- 原视频和HLS目录不得作为公开静态目录。
- 发布前必须备份数据库和环境配置，发布后必须运行冒烟测试并检查服务日志。
