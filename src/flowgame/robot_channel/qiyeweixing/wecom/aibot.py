"""企业微信智能机器人（WebSocket / wecom-aibot-sdk）。

能力：
  - 主动发送 markdown 文本
  - 上传并发送 image / file / voice / video
  - 短时监听并收集入站消息（适合动态代码节点）
  - 下载单聊发来的 image / file / video 到 downloads/

官方限制：image / file / video / voice 回调目前主要支持「单聊」。
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

_qiye_root = str(Path(__file__).resolve().parents[1])
if _qiye_root not in sys.path:
    sys.path.insert(0, _qiye_root)

from _compat import ensure_typing_not_required

ensure_typing_not_required()

from wecom_aibot_sdk import WSClient, generate_req_id
from wecom_aibot_sdk.types import WeComMediaType

from ._util import (
    DOWNLOAD_DIR,
    ENV_ROBOT_ID,
    load_last_chatid,
    resolve_bot_creds,
    resolve_chatid,
    run_async,
    save_last_chatid,
)

logger = logging.getLogger("flowgame.wecom.aibot")


def extract_text(frame: dict) -> str:
    body = frame.get("body") or {}
    text = body.get("text") or {}
    return (text.get("content") or "").strip()


def extract_meta(frame: dict) -> dict[str, Any]:
    body = frame.get("body") or {}
    sender = body.get("from") or {}
    chattype = body.get("chattype")
    chatid = body.get("chatid") or ""
    userid = (sender.get("userid") or "").strip()
    target = chatid if chattype == "group" else userid
    return {
        "msgtype": body.get("msgtype"),
        "chattype": chattype,
        "chatid": chatid,
        "userid": userid,
        "target": target,
        "msgid": body.get("msgid"),
        "aibotid": body.get("aibotid"),
    }


def guess_media_type(path: Path) -> WeComMediaType:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}:
        return "image"
    if suffix in {".amr"}:
        return "voice"
    if suffix in {".mp4"}:
        return "video"
    return "file"


async def _wait_authenticated(client: WSClient, timeout: float = 10) -> bool:
    import asyncio

    authenticated = asyncio.Event()
    client.on("authenticated", lambda: authenticated.set())
    try:
        await asyncio.wait_for(authenticated.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logger.error("企业微信智能机器人认证超时")
        return False


async def _send_markdown_async(
    chatid: str,
    content: str,
    *,
    bot_id: str,
    secret: str,
) -> dict[str, Any]:
    client = WSClient(bot_id=bot_id, secret=secret)
    await client.connect()
    try:
        if not await _wait_authenticated(client):
            raise TimeoutError("企业微信智能机器人认证超时")
        result = await client.send_message(
            chatid,
            {"msgtype": "markdown", "markdown": {"content": content}},
        )
        save_last_chatid(chatid)
        return {"ok": True, "chatid": chatid, "result": result}
    finally:
        await client.disconnect()


async def _upload_and_send_file_async(
    chatid: str,
    file_path: str | Path,
    *,
    bot_id: str,
    secret: str,
    media_type: WeComMediaType | None = None,
) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")

    data = path.read_bytes()
    size_mb = len(data) / (1024 * 1024)
    if size_mb > 50:
        raise ValueError(f"文件过大（{size_mb:.1f}MB），SDK 上限约 50MB")

    mtype = media_type or guess_media_type(path)
    client = WSClient(bot_id=bot_id, secret=secret)
    await client.connect()
    try:
        if not await _wait_authenticated(client):
            raise TimeoutError("企业微信智能机器人认证超时")
        uploaded = await client.upload_media(data, type=mtype, filename=path.name)
        media_id = uploaded["media_id"]
        send_result = await client.send_media_message(chatid, mtype, media_id)
        save_last_chatid(chatid)
        return {
            "ok": True,
            "chatid": chatid,
            "path": str(path),
            "type": mtype,
            "upload": uploaded,
            "send": send_result,
        }
    finally:
        await client.disconnect()


async def _save_incoming_media(client: WSClient, frame: dict) -> Path | None:
    body = frame.get("body") or {}
    msgtype = body.get("msgtype")
    if msgtype not in {"image", "file", "video"}:
        return None

    media = body.get(msgtype) or {}
    url = media.get("url") or ""
    aeskey = media.get("aeskey") or ""
    if not url:
        logger.warning("媒体消息缺少 url: %s", json.dumps(body, ensure_ascii=False)[:300])
        return None

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    result = await client.download_file(url, aeskey or None)
    buffer: bytes = result["buffer"]
    filename = result.get("filename") or f"{msgtype}_{body.get('msgid', 'unknown')}"
    safe_name = Path(str(filename)).name or f"{msgtype}.bin"
    save_path = DOWNLOAD_DIR / safe_name
    if save_path.exists():
        stem, suffix = save_path.stem, save_path.suffix
        save_path = DOWNLOAD_DIR / f"{stem}_{body.get('msgid', 'dup')[:12]}{suffix}"
    save_path.write_bytes(buffer)
    return save_path


async def _collect_messages_async(
    *,
    bot_id: str,
    secret: str,
    timeout_sec: float,
    max_count: int,
    auto_reply: bool,
    save_media: bool,
) -> list[dict[str, Any]]:
    import asyncio

    client = WSClient(bot_id=bot_id, secret=secret)
    collected: list[dict[str, Any]] = []
    done = asyncio.Event()

    def _maybe_finish() -> None:
        if len(collected) >= max_count:
            done.set()

    async def on_text(frame: dict) -> None:
        content = extract_text(frame)
        meta = extract_meta(frame)
        if meta["target"]:
            save_last_chatid(meta["target"])
        item = {"kind": "text", "text": content, **meta}
        collected.append(item)
        if auto_reply:
            stream_id = generate_req_id("stream")
            await client.reply_stream(frame, stream_id, f"已收到：{content}", True)
        _maybe_finish()

    async def on_media(frame: dict) -> None:
        meta = extract_meta(frame)
        if meta["target"]:
            save_last_chatid(meta["target"])
        saved: str | None = None
        if save_media:
            try:
                path = await _save_incoming_media(client, frame)
                saved = str(path) if path else None
            except Exception as exc:  # noqa: BLE001
                logger.error("下载媒体失败: %s", exc)
                collected.append({"kind": "media_error", "error": str(exc), **meta})
                _maybe_finish()
                return
        body = frame.get("body") or {}
        item = {
            "kind": "media",
            "msgtype": body.get("msgtype"),
            "saved_path": saved,
            **meta,
        }
        collected.append(item)
        if auto_reply:
            stream_id = generate_req_id("stream")
            name = Path(saved).name if saved else body.get("msgtype")
            await client.reply_stream(frame, stream_id, f"已收到媒体：{name}", True)
        _maybe_finish()

    async def on_voice(frame: dict) -> None:
        body = frame.get("body") or {}
        voice = body.get("voice") or {}
        content = (voice.get("content") or "").strip()
        meta = extract_meta(frame)
        if meta["target"]:
            save_last_chatid(meta["target"])
        collected.append({"kind": "voice", "text": content, **meta})
        if auto_reply and content:
            stream_id = generate_req_id("stream")
            await client.reply_stream(frame, stream_id, f"语音识别：{content}", True)
        _maybe_finish()

    client.on("message.text", on_text)
    client.on("message.image", on_media)
    client.on("message.file", on_media)
    client.on("message.video", on_media)
    client.on("message.voice", on_voice)

    await client.connect()
    try:
        if not await _wait_authenticated(client):
            raise TimeoutError("企业微信智能机器人认证超时")
        try:
            await asyncio.wait_for(done.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            pass
        return collected
    finally:
        await client.disconnect()


def _resolve_via(via: str | None) -> str:
    text = (via or "auto").strip().lower()
    if text in {"worker", "queue", "long"}:
        return "worker"
    if text in {"direct", "short", "ws"}:
        return "direct"
    return "auto"


def _resolve_robot_id(robot_id: str | None = None) -> str:
    import os

    return (robot_id or os.getenv(ENV_ROBOT_ID) or "").strip()


def _try_send_via_worker(
    *,
    robot_id: str,
    msgtype: str,
    chatid: str,
    content: str = "",
    file_path: str = "",
    media_type: str = "",
    wait_sec: float = 30,
) -> dict[str, Any] | None:
    """投递 Worker 出站队列；失败返回 None 以便回退短连。"""
    try:
        from src.flowgame.robot_channel import store as robot_store
        from src.flowgame.robot_channel.outbound import (
            enqueue_outbound,
            wait_outbound_result,
        )

        if not robot_store.is_worker_online():
            logger.info("Worker 未在线，aibot 回退短连接 robotId=%s", robot_id)
            return None
        req_id = enqueue_outbound(
            robot_id,
            msgtype=msgtype,
            content=content,
            chatid=chatid,
            file_path=file_path,
            media_type=media_type,
        )
        result = wait_outbound_result(req_id, timeout_sec=wait_sec)
        if result.get("ok"):
            return result
        logger.warning(
            "Worker 出站未成功 reqId=%s err=%s，将回退短连接",
            req_id,
            result.get("error"),
        )
        # via=worker 强制时仍返回失败结果；由调用方决定
        return result
    except Exception as exc:  # noqa: BLE001
        logger.info("投递 Worker 队列失败，回退短连接: %s", exc)
        return None


def send_markdown(
    content: str,
    chatid: str | None = None,
    *,
    bot_id: str | None = None,
    secret: str | None = None,
    via: str | None = "auto",
    robot_id: str | None = None,
    wait_sec: float = 30,
) -> dict[str, Any]:
    """主动发送一条 markdown。

    ``via``:
      - ``auto``（默认）：有 robotId 且 Worker 在线 → 走 Worker 长连接队列；否则短连
      - ``worker``：强制走 Worker 队列
      - ``direct``：强制短连（connect→send→disconnect）
    """
    cid = resolve_chatid(chatid)
    mode = _resolve_via(via)
    rid = _resolve_robot_id(robot_id)

    if mode in {"auto", "worker"} and rid:
        queued = _try_send_via_worker(
            robot_id=rid,
            msgtype="markdown",
            chatid=cid,
            content=content,
            wait_sec=wait_sec,
        )
        if queued is not None and queued.get("ok"):
            return queued
        if mode == "worker":
            return queued or {
                "ok": False,
                "error": "Worker 发送失败且未回退短连",
                "via": "worker",
            }

    bid, sec = resolve_bot_creds(bot_id, secret)
    out = run_async(_send_markdown_async(cid, content, bot_id=bid, secret=sec))
    if isinstance(out, dict):
        out.setdefault("via", "direct")
    return out


def send_file(
    file_path: str | Path,
    chatid: str | None = None,
    *,
    media_type: WeComMediaType | None = None,
    bot_id: str | None = None,
    secret: str | None = None,
    via: str | None = "auto",
    robot_id: str | None = None,
    wait_sec: float = 60,
) -> dict[str, Any]:
    """上传本地文件并发送（按扩展名推断 image/file/voice/video）。

    ``via`` 语义同 ``send_markdown``。
    """
    cid = resolve_chatid(chatid)
    path = Path(file_path)
    mode = _resolve_via(via)
    rid = _resolve_robot_id(robot_id)
    mtype = media_type or guess_media_type(path)

    if mode in {"auto", "worker"} and rid:
        queued = _try_send_via_worker(
            robot_id=rid,
            msgtype=str(mtype),
            chatid=cid,
            file_path=str(path.expanduser()),
            media_type=str(mtype),
            wait_sec=wait_sec,
        )
        if queued is not None and queued.get("ok"):
            return queued
        if mode == "worker":
            return queued or {
                "ok": False,
                "error": "Worker 发送失败且未回退短连",
                "via": "worker",
            }

    bid, sec = resolve_bot_creds(bot_id, secret)
    out = run_async(
        _upload_and_send_file_async(
            cid, file_path, bot_id=bid, secret=sec, media_type=media_type
        )
    )
    if isinstance(out, dict):
        out.setdefault("via", "direct")
    return out


def collect_messages(
    timeout_sec: float = 30,
    max_count: int = 1,
    *,
    auto_reply: bool = False,
    save_media: bool = True,
    bot_id: str | None = None,
    secret: str | None = None,
) -> list[dict[str, Any]]:
    """短时连接并收集入站消息，到齐或超时后断开。

    适合 FlowGame 动态代码节点；长驻监听请用 CLI：``python -m wecom.daemon``。
    """
    bid, sec = resolve_bot_creds(bot_id, secret)
    return run_async(
        _collect_messages_async(
            bot_id=bid,
            secret=sec,
            timeout_sec=timeout_sec,
            max_count=max(1, int(max_count)),
            auto_reply=auto_reply,
            save_media=save_media,
        )
    )


def last_chatid() -> str:
    """读取最近一次会话 ID（群 chatid 或单聊 userid）。"""
    return load_last_chatid()
