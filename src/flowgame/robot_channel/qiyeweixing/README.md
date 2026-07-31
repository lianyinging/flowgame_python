# 企业微信机器人渠道（FlowGame）

把企业微信收发能力接到 FlowGame：**动态代码**节点里用 Python 调用 `wecom` 包。

> 给大模型用的完整调用约定与示例代码在 **[skill.md](./skill.md)**，请不要把本 README 当 Prompt 塞给模型。

---

## 你能做什么

本目录含 **两种** 企微机器人，不要混用凭证：

| 类型 | 模块 | 能力 |
|------|------|------|
| 智能机器人（WebSocket） | `wecom.aibot` | 收群 @ / 单聊消息；主动发 markdown；上传发文件/图片/视频；短时收集入站消息 |
| 群机器人（Webhook） | `wecom.webhook` | 仅向配置了 Webhook 的群 **推送** text / markdown，**不能收消息** |

实现来自本地工具目录「企业微信」：`aibot_ws_receiver.py` + `test_wecom_bot.py`。

---

## 环境准备

在 `flowgame_python` 环境中：

```bash
pip install -r requirements.txt   # 已含 wecom-aibot-sdk、requests、typing_extensions
```

在仓库根 `.env` / `.env.dev`（或本目录 `.env.example` 作参考）配置：

```bash
# 智能机器人
FLOWGAME_WECOM_BOT_ID=你的BotID
FLOWGAME_WECOM_BOT_SECRET=你的Secret
FLOWGAME_WECOM_CHATID=可选默认会话

# 群 Webhook（key= 后面那一段）
FLOWGAME_WECOM_WEBHOOK_KEY=你的webhook_key
```

**不要把密钥提交进 Git。** 原先测试脚本里的明文 BotID/Secret 已改为环境变量，请自行填到本地 env。

如何拿到凭证：

1. **智能机器人**：企微后台创建「智能机器人」，复制 BotID / Secret；把机器人拉进群后，在群里 @ 它发一条，即可记下 chatid（也会写入本目录 `.last_chatid`）。
2. **群 Webhook**：群聊 → 添加群机器人 → 复制 Webhook URL 中 `key=` 后面的字符串。

---

## 在编辑器里怎么用

1. 流程里加 **动态代码** 节点  
2. 引擎选 **Python**，代码用 **多行**  
3. `import` 后调用 API，最后把结果赋给 **`result`**  

Webhook 最短例子：

```python
from wecom import webhook
result = webhook.send_markdown("**FlowGame** 推送测试")
```

智能机器人发文本：

```python
from wecom import aibot
result = aibot.send_markdown("你好", chatid="你的chatid")
```

后端执行动态代码时会自动把本目录加入 `sys.path`，因此 `from wecom import …` 可用。

包名刻意使用 **`wecom`**，而不是小红书渠道的 `scripts`，避免两边同时注入时 import 冲突。

---

## 本机 CLI（常驻收发）

在已配置环境变量、且 `qiyeweixing` 在 `PYTHONPATH`（或 `cd` 到该目录）时：

```bash
cd src/flowgame/robot_channel/qiyeweixing
# 仓库根需在 PYTHONPATH，或从 flowgame_python 根：
PYTHONPATH=. python -m wecom.daemon

# 发一条后退出
PYTHONPATH=src/flowgame/robot_channel/qiyeweixing python -m wecom.daemon \
  --send "你好" --chatid 你的chatid

# 发文件
PYTHONPATH=src/flowgame/robot_channel/qiyeweixing python -m wecom.daemon \
  --send-file ./report.pdf --chatid 你的chatid
```

更稳妥的方式：从 `flowgame_python` 根先注入路径再跑，或用动态代码节点调用 `aibot.send_*` / `collect_messages`。

收到的单聊图片/文件默认落在本目录 `downloads/`。

---

## 限制与注意

- image / file / video 入站：**官方目前主要支持单聊**，群里发文件常常收不到  
- 智能机器人主动发文件需先 `upload_media`，单文件约 ≤50MB  
- 群 Webhook 频率约 20 条/分钟；错误码 93000 多为 key 无效，45009 为超限  
- 动态代码节点适合「发一条 / 短等几条」；**不要**在节点里写死循环常驻监听  

---

## 目录说明

```text
qiyeweixing/
├── README.md       ← 你正在看的（给人）
├── skill.md        ← 给大模型的操作契约与可粘贴代码
├── __init__.py     ← 注册 wecom 的 import 路径
├── _compat.py      ← Python 3.10 兼容 typing.NotRequired
├── .env.example
├── downloads/      ← 入站媒体保存目录
└── wecom/
    ├── aibot.py    ← 智能机器人同步 API
    ├── webhook.py  ← 群 Webhook
    ├── daemon.py   ← 常驻 CLI
    └── _util.py
```

---

## 来源与维护

- 移植自：`/Users/lianying/Desktop/神经网络/我的项目/工具/企业微信`  
- 升级上游时：对照 `aibot_ws_receiver.py` / `test_wecom_bot.py` 同步 `wecom/`，并核对本 README / skill.md  
- 联调优先查：环境变量是否加载、chatid 是否正确、动态代码是否多行且赋了 `result`

---

## 会话机器人（编辑器业务工具）

管理端「业务工具 → 会话机器人」可配置企微智能机器人、绑定流程与入出参映射，并**启动/停用**。

- **监听进程**：独立 `Robot Worker`（与 API 同仓库）
- **本地一键**：`APP_ENV=dev python run.py` 会自动拉起 Worker（`FLOWGAME_ROBOT_AUTOSTART=true`）
- **单独运行**：`python -m src.flowgame.robot_channel.worker`
- **API 多 workers**：安全；监听只在 Worker 单实例里
- 收到消息后 Worker 按映射调用 `POST /execute`，再按输出映射回发：
  - `reply_markdown` / `reply_text` → 文字
  - `reply_file` → 本地文件路径（可数组）；与文字同时有时 **先文后文件**
- 启动时创建工作空间：`robot_space/qiyeweixing/{robotId}/`，流程变量注入 `robotSpace`

相关代码：`src/flowgame/robot_channel/`（`store` / `runtime` / `worker` / `spawn` / `router`）。
