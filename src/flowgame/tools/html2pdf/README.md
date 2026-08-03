# HTML 转 PDF（html2pdf）

Playwright / Chromium 将 HTML 转为 PDF。给人看的说明；**给模型的调用契约见 [skill.md](./skill.md)**。  
工具索引见上级 [../skill.md](../skill.md)。

## 能力

| API | 输入 |
|-----|------|
| `convert(source, …)` | URL 或本地 `.html` / `.htm` |
| `convert_html(html, …)` | HTML 字符串 |

可选水印；自动清理 \`\`\`html 包裹。返回 dict，`output` 为 PDF 绝对路径。

## 环境

```bash
pip install -r requirements.txt   # 已含 playwright、requests
playwright install chromium
```

可选：`FLOWGAME_HTML2PDF_OUTPUT_DIR`（仅当未指定 `output` 时作为落盘目录；默认系统临时目录下的 `flowgame_html2pdf/`）。**业务产物请写到 `robotSpace` / `runtimeSpace`。**

## 目录

```text
html2pdf/
├── skill.md       ← 模型按需加载（入参/出参/脚本格式）
├── README.md      ← 你正在看的
├── __init__.py
└── converter.py
```

本目录**不**再维护 `output/` 子目录。
