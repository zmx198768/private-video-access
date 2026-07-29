# 贡献指南

感谢参与本项目。提交变更前请先阅读 `AGENTS.md`，并通过 `docs/README.md` 找到与改动相关的架构、部署、数据库或操作文档。

## 开发环境

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py test -v 2
```

本地未设置 `DB_ENGINE=mysql` 时使用SQLite。生产部署仍必须使用MySQL 8。

## 提交要求

- 一个提交只解决一个清晰问题
- 模型变更包含Django迁移
- 行为变更包含测试和文档
- 环境变量、服务或部署脚本变更同步更新环境样例和部署手册
- 不提交真实凭据、IP、视频、HLS、数据库或日志
- 不绕过CSRF、权限、限流、签名或路径校验
- 提交前运行 `manage.py check`、全部测试、迁移检查和 `git diff --check`

## 报告问题

安全问题不要提交公开Issue，请按 `SECURITY.md` 的方式私下报告。普通问题请提供版本、复现步骤、预期行为、实际行为和相关日志，日志必须先脱敏。
