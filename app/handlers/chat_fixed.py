from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.config import settings
from app.services.memory import (
    get_active_project, get_chat_flags, get_context_filters_state, get_linked_project_ids,
    gather_context_sources, get_preferred_model, _ensure_user_state,
)
from app.models import BotMessage
from app.llm import ask_llm
from app.services.ui_helpers import attach_reply_kb as svc_attach_reply_kb
from html import escape

router = Router()

# Префикс для запроса тегов
TAG_PROMPT_PREFIX = "Свои теги (через запятую)"

# Service texts that should be ignored by the chat handler
SERVICE_TEXTS = {
    "Ask ❓", "⚙️ Actions", "❓ ASK‑WIZARD", "💬 Chat: ON", "😴 Chat: OFF",
    "Меню", "Menu", "Статус", "Status"
}

def answer_kb(msg_id: int, saved: bool):
    # обязательные кнопки: Save / Summary / Tag / Delete / Refine
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=("✅ Saved" if saved else "💾 Save"), callback_data=f"ans:save:{msg_id}"),
        InlineKeyboardButton(text="📌 Summary", callback_data=f"ans:sum:{msg_id}"),
        InlineKeyboardButton(text="🏷 Tag", callback_data=f"ans:tag:{msg_id}"),
    ],[
        InlineKeyboardButton(text="🗑 Delete", callback_data=f"ans:del:{msg_id}"),
        InlineKeyboardButton(text="↩ Refine", callback_data=f"ans:ref:{msg_id}"),
    ]])

@router.message(F.text & ~F.text.startswith("/"))
async def on_free_text(message: Message):
    from app.db import session_scope
    async with session_scope() as st:
        if not message.from_user:
            return
        
        # Если это ответ на наш форс-промпт тегов — пропускаем,
        # пусть обработает tags_free_reply
        if message.reply_to_message and (
            (message.reply_to_message.text or "").startswith(TAG_PROMPT_PREFIX) or
            (message.reply_to_message.text or "").startswith("Свои теги для импорта")
        ):
            return

        # Ignore service texts
        text = (message.text or "").strip()
        if not text or text in SERVICE_TEXTS:
            return  # не трогаем

        stt = await _ensure_user_state(st, message.from_user.id)

        # 1) если ждём вопрос после Ask (армирован)
        if stt.ask_armed:
            stt.ask_armed = False
            await st.commit()
            return await run_question_with_selection(message, st, stt, text)

        # Check if we're awaiting search input - if so, don't process with LLM (LLM safety) (Hotfix F)
        if stt.awaiting_ask_search:
            # Don't process with LLM when awaiting search input
            return

        chat_on, quiet_on, sources_mode, scope_mode = await get_chat_flags(st, message.from_user.id)
        if quiet_on:
            return
        if not chat_on:
            # один мягкий хинт можно запоминать в памяти, но для MVP просто ответим
            await message.answer("💡 Включи чат: нажми «💬 Chat» на синей клавиатуре или команду /actions → Quiet OFF.")
            await svc_attach_reply_kb(message, message.from_user.id)
            return
        
        proj = await get_active_project(st, message.from_user.id)
        if not proj:
            await message.answer("Сначала выбери проект: открой Actions → Projects (или /project <name>).")
            await svc_attach_reply_kb(message, message.from_user.id)
            return
        
        # Сбор контекста по источникам (упрощённая версия)
        ctx_texts = await gather_context_sources(
            st, message.from_user.id, proj.id,
            max_chunks=settings.project_max_chunks
        )

        model = await get_preferred_model(st, message.from_user.id)

        # Решаем по scope:
        prompt = message.text or ""
        final_ctx = ctx_texts if scope_mode in ("auto", "project") else []
        
        answer = await ask_llm(prompt, final_ctx, model=model)  # внутри ask_llm ты уже умеешь сшивать ctx в system

        # штамп
        from app.services.memory import list_projects
        names = {p.id: p.name for p in await list_projects(st)}
        stamp = f"\n\n<i>Project: {escape(proj.name) if proj else '—'} • Scope: {scope_mode} • Sources: {sources_mode} • Model: {model}</i>"

        sent = await message.answer(answer + stamp)
        bm = BotMessage(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            tg_message_id=sent.message_id,
            reply_to_user_msg_id=message.message_id,
            artifact_id=None, saved=False,
            project_id=(proj.id if proj else None),
            used_projects={"ids": [proj.id] if proj else []},
        )
        st.add(bm); await st.commit()
        await sent.edit_reply_markup(reply_markup=answer_kb(sent.message_id, saved=False))

async def run_question_with_selection(message: Message, st: AsyncSession, stt, text: str):
    """Run question with selected artifacts only"""
    from app.services.artifacts import get_chunks_by_artifact_ids
    from app.services.memory import get_active_project, get_preferred_model, fetch_chunks_for_question
    from app.llm import ask_llm
    from app.models import BotMessage
    from html import escape
    
    proj = await get_active_project(st, message.from_user.id)
    if not proj:
        await message.answer("Сначала выбери проект: открой Actions → Projects (или /project <name>).")
        await svc_attach_reply_kb(message, message.from_user.id)
        return
    
    model = await get_preferred_model(st, message.from_user.id)
    project_id = proj.id  # This is safe because we've already checked that proj is not None
    
    # Get chunks based on selection
    chunks, approx_tokens, has_selection, auto_clear = await fetch_chunks_for_question(
        st, message.from_user.id, project_id, model
    )
    
    answer = await ask_llm(text, chunks, model=model)
    
    # Clear selection if auto-clear is enabled
    if has_selection and auto_clear:
        stt.selected_artifact_ids = None
        await st.commit()
    
    # штамп
    stamp = f"\n\n<i>Project: {escape(proj.name) if proj else '—'} • Scope: selected • Model: {model}</i>"
    
    sent = await message.answer(answer + stamp)
    bm = BotMessage(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        tg_message_id=sent.message_id,
        reply_to_user_msg_id=message.message_id,
        artifact_id=None, saved=False,
        project_id=project_id,
        used_projects={"ids": [project_id]},
    )
    st.add(bm); await st.commit()
    await sent.edit_reply_markup(reply_markup=answer_kb(sent.message_id, saved=False))
