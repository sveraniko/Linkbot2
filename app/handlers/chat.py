from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message

from app.db import session_scope
from app.services.memory import _ensure_user_state, get_chat_flags
from app.handlers.keyboard import SERVICE_TEXTS
from app.handlers.ask import run_question_with_selection
from app.services.ui_helpers import attach_reply_kb as svc_attach_reply_kb

router = Router(name="chat")

@router.message(F.text & ~F.text.startswith("/"))
async def on_free_text(message: Message):
    if not message.from_user or (message.text is None):
        return
    text = message.text.strip()
    if text in SERVICE_TEXTS:
        return

    async with session_scope() as st:
        stt = await _ensure_user_state(st, message.from_user.id)
        
        # Early exit if awaiting ASK search response
        if bool(stt.awaiting_ask_search):
            # This message is a response to ASK search ForceReply
            # Reset the flag and let the ASK handler process it
            stt.awaiting_ask_search = False
            await st.commit()
            # Import and call the ASK search reply handler
            from app.handlers.ask import ask_search_reply
            return await ask_search_reply(message)
        
        chat_on, *_ = await get_chat_flags(st, message.from_user.id)

        # ASK path first
        if bool(stt.ask_armed):
            if not chat_on:
                await message.answer(
                    "Чат выключен. Нажми ‘💬 Chat: ON’ и отправь вопрос — ASK уже готов."
                )
                await svc_attach_reply_kb(message, message.from_user.id)
                return
            # IMPORTANT: no LLM call in test mode
            return await run_question_with_selection(message, text)

        # Global chat path — TEMPORARILY DISABLED to avoid token usage
        if chat_on:
            await message.answer("Глобальный чат временно отключён (тест-режим, без LLM).")
            return
        else:
            await message.answer(
                "Чат выключен. Нажми ‘💬 Chat: ON’ чтобы задать вопрос (LLM сейчас отключён)."
            )
            await svc_attach_reply_kb(message, message.from_user.id)
            return
