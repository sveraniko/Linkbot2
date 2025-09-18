from __future__ import annotations
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, Message
from app.db import session_scope
from app.services.memory import get_active_project, get_context_filters_state
from app.exporter import export_project_zip
from app.services.ui_helpers import attach_reply_kb as svc_attach_reply_kb
from html import escape

router = Router()

def build_export_kb(project_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"📦 Export project ({project_name})", callback_data="export:project"),
        InlineKeyboardButton(text="🎯 Export context (filters)", callback_data="export:context"),
    ]])

@router.callback_query(F.data == "export:open")
async def export_open(cb: CallbackQuery):
    async with session_scope() as st:
        proj = await get_active_project(st, cb.from_user.id if cb.from_user else 0)
        if not proj:
            if cb.message and isinstance(cb.message, Message):
                await cb.message.answer("Сначала выбери проект: Actions → Projects.")
                await svc_attach_reply_kb(cb.message, cb.from_user.id if cb.from_user else 0)
            return await cb.answer()
        kb = build_export_kb(proj.name)
    if cb.message and isinstance(cb.message, Message):
        await cb.message.answer("Экспорт:", reply_markup=kb)
        await svc_attach_reply_kb(cb.message, cb.from_user.id if cb.from_user else 0)
    await cb.answer()

@router.callback_query(F.data == "export:project")
async def export_project(cb: CallbackQuery):
    async with session_scope() as st:
        proj = await get_active_project(st, cb.from_user.id if cb.from_user else 0)
        if not proj:
            if cb.message and isinstance(cb.message, Message):
                await cb.message.answer("Нет активного проекта.")
                await svc_attach_reply_kb(cb.message, cb.from_user.id if cb.from_user else 0)
            return await cb.answer()
        data = await export_project_zip(st, proj)
    path = "/tmp/pm_export.zip"
    with open(path, "wb") as f: f.write(data)
    if cb.message and isinstance(cb.message, Message):
        await cb.message.answer_document(FSInputFile(path, filename=f"{proj.name}-export.zip"), caption=f"Export: {escape(proj.name)}")
        await svc_attach_reply_kb(cb.message, cb.from_user.id if cb.from_user else 0)
    await cb.answer()

@router.callback_query(F.data == "export:context")
async def export_context(cb: CallbackQuery):
    async with session_scope() as st:
        proj = await get_active_project(st, cb.from_user.id if cb.from_user else 0)
        if not proj:
            if cb.message and isinstance(cb.message, Message):
                await cb.message.answer("Нет активного проекта.")
                await svc_attach_reply_kb(cb.message, cb.from_user.id if cb.from_user else 0)
            return await cb.answer()
        kinds, tags = await get_context_filters_state(st, cb.from_user.id if cb.from_user else 0)
        data = await export_project_zip(st, proj, kinds=kinds or None, tags=tags or None)
    path = "/tmp/pm_ctx_export.zip"
    with open(path, "wb") as f: f.write(data)
    if cb.message and isinstance(cb.message, Message):
        await cb.message.answer_document(FSInputFile(path, filename=f"{proj.name}-context.zip"), caption=f"Export (filters): {escape(proj.name)}")
        await svc_attach_reply_kb(cb.message, cb.from_user.id if cb.from_user else 0)
    await cb.answer()
