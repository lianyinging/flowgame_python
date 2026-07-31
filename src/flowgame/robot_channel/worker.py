"""独立会话机器人 Worker 进程。

由 ``run.py`` 自动拉起，也可单独运行::

    python -m src.flowgame.robot_channel.worker
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

# 保证从任意 cwd 可导入
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.flowgame.settings import load_flowgame_dotenv

load_flowgame_dotenv()

logging.basicConfig(
    level=os.getenv("FLOWGAME_ROBOT_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("flowgame.robot_worker")


def main() -> int:
    from src.flowgame.robot_channel import store as robot_store
    from src.flowgame.robot_channel.runtime import RobotSupervisor, worker_owner_id

    poll_sec = float(os.getenv("FLOWGAME_ROBOT_POLL_SEC", "2"))
    presence_ttl = int(os.getenv("FLOWGAME_ROBOT_PRESENCE_TTL_SEC", "30"))
    owner = worker_owner_id()
    supervisor = RobotSupervisor(owner=owner)
    stopping = False

    def _stop(*_args: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    logger.info(
        "Robot Worker 已启动 owner=%s poll=%.1fs api=%s",
        owner,
        poll_sec,
        os.getenv("FLOWGAME_ROBOT_API_BASE") or "(auto)",
    )

    while not stopping:
        try:
            robot_store.touch_worker_presence(owner, ttl_sec=presence_ttl)
            supervisor.reconcile_once()
        except Exception:  # noqa: BLE001
            logger.exception("Worker 循环异常")
        time.sleep(poll_sec)

    logger.info("Robot Worker 正在退出…")
    supervisor.stop_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
