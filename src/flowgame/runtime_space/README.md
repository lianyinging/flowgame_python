# AgentTeam / 数字员工临时 Runtime 空间

每次 `POST /teams/run` 启动时会在 `runs/` 下创建：

```text
{teamKey}_{UTC时间}_{runId}/
  .runtime_workspace     # 工作区标记 + 本次运行元数据（JSON）
  （子 Agent 工作成果文件）
```

`.runtime_workspace` 示例字段：`schema`、`kind=digital_employee_run`、`teamKey`、`runId`、`runtimeSpace`、`createdAt`。

黑板写入：

| 键 | 含义 |
|----|------|
| `runId` | 本次运行短 ID |
| `runtimeSpace` | 目录绝对路径 |

环境变量：

| 变量 | 说明 | 默认 |
|------|------|------|
| `FLOWGAME_RUNTIME_SPACE_DIR` | 根目录（绝对或相对仓库根） | `src/flowgame/runtime_space/runs` |
