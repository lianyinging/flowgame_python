# 会话机器人工作空间

每个机器人启动时确保目录：

```text
robot_space/
  qiyeweixing/           # 渠道（企业微信智能机器人）
    {robotId}/           # 该机器人工作空间
```

- 渠道目录已存在则不再「新建」（`mkdir(exist_ok=True)`）
- 仅保证 `{robotId}` 目录存在

流程执行时会注入变量：

| 键 | 含义 |
|----|------|
| `robotSpace` | 该机器人工作空间绝对路径 |
| `robotId` | 机器人 ID |

环境变量：

| 变量 | 说明 | 默认 |
|------|------|------|
| `FLOWGAME_ROBOT_SPACE_DIR` | 根目录（绝对或相对仓库根） | `src/flowgame/robot_space` |
