# 裸机部署手册

本文说明在一台 Linux 服务器上部署本项目。生产架构使用 MySQL 8、Redis、FFmpeg、Gunicorn、Nginx 和 systemd，不使用 Docker。

## 1. 前置要求

- 64位 Linux，建议至少2核CPU、2GB内存
- Python 3.11+
- MySQL 8
- Redis 6+
- FFmpeg与FFprobe
- Nginx、systemd
- 足够存放原视频和HLS文件的磁盘空间

以下路径可按环境调整：

- 应用：`/opt/private-video`
- 原视频：`/video`
- HLS：`/var/lib/private-video/hls`
- 环境配置：`/etc/private-video.env`

## 2. 创建系统用户与目录

```bash
useradd --system --home /opt/private-video --shell /usr/sbin/nologin privatevideo
install -d -o privatevideo -g privatevideo -m 0750 /opt/private-video
install -d -o privatevideo -g privatevideo -m 0750 /video
install -d -o privatevideo -g privatevideo -m 0750 /var/lib/private-video/hls
```

将代码复制到 `/opt/private-video`，不要复制 `.env`、数据库转储或开发虚拟环境。

## 3. 初始化 MySQL

复制 `deploy/mysql/init.sql`，替换其中占位密码后，以MySQL管理员执行。也可以根据实际主机来源调整授权用户的 host。

```bash
mysql -u root -p < deploy/mysql/init.sql
```

数据库脚本只创建数据库与最小应用用户。Django表结构由迁移创建。

## 4. 配置 Redis

为 Redis 设置强密码并限制为本机访问。建议为应用使用独立数据库编号，例如 `/4`：

```text
redis://:URL_ENCODED_PASSWORD@127.0.0.1:6379/4
```

密码中有特殊字符时必须进行 URL 编码。

## 5. Python环境

```bash
cd /opt/private-video
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

系统还必须能在 `PATH` 中找到 `ffmpeg` 和 `ffprobe`。

## 6. 应用环境变量

```bash
install -m 0600 deploy/private-video.env.example /etc/private-video.env
```

编辑 `/etc/private-video.env`，至少修改：

- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `DB_PASSWORD`
- `DB_HOST` / `DB_PORT`
- `REDIS_URL`
- HTTPS相关开关

不要把修改后的生产文件复制回仓库。

## 7. 初始化应用

```bash
set -a
source /etc/private-video.env
set +a

/opt/private-video/.venv/bin/python manage.py migrate
/opt/private-video/.venv/bin/python manage.py collectstatic --noinput
/opt/private-video/.venv/bin/python manage.py createsuperuser
/opt/private-video/.venv/bin/python manage.py check --deploy
```

也可以使用 `bootstrap_admin` 命令读取 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 环境变量创建初始管理员。

## 8. 安装服务

检查 `deploy/*.service` 中的路径与系统服务名称，然后执行：

```bash
install -m 0644 deploy/private-video-web.service /etc/systemd/system/
install -m 0644 deploy/private-video-worker.service /etc/systemd/system/
install -m 0644 deploy/private-video-beat.service /etc/systemd/system/
install -m 0644 deploy/nginx-private-video.conf /etc/nginx/conf.d/private-video.conf

systemctl daemon-reload
systemctl enable --now private-video-web private-video-worker private-video-beat nginx
nginx -t
systemctl reload nginx
```

如使用非 Debian 系发行版，Nginx运行用户和配置目录可能不同。

## 9. HTTPS

生产环境应配置域名和可信TLS证书，并设置：

```text
COOKIE_SECURE=1
SECURE_SSL_REDIRECT=1
CSRF_TRUSTED_ORIGINS=https://video.example.com
```

如果TLS在上游代理终止，确认代理正确传递 `X-Forwarded-Proto`。

## 10. 部署更新

1. 备份MySQL与 `/etc/private-video.env`。
2. 替换应用代码，保留 `/video` 和HLS目录。
3. 安装新依赖。
4. 执行 `manage.py migrate`。
5. 执行 `collectstatic --noinput`。
6. 重启 Web、Worker、Beat。
7. 执行 `nginx -t` 后重载Nginx。
8. 运行 `deploy/smoke_test.sh`。

## 11. 回滚

- 回滚前先阅读新迁移是否可逆。
- 恢复旧代码后执行目标迁移，例如 `manage.py migrate videos 0003`。
- 恢复数据库前停止Web和任务服务。
- 不要删除 `/video` 或HLS目录作为普通回滚手段。
