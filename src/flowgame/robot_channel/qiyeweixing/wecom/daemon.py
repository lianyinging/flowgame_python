"""常驻收发 CLI（终端交互），来自原 aibot_ws_receiver 能力。

用法（在 qiyeweixing 目录或已注入 sys.path 后）::

    python -m wecom.daemon
    python -m wecom.daemon --send "你好" --chatid xxx
    python -m wecom.daemon --send-file ./a.pdf --chatid xxx
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

_qiye_root = str(Path(__file__).resolve().parents[1])
if _qiye_root not in sys.path:
    sys.path.insert(0, _qiye_root)

from _compat import ensure_typing_not_required

ensure_typing_not_required()

from wecom_aibot_sdk import WSClient, generate_req_id

from . import aibot as aibot_mod
from ._util import (
    load_last_chatid,
    resolve_bot_creds,
    resolve_chatid,
    save_last_chatid,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("wecom.daemon")


def _stdin_readline() -> str | None:
    try:
        return input()
    except EOFError:
        return None


async def _stdin_sender(client: WSClient, chatid_holder: dict[str, str]) -> None:
    loop = asyncio.get_running_loop()
    logger.info(
        "终端发送已开启：\n"
        "  - 直接输入文字回车 → 发文本\n"
        "  - file:/绝对或相对路径 → 发文件\n"
        "  - quit → 退出"
    )
    while True:
        line = await loop.run_in_executor(None, _stdin_readline)
        if line is None:
            break
        text = line.strip()
        if not text:
            continue
        if text.lower() in {"quit", "exit", "q"}:
            raise KeyboardInterrupt
        chatid = chatid_holder.get("chatid") or ""
        if not chatid:
            logger.warning("还没有会话 ID。请先在群里 @ 机器人发一条，或用 --chatid 指定")
            continue
        try:
            if text.lower().startswith("file:"):
                file_path = text[5:].strip().strip("'\"")
                path = Path(file_path).expanduser().resolve()
                data = path.read_bytes()
                mtype = aibot_mod.guess_media_type(path)
                uploaded = await client.upload_media(data, type=mtype, filename=path.name)
                await client.send_media_message(chatid, mtype, uploaded["media_id"])
                logger.info("已发送文件到 %s: %s", chatid, file_path)
            else:
                await client.send_message(
                    chatid,
                    {"msgtype": "markdown", "markdown": {"content": text}},
                )
                logger.info("已主动发送到 %s: %s", chatid, text)
        except Exception as exc:  # noqa: BLE001
            logger.error("主动发送失败: %s", exc)


async def run_daemon(
    bot_id: str,
    secret: str,
    *,
    auto_reply: bool,
    chatid: str,
    enable_stdin: bool,
) -> None:
    client = WSClient(bot_id=bot_id, secret=secret)
    chatid_holder = {"chatid": chatid or load_last_chatid()}

    client.on("connected", lambda: logger.info("WebSocket 已连接"))
    client.on(
        "authenticated",
        lambda: logger.info(
            "认证成功。当前发送目标 chatid=%s",
            chatid_holder["chatid"] or "(收到消息后自动记录)",
        ),
    )
    client.on("disconnected", lambda reason: logger.warning("连接断开: %s", reason))
    client.on("reconnecting", lambda attempt: logger.info("正在重连 (#%s)", attempt))
    client.on("error", lambda err: logger.error("错误: %s", err))

    async def on_text(frame: dict) -> None:
        content = aibot_mod.extract_text(frame)
        meta = aibot_mod.extract_meta(frame)
        if meta["target"]:
            chatid_holder["chatid"] = meta["target"]
            save_last_chatid(meta["target"])
        logger.info(
            "收到文本 | chattype=%s target=%s userid=%s | %s",
            meta["chattype"],
            meta["target"],
            meta["userid"],
            content,
        )
        print(json.dumps({"text": content, **meta}, ensure_ascii=False, indent=2))
        if not auto_reply:
            return
        stream_id = generate_req_id("stream")
        await client.reply_stream(frame, stream_id, f"已收到：{content}", True)

    async def on_media(frame: dict) -> None:
        meta = aibot_mod.extract_meta(frame)
        if meta["target"]:
            chatid_holder["chatid"] = meta["target"]
            save_last_chatid(meta["target"])
        body = frame.get("body") or {}
        msgtype = body.get("msgtype")
        try:
            saved = await aibot_mod._save_incoming_media(client, frame)
        except Exception as exc:  # noqa: BLE001
            logger.error("下载/保存媒体失败: %s", exc)
            if auto_reply:
                stream_id = generate_req_id("stream")
                await client.reply_stream(
                    frame, stream_id, f"收到{msgtype}，但保存失败：{exc}", True
                )
            return
        if saved and auto_reply:
            stream_id = generate_req_id("stream")
            await client.reply_stream(
                frame,
                stream_id,
                f"已收到你的{msgtype}，已保存为 `{saved.name}`",
                True,
            )

    async def on_voice(frame: dict) -> None:
        body = frame.get("body") or {}
        voice = body.get("voice") or {}
        content = (voice.get("content") or "").strip()
        meta = aibot_mod.extract_meta(frame)
        if meta["target"]:
            chatid_holder["chatid"] = meta["target"]
            save_last_chatid(meta["target"])
        logger.info("收到语音转文字 | userid=%s | %s", meta["userid"], content)
        if auto_reply and content:
            stream_id = generate_req_id("stream")
            await client.reply_stream(frame, stream_id, f"语音识别：{content}", True)

    async def on_enter_chat(frame: dict) -> None:
        logger.info("用户进入会话")
        await client.reply_welcome(
            frame,
            {
                "msgtype": "text",
                "text": {
                    "content": (
                        "你好，我是智能机器人。\n"
                        "- 群聊：@ 我发文字\n"
                        "- 单聊：可发文字/图片/文件/视频（文件会自动保存）"
                    )
                },
            },
        )

    client.on("message.text", on_text)
    client.on("message.image", on_media)
    client.on("message.file", on_media)
    client.on("message.video", on_media)
    client.on("message.voice", on_voice)
    client.on("event.enter_chat", on_enter_chat)

    await client.connect()
    tasks: list[asyncio.Task] = []
    if enable_stdin:
        tasks.append(asyncio.create_task(_stdin_sender(client, chatid_holder)))
    try:
        if tasks:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        else:
            await asyncio.Event().wait()
    finally:
        for t in tasks:
            t.cancel()
        await client.disconnect()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="企业微信智能机器人 WebSocket 收发")
    parser.add_argument("--bot-id", default="", help="BotID（默认读环境变量）")
    parser.add_argument("--secret", default="", help="Secret（默认读环境变量）")
    parser.add_argument("--chatid", default="", help="主动发送目标会话 ID")
    parser.add_argument("--send", default="", help="主动发送一条 markdown 后退出")
    parser.add_argument("--send-file", default="", help="主动发送本地文件后退出")
    parser.add_argument("--no-reply", action="store_true", help="收到消息时不自动回复")
    parser.add_argument("--no-stdin", action="store_true", help="常驻时不从终端读输入")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        bot_id, secret = resolve_bot_creds(args.bot_id or None, args.secret or None)
    except ValueError as exc:
        print(exc)
        return 1

    try:
        if args.send or args.send_file:
            chatid = resolve_chatid(args.chatid or None)
            if args.send_file:
                aibot_mod.send_file(args.send_file, chatid, bot_id=bot_id, secret=secret)
            else:
                aibot_mod.send_markdown(args.send, chatid, bot_id=bot_id, secret=secret)
            print("发送成功")
            return 0

        chatid = (args.chatid or load_last_chatid() or "").strip()
        asyncio.run(
            run_daemon(
                bot_id,
                secret,
                auto_reply=not args.no_reply,
                chatid=chatid,
                enable_stdin=not args.no_stdin,
            )
        )
    except KeyboardInterrupt:
        logger.info("已退出")
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("%s", exc)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
