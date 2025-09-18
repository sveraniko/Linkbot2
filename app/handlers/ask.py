from __future__ import annotations
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply, Message, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext  # Add this import for FSMContext
import sqlalchemy as sa
from sqlalchemy import distinct, and_
from typing import Iterable, Sequence
from html import escape
import re
import datetime as dt
from zoneinfo import ZoneInfo
import zipfile
import tempfile
from pathlib import Path
import contextlib  # Add this import for contextlib
import json  # Add this import for JSON handling
import time  # Add this import for time handling
import asyncio  # Add this import for asyncio handling

from app.db import session_scope
from app.models import Artifact, Chunk, UserState, Tag, artifact_tags
from app.services.memory import _ensure_user_state, get_active_project, get_chat_flags, get_linked_project_ids, set_chat_mode
from app.handlers.import_file import _LAST_DOC
from app.services.artifacts import create_import
from app.config import settings
from app.storage import save_file
from app.ignore import load_pmignore, iter_text_files
from app.utils.zipfix import fix_zip_name, decode_text_bytes
from app.utils.tg import _toast, _safe_delete, _send_ephemeral  # Add this import
from app.utils.callback import safe_callback_data, check_callback_size
from app.utils.unicode_utils import normalize_user_input, normalize_search_term
from app.services.telemetry import event, error
# Service-layer imports
from app.services.llm_pipeline import run_llm_pipeline as svc_run_llm
from app.services.ask_list import list_sources as svc_list_sources
from app.services.ask_answer import compute_cost as svc_compute_cost, build_context_line as svc_build_ctx_line, build_sources_short as svc_build_sources_short
from app.services.ask_selection import toggle_selection as svc_toggle_selection, clear_selection as svc_clear_selection, set_autoclear as svc_set_autoclear, get_selection as svc_get_selection
from app.services.ui_helpers import show_answer_with_bar, restore_answer_with_bar, attach_reply_kb as svc_attach_reply_kb

# Add Berlin timezone
BERLIN = ZoneInfo("Europe/Berlin")

router = Router(name="ask")


async def _debounce_action(user_id: int, run_id: str, key: str, window_ms: int = 1500) -> bool:
    """Return True if action should be debounced (skip now)."""
    import json
    now = int(time.time() * 1000)
    async with session_scope() as st:
        stt = await _ensure_user_state(st, user_id)
        try:
            la = json.loads(stt.last_answer) if stt.last_answer else {}
        except Exception:
            la = {}
        if la.get("run_id") != run_id:
            return False
        locks = la.get("locks") or {}
        until = int(locks.get(key) or 0)
        if now < until:
            return True
        locks[key] = now + window_ms
        la["locks"] = locks
        stt.last_answer = json.dumps(la)
        await st.commit()
        return False


# Helper to fetch preferred model
async def get_preferred_model_helper(user_id: int) -> str:
    async with session_scope() as st:
        from app.services.memory import get_preferred_model
        return await get_preferred_model(st, user_id)


# -------------------- Utils
def _ids_get(stt: UserState) -> list[int]:
    raw = (stt.selected_artifact_ids or "").strip()
    if not raw:
        return []
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return ids

def _ids_set(stt: UserState, ids: Iterable[int]) -> None:
    uniq = sorted({int(i) for i in ids})
    stt.selected_artifact_ids = ",".join(str(i) for i in uniq) if uniq else None

def _budget_for_selection(chunks: Sequence[Chunk]) -> int:
    total = 0
    for ch in chunks:
        try:
            token_count = int(ch.tokens or 0)
            # Ensure we don't have negative token counts
            total += max(0, token_count)
        except Exception:
            # Fallback estimation if tokens is not a valid number
            total += max(1, len(ch.text)//4)
    return total

async def _get_selected_source_ids(st, user_id: int) -> list[int]:
    """Get selected source IDs from database for the user's active project and linked projects."""
    # Get active project and linked project IDs
    active_proj = await get_active_project(st, user_id)
    if not active_proj:
        return []
        
    linked_project_ids = await get_linked_project_ids(st, user_id)
    project_ids = [active_proj.id] + linked_project_ids
    
    # Get user state to retrieve selected artifact IDs
    stt = await _ensure_user_state(st, user_id)
    selected_ids = _ids_get(stt)
    
    # Filter selected IDs to only those in active + linked projects
    if not selected_ids:
        return []
        
    # Verify that selected artifacts belong to active + linked projects
    q = sa.select(Artifact.id).where(
        Artifact.id.in_(selected_ids),
        Artifact.project_id.in_(project_ids)
    )
    result = await st.execute(q)
    valid_ids = [row[0] for row in result.fetchall()]
    
    return valid_ids

async def _auto_delete_message(bot, chat_id: int, message_id: int, delay: float = 3.0):
    """Auto-delete a message after a delay."""
    import asyncio
    await asyncio.sleep(delay)
    with contextlib.suppress(Exception):
        await bot.delete_message(chat_id, message_id)

def _format_selected_summary(artifacts: list[Artifact]) -> str:
    """Format a summary of selected artifacts for display at the top of the panel."""
    if not artifacts:
        return ""
    
    # Show first artifact with its title
    first = artifacts[0]
    title = (first.title or str(first.id))[:50]
    summary = f"Выбрано: {len(artifacts)} • {escape(title)} [{first.id}]"
    
    # If more than one artifact, show count of remaining
    if len(artifacts) > 1:
        summary += f" … + ещё {len(artifacts) - 1}"
    
    return summary

def _panel_kb(selected_count: int, budget_label: str, auto_clear: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    # Step 1: Search is always available
    b.button(text="📋 List", callback_data="aw:list")
    # Step 2: Ask appears only when at least one source is selected
    if selected_count > 0:
        b.button(text="❓ Ask", callback_data="aw:arm")
    b.adjust(2)
    # Row 2
    b.button(text=f"Auto-clear: {'ON' if auto_clear else 'OFF'}", callback_data="aw:autoclear")
    b.button(text="❌ Сброс", callback_data="aw:clear")
    b.adjust(2)
    # Row 3: Import last button
    b.button(text="📥 Import last", callback_data="aw:import_last")
    # Row 4 (label, non-interactive)
    b.button(text=budget_label or "Бюджет: ~0 токенов", callback_data="aw:noop")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()

async def _calc_budget_label(st, sel: list[int]) -> str:
    if not sel:
        return "Бюджет: ~0 токенов"
    q = sa.select(Chunk).where(Chunk.artifact_id.in_(sel))
    chunks = (await st.execute(q)).scalars().all()
    return f"Бюджет: ~{_budget_for_selection(chunks)} токенов"

def _parse_search_query(q: str) -> tuple[list[str], list[str], str | None]:
    """
    Parse search query to extract tag, id, and title filters.
    Returns (tag_filters, id_filters, title_filter)
    """
    # Strip whitespace
    q = q.strip()
    
    # Handle special case: if input is purely numeric, treat as ID search (Hotfix C)
    if re.match(r'^\d+$', q):
        return [], [q], None
    
    # Handle special case: if input starts with #, treat as tag search (Hotfix C)
    if q.startswith('#'):
        tag_query = q[1:].strip()  # Remove the # prefix
        if tag_query:
            return [tag_query], [], None
        return [], [], None
    
    # Otherwise, treat as title search
    return [], [], q

async def _render_panel(m: Message, st, q: str | None = None, page: int = 1, user_id: int | None = None):
    # Use provided user_id if available, otherwise fallback to m.from_user.id
    actual_user_id = user_id if user_id is not None else (m.from_user.id if m.from_user else None)
    if not actual_user_id:
        return
    proj = await get_active_project(st, actual_user_id)
    print(f"DEBUG: proj: {proj}")
    if not proj:
        print(f"DEBUG: No active project found for user {actual_user_id}")
        # Always include reply keyboard to prevent it from disappearing
        await m.answer("Нет активного проекта. Создай или выбери.")
        await svc_attach_reply_kb(m, actual_user_id)
        return
    stt = await _ensure_user_state(st, actual_user_id)
    sel = set(_ids_get(stt))
    
    # Get linked project IDs for proper search scope (Hotfix B)
    linked_project_ids = await get_linked_project_ids(st, actual_user_id)
    # Combine active project ID with linked project IDs
    project_ids = [proj.id] + linked_project_ids
    
    # Log parameters for debugging (Hotfix A)
    print(f"DEBUG: _render_panel - project_ids={project_ids}, search_query='{q}', page={page}")
    
    # Get selected artifacts for summary display
    selected_artifacts = []
    if sel:
        sel_query = sa.select(Artifact).where(Artifact.id.in_(list(sel)))
        selected_artifacts = (await st.execute(sel_query)).scalars().all()

    # Use service for list/search/pagination
    page_size = 5
    res, total_count = await svc_list_sources(project_ids, term=q, page=page, page_size=page_size)
    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

    # Send header with search functionality
    if m.bot:
        # Header message with search button
        header_builder = InlineKeyboardBuilder()
        header_builder.button(text="🔍", callback_data="aw:search")
        header_text = "Найти источник"
        
        # If there's an active search, show search chip
        if q:
            header_text = f'Поиск: "{q}"'
            header_builder.button(text="✖ Очистить", callback_data="aw:clear_search")
            header_builder.adjust(2)
        else:
            header_builder.adjust(1)
            
        # Send header message
        header_msg = await m.bot.send_message(
            chat_id=m.chat.id,
            text=header_text,
            reply_markup=header_builder.as_markup()
        )
        header_msg_id = header_msg.message_id

    # Send each artifact as a separate message with its own inline keyboard
    if m.bot:
        # Delete previous messages if this is a pagination action
        if stt.ask_page_msg_ids:
            try:
                msg_ids = [int(id_str) for id_str in stt.ask_page_msg_ids.split(',') if id_str.strip()]
                for msg_id in msg_ids:
                    await _safe_delete(m.bot, m.chat.id, msg_id)
            except Exception:
                pass  # Ignore errors when deleting messages
        
        # Delete previous footer message if it exists
        if stt.ask_footer_msg_id:
            try:
                await _safe_delete(m.bot, m.chat.id, stt.ask_footer_msg_id)
            except Exception:
                pass  # Ignore errors when deleting messages
        
        # Send new messages
        sent_msg_ids = []
        for i, a in enumerate(res, 1):
            # Create artifact text line in required format (N. <Название> [#tag1 #tag2] (id 689..., 2025-09-16))
            tags = ""
            if a.tags:
                tag_list = [t.name for t in a.tags]
                if tag_list:
                    tags = " [" + " ".join(escape(t) for t in tag_list[:3]) + "]"
            title = escape((a.title or str(a.id))[:80])
            created_at = a.created_at.strftime("%Y-%m-%d") if a.created_at else ""
            text_line = f"{i}. {title}{tags} (id {a.id}{', ' + created_at if created_at else ''})"
            
            # Create inline keyboard for this artifact
            kb = InlineKeyboardBuilder()
            mark = "✅" if a.id in sel else "➕"
            kb.button(text=mark, callback_data=f"aw:toggle:{a.id}")
            kb.button(text="🗑", callback_data=f"aw:delete:{a.id}")
            kb.adjust(2)
            
            # Send message for this artifact
            sent_msg = await m.bot.send_message(
                chat_id=m.chat.id,
                text=text_line,
                reply_markup=kb.as_markup()
            )
            sent_msg_ids.append(str(sent_msg.message_id))
        
        # Store message IDs for future pagination
        stt.ask_page_msg_ids = ",".join(sent_msg_ids) if sent_msg_ids else None
        
        # Pagination footer from service total_count
        total_pages = max(1, total_pages)
        
        footer_msg_id = None
        if total_pages > 1:
            footer_builder = InlineKeyboardBuilder()
            if page > 1:
                footer_builder.button(text="⬅️ Назад", callback_data=f"aw:page:{page-1}")
            footer_builder.button(text=f"Стр. {page}/{total_pages}", callback_data="aw:noop")
            if page < total_pages:
                footer_builder.button(text="Далее ➡️", callback_data=f"aw:page:{page+1}")
            footer_builder.adjust(3)
            
            footer_msg = await m.bot.send_message(
                chat_id=m.chat.id,
                text="Пагинация:",
                reply_markup=footer_builder.as_markup()
            )
            # Store footer message ID
            footer_msg_id = footer_msg.message_id
        else:
            stt.ask_footer_msg_id = None
        
        # Update state with new message IDs
        stt.ask_page_msg_ids = ",".join(sent_msg_ids) if sent_msg_ids else None
        stt.ask_footer_msg_id = footer_msg_id
        
        await st.commit()
    
    # Always send reply keyboard to prevent it from disappearing
    chat_on, *_ = await get_chat_flags(st, actual_user_id)

@router.message(F.text == "❓ ASK‑WIZARD")
async def ask_open(message: Message):
    """Open ASK wizard root. This never calls LLM."""
    if not message.from_user:
        return
    async with session_scope() as st:
        stt = await _ensure_user_state(st, message.from_user.id)
        stt.ask_armed = False
        await st.flush()
        
        # Get active project for display
        active_proj = await get_active_project(st, message.from_user.id)
        proj_name = active_proj.name if active_proj else "Нет проекта"
        
        # Get linked projects for display
        linked_ids = await get_linked_project_ids(st, message.from_user.id)
        linked_status = "Linked: ON" if linked_ids else "Linked: OFF"
        
        # Get selected artifacts count and budget
        selected_ids = _ids_get(stt)
        selected_count = len(selected_ids)
        budget_label = await _calc_budget_label(st, selected_ids)
        
        # Build home panel text
        panel_text = f"ASK‑WIZARD (проект: {proj_name})\n"
        if linked_ids:
            panel_text += f"🔒 {linked_status}\n"
        
        # Build inline keyboard for home panel
        b = InlineKeyboardBuilder()
        
        # Search button (always available) - changed to just "🔍" to match specification
        b.button(text="📋 List", callback_data="aw:list")
        
        # Ask button (only when sources selected)
        if selected_count > 0:
            b.button(text="❓ Ask", callback_data="aw:arm")
        b.adjust(2)
        
        # Auto-clear toggle
        b.button(text=f"Auto-clear: {'ON' if stt.auto_clear_selection else 'OFF'}", callback_data="aw:autoclear")
        
        # Reset button
        b.button(text="❌ Сброс", callback_data="aw:clear")
        b.adjust(2, 2)
        
        # Import last button
        b.button(text="📥 Import last", callback_data="aw:import_last")
        b.adjust(2, 2, 1)
        
        # Budget display (non-interactive)
        b.button(text=budget_label or "Бюджет: ~0 токенов", callback_data="aw:noop")
        b.adjust(2, 2, 1, 1)
        
        await message.answer(
            panel_text,
            reply_markup=b.as_markup(),
        )
        
        # Always include reply keyboard without status message
        await svc_attach_reply_kb(message, message.from_user.id)

@router.callback_query(F.data == "aw:search")
async def ask_search(cb: CallbackQuery):
    if not cb.from_user:
        # Always include reply keyboard
        async with session_scope() as st:
            chat_on, *_ = await get_chat_flags(st, cb.from_user.id if cb.from_user else 0)
            # Removed temporary "..." message
            # if cb.message:
            #     await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
        return await cb.answer("Invalid user")
    await cb.answer()
    if cb.message:
        prompt_msg = await cb.message.answer("Введи название, #тег или id:...", reply_markup=ForceReply(selective=True))
        
        # Set the awaiting_ask_search flag and store prompt message ID
        async with session_scope() as st:
            stt = await _ensure_user_state(st, cb.from_user.id)
            stt.awaiting_ask_search = True
            # Store the prompt message ID for later cleanup
            # Note: We'll need to store this in a different way since UserState doesn't have ask_prompt_msg_id
            # For now, we'll handle cleanup in the reply handler
            await st.commit()
        

@router.message(F.reply_to_message & (F.reply_to_message.text == "Введи название, #тег или id:..."))
async def ask_search_reply(message: Message):
    if not message.from_user or not message.text:
        return
    q = normalize_search_term(message.text)
    async with session_scope() as st:
        # Reset the awaiting_ask_search flag
        stt = await _ensure_user_state(st, message.from_user.id)
        stt.awaiting_ask_search = False
        
        # Log search parameters for debugging (Hotfix A)
        active_project = await get_active_project(st, message.from_user.id)
        active_project_id = active_project.id if active_project else None
        linked_project_ids = await get_linked_project_ids(st, message.from_user.id)
        
        # Parse the search query to determine mode
        if q.isdigit():
            mode = "id"
        elif q.startswith('#') and len(q) > 1:
            mode = "tag"
        else:
            mode = "name"
        
        print(f"DEBUG: ask_search_reply - mode={mode}, term='{q}', active_project_id={active_project_id}, linked_project_ids={linked_project_ids}, user_id={message.from_user.id}")
        
        await st.commit()
        
        await _render_panel(message, st, q=q, page=1, user_id=message.from_user.id if message.from_user else None)
        
        # Always include reply keyboard
        chat_on, *_ = await get_chat_flags(st, message.from_user.id)
        # Removed temporary "..." message
        # await message.answer("...", reply_markup=main_reply_kb(chat_on))
        
        # Delete the prompt message and user's reply message
        if message.reply_to_message and message.bot:
            await _safe_delete(message.bot, message.chat.id, message.reply_to_message.message_id)
        if message.message_id and message.bot:
            await _safe_delete(message.bot, message.chat.id, message.message_id)

@router.callback_query(F.data == "aw:list")
async def ask_open_list(cb: CallbackQuery):
    """Open the ASK list view (page 1) from the home panel. No LLM involved."""
    if not cb.from_user:
        # Always include reply keyboard
        async with session_scope() as st:
            chat_on, *_ = await get_chat_flags(st, cb.from_user.id if cb.from_user else 0)
            # Removed temporary "..." message
            # if cb.message:
            #     await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
        return await cb.answer("Invalid user")
    async with session_scope() as st:
        # Debug: Check if we can get the active project
        active_proj = await get_active_project(st, cb.from_user.id)
        print(f"DEBUG: active_proj: {active_proj}")
        if active_proj:
            print(f"DEBUG: active_proj.id: {active_proj.id}, active_proj.name: {active_proj.name}")
        
        if cb.message and isinstance(cb.message, Message):
            await _render_panel(cb.message, st, q=None, page=1, user_id=cb.from_user.id)
        # Always include reply keyboard
        # Removed temporary "..." message
        # chat_on, *_ = await get_chat_flags(st, cb.from_user.id)
        # if cb.message and isinstance(cb.message, Message):
        #     await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
    await cb.answer()

@router.callback_query(F.data.startswith("aw:page:"))
async def ask_page(cb: CallbackQuery):
    if not cb.data:
        page = 1
    else:
        try:
            page = int(cb.data.split(":", 2)[-1])
        except Exception:
            page = 1
    async with session_scope() as st:
        if cb.message and isinstance(cb.message, Message):
            await _render_panel(cb.message, st, q=None, page=page, user_id=cb.from_user.id if cb.from_user else None)
            
        # Always include reply keyboard
        # Removed temporary "..." message
        # chat_on, *_ = await get_chat_flags(st, cb.from_user.id if cb.from_user else 0)
        # if cb.message and isinstance(cb.message, Message):
        #     await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
    await cb.answer()

@router.callback_query(F.data.startswith("aw:toggle:"))
async def ask_toggle(cb: CallbackQuery):
    if not (cb.from_user and cb.data):
        # Always include reply keyboard
        # Removed temporary "..." message
        # async with session_scope() as st:
        #     chat_on, *_ = await get_chat_flags(st, cb.from_user.id if cb.from_user else 0)
        #     if cb.message:
        #         await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
        return await cb.answer("Invalid")
    try:
        art_id = int(cb.data.split(":", 2)[-1])
    except Exception:
        # Always include reply keyboard
        # Removed temporary "..." message
        # async with session_scope() as st:
        #     chat_on, *_ = await get_chat_flags(st, cb.from_user.id if cb.from_user else 0)
        #     if cb.message:
        #         await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
        return await cb.answer("Bad id")
    async with session_scope() as st:
        # Use service toggle
        added = await svc_toggle_selection(st, cb.from_user.id, art_id)
        action_text = "Добавлен в выбор" if added else "Убран из выбора"
        new_icon = "✅" if added else "➕"
        await st.commit()
        try:
            event("ask_selection_toggle", user_id=cb.from_user.id, chat_id=(cb.message.chat.id if cb.message and cb.message.chat else 0), artifact_id=art_id, added=added)
        except Exception:
            pass
        
        # Update the inline keyboard of the current message to show the new icon (instant toggle) (Hotfix E)
        if cb.message and isinstance(cb.message, Message) and cb.message.bot:
            # Create updated inline keyboard with new icon
            builder = InlineKeyboardBuilder()
            builder.button(text=new_icon, callback_data=f"aw:toggle:{art_id}")
            builder.button(text="🗑", callback_data=f"aw:delete:{art_id}")
            builder.adjust(2)
            
            try:
                await cb.message.bot.edit_message_reply_markup(
                    chat_id=cb.message.chat.id,
                    message_id=cb.message.message_id,
                    reply_markup=builder.as_markup()
                )
                # Answer callback without showing alert for instant toggle (Hotfix E)
                await cb.answer(action_text, show_alert=False)
            except Exception as e:
                # Log error but still answer the callback
                print(f"DEBUG: Error updating inline keyboard: {e}")
                await cb.answer(action_text, show_alert=True)
        
        # Always include reply keyboard
        # Removed temporary "..." message
        # chat_on, *_ = await get_chat_flags(st, cb.from_user.id)
        # if cb.message and isinstance(cb.message, Message):
        #     await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
    # Callback already answered above, no need to answer again

@router.callback_query(F.data.startswith("aw:delete:"))
async def ask_delete(cb: CallbackQuery):
    if not (cb.from_user and cb.data):
        # Always include reply keyboard
        # Removed temporary "..." message
        # async with session_scope() as st:
        #     chat_on, *_ = await get_chat_flags(st, cb.from_user.id if cb.from_user else 0)
        #     if cb.message:
        #         await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
        return await cb.answer("Invalid")
    try:
        art_id = int(cb.data.split(":", 2)[-1])
    except Exception:
        # Always include reply keyboard
        # Removed temporary "..." message
        # async with session_scope() as st:
        #     chat_on, *_ = await get_chat_flags(st, cb.from_user.id if cb.from_user else 0)
        #     if cb.message:
        #         await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
        return await cb.answer("Bad id")
    
    async with session_scope() as st:
        # Delete the artifact
        artifact = await st.get(Artifact, art_id)
        if artifact:
            await st.delete(artifact)
            await st.commit()
            # Show toast message instead of creating new message
            await _toast(cb, "Артефакт удален")
        else:
            await _toast(cb, "Артефакт не найден")
        
        # Rerender current page
        if cb.message and isinstance(cb.message, Message):
            await _render_panel(cb.message, st, q=None, page=1, user_id=cb.from_user.id if cb.from_user else None)
            
        # Always include reply keyboard
        # Removed temporary "..." message
        # chat_on, *_ = await get_chat_flags(st, cb.from_user.id)
        # if cb.message and isinstance(cb.message, Message):
        #     await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
    # Callback already answered above

@router.callback_query(F.data == "aw:autoclear")
async def ask_autoclear(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.from_user:
        return await cb.answer("Invalid user")
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        new_state = await svc_set_autoclear(st, cb.from_user.id, not bool(stt.auto_clear_selection))
        await st.commit()
        budget_label = await _calc_budget_label(st, _ids_get(stt))
        try:
            event("ask_selection_autoclear", user_id=cb.from_user.id, value=new_state)
        except Exception:
            pass
        if cb.message:
            await cb.message.answer(
                "ASK панель:",
                reply_markup=_panel_kb(len(_ids_get(stt)), budget_label, stt.auto_clear_selection),
            )
            
        # Always include reply keyboard without status message
        if cb.message:
            await svc_attach_reply_kb(cb.message, cb.from_user.id)
    await cb.answer()

@router.callback_query(F.data == "aw:clear")
async def ask_clear(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.from_user:
        return await cb.answer("Invalid user")
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        await svc_clear_selection(st, cb.from_user.id)
        stt.ask_armed = False
        await st.commit()
        try:
            event("ask_selection_clear", user_id=cb.from_user.id)
        except Exception:
            pass
        if cb.message:
            await cb.message.answer(
                "ASK панель:",
                reply_markup=_panel_kb(0, "Бюджет: ~0 токенов", stt.auto_clear_selection),
            )
            
        # Always include reply keyboard without status message
        if cb.message:
            await svc_attach_reply_kb(cb.message, cb.from_user.id)
    await cb.answer("Очищено")

@router.callback_query(F.data == "aw:arm")
async def ask_arm(cb: CallbackQuery, state: FSMContext):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.from_user:
        return await cb.answer("Invalid user")
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        sel = _ids_get(stt)
        if not sel:
            return await cb.answer("Не выбрано ни одного источника", show_alert=True)
        stt.ask_armed = True
        await st.commit()
        chat_on, *_ = await get_chat_flags(st, cb.from_user.id)
        if cb.message:
            if not chat_on:
                # Create inline button to toggle chat
                inline_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Включить чат", callback_data="ask:chat:on")]
                ])
                # Store message ID for later editing
                prompt_msg = await cb.message.answer(
                    "Включи чат (кнопка внизу), затем отправь вопрос", 
                    reply_markup=inline_kb
                )
                # Store prompt message ID for later editing
                stt.ask_prompt_msg_id = prompt_msg.message_id
                await st.commit()
            else:
                # Send ForceReply prompt and store its message ID
                prompt_msg = await cb.message.answer("Введите вопрос…", reply_markup=ForceReply(selective=True))
                # Store prompt message ID for later deletion
                stt.ask_prompt_msg_id = prompt_msg.message_id
                await st.commit()
                # Also set the awaiting flag in FSM
                await state.update_data(awaiting_ask_question=True)
                
    await cb.answer()

# HOTFIX: callback ask:chat:on
@router.callback_query(F.data == "ask:chat:on")
async def ask_toggle_chat(cb: CallbackQuery, state: FSMContext):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    
    user_id = cb.from_user.id
    
    # 1. Set both FSM flags as required
    await state.update_data(chat_on=True, awaiting_ask_question=True)
    
    # 2. DB-флаг
    try:
        async with session_scope() as st:
            await set_chat_mode(st, user_id, on=True)
            await st.commit()
    except Exception as e:
        return await cb.answer(f"Ошибка включения чата: {str(e)}")
    
    # 3. Перерисовать нижнюю реплай-клавиатуру
    try:
        if cb.message and isinstance(cb.message, Message):
            await cb.message.answer("Чат: ON")
            await svc_attach_reply_kb(cb.message, cb.from_user.id)
    except Exception as e:
        pass  # Continue even if we can't update the keyboard
    
    # 4. Удалить подсказку «включи чат…»
    try:
        if cb.message and isinstance(cb.message, Message):
            await cb.message.delete()
    except Exception:
        pass  # Continue even if we can't delete the message
    
    # 5. Выдать ForceReply «Введите вопрос…» и запомнить ask_prompt_msg_id
    try:
        if cb.message and isinstance(cb.message, Message):
            prompt = await cb.message.answer("Введите вопрос…", reply_markup=ForceReply(selective=True))
            await state.update_data(ask_prompt_msg_id=prompt.message_id)
    except Exception as e:
        return await cb.answer(f"Ошибка при создании запроса: {str(e)}")
    
    # 6. Всегда вызвать await cb.answer()
    await cb.answer()

@router.callback_query(F.data == "aw:import_last")
async def ask_import_last(cb: CallbackQuery):
    """Handler for importing the last document from ASK wizard."""
    # Import the last document by calling the wizard_import_last function directly
    from app.handlers.menu import wizard_import_last
    return await wizard_import_last(cb)

@router.callback_query(F.data == "aw:clear_search")
async def ask_clear_search(cb: CallbackQuery):
    """Clear search filter and re-render panel."""
    if not cb.from_user:
        # Always include reply keyboard
        # Removed temporary "..." message
        # async with session_scope() as st:
        #     chat_on, *_ = await get_chat_flags(st, cb.from_user.id if cb.from_user else 0)
        #     if cb.message:
        #         await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
        return await cb.answer("Invalid user")
    
    async with session_scope() as st:
        if cb.message and isinstance(cb.message, Message):
            await _render_panel(cb.message, st, q=None, page=1)
            
        # Always include reply keyboard
        # Removed temporary "..." message
        # chat_on, *_ = await get_chat_flags(st, cb.from_user.id)
        # if cb.message and isinstance(cb.message, Message):
        #     await cb.message.answer("...", reply_markup=main_reply_kb(chat_on))
    await cb.answer()

# Public entry used by chat free-text handler. LLM calls are DISABLED here on purpose.
async def run_question_with_selection(message: Message, prompt: str):
    if not message.from_user:
        return
    async with session_scope() as st:
        stt = await _ensure_user_state(st, message.from_user.id)
        sel = _ids_get(stt)
        # Compose a debug-only echo with selected ids. Do not call any LLM here.
        if not sel:
            # Always include reply keyboard to prevent it from disappearing
            await message.answer("ASK: источники не выбраны (LLM отключён, тест-режим).")
            await svc_attach_reply_kb(message, message.from_user.id)
            return
        # Escape prompt in simple way (no HTML parse here to avoid injection)
        try:
            from html import escape as _esc
            safe_prompt = _esc(prompt)
        except Exception:
            safe_prompt = prompt
        response_text = (
            "🧪 TEST: LLM отключён.\n"
            f"Вопрос: {safe_prompt}\n"
            f"Источники: {', '.join(map(str, sel))}"
        )
        await message.answer(response_text)
        
        # Reset armed and optionally clear selection
        if stt.auto_clear_selection:
            _ids_set(stt, [])
            # Re-render panel if auto-clear is on
            budget_label = await _calc_budget_label(st, [])
            controls = _panel_kb(0, budget_label, stt.auto_clear_selection)
            
            # Edit existing panel or send new one
            if stt.last_panel_msg_id and message.chat and message.bot:
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=stt.last_panel_msg_id,
                        text="ASK панель:",
                        reply_markup=controls
                    )
                except Exception:
                    # If editing fails, send a new message
                    await message.answer("ASK панель:", reply_markup=controls)
            else:
                await message.answer("ASK панель:", reply_markup=controls)
        
        stt.ask_armed = False
        await st.commit()
        
        # Always include reply keyboard to prevent it from disappearing
        chat_on, *_ = await get_chat_flags(st, message.from_user.id)
        # Removed temporary "..." message - using proper keyboard only

# FIX 3: Delete with confirmation and reply keyboard restoration
@router.callback_query(F.data.startswith("ask:answer:delete:"))
async def answer_delete_confirm(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.data:
        return await cb.answer("Invalid data")
    
    # Extract run_id from callback data
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Invalid callback data")
    
    run_id = parts[3]
    
    # Get user state to retrieve last answer data
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        
        # Parse last_answer JSON data
        import json
        try:
            last_answer = json.loads(stt.last_answer) if stt.last_answer else {}
        except (json.JSONDecodeError, TypeError):
            last_answer = {}
        
        # Check if run_id matches
        if last_answer.get("run_id") != run_id:
            return await cb.answer("Нет контекста", show_alert=True)
        
        # FIX 3: Show confirmation dialog with text + two buttons
        confirm_kb = InlineKeyboardBuilder()
        confirm_kb.button(text="Да", callback_data=f"ask:answer:delete:confirm:{run_id}")
        confirm_kb.button(text="Отмена", callback_data=f"ask:answer:delete:cancel:{run_id}")
        confirm_kb.adjust(2)
        
        if cb.message and isinstance(cb.message, Message):
            try:
                await cb.message.edit_text(
                    "Удалить ответ и мой вопрос?",
                    reply_markup=confirm_kb.as_markup()
                )
                print(f"DEBUG DEL confirm run={run_id}")
                try:
                    event("delete_confirm", user_id=cb.from_user.id, run_id=run_id)
                except Exception:
                    pass
                await cb.answer()
            except Exception as e:
                await cb.answer(f"Error showing confirmation: {str(e)}", show_alert=True)
        else:
            await cb.answer("Invalid message")

@router.callback_query(F.data.startswith("ask:answer:delete:confirm:"))
async def answer_delete_execute(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.data:
        return await cb.answer("Invalid data")
    
    # Extract run_id from callback data
    parts = cb.data.split(":")
    if len(parts) < 5:
        return await cb.answer("Invalid callback data")
    
    run_id = parts[4]
    
    # Get user state to retrieve last answer data
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        
        # Parse last_answer JSON data
        import json
        try:
            last_answer = json.loads(stt.last_answer) if stt.last_answer else {}
        except (json.JSONDecodeError, TypeError):
            last_answer = {}
        
        # Check if run_id matches
        if last_answer.get("run_id") != run_id:
            return await cb.answer("Нет контекста", show_alert=True)
        
        # Delete messages
        if cb.message and isinstance(cb.message, Message) and cb.message.bot:
            try:
                # Delete the answer message
                with contextlib.suppress(Exception):
                    await cb.message.delete()
                
                # Explicitly delete the original question upon confirmation
                q_mid = last_answer.get("question_msg_id")
                if q_mid:
                    with contextlib.suppress(Exception):
                        await cb.message.bot.delete_message(cb.message.chat.id, q_mid)
                
                # Delete any ForceReply prompt messages
                pid = stt.ask_prompt_msg_id
                if pid:
                    with contextlib.suppress(Exception):
                        await cb.message.bot.delete_message(cb.message.chat.id, pid)
                
                # Clear last answer data and prompt message IDs
                stt.last_answer = None
                stt.ask_prompt_msg_id = None
                stt.ask_refine_run_id = None
                await st.commit()
                
                # FIX 3: Send status-strip message with reply keyboard to restore it
                await cb.message.bot.send_message(
                    chat_id=cb.message.chat.id,
                    text="Удалено"
                )
                await svc_attach_reply_kb(cb.message, cb.from_user.id if cb.from_user else 0)
                try:
                    event("delete_done", user_id=cb.from_user.id, run_id=run_id)
                except Exception:
                    pass
                await cb.answer("Удалено")
            except Exception as e:
                await cb.answer(f"Error deleting messages: {str(e)}", show_alert=True)
        else:
            await cb.answer("Invalid message or bot")

@router.callback_query(F.data.startswith("ask:answer:delete:cancel:"))
async def answer_delete_cancel(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.data:
        return await cb.answer("Invalid data")
    
    # Extract run_id from callback data
    parts = cb.data.split(":")
    if len(parts) < 5:
        return await cb.answer("Invalid callback data")
    
    run_id = parts[4]
    
    # Get user state to retrieve last answer data with fallback protection
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        
        # Parse last_answer JSON data to get saved/pinned status
        import json
        saved = False
        pinned = False
        
        try:
            last_answer = json.loads(stt.last_answer) if stt.last_answer else {}
            # Verify run_id matches - if not, use defaults but still restore keyboard
            if last_answer.get("run_id") == run_id:
                saved = last_answer.get("saved", False)
                pinned = last_answer.get("pinned", False)
            else:
                # Context mismatch - log but continue with defaults
                print(f"DEBUG: Cancel context mismatch - expected {run_id}, got {last_answer.get('run_id')}")
        except (json.JSONDecodeError, TypeError):
            # JSON parsing error - log but continue with defaults
            print(f"DEBUG: Cancel JSON parsing error for run_id {run_id}")
        
        # Always restore keyboard, even if context is missing (protective fallback)
        kb = answer_actions_kb(run_id, saved=saved, pinned=pinned)
        
        if cb.message and isinstance(cb.message, Message):
            try:
                await restore_answer_with_bar(cb, kb, cb.from_user.id)
                try:
                    event("delete_cancel", user_id=cb.from_user.id, run_id=run_id)
                except Exception:
                    pass
                print(f"DEBUG DEL cancel run={run_id}")
                await cb.answer("Отменено")
            except Exception as e:
                # Even if restore fails, still answer the callback
                print(f"DEBUG: Error restoring keyboard: {e}")
                await cb.answer("Отменено")
        else:
            await cb.answer("Отменено")

# HOTFIX: единая панель
def answer_actions_kb(run_id: str, *, saved: bool = False, pinned: bool = False, artifact_id: int | None = None) -> InlineKeyboardMarkup:
    """Create inline keyboard with answer action buttons.
    If artifact_id is provided, show 🗂 Open.
    """
    builder = InlineKeyboardBuilder()
    if artifact_id:
        builder.button(text="🗂", callback_data=f"ask:answer:open:{artifact_id}")
    builder.button(text=("✅" if saved else "💾"), callback_data=f"ask:answer:save:{run_id}")
    builder.button(text=("📍" if pinned else "📌"), callback_data=f"ask:answer:pin:{run_id}")
    builder.button(text="🧾", callback_data=f"ask:answer:summary:{run_id}")
    builder.button(text="🔁", callback_data=f"ask:answer:refine:{run_id}")
    builder.button(text="📚", callback_data=f"ask:answer:sources:{run_id}")
    builder.button(text="🗑", callback_data=f"ask:answer:delete:{run_id}")
    builder.adjust(6)  # One row of 6 buttons
    return builder.as_markup()


# Add answer action handlers
# HOTFIX: sources overlay
@router.callback_query(F.data.startswith("ask:answer:sources:"))
async def answer_sources(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.data:
        return await cb.answer("Invalid data")
    
    # Extract run_id from callback data
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Invalid callback data")
    
    run_id = parts[3]
    page = 1
    if len(parts) >= 6 and parts[2] == "answer" and parts[3] == "sources" and parts[4] == "p":
        run_id = parts[5]
        try:
            page = int(parts[6]) if len(parts) >= 7 else 1
        except Exception:
            page = 1
    
    # Get user state to retrieve last answer data
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        
        # Parse last_answer JSON data
        import json
        try:
            last_answer = json.loads(stt.last_answer) if stt.last_answer else {}
        except (json.JSONDecodeError, TypeError):
            last_answer = {}
        
        # Check if run_id matches
        if last_answer.get("run_id") != run_id:
            # fallback: try to continue with stored keyboard
            saved = False
            pinned = False
            try:
                la = json.loads(stt.last_answer) if stt.last_answer else {}
                saved = la.get("saved", False); pinned = la.get("pinned", False)
            except Exception:
                pass
            if cb.message and isinstance(cb.message, Message):
                try:
                    await cb.message.edit_reply_markup(reply_markup=answer_actions_kb(run_id, saved=saved, pinned=pinned))
                except Exception:
                    pass
            return await _toast(cb, "Контекст истёк")
        
        # Get source IDs
        src_ids = last_answer.get("source_ids") or []
        if not src_ids:
            return await _toast(cb, "Контекст истёк")
        
        # Load artifact titles for nicer chips
        titles = {}
        try:
            q = sa.select(Artifact.id, Artifact.title).where(Artifact.id.in_(src_ids))
            rows = (await st.execute(q)).all()
            titles = {rid: (ttl or str(rid)) for rid, ttl in rows}
        except Exception:
            titles = {rid: str(rid) for rid in src_ids}
        
        # Pagination 5 per page
        page_size = 5
        total = len(src_ids)
        total_pages = (total + page_size - 1) // page_size
        page = max(1, min(page, max(total_pages, 1)))
        start = (page - 1) * page_size
        items = src_ids[start:start+page_size]
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        for sid in items:
            short = (titles.get(sid, str(sid)) or str(sid))
            if len(short) > 18:
                short = short[:18] + " …"
            kb.button(text=f"#{short} id{sid}", callback_data=f"ask:answer:srcinfo:{run_id}:{sid}")
        # nav row
        if total_pages > 1:
            if page > 1:
                kb.button(text="⬅️", callback_data=f"ask:answer:sources:p:{run_id}:{page-1}")
            kb.button(text=f"{page}/{total_pages}", callback_data=f"ask:noop:{run_id}")
            if page < total_pages:
                kb.button(text="➡️", callback_data=f"ask:answer:sources:p:{run_id}:{page+1}")
            kb.adjust(3)
        # back
        kb.button(text="↩️ Назад", callback_data=f"ask:answer:sources:back:{run_id}")
        # layout
        kb.adjust(1, 1)
        
        # Update message with overlay keyboard
        if cb.message and isinstance(cb.message, Message):
            try:
                await cb.message.edit_reply_markup(reply_markup=kb.as_markup())
                try:
                    event("sources_open", user_id=cb.from_user.id, run_id=run_id, page=page, total=total)
                except Exception:
                    pass
                await cb.answer()
            except Exception as e:
                await cb.answer(f"Error updating keyboard: {str(e)}", show_alert=True)
        else:
            await cb.answer("Invalid message")

@router.callback_query(F.data.startswith("ask:answer:sources:back:"))
async def answer_sources_back(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.data:
        return await cb.answer("Invalid data")
    
    # Extract run_id from callback data
    parts = cb.data.split(":")
    if len(parts) < 5:
        return await cb.answer("Invalid callback data")
    
    run_id = parts[4]
    
    # Get user state to retrieve last answer data
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        
        # Parse last_answer JSON data to get saved/pinned status
        import json
        try:
            last_answer = json.loads(stt.last_answer) if stt.last_answer else {}
        except (json.JSONDecodeError, TypeError):
            last_answer = {}
        
        saved = last_answer.get("saved", False)
        pinned = last_answer.get("pinned", False)
        artifact_id = last_answer.get("artifact_id")
        
        # Restore original answer actions keyboard
        kb = answer_actions_kb(run_id, saved=saved, pinned=pinned, artifact_id=artifact_id)
        # Keep context alive; do not clear last_answer here
        
        if cb.message and isinstance(cb.message, Message):
            try:
                await restore_answer_with_bar(cb, kb, cb.from_user.id)
                try:
                    event("sources_back", user_id=cb.from_user.id, run_id=run_id)
                except Exception:
                    pass
                await cb.answer()
            except Exception as e:
                await cb.answer(f"Error updating keyboard: {str(e)}", show_alert=True)
        else:
            await cb.answer("Invalid message")

# HOTFIX: save action
@router.callback_query(F.data.startswith("ask:answer:save:"))
async def answer_save(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.data:
        return await cb.answer("Invalid data")
    
    # Extract run_id from callback data
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Invalid callback data")
    
    run_id = parts[3]
    
    # Get user state to retrieve last answer data
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        
        # Parse last_answer JSON data
        import json
        try:
            last_answer = json.loads(stt.last_answer) if stt.last_answer else {}
        except (json.JSONDecodeError, TypeError):
            last_answer = {}
        
        # Check if run_id matches
        if last_answer.get("run_id") != run_id:
            return await cb.answer("Нет контекста", show_alert=True)
        
        # Idempotent save: create artifact if not exists
        artifact_id = last_answer.get("artifact_id")
        if not artifact_id:
            proj = await get_active_project(st, cb.from_user.id)
            if not proj:
                return await cb.answer("Нет активного проекта", show_alert=True)
            text = (cb.message.text or cb.message.caption or "") if cb.message and isinstance(cb.message, Message) else ""
            title = text.splitlines()[0][:128] if text else "Chat answer"
            art = Artifact(
                project_id=proj.id,
                kind="answer",
                title=title,
                raw_text=text,
                pinned=False,
                related_source_ids={"ids": last_answer.get("source_ids", [])},
                run_meta=last_answer.get("run_meta") or {}
            )
            st.add(art)
            await st.flush()
            artifact_id = art.id
            last_answer["artifact_id"] = artifact_id
        
        last_answer["saved"] = True
        stt.last_answer = json.dumps(last_answer)
        await st.commit()
        
        # Update the keyboard to show saved state + Open
        kb = answer_actions_kb(run_id, saved=True, pinned=last_answer.get("pinned", False), artifact_id=artifact_id)
        
        if cb.message and isinstance(cb.message, Message):
            try:
                await cb.message.edit_reply_markup(reply_markup=kb)
                await svc_attach_reply_kb(cb.message, cb.from_user.id)
                try:
                    event("save_done", user_id=cb.from_user.id, run_id=run_id, artifact_id=artifact_id)
                except Exception:
                    pass
                await cb.answer("Сохранено ✅")
            except Exception:
                await cb.answer("Сохранено ✅")
        else:
            await cb.answer("Invalid message")

# HOTFIX: pin action
@router.callback_query(F.data.startswith("ask:answer:pin:"))
async def answer_pin(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.data:
        return await cb.answer("Invalid data")
    
    # Extract run_id from callback data
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Invalid callback data")
    
    run_id = parts[3]
    
    # Get user state to retrieve last answer data
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        
        # Parse last_answer JSON data
        import json
        try:
            last_answer = json.loads(stt.last_answer) if stt.last_answer else {}
        except (json.JSONDecodeError, TypeError):
            last_answer = {}
        
        # Check if run_id matches
        if last_answer.get("run_id") != run_id:
            return await cb.answer("Нет контекста", show_alert=True)
        
        # Toggle pinned state
        pinned = not last_answer.get("pinned", False)
        last_answer["pinned"] = pinned
        stt.last_answer = json.dumps(last_answer)
        await st.commit()
        
        # Update the keyboard to show pinned state
        kb = answer_actions_kb(run_id, saved=last_answer.get("saved", False), pinned=pinned)
        
        if cb.message and isinstance(cb.message, Message):
            try:
                await cb.message.edit_reply_markup(reply_markup=kb)
                await svc_attach_reply_kb(cb.message, cb.from_user.id)
                try:
                    event("pin", user_id=cb.from_user.id, run_id=run_id, pinned=pinned)
                except Exception:
                    pass
                await cb.answer("Закреплено 📌" if pinned else "Откреплено")
            except Exception as e:
                await cb.answer(f"Error updating keyboard: {str(e)}", show_alert=True)
        else:
            await cb.answer("Invalid message")

# HOTFIX: summary action
@router.callback_query(F.data.startswith("ask:answer:srcinfo:"))
async def answer_srcinfo(cb: CallbackQuery):
    if not cb.from_user or not cb.data:
        return await cb.answer("Invalid data")
    parts = cb.data.split(":")
    if len(parts) < 5:
        return await cb.answer("Invalid callback data")
    run_id = parts[3]
    try:
        sid = int(parts[4])
    except Exception:
        return await cb.answer("Invalid source id")
    async with session_scope() as st:
        # Load artifact details
        art = await st.get(Artifact, sid)
        if not art:
            return await cb.answer("Источник не найден", show_alert=True)
        title = (art.title or str(sid))
        tags = [t.name for t in (art.tags or [])]
        tag_str = ("#" + " #".join(tags)) if tags else "(нет тегов)"
        detail = f"{title}\nid{sid}\n{tag_str}"
        # Telegram alert limit ~200 chars; truncate if needed
        if len(detail) > 190:
            detail = detail[:187] + "…"
        await cb.answer(detail, show_alert=True)

@router.callback_query(F.data.startswith("ask:answer:summary:"))
async def answer_summary(cb: CallbackQuery):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.data:
        return await cb.answer("Invalid data")
    
    # Extract run_id from callback data
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Invalid callback data")
    
    run_id = parts[3]
    
    # Get user state to retrieve last answer data
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        
        # Parse last_answer JSON data
        import json
        try:
            last_answer = json.loads(stt.last_answer) if stt.last_answer else {}
        except (json.JSONDecodeError, TypeError):
            last_answer = {}
        
        # Check if run_id matches
        if last_answer.get("run_id") != run_id:
            return await cb.answer("Нет контекста", show_alert=True)
        
        # Get the answer text to summarize
        answer_text = ""
        if cb.message and isinstance(cb.message, Message):
            answer_text = cb.message.text or cb.message.caption or ""
        
        # Show a message that we're generating summary
        try:
            event("summary", user_id=cb.from_user.id, run_id=run_id, text_len=len(answer_text or ""))
        except Exception:
            pass
        if cb.message and isinstance(cb.message, Message):
            await cb.message.answer("Генерирую краткое содержание...")
        
        await cb.answer("Генерирую краткое содержание...")

# FIX 8: Refine with original question text insertion
@router.callback_query(F.data.startswith("ask:answer:refine:"))
async def answer_refine(cb: CallbackQuery, state: FSMContext):
    if not cb.from_user:
        return await cb.answer("Invalid user")
    if not cb.data:
        return await cb.answer("Invalid data")
    
    # Extract run_id from callback data
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Invalid callback data")
    
    run_id = parts[3]
    
    # Get user state to retrieve last answer data
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        
        # Parse last_answer JSON data
        import json
        try:
            last_answer = json.loads(stt.last_answer) if stt.last_answer else {}
        except (json.JSONDecodeError, TypeError):
            last_answer = {}
        
        # Check if run_id matches
        if last_answer.get("run_id") != run_id:
            return await cb.answer("Нет контекста", show_alert=True)
        
        # Show ForceReply prompt for refinement (single message)
        if cb.message and isinstance(cb.message, Message) and cb.message.bot:
            try:
                tip = await cb.message.answer("Уточните запрос…", reply_markup=ForceReply(selective=True))
                # Store prompt message ID and refine run ID in user state
                stt.ask_prompt_msg_id = tip.message_id
                stt.ask_refine_run_id = run_id
                await st.commit()
                # Set FSM state for refine
                await state.update_data(awaiting_ask_question=True, ask_prompt_msg_id=tip.message_id)
                try:
                    event("refine_open", user_id=cb.from_user.id, run_id=run_id)
                except Exception:
                    pass
                await cb.answer()
            except Exception as e:
                await cb.answer(f"Error showing refine prompt: {str(e)}", show_alert=True)
        else:
            await cb.answer("Invalid message or bot")

# HOTFIX: Question receiver - не удаляем сообщение пользователя, убираем только ForceReply, зовём LLM
@router.message()
async def ask_question_receiver(msg: Message, state: FSMContext):
    if not msg.from_user or not msg.text:
        return
        
    # FIX 10: Anti-duplicate ASK - check if already processing
    async with session_scope() as st:
        stt = await _ensure_user_state(st, msg.from_user.id)
        # Check if already processing a question (in-flight protection)
        if hasattr(stt, 'ask_inflight') and stt.ask_inflight:
            if msg.bot:
                temp_msg = await msg.answer("Обрабатываю предыдущий запрос...")
                asyncio.create_task(_auto_delete_message(msg.bot, msg.chat.id, temp_msg.message_id, delay=3.0))
            return
    
    # Check both FSM flag and reply-to-message conditions
    data = await state.get_data()
    prompt_id = data.get("ask_prompt_msg_id")
    by_state = bool(data.get("awaiting_ask_question"))
    
    # FIX 2: Check both FSM state and DB state for prompt message ID
    async with session_scope() as st:
        stt = await _ensure_user_state(st, msg.from_user.id)
        db_prompt_id = stt.ask_prompt_msg_id
        
    by_reply = bool(msg.reply_to_message) and (
        (prompt_id and msg.reply_to_message.message_id == prompt_id) or
        (db_prompt_id and msg.reply_to_message.message_id == db_prompt_id)
    )
    
    if not (by_state or by_reply):
        return  # не наш кейс — пропускаем дальше

    # Capture ForceReply prompt id; remove only on success to keep ForceReply if LLM fails
    pid = data.get("ask_prompt_msg_id") or db_prompt_id

    # гейт: чат должен быть ON (DB-источник истины)
    async with session_scope() as st:
        chat_on, *_ = await get_chat_flags(st, msg.from_user.id)
        active_proj = await get_active_project(st, msg.from_user.id)
        linked_project_ids = await get_linked_project_ids(st, msg.from_user.id)
        project_ids = [active_proj.id] + linked_project_ids if active_proj else []
        # собрать выбранные источники из БД (не из FSM!)
        selected_ids = await _get_selected_source_ids(st, msg.from_user.id)
        
    # DEBUG ASK: chat_on=<bool> project_ids=[…] selected=[…]
    print(f"DEBUG ASK: chat_on={chat_on} project_ids={project_ids} selected={selected_ids}")
    
    if not chat_on:
        # Используем эфемерное уведомление вместо залипающего сообщения
        if msg.bot:
            temp_msg = await msg.answer("Включи чат кнопкой внизу или через ASK‑панель.")
            # Авто-удаляем через 3 секунды
            import asyncio
            asyncio.create_task(_auto_delete_message(msg.bot, msg.chat.id, temp_msg.message_id, delay=3.0))
        return

    # подготовка ответа (одно сообщение, потом редактируем)
    if not msg.bot:
        return
    prep = await msg.answer("Готовлю ответ…")

    # DEBUG ASK: chat_on=<bool> project_ids=[…] selected=[…]
    print(f"DEBUG ASK: chat_on={chat_on} project_ids={project_ids} selected={selected_ids}")
    # DEBUG ASK: selected_ids=<список> project_ids=<список>
    print(f"DEBUG ASK: selected_ids={selected_ids} project_ids={project_ids}")

    # Normalize user input for consistent processing
    normalized_question = normalize_user_input(msg.text)
    
    # Save preliminary last_answer context immediately (unified schema)
    run_id = f"run-{int(time.time())}-{hash(normalized_question) % 10000}"
    async with session_scope() as st:
        stt = await _ensure_user_state(st, msg.from_user.id)
        import json
        # If this question was initiated via Refine, capture parent run and emit telemetry
        parent_run_id = getattr(stt, "ask_refine_run_id", None)
        stt.ask_refine_run_id = None
        stt.last_answer = json.dumps({
            "run_id": run_id,
            "question_msg_id": msg.message_id,
            "answer_msg_id": prep.message_id,
            "source_ids": list(selected_ids),
            "saved": False,
            "pinned": False,
            "ts": int(time.time()*1000)
        })
        await st.commit()
    
    if parent_run_id:
        try:
            event("refine_sent", user_id=msg.from_user.id, parent_run_id=parent_run_id, run_id=run_id, text_len=len(msg.text or ""))
        except Exception:
            pass
    
    if not selected_ids:
        # Используем эфемерное уведомление вместо залипающего сообщения
        if msg.bot:
            temp_msg = await msg.answer("Выбери источники в List.")
            # Авто-удаляем через 3 секунды
            import asyncio
            asyncio.create_task(_auto_delete_message(msg.bot, msg.chat.id, temp_msg.message_id, delay=3.0))
        await show_answer_with_bar(msg.bot, prep.chat.id, prep.message_id, "Нет выбранных источников.", answer_actions_kb("test", saved=False, pinned=False), user_id=msg.from_user.id)
        await state.update_data(awaiting_ask_question=False)
        return

    # FIX 10: Set in-flight flag to prevent duplicate processing
    async with session_scope() as st:
        stt = await _ensure_user_state(st, msg.from_user.id)
        stt.ask_inflight = True
        await st.commit()

    # DEBUG ASK start: q=…, src=[…]
    print(f"DEBUG ASK start: q={msg.text} src={selected_ids}")
    
    try:
        from app.config import LLM_DISABLED
        if LLM_DISABLED:
            answer_text = "LLM временно отключён админом."
            used = list(selected_ids)
            metadata = {"model": (await get_preferred_model_helper(msg.from_user.id)), "tokens_in": 0, "tokens_out": 0, "duration_ms": 0}
        else:
            answer_text, used, metadata = await svc_run_llm(
                user_id=msg.from_user.id,
                selected_artifact_ids=selected_ids,
                question=msg.text or "",
                run_id=run_id
            )
        # Keep ForceReply prompt message as per UX requirement (do not delete)
    except Exception as e:
        # LLM error: keep ForceReply and show warning block
        async with session_scope() as st:
            proj = await get_active_project(st, msg.from_user.id)
            proj_name = proj.name if proj else "Нет проекта"
            user_model = await get_preferred_model_helper(msg.from_user.id)
        scope = "selected" if selected_ids else "all"
        from app.services.token_budget import calculate_token_budget
        tokens_budget = calculate_token_budget(user_model)
        print(f"DEBUG LLM error: exc={e} model={user_model} tokens_budget={tokens_budget}")
        try:
            error("llm_error", user_id=msg.from_user.id, run_id=run_id, model=user_model, err=str(e))
        except Exception:
            pass
        warn = (
            f"⚠️ Не удалось получить ответ от модели. Попробуй ещё раз или проверь ключ/лимиты. "
            f"Project: {proj_name} • Scope: {scope} • Model: {user_model}"
        )
        await show_answer_with_bar(msg.bot, prep.chat.id, prep.message_id, warn, answer_actions_kb(run_id, saved=False, pinned=False), user_id=msg.from_user.id)
        await state.update_data(awaiting_ask_question=False)
        async with session_scope() as st:
            stt = await _ensure_user_state(st, msg.from_user.id)
            stt.ask_inflight = False
            await st.commit()
        return
    finally:
        # FIX 10: Clear in-flight flag
        async with session_scope() as st:
            stt = await _ensure_user_state(st, msg.from_user.id)
            stt.ask_inflight = False
            await st.commit()

    # Update last_answer with used sources and keep ts
    async with session_scope() as st:
        stt = await _ensure_user_state(st, msg.from_user.id)
        import json
        try:
            ctx = json.loads(stt.last_answer) if stt.last_answer else {}
        except Exception:
            ctx = {}
        ctx.update({
            "run_id": run_id,
            "question_msg_id": msg.message_id,
            "answer_msg_id": prep.message_id,
            "source_ids": list(used),
            "saved": ctx.get("saved", False),
            "pinned": ctx.get("pinned", False),
            "ts": ctx.get("ts") or int(time.time()*1000)
        })
        stt.last_answer = json.dumps(ctx)
        await st.commit()

    # Auto-clear selection if enabled
    auto_cleared = False
    async with session_scope() as st:
        stt = await _ensure_user_state(st, msg.from_user.id)
        if stt.auto_clear_selection:
            await svc_clear_selection(st, msg.from_user.id)
            await st.commit()
            auto_cleared = True
            try:
                event("ask_selection_autoclear_performed", user_id=msg.from_user.id)
            except Exception:
                pass
            
    # Update FSM to clear awaiting flag
    await state.update_data(awaiting_ask_question=False)
    
    # Build context line under answer
    async with session_scope() as st:
        proj = await get_active_project(st, msg.from_user.id)
        proj_name = proj.name if proj else "Нет проекта"
    scope = "selected" if used else "all"
    model_used = metadata.get("model", "?")
    ti = metadata.get("tokens_in", 0)
    to = metadata.get("tokens_out", 0)
    # Build Budget + ≈cost line (no tokens / no time)
    from app.services.token_budget import calculate_token_budget
    from app.services.llm import LLM_MAX_TOKENS_OUT
    in_budget = calculate_token_budget(model_used, LLM_MAX_TOKENS_OUT)
    cost = svc_compute_cost(model_used, ti, to)
    context_line = svc_build_ctx_line(proj_name, scope, model_used, in_budget, cost)

    # Sources short line inside message
    sources_line = ""
    if used:
        first_id = used[0]
        async with session_scope() as st:
            try:
                ttl = (await st.execute(sa.select(Artifact.title).where(Artifact.id == first_id))).scalar_one_or_none()
            except Exception:
                ttl = None
        sources_line = svc_build_sources_short((ttl or str(first_id)), first_id)

    # показать итог и панель
    kb = answer_actions_kb(run_id, saved=False, pinned=False)
    final_text = answer_text
    if sources_line:
        final_text += "\n\n" + sources_line
    final_text += "\n" + context_line
    await show_answer_with_bar(msg.bot, prep.chat.id, prep.message_id, final_text, kb, user_id=msg.from_user.id)
    
    # Persist rendered text and run meta for reliable restore/open
    async with session_scope() as st:
        stt = await _ensure_user_state(st, msg.from_user.id)
        import json
        try:
            ctx = json.loads(stt.last_answer) if stt.last_answer else {}
        except Exception:
            ctx = {}
        ctx["answer_text_rendered"] = final_text
        ctx["run_meta"] = {"model": model_used, "tokens_in": ti, "tokens_out": to, "cost_estimate": float(cost), "ts": int(time.time()*1000)}
        stt.last_answer = json.dumps(ctx)
        await st.commit()
    
    # Ensure reply keyboard is present after final answer
    await svc_attach_reply_kb(msg, msg.from_user.id)
    
    if auto_cleared:
        async with session_scope() as st:
            budget_label = await _calc_budget_label(st, [])
            controls = _panel_kb(0, budget_label, True)
            await msg.answer("ASK панель:", reply_markup=controls)

# ── OPEN: Saved answer card / full view / download / back ─────────────────────
@router.callback_query(F.data.startswith("ask:answer:open:page:"))
async def answer_open_page(cb: CallbackQuery):
    if not cb.from_user or not cb.data:
        return await cb.answer("Invalid data")
    parts = cb.data.split(":")
    if len(parts) < 5:
        return await cb.answer("Invalid callback data")
    try:
        artifact_id = int(parts[3]) if parts[2] == "open" else int(parts[4])
    except Exception:
        return await cb.answer("Bad id")
    # Page index
    try:
        page = int(parts[-1])
    except Exception:
        page = 1
    async with session_scope() as st:
        art = await st.get(Artifact, artifact_id)
        if not art:
            return await cb.answer("Артефакт не найден", show_alert=True)
        text = art.raw_text or ""
        page_size = 3600
        total_pages = max(1, (len(text) + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        start = (page - 1) * page_size
        chunk = text[start:start+page_size]
        # Build paging keyboard
        kb = InlineKeyboardBuilder()
        if page > 1:
            kb.button(text="◀", callback_data=f"ask:answer:open:page:{artifact_id}:{page-1}")
        kb.button(text=f"{page}/{total_pages}", callback_data="ask:noop")
        if page < total_pages:
            kb.button(text="▶", callback_data=f"ask:answer:open:page:{artifact_id}:{page+1}")
        # back row
        # Need run_id for back
        stt = await _ensure_user_state(st, cb.from_user.id)
        try:
            ctx = json.loads(stt.last_answer) if stt.last_answer else {}
        except Exception:
            ctx = {}
        run_id = ctx.get("run_id", "")
        kb.button(text="↩️ Назад", callback_data=f"ask:answer:open:back:{run_id}")
        kb.adjust(3, 1)
        # Edit message with current page
        if cb.message and isinstance(cb.message, Message):
            try:
                await cb.message.edit_text(chunk, reply_markup=kb.as_markup())
                try:
                    event("open_page", user_id=cb.from_user.id, run_id=run_id, artifact_id=artifact_id, page=page, total_pages=total_pages)
                except Exception:
                    pass
            except Exception as e:
                return await cb.answer(f"Ошибка: {str(e)}", show_alert=True)
    await cb.answer()

@router.callback_query(F.data.startswith("ask:answer:open:download:"))
async def answer_open_download(cb: CallbackQuery):
    if not cb.from_user or not cb.data:
        return await cb.answer("Invalid data")
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Invalid callback data")
    try:
        artifact_id = int(parts[3])
    except Exception:
        return await cb.answer("Bad id")
    async with session_scope() as st:
        art = await st.get(Artifact, artifact_id)
        if not art:
            return await cb.answer("Артефакт не найден", show_alert=True)
        filename = f"answer-{artifact_id}.txt"
        content = (art.raw_text or "").encode("utf-8")
        file = BufferedInputFile(content, filename)
        if cb.message and isinstance(cb.message, Message) and cb.message.bot:
            await cb.message.bot.send_document(cb.message.chat.id, document=file, caption=art.title or filename)
            try:
                # Get run_id from context for telemetry
                stt = await _ensure_user_state(st, cb.from_user.id)
                try:
                    ctx = json.loads(stt.last_answer) if stt.last_answer else {}
                except Exception:
                    ctx = {}
                run_id = ctx.get("run_id", "")
                event("open_download", user_id=cb.from_user.id, run_id=run_id, artifact_id=artifact_id)
            except Exception:
                pass
    await cb.answer("Готово")

@router.callback_query(F.data.startswith("ask:answer:open:back:"))
async def answer_open_back(cb: CallbackQuery):
    if not cb.from_user or not cb.data:
        return await cb.answer("Invalid data")
    parts = cb.data.split(":")
    if len(parts) < 5:
        return await cb.answer("Invalid callback data")
    run_id = parts[4]
    async with session_scope() as st:
        stt = await _ensure_user_state(st, cb.from_user.id)
        try:
            ctx = json.loads(stt.last_answer) if stt.last_answer else {}
        except Exception:
            ctx = {}
        if ctx.get("run_id") != run_id:
            return await _toast(cb, "Контекст истёк")
        text = ctx.get("answer_text_rendered") or "(пусто)"
        saved = ctx.get("saved", False)
        pinned = ctx.get("pinned", False)
        artifact_id = ctx.get("artifact_id")
        kb = answer_actions_kb(run_id, saved=saved, pinned=pinned, artifact_id=artifact_id)
        if cb.message and isinstance(cb.message, Message) and cb.message.bot:
            try:
                await show_answer_with_bar(cb.message.bot, cb.message.chat.id, cb.message.message_id, text, kb, user_id=cb.from_user.id)
                try:
                    event("open_back", user_id=cb.from_user.id, run_id=run_id, artifact_id=artifact_id)
                except Exception:
                    pass
            except Exception:
                # fallback to just keyboard restore
                try:
                    await restore_answer_with_bar(cb, kb, cb.from_user.id)
                except Exception:
                    pass
    await cb.answer("Вернулось")

@router.callback_query(F.data.startswith("ask:answer:open:"))
async def answer_open(cb: CallbackQuery):
    if not cb.from_user or not cb.data:
        return await cb.answer("Invalid data")
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Invalid callback data")
    try:
        artifact_id = int(parts[3])
    except Exception:
        return await cb.answer("Bad id")
    async with session_scope() as st:
        art = await st.get(Artifact, artifact_id)
        if not art:
            return await cb.answer("Артефакт не найден", show_alert=True)
        # Read last run ctx for back and panel restore
        stt = await _ensure_user_state(st, cb.from_user.id)
        try:
            ctx = json.loads(stt.last_answer) if stt.last_answer else {}
        except Exception:
            ctx = {}
        run_id = ctx.get("run_id", "")
        # Build card text
        title = art.title or f"Answer #{artifact_id}"
        created_at = art.created_at.strftime("%Y-%m-%d") if getattr(art, "created_at", None) else ""
        # Meta
        rm = art.run_meta or ctx.get("run_meta") or {}
        model = rm.get("model", "?")
        cost = rm.get("cost_estimate")
        cost_str = f"≈ ${float(cost):.4f}" if isinstance(cost, (int, float)) else ""
        # Sources
        src_ids = []
        try:
            rel = art.related_source_ids or {}
            src_ids = rel.get("ids") or rel.get("source_ids") or []
        except Exception:
            src_ids = []
        # Tags
        tag_names = []
        try:
            if art.tags:
                tag_names = [t.name for t in art.tags][:6]
        except Exception:
            tag_names = []
        # snippet
        raw = art.raw_text or ""
        snippet = raw[:600]
        if len(raw) > 600:
            snippet = snippet.rstrip() + " …"
        card_lines = [
            f"🗂 {title}",
            (f"Model: {model} {('• ' + cost_str) if cost_str else ''}"),
            (f"Date: {created_at}" if created_at else None),
            (f"Tags: {' '.join('#'+t for t in tag_names)}" if tag_names else None),
            "",
            snippet,
        ]
        card = "\n".join([ln for ln in card_lines if ln is not None])
        # Build controls with source chips (alerts)
        kb = InlineKeyboardBuilder()
        # Source chips (first 5)
        for sid in src_ids[:5]:
            kb.button(text=f"id{sid}", callback_data=f"ask:answer:srcinfo:{run_id}:{sid}")
        if src_ids:
            kb.adjust(min(5, len(src_ids)))
        # Controls
        kb.button(text="📖 Полный текст", callback_data=f"ask:answer:open:page:{artifact_id}:1")
        kb.button(text="⬇️ Download .txt", callback_data=f"ask:answer:open:download:{artifact_id}")
        kb.button(text="↩️ Назад", callback_data=f"ask:answer:open:back:{run_id}")
        kb.adjust(1, 1, 1)
        if cb.message and isinstance(cb.message, Message):
            try:
                await cb.message.edit_text(card, reply_markup=kb.as_markup())
                try:
                    event("open_card", user_id=cb.from_user.id, run_id=run_id, artifact_id=artifact_id)
                except Exception:
                    pass
            except Exception as e:
                return await cb.answer(f"Ошибка: {str(e)}", show_alert=True)
    await cb.answer()
