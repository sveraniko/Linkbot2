from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.artifacts import get_or_create_project, create_note
from app.services.memory import (
    set_active_project, get_active_project, list_artifacts, clear_project,
    set_context_filters, set_preferred_model, get_preferred_model
)
from app.config import settings
from app.db import get_session
from app.states import state_manager
import logging
from html import escape
from app.services.ui_helpers import attach_reply_kb as svc_attach_reply_kb
from app.services.telemetry import error

logger = logging.getLogger(__name__)
router = Router()
_pending_clear: dict[int, str] = {}

@router.message(Command("start"))
async def start(message: Message):
    if message.from_user:
        try:
            await message.answer(
                "Привет!\n"
                "<code>/project &lt;name&gt;</code> — выбрать/создать проект\n"
                "<code>/memory add &lt;text&gt;</code> — добавить заметку\n"
                "<code>/memory show</code> — показать краткий конспект\n"
                "<code>/memory list</code> — список артефактов\n"
                "<code>/import</code> — ответьте этой командой на .txt/.md/.json файл\n"
                "<code>/ask &lt;вопрос&gt;</code> — спросить с учётом памяти\n"
                "<code>/ctx kinds note,import</code> | <code>/ctx tags api,db</code> — фильтры контекста\n"
                "<code>/memory clear</code> — безопасная очистка (двухшаговая)\n"
                "<code>/model gpt-5</code> | <code>/model gpt-5-thinking</code> — выбрать модель\n"
                "\nОткрой меню: <code>/menu</code>"
            )
            await svc_attach_reply_kb(message, message.from_user.id)
        except Exception as e:
            try:
                error("handler_exception", where="start", user_id=message.from_user.id, err=str(e))
            except Exception:
                pass
            await message.answer("Произошла ошибка при запуске")

@router.message(Command("ctx"))
async def ctx_filters(message: Message):
    from app.db import session_scope
    async with session_scope() as st:
        args = ((message.text or "").split(maxsplit=1) + [""])[1]
        if not args:
            await message.answer("Пример: /ctx kinds note,import | /ctx tags api,db | /ctx reset")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        if args.startswith("kinds"):
            kinds_csv = args.replace("kinds", "", 1).strip()
            await set_context_filters(st, message.from_user.id if message.from_user else 0, kinds_csv=kinds_csv)
        elif args.startswith("tags"):
            tags_csv = args.replace("tags", "", 1).strip()
            await set_context_filters(st, message.from_user.id if message.from_user else 0, tags_csv=tags_csv)
        elif args.strip() == "reset":
            await set_context_filters(st, message.from_user.id if message.from_user else 0, kinds_csv="", tags_csv="")
        await st.commit()
        await message.answer("Ок. Фильтры обновлены.")
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)

@router.message(Command("model"), F.text)
async def set_model(message: Message):
    from app.db import session_scope
    async with session_scope() as st:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            current = await get_preferred_model(st, message.from_user.id if message.from_user else 0)
            await message.answer(f"Текущая модель: {current}\nИспользование: /model gpt-5 | gpt-5-thinking")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        model = parts[1].strip()
        applied = await set_preferred_model(st, message.from_user.id if message.from_user else 0, model)
        await st.commit()
        await message.answer(f"Модель установлена: {applied}")
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)

@router.message(Command("project"))
async def project_select(message: Message):
    from app.db import session_scope
    from app.services.artifacts import get_or_create_project
    from app.services.memory import set_active_project
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        async with session_scope() as st:
            await message.answer("Укажите имя проекта: <code>/project &lt;name&gt;</code>")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
        return
    name = parts[1].strip()
    async with session_scope() as st:  # получаем ОДНУ сессию и переиспользуем
        proj = await get_or_create_project(st, name)
        await set_active_project(st, message.from_user.id if message.from_user else 0, proj)
        await st.commit()
        await message.answer(f"Активен проект: <b>{escape(proj.name)}</b>")
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)

@router.message(Command("memory"), F.text.regexp(r"^/memory\s+add\b"))
async def memory_add(message: Message):
    from app.db import session_scope
    from app.services.memory import get_active_project
    from app.services.artifacts import create_note
    async with session_scope() as st:
        proj = await get_active_project(st, message.from_user.id if message.from_user else 0)
        if not proj:
            await message.answer("Сначала выберите проект: <code>/project &lt;name&gt;</code>")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        
        # Парсим текст с возможными тегами: /memory add #tag1 #tag2 текст
        text_part = (message.text or "").split("add", 1)[1].strip()
        if not text_part:
            await message.answer("Добавьте текст: <code>/memory add &lt;text&gt;</code>\nМожно добавить теги: <code>/memory add #тег1 #тег2 текст</code>")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        
        # Извлекаем теги и текст
        words = text_part.split()
        tags = []
        text_words = []
        
        for word in words:
            if word.startswith('#') and len(word) > 1:
                tags.append(word[1:])  # Убираем #
            else:
                text_words.append(word)
        
        text = ' '.join(text_words)
        if not text:
            await message.answer("Текст заметки не может быть пустым")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        
        # Автоматически добавляем тег 'note' для всех заметок
        if 'note' not in tags:
            tags.append('note')
        
        try:
            await create_note(
                st, proj, 
                title=text[:60], 
                text=text, 
                chunk_size=settings.chunk_size, 
                overlap=settings.chunk_overlap,
                tags=tags if tags else None
            )
            await st.commit()
            
            tags_str = ', '.join(tags) if tags else 'нет'
            await message.answer(
                f"✅ Заметка добавлена в память проекта.\n"
                f"🏷️ Теги: {escape(tags_str)}"
            )
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
        except Exception as e:
            logger.error(f"Error adding note: {e}")
            await message.answer("⚠️ Ошибка при добавлении заметки")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)

@router.message(Command("memory"), F.text.regexp(r"^/memory\s+list($|\s)"))
async def memory_list(message: Message):
    from app.db import session_scope
    from app.services.memory import get_active_project
    from html import escape
    async with session_scope() as st:
        proj = await get_active_project(st, message.from_user.id if message.from_user else 0)
        if not proj:
            await message.answer("Сначала выберите проект: <code>/project &lt;name&gt;</code>")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        
        # Парсим фильтры из команды: /memory list tag=code kind=import
        command_text = (message.text or "").strip()
        params = {}
        
        # Простой парсинг фильтров
        if 'tag=' in command_text:
            tag_filter = command_text.split('tag=')[1].split()[0]
            params['tag'] = tag_filter
        if 'kind=' in command_text:
            kind_filter = command_text.split('kind=')[1].split()[0]
            params['kind'] = kind_filter
            
        # Получить список тегов
        tags = []
        if params.get("tag"):
            tags = [t.strip().lower() for t in params["tag"].split(",") if t.strip()]
        
        # Используем правильную функцию для получения артефактов с фильтрацией
        from sqlalchemy import select
        from app.models import Artifact, artifact_tags
        
        q = select(Artifact).where(Artifact.project_id == proj.id)
        
        # Применяем фильтры по видам
        if params.get('kind'):
            q = q.where(Artifact.kind == params['kind'])
            
        # Применяем фильтры по тегам
        if tags:
            q = q.join(artifact_tags, artifact_tags.c.artifact_id == Artifact.id) \
                 .where(artifact_tags.c.tag_name.in_(tags))  # <-- ВАЖНО: tag_name
        
        q = q.order_by(Artifact.created_at.desc())
        res = await st.execute(q)
        filtered_arts = list(res.scalars().all())
        
        if not filtered_arts:
            filter_desc = ', '.join([f"{k}={v}" for k, v in params.items()])
            await message.answer(f"🔍 По фильтрам {escape(filter_desc)} ничего не найдено.")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        
        lines = [f"📁 Артефакты проекта <b>{escape(proj.name)}</b>:"]
        for i, a in enumerate(filtered_arts[:20], 1):  # Показываем только первые 20
            icon = "📝" if a.kind == "note" else "📄"
            # Загружаем теги для отображения
            tag_names = []
            if hasattr(a, 'tags') and a.tags:
                tag_names = [t.name for t in a.tags]
            tags_str = ", ".join(tag_names) if tag_names else "нет"
            storage_info = f" 🗃️" if a.uri else ""
            lines.append(f"{i}. {icon} <b>{escape(a.title)}</b>\n   🏷️ {tags_str}{storage_info}")
        
        if len(filtered_arts) > 20:
            lines.append(f"\n... и ещё {len(filtered_arts) - 20} артефактов")
        
        if params:
            filter_desc = ', '.join([f"{k}={v}" for k, v in params.items()])
            lines.append(f"\n🔍 Фильтр: {escape(filter_desc)}")
        
        await message.answer("\n".join(lines))
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)

@router.message(Command("memory"), F.text.regexp(r"^/memory\s+show$"))
async def memory_show(message: Message):
    from app.db import session_scope
    from app.services.memory import get_active_project
    from app.services.memory import list_artifacts
    async with session_scope() as st:
        proj = await get_active_project(st, message.from_user.id if message.from_user else 0)
        if not proj:
            await message.answer("Сначала выберите проект: <code>/project &lt;name&gt;</code>")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        arts = await list_artifacts(st, proj)
        if not arts:
            await message.answer("Память пуста.")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        preview = []
        for a in arts[:10]:
            preview.append(f"[{escape(a.kind)}] <b>{escape(a.title)}</b>\n{(escape(a.raw_text[:200]) + '...') if len(a.raw_text)>200 else escape(a.raw_text)}")
        await message.answer("\n\n".join(preview))
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)

@router.message(Command("memory"), F.text.regexp(r"^/memory\s+clear$"))
async def memory_clear_ask(message: Message):
    from app.db import session_scope
    from app.services.memory import get_active_project
    async with session_scope() as st:
        proj = await get_active_project(st, message.from_user.id if message.from_user else 0)
        if not proj:
            await message.answer("Сначала выберите проект: <code>/project &lt;name&gt;</code>")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        _pending_clear[message.from_user.id if message.from_user else 0] = proj.name
        await message.answer(f"⚠️ Подтверждение: /memory clear {escape(proj.name)}")
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)

@router.message(Command("memory"), F.text.regexp(r"^/memory\s+clear\s+.+$"))
async def memory_clear_confirm(message: Message):
    from app.db import session_scope
    from app.services.memory import get_active_project, clear_project
    async with session_scope() as st:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("Формат: <code>/memory clear &lt;project&gt;</code>")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        proj_name = parts[2]
        expected = _pending_clear.get(message.from_user.id if message.from_user else 0)
        if expected != proj_name:
            await message.answer("Имя проекта не совпало или нет ожидания очистки.")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        proj = await get_active_project(st, message.from_user.id if message.from_user else 0)
        if not proj or proj.name != proj_name:
            await message.answer("Сначала выберите проект: <code>/project &lt;name&gt;</code>")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return
        await clear_project(st, proj)
        await st.commit()
        _pending_clear.pop(message.from_user.id if message.from_user else 0, None)
        await message.answer("Память проекта очищена.")
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
