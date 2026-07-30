---
name: flowgame-qiyeweixin
description: >
  FlowGame 动态代码节点调用企业微信（WeCom）机器人能力。
  含两类：①智能机器人 WebSocket 收发（from wecom import aibot）；
  ②群 Webhook 仅推送（from wecom import webhook）。
  当编排需要：往企微群/单聊发 markdown、发文件图片、短时收消息时使用本 skill。
  在动态代码中写 Python 多行，最终赋值给 result。
---

# 企业微信 Skill（给大模型）

## 硬约束

1. 只通过 FlowGame **动态代码**节点调用；引擎=**Python**；代码=**多行**；输出变量名必须是 **`result`**。
2. 允许：`from wecom import aibot`、`from wecom import webhook`（包名是 **`wecom`**，不是 `scripts`，以免与小红书冲突）。
3. **凭证不得写死在代码里**。智能机器人用环境变量 `FLOWGAME_WECOM_BOT_ID` / `FLOWGAME_WECOM_BOT_SECRET`（可另传 `bot_id=` / `secret=`）；Webhook 用 `FLOWGAME_WECOM_WEBHOOK_KEY`（或 `key=`）。
4. 主动发送必须有会话：`chatid=`（群填 chatid，单聊填 userid），或环境变量 `FLOWGAME_WECOM_CHATID`，或此前已收过消息写入的 `.last_chatid`。
5. **Webhook 只能发、不能收**；要收消息用 `aibot.collect_messages`。
6. 官方限制：image / file / video / voice 入站回调目前主要支持**单聊**；群聊里发文件通常收不到。
7. 若上下文有黑板变量 `runtimeSpace`，下载/中间产物可拷到该目录。
8. 群 Webhook 约 **20 条/分钟**限流，勿刷屏。

## 调用环境（已由后端注入）

- `sys.path` 已含 `robot_channel/qiyeweixing`，故 `from wecom import aibot` 可用。
- 依赖：`wecom-aibot-sdk`、`requests`、`typing_extensions`（Python 3.10 需要）。

## 选型

| 场景 | 用 |
|------|-----|
| 只要往群里推一条通知 | `webhook.send_text` / `webhook.send_markdown` |
| 要发到指定会话、发文件、或要收消息 | `aibot.*` |

---

## API 速查与可粘贴代码

### webhook — 群机器人推送

```python
from wecom import webhook
result = webhook.send_text("流程跑完了")
```

```python
from wecom import webhook
result = webhook.send_text("请相关同学看一下", mentioned_list=["@all"])
```

```python
from wecom import webhook
result = webhook.send_markdown("**情报推送**\n> 今日摘要已生成")
```

### aibot — 智能机器人：发 markdown

```python
from wecom import aibot
result = aibot.send_markdown(
    "你好，这是 FlowGame 推送",
    chatid="群chatid或单聊userid",
)
```

不写 chatid 时读 `FLOWGAME_WECOM_CHATID` 或最近会话：

```python
from wecom import aibot
result = aibot.send_markdown("使用默认会话发送")
```

### aibot — 发文件 / 图片 / 视频

按扩展名自动推断类型（jpg/png→image，mp4→video，amr→voice，其它→file），单文件约 ≤50MB。

```python
from wecom import aibot
result = aibot.send_file("/abs/path/report.pdf", chatid="会话id")
```

```python
from pathlib import Path
from wecom import aibot
path = Path(runtimeSpace) / "article.md"
# 若已有成品文件：
result = aibot.send_file(str(path), chatid=chatid)
```

### aibot — 短时收消息

连接 → 收满 `max_count` 条或等到 `timeout_sec` → 断开。适合节点内阻塞等待一次用户回复。

```python
from wecom import aibot
msgs = aibot.collect_messages(timeout_sec=60, max_count=1, auto_reply=False)
result = {
    "count": len(msgs),
    "messages": msgs,
    "last_chatid": aibot.last_chatid(),
}
```

媒体会默认存到渠道目录 `downloads/`；条目里常见字段：`kind`（text/media/voice）、`text`、`target`、`userid`、`chattype`、`saved_path`。

### aibot — 查最近会话

```python
from wecom import aibot
result = {"chatid": aibot.last_chatid()}
```

---

## 决策提示（编排时）

| 用户意图 | 优先调用 |
|----------|----------|
| 群里弹一条通知即可 | `webhook.send_*` |
| 推送给指定群/人，或要 markdown 更丰富 | `aibot.send_markdown` |
| 推送 PDF/图片等附件 | `aibot.send_file` |
| 等人 @ 机器人说一句话再继续 | `aibot.collect_messages` |
| 只要 Webhook、没有 BotID | 不要调用 `aibot` |

## 禁止

- 把 Bot Secret / Webhook key 写进流程节点明文（应用环境变量）
- 用 Webhook API 假装能「接收」群消息
- 在动态代码里跑无限常驻循环（长驻用 CLI `python -m wecom.daemon`，不是节点）
- 群发刷屏触发限流后仍死循环重试
