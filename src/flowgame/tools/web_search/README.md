# web_search（联网搜索）

多渠道联网搜索工具。给人看；模型见 [skill.md](./skill.md)。

## 已实现渠道

| 目录 | 说明 |
|------|------|
| [channel/tenxunxinwen](./channel/tenxunxinwen/) | 腾讯新闻（Playwright） |

规划中的渠道列表：`channel/搜索渠道.txt`。

## 动态代码

```python
from web_search.channel.tenxunxinwen import search
result = search(keyword="小红书", limit=10)
```

后端会把 `tools/` 注入 `sys.path`。
