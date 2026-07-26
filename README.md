# 私密视频授权播放系统

一个用于自托管私密视频分享的 Django 应用。管理员上传 MP4 或将视频放入服务器 `/video` 目录，系统通过 FFmpeg 转为受保护的 HLS，并用10位限时授权码控制在线观看。

> 浏览器播放视频时必须接收媒体数据，因此无法承诺“绝对不可下载或录屏”。本系统通过隔离原文件、HLS分片、短期签名、限流、水印和审计提高未授权获取与传播成本。

## 主要功能

- 每个视频可创建多个授权码
- 授权码支持安全随机生成或管理员手工设置
- 独立设置生效时间、失效时间和备注
- 删除授权码后立即撤销其活动播放会话
- 管理端上传 MP4，校验容器和视频轨道
- 自定义视频显示名称，不暴露无意义的物理文件名
- 每分钟扫描 `/video`，Celery与FFmpeg异步转码
- 动态重写HLS清单，媒体资源使用短期签名
- 记录授权时间、IP、观看时长、进度和播放事件
- 观看记录分页查询
- 自定义系统名称、管理员自助修改密码
- 支持正则表达式的IP访问黑名单
- 管理员操作与安全事件审计

## 技术栈

- Django 5 / Python 3.11+
- MySQL 8
- Redis / Celery
- FFmpeg / FFprobe
- Gunicorn / Nginx / systemd

生产部署为裸机服务，不依赖 Docker。本地测试默认使用SQLite。

## 快速开始

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py createsuperuser
.venv\Scripts\python manage.py runserver
```

打开：

- `http://127.0.0.1:8000/`：授权观看入口
- `http://127.0.0.1:8000/manage/`：管理控制台
- `http://127.0.0.1:8000/admin/`：Django系统管理

本地未设置 `DB_ENGINE=mysql` 时使用SQLite，仅用于开发和测试。

## 文档

- [系统架构](docs/ARCHITECTURE.md)
- [裸机部署手册](docs/DEPLOYMENT.md)
- [数据库初始化与维护](docs/DATABASE.md)
- [管理员操作手册](docs/OPERATIONS.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)
- [自动化代理约定](AGENTS.md)
- [变更记录](CHANGELOG.md)

## 生产初始化

1. 使用 `deploy/mysql/init.sql` 创建MySQL数据库与应用用户。
2. 复制并填写 `deploy/private-video.env.example`。
3. 安装依赖并执行Django迁移。
4. 安装 `deploy/` 下的systemd和Nginx配置。
5. 运行 `deploy/smoke_test.sh`。

完整步骤见 [部署手册](docs/DEPLOYMENT.md)。

## 测试

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test -v 2
```

GitHub Actions工作流会执行相同检查。工作流只使用SQLite测试，不会连接生产数据库。

## 仓库安全

提交前确认未包含：

- 生产服务器IP、域名和环境文件
- 数据库、Redis或管理员密码
- 授权码、Cookie、私钥和数据库转储
- 原始视频、HLS、日志和未脱敏截图

生产凭据应只保存在服务器的权限受限文件中。

## 许可证

本项目采用 [MIT License](LICENSE)。

## 作者

- WeChat：`8574157`
