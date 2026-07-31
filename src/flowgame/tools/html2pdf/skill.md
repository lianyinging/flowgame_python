---
name: flowgame-html2pdf
description: >
  FlowGame 动态代码节点将 HTML 转为 PDF（Playwright/Chromium）。
  API：from html2pdf import convert / convert_html。
  支持 URL、本地 .html、HTML 字符串；可加水印；自动清理 ```html 包裹。
  返回 dict，取 result = info["output"] 得到 PDF 绝对路径。
---

# HTML→PDF Skill（给大模型）

## 硬约束

1. 只通过 FlowGame **动态代码**节点调用；引擎=**Python**；代码=**多行**；业务输出赋给 **`result`**。
2. 允许：`from html2pdf import convert`、`from html2pdf import convert_html`（也可 `from src.flowgame.tools.html2pdf import …`）。
3. 依赖本机已 `playwright install chromium`；未安装时会抛 `ImportError` 提示。
4. `convert(source)` 的 `source` 只能是 **URL** 或 **本地 html/htm 路径**；HTML **字符串**必须用 **`convert_html`**。
5. 若上下文有 `robotSpace`，输出优先写到该目录，便于会话机器人 `reply_file`。
6. 不要在节点里死循环；单次转换即可。

## 调用环境（已由后端注入）

- `sys.path` 已含 `src/flowgame/tools`，故 `from html2pdf import convert` 可用。
- 依赖：`playwright`、`requests`（见 `requirements.txt`）。

## 选型

| 场景 | 用 |
|------|-----|
| 上游已是 HTML 字符串（如 LLM / 模板节点） | `convert_html(html, output=…)` |
| 已有本地 `.html` 文件路径 | `convert(path, …)` |
| 公开/内网 HTML URL | `convert(url, …)` |

## 返回值

```text
{
  "input": str,
  "output": str,              # PDF 绝对路径 ← 通常赋给 result
  "source_type": "url"|"local"|"string",
  "cleaned": bool,
  "removed_artifacts": list,
  "watermarked": bool,
  "watermark_text": str|None,
  "watermark_options": dict|None,
}
```

---

## 可粘贴代码

### HTML 字符串 → PDF（推荐写 robotSpace）

```python
from pathlib import Path
from html2pdf import convert_html

info = convert_html(
    htmlContent,
    output=Path(str(robotSpace)) / "report.pdf",
)
result = info["output"]
```

### 带水印

```python
from pathlib import Path
from html2pdf import convert_html

info = convert_html(
    htmlContent,
    output=Path(str(robotSpace)) / "report.pdf",
    watermark="内部资料 请勿外传",
    watermark_opacity=0.1,
    watermark_angle=-45,
    watermark_font_size=28,
    watermark_density=2.0,
    watermark_color="#000000",
)
result = info["output"]
```

### 本地 HTML 文件

```python
from html2pdf import convert

info = convert(str(htmlPath))
result = info["output"]
```

### URL

```python
from html2pdf import convert

info = convert(
    "https://example.com/page.html",
    output_dir=robotSpace,  # 可选：覆盖默认 output/
)
result = info["output"]
```

### 转完后给会话机器人回发文件

输出映射：动态代码节点输出字段 → `reply_file`。  
`result` 必须是本机存在的 PDF 路径字符串。

---

## 参数速查

| 参数 | 含义 | 默认 |
|------|------|------|
| `output` | PDF 完整路径 | 见 README 默认规则 |
| `output_dir` | 仅影响 URL/默认落盘目录 | `FLOWGAME_HTML2PDF_OUTPUT_DIR` 或包内 `output/` |
| `page_format` | 纸张 | `A4` |
| `landscape` | 横向 | `False` |
| `print_background` | 打印背景 | `True` |
| `wait_until` | `load` / `domcontentloaded` / `networkidle` / `commit` | `networkidle` |
| `timeout_ms` | 加载超时 | `30000` |
| `base_url` | 仅 `convert_html`：相对资源基址 | `about:blank` |
| `watermark*` | 水印文字与样式 | 无水印 |

## 禁止

- 把密钥写进代码。
- 对字符串误用 `convert(html_string)`（会当路径/URL 处理而失败）。
- 假设相对路径在任意 cwd 下可读：优先绝对路径 / `robotSpace`。
