# 小红书媒体渠道（FlowGame）

把小红书自动化能力接到 FlowGame：**动态代码**节点里用 Python 调用 `scripts` 包（搜索、读笔记、互动、发布等）。

> 给大模型用的完整调用约定与示例代码在 **[skill.md](./skill.md)**，请不要把本 README 当 Prompt 塞给模型。

---

## 你能做什么

| 能力 | 模块 |
|------|------|
| 扫码登录 / 检查登录 | `scripts.login` |
| 搜索笔记 | `scripts.search` |
| 笔记详情（含评论） | `scripts.feed` |
| 首页推荐流 | `scripts.explore` |
| 用户主页 | `scripts.user` |
| 评论 / 回复 | `scripts.comment` |
| 点赞 / 收藏 | `scripts.interact` |
| 发图文 / 视频 / Markdown / 长文 | `scripts.publish` |
| 写作模板、运营策略、SOP | `scripts.templates` / `strategy` / `sop` |

实现基于 Playwright，数据多来自页面 `window.__INITIAL_STATE__`。

---

## 环境准备

在 `flowgame_python` 环境中：

```bash
pip install -r requirements.txt   # 已含 playwright；另有 markdown、Pygments
playwright install chromium
# Linux 无桌面环境可能还需要：
# playwright install-deps chromium
```

### 第一次登录

需要能弹出浏览器（本机 GUI），或把二维码图片发出去扫：

```bash
cd src/flowgame/media_channel/xiaohongshu
python -m scripts qrcode --headless=false
python -m scripts check-login
```

登录态默认保存在：

- `~/.xiaohongshu/cookies.json`
- `~/.xiaohongshu/browser-data/`

多账号可用 profile（见 `scripts/profiles.py`）。

---

## 在编辑器里怎么用

1. 流程里加 **动态代码** 节点  
2. 引擎选 **Python**，代码用 **多行**（不要只写单行表达式）  
3. `import` 后调用 API，最后把结果赋给 **`result`**  

最短例子：

```python
from scripts import feed

detail = feed.feed_detail(
    feed_id="笔记id",
    xsec_token="搜索结果里的token",
    load_comments=True,
    max_comments=20,
    headless=True,
)
result = detail
```

检查登录 + 未登录时返回二维码相对路径（`src/flowgame/.../qrcode.png`）：

```python
from scripts import login

ok, username = login.check_login()
if ok:
    result = {"logged_in": True, "username": username}
else:
    info = login.get_qrcode(headless=True)
    result = {
        "logged_in": False,
        "qrcode_rel": info["qrcode_rel"],   # 如 src/flowgame/media_channel/xiaohongshu/data/qrcode.png
        "qrcode_path": info["qrcode_path"], # 绝对路径
    }
```

后端执行动态代码时会自动把本目录加入 `sys.path`，因此 `from scripts import …` 可用。

AgentTeam 跑任务时，黑板里会有 `runtimeSpace`（本次运行目录绝对路径），可以把搜索结果 / 草稿写到该目录再给下游用。

---

## 安全与风控（请人工把关）

这些操作会**真实改账号数据**，上线流程前务必确认文案与目标：

- 发布笔记  
- 发评论 / 回复  
- 点赞 / 收藏  

另外：

- 频繁操作容易触发验证码或限流，不要关内置间隔  
- `xsec_token` 跟会话绑定，请用**最新搜索结果**里的  
- Cookie 会过期，`check-login` 失败就重新扫码  
- 本工具仅供学习研究，勿滥用

---

## 目录说明

```text
xiaohongshu/
├── README.md      ← 你正在看的（给人）
├── skill.md       ← 给大模型的操作契约与全量示例
├── __init__.py    ← 注册 scripts 的 import 路径
└── scripts/       ← 核心实现（来自 xiaohongshu-skill / redbook）
```

---

## 来源与维护

- 代码拷贝自测试项目 `redbook`（xiaohongshu-skill）  
- 升级上游时：同步覆盖 `scripts/`，并核对本 README / skill.md 是否仍匹配公开 API  
- 联调问题优先查：Chromium 是否安装、是否已登录、动态代码是否多行且赋了 `result`
