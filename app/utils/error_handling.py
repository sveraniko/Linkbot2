"""Error handling utilities following AntiFragile v3 principles"""
from __future__ import annotations
import logging
import asyncio
import random
from typing import Optional, Callable, Any
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.types import Message

# Try to import structlog, fallback to standard logging if not available
try:
    import structlog
    logger = structlog.get_logger(__name__)
    HAS_STRUCTLOG = True
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    HAS_STRUCTLOG = False


def toast_or_log(user_message: str, dev_detail: str, user_id: Optional[int] = None) -> None:
    """
    Helper for dual logging: brief message for user context, detailed for developers.
    
    Args:
        user_message: Brief, user-friendly description
        dev_detail: Technical details for logs/Sentry
        user_id: Optional user ID for context
    """
    logger.warning(
        "User-facing error occurred",
        action="toast_or_log",
        user_message=user_message,
        dev_detail=dev_detail,
        user_id=user_id
    )


async def retry_with_backoff(
    operation: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    jitter: bool = True,
    operation_name: str = "telegram_operation"
) -> Any:
    """
    Retry operation with exponential backoff and jitter.
    Only for idempotent operations like editMessage, get*, deleteMessage.
    
    Args:
        operation: Async callable to retry
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        jitter: Add random jitter to prevent thundering herd
        operation_name: Operation name for logging
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except TelegramRetryAfter as e:
            # Respect Telegram's rate limiting
            delay = e.retry_after
            if attempt < max_retries:
                logger.info(
                    "Rate limited, retrying",
                    action="retry_with_backoff",
                    operation=operation_name,
                    delay=delay,
                    attempt=attempt + 1,
                    max_retries=max_retries + 1,
                    error_type="TelegramRetryAfter"
                )
                await asyncio.sleep(delay)
                continue
            last_exception = e
            break
        except TelegramNetworkError as e:
            if attempt < max_retries:
                # Calculate exponential backoff with optional jitter
                delay = min(base_delay * (2 ** attempt), max_delay)
                if jitter:
                    delay *= (0.5 + random.random() * 0.5)  # Add ±25% jitter
                
                logger.warning(
                    "Network error, retrying",
                    action="retry_with_backoff",
                    operation=operation_name,
                    error_type="TelegramNetworkError",
                    error=str(e),
                    attempt=attempt + 1,
                    max_retries=max_retries + 1,
                    delay=round(delay, 1)
                )
                await asyncio.sleep(delay)
                continue
            last_exception = e
            break
        except TelegramBadRequest as e:
            # Don't retry bad requests - they're usually permanent
            logger.warning(
                "Invalid request, not retrying",
                action="retry_with_backoff",
                operation=operation_name,
                error_type="TelegramBadRequest",
                error=str(e)
            )
            last_exception = e
            break
        except Exception as e:
            logger.error(
                "Unexpected error in operation",
                action="retry_with_backoff",
                operation=operation_name,
                error_type=type(e).__name__,
                error=str(e)
            )
            last_exception = e
            break
    
    # All retries exhausted
    if last_exception:
        logger.error(
            f"Operation {operation_name} failed after {max_retries + 1} attempts: {last_exception}"
        )
        # Don't re-raise to avoid breaking user flow - return None or handle gracefully
        return None
    
    return None


async def safe_edit_message_text(bot, chat_id: int, message_id: int, text: str, reply_markup=None) -> bool:
    """
    Safely edit message text with retry logic.
    Returns True if successful, False otherwise.
    """
    async def operation():
        return await bot.edit_message_text(
            chat_id=chat_id, 
            message_id=message_id, 
            text=text, 
            reply_markup=reply_markup
        )
    
    result = await retry_with_backoff(
        operation, 
        operation_name=f"edit_message_text(chat_id={chat_id}, msg_id={message_id})"
    )
    return result is not None


async def safe_edit_message_reply_markup(bot, chat_id: int, message_id: int, reply_markup) -> bool:
    """
    Safely edit message reply markup with retry logic.
    Returns True if successful, False otherwise.
    """
    async def operation():
        return await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup
        )
    
    result = await retry_with_backoff(
        operation,
        operation_name=f"edit_message_reply_markup(chat_id={chat_id}, msg_id={message_id})"
    )
    return result is not None


async def safe_delete_message(bot, chat_id: int, message_id: int, user_id: Optional[int] = None) -> bool:
    """
    Safely delete message with retry logic.
    Returns True if successful, False otherwise.
    """
    async def operation():
        return await bot.delete_message(chat_id=chat_id, message_id=message_id)
    
    result = await retry_with_backoff(
        operation,
        operation_name=f"delete_message(chat_id={chat_id}, msg_id={message_id})"
    )
    
    if result is None:
        toast_or_log(
            "Could not delete message",
            f"Failed to delete message {message_id} in chat {chat_id}",
            user_id
        )
    
    return result is not None
