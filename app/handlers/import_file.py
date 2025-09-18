# app/handlers/import_file.py
from __future__ import annotations
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from pathlib import Path
import re
import datetime as dt
import uuid
import hashlib
from html import escape
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.memory import get_active_project, _ensure_user_state
from app.services.artifacts import create_import
from app.storage import save_file
from app.db import session_scope
from app.ignore import load_pmignore, iter_text_files
from app.models import Tag, artifact_tags
from app.services.ui_helpers import attach_reply_kb as svc_attach_reply_kb

# Add Berlin timezone
BERLIN = ZoneInfo("Europe/Berlin")

router = Router()

# Храним "последний документ" на пользователя/чат (fallback, если нет reply)
# ключ: (chat_id, user_id) -> (file_id, file_name)
_LAST_DOC: dict[tuple[int, int], tuple[str, str]] = {}

ALLOWED_EXTS = {".txt", ".md", ".json", ".zip"}

# Date extraction patterns for auto-tags
DATE_PATTERNS = [
    re.compile(r"[_-](\d{4})(\d{2})(\d{2})[_-]"),         # _YYYYMMDD_ or -YYYYMMDD-
    re.compile(r"[-](\d{4})[-](\d{2})[-](\d{2})"),        # -YYYY-MM-DD
]

def extract_doc_date(filename: str) -> str | None:
    """Extract document date from filename if possible."""
    for pat in DATE_PATTERNS:
        m = pat.search(filename or "")
        if m:
            year, month, day = m.group(1), m.group(2), m.group(3)
            # Validate date
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

def _extract_doc_tag(name: str) -> str | None:
    m = re.search(r'(\d{4})(\d{2})(\d{2})', (name or "").lower())
    if m:
        year, month, day = m.group(1), m.group(2), m.group(3)
        # Validate date
        try:
            dt.date(int(year), int(month), int(day))
            return f"doc-{year}-{month}-{day}"
        except ValueError:
            return None
    return None

def _parse_tags(cmd_text: str | None) -> list[str] | None:
    if not cmd_text:
        return None
    # /import tags a,b,c
    m = re.search(r"/import(?:\s+tags\s+(.*))?$", cmd_text, flags=re.IGNORECASE)
    if not m:
        return None
    grp = m.group(1)
    if not grp:
        return None
    return [t.strip() for t in grp.split(",") if t.strip()]

@router.message(F.document)
async def on_document(message: Message):
    """Ловим любой документ и запоминаем его как 'последний' для юзера в этом чате."""
    doc = message.document
    if not doc or not message.from_user:
        return
    _LAST_DOC[(message.chat.id, message.from_user.id)] = (doc.file_id, doc.file_name or "file")

    # Save to database as well
    async with session_scope() as st:
        stt = await _ensure_user_state(st, message.from_user.id)
        stt.last_doc_file_id = doc.file_id
        stt.last_doc_name = doc.file_name or "file"
        stt.last_doc_mime = doc.mime_type or ""
        await st.commit()

        # For ZIP files, provide special instructions
        if doc.file_name and doc.file_name.lower().endswith(".zip"):
            await message.answer("Получил ZIP-архив. Теперь ответьте на него командой /import, "
                                 "или нажмите в Actions: «Импорт (последний файл)».")
            await svc_attach_reply_kb(message, message.from_user.id)
        else:
            await message.answer("Получил документ. Теперь ответьте на него командой /import, "
                                 "или нажмите в Actions: «Импорт (последний файл)».")
            await svc_attach_reply_kb(message, message.from_user.id)

@router.message(Command("import"))
async def import_document(message: Message):
    if not message.from_user:
        return

    async with session_scope() as st:
        proj = await get_active_project(st, message.from_user.id)
        if not proj:
            await message.answer("Сначала выберите проект: <code>/project <name></code>")
            await svc_attach_reply_kb(message, message.from_user.id)
            return

        # 1) Пытаемся взять документ из reply
        doc = None
        if message.reply_to_message and message.reply_to_message.document:
            doc = message.reply_to_message.document

        # 2) Если нет reply — берем последний документ пользователя в этом чате
        if not doc:
            key = (message.chat.id, message.from_user.id)
            last = _LAST_DOC.get(key)
            if last:
                file_id, file_name = last
                # подтягиваем объект файла через get_file, чтобы скачать
                # В aiogram для скачивания нужен FilePath -> берем через bot.get_file(file_id)
                if not message.bot:
                    await message.answer("Ошибка доступа к боту")
                    await svc_attach_reply_kb(message, message.from_user.id)
                    return
                tg_file = await message.bot.get_file(file_id)
                if not tg_file.file_path:
                    await message.answer("Не удалось получить путь к файлу")
                    await svc_attach_reply_kb(message, message.from_user.id)
                    return
                file_bytes_io = await message.bot.download_file(tg_file.file_path)
                if not file_bytes_io:
                    await message.answer("Не удалось скачать файл")
                    await svc_attach_reply_kb(message, message.from_user.id)
                    return
                data = file_bytes_io.read()
                ext = Path(file_name).suffix.lower()
                if ext not in ALLOWED_EXTS:
                    await message.answer("Файл найден, но расширение не поддерживается. Доступно: .txt .md .json .zip")
                    await svc_attach_reply_kb(message, message.from_user.id)
                    return
                uri = await save_file(file_name, data)  # MinIO (может вернуть None, если не настроен)
                text = data.decode("utf-8", errors="ignore")
                title = file_name or "import.txt"
                tags = _parse_tags(message.text)
                
                # Add auto-tags using the new function
                auto_tags = auto_tags_for_single_file(title)
                
                # Combine user tags with auto tags
                if tags:
                    tags.extend(auto_tags)
                else:
                    tags = auto_tags
                    
                art = await create_import(
                    st, proj,
                    title=title,
                    text=text,
                    chunk_size=settings.chunk_size,
                    overlap=settings.chunk_overlap,
                    tags=tags,
                    uri=uri,
                )
                await st.commit()
                
                # Create service card without MinIO key
                lines = [
                    f"Импортировано в проект: <b>{escape(proj.name)}</b>",
                    f"Файл: {escape(title)}"
                ]
                
                # Build inline keyboard with action buttons
                from aiogram.utils.keyboard import InlineKeyboardBuilder
                builder = InlineKeyboardBuilder()
                builder.button(text="🏷 Теги", callback_data=f"imp:tag:{art.id}")
                builder.button(text="🗑 Удалить", callback_data=f"imp:del:{art.id}")
                builder.button(text="🔎 Ask this", callback_data=f"imp:ask:{art.id}")
                builder.adjust(2)
                
                await message.answer(
                    "\n".join(lines),
                    reply_markup=builder.as_markup()
                )
                return

            # Вообще ничего не нашли
            await message.answer("Пришлите файл .txt/.md/.json/.zip и ответьте на него командой /import для импорта.")
            await svc_attach_reply_kb(message, message.from_user.id)
            return

        # 3) Ветка с reply (основной happy-path)
        file_name = doc.file_name or "import.txt"
        ext = Path(file_name).suffix.lower()
        if ext not in ALLOWED_EXTS:
            await message.answer("Файл получен, но расширение не поддерживается. Доступно: .txt .md .json .zip")
            await svc_attach_reply_kb(message, message.from_user.id)
            return

        if not message.bot:
            await message.answer("Ошибка доступа к боту")
            await svc_attach_reply_kb(message, message.from_user.id)
            return
            
        tg_file = await message.bot.get_file(doc.file_id)
        if not tg_file.file_path:
            await message.answer("Не удалось получить путь к файлу")
            await svc_attach_reply_kb(message, message.from_user.id)
            return
            
        file_bytes_io = await message.bot.download_file(tg_file.file_path)
        if not file_bytes_io:
            await message.answer("Не удалось скачать файл")
            await svc_attach_reply_kb(message, message.from_user.id)
            return
            
        data = file_bytes_io.read()
        uri = await save_file(file_name, data)  # MinIO (публичный URL или None)
        text = data.decode("utf-8", errors="ignore")
        tags = _parse_tags(message.text)
        
        # Add auto-tags using the new function
        auto_tags = auto_tags_for_single_file(file_name)
        
        # Combine user tags with auto tags
        if tags:
            tags.extend(auto_tags)
        else:
            tags = auto_tags

        art = await create_import(
            st, proj,
            title=file_name,
            text=text,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
            tags=tags,
            uri=uri,
        )
        await st.commit()
        
        # Create service card without MinIO key
        lines = [
            f"Импортировано в проект: <b>{escape(proj.name)}</b>",
            f"Файл: {escape(file_name)}"
        ]
        
        # Build inline keyboard with action buttons
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="🏷 Теги", callback_data=f"imp:tag:{art.id}")
        builder.button(text="🗑 Удалить", callback_data=f"imp:del:{art.id}")
        builder.button(text="🔎 Ask this", callback_data=f"imp:ask:{art.id}")
        builder.adjust(2)
        
        await message.answer(
            "\n".join(lines),
            reply_markup=builder.as_markup()
        )

# --- ZIP import ---
@router.message(Command("importzip"))
async def import_zip(message: Message):
    # Проверяем, что есть reply с документом
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.answer("Прикрепите ZIP как файл и ответьте на сообщение с командой:\n<code>/importzip tags code,snapshot,rev-YYYY-MM-DD</code>")
        await svc_attach_reply_kb(message, message.from_user.id)
        return
    
    doc = message.reply_to_message.document
    if not doc.file_name or not doc.file_name.endswith(".zip"):
        await message.answer("Файл должен быть быть .zip")
        await svc_attach_reply_kb(message, message.from_user.id)
        return
    
    # Получаем теги из команды
    tags = _parse_tags(message.text)
    
    # Generate batch tag for ZIP import
    import hashlib
    batch_hash = hashlib.md5(f"{doc.file_name}{dt.datetime.now(BERLIN).isoformat()}".encode()).hexdigest()[:8]
    batch_tag = f"batch-{batch_hash}"
    
    # Add auto-tags
    auto_tags = []
    auto_tags.append(f"rel-{dt.datetime.now(BERLIN).date().isoformat()}")
    doc_tag = _extract_doc_tag(doc.file_name or "")
    if doc_tag:
        auto_tags.append(doc_tag)
    auto_tags.append(batch_tag)
    
    # Combine user tags with auto tags
    if tags:
        tags.extend(auto_tags)
    else:
        tags = auto_tags
    
    # Скачиваем ZIP
    if not message.bot:
        await message.answer("Ошибка доступа к боту")
        await svc_attach_reply_kb(message, message.from_user.id)
        return
        
    tg_file = await message.bot.get_file(doc.file_id)
    if not tg_file.file_path:
        await message.answer("Не удалось получить путь к файлу")
        await svc_attach_reply_kb(message, message.from_user.id)
        return
        
    file_bytes_io = await message.bot.download_file(tg_file.file_path)
    if not file_bytes_io:
        await message.answer("Не удалось скачать файл")
        await svc_attach_reply_kb(message, message.from_user.id)
        return
        
    data = file_bytes_io.read()
    
    # Сохраняем временно
    tmp = Path("/tmp/pm_zip")
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)

    tmp.mkdir(parents=True, exist_ok=True)
    
    # Сохраняем ZIP
    zip_path = tmp / doc.file_name
    with open(zip_path, "wb") as f:
        f.write(data)
    
    # Распаковываем
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    
    # Загружаем .pmignore
    spec = load_pmignore(tmp)
    
    # Импортируем текстовые файлы
    async with session_scope() as st:
        proj = await get_active_project(st, message.from_user.id if message.from_user else 0)
        if not proj:
            return await message.answer("Сначала выберите проект: <code>/project &lt;name&gt;</code>")
        
        imported = 0
        for rel, text in iter_text_files(tmp, spec):
            title = f"{escape(doc.file_name)}:{rel}"
            await create_import(
                st, proj,
                title=title,
                text=text,
                chunk_size=settings.chunk_size,
                overlap=settings.chunk_overlap,
                tags=tags
            )
            imported += 1
        await st.commit()
    
    await message.answer(f"Импорт ZIP завершён: {imported} файлов.\nТег: <code>{escape(batch_tag)}</code>")
    await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)

# --- экспортируем для меню ---
async def import_last_for_user(message: Message, st: AsyncSession, tags: list[str] | None) -> bool:
    if not message.from_user:
        return False
    key = (message.chat.id, message.from_user.id)
    last = _LAST_DOC.get(key)
    if not last:
        return False
    file_id, file_name = last
    if not message.bot:
        await message.answer("Ошибка доступа к боту")
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
        return True
    tg_file = await message.bot.get_file(file_id)
    if not tg_file.file_path:
        await message.answer("Не удалось получить путь к файлу")
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
        return True
    file_bytes_io = await message.bot.download_file(tg_file.file_path)
    if not file_bytes_io:
        await message.answer("Не удалось скачать файл")
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
        return True
    data = file_bytes_io.read()
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        await message.answer("Файл найден, но расширение не поддерживается. Доступно: .txt .md .json .zip")
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
        return True

    proj = await get_active_project(st, message.from_user.id)
    if not proj:
        await message.answer("Сначала выберите проект: <code>/project <name></code>")
        await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
        return True
        
    # Generate batch tag for single file import
    batch_hash = hashlib.md5(f"{file_name}{dt.datetime.now(BERLIN).isoformat()}".encode()).hexdigest()[:8]
    batch_tag = f"batch-{batch_hash}"
    
    # Add auto-tags using the new function
    auto_tags = auto_tags_for_single_file(file_name)
    
    # Combine user tags with auto tags
    if tags:
        tags.extend(auto_tags)
    else:
        tags = auto_tags
        
    if ext == ".zip":
        # Handle ZIP file import
        import zipfile
        import tempfile
        from app.ignore import load_pmignore, iter_text_files
        from app.utils.zipfix import fix_zip_name, decode_text_bytes
        
        try:
            # Create temporary directory and file
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                zip_path = tmp_path / "temp.zip"
                
                # Write ZIP data to temporary file
                with open(zip_path, "wb") as f:
                    f.write(data)
                
                # Extract ZIP
                with zipfile.ZipFile(zip_path) as z:
                    z.extractall(tmp_path)
                
                # Load .pmignore spec
                spec = load_pmignore(tmp_path)
                
                # Import text files with encoding fixes
                imported_count = 0
                for p in tmp_path.rglob("*"):
                    if p.is_file():
                        rel_path = p.relative_to(tmp_path).as_posix()
                        if spec.match_file(rel_path):
                            continue
                        
                        # Try to fix ZIP filename encoding
                        # Since we don't have flag_bits here, we'll try our best to detect encoding issues
                        fixed_rel_path = rel_path
                        # Simple heuristic: if filename contains non-ASCII characters that look like encoding issues
                        try:
                            rel_path.encode("ascii")
                        except UnicodeEncodeError:
                            # Likely encoding issue, try to fix it
                            fixed_rel_path = fix_zip_name(rel_path, 0)  # 0 flag bits as we don't have them
                        
                        # Check if it's a text file
                        if not fixed_rel_path.lower().endswith((".md", ".txt", ".json")):
                            continue
                            
                        # Read and decode content with proper encoding detection
                        try:
                            raw_data = p.read_bytes()
                            content = decode_text_bytes(raw_data)
                            
                            title = f"{escape(file_name)}:{escape(fixed_rel_path)}"
                            await create_import(
                                st, proj,
                                title=title,
                                text=content,
                                chunk_size=settings.chunk_size,
                                overlap=settings.chunk_overlap,
                                tags=tags + ['zip']
                            )
                            imported_count += 1
                        except Exception:
                            # Skip files that can't be processed
                            continue
                
                await st.commit()
                await message.answer(f"Импортировано из ZIP в <b>{escape(proj.name)}</b>: {imported_count} файлов\nАрхив: {escape(file_name)}\nТеги: {', '.join(tags) if tags else '—'}")
                await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
                return True

        except Exception as e:
            await message.answer(f"Ошибка при импорте ZIP: {escape(str(e))}")
            await svc_attach_reply_kb(message, message.from_user.id if message.from_user else 0)
            return True
    else:
        # Handle regular text files
        uri = await save_file(file_name, data)
        text = data.decode("utf-8", errors="ignore")
        art = await create_import(
            st, proj,
            title=file_name, text=text,
            chunk_size=settings.chunk_size, overlap=settings.chunk_overlap,
            tags=tags, uri=uri,
        )
        await st.commit()
        
        # Create service card without MinIO key
        lines = [
            f"Импортировано в проект: <b>{escape(proj.name)}</b>",
            f"Файл: {escape(file_name)}"
        ]
        
        # Build inline keyboard with action buttons
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="🏷 Теги", callback_data=f"imp:tag:{art.id}")
        builder.button(text="🗑 Удалить", callback_data=f"imp:del:{art.id}")
        builder.button(text="🔎 Ask this", callback_data=f"imp:ask:{art.id}")
        builder.adjust(2)
        
        await message.answer("\n".join(lines), reply_markup=builder.as_markup())
        return True
