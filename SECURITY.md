# 安全策略

## 报告安全问题

请不要通过公开Issue披露可利用漏洞。仓库公开后，请使用 GitHub 仓库的
“Security → Advisories → Report a vulnerability” 私密报告入口联系维护者。

报告应包含影响范围、复现步骤、受影响版本和建议修复方式。请勿附带真实授权码、Cookie、管理员密码或用户数据。

## 敏感数据

以下内容不得进入Git仓库：

- `/etc/private-video.env`
- `/root/private-video-admin.txt`
- 数据库与Redis密码
- 真实授权码和会话Cookie
- MySQL转储
- 私钥与TLS私钥
- 未脱敏日志、IP和观看记录

## 支持范围

安全更新以最新主分支为准。公开发布后应在此文件维护受支持版本表。

## 已知边界

系统通过访问控制、短期签名、HLS分片和审计提高未授权获取成本，但无法保证浏览器已接收的视频数据绝对不能被提取或录屏。
