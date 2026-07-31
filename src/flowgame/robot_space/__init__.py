"""会话机器人工作空间。

目录结构::

    robot_space/
      qiyeweixing/          # 渠道（类型）目录，已存在则不重复创建逻辑之外的 mkdir(exist_ok)
        {robotId}/         # 该机器人工作空间

启动机器人时确保渠道目录与 robotId 目录存在；路径可注入流程变量 ``robotSpace``。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

# .../src/flowgame/robot_space
_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parents[2]

# 机器人 type → 渠道文件夹名
CHANNEL_DIR_BY_TYPE = {
    "wecom_aibot": "qiyeweixing",
}

BLACKBOARD_ROBOT_SPACE = "robotSpace"


def get_robot_space_root() -> Path:
    """机器人工作空间根目录。

    环境变量 ``FLOWGAME_ROBOT_SPACE_DIR`` 可覆盖；
    默认：本包目录（``src/flowgame/robot_space``）。
    """
    raw = (os.getenv("FLOWGAME_ROBOT_SPACE_DIR") or "").strip()
    if raw:
        root = Path(raw).expanduser()
        if not root.is_absolute():
            root = (_REPO_ROOT / root).resolve()
        else:
            root = root.resolve()
    else:
        root = _PACKAGE_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_channel_name(robot_type: str) -> str:
    key = (robot_type or "").strip()
    if key in CHANNEL_DIR_BY_TYPE:
        return CHANNEL_DIR_BY_TYPE[key]
    # 未知类型：用安全化后的 type 名
    return _safe_segment(key or "unknown")


def _safe_segment(text: str, max_len: int = 64) -> str:
    s = re.sub(r"[^\w\-]+", "_", (text or "").strip(), flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s or "robot")[:max_len]


def ensure_channel_dir(robot_type: str) -> Path:
    """确保渠道目录存在（已存在则直接返回）。"""
    channel = resolve_channel_name(robot_type)
    path = get_robot_space_root() / channel
    if not path.is_dir():
        path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_robot_workspace(
    robot_id: str,
    robot_type: str = "wecom_aibot",
) -> Path:
    """启动机器人时调用：确保 ``robot_space/{渠道}/{robotId}/`` 存在。

    - 渠道目录已存在则不「重建」，仅 ``mkdir(exist_ok=True)``
    - 始终确保该 robotId 工作目录存在

    Returns:
        机器人工作空间绝对路径
    """
    raw_id = (robot_id or "").strip()
    if not raw_id:
        raise ValueError("robotId 不能为空")
    rid = _safe_segment(raw_id, max_len=80)
    # 极端情况下 sanitize 后为空，回退用原 id 的哈希片段，避免静默失败
    if not rid or rid == "robot":
        import hashlib

        rid = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:12]

    channel_dir = ensure_channel_dir(robot_type)
    workspace = channel_dir / rid
    workspace.mkdir(parents=True, exist_ok=True)
    marker = workspace / ".robot_workspace"
    if not marker.exists():
        marker.write_text(
            f"robotId={raw_id}\n"
            f"channel={resolve_channel_name(robot_type)}\n"
            f"path={workspace.resolve()}\n",
            encoding="utf-8",
        )
    return workspace.resolve()


def get_robot_workspace(
    robot_id: str,
    robot_type: str = "wecom_aibot",
    *,
    create: bool = False,
) -> Optional[Path]:
    """查询工作空间路径；``create=True`` 时等价于 ``ensure_robot_workspace``。"""
    if create:
        return ensure_robot_workspace(robot_id, robot_type)
    rid = _safe_segment((robot_id or "").strip(), max_len=80)
    path = get_robot_space_root() / resolve_channel_name(robot_type) / rid
    if path.is_dir():
        return path.resolve()
    return None
