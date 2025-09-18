from __future__ import annotations
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.services.memory import (
    get_active_project, get_preferred_model, get_context_filters_state, count_artifacts,
    get_chat_flags, get_linked_project_ids, list_projects
)
from app.services.ui_helpers import attach_reply_kb as svc_attach_reply_kb
from html import escape

router = Router()

async def render_status(st: AsyncSession, user_id: int) -> str:
    proj = await get_active_project(st, user_id)
    model = await get_preferred_model(st, user_id)
    kinds, tags = await get_context_filters_state(st, user_id)
    chat_on, quiet_on, sources_mode, scope_mode = await get_chat_flags(st, user_id)
    linked_ids = await get_linked_project_ids(st, user_id)
    all_projects = {p.id: p.name for p in await list_projects(st)}
    linked_names = [all_projects.get(pid, str(pid)) for pid in linked_ids]
    if proj:
        n = await count_artifacts(st, proj)
        p = f"<b>{escape(proj.name)}</b> (артефактов: {n})"
    else:
        p = "— не выбран —"
    return (
        f"📊 <b>Статус</b>\n"
        f"Проект: {p}\n"
        f"Модель: <code>{model}</code>\n"
        f"Chat: {'ON' if chat_on else 'OFF'} | Quiet: {'ON' if quiet_on else 'OFF'}\n"
        f"Scope: <code>{scope_mode}</code> | Sources: <code>{sources_mode}</code>\n"
        f"Linked: <code>{', '.join(linked_names) or '—'}</code>\n"
        f"Фильтры kinds: <code>{', '.join(kinds) or '—'}</code>\n"
        f"Фильтры tags: <code>{', '.join(tags) or '—'}</code>\n"
        f"\nОткрой панель: <code>/actions</code>"
    )

@router.message(Command("status"))
async def status_cmd(message: Message):
    from app.db import session_scope
    async with session_scope() as st:
        if message.from_user:
            text = await render_status(st, message.from_user.id)
            await message.answer(text)
            await svc_attach_reply_kb(message, message.from_user.id)
