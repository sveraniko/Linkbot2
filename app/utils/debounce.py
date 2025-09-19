"""Debounce manager for preventing duplicate operations and improving UX"""
import asyncio
import time
from typing import Dict, Optional, Set, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from app.config import settings

import logging
logger = logging.getLogger(__name__)

@dataclass
class DebounceEntry:
    """Entry in the debounce cache"""
    last_call: datetime
    lock: asyncio.Lock
    result: Optional[Any] = None
    in_progress: bool = False

class DebounceManager:
    """
    Manager for debouncing user interactions to prevent duplicate operations.
    
    Provides two main features:
    1. Time-based debouncing - prevents rapid successive calls
    2. Idempotent operations - returns cached result for identical operations in progress
    """
    
    def __init__(self, timeout_ms: int = None):
        self.timeout_ms = timeout_ms or settings.security.debounce_timeout_ms
        self.timeout = timedelta(milliseconds=self.timeout_ms)
        self._cache: Dict[str, DebounceEntry] = {}
        self._cleanup_interval = 60  # Clean up old entries every 60 seconds
        self._last_cleanup = time.time()
    
    def _cleanup_old_entries(self):
        """Remove old entries to prevent memory leaks"""
        current_time = time.time()
        if current_time - self._last_cleanup < self._cleanup_interval:
            return
            
        now = datetime.now()
        cutoff = now - timedelta(seconds=300)  # Remove entries older than 5 minutes
        
        old_keys = [
            key for key, entry in self._cache.items()
            if entry.last_call < cutoff and not entry.in_progress
        ]
        
        for key in old_keys:
            del self._cache[key]
        
        self._last_cleanup = current_time
        if old_keys:
            logger.debug(f"Cleaned up {len(old_keys)} old debounce entries")
    
    async def should_process(self, key: str) -> bool:
        """
        Check if the operation should be processed based on debounce rules.
        
        Args:
            key: Unique identifier for the operation (e.g., "user_id:message_id:action")
            
        Returns:
            True if operation should proceed, False if it should be debounced
        """
        if not settings.features.use_debounce:
            return True
        
        self._cleanup_old_entries()
        
        now = datetime.now()
        
        if key not in self._cache:
            self._cache[key] = DebounceEntry(
                last_call=now,
                lock=asyncio.Lock()
            )
            return True
        
        entry = self._cache[key]
        
        async with entry.lock:
            # Check if enough time has passed since last call
            if now - entry.last_call < self.timeout:
                logger.debug(f"Debounced operation: {key}")
                return False
            
            # Update last call time
            entry.last_call = now
            return True
    
    async def execute_with_idempotency(self, key: str, operation, *args, **kwargs):
        """
        Execute operation with idempotency protection.
        
        If the same operation is already in progress, waits for it to complete
        and returns the same result instead of executing again.
        
        Args:
            key: Unique identifier for the operation
            operation: Async function to execute
            *args, **kwargs: Arguments to pass to the operation
            
        Returns:
            Result of the operation
        """
        if not settings.features.use_debounce:
            return await operation(*args, **kwargs)
        
        self._cleanup_old_entries()
        
        if key not in self._cache:
            self._cache[key] = DebounceEntry(
                last_call=datetime.now(),
                lock=asyncio.Lock()
            )
        
        entry = self._cache[key]
        
        async with entry.lock:
            # If operation is already in progress, wait for it
            if entry.in_progress and entry.result is not None:
                logger.debug(f"Returning cached result for: {key}")
                return entry.result
            
            # Mark as in progress
            entry.in_progress = True
            entry.last_call = datetime.now()
            
            try:
                # Execute the operation
                result = await operation(*args, **kwargs)
                entry.result = result
                return result
                
            except Exception as e:
                entry.result = None
                raise e
                
            finally:
                entry.in_progress = False
    
    def create_key(self, user_id: int, message_id: int, action: str, **extra) -> str:
        """
        Create a standardized debounce key.
        
        Args:
            user_id: Telegram user ID
            message_id: Telegram message ID  
            action: Action type (ask, refine, list, etc.)
            **extra: Additional parameters to include in key
            
        Returns:
            Formatted debounce key
        """
        key_parts = [str(user_id), str(message_id), action]
        
        # Add sorted extra parameters for consistent key generation
        for k, v in sorted(extra.items()):
            key_parts.append(f"{k}:{v}")
        
        return ":".join(key_parts)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get debounce manager statistics"""
        active_entries = sum(1 for entry in self._cache.values() if entry.in_progress)
        total_entries = len(self._cache)
        
        return {
            "enabled": settings.features.use_debounce,
            "timeout_ms": self.timeout_ms,
            "total_entries": total_entries,
            "active_entries": active_entries,
            "cache_size_bytes": len(str(self._cache))
        }

# Global instance for use across the application
debounce_manager = DebounceManager()

# Convenience functions for common patterns
async def debounce_user_action(user_id: int, message_id: int, action: str, **extra) -> bool:
    """Quick check if user action should be processed"""
    key = debounce_manager.create_key(user_id, message_id, action, **extra)
    return await debounce_manager.should_process(key)

async def execute_with_debounce(user_id: int, message_id: int, action: str, 
                               operation, *args, **kwargs):
    """Execute operation with debouncing and idempotency"""
    key = debounce_manager.create_key(user_id, message_id, action)
    return await debounce_manager.execute_with_idempotency(key, operation, *args, **kwargs)
