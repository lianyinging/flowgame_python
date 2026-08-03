# 腾讯新闻搜索渠道（tenxunxinwen）

Playwright 抓取 [腾讯新闻搜索](https://news.qq.com/search?query=...)，**默认继续打开结果 URL 抓正文**。  
给人看的说明；**模型调用契约见 [skill.md](./skill.md)**。

## 能力

```python
from web_search.channel.tenxunxinwen import search, fetch_article

# 搜索 + 正文（默认）
items = search(keyword="小红书", limit=5)
# content = 详情页正文；summary = 列表摘要；contentFetched 表示正文是否抓成功

# 只要列表
items = search(keyword="小红书", limit=10, fetch_content=False)

# 单 URL 正文
doc = fetch_article("https://news.qq.com/rain/a/...")
```

正文抽取：Playwright 选择器优先，过短则回退 `web.fetch.fetch_url_document`（Jina / HTML strip）。

## 环境

```bash
pip install -r requirements.txt
playwright install chromium
```

## CLI

```bash
PYTHONPATH=src/flowgame/tools python -m web_search.channel.tenxunxinwen.crawler -k 小红书 -n 3
PYTHONPATH=src/flowgame/tools python -m web_search.channel.tenxunxinwen.crawler -k 小红书 -n 5 --no-fetch-content
```
