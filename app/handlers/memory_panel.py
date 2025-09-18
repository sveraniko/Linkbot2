from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, ForceReply
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload
from html import escape
import datetime as dt
import uuid
import re

from app.db import session_scope
from app.models import Artifact, Project, Tag, artifact_tags
from app.services.memory import get_active_project, _ensure_user_state
from app.services.ui_helpers import attach_reply_kb as svc_attach_reply_kb
from app.services.telemetry import error
from app.ui import show_panel

router = Router(name="memory_panel")

# Date extraction patterns for auto-tags
DATE_PATTERNS = [
    re.compile(r"[_-](\d{4})(\d{2})(\d{2})[_-]"),         # _YYYYMMDD_ or -YYYYMMDD-
    re.compile(r"[-](\d{4})[-](\d{2})[-](\d{2})"),       # -YYYY-MM-DD
]


def extract_doc_date(filename: str) -> str | None:
    """Extract document date from filename if possible."""
    for pat in DATE_PATTERNS:
        m = pat.search(filename or "")
        if m:
            year, month, day = m.group(1), m.group(2), m.group(3)
            try:
                dt.date(int(year), int(month), int(day))
                return f"{year}-{month}-{day}"
            except ValueError:
                continue
    return None


def auto_tags_for_single_file(filename: str) -> list[str]:
    """Generate auto-tags for single file import."""
    tags = [f"rel-{dt.date.today():%Y-%m-%d}"]
    d = extract_doc_date(filename)
    if d:
        tags.append(f"doc-{d}")
    tags.append(f"batch-{str(uuid.uuid4())[:6]}")
    return tags


# Memory panel main keyboard
def _memory_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 List", callback_data="mem:list:1")
    builder.button(text="🧾 Show", callback_data="mem:show")
    builder.button(text="🧹 Clear…", callback_data="mem:clear_confirm")
    builder.button(text="➕ Add note", callback_data="mem:add_note")
    builder.button(text="📥 Import last", callback_data="mem:import_last")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


# Memory panel entry point
@router.message(F.text == "🧠 Memory")
async def memory_open(message: Message):
    """Open Memory panel."""
    if not message.from_user:
        return
    try:
        async with session_scope() as st:
            proj = await get_active_project(st, message.from_user.id)
            if not proj:
                await message.answer("Нет активного проекта. Создай или выбери.")
                await svc_attach_reply_kb(message, message.from_user.id)
                return
            await message.answer("Memory панель:", reply_markup=_memory_kb())
            await svc_attach_reply_kb(message, message.from_user.id)
    except Exception as e:
        try:
            error("handler_exception", where="memory_open", user_id=message.from_user.id, err=str(e))
        except Exception:
            pass
        await message.answer("Произошла ошибка при открытии Memory панели")
        await svc_attach_reply_kb(message, message.from_user.id)


# List artifacts with pagination
@router.callback_query(F.data.startswith("mem:list:"))
async def memory_list(cb: CallbackQuery):
    if not cb.from_user or not cb.data:
        return await cb.answer("Invalid user")

    try:
        page = int(cb.data.split(":")[2])
    except (IndexError, ValueError):
        page = 1

    async with session_scope() as st:
        proj = await get_active_project(st, cb.from_user.id)
        if not proj:
            if cb.message and isinstance(cb.message, Message):
                await cb.message.answer("Нет активного проекта")
                await svc_attach_reply_kb(cb.message, cb.from_user.id)
            return await cb.answer("Нет активного проекта")

        page_size = 5
        offset = (page - 1) * page_size

        stmt = (
            select(Artifact)
            .options(selectinload(Artifact.tags))
            .where(Artifact.project_id == proj.id)
            .order_by(Artifact.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await st.execute(stmt)
        artifacts = result.scalars().all()

        # Deduplicate by ID
        seen = set()
        unique_artifacts: list[Artifact] = []
        for art in artifacts:
            if art.id not in seen:
                seen.add(art.id)
                unique_artifacts.append(art)
        artifacts = unique_artifacts

        # User state for page tracking
        stt = await _ensure_user_state(st, cb.from_user.id)
        selected_ids = set()
        if stt.selected_artifact_ids:
            try:
                selected_ids = {int(x.strip()) for x in stt.selected_artifact_ids.split(",") if x.strip()}
            except ValueError:
                selected_ids = set()

        # Delete previous page messages and footer
        if cb.message and isinstance(cb.message, Message) and cb.message.bot:
            if stt.memory_page_msg_ids:
                try:
                    msg_ids = [int(i) for i in stt.memory_page_msg_ids.split(",") if i.strip()]
                    for mid in msg_ids:
                        try:
                            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=mid)
                        except Exception:
                            pass
                except Exception:
                    pass
            if stt.memory_footer_msg_id:
                try:
                    await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=stt.memory_footer_msg_id)
                except Exception:
                    pass

            # Send new page
            sent_msg_ids: list[str] = []
            for art in artifacts:
                tag_names = [t.name for t in art.tags] if art.tags else []
                tags_str = " [" + " ".join(escape(t) for t in tag_names[:3]) + "]" if tag_names else ""
                title = escape((art.title or str(art.id))[:80])
                created_at = art.created_at.strftime("%Y-%m-%d") if art.created_at else ""
                text_line = f"{title}{tags_str} (id {art.id}{', ' + created_at if created_at else ''})"

                b = InlineKeyboardBuilder()
                toggle_icon = "🧺" if art.id in selected_ids else "➕"
                b.button(text=toggle_icon, callback_data=f"mem:toggle:{art.id}")
                b.button(text="🗑", callback_data=f"mem:delete:{art.id}")
                b.button(text="📌", callback_data=f"mem:pin:{art.id}")
                b.button(text="❔ Ask", callback_data=f"mem:ask:{art.id}")
                b.adjust(2, 2)

                sent = await cb.message.bot.send_message(cb.message.chat.id, text_line, reply_markup=b.as_markup())
                sent_msg_ids.append(str(sent.message_id))

            stt.memory_page_msg_ids = ",".join(sent_msg_ids) if sent_msg_ids else None

            # Footer pagination
            total_count = (await st.execute(select(func.count(Artifact.id)).where(Artifact.project_id == proj.id))).scalar_one_or_none() or 0
            total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

            if total_pages > 1:
                footer = InlineKeyboardBuilder()
                if page > 1:
                    footer.button(text="⬅️ Назад", callback_data=f"mem:list:{page-1}")
                footer.button(text=f"Стр. {page}/{total_pages}", callback_data="mem:noop")
                if page < total_pages:
                    footer.button(text="Далее ➡️", callback_data=f"mem:list:{page+1}")
                footer.adjust(3)
                fmsg = await cb.message.bot.send_message(cb.message.chat.id, "Пагинация:", reply_markup=footer.as_markup())
                stt.memory_footer_msg_id = fmsg.message_id
            else:
                stt.memory_footer_msg_id = None

            await st.commit()

        # Always reattach reply keyboard
        if cb.message and isinstance(cb.message, Message):
            await svc_attach_reply_kb(cb.message, cb.from_user.id)
    await cb.answer()


# Show memory summary
@router.callback_query(F.data == "mem:show")
async def memory_show(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")

    async with session_scope() as st:
        proj = await get_active_project(st, cb.from_user.id)
        if not proj:
            if cb.message and isinstance(cb.message, Message):
                await cb.message.answer("Нет активного проекта")
                await svc_attach_reply_kb(cb.message, cb.from_user.id)
            return await cb.answer("Нет активного проекта")

        import_count = (await st.execute(select(func.count(Artifact.id)).where(Artifact.project_id == proj.id, Artifact.kind == "import"))).scalar_one_or_none() or 0
        note_count = (await st.execute(select(func.count(Artifact.id)).where(Artifact.project_id == proj.id, Artifact.kind == "note"))).scalar_one_or_none() or 0
        answer_count = (await st.execute(select(func.count(Artifact.id)).where(Artifact.project_id == proj.id, Artifact.kind == "answer"))).scalar_one_or_none() or 0
        total_count = (await st.execute(select(func.count(Artifact.id)).where(Artifact.project_id == proj.id))).scalar_one_or_none() or 0

        date_result = await st.execute(
            select(Artifact.created_at).where(Artifact.project_id == proj.id).order_by(Artifact.created_at.desc()).limit(5)
        )
        recent_dates = [row[0].date() for row in date_result.all()]

        lines = ["<b>Memory — сводка</b>"]
        lines.append(f"Всего: {total_count}")
        lines.append(f"  import: {import_count}")
        lines.append(f"  note: {note_count}")
        lines.append(f"  answer: {answer_count}")
        if recent_dates:
            lines.append(f"Последние даты: {', '.join(str(d) for d in sorted(set(recent_dates), reverse=True)[:3])}")

        b = InlineKeyboardBuilder()
        b.button(text="🏠 Назад", callback_data="mem:main")

        if cb.message and isinstance(cb.message, Message) and cb.message.bot:
            await show_panel(st, cb.message.bot, cb.message.chat.id, cb.from_user.id, "\n".join(lines), b.as_markup())

        if cb.message and isinstance(cb.message, Message):
            await svc_attach_reply_kb(cb.message, cb.from_user.id)
    await cb.answer()


# Clear confirmation
@router.callback_query(F.data == "mem:clear_confirm")
async def memory_clear_confirm(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")

    async with session_scope() as st:
        proj = await get_active_project(st, cb.from_user.id)
        if not proj:
            if cb.message and isinstance(cb.message, Message):
                await cb.message.answer("Нет активного проекта")
                await svc_attach_reply_kb(cb.message, cb.from_user.id)
            return await cb.answer("Нет активного проекта")

        lines = [
            "<b>Memory — очистка</b>",
            f"Вы уверены, что хотите удалить ВСЕ записи в проекте <b>{escape(proj.name)}</b>?",
            "Это действие нельзя отменить."
        ]

        footer = InlineKeyboardBuilder()
        footer.button(text="✅ Да, удалить всё", callback_data="mem:clear_execute")
        footer.button(text="❌ Отмена", callback_data="mem:main")
        footer.adjust(1)

        if cb.message and isinstance(cb.message, Message) and cb.message.bot:
            await show_panel(st, cb.message.bot, cb.message.chat.id, cb.from_user.id, "\n".join(lines), footer.as_markup())

        if cb.message and isinstance(cb.message, Message):
            await svc_attach_reply_kb(cb.message, cb.from_user.id)
    await cb.answer()


# Execute clear
@router.callback_query(F.data == "mem:clear_execute")
async def memory_clear_execute(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")

    async with session_scope() as st:
        proj = await get_active_project(st, cb.from_user.id)
        if not proj:
            if cb.message and isinstance(cb.message, Message):
                await cb.message.answer("Нет активного проекта")
