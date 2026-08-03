---
name: flowgame-web-search
tool_id: web_search
description: >
  FlowGame 联网搜索工具。先选渠道 channel_id，再加载对应 channel/*/skill.md。
  当前已实现：tenxunxinwen（腾讯新闻）。
---

# web_search 工具 Skill（给大模型）

## 两阶段

1. 确认需要联网搜索 → `tool_id=web_search`
2. 选择渠道 → 加载该渠道 `skill.md` → 按脚本格式调用

## 渠道目录

| channel_id | 名称 | 何时用 | 详情 skill |
|------------|------|--------|------------|
| `tenxunxinwen` | 腾讯新闻 | 中文新闻/热点；默认返回列表并抓取每条 url 正文 | `channel/tenxunxinwen/skill.md` |

其它渠道见 `channel/搜索渠道.txt`（规划中，未实现勿调用）。

## 硬约束

- 产物一般为内存中的结果列表；若需落盘，写到 `robotSpace` / `runtimeSpace`。
- 动态代码：`result = …`；引擎 Python 多行。
- 未加载渠道详情 skill 前，不得编造函数名。

## 选型示例

```json
{
  "tool_id": "web_search",
  "channel_id": "tenxunxinwen",
  "reason": "需要中文新闻检索",
  "skill_path": "channel/tenxunxinwen/skill.md"
}
```
