"""会话机器人连接运行时（仅由独立 Robot Worker 进程使用）。"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
import time
from typing import Any, Dict, Optional

import requests

from src.flowgame.constants import API_PREFIX
from src.flowgame.robot_channel import store as robot_store
from src.flowgame.robot_channel.mapping import apply_input_mapping, apply_output_mapping
from src.flowgame.robot_channel.models import SessionRobot, default_execute_timeout_sec
from src.flowgame.robot_channel.qiyeweixing import ensure_wecom_import_path
from src.flowgame.robot_channel.qiyeweixing._compat import ensure_typing_not_required

logger = logging.getLogger("flowgame.session_robot")


class RobotRuntimeError(RuntimeError):
    pass


def worker_owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def resolve_execute_url() -> str:
    base = (os.getenv("FLOWGAME_ROBOT_API_BASE") or "").strip().rstrip("/")
    if not base:
        host = os.getenv("FLOWGAME_HOST", "127.0.0.1")
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        port = os.getenv("FLOWGAME_PORT", "8001")
        base = f"http://{host}:{port}"
    return f"{base}{API_PREFIX}/execute"


def execute_flow_http(
    method_key: str,
    variables: Dict[str, Any],
    *,
    timeout_sec: Optional[float] = None,
) -> Any:
    url = resolve_execute_url()
    if timeout_sec is not None and float(timeout_sec) > 0:
        timeout = float(timeout_sec)
    else:
        timeout = float(default_execute_timeout_sec())
    resp = requests.post(
        url,
        json={"methodKey": method_key, "variables": variables},
        timeout=timeout,
    )
    if resp.status_code >= 400:
        detail = resp.text[:500]
        try:
            detail = str(resp.json().get("detail") or resp.json().get("msg") or detail)
        except Exception:  # noqa: BLE001
            pass
        raise RobotRuntimeError(f"execute HTTP {resp.status_code}: {detail}")
    body = resp.json()
    if isinstance(body, dict) and "data" in body:
        return body.get("data")
    return body


class _RobotConnection:
    """单个企微机器人的 WebSocket 连接（跑在独立线程+事件循环）。"""

    def __init__(self, robot_id: str, owner: str) -> None:
        self.robot_id = robot_id
        self.owner = owner
        # 必须用 threading.Event：asyncio.Event 在主线程创建会绑错 loop，
        # 导致 _main 里 wait 立刻结束 → Worker 每 2s 重拉、日志刷屏、状态卡住。
        self._stop = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._error = ""

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start_background(self) -> None:
        if self.alive:
            return
        self._stop.clear()
        self._error = ""

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                loop.run_until_complete(self._main())
            except Exception as exc:  # noqa: BLE001
                self._error = str(exc)
                logger.exception("机器人 %s 运行异常", self.robot_id)
                try:
                    robot_store.update_runtime(
                        self.robot_id,
                        runtime_status="error",
                        runtime_message=str(exc),
                        runtime_owner=self.owner,
                    )
                except Exception:  # noqa: BLE001
                    pass
            finally:
                try:
                    loop.close()
                except Exception:  # noqa: BLE001
                    pass
                self._loop = None

        self._thread = threading.Thread(
            target=_run,
            name=f"session-robot-{self.robot_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 8.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    async def _main(self) -> None:
        ensure_typing_not_required()
        ensure_wecom_import_path()
        from wecom_aibot_sdk import WSClient, generate_req_id
        from wecom.aibot import extract_meta, extract_text

        robot = robot_store.get_robot(self.robot_id, include_secret=True)
        if not robot:
            raise RobotRuntimeError("机器人不存在")
        if robot.type != "wecom_aibot":
            raise RobotRuntimeError(f"不支持的类型: {robot.type}")
        if not robot.methodKey:
            raise RobotRuntimeError("请先绑定流程 methodKey")

        from src.flowgame.robot_space import ensure_robot_workspace

        workspace = ensure_robot_workspace(robot.robotId, robot.type)
        logger.info("机器人 %s 工作空间: %s", robot.robotId, workspace)

        robot_store.update_runtime(
            self.robot_id,
            runtime_status="connecting",
            runtime_message="正在连接企微…",
            runtime_owner=self.owner,
        )

        client = WSClient(bot_id=robot.botId, secret=robot.secret)
        handling = asyncio.Lock()

        async def handle_inbound(frame: dict, *, kind: str) -> None:
            async with handling:
                await self._handle_message(
                    client,
                    frame,
                    kind=kind,
                    extract_text_fn=extract_text,
                    extract_meta_fn=extract_meta,
                    generate_req_id_fn=generate_req_id,
                )

        async def on_text(frame: dict) -> None:
            await handle_inbound(frame, kind="text")

        async def on_voice(frame: dict) -> None:
            await handle_inbound(frame, kind="voice")

        client.on("connected", lambda: logger.info("机器人 %s WS 已连接", self.robot_id))
        client.on(
            "authenticated",
            lambda: logger.info("机器人 %s 认证成功", self.robot_id),
        )
        client.on(
            "disconnected",
            lambda reason: logger.warning("机器人 %s 断开: %s", self.robot_id, reason),
        )
        client.on("error", lambda err: logger.error("机器人 %s 错误: %s", self.robot_id, err))
        client.on("message.text", on_text)
        client.on("message.voice", on_voice)

        await client.connect()
        robot_store.update_runtime(
            self.robot_id,
            runtime_status="running",
            runtime_message="",
            runtime_owner=self.owner,
        )

        heartbeat_sec = float(os.getenv("FLOWGAME_ROBOT_HEARTBEAT_SEC", "10"))

        async def _heartbeat() -> None:
            while not self._stop.is_set():
                try:
                    robot_store.update_runtime(
                        self.robot_id,
                        runtime_status="running",
                        runtime_message="",
                        runtime_owner=self.owner,
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("heartbeat failed", exc_info=True)
                # threading.Event.wait 放到线程池，避免阻塞事件循环
                await asyncio.to_thread(self._stop.wait, heartbeat_sec)

        hb_task = asyncio.create_task(_heartbeat())
        try:
            await asyncio.to_thread(self._stop.wait)
        finally:
            hb_task.cancel()
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                logger.debug("disconnect failed", exc_info=True)
            try:
                cur = robot_store.get_robot(self.robot_id)
                if cur and cur.desiredStatus != "running":
                    robot_store.update_runtime(
                        self.robot_id,
                        runtime_status="stopped",
                        runtime_message="",
                        runtime_owner=self.owner,
                        touch_heartbeat=False,
                    )
            except Exception:  # noqa: BLE001
                pass

    async def _handle_message(
        self,
        client: Any,
        frame: dict,
        *,
        kind: str,
        extract_text_fn,
        extract_meta_fn,
        generate_req_id_fn,
    ) -> None:
        robot = robot_store.get_robot(self.robot_id, include_secret=True)
        if not robot or not robot.methodKey:
            return

        meta = extract_meta_fn(frame)
        if kind == "text":
            text = extract_text_fn(frame)
        else:
            body = frame.get("body") or {}
            voice = body.get("voice") or {}
            text = (voice.get("content") or "").strip()

        inbound: Dict[str, Any] = {"text": text, "kind": kind, **meta}
        variables = apply_input_mapping(inbound, robot.inputMapping)
        variables.setdefault("robotId", robot.robotId)
        variables.setdefault("sessionId", meta.get("target") or meta.get("userid") or "")
        try:
            from src.flowgame.robot_space import ensure_robot_workspace

            variables.setdefault(
                "robotSpace",
                str(ensure_robot_workspace(robot.robotId, robot.type)),
            )
        except Exception:  # noqa: BLE001
            logger.debug("inject robotSpace skipped", exc_info=True)

        logger.info(
            "机器人 %s 收到消息 → 流程 %s | %s",
            robot.robotId,
            robot.methodKey,
            (text or "")[:120],
        )

        try:
            result = await asyncio.to_thread(
                execute_flow_http,
                robot.methodKey,
                variables,
                timeout_sec=robot.executeTimeoutSec,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("机器人 %s 执行流程失败", robot.robotId)
            try:
                stream_id = generate_req_id_fn("stream")
                await client.reply_stream(
                    frame, stream_id, f"流程执行失败：{exc}", True
                )
            except Exception:  # noqa: BLE001
                logger.debug("error reply failed", exc_info=True)
            return

        actions = apply_output_mapping(result, robot.outputMapping)
        reply = actions.get("reply_markdown") or actions.get("reply_text")
        files = actions.get("reply_file") or []
        if not isinstance(files, list):
            files = []

        if not reply and not files:
            logger.info("机器人 %s 流程无回发内容，跳过回复", robot.robotId)
            return

        # 先文后文件
        if reply:
            stream_id = generate_req_id_fn("stream")
            await client.reply_stream(frame, stream_id, str(reply), True)

        if files:
            await self._reply_files(
                client,
                frame,
                files=[str(p) for p in files],
                generate_req_id_fn=generate_req_id_fn,
            )

    async def _reply_files(
        self,
        client: Any,
        frame: dict,
        *,
        files: list[str],
        generate_req_id_fn,
    ) -> None:
        from pathlib import Path

        ensure_typing_not_required()
        ensure_wecom_import_path()
        from wecom.aibot import guess_media_type

        for raw_path in files:
            path = Path(raw_path).expanduser()
            try:
                if not path.is_file():
                    raise FileNotFoundError(f"文件不存在: {path}")
                data = path.read_bytes()
                size_mb = len(data) / (1024 * 1024)
                if size_mb > 50:
                    raise ValueError(f"文件过大（{size_mb:.1f}MB），上限约 50MB")
                mtype = guess_media_type(path)
                uploaded = await client.upload_media(
                    data, type=mtype, filename=path.name
                )
                media_id = uploaded["media_id"]
                await client.reply_media(frame, mtype, media_id)
                logger.info(
                    "机器人 %s 已回发文件 %s type=%s",
                    self.robot_id,
                    path.name,
                    mtype,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("机器人 %s 回发文件失败: %s", self.robot_id, raw_path)
                try:
                    stream_id = generate_req_id_fn("stream")
                    await client.reply_stream(
                        frame,
                        stream_id,
                        f"文件发送失败：{Path(raw_path).name}（{exc}）",
                        True,
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("file error reply failed", exc_info=True)


class RobotSupervisor:
    """按 Redis desiredStatus 拉起/停掉本地连接。"""

    def __init__(self, owner: Optional[str] = None) -> None:
        self.owner = owner or worker_owner_id()
        self._conns: Dict[str, _RobotConnection] = {}
        self._lock = threading.Lock()
        self._last_start_at: Dict[str, float] = {}
        self._restart_backoff_sec = float(
            os.getenv("FLOWGAME_ROBOT_RESTART_BACKOFF_SEC", "5")
        )

    def reconcile_once(self) -> None:
        robots = robot_store.list_robots()
        desired_running = {
            r.robotId
            for r in robots
            if r.desiredStatus == "running" and r.methodKey and r.botId and r.secret
        }

        with self._lock:
            # 停掉不再需要的
            for rid, conn in list(self._conns.items()):
                if rid not in desired_running:
                    conn.stop(timeout=5)
                    self._conns.pop(rid, None)
                    self._last_start_at.pop(rid, None)
                    try:
                        robot_store.update_runtime(
                            rid,
                            runtime_status="stopped",
                            runtime_message="",
                            runtime_owner=self.owner,
                            touch_heartbeat=False,
                        )
                    except Exception:  # noqa: BLE001
                        pass

            # 拉起缺失的
            for rid in desired_running:
                conn = self._conns.get(rid)
                if conn and conn.alive:
                    continue
                now = time.monotonic()
                last = self._last_start_at.get(rid, 0.0)
                if now - last < self._restart_backoff_sec:
                    continue
                if conn:
                    err = conn._error
                    conn.stop(timeout=2)
                    if err:
                        logger.warning(
                            "机器人 %s 监听线程已退出，将重试: %s", rid, err
                        )
                try:
                    from src.flowgame.robot_space import ensure_robot_workspace

                    robot = next((x for x in robots if x.robotId == rid), None)
                    rtype = robot.type if robot else "wecom_aibot"
                    ws = ensure_robot_workspace(rid, rtype)
                    logger.debug("机器人工作空间就绪: %s -> %s", rid, ws)
                except Exception:  # noqa: BLE001
                    logger.exception("创建机器人工作空间失败: %s", rid)
                new_conn = _RobotConnection(rid, self.owner)
                self._conns[rid] = new_conn
                self._last_start_at[rid] = now
                new_conn.start_background()
                logger.info("Worker 拉起机器人监听: %s", rid)

    def stop_all(self) -> None:
        with self._lock:
            for rid, conn in list(self._conns.items()):
                conn.stop(timeout=5)
            self._conns.clear()


# 兼容旧 import 名：API 侧不再持有连接
class SessionRobotManager:
    """API 侧仅改 desiredStatus，真正监听在 Worker。"""

    def start(self, robot_id: str) -> SessionRobot:
        robot = robot_store.get_robot(robot_id, include_secret=True)
        if not robot:
            raise RobotRuntimeError("机器人不存在")
        if robot.type != "wecom_aibot":
            raise RobotRuntimeError(f"暂不支持类型: {robot.type}")
        if not robot.botId or not robot.secret:
            raise RobotRuntimeError("缺少 botId / secret")
        if not robot.methodKey:
            raise RobotRuntimeError("请先绑定流程 methodKey 再启动")
        from src.flowgame.robot_space import ensure_robot_workspace

        ensure_robot_workspace(robot.robotId, robot.type)
        return robot_store.set_desired_status(robot_id, "running")

    def stop(self, robot_id: str) -> SessionRobot:
        robot = robot_store.get_robot(robot_id, include_secret=True)
        if not robot:
            raise RobotRuntimeError("机器人不存在")
        return robot_store.set_desired_status(robot_id, "stopped")

    def is_running(self, robot_id: str) -> bool:
        robot = robot_store.get_robot(robot_id)
        if not robot:
            return False
        return robot.desiredStatus == "running" and robot.runtimeStatus == "running"

    def restore_running(self) -> None:
        """API 进程不再恢复监听（由 Worker 负责）。"""
        return


session_robot_manager = SessionRobotManager()
