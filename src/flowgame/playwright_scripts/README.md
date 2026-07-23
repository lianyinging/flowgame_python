# Playwright 搜索脚本

供 `webSearchNode` **可选渠道**使用的 Playwright 爬虫，目录独立于 `web/search.py` 主逻辑。

| 引擎 id（节点勾选） | 脚本 | 目标站 |
|---------------------|------|--------|
| `qq_news` | `qq_news.py` | 腾讯新闻搜索 |
| `sina_news` | `sina_news.py` | 新浪新闻搜索 |

## 安装

`playwright` 已写入默认 `requirements.txt`。本地还需下载 Chromium；Docker（`Dockerfile` / `Dockerfile_test`）构建时会执行 `playwright install --with-deps chromium`。

```bash
pip install -r requirements.txt
playwright install chromium
```

环境变量见仓库根目录 `.env.example`（`FLOWGAME_PLAYWRIGHT_*`）。

## 单独调试

```bash
cd /path/to/flowgame_python
python -m src.flowgame.playwright_scripts.qq_news --keyword 小红书 --pages 2
python -m src.flowgame.playwright_scripts.sina_news --keyword 小红书 --pages 2
```

## 约定

- `crawl(keyword, ...)` 返回 `[{title, summary, url, ...}, ...]`
- 由 `web/search.py` 映射为统一 `documents`（title / content / url / engine / source）
- 未安装 Playwright 时，勾选对应引擎会写入 `errors`，不影响其它免费引擎
