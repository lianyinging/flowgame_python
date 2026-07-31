# HTML 转 PDF（FlowGame tools）

用 Playwright / Chromium 把 HTML 打成 PDF，支持 **URL**、**本地 .html**、**HTML 字符串**，可选平铺水印，并自动剥掉大模型常见的 \`\`\`html 包裹。

> 给大模型用的完整调用约定与可粘贴代码在 **[skill.md](./skill.md)**，请不要把本 README 当 Prompt 塞给模型。

移植自本地工具目录「html转pdf」。

---

## 你能做什么

| 入口 | 说明 |
|------|------|
| `convert(source, …)` | `source` 为 `http(s)://…` 或本地 `.html` / `.htm` 路径 |
| `convert_html(html, …)` | 直接传 HTML 字符串（适合动态代码上游已生成 HTML） |
| CLI | `python -m src.flowgame.tools.html2pdf.converter <source>` |

返回值均为 dict，其中 **`output`** 为生成的 PDF **绝对路径**（可再映射到会话机器人 `reply_file`）。

---

## 环境准备

`flowgame_python` 的 `requirements.txt` 已含 `playwright`、`requests`。本机还需浏览器内核：

```bash
pip install -r requirements.txt
playwright install chromium
```

Docker 镜像构建时一般已执行 `playwright install --with-deps chromium`。

可选环境变量：

| 变量 | 说明 | 默认 |
|------|------|------|
| `FLOWGAME_HTML2PDF_OUTPUT_DIR` | URL / 字符串转 PDF 的默认输出目录 | 本包下 `output/` |

---

## 在编辑器里怎么用

1. 加 **动态代码** 节点，引擎选 **Python**，写 **多行**
2. `from html2pdf import convert` 或 `convert_html`（后端会把 `tools/` 注入 `sys.path`）
3. 把 PDF 路径赋给 **`result`**（或 `result = info["output"]`）

HTML 字符串 + 存到机器人工作空间：

```python
from pathlib import Path
from html2pdf import convert_html

info = convert_html(
    htmlContent,
    output=Path(str(robotSpace)) / "report.pdf",
    watermark="内部资料",
)
result = info["output"]
```

本地 HTML 文件：

```python
from html2pdf import convert

info = convert(str(htmlPath), watermark="内部资料 请勿外传")
result = info["output"]
```

URL：

```python
from html2pdf import convert

info = convert("https://example.com/page.html")
result = info["output"]
```

---

## 默认输出位置

| 输入 | 未指定 `-o` / `output` 时 |
|------|---------------------------|
| 本地 HTML | 与源文件同目录，扩展名改为 `.pdf` |
| URL | `FLOWGAME_HTML2PDF_OUTPUT_DIR` 或本包 `output/{从 URL 推断的名字}.pdf` |
| HTML 字符串 | 同上目录下 `{uuid}.pdf`（建议显式传 `output` / `output_dir=robotSpace`） |

---

## 水印与清理

- 处理顺序：读入 → 去掉 \`\`\`html / \`\`\` → 注入 CSS 平铺水印 → Playwright 渲染
- 常用参数：`watermark`、`watermark_opacity`、`watermark_angle`、`watermark_font_size`、`watermark_density`、`watermark_color`

---

## 目录说明

```text
html2pdf/
├── README.md       ← 你正在看的（给人）
├── skill.md        ← 给大模型的操作契约
├── __init__.py     ← 导出 API + 注册 import 路径
├── converter.py    ← 核心实现与 CLI
└── output/         ← URL/字符串默认输出（可 gitignore）
```

---

## 测试

```bash
cd flowgame_python
python -m unittest tests.test_html2pdf -v

# 真实起 Chromium（可选）
RUN_PLAYWRIGHT_INTEGRATION=1 python -m unittest tests.test_html2pdf.TestConvertIntegration -v
```
