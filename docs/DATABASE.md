# 数据库初始化与维护

## 1. 基本约定

- 生产数据库：MySQL 8
- 字符集：`utf8mb4`
- 排序规则：`utf8mb4_0900_ai_ci`
- 本地自动化测试：SQLite内存数据库
- 表结构事实来源：Django迁移

`deploy/mysql/init.sql` 只负责创建 `private_video` 数据库和最小权限应用用户，不重复维护业务表结构。

## 2. 新数据库初始化

编辑初始化SQL中的占位密码，然后以MySQL管理员执行：

```bash
mysql -u root -p < deploy/mysql/init.sql
```

配置 `/etc/private-video.env` 后执行：

```bash
set -a
source /etc/private-video.env
set +a

cd /opt/private-video
.venv/bin/python manage.py migrate --plan
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
```

不要手工复制Django模型生成的 `CREATE TABLE`，否则容易与迁移历史漂移。

## 3. 主要数据表

### 视频与管理

| 表 | 内容 |
| --- | --- |
| `videos_video` | 原文件路径、显示名称、媒体信息、转码状态、共享状态 |
| `videos_accesscode` | 视频授权码HMAC摘要、仅对未删除记录唯一的有效摘要、加密密文、尾号、有效期和删除状态 |
| `videos_playbacksession` | 播放会话令牌摘要、IP、观看统计和状态 |
| `videos_viewevent` | 播放开始、心跳、暂停、跳转和结束事件 |
| `videos_securityevent` | 授权失败、限流和IP黑名单事件 |
| `videos_adminauditlog` | 管理员写操作审计 |
| `videos_systemsettings` | 单例系统名称和IP黑名单 |

### 私密聊天

| 表 | 内容 |
| --- | --- |
| `chat_chatroom` | 聊天室名称、授权码摘要、加密密文、昵称组和开放状态 |
| `chat_chatparticipant` | 访客令牌摘要、临时身份摘要、设备特征摘要、IP、昵称、头像、进入和撤销时间 |
| `chat_chatmessage` | 文本/图片消息、受保护图片相对路径与尺寸、发送者、时间和客户端幂等编号 |

### Django

- `auth_*`：管理员账号、权限和组
- `django_session`：管理员登录会话
- `django_migrations`：已执行迁移
- `django_admin_log`：Django Admin操作记录

授权码明文不直接存储，数据库中的加密密文可由应用使用
`ACCESS_CODE_ENCRYPTION_KEY` 解密并仅向staff展示。播放令牌、聊天访客令牌和临时身份标识明文不应出现在数据库中。

`code_digest`允许保留多个历史相同值，`active_digest`只在授权码未删除时保存摘要并具有唯一约束。删除时该字段置空，因此码值可复用，同时播放历史仍指向原授权记录。

聊天图片二进制不写入MySQL；数据库只保存随机相对路径、WebP类型、字节数及宽高。消息必须至少包含正文或图片之一。

必须随数据库备份同步备份 `/etc/private-video.env`。丢失或更改授权码加密密钥后，既有授权码仍可凭HMAC摘要验证，但管理端无法恢复显示其完整值。

## 4. 迁移流程

### 开发环境

```powershell
.venv\Scripts\python manage.py makemigrations
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py makemigrations --check --dry-run
```

模型变更必须创建新迁移；不得修改已经用于生产的历史迁移。

### 生产环境

1. 确认目标服务器、数据库主机和库名。
2. 完成数据库备份。
3. 部署与迁移匹配的代码。
4. 执行 `manage.py migrate --plan`。
5. 执行 `manage.py migrate --noinput`。
6. 重启Web、Chat、Worker和Beat。
7. 运行系统检查和冒烟测试。

## 5. 备份

从 `/etc/private-video.env` 读取连接配置后执行：

```bash
set -a
source /etc/private-video.env
set +a

umask 077
MYSQL_PWD="$DB_PASSWORD" mysqldump \
  --single-transaction \
  --no-tablespaces \
  --routines \
  --triggers \
  --default-character-set=utf8mb4 \
  -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" \
  "$DB_NAME" > "private_video-$(date +%Y%m%d-%H%M%S).sql"
unset MYSQL_PWD
```

`--no-tablespaces` 避免应用用户因为没有MySQL全局 `PROCESS` 权限而产生tablespace导出错误。应用用户仍只需要目标数据库权限。

备份后至少检查：

```bash
test -s private_video-YYYYMMDD-HHMMSS.sql
grep -q 'Table structure for table `videos_video`' private_video-YYYYMMDD-HHMMSS.sql
grep -q 'Table structure for table `chat_chatroom`' private_video-YYYYMMDD-HHMMSS.sql
```

数据库转储包含管理员、IP、聊天正文、审计和会话数据，必须限制权限并加密保存。

同时备份：

- `/etc/private-video.env`
- `/root/private-video-admin.txt`
- 与数据库迁移状态匹配的应用版本
- 根据恢复目标决定是否备份 `/video` 与HLS目录
- `/var/lib/private-video/chat-images` 聊天图片目录

数据库转储与聊天图片目录应记录同一个备份时间点。图片消息的元数据位于MySQL，二进制位于文件系统；只保存其中一部分不能完整恢复聊天记录。

## 6. 恢复

1. 明确恢复目标库并再次备份当前状态。
2. 停止4个应用服务：

```bash
systemctl stop private-video-web private-video-chat private-video-worker private-video-beat
```

3. 在隔离环境确认转储可读取。
4. 创建空数据库并导入转储。
5. 部署与转储迁移状态匹配的代码。
6. 执行 `manage.py migrate` 补齐后续迁移。
7. 若备份包含聊天图片，在应用服务停止期间将图片目录恢复到 `CHAT_IMAGE_DIR`，执行 `chown -R privatevideo:privatevideo "$CHAT_IMAGE_DIR"` 并确认目录权限为0750。
8. 启动服务并验证：

```bash
systemctl start private-video-web private-video-chat private-video-worker private-video-beat
systemctl is-active private-video-web private-video-chat private-video-worker private-video-beat nginx
/opt/private-video/deploy/smoke_test.sh
```

恢复后应抽查包含图片的聊天记录，确认访客只能读取当前聊天室图片、staff可以从聊天记录页面读取图片，且Nginx内部图片路径无法被外部直接访问。

## 7. 数据保留与清理

当前版本不会自动清理以下业务记录：

- 观看记录与播放事件
- 聊天参与记录和聊天消息
- 安全事件与管理员审计

制定保留策略前，应先明确审计要求、备份周期和恢复需求。不要直接删除表或绕过Django关系约束。

## 8. 禁止操作

- 不要在存量数据库上运行 `finish_install.sh --reset-empty-database`。
- 不要把SQLite开发数据库当作生产初始化或恢复来源。
- 不要提交数据库转储到Git。
- 不要在未确认目标库和备份有效性时执行 `DROP DATABASE`、恢复或破坏性清理。
