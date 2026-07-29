# 私密视频与聊天授权系统

一个面向自托管场景的 Django 应用：管理员上传或放置 MP4 视频，系统将视频转为受保护的 HLS；访问者在统一入口输入10位授权码后，系统自动识别并进入对应的视频或私密聊天室。

> 浏览器播放时必须接收媒体数据，因此任何Web方案都无法承诺“绝对不可下载或录屏”。本项目通过原文件隔离、HLS分片、短期签名、会话校验、限流和审计提高未授权获取与传播成本。

## 当前功能

### 私密视频

- 管理端上传MP4，校验扩展名、容器头、视频轨道、大小和路径安全
- 每分钟扫描 `/video`，文件稳定后由Celery和FFmpeg异步转码
- 自定义视频显示名称，并展示上传或发现时间
- 每个视频可生成多个10位授权码，支持随机生成、手工设置、生效时间、失效时间和备注
- 完整授权码仅在创建结果页显示一次；数据库只保存HMAC摘要和尾号
- 删除授权码或停止共享时立即撤销相关活动会话
- 动态重写HLS清单，分片URL使用短期签名并经Nginx内部路径发送
- 记录IP、授权时间、观看时长、最远进度和播放事件，管理端分页查看

### 私密聊天

- 管理员可创建不限数量的聊天室，并随机生成或手工设置10位授权码
- 视频与聊天室授权码全局唯一，由统一入口自动识别访问类型
- 多人WebSocket实时聊天；断线自动重连、遗漏消息补拉并支持HTTP轮询降级
- 消息先持久化到MySQL，再通过Redis Channel Layer广播
- 默认加载最近50条消息，向上滚动每次加载更早50条
- 每位参与者获得聊天室内唯一的小说人物昵称、随机头像和脱敏IP标识
- 内置22组中文小说人物备用昵称
- 参与者可主动退出聊天室，退出后当前会话立即失效
- 管理端分页查看参与记录，以及按聊天室查看完整聊天记录

### 管理与安全

- 管理端一级菜单：私密视频、私密聊天、系统设置、系统管理
- 设置全局系统名称、IP黑名单和当前管理员密码
- IP黑名单支持完整IP、`*`范围规则，并兼容原有正则表达式
- 公开授权入口、视频观看页和聊天室均不显示管理员菜单
- 管理员操作、安全事件和授权失败均保留审计记录
- CSRF保护、HttpOnly会话Cookie、访问限流、WebSocket来源与IP一致性校验

## 技术架构

- Python 3.11+、Django 5
- MySQL 8
- Redis、Celery Worker、Celery Beat
- Django Channels、channels_redis、Daphne
- FFmpeg、FFprobe
- Gunicorn、Nginx、systemd

生产环境采用裸机部署，不使用 Docker。本地开发和自动化测试默认使用SQLite。

## 本地开发

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py createsuperuser
.venv\Scripts\python manage.py runserver
```

常用入口：

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:8000/` | 视频与聊天室统一授权入口 |
| `http://127.0.0.1:8000/manage/` | 私密视频控制台 |
| `http://127.0.0.1:8000/chat/manage/` | 聊天室管理 |
| `http://127.0.0.1:8000/manage/settings/` | 系统设置 |
| `http://127.0.0.1:8000/admin/` | Django系统管理 |

本地未设置 `DB_ENGINE=mysql` 时使用SQLite；SQLite不能作为生产初始化方案。

## 生产部署

生产初始化需要：

1. 准备MySQL 8、Redis、FFmpeg、Nginx和Python 3.11+。
2. 使用 `deploy/mysql/init.sql` 或 `deploy/configure_secrets.sh` 初始化应用数据库和环境配置。
3. 安装依赖，执行Django迁移和静态文件收集。
4. 安装4个systemd服务及Nginx配置。
5. 配置HTTPS后运行 `deploy/smoke_test.sh`。

完整的新装、更新、回滚与排障步骤见 [裸机部署手册](docs/DEPLOYMENT.md)。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `private_video/` | Django配置、URL、WSGI/ASGI和Celery入口 |
| `videos/` | 视频、授权、观看记录、扫描转码、系统设置和审计 |
| `chat/` | 聊天室、参与者、消息、HTTP接口和WebSocket消费者 |
| `templates/`、`static/` | 公开访问页、管理界面、样式和前端脚本 |
| `deploy/` | MySQL初始化、环境样例、systemd、Nginx和冒烟测试 |
| `docs/` | 架构、部署、数据库和操作文档 |

## 文档

从 [文档导航](docs/README.md) 开始，或直接查看：

- [系统架构](docs/ARCHITECTURE.md)
- [裸机部署手册](docs/DEPLOYMENT.md)
- [数据库初始化与维护](docs/DATABASE.md)
- [管理员操作手册](docs/OPERATIONS.md)
- [安全策略](SECURITY.md)
- [变更记录](CHANGELOG.md)

## 验证

```powershell
.venv\Scripts\python manage.py check
.venv\Scripts\python manage.py makemigrations --check --dry-run
.venv\Scripts\python manage.py test -v 2
git diff --check
```

GitHub Actions使用Python 3.11和SQLite执行Django检查、迁移漂移检查及全部测试，不连接生产MySQL或Redis。

## 仓库安全

提交前必须确认仓库中没有生产IP或域名、数据库和Redis密码、生产环境文件、授权码、Cookie、私钥、数据库转储、原视频、HLS、日志或未脱敏截图。

## 作者与许可

- WeChat：`8574157`
- License：[MIT](LICENSE)
