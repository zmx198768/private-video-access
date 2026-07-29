# 裸机部署手册

本文说明如何在Linux服务器上部署当前版本。生产架构使用MySQL 8、Redis、FFmpeg、Gunicorn、Daphne、Nginx和systemd，不使用Docker。

## 1. 部署前确认

### 软件与资源

- 64位Linux，建议至少2核CPU、2GB内存
- Python 3.11+
- MySQL 8
- Redis 6+
- FFmpeg与FFprobe
- Nginx、systemd、OpenSSL
- 足够容纳原视频、HLS和数据库备份的磁盘空间

默认路径：

| 用途 | 路径 |
| --- | --- |
| 应用代码 | `/opt/private-video` |
| 原视频 | `/video` |
| HLS | `/var/lib/private-video/hls` |
| 应用环境 | `/etc/private-video.env` |
| 初始管理员凭据 | `/root/private-video-admin.txt` |

生产服务器上的环境文件、管理员密码和数据库转储不得复制回Git仓库。

## 2. 创建运行用户和目录

```bash
useradd --system --home /opt/private-video --shell /usr/sbin/nologin privatevideo
install -d -o privatevideo -g privatevideo -m 0750 /opt/private-video
install -d -o privatevideo -g privatevideo -m 0750 /video
install -d -o privatevideo -g privatevideo -m 0750 /var/lib/private-video/hls
```

将代码放入 `/opt/private-video`。不要复制本地 `.venv`、SQLite数据库、日志或测试媒体。

## 3. 安装Python依赖

```bash
cd /opt/private-video
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
ffmpeg -version
ffprobe -version
```

## 4. 初始化MySQL和环境配置

二选一即可。

### 方式A：辅助脚本

脚本会要求输入MySQL管理员密码和Redis密码，自动生成应用数据库密码、Django密钥及初始管理员密码：

```bash
cd /opt/private-video
chmod 700 deploy/configure_secrets.sh

APP_HOST=video.example.com \
APP_ORIGIN=https://video.example.com \
MYSQL_HOST=127.0.0.1 \
MYSQL_PORT=3306 \
REDIS_HOST=127.0.0.1 \
REDIS_PORT=6379 \
REDIS_DB=4 \
CHAT_REDIS_DB=5 \
./deploy/configure_secrets.sh
```

生成：

- `/etc/private-video.env`
- `/root/private-video-admin.txt`
- MySQL数据库 `private_video` 及应用用户

脚本默认将Redis数据库4用于缓存和Celery，将数据库5用于聊天Channel Layer。两个编号可以调整，但不要让其他应用共用。

### 方式B：手工初始化

1. 编辑 `deploy/mysql/init.sql`，替换占位密码。
2. 以MySQL管理员执行：

```bash
mysql -u root -p < deploy/mysql/init.sql
```

3. 复制环境样例并设置权限：

```bash
install -m 0600 deploy/private-video.env.example /etc/private-video.env
```

4. 编辑全部占位值，特别是Django密钥、允许的域名、CSRF来源、MySQL密码和Redis URL。

初始化SQL只创建数据库和应用用户；Django表结构必须通过迁移创建。

## 5. 关键环境变量

| 变量 | 说明 |
| --- | --- |
| `DJANGO_SECRET_KEY` | 长随机密钥，生产环境必须更换 |
| `DJANGO_ALLOWED_HOSTS` | 允许访问的域名或主机，逗号分隔 |
| `CSRF_TRUSTED_ORIGINS` | 带协议的可信来源，例如 `https://video.example.com` |
| `DB_*` | MySQL 8连接参数 |
| `REDIS_URL` | Django缓存、Celery Broker和结果后端 |
| `CHAT_REDIS_URL` | Channels聊天广播，建议使用独立Redis数据库编号 |
| `USE_REDIS_CACHE` | 生产设置为 `1` |
| `USE_REDIS_CHANNEL_LAYER` | 多进程生产聊天必须设置为 `1` |
| `VIDEO_SOURCE_DIR` | 原视频目录，默认 `/video` |
| `VIDEO_HLS_DIR` | HLS目录，默认 `/var/lib/private-video/hls` |
| `MAX_VIDEO_UPLOAD_BYTES` | Web上传大小上限，默认2GB |
| `TRUST_PROXY_HEADERS` | 仅在请求只能经过可信Nginx时设置为 `1` |
| `COOKIE_SECURE` | HTTPS生产环境设置为 `1` |
| `SECURE_SSL_REDIRECT` | HTTPS生产环境设置为 `1` |
| `CHAT_MESSAGE_MAX_LENGTH` | 单条消息最大长度，默认2000 |
| `CHAT_SEND_RATE_PER_MINUTE` | 每个参与者每分钟发送上限，默认30 |
| `CHAT_ENTRY_RATE_PER_MINUTE` | 每个IP每分钟进入聊天室上限，默认10 |

完整样例见 `deploy/private-video.env.example`；默认值以 `private_video/settings.py` 为准。

## 6. 执行初始化

```bash
set -a
source /etc/private-video.env
set +a

cd /opt/private-video
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py check --deploy
```

若使用辅助脚本生成了 `/root/private-video-admin.txt`，可执行：

```bash
set -a
source /root/private-video-admin.txt
set +a
/opt/private-video/.venv/bin/python manage.py bootstrap_admin
unset ADMIN_USERNAME ADMIN_PASSWORD
```

## 7. 安装systemd和Nginx

```bash
install -m 0644 deploy/private-video-web.service /etc/systemd/system/
install -m 0644 deploy/private-video-chat.service /etc/systemd/system/
install -m 0644 deploy/private-video-worker.service /etc/systemd/system/
install -m 0644 deploy/private-video-beat.service /etc/systemd/system/
install -m 0644 deploy/nginx-private-video.conf /etc/nginx/conf.d/private-video.conf

systemctl daemon-reload
systemctl enable --now private-video-web private-video-chat private-video-worker private-video-beat
nginx -t
systemctl enable --now nginx
systemctl reload nginx
```

服务监听：

- Gunicorn：`127.0.0.1:8008`
- Daphne：`127.0.0.1:8009`

两者都不得直接暴露到公网。不同发行版的Nginx用户和配置目录可能不同；必须确保Nginx可以读取静态目录和HLS目录。

也可在确认 `/etc/private-video.env` 与 `/root/private-video-admin.txt` 已正确生成后运行：

```bash
chmod 700 deploy/finish_install.sh
./deploy/finish_install.sh
```

`finish_install.sh --reset-empty-database` 会删除并重建目标数据库，只允许用于已经确认无业务数据的新安装。不要在升级、恢复或生产存量数据库上使用。

## 8. HTTPS与代理

生产环境应使用可信TLS证书，并设置：

```text
CSRF_TRUSTED_ORIGINS=https://video.example.com
COOKIE_SECURE=1
SECURE_SSL_REDIRECT=1
TRUST_PROXY_HEADERS=1
```

如果TLS在上游代理终止，代理必须正确写入 `X-Forwarded-Proto`。启用 `TRUST_PROXY_HEADERS` 后，应用会信任Nginx设置的 `X-Real-IP`；因此必须阻止客户端绕过Nginx访问Gunicorn和Daphne。

修改Nginx配置后：

```bash
nginx -t
systemctl reload nginx
```

## 9. 首次验证

```bash
systemctl is-active private-video-web private-video-chat private-video-worker private-video-beat nginx
/opt/private-video/.venv/bin/python manage.py check --deploy
/opt/private-video/deploy/smoke_test.sh
journalctl -u private-video-web -u private-video-chat \
  -u private-video-worker -u private-video-beat --since=-10m -p warning --no-pager
```

冒烟测试会：

- 检查健康接口、管理端、聊天室管理和统一入口
- 临时生成测试视频并等待扫描转码
- 创建临时授权码，验证观看页、HLS清单和分片
- 完成后删除本次创建的测试数据和文件

运行前确认 `/root/private-video-admin.txt` 中的管理员账号仍有效，并确认服务器有可用FFmpeg编码器。

## 10. 更新发布

1. 确认目标服务器和数据库名称。
2. 备份MySQL、`/etc/private-video.env` 和 `/root/private-video-admin.txt`。
3. 更新代码并安装新增依赖。
4. 查看迁移计划并执行迁移。
5. 收集静态文件。
6. 若systemd文件有变化，执行 `systemctl daemon-reload`。
7. 重启Web、Chat、Worker、Beat。
8. 验证并重载Nginx。
9. 运行冒烟测试并检查近期日志。

```bash
cd /opt/private-video
set -a
source /etc/private-video.env
set +a

.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate --plan
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
systemctl restart private-video-web private-video-chat private-video-worker private-video-beat
nginx -t
systemctl reload nginx
deploy/smoke_test.sh
```

## 11. 回滚

- 回滚前先备份当前数据库和配置。
- 确认新迁移是否可逆，不要直接修改迁移历史。
- 需要恢复数据库时先停止Web、Chat、Worker和Beat。
- 恢复与备份迁移状态匹配的代码，再导入数据库并执行 `manage.py migrate`。
- `/video` 和HLS目录不应作为普通回滚手段删除。
- 回滚后重启4个应用服务，验证Nginx并运行冒烟测试。

数据库备份和恢复命令见 [数据库手册](DATABASE.md)。

## 12. 常见故障

### 聊天室一直重连

检查：

```bash
systemctl status private-video-chat
journalctl -u private-video-chat --since=-30m
redis-cli -u "$CHAT_REDIS_URL" ping
```

确认 `USE_REDIS_CHANNEL_LAYER=1`、Nginx `/ws/chat/` 代理存在，并且访客Cookie路径为 `/`。

### 授权提交出现CSRF失败

确认访问域名与 `CSRF_TRUSTED_ORIGINS` 一致、代理传递正确协议、浏览器可接收CSRF Cookie，并检查服务器时间。

### 视频长时间未转码

检查Worker、Beat、FFmpeg、目录权限和磁盘空间：

```bash
systemctl status private-video-worker private-video-beat
journalctl -u private-video-worker --since=-1h
df -h /video /var/lib/private-video/hls
```
