# AgentTeam 临时 Runtime 空间

每次 `POST /teams/run` 启动时会在 `runs/` 下创建：

```text
{teamKey}_{UTC时间}_{runId}/
  README.txt
  （子 Agent 工作成果文件）
```

黑板写入：

| 键 | 含义 |
|----|------|
| `runId` | 本次运行短 ID |
| `runtimeSpace` | 目录绝对路径 |

环境变量：

| 变量 | 说明 | 默认 |
|------|------|------|
| `FLOWGAME_RUNTIME_SPACE_DIR` | 根目录（绝对或相对仓库根） | `src/flowgame/runtime_space/runs` |
