from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from app.db import session_scope
from app.services.ui_helpers import attach_reply_kb as svc_attach_reply_kb
from app.services.memory import _ensure_user_state
from app.services.tags import get_presets
from sqlalchemy import delete
from app.models import Artifact, artifact_tags, Tag
from html import escape
import sqlalchemy as sa

router = Router()

# Cache for batch tag selection (similar to answer_actions.py)
BATCH_TAG_CACHE: dict[int, set[str]] = {}

@router.callback_query(F.data == "batch:tag")
async def batch_tag(cb: CallbackQuery):
    """Open tag selection interface for batch operations."""
    from app.services.memory import get_active_project
    async with session_scope() as st:
        # Get user state to retrieve batch IDs
        stt = await _ensure_user_state(st, cb.from_user.id if cb.from_user else 0)
        if not stt.last_batch_ids:
            return await cb.answer("No batch found", show_alert=True)
            
        # Get project-specific presets
        proj = await get_active_project(st, cb.from_user.id if cb.from_user else 0)
        pid = proj.id if proj else None
        presets = await get_presets(st, cb.from_user.id if cb.from_user else 0, pid)
        
        # Parse batch IDs
        batch_ids = [int(x) for x in stt.last_batch_ids.split(",") if x.strip().isdigit()]
        if not batch_ids:
            return await cb.answer("Invalid batch", show_alert=True)
            
        # Initialize tag cache for this user
        BATCH_TAG_CACHE[cb.from_user.id if cb.from_user else 0] = set()
        
        if cb.message and isinstance(cb.message, Message):
            await cb.message.answer(
                f"Выбери теги для пакета из {len(batch_ids)} артефактов (тап по кнопкам), потом нажми «Готово».",
                reply_markup=build_batch_tag_kb(presets, cb.from_user.id if cb.from_user else 0)
            )
    await cb.answer()

def build_batch_tag_kb(tags: list[str], user_id: int):
    """Build tag keyboard for batch operations."""
    rows, row = [], []
    for i, t in enumerate(tags, 1):
        row.append(InlineKeyboardButton(
            text=f"{escape(t)}", 
            callback_data=f"batch:tagtoggle:{user_id}:{t}"
        ))
        if i % 3 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
        
    rows.append([
        InlineKeyboardButton(text="✅ Готово", callback_data=f"batch:tagdone:{user_id}"),
        InlineKeyboardButton(text="✍️ Свои", callback_data=f"batch:tagfree:{user_id}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data.startswith("batch:tagtoggle:"))
async def batch_tag_toggle(cb: CallbackQuery):
    """Toggle tag selection for batch operations."""
    if not cb.data:
        return await cb.answer("Invalid data")
        
    parts = cb.data.split(":")
    if len(parts) < 4:
        return await cb.answer("Invalid data format")
        
    _, _, user_id_str, tag = parts
    user_id = int(user_id_str)
    
    cur = BATCH_TAG_CACHE.get(user_id, set())
    if tag in cur:
        cur.remove(tag)
    else:
        cur.add(tag)
    BATCH_TAG_CACHE[user_id] = cur
    await cb.answer(f"{'+' if tag in cur else '-'} {escape(tag)}")

@router.callback_query(F.data.startswith("batch:tagdone:"))
async def batch_tag_done(cb: CallbackQuery):
    """Apply selected tags to all artifacts in batch."""
    if not cb.data:
        return await cb.answer("Invalid data")
        
    parts = cb.data.split(":")
    if len(parts) < 3:
        return await cb.answer("Invalid data format")
        
    user_id = int(parts[2])
    tags = sorted(BATCH_TAG_CACHE.get(user_id, set()))
    
    if not tags:
        return await cb.answer("Не выбрано ни одного тега.", show_alert=True)
        
    async with session_scope() as st:
        # Get user state to retrieve batch IDs
        stt = await _ensure_user_state(st, user_id)
        if not stt.last_batch_ids:
            return await cb.answer("No batch found", show_alert=True)
            
        # Parse batch IDs
        batch_ids = [int(x) for x in stt.last_batch_ids.split(",") if x.strip().isdigit()]
        if not batch_ids:
            return await cb.answer("Invalid batch", show_alert=True)
            
        # Create tag objects first to ensure they exist in the tags table
        tag_objects = []
        for tag_name in tags:
            # Check if tag exists
            tag_stmt = sa.select(Tag).where(Tag.name == tag_name)
            tag_result = await st.execute(tag_stmt)
            tag = tag_result.scalar_one_or_none()
            
            if not tag:
                # Create new tag if it doesn't exist
                tag = Tag(name=tag_name)
                st.add(tag)
                await st.flush()
                
            tag_objects.append(tag)
        
        # Insert into artifact_tags with proper tag_name references
        insert_data = []
        for art_id in batch_ids:
            for tag in tag_objects:
                insert_data.append({"artifact_id": art_id, "tag_name": tag.name})
                
        if insert_data:
            # For PostgreSQL, we can use ON CONFLICT DO NOTHING
            from app.models import artifact_tags
            from sqlalchemy.dialects.postgresql import insert
            stmt = insert(artifact_tags).values(insert_data)
            stmt = stmt.on_conflict_do_nothing()
            await st.execute(stmt)
            
        await st.commit()
        
        
        # Clear tag cache
        BATCH_TAG_CACHE.pop(user_id, None)
        
    if cb.message and isinstance(cb.message, Message):
        await cb.message.answer(
            f"🏷 Теги для пакета: {escape(', '.join(tags))}\n"
            f"Применены к {len(batch_ids)} артефактам"
        )
        await svc_attach_reply_kb(cb.message, cb.from_user.id if cb.from_user else 0)
    await cb.answer("Теги применены")

@router.callback_query(F.data.startswith("batch:tagfree:"))
async def batch_tag_free(cb: CallbackQuery):
    """Prompt user for custom tags for batch."""
    if not cb.data:
        return await cb.answer("Invalid data")
        
    parts = cb.data.split(":")
    if len(parts) < 3:
        return await cb.answer("Invalid data format")
        
    user_id = int(parts[2])
    
    if cb.message and isinstance(cb.message, Message):
        await cb.message.answer(
            "Свои теги для пакета (через запятую):",
            reply_markup=ForceReply(selective=True)
        )
    await cb.answer()

@router.message(F.reply_to_message & F.reply_to_message.text.startswith("Свои теги для пакета"))
async def batch_tags_free_reply(message: Message):
    """Handle custom tags input for batch."""
    if not message.from_user:
        return
        
    user_id = message.from_user.id
    tags = [t.strip() for t in (message.text or "").split(",") if t.strip()]
    
    if not tags:
        await message.answer("Пусто.")
        await svc_attach_reply_kb(message, user_id)
        return
        
    async with session_scope() as st:
        # Get user state to retrieve batch IDs
        stt = await _ensure_user_state(st, user_id)
        if not stt.last_batch_ids:
            await message.answer("Не найден пакет для тегов.")
            await svc_attach_reply_kb(message, user_id)
            return
            
        # Parse batch IDs
        batch_ids = [int(x) for x in stt.last_batch_ids.split(",") if x.strip().isdigit()]
        if not batch_ids:
            await message.answer("Некорректный пакет.")
            await svc_attach_reply_kb(message, user_id)
            return
            
        # Create tag objects first to ensure they exist in the tags table
        tag_objects = []
        for tag_name in tags:
            # Check if tag exists
            tag_stmt = sa.select(Tag).where(Tag.name == tag_name)
            tag_result = await st.execute(tag_stmt)
            tag = tag_result.scalar_one_or_none()
            
            if not tag:
                # Create new tag if it doesn't exist
                tag = Tag(name=tag_name)
                st.add(tag)
                await st.flush()
                
            tag_objects.append(tag)
        
        # Insert into artifact_tags with proper tag_name references
        insert_data = []
        for art_id in batch_ids:
            for tag in tag_objects:
                insert_data.append({"artifact_id": art_id, "tag_name": tag.name})
                
        if insert_data:
            # For PostgreSQL, we can use ON CONFLICT DO NOTHING
            from app.models import artifact_tags
            from sqlalchemy.dialects.postgresql import insert
            stmt = insert(artifact_tags).values(insert_data)
            stmt = stmt.on_conflict_do_nothing()
            await st.execute(stmt)
            
        await st.commit()
        
        
    await message.answer(
        f"🏷 Теги для пакета: {escape(', '.join(tags))}\n"
        f"Применены к {len(batch_ids)} артефактам"
    )
    await svc_attach_reply_kb(message, user_id)

@router.callback_query(F.data == "batch:delete")
async def batch_delete(cb: CallbackQuery):
    """Delete all artifacts in batch."""
    async with session_scope() as st:
        # Get user state to retrieve batch IDs
        stt = await _ensure_user_state(st, cb.from_user.id if cb.from_user else 0)
        if not stt.last_batch_ids:
            return await cb.answer("No batch found", show_alert=True)
            
        # Parse batch IDs
        batch_ids = [int(x) for x in stt.last_batch_ids.split(",") if x.strip().isdigit()]
        if not batch_ids:
            return await cb.answer("Invalid batch", show_alert=True)
            
        # Delete all artifacts in batch
        result = await st.execute(delete(Artifact).where(Artifact.id.in_(batch_ids)))
        await st.commit()
        
        
        # Clear the batch from user state
        stt.last_batch_ids = None
        stt.last_batch_at = None
        await st.commit()
        
    if cb.message and isinstance(cb.message, Message):
        await cb.message.answer(
            f"🗑 Пакет удалён: {result.rowcount} артефактов"
        )
        await svc_attach_reply_kb(cb.message, cb.from_user.id if cb.from_user else 0)
    await cb.answer("Пакет удалён")
