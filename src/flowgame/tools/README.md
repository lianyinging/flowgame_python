# FlowGame Tools（给人）

本目录是 **可被 Agent 选用的工具集**。

| 文件 | 给谁 | 作用 |
|------|------|------|
| [skill.md](./skill.md) | 大模型 | **索引**：有哪些工具、何时用、详情 skill 路径 |
| `{tool}/skill.md` | 大模型 | **详情**：入参/出参、须返回的脚本格式（按需加载） |
| `{tool}/README.md` | 人 | 安装、依赖、本地调试 |

约定：

1. 不要在本目录下为工具建长期 `output/`；产物写到调用方工作区（如 `robotSpace` / `runtimeSpace`）或系统临时目录。
2. 新增工具：新建子目录 + `skill.md`（必填）+ 实现代码；并在根 `skill.md` 索引表里加一行。
3. 联网搜索渠道：放在 `web_search/channel/{channel_id}/`，并在 `web_search/skill.md` 渠道表登记。
4. Agent 选型时只读根索引；决定调用某工具后再加载该工具的 `skill.md`。
