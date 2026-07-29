# 聊天室备用昵称库

## 设计规则

- 每个聊天室创建时随机选择一组昵称，也允许管理员指定。
- 一组昵称对应一部中文热门小说，参与者进入时依次获得不同人物昵称。
- 当前内置22组，每组12个基础昵称。
- 同一聊天室超过12位历史参与者时，系统会在人物名后增加轮次编号，仍保持昵称唯一。
- 昵称仅用于聊天室内区分身份，不代表人物、作者或出版方对本项目的授权或背书。

## 内置作品

1. 西游记
2. 三国演义
3. 水浒传
4. 红楼梦
5. 射雕英雄传
6. 神雕侠侣
7. 倚天屠龙记
8. 天龙八部
9. 笑傲江湖
10. 鹿鼎记
11. 诛仙
12. 斗破苍穹
13. 斗罗大陆
14. 凡人修仙传
15. 全职高手
16. 盗墓笔记
17. 鬼吹灯
18. 庆余年
19. 琅琊榜
20. 雪中悍刀行
21. 将夜
22. 诡秘之主

具体人物名单由 `chat/nicknames.py` 统一维护。

## 网络资料核对

人物名单结合小说常见主要人物资料整理，并重点交叉核对以下公开页面：

- 四大名著：https://zh.wikipedia.org/wiki/四大名著
- 三国演义角色：https://zh.wikipedia.org/wiki/三国演义角色列表
- 射雕英雄传：https://zh.wikipedia.org/wiki/射雕英雄传
- 诛仙：https://zh.wikipedia.org/wiki/诛仙
- 斗破苍穹：https://zh.wikipedia.org/wiki/斗破苍穹
- 盗墓笔记：https://zh.wikipedia.org/wiki/盗墓笔记
- 鬼吹灯：https://zh.wikipedia.org/wiki/鬼吹灯
- 庆余年：https://zh.wikipedia.org/wiki/庆余年_(第一季)
- 琅琊榜：https://zh.wikipedia.org/wiki/琅琊榜_(电视剧)
- 雪中悍刀行：https://zh.wikipedia.org/wiki/雪中悍刀行
- 将夜：https://zh.wikipedia.org/wiki/将夜_(小说)
- 凡人修仙传：https://zh.wikipedia.org/wiki/凡人修仙传

昵称库只保存人物名称，不复制作品正文、人物介绍或其他受版权保护的表达。
