"""Redis-based cache service for improving performance with hot data"""
import json
import pickle
import hashlib
from typing import Optional, Any, Union, Dict, List
from datetime import datetime, timedelta
import redis.asyncio as redis

from app.config import settings
import logging

logger = logging.getLogger(__name__)

class CacheService:
    """
    Redis-based caching service with automatic serialization and TTL management.
    
    Features:
    - Automatic JSON serialization for simple data types
    - Pickle fallback for complex objects
    - TTL management with default and custom expiration times
    - Connection pooling for better performance
    - Graceful fallback when Redis is unavailable
    """
    
    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._connection_pool: Optional[redis.ConnectionPool] = None
        self._is_available = False
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize Redis connection with connection pooling"""
        if not settings.features.use_cache or not settings.redis.is_configured:
            logger.info("Cache service disabled or Redis not configured")
            return
        
        try:
            # Create connection pool
            pool_kwargs = {
                "host": settings.redis.host,
                "port": settings.redis.port,
                "db": settings.redis.db,
                "decode_responses": False,  # We handle encoding ourselves
                "max_connections": settings.redis.connection_pool_size,
                "retry_on_timeout": True,
                "socket_keepalive": True,
                "socket_keepalive_options": {},
                "health_check_interval": 30
            }
            
            if settings.redis.password:
                pool_kwargs["password"] = settings.redis.password.get_secret_value()
            
            if settings.redis.ssl:
                pool_kwargs["connection_class"] = redis.SSLConnection
            
            self._connection_pool = redis.ConnectionPool(**pool_kwargs)
            self._redis = redis.Redis(connection_pool=self._connection_pool)
            self._is_available = True
            
            logger.info(f"Cache service initialized with Redis connection pooling: "
                       f"host={settings.redis.host}, port={settings.redis.port}, "
                       f"pool_size={settings.redis.connection_pool_size}")
            
        except Exception as e:
            logger.error(f"Failed to initialize cache service: {str(e)}")
            self._is_available = False
    
    def _serialize_value(self, value: Any) -> bytes:
        """Serialize value for storage in Redis"""
        try:
            # Try JSON first for better readability and smaller size
            if isinstance(value, (str, int, float, bool, list, dict, type(None))):
                return json.dumps(value, default=str).encode('utf-8')
            else:
                # Fallback to pickle for complex objects
                return pickle.dumps(value)
        except (TypeError, ValueError):
            # Final fallback to pickle
            return pickle.dumps(value)
    
    def _deserialize_value(self, data: bytes) -> Any:
        """Deserialize value from Redis storage"""
        try:
            # Try JSON first
            text = data.decode('utf-8')
            return json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            # Fallback to pickle
            try:
                return pickle.loads(data)
            except pickle.PickleError:
                logger.error("Failed to deserialize cached value")
                return None
    
    def _create_cache_key(self, key: str, namespace: str = "default") -> str:
        """Create a namespaced cache key"""
        app_version = settings.monitoring.app_version
        return f"memory_bot:{app_version}:{namespace}:{key}"
    
    async def get(self, key: str, namespace: str = "default") -> Optional[Any]:
        """Get value from cache"""
        if not self._is_available or not self._redis:
            return None
        
        try:
            cache_key = self._create_cache_key(key, namespace)
            data = await self._redis.get(cache_key)
            
            if data is None:
                return None
            
            value = self._deserialize_value(data)
            logger.debug(f"Cache hit: {cache_key}")
            return value
            
        except Exception as e:
            logger.warning(f"Cache get failed for key {key}: {str(e)}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = None, namespace: str = "default") -> bool:
        """Set value in cache with TTL"""
        if not self._is_available or not self._redis:
            return False
        
        try:
            cache_key = self._create_cache_key(key, namespace)
            serialized_value = self._serialize_value(value)
            ttl_seconds = ttl or settings.security.cache_ttl
            
            await self._redis.set(cache_key, serialized_value, ex=ttl_seconds)
            logger.debug(f"Cache set: {cache_key} (TTL: {ttl_seconds}s)")
            return True
            
        except Exception as e:
            logger.warning(f"Cache set failed for key {key}: {str(e)}")
            return False
    
    async def delete(self, key: str, namespace: str = "default") -> bool:
        """Delete value from cache"""
        if not self._is_available or not self._redis:
            return False
        
        try:
            cache_key = self._create_cache_key(key, namespace)
            result = await self._redis.delete(cache_key)
            logger.debug(f"Cache delete: {cache_key}")
            return result > 0
            
        except Exception as e:
            logger.warning(f"Cache delete failed for key {key}: {str(e)}")
            return False
    
    async def exists(self, key: str, namespace: str = "default") -> bool:
        """Check if key exists in cache"""
        if not self._is_available or not self._redis:
            return False
        
        try:
            cache_key = self._create_cache_key(key, namespace)
            return await self._redis.exists(cache_key) > 0
        except Exception as e:
            logger.warning(f"Cache exists check failed for key {key}: {str(e)}")
            return False
    
    async def get_or_set(self, key: str, value_factory, ttl: int = None, 
                        namespace: str = "default") -> Any:
        """Get from cache or set if not exists (cache-aside pattern)"""
        # Try to get from cache first
        cached_value = await self.get(key, namespace)
        if cached_value is not None:
            return cached_value
        
        # Generate new value
        try:
            if callable(value_factory):
                if asyncio.iscoroutinefunction(value_factory):
                    value = await value_factory()
                else:
                    value = value_factory()
            else:
                value = value_factory
            
            # Cache the new value
            await self.set(key, value, ttl, namespace)
            return value
            
        except Exception as e:
            logger.error(f"Value factory failed for cache key {key}: {str(e)}")
            return None
    
    async def increment(self, key: str, amount: int = 1, namespace: str = "default") -> Optional[int]:
        """Increment a counter in cache"""
        if not self._is_available or not self._redis:
            return None
        
        try:
            cache_key = self._create_cache_key(key, namespace)
            result = await self._redis.incrby(cache_key, amount)
            return result
        except Exception as e:
            logger.warning(f"Cache increment failed for key {key}: {str(e)}")
            return None
    
    async def expire(self, key: str, ttl: int, namespace: str = "default") -> bool:
        """Set TTL for existing key"""
        if not self._is_available or not self._redis:
            return False
        
        try:
            cache_key = self._create_cache_key(key, namespace)
            return await self._redis.expire(cache_key, ttl)
        except Exception as e:
            logger.warning(f"Cache expire failed for key {key}: {str(e)}")
            return False
    
    async def clear_namespace(self, namespace: str) -> int:
        """Clear all keys in a namespace"""
        if not self._is_available or not self._redis:
            return 0
        
        try:
            pattern = self._create_cache_key("*", namespace)
            keys = await self._redis.keys(pattern)
            if keys:
                deleted = await self._redis.delete(*keys)
                logger.info(f"Cleared {deleted} keys from namespace {namespace}")
                return deleted
            return 0
        except Exception as e:
            logger.warning(f"Cache clear namespace failed for {namespace}: {str(e)}")
            return 0
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = {
            "enabled": settings.features.use_cache,
            "available": self._is_available,
            "redis_configured": settings.redis.is_configured
        }
        
        if self._is_available and self._redis:
            try:
                info = await self._redis.info()
                stats.update({
                    "connected_clients": info.get("connected_clients", 0),
                    "used_memory": info.get("used_memory", 0),
                    "keyspace_hits": info.get("keyspace_hits", 0),
                    "keyspace_misses": info.get("keyspace_misses", 0),
                    "total_commands_processed": info.get("total_commands_processed", 0)
                })
                
                # Calculate hit rate
                hits = stats["keyspace_hits"]
                misses = stats["keyspace_misses"]
                if hits + misses > 0:
                    stats["hit_rate"] = hits / (hits + misses)
                else:
                    stats["hit_rate"] = 0.0
                    
            except Exception as e:
                logger.warning(f"Failed to get Redis stats: {str(e)}")
                stats["stats_error"] = str(e)
        
        return stats

# Domain-specific cache methods
class UserCacheService:
    """Cache service for user-specific data"""
    
    def __init__(self, cache: CacheService):
        self.cache = cache
        self.namespace = "user"
    
    async def get_user_profile(self, user_id: int) -> Optional[Dict]:
        """Get cached user profile"""
        return await self.cache.get(f"profile:{user_id}", self.namespace)
    
    async def set_user_profile(self, user_id: int, profile: Dict, ttl: int = 600) -> bool:
        """Cache user profile for 10 minutes by default"""
        return await self.cache.set(f"profile:{user_id}", profile, ttl, self.namespace)
    
    async def get_user_projects(self, user_id: int) -> Optional[List]:
        """Get cached user projects"""
        return await self.cache.get(f"projects:{user_id}", self.namespace)
    
    async def set_user_projects(self, user_id: int, projects: List, ttl: int = 300) -> bool:
        """Cache user projects for 5 minutes by default"""
        return await self.cache.set(f"projects:{user_id}", projects, ttl, self.namespace)
    
    async def get_user_settings(self, user_id: int) -> Optional[Dict]:
        """Get cached user settings"""
        return await self.cache.get(f"settings:{user_id}", self.namespace)
    
    async def set_user_settings(self, user_id: int, settings_data: Dict, ttl: int = 1800) -> bool:
        """Cache user settings for 30 minutes by default"""
        return await self.cache.set(f"settings:{user_id}", settings_data, ttl, self.namespace)
    
    async def invalidate_user(self, user_id: int):
        """Invalidate all cached data for a user"""
        keys_to_delete = [
            f"profile:{user_id}",
            f"projects:{user_id}", 
            f"settings:{user_id}"
        ]
        
        for key in keys_to_delete:
            await self.cache.delete(key, self.namespace)

# Global instances
cache_service = CacheService()
user_cache = UserCacheService(cache_service)

# Import asyncio at module level for proper detection
import asyncio
