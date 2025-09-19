"""Logging and monitoring setup following AntiFragile v3 principles"""
from __future__ import annotations
import logging
import sys
import time
from typing import Optional, Dict, Any
from functools import wraps

import structlog
from app.config import settings

# Global logger instance
logger = structlog.get_logger()

def setup_structured_logging() -> None:
    """
    Configure structlog with JSON output for production-ready logging.
    Should be called once at app startup.
    """
    # Configure standard library logging first
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.monitoring.log_level.value.upper(), logging.INFO),
    )
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            # Use JSONRenderer for structured logs
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def setup_sentry() -> None:
    """
    Configure Sentry for error tracking with rate limiting.
    Only captures ERROR+ level events to avoid spam.
    """
    if not settings.monitoring.sentry_dsn:
        logger.info("Sentry DSN not configured, skipping Sentry setup")
        return
    
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
        
        sentry_logging = LoggingIntegration(
            level=logging.INFO,        # Capture info and above as breadcrumbs
            event_level=logging.ERROR  # Only send ERROR+ as events to avoid spam
        )
        
        sentry_sdk.init(
            dsn=settings.monitoring.sentry_dsn,
            integrations=[sentry_logging],
            traces_sample_rate=0.1,    # Low sampling rate for performance
            release=settings.monitoring.app_version,
            environment=settings.environment.value,
            before_send=_filter_sentry_events,  # Custom filter to reduce noise
        )
        logger.info("Sentry monitoring initialized")
        
    except ImportError:
        logger.warning("Sentry SDK not installed, error tracking disabled")
    except Exception as e:
        logger.error("Failed to initialize Sentry", error=str(e))


def _filter_sentry_events(event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Filter out expected/noisy errors from Sentry to avoid spam.
    Returns None to drop the event, or the event to send it.
    """
    # Don't send events for expected Telegram API errors
    if 'exception' in event:
        for exception in event['exception']['values']:
            error_type = exception.get('type', '')
            error_value = exception.get('value', '')
            
            # Filter out common expected errors
            if 'TelegramBadRequest' in error_type and any(msg in error_value for msg in [
                'message to delete not found',
                'message is not modified', 
                'can\'t parse entities',
                'query is too old'
            ]):
                return None
                
            # Filter out network timeouts (temporary issues)
            if 'TelegramNetworkError' in error_type:
                return None
    
    return event


class TelegramMetrics:
    """
    Collects and logs key metrics for Telegram bot operations.
    Provides context for performance monitoring and debugging.
    """
    
    @staticmethod
    def log_handler_execution(
        handler_name: str,
        user_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        duration_ms: Optional[float] = None,
        success: bool = True,
        error: Optional[str] = None,
        **extra_context
    ) -> None:
        """Log handler execution with standardized fields."""
        logger.info(
            "Handler execution",
            action=handler_name,
            user_id=user_id,
            chat_id=chat_id,
            duration_ms=duration_ms,
            success=success,
            error=error,
            **extra_context
        )
    
    @staticmethod
    def log_llm_request(
        user_id: int,
        model: str,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        duration_ms: Optional[float] = None,
        cost: Optional[float] = None,
        success: bool = True,
        error: Optional[str] = None
    ) -> None:
        """Log LLM API requests with token and cost tracking."""
        logger.info(
            "LLM request",
            action="llm_request", 
            user_id=user_id,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=duration_ms,
            cost=cost,
            success=success,
            error=error
        )
    
    @staticmethod
    def log_callback_query(
        callback_data: str,
        user_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        success: bool = True,
        error: Optional[str] = None
    ) -> None:
        """Log callback query handling for debugging UI flows."""
        logger.info(
            "Callback query",
            action="callback_query",
            callback=callback_data,
            user_id=user_id,
            chat_id=chat_id,
            success=success,
            error=error
        )


def log_execution_time(action_name: str):
    """
    Decorator to automatically log execution time of functions.
    Usage: @log_execution_time("function_name")
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.debug(
                    "Function execution", 
                    action=action_name,
                    duration_ms=round(duration_ms, 2),
                    success=True
                )
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.error(
                    "Function execution failed",
                    action=action_name,
                    duration_ms=round(duration_ms, 2),
                    success=False,
                    error=str(e)
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.debug(
                    "Function execution",
                    action=action_name,
                    duration_ms=round(duration_ms, 2),
                    success=True
                )
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.error(
                    "Function execution failed",
                    action=action_name,
                    duration_ms=round(duration_ms, 2),
                    success=False,
                    error=str(e)
                )
                raise
        
        # Return appropriate wrapper based on function type
        if hasattr(func, '__code__') and func.__code__.co_flags & 0x80:  # CO_COROUTINE
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# Export the main metrics instance for easy imports
metrics = TelegramMetrics()
