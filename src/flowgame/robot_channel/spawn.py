"""在 run.py / start_server 中自动拉起 Robot Worker 子进程。"""
from __future__ import annotations

import atexit
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("flowgame.robot_spawn")

_PROC: Optional[subprocess.Popen] = None


def _truthy(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def start_embedded_robot_worker(*, api_port: Optional[int] = None) -> Optional[subprocess.Popen]:
    """若启用自动拉起，则启动 ``python -m src.flowgame.robot_channel.worker``。"""
    global _PROC
    if not _truthy("FLOWGAME_ROBOT_AUTOSTART", "true"):
        logger.info("FLOWGAME_ROBOT_AUTOSTART=false，跳过内嵌 Robot Worker")
        return None
    if _PROC and _PROC.poll() is None:
        return _PROC

    root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(root))
    if "PYTHONPATH" in env and str(root) not in env["PYTHONPATH"]:
        env["PYTHONPATH"] = f"{root}{os.pathsep}{env['PYTHONPATH']}"

    port = api_port or int(os.getenv("FLOWGAME_PORT", "8001"))
    host = os.getenv("FLOWGAME_HOST", "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    env.setdefault("FLOWGAME_ROBOT_API_BASE", f"http://{host}:{port}")

    cmd = [sys.executable, "-m", "src.flowgame.robot_channel.worker"]
    logger.info("自动启动 Robot Worker: %s", " ".join(cmd))
    _PROC = subprocess.Popen(
        cmd,
        cwd=str(root),
        env=env,
        stdout=None,
        stderr=None,
    )
    atexit.register(stop_embedded_robot_worker)
    return _PROC


def stop_embedded_robot_worker() -> None:
    global _PROC
    proc = _PROC
    _PROC = None
    if not proc or proc.poll() is not None:
        return
    logger.info("停止 Robot Worker pid=%s", proc.pid)
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
