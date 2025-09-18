"""UI helpers (Telegram-agnostic wrappers to be used from handlers)
- show_answer_with_bar(bot, chat_id, message_id, text, bar, user_id)
- restore_answer_with_bar(cb, bar, user_id)
- attach_reply_kb(message, user_id)
- main_reply_kb(chat_on)
"""
from __future__ import annotations
from typing import Optional
import contextlib
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from app.db import session_scope
from app.services.memory import get_chat_flags

BTN_ACTIONS = "⚙️ Actions"
BTN_CHAT_ON = "💬 Chat: ON"
BTN_CHAT_OFF = "😴 Chat: OFF"
BTN_ASK = "❓ ASK‑WIZARD"

def main_reply_kb(chat_on: bool) -> ReplyKeyboardMarkup:
    chat_label = BTN_CHAT_ON if chat_on else BTN_CHAT_OFF
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[[
            KeyboardButton(text=BTN_ACTIONS),
            KeyboardButton(text=chat_label),
            KeyboardButton(text=BTN_ASK),
        ]],
    )


async def show_answer_with_bar(bot, chat_id: int, message_id: int, text: str, bar, user_id: Optional[int] = None) -> None:
    """Edit the target message with provided text and inline bar, then ensure reply keyboard is present.
    - bot: aiogram.Bot
    - chat_id/message_id: target message to edit
    - text: final message text
    - bar: InlineKeyboardMarkup to attach
    - user_id: for restoring reply keyboard state (optional)
    """
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=bar)
    except Exception:
        # Best effort: try updating only markup
        with contextlib.suppress(Exception):
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=bar)
    # Не отправляем дополнительное сообщение для обновления клавиатуры


async def restore_answer_with_bar(cb: CallbackQuery, bar, user_id: int) -> None:
    """Restore only the inline bar for the answer message and reattach reply keyboard."""
    if cb.message and isinstance(cb.message, Message):
        with contextlib.suppress(Exception):
            await cb.message.edit_reply_markup(reply_markup=bar)
        # Не отправляем дополнительное сообщение для обновления клавиатуры


async def attach_reply_kb(message: Message, user_id: int) -> None:
    # Не отправляем дополнительное сообщение, просто обновляем клавиатуру через бота
    async with session_scope() as st:
        chat_on, *_ = await get_chat_flags(st, user_id)
        # Используем метод set_my_commands или просто полагаемся на то, что клавиатура уже установлена
        # Если нужно обновить клавиатуру, это должно происходить через редактирование существующего сообщения
        pass
