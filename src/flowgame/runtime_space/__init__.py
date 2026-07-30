"""AgentTeam 临时运行时工作目录。

每次 Team 启动时在此目录下创建独立子目录，路径写入黑板 `runtimeSpace`，
供子 Agent 落盘工作成果；后续可通过 WebSocket 等通道对外推送。
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

# 本包目录：.../src/flowgame/runtime_space
_PACKAGE_DIR = Path(__file__).resolve().parent
# flowgame_python 仓库根：runtime_space → flowgame → src → 仓库根 用 parents[2]
# Path: .../src/flowgame/runtime_space → parents[2] == .../flowgame_python
_REPO_ROOT = _PACKAGE_DIR.parents[2]

# 黑板键（camelCase，与 menuContent 等一致）
BLACKBOARD_RUNTIME_SPACE = "runtimeSpace"
BLACKBOARD_RUN_ID = "runId"


def get_runtime_space_root() -> Path:
    """运行时空间根目录。

    环境变量 FLOWGAME_RUNTIME_SPACE_DIR 可覆盖；
    默认：本包下的 ``runs/``（不污染源码树其它位置）。
    """
    raw = (os.getenv("FLOWGAME_RUNTIME_SPACE_DIR") or "").strip()
    if raw:
        root = Path(raw).expanduser()
        if not root.is_absolute():
            root = (_REPO_ROOT / root).resolve()
        else:
            root = root.resolve()
    else:
        root = (_PACKAGE_DIR / "runs").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_segment(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^\w\-]+", "_", (text or "").strip(), flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s or "team")[:max_len]


def create_team_runtime_dir(
    team_key: str,
    *,
    run_id: Optional[str] = None,
) -> Tuple[str, Path]:
    """为一次 Team 运行创建独立目录。

    Returns:
        (run_id, absolute_path)
    """
    rid = (run_id or "").strip() or uuid.uuid4().hex[:12]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"{_safe_segment(team_key)}_{stamp}_{rid}"
    path = get_runtime_space_root() / name
    path.mkdir(parents=True, exist_ok=False)
    # 占位说明，方便人工查看
    readme = path / "README.txt"
    readme.write_text(
        f"FlowGame AgentTeam runtime workspace\n"
        f"teamKey={team_key}\n"
        f"runId={rid}\n"
        f"createdAt={datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    return rid, path
