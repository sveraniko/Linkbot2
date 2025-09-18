from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message

from app.db import session_scope
from app.services.memory import get_chat_flags, set_chat_mode
from app.services.ui_helpers import attach_reply_kb as svc_attach_reply_kb, main_reply_kb, BTN_ACTIONS, BTN_CHAT_ON, BTN_CHAT_OFF, BTN_ASK

router = Router(name="keyboard")

SERVICE_TEXTS = {BTN_ACTIONS, BTN_ASK, BTN_CHAT_ON, BTN_CHAT_OFF, "Меню", "Menu", "Chat"}

@router.message(F.text == BTN_ACTIONS)
async def open_actions_from_kb(message: Message):
    """
    Открывает твою панель действий по кнопке снизу.
    Пробуем найти одну из функций меню и вызвать её напрямую.
    """
    open_menu = None
    try:
        # 1) если у тебя есть такой модуль/ф-ция
        from app.handlers.menu import menu as open_menu  # noqa: F401
    except Exception:
        try:
            from app.handlers.menu import actions as open_menu  # noqa: F401
        except Exception:
            open_menu = None

    if open_menu:
        # Delete the command message to keep chat clean
        try:
            await message.delete()
        except Exception:
            pass
        return await open_menu(message)

    # Фоллбек, если прямой вызов не найден:
    # лучше вернуть подсказку, чем молчать
    # Delete the command message to keep chat clean
    try:
        await message.delete()
    except Exception:
        pass
    return await message.answer("Открой меню командой /menu")

@router.message(F.text == BTN_ASK)
async def open_ask_from_kb(message: Message):
    """
    Open ASK-WIZARD panel from the keyboard button.
    """
    from app.handlers.ask import ask_open
    # Delete the command message to keep chat clean
    try:
        await message.delete()
    except Exception:
        pass
    return await ask_open(message)

@router.message(F.text.in_({BTN_CHAT_ON, BTN_CHAT_OFF}))
async def kb_chat_toggle(message: Message):
    """Toggle Chat ON/OFF and rebuild the bottom-row keyboard. Never call LLM here."""
    if not message.from_user:
        return
    async with session_scope() as st:
        chat_on, *_ = await get_chat_flags(st, message.from_user.id)
        new_state = not chat_on
        await set_chat_mode(st, message.from_user.id, on=new_state)
        await st.commit()
        # Delete the command message to keep chat clean
        try:
            await message.delete()
        except Exception:
            pass
        async with session_scope() as st2:
            chat_on, *_ = await get_chat_flags(st2, message.from_user.id)
            await message.answer(
                f"Чат: {'ON' if new_state else 'OFF'}",
                reply_markup=main_reply_kb(chat_on)
            )

__all__ = ["SERVICE_TEXTS", "router"]
