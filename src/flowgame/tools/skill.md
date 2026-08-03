---
name: flowgame-tools
description: >
  FlowGame 可选用工具索引（供 Agent 选型）。
  先根据本文件选择 tool_id，再按需加载对应子目录 skill.md 获取入参/出参与须返回的脚本格式。
  不要在未加载详情 skill 前臆造 API。
---

# FlowGame Tools 索引（给大模型）

## 用法（两阶段）

1. **选型**：只根据本索引的「何时用」选择 `tool_id`。
2. **调用**：加载 `skill_path` 指向的详情 skill，严格按其中的**输入 / 输出 / 脚本格式**产出可执行代码或结构化调用结果。

## 硬约束

- 产物路径优先使用上下文中的 `robotSpace` 或 `runtimeSpace`；**禁止**依赖 `tools/**/output/`。
- 动态代码场景：引擎=Python，多行脚本，最终赋值 **`result`**（见各工具 skill）。
- 未加载某工具的详情 skill 前，不得编造函数签名或返回字段。

## 工具目录

| tool_id | 名称 | 何时用 | 详情 skill（按需加载） |
|---------|------|--------|------------------------|
| `html2pdf` | HTML 转 PDF | 需要把 HTML（URL / 本地文件 / 字符串）渲染成 PDF 文件，可选水印 | `html2pdf/skill.md` |
| `web_search` | 联网搜索 | 需要按关键词检索网页/新闻（先选渠道再加载渠道 skill） | `web_search/skill.md` |

## 选型后你应返回的中间决策（推荐）

在真正写脚本前，先明确（可对内思考，不必对用户复述）：

```json
{
  "tool_id": "html2pdf",
  "reason": "一句话说明为何选该工具",
  "skill_path": "html2pdf/skill.md"
}
```

然后加载该 `skill_path`，再按详情 skill 输出最终脚本。
