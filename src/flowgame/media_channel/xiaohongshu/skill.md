---
name: flowgame-xiaohongshu
description: >
  FlowGame 动态代码节点调用小红书（Xiaohongshu / RedNote）能力。
  当用户或编排需要：搜索笔记、读详情、推荐流、用户主页、评论、点赞收藏、发图文/视频/Markdown/长文、
  写作模板、运营策略、SOP、检查登录时使用本 skill。
  在动态代码中写 Python 多行，from scripts import …，最终赋值给 result。
  发布/评论/点赞/收藏属于写操作，必须先得到用户明确确认再执行。
---

# 小红书 Skill（给大模型）

## 硬约束

1. 只通过 FlowGame **动态代码**节点调用；引擎=**Python**；代码=**多行**；输出变量名必须是 **`result`**。
2. 允许：`from scripts import login, search, feed, explore, user, comment, interact, publish, templates, strategy, sop`。
3. **写操作**（publish_* / post_comment / reply_* / like / unlike / collect / uncollect / 会改号的 SOP）执行前必须已获得用户确认；未确认则只生成草稿或说明，不要调用写 API。
4. 需要 `feed_id` + `xsec_token` 时，token 必须来自**同一次**搜索/推荐结果，禁止臆造。
5. 默认 `headless=True`；扫码登录用 `login.login(headless=False)`。
6. 若上下文有黑板变量 `runtimeSpace`，中间产物优先写入该目录。
7. 登录态路径默认 `~/.xiaohongshu/`；Cookie 失效则提示用户重新扫码，不要死循环重试写操作。
8. 触发验证码 / `CaptchaError`：停止写操作，提示降速或有界面重新登录。

## 调用环境（已由后端注入）

- `sys.path` 已含 `media_channel/xiaohongshu`，故 `from scripts import feed` 可用。
- 依赖：`playwright`（需已 `playwright install chromium`）、发布 Markdown 时需要 `markdown` / `Pygments`。

---

## API 速查与可粘贴代码

以下每段都是完整动态代码模板；按需改参数后整段使用。

### login — 登录

`check_login()` 只返回是否登录，**不含二维码图**。需要图片路径用 `get_qrcode()`。

```python
from scripts import login
ok, username = login.check_login()
result = {"logged_in": bool(ok), "username": username}
```

未登录时取二维码（相对路径形如 `src/flowgame/media_channel/xiaohongshu/data/qrcode.png`）：

```python
from scripts import login

ok, username = login.check_login()
if ok:
    result = {"logged_in": True, "username": username, "qrcode_rel": None}
else:
    info = login.get_qrcode(headless=True)
    # 也可拷到本次 Team 目录：
    # info = login.get_qrcode(headless=True, copy_to=str(Path(runtimeSpace) / "qrcode.png"))
    result = {
        "logged_in": False,
        "username": None,
        "qrcode_path": info.get("qrcode_path"),   # 绝对路径
        "qrcode_rel": info.get("qrcode_rel"),     # 相对仓库根，如 src/flowgame/.../qrcode.png
        "message": info.get("message"),
    }
```

阻塞等待扫码（会等到超时或成功；结果里也带 `qrcode_rel`）：

```python
from scripts import login
ok = login.login(headless=False, timeout=120)
result = ok  # dict: status / qrcode_path / qrcode_rel / username / message
```

```python
from scripts import login
login.logout()
result = {"ok": True}
```

### search — 搜索

参数枚举：
- `sort_by`: 综合 | 最新 | 最多点赞 | 最多评论 | 最多收藏
- `note_type`: 不限 | 视频 | 图文
- `publish_time`: 不限 | 一天内 | 一周内 | 半年内
- `search_scope`: 不限 | 已看过 | 未看过 | 已关注
- `location`: 不限 | 同城 | 附近

返回列表元素通常含：`id`, `xsec_token`, `title`, `type`, `user`, `user_id`, `liked_count`, `collected_count`, `comment_count`。

```python
from scripts import search
items = search.search(
    keyword="关键词",
    sort_by="最新",
    note_type="图文",
    publish_time="一周内",
    search_scope="不限",
    location="不限",
    limit=10,
    headless=True,
) or []
result = {"count": len(items), "items": items}
```

### feed — 笔记详情

```python
from scripts import feed
detail = feed.feed_detail(
    feed_id="笔记id",
    xsec_token="搜索结果里的token",
    load_comments=True,
    max_comments=20,
    xsec_source="pc_feed",
    headless=True,
)
result = detail
```

搜索后取第一条详情：

```python
from scripts import search, feed
items = search.search(keyword="美食探店", limit=5, headless=True) or []
if not items:
    result = {"error": "无搜索结果"}
else:
    first = items[0]
    detail = feed.feed_detail(
        feed_id=first["id"],
        xsec_token=first["xsec_token"],
        load_comments=True,
        max_comments=20,
        headless=True,
    )
    result = {"search_hit": first, "detail": detail}
```

写入 runtimeSpace：

```python
from pathlib import Path
import json
from scripts import feed
detail = feed.feed_detail(feed_id=feed_id, xsec_token=xsec_token, load_comments=True, max_comments=30, headless=True)
out = Path(runtimeSpace) / f"feed_{feed_id}.json"
out.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
result = {"path": str(out), "detail": detail}
```

### explore — 推荐流

```python
from scripts import explore
feeds = explore.explore(limit=20, headless=True) or []
result = {"count": len(feeds), "feeds": feeds}
```

### user — 用户

```python
from scripts import user
result = user.user_profile(user_id="用户id", xsec_token="可选token", headless=True)
```

```python
from scripts import user
result = user.my_profile(headless=True)
```

### comment — 评论（写 · 须确认）

```python
from scripts import comment
result = comment.post_comment(feed_id="笔记id", xsec_token="token", content="好棒的笔记！", headless=True)
```

```python
from scripts import comment
result = comment.reply_to_comment(
    feed_id="笔记id", xsec_token="token",
    comment_id="评论id", reply_user_id="用户id",
    content="感谢分享", headless=True,
)
```

```python
from scripts import comment
result = comment.reply_via_notification(content="谢谢关注", notification_index=0, headless=True)
```

### interact — 点赞收藏（写 · 须确认）

```python
from scripts import interact
result = {
    "like": interact.like(feed_id="笔记id", xsec_token="token", headless=True),
    "unlike": interact.unlike(feed_id="笔记id", xsec_token="token", headless=True),
    "collect": interact.collect(feed_id="笔记id", xsec_token="token", headless=True),
    "uncollect": interact.uncollect(feed_id="笔记id", xsec_token="token", headless=True),
}
```

### publish — 发布（写 · 须确认）

`auto_publish=False` 时通常停在发布按钮；确认后才可 `True`。

```python
from scripts import publish
result = publish.publish_image(
    title="标题",
    content="正文",
    image_paths=["/abs/a.jpg", "/abs/b.jpg"],
    tags=["旅行", "美食"],
    schedule_time=None,
    auto_publish=False,
    headless=True,
)
```

```python
from scripts import publish
result = publish.publish_video(
    title="标题", content="描述", video_path="/abs/v.mp4",
    tags=["vlog"], auto_publish=False, headless=True,
)
```

```python
from scripts import publish
result = publish.publish_markdown(
    title="干货",
    markdown_text="# 标题\n- 要点",
    extra_content="欢迎关注",
    tags=["干货"],
    auto_publish=False,
    image_width=1080,
    headless=True,
)
```

```python
from pathlib import Path
from scripts import publish
paths = publish.md_to_images(
    markdown_text="# Hello\n内容",
    output_dir=str(Path(runtimeSpace) / "md_images"),
    width=1080,
)
result = {"images": paths}
```

```python
from scripts import publish
result = publish.publish_longform(title="长文标题", content="长文正文", auto_publish=False, headless=True)
```

### templates — 写作模板

```python
from scripts import templates
result = templates.generate_template(topic="旅行攻略", note_type="图文")
```

### strategy — 策略 / 配额

```python
from scripts import strategy
strategy.init_strategy(
    persona="旅行博主",
    target_audience="18-35岁旅行爱好者",
    content_direction="旅行攻略,小众目的地",
)
result = {
    "strategy": strategy.show_strategy(),
    "limit": strategy.check_daily_limit(action_type="likes"),
    "upcoming": strategy.get_upcoming_posts(days=7),
}
```

```python
from scripts import strategy
strategy.record_action(action_type="likes")
strategy.add_scheduled_post(date="2026-08-01", topic="春日出行", note_type="图文", notes="")
result = {"ok": True}
```

### sop — 编排（含写操作的须确认）

```python
from scripts import sop
result = sop.run_publish_sop(topic="旅行攻略", note_type="图文", auto_publish=False)
```

```python
from scripts import sop
result = sop.run_explore_sop(
    feed_count=10, like_probability=0.3, collect_probability=0.1, comment_probability=0.0,
)
```

```python
from scripts import sop
result = sop.run_comment_sop(
    replies=[{"feed_id": "abc", "xsec_token": "xyz", "content": "好棒"}],
    cooldown_min=3, cooldown_max=8,
)
```

### client — 高级

```python
from scripts.client import create_client
client = create_client(headless=True)
try:
    client.start()
    result = {"ok": True}
finally:
    client.close()
```

---

## 决策提示（编排时）

| 用户意图 | 优先调用 |
|----------|----------|
| 有没有登录 | `login.check_login` |
| 找笔记 / 关键词 | `search.search` |
| 看某篇内容/评论 | `feed.feed_detail`（带搜索得到的 token） |
| 刷首页 | `explore.explore` |
| 看某人 / 看自己 | `user.user_profile` / `user.my_profile` |
| 想互动但未确认 | 只返回拟操作摘要，等确认 |
| 已确认互动 | `comment.*` / `interact.*` |
| 已确认发布 | `publish.*` 且审慎使用 `auto_publish` |
| 要运营节奏 | `strategy.*` / `sop.*` |

## 页面数据路径（排障）

| 数据 | `__INITIAL_STATE__` |
|------|---------------------|
| 搜索 | `.search.feeds` |
| 详情 | `.note.noteDetailMap` |
| 用户 | `.user.userPageData` / `.user.notes` |
| 推荐 | `.feed.feeds` |

## 禁止

- 在未确认时执行写操作  
- 伪造 `xsec_token` / `feed_id`  
- 忽略验证码继续刷写接口  
- 把本 skill 的约束说成「可以自动随便发帖」
