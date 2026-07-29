# AGENTS.md

本文件定义自动化开发代理和人工贡献者在本仓库中的工作约定。规则适用于仓库根目录及全部子目录。

## 项目目标

本项目是一个裸机部署的私密视频授权播放与私密聊天系统。管理员上传或放置 MP4 视频，系统通过 FFmpeg 转码为受保护的 HLS；观看者凭10位限时授权码播放；管理员还可创建凭10位授权码进入的多人聊天室。

## 技术栈与运行边界

- Python 3.11+、Django 5
- MySQL 8，生产环境不得改用 SQLite
- Redis、Celery Worker、Celery Beat
- Django Channels、channels_redis、Daphne
- FFmpeg / FFprobe
- Gunicorn、Daphne、Nginx、systemd
- 生产部署不使用 Docker
- 原视频目录默认为 `/video`
- HLS目录默认为 `/var/lib/private-video/hls`

本地自动化测试默认使用 SQLite 内存数据库。不得把本地测试数据库当作生产初始化方案。

## 代码结构

- `private_video/`：Django项目配置、URL和Celery入口
- `videos/`：模型、表单、视图、任务、迁移和测试
- `chat/`：聊天室模型、授权、历史记录接口、WebSocket消费者、迁移和测试
- `templates/`：公开观看页、控制台和Django Admin覆盖模板
- `static/`：站点样式和已固定版本的前端依赖
- `deploy/`：裸机部署脚本、systemd、Nginx和数据库初始化材料
- `docs/`：架构、数据库、部署和操作文档

## 开发工作流

1. 修改前阅读相关模型、视图、模板、测试和迁移，不重复实现已有能力。
2. 模型发生变化时必须生成新的迁移；不得修改已经用于生产的历史迁移。
3. 所有管理端写操作必须：
   - 要求 staff 登录；
   - 使用 POST 和 CSRF；
   - 校验输入；
   - 写入 `AdminAuditLog`；
   - 在可能的情况下使用事务。
4. 文件操作必须将目标解析到配置目录内；禁止使用用户输入直接组成物理路径。
5. 上传必须先写临时文件，校验成功后再原子移动；失败时仅清理本次请求创建的精确文件。
6. 授权码明文只能在创建结果页显示一次，数据库只保存 HMAC 摘要和尾号。
7. 不得创建公开的原视频或HLS静态目录；媒体访问必须继续经过会话和签名校验。
8. 页面新增功能必须兼顾桌面端和窄屏布局。
9. 聊天消息必须先持久化到MySQL，再通过Redis广播；Redis不得作为唯一聊天记录。
10. WebSocket连接必须校验来源、访客令牌、聊天室状态、IP一致性和IP黑名单。
11. 聊天室备用昵称统一维护在 `chat/nicknames.py`；同一聊天室的参与者昵称必须唯一。

## 常用命令

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test -v 2
```

Linux生产检查：

```bash
/opt/private-video/.venv/bin/python manage.py check --deploy
/opt/private-video/deploy/smoke_test.sh
systemctl is-active private-video-web private-video-chat private-video-worker private-video-beat nginx
```

## 测试要求

- 修复缺陷时先补充能复现缺陷的测试。
- 新功能至少覆盖成功路径、权限限制和关键失败路径。
- 涉及授权时覆盖有效、未生效、过期、删除和停止共享状态。
- 涉及上传时覆盖扩展名、容器头、视频轨道、大小限制和路径安全。
- 涉及聊天时覆盖授权进入、聊天室隔离、最近50条、向上游标分页、实时广播、断线会话、IP黑名单和XSS。
- 提交前运行系统检查、全部测试和 `git diff --check`。

## 数据库与迁移

- MySQL字符集使用 `utf8mb4`。
- 初始化数据库参见 `deploy/mysql/init.sql` 和 `docs/DATABASE.md`。
- 数据表由 `python manage.py migrate` 创建；不要维护一份与Django迁移重复的表结构转储。
- 生产执行破坏性SQL、重置数据库或恢复备份前必须明确确认目标库并完成备份。

## 安全与仓库卫生

- 禁止提交真实IP、域名、密码、Redis URL、数据库转储、授权码、Cookie、私钥和生产环境文件。
- `/etc/private-video.env` 与 `/root/private-video-admin.txt` 只存在于服务器，不进入仓库。
- 日志、截图和测试夹具在提交前检查是否包含IP、用户名或授权码。
- 不降低 CSRF、会话 Cookie、访问限流、路径校验或签名校验。
- 聊天授权码和访客会话令牌明文不得入库或写入日志；普通聊天页面只显示脱敏IP。
- 不声称浏览器视频“绝对无法下载”；文档应准确描述为提高未授权获取成本。

## 部署约定

- 部署前备份数据库和环境配置。
- 先执行迁移与静态文件收集，再重启 Web、Chat、Worker 和 Beat，最后校验并重载 Nginx。
- 变更 systemd 文件后执行 `systemctl daemon-reload`。
- 部署完成必须运行冒烟测试和查看近期 warning/error 日志。
- 不得在未获授权时向 GitHub 推送、创建发布或公开仓库。

## 完成标准

任务只有在代码、迁移、测试、相关文档和部署验证均完成后才算完成。最终说明应列出行为变化、测试结果、迁移影响和仍需用户决定的事项。
