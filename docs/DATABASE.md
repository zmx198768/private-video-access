# 数据库初始化与维护

## 初始化

本项目生产环境使用 MySQL 8。`deploy/mysql/init.sql` 负责创建：

- `private_video` 数据库
- 仅能访问该数据库的 `private_video` 用户
- `utf8mb4` 字符集和MySQL 8排序规则

执行前必须替换占位密码。数据库表、索引和数据迁移统一由Django维护：

```bash
python manage.py migrate
```

不要手工复制Django模型生成的 `CREATE TABLE` 到初始化SQL，否则容易与迁移历史发生漂移。

## 主要数据

- `videos_video`：源文件、显示名称、转码状态和共享状态
- `videos_accesscode`：授权码摘要、有效期和删除状态
- `videos_playbacksession`：授权会话、IP和观看统计
- `videos_viewevent`：播放事件
- `videos_securityevent`：失败授权和限流事件
- `videos_adminauditlog`：管理员操作审计
- `videos_systemsettings`：单例系统名称与IP黑名单配置
- Django `auth_*`、`django_session`：管理员账号与会话

## 迁移流程

开发环境：

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py makemigrations --check --dry-run
```

生产环境：

1. 备份数据库。
2. 部署与迁移匹配的代码。
3. 执行 `python manage.py migrate --plan`。
4. 执行 `python manage.py migrate`。
5. 运行系统检查与冒烟测试。

不得修改已经在生产执行过的历史迁移，应创建新的迁移。

## 备份

```bash
mysqldump \
  --single-transaction \
  --routines \
  --triggers \
  --default-character-set=utf8mb4 \
  -h 127.0.0.1 -P 3306 -u private_video -p \
  private_video > private_video-YYYYMMDD.sql
```

备份文件包含用户、IP、审计和会话数据，必须加密保存并限制访问。

## 恢复

1. 停止Web、Worker和Beat。
2. 在隔离环境验证备份可读取。
3. 创建空数据库。
4. 导入转储。
5. 部署与转储迁移状态相匹配的代码。
6. 执行 `manage.py migrate`。
7. 启动服务并运行冒烟测试。

禁止直接在未确认库名的情况下执行仓库中的 `--reset-empty-database` 选项。
