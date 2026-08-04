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
from src.flowgame.robot_channel.bind_context import (
    apply_decision_result,
    enrich_robot_variables,
    ensure_team_topic,
    flatten_team_result,
    robot_wecom_env,
    team_reply_fallback,
)
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


def execute_team_local(
    robot: SessionRobot,
    variables: Dict[str, Any],
    *,
    team_key: str = "",
) -> Dict[str, Any]:
    """进程内执行 AgentTeam，并把结果摊成可映射字典。"""
    from src.flowgame.team.models import FlowAgentConfig
    from src.flowgame.team.runtime import TeamRuntime, TeamRuntimeError
    from src.flowgame.team import store as team_store

    key = (team_key or robot.teamKey or "").strip()
    if not key:
        raise RobotRuntimeError("bindType=team 但 teamKey 为空")
    team = team_store.get_team(key)
    if not team:
        raise RobotRuntimeError(f"AgentTeam 不存在: {key}")

    agents: Dict[str, FlowAgentConfig] = {}
    try:
        for a in team_store.list_agents():
            agents[a.agentKey] = a
    except Exception:  # noqa: BLE001
        logger.debug("list_agents failed", exc_info=True)

    agent_keys = [m.agentKey for m in team.members]
    if team.supervisorAgentKey:
        agent_keys.append(team.supervisorAgentKey)
    for agent_key in agent_keys:
        if agent_key and agent_key not in agents:
            agents[agent_key] = FlowAgentConfig(
                agentKey=agent_key,
                methodKey=agent_key,
                name=agent_key,
                published=True,
            )

    try:
        with robot_wecom_env(robot, variables):
            result = TeamRuntime(team, agents).run(variables)
    except TeamRuntimeError as exc:
        raise RobotRuntimeError(str(exc)) from exc
    return flatten_team_result(result)


def _robot_ready_for_listen(robot: SessionRobot) -> bool:
    return bool(
        robot.desiredStatus == "running"
        and robot.botId
        and robot.secret
        and robot.is_bound()
    )

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
        if not robot.is_bound():
            raise RobotRuntimeError(
                "请先绑定数字员工（或其决策/任务目标），或兼容旧配置绑定流程/Team"
            )

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
                await asyncio.to_thread(self._stop.wait, heartbeat_sec)

        async def _outbound_pump() -> None:
            """消费 Redis 出站队列，用当前长连接发送（供流程内 aibot via=worker）。"""
            from pathlib import Path

            from src.flowgame.robot_channel.outbound import (
                pop_outbound_task,
                set_outbound_result,
            )
            from wecom.aibot import guess_media_type

            while not self._stop.is_set():
                try:
                    task = await asyncio.to_thread(
                        pop_outbound_task, self.robot_id, timeout_sec=1
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("outbound pop failed", exc_info=True)
                    await asyncio.sleep(0.5)
                    continue
                if not task:
                    continue
                req_id = str(task.get("reqId") or "")
                chatid = str(task.get("chatid") or "").strip()
                msgtype = str(task.get("msgtype") or "markdown").strip()
                result: Dict[str, Any] = {"ok": False, "reqId": req_id, "via": "worker"}
                try:
                    async with handling:
                        if msgtype == "markdown":
                            content = str(task.get("content") or "")
                            send_ret = await client.send_message(
                                chatid,
                                {
                                    "msgtype": "markdown",
                                    "markdown": {"content": content},
                                },
                            )
                            result = {
                                "ok": True,
                                "reqId": req_id,
                                "via": "worker",
                                "chatid": chatid,
                                "result": send_ret,
                            }
                        elif msgtype in {"file", "image", "video", "voice"}:
                            path = Path(str(task.get("filePath") or "")).expanduser()
                            if not path.is_file():
                                raise FileNotFoundError(f"文件不存在: {path}")
                            data = path.read_bytes()
                            mtype = str(task.get("mediaType") or "") or guess_media_type(
                                path
                            )
                            uploaded = await client.upload_media(
                                data, type=mtype, filename=path.name
                            )
                            send_ret = await client.send_media_message(
                                chatid, mtype, uploaded["media_id"]
                            )
                            result = {
                                "ok": True,
                                "reqId": req_id,
                                "via": "worker",
                                "chatid": chatid,
                                "type": mtype,
                                "upload": uploaded,
                                "send": send_ret,
                            }
                        else:
                            raise ValueError(f"不支持的出站 msgtype: {msgtype}")
                    logger.info(
                        "机器人 %s Worker 出站成功 reqId=%s type=%s",
                        self.robot_id,
                        req_id,
                        msgtype,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "机器人 %s Worker 出站失败 reqId=%s", self.robot_id, req_id
                    )
                    result = {
                        "ok": False,
                        "reqId": req_id,
                        "via": "worker",
                        "error": str(exc),
                    }
                if req_id:
                    try:
                        set_outbound_result(req_id, result)
                    except Exception:  # noqa: BLE001
                        logger.debug("set_outbound_result failed", exc_info=True)

        hb_task = asyncio.create_task(_heartbeat())
        out_task = asyncio.create_task(_outbound_pump())
        try:
            await asyncio.to_thread(self._stop.wait)
        finally:
            hb_task.cancel()
            out_task.cancel()
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
        if not robot or not robot.is_bound():
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

        from src.flowgame.digital_employee.binding import (
            BindingResolveError,
            resolve_binding_for_message,
        )

        try:
            binding = resolve_binding_for_message(robot, text or "")
        except BindingResolveError as exc:
            logger.error("机器人 %s 绑定解析失败: %s", robot.robotId, exc)
            return
        if not binding.is_task_bound():
            logger.error(
                "机器人 %s 数字员工 %s 未绑定任务目标",
                robot.robotId,
                binding.employeeId or "（无）",
            )
            return

        enrich_robot_variables(robot, variables, meta=meta, binding=binding)

        task_desc = (
            f"Team {binding.teamKey}"
            if binding.bindType == "team"
            else f"流程 {binding.methodKey}"
        )
        logger.info(
            "机器人 %s 路由员工=%s(%s) source=%s → 决策=%s 任务=%s | %s",
            robot.robotId,
            binding.employeeId or "（legacy）",
            binding.employeeName or "",
            binding.source,
            binding.decisionMethodKey or "（无）",
            task_desc,
            (text or "")[:120],
        )

        try:
            # 1) 可选决策流程：判断是否执行任务、补齐入参、可选直接回复
            if binding.has_decision_flow():
                decision_raw = await asyncio.to_thread(
                    execute_flow_http,
                    binding.decisionMethodKey,
                    variables,
                    timeout_sec=binding.resolve_execute_timeout_sec(
                        robot.executeTimeoutSec
                    ),
                )
                decision = apply_decision_result(variables, decision_raw)
                logger.info(
                    "机器人 %s 决策 shouldRun=%s reason=%s",
                    robot.robotId,
                    decision.get("shouldRun"),
                    (decision.get("reason") or "")[:80],
                )
                # 无论是否跑任务：决策结果先按输出映射回发（有文案则回）
                await self._reply_from_result(
                    client,
                    frame,
                    decision_raw,
                    robot=robot,
                    generate_req_id_fn=generate_req_id_fn,
                    allow_team_fallback=False,
                    empty_log=(
                        "决策跳过任务且输出映射无回发内容，静默结束"
                        if not decision.get("shouldRun")
                        else "决策通过且输出映射无即时回发，继续任务目标"
                    ),
                )
                if not decision.get("shouldRun"):
                    return

            # 2) 任务目标：flow / AgentTeam
            timeout_sec = binding.resolve_execute_timeout_sec(robot.executeTimeoutSec)
            if binding.bindType == "team":
                ensure_team_topic(variables, inbound_text=text or "")
                result = await asyncio.to_thread(
                    execute_team_local,
                    robot,
                    variables,
                    team_key=binding.teamKey,
                )
            else:
                result = await asyncio.to_thread(
                    execute_flow_http,
                    binding.methodKey,
                    variables,
                    timeout_sec=timeout_sec,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("机器人 %s 执行失败（%s）", robot.robotId, task_desc)
            try:
                stream_id = generate_req_id_fn("stream")
                await client.reply_stream(
                    frame, stream_id, f"执行失败：{exc}", True
                )
            except Exception:  # noqa: BLE001
                logger.debug("error reply failed", exc_info=True)
            return

        await self._reply_from_result(
            client,
            frame,
            result,
            robot=robot,
            generate_req_id_fn=generate_req_id_fn,
            allow_team_fallback=(binding.bindType == "team"),
            empty_log="无回发内容，跳过回复",
        )

    async def _reply_from_result(
        self,
        client: Any,
        frame: dict,
        result: Any,
        *,
        robot: SessionRobot,
        generate_req_id_fn,
        allow_team_fallback: bool = False,
        empty_log: str = "无回发内容，跳过回复",
    ) -> None:
        """按机器人 outputMapping 从执行结果映射并回发（决策跳过 / 任务结束共用）。"""
        actions = apply_output_mapping(result, robot.outputMapping)
        if allow_team_fallback:
            reply = actions.get("reply_markdown") or actions.get("reply_text")
            if not reply:
                fallback = team_reply_fallback(
                    result if isinstance(result, dict) else {}
                )
                if fallback:
                    actions["reply_markdown"] = fallback

        reply = actions.get("reply_markdown") or actions.get("reply_text")
        files = actions.get("reply_file") or []
        if not isinstance(files, list):
            files = []

        if not reply and not files:
            logger.info("机器人 %s %s", robot.robotId, empty_log)
            return

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
            if _robot_ready_for_listen(r)
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
        if not robot.is_bound():
            raise RobotRuntimeError(
                "请先绑定数字员工（并配置其任务目标），或兼容旧配置绑定流程/Team 再启动"
            )
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
