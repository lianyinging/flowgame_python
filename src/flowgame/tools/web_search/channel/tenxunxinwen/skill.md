---
name: flowgame-web-search-tenxunxinwen
tool_id: web_search
channel_id: tenxunxinwen
description: >
  腾讯新闻渠道联网搜索（Playwright）。默认搜索列表后继续打开 url 抓取正文。
  入口：from web_search.channel.tenxunxinwen import search / fetch_article
---

# 腾讯新闻渠道详情 Skill（给大模型 · 按需加载）

> 仅在索引选型为 `web_search` 且渠道为 `tenxunxinwen` 后加载本文件。

## 硬约束

1. 动态代码：引擎=**Python**；代码=**多行**；最终赋值 **`result`**。
2. `from web_search.channel.tenxunxinwen import search`（`sys.path` 已含 `tools/`）。
3. 依赖：已安装 `playwright` 且 `playwright install chromium`。
4. `keyword` 必填；不要空搜。
5. **默认会抓正文**（`fetch_content=True`），条数不宜过大（建议 `limit≤5`～`10`）。
6. 只要列表不要正文时显式传 `fetch_content=False`。

---

## 输入参数 — `search(keyword, **opts)`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keyword` | string | 是 | 搜索关键词 |
| `limit` | int | 否 | 最多返回条数，默认 `10` |
| `pages` | int | 否 | 翻页数；默认按 `limit` 估算 |
| `start_page` | int | 否 | 起始页，默认 `1` |
| `headless` | bool | 否 | 默认跟 `FLOWGAME_PLAYWRIGHT_HEADLESS` |
| `delay` | float | 否 | 翻页/抓正文间隔秒 |
| `fetch_content` | bool | 否 | **默认 `True`**：打开每条 `url` 抓正文写入 `content` |
| `max_content_chars` | int | 否 | 正文最大字符，默认 `6000` |

搜索页：`https://news.qq.com/search?query={keyword}&page={page}`

### 单 URL 正文 — `fetch_article(url, **opts)`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | 是 | 文章 URL |
| `max_chars` | int | 否 | 默认 `6000` |
| `hint_title` | string | 否 | 标题提示 |

优先 Playwright 抽取；过短则回退 Jina / requests（`fetch_url_document`）。

---

## 输出

`search(...)` 返回 **list[dict]**，每项：

```json
{
  "title": "搜索列表标题",
  "summary": "搜索列表摘要",
  "content": "正文（fetch_content=True 时为详情页正文；否则多为摘要）",
  "url": "https://...",
  "channel": "tenxunxinwen",
  "source": "腾讯新闻",
  "engine": "tenxunxinwen",
  "contentFetched": true,
  "fetchMethod": "playwright",
  "pageTitle": "详情页标题（可选）",
  "errorMessage": ""
}
```

| 字段 | 含义 |
|------|------|
| `summary` | 搜索结果卡片摘要 |
| `content` | **正文**（抓取成功）或回退为摘要 |
| `contentFetched` | 是否成功从详情页拿到足够正文 |
| `fetchMethod` | `playwright` / `jina` / `requests+strip` 等 |

---

## 模型须返回的脚本格式

### 模板 A — 搜索 + 正文（默认）

```python
from web_search.channel.tenxunxinwen import search

result = search(keyword=str(topic).strip(), limit=5, fetch_content=True)
```

### 模板 B — 只要搜索列表

```python
from web_search.channel.tenxunxinwen import search

result = search(keyword=str(topic).strip(), limit=10, fetch_content=False)
```

### 模板 C — 已知 URL 只抓正文

```python
from web_search.channel.tenxunxinwen import fetch_article

doc = fetch_article(str(url).strip(), hint_title=str(title or ""))
result = doc.get("content") or ""
```

### 模板 D — 只要标题+链接+正文

```python
from web_search.channel.tenxunxinwen import search

items = search(keyword=str(topic).strip(), limit=5, fetch_content=True)
result = [
    {
        "title": x.get("pageTitle") or x["title"],
        "url": x["url"],
        "content": x.get("content") or "",
        "contentFetched": x.get("contentFetched"),
    }
    for x in items
]
```

---

## 禁止

- 伪造正文。
- `limit` 很大且 `fetch_content=True`（会非常慢）。
- 未装 Chromium 时假装已搜到。
