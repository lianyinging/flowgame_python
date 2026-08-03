---
name: flowgame-html2pdf
tool_id: html2pdf
description: >
  HTML→PDF（Playwright/Chromium）。按需加载本 skill 后再生成调用脚本。
  支持 URL、本地 .html/.htm、HTML 字符串；可加水印；自动清理 ```html 包裹。
---

# html2pdf 详情 Skill（给大模型 · 按需加载）

> 仅在索引 `tools/skill.md` 选型为 `html2pdf` 后加载本文件。

## 硬约束

1. 动态代码：引擎=**Python**；代码=**多行**；最终必须赋值 **`result`**。
2. API：`from html2pdf import convert` / `convert_html`（`sys.path` 已含 `tools/`）。
3. `convert(source)`：`source` 只能是 **http(s) URL** 或 **本地 .html/.htm 路径**。
4. HTML **字符串**必须用 **`convert_html(html, …)`**，禁止把整段 HTML 传给 `convert`。
5. **必须显式指定落盘位置**：优先 `robotSpace` / `runtimeSpace`；勿依赖包内 `output/`。
6. 依赖：已安装 `playwright` 且执行过 `playwright install chromium`。

---

## 输入参数

### `convert(source, **opts)` — URL 或本地文件

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | `https://…` 或本地 `.html`/`.htm` 绝对/相对路径 |
| `output` | string/Path | 强烈建议 | PDF 完整路径；缺省时 URL 落到系统临时目录 |
| `output_dir` | string/Path | 否 | 仅 URL 且未给 `output` 时作为目录 |
| `page_format` | string | 否 | 默认 `A4` |
| `landscape` | bool | 否 | 默认 `False` |
| `print_background` | bool | 否 | 默认 `True` |
| `wait_until` | string | 否 | `load` / `domcontentloaded` / `networkidle` / `commit` |
| `timeout_ms` | int | 否 | 默认 `30000` |
| `watermark` | string | 否 | 水印文字；空则无水印 |
| `watermark_opacity` | float | 否 | 默认 `0.12` |
| `watermark_angle` | float | 否 | 默认 `-45` |
| `watermark_font_size` | int | 否 | 默认 `48` |
| `watermark_density` | float | 否 | `0.5~5`，默认 `1.5` |
| `watermark_color` | string | 否 | `#RRGGBB` 或 `rgb(r,g,b)` |

### `convert_html(html, **opts)` — HTML 字符串

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `html` | string | 是 | HTML 文本（可含 \`\`\`html 包裹，会自动清理） |
| `output` | string/Path | **强烈建议** | PDF 完整路径 |
| `output_dir` | string/Path | 否 | 未给 `output` 时目录（再生成随机文件名） |
| `base_url` | string | 否 | 相对资源基址，默认 `about:blank` |
| 其余 | | | 与 `convert` 的版式/水印参数相同 |

### 上下文变量（若存在则优先使用）

| 变量 | 用途 |
|------|------|
| `robotSpace` | 会话机器人工作区绝对路径 |
| `runtimeSpace` | AgentTeam 本次运行工作区绝对路径 |
| `htmlContent` / `htmlPath` / `imgUrl` 等 | 上游节点注入时按实际变量名使用 |

---

## 输出（函数返回值）

`convert` / `convert_html` 均返回 **dict**：

```json
{
  "input": "string",
  "output": "string",
  "source_type": "url | local | string",
  "cleaned": true,
  "removed_artifacts": [],
  "watermarked": false,
  "watermark_text": null,
  "watermark_options": null
}
```

| 字段 | 含义 |
|------|------|
| `output` | **PDF 绝对路径**（动态代码里通常 `result = info["output"]`） |
| `source_type` | `url` / `local` / `string` |
| `cleaned` | 是否去掉了 markdown 代码围栏 |
| `watermarked` | 是否加水印 |

---

## 模型须返回的脚本格式

生成 **完整可执行** 的 Python 多行脚本（不要省略 import），最后一行逻辑必须让业务结果进入 **`result`**。

### 模板 A — HTML 字符串 → PDF（有 robotSpace）

```python
from pathlib import Path
from html2pdf import convert_html

info = convert_html(
    htmlContent,
    output=Path(str(robotSpace)) / "report.pdf",
)
result = info["output"]
```

### 模板 B — 带水印

```python
from pathlib import Path
from html2pdf import convert_html

info = convert_html(
    htmlContent,
    output=Path(str(robotSpace)) / "report.pdf",
    watermark="内部资料 请勿外传",
    watermark_opacity=0.1,
    watermark_font_size=28,
    watermark_density=2.0,
)
result = info["output"]
```

### 模板 C — 本地 HTML 文件

```python
from pathlib import Path
from html2pdf import convert

info = convert(
    str(htmlPath),
    output=Path(str(robotSpace)) / "page.pdf",
)
result = info["output"]
```

### 模板 D — URL

```python
from pathlib import Path
from html2pdf import convert

info = convert(
    pageUrl,
    output=Path(str(robotSpace)) / "page.pdf",
)
result = info["output"]
```

### 若需把整个 info 交给下游

```python
result = info  # dict；仅当下游明确要完整对象时
```

默认优先：`result = info["output"]`（路径字符串，便于 `reply_file`）。

---

## 禁止

- 未指定 `output`/`output_dir`/`robotSpace`/`runtimeSpace` 时假定固定业务路径。
- 对字符串误用 `convert(html_string)`。
- 在工具目录下创建或依赖 `html2pdf/output/`。
