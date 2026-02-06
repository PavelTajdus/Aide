import argparse
import asyncio
import os
import time
from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from agent import run_agent
from config import get_allowed_users, load_workspace_env, resolve_workspace
from context import recall_memory
from core_tools._utils import atomic_write_json, file_lock, load_json


RUNNING: Dict[int, Any] = {}


def _escape_markdown_v2(text: str) -> str:
    # Telegram MarkdownV2 special chars (aggressive escaping)
    text = text.replace("\\", "\\\\")
    escape_chars = r"_[]()~`>#+-=|{}.!"
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text


def _sessions_path(workspace: Path) -> Path:
    return workspace / "data" / "sessions.json"


def _get_session_id(workspace: Path, chat_id: int) -> Optional[str]:
    path = _sessions_path(workspace)
    with file_lock(path):
        data = load_json(path, {})
        return data.get(str(chat_id))


def _set_session_id(workspace: Path, chat_id: int, session_id: Optional[str]) -> None:
    path = _sessions_path(workspace)
    with file_lock(path):
        data = load_json(path, {})
        key = str(chat_id)
        if session_id:
            data[key] = session_id
        else:
            data.pop(key, None)
        atomic_write_json(path, data)


def _is_allowed(user_id: Optional[int], allowed: list[int]) -> bool:
    if user_id is None:
        return False
    if not allowed:
        return False
    return user_id in allowed


def _ensure_inbox(workspace: Path) -> Path:
    inbox = workspace / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


def _build_prompt(text: Optional[str], attachment_paths: list[str]) -> str:
    base = text.strip() if text else ""
    if attachment_paths:
        attachments = "\n".join(f"- {p}" for p in attachment_paths)
        if base:
            return f"{base}\n\nAttachments:\n{attachments}"
        return f"Attachment received:\n{attachments}"
    return base


def _split_text(text: str, limit: int = 3800) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        chunks.append(text[start:end])
        start = end
    return chunks


def _get_parse_mode() -> Optional[str]:
    raw = os.environ.get("AIDE_TELEGRAM_PARSE_MODE", "plain").strip().lower()
    if raw in ("markdown_v2", "markdownv2", "mdv2"):
        return ParseMode.MARKDOWN_V2
    return None


def _get_escape_mode() -> str:
    raw = os.environ.get("AIDE_TELEGRAM_ESCAPE", "none").strip().lower()
    if raw in ("aggressive", "full"):
        return "aggressive"
    return "none"


def _progress_enabled() -> bool:
    raw = os.environ.get("AIDE_TELEGRAM_PROGRESS", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _progress_text(tool_name: str) -> str:
    name = tool_name.lower()
    if "web" in name or "search" in name:
        return "Searching the web…"
    if "bash" in name or "shell" in name:
        return "Running command…"
    if "read" in name:
        return "Loading context…"
    if "write" in name or "edit" in name:
        return "Editing files…"
    return "Working…"


def _max_file_bytes() -> tuple[int, float]:
    raw = os.environ.get("AIDE_TELEGRAM_MAX_FILE_MB", "10").strip().lower()
    try:
        mb = float(raw)
    except ValueError:
        mb = 10.0
    if mb <= 0:
        mb = 10.0
    return int(mb * 1024 * 1024), mb


async def _progress_worker(bot, chat_id: int, message_id: int, queue: asyncio.Queue) -> None:
    last_update = 0.0
    last_text: Optional[str] = None
    while True:
        item = await queue.get()
        if item is None:
            break
        # Coalesce multiple pending updates
        pending = item
        while True:
            try:
                nxt = queue.get_nowait()
                if nxt is None:
                    pending = None
                    break
                pending = nxt
            except asyncio.QueueEmpty:
                break
        if not pending or pending == last_text:
            continue
        now = time.time()
        wait = max(0.0, 1.2 - (now - last_update))
        if wait:
            await asyncio.sleep(wait)
        try:
            await bot.edit_message_text(
                text=pending,
                chat_id=chat_id,
                message_id=message_id,
            )
            last_text = pending
            last_update = time.time()
        except BadRequest:
            # Ignore update errors for status message
            continue


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    workspace = resolve_workspace(context.application.bot_data.get("workspace"))
    _set_session_id(workspace, update.effective_chat.id, None)
    await update.message.reply_text("New session created.")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    proc = RUNNING.get(chat_id)
    if not proc:
        await update.message.reply_text("No session running.")
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()
    RUNNING.pop(chat_id, None)
    await update.message.reply_text("Session stopped.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    workspace = resolve_workspace(context.application.bot_data.get("workspace"))
    load_workspace_env(workspace)

    allowed = context.application.bot_data.get("allowed_users", [])
    if not _is_allowed(update.effective_user.id if update.effective_user else None, allowed):
        return

    message = update.message
    if message is None:
        return

    attachment_paths: list[str] = []
    inbox = _ensure_inbox(workspace)
    max_bytes, max_mb = _max_file_bytes()
    oversize = False

    if message.photo:
        photo = message.photo[-1]
        if photo.file_size and photo.file_size > max_bytes:
            oversize = True
        else:
            file = await photo.get_file()
            ext = ".jpg"
            filename = f"{int(time.time())}_{photo.file_unique_id}{ext}"
            target = inbox / filename
            await file.download_to_drive(custom_path=str(target))
            attachment_paths.append(str(target))

    if message.document:
        doc = message.document
        if doc.file_size and doc.file_size > max_bytes:
            oversize = True
        else:
            file = await doc.get_file()
            ext = Path(doc.file_name or "").suffix or Path(file.file_path or "").suffix or ".bin"
            filename = f"{int(time.time())}_{doc.file_unique_id}{ext}"
            target = inbox / filename
            await file.download_to_drive(custom_path=str(target))
            attachment_paths.append(str(target))

    prompt = _build_prompt(message.text or message.caption, attachment_paths)
    if oversize:
        warning = f"Attachment too large (max {int(max_mb)} MB), not downloaded."
        if not prompt:
            await message.reply_text(warning)
            return
        await message.reply_text(warning)
    if not prompt:
        await message.reply_text("No text or attachment received.")
        return

    thinking = await message.reply_text("Thinking...")

    session_id = _get_session_id(workspace, update.effective_chat.id)

    # Auto-recall memory context for new sessions
    if not session_id:
        memory_context = recall_memory(workspace, prompt)
        if memory_context:
            prompt = f"{memory_context}\n\n{prompt}"

    def _process_cb(proc):
        RUNNING[update.effective_chat.id] = proc

    loop = asyncio.get_running_loop()
    progress_queue: Optional[asyncio.Queue] = None
    progress_task: Optional[asyncio.Task] = None

    if _progress_enabled():
        progress_queue = asyncio.Queue()
        progress_task = asyncio.create_task(
            _progress_worker(context.bot, update.effective_chat.id, thinking.message_id, progress_queue)
        )

        def _tool_cb(name: str) -> None:
            if not progress_queue:
                return
            msg = _progress_text(name)
            loop.call_soon_threadsafe(progress_queue.put_nowait, msg)
    else:
        def _tool_cb(name: str) -> None:
            return

    try:
        answer, new_session_id, _tool_log = await loop.run_in_executor(
            None,
            partial(
                run_agent,
                prompt,
                session_id=session_id,
                working_dir=workspace,
                process_cb=_process_cb,
                tool_cb=_tool_cb,
            ),
        )
    except Exception as exc:
        RUNNING.pop(update.effective_chat.id, None)
        safe_text = f"Error: {exc}"
        await context.bot.edit_message_text(
            text=safe_text,
            chat_id=update.effective_chat.id,
            message_id=thinking.message_id,
        )
        return

    if progress_queue:
        progress_queue.put_nowait(None)
    if progress_task:
        try:
            await progress_task
        except Exception:
            pass

    RUNNING.pop(update.effective_chat.id, None)
    if new_session_id:
        _set_session_id(workspace, update.effective_chat.id, new_session_id)

    parse_mode = _get_parse_mode()
    escape_mode = _get_escape_mode()
    rendered = _escape_markdown_v2(answer) if (parse_mode and escape_mode == "aggressive") else answer
    chunks = _split_text(rendered)
    try:
        if parse_mode:
            await context.bot.edit_message_text(
                text=chunks[0],
                chat_id=update.effective_chat.id,
                message_id=thinking.message_id,
                parse_mode=parse_mode,
            )
        else:
            await context.bot.edit_message_text(
                text=chunks[0],
                chat_id=update.effective_chat.id,
                message_id=thinking.message_id,
            )
    except BadRequest:
        await context.bot.edit_message_text(
            text=answer,
            chat_id=update.effective_chat.id,
            message_id=thinking.message_id,
        )

    for chunk in chunks[1:]:
        try:
            if parse_mode:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=chunk,
                    parse_mode=parse_mode,
                )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=chunk,
                )
        except BadRequest:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=chunk,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Aide Telegram bot")
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()

    workspace = resolve_workspace(args.workspace)
    load_workspace_env(workspace)

    telegram_enabled = os.environ.get("AIDE_TELEGRAM_ENABLED", "1").strip().lower()
    if telegram_enabled in ("0", "false", "no", "off"):
        return

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_TOKEN in workspace .env")

    allowed = get_allowed_users()

    app = ApplicationBuilder().token(token).build()
    app.bot_data["workspace"] = str(workspace)
    app.bot_data["allowed_users"] = allowed

    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()
