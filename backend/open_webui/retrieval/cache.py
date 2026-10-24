"""
RAG Search Cache Service

Provides caching for vector search results with TTL and statistics.
Supports both in-memory LRU and Redis backends.
"""

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple, Union

# Redis connection

# Import RAG cache configuration variables
from open_webui.env import (
    ENABLE_RAG_SEARCH_CACHE,
    RAG_CACHE_SIZE,
    RAG_CACHE_TTL,
    RAG_CACHE_BACKEND,
    RAG_REDIS_HOST,
    RAG_REDIS_PORT,
    RAG_REDIS_DB,
    RAG_REDIS_PASSWORD,
    RAG_REDIS_MAX_CONNECTIONS,
)
try:
    import redis
    from redis import ConnectionPool
except ImportError:
    redis = None
    ConnectionPool = None

log = logging.getLogger(__name__)


class CacheEntry:
    """Cache entry with timestamp and TTL."""

    def __init__(self, value: Any, ttl: int = 3600):
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl
        self.access_count = 0

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl

    def access(self):
        self.access_count += 1


class LRUBackend:
    """In-memory LRU cache with TTL support."""

    def __init__(self, capacity: int = 10000, default_ttl: int = 3600):
        self.capacity = capacity
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._ordered: List[str] = []  # For LRU ordering
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "current_size": 0,
            "total_requests": 0,
        }

    def get(self, key: str) -> Optional[Any]:
        self.stats["total_requests"] += 1
        if key in self._cache:
            entry = self._cache[key]
            if not entry.is_expired():
                entry.access()
                self.stats["hits"] += 1
                return entry.value
            else:
                # Remove expired entry
                del self._cache[key]
                self._ordered.remove(key)
        self.stats["misses"] += 1
        return None

    def set(self, key: str, value: Any, ttl: int = None):
        ttl = ttl or self.default_ttl

        # Check capacity and evict if needed
        while len(self._cache) >= self.capacity:
            self._evict_lru()

        # Add new entry
        entry = CacheEntry(value, ttl)
        self._cache[key] = entry
        # Move to end of LRU order (most recently used)
        if key in self._ordered:
            self._ordered.remove(key)
        self._ordered.append(key)
        self.stats["current_size"] = len(self._cache)

    def _evict_lru(self):
        """Evict least recently used entry."""
        if not self._ordered:
            return
        lru_key = self._ordered.pop(0)
        if lru_key in self._cache:
            del self._cache[lru_key]
            self.stats["current_size"] = len(self._cache)
            self.stats["evictions"] += 1

    def clear(self):
        self._cache.clear()
        self._ordered.clear()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "current_size": 0,
            "total_requests": 0,
        }

    def invalidate_pattern(self, pattern: str):
        """Remove entries matching a key pattern."""
        to_remove = [k for k in self._cache if pattern in k]
        for k in to_remove:
            del self._cache[k]
            if k in self._ordered:
                self._ordered.remove(k)
            self.stats["current_size"] = len(self._cache)

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "backend": "memory",
        }


class RedisBackend:
    """Redis-backed cache with TTL and statistics."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 50,
        default_ttl: int = 3600,
    ):
        if redis is None:
            raise ImportError("redis-py is required for Redis backend")

        self.default_ttl = default_ttl
        self.connection_pool = ConnectionPool(
            host=host, port=port, db=db, password=password, max_connections=max_connections, decode_responses=False
        )
        self._client = redis.Redis(connection_pool=self.connection_pool)

        # Stats
        self.stats = {
            "hits": 0,
            "misses": 0,
            "current_size": 0,  # Redis size estimation
            "total_requests": 0,
            "backend": "redis",
        }

        # Test connection
        try:
            self._client.ping()
            log.info("Redis cache connection established")
        except Exception as e:
            log.error(f"Failed to connect to Redis: {e}")
            raise

    def _make_key(self, pattern: str, *args, **kwargs) -> str:
        """Generate consistent key from search parameters (for Redis)."""
        key_dict = {"args": args, "kwargs": kwargs}
        key_str = json.dumps(key_dict, sort_keys=True, default=str)
        return pattern + ":" + hashlib.sha256(key_str.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        self.stats["total_requests"] += 1
        try:
            value = self._client.get(key)
            if value is not None:
                # Decode and deserialize
                deserialized = json.loads(value)
                self.stats["hits"] += 1
                return deserialized["value"]
        except Exception as e:
            log.error(f"Redis get error: {e}")

        self.stats["misses"] += 1
        return None

    def set(self, key: str, value: Any, ttl: int = None):
        ttl = ttl or self.default_ttl
        try:
            self._client.setex(
                key, ttl, json.dumps({"value": value, "created_at": time.time()}, default=str)
            )
        except Exception as e:
            log.error(f"Redis set error: {e}")

    def invalidate(self, key: str):
        try:
            self._client.delete(key)
        except Exception as e:
            log.error(f"Redis invalidate error: {e}")

    def invalidate_pattern(self, pattern: str):
        try:
            # Use KEYS to find keys matching pattern, then delete them
            keys = self._client.keys(pattern + ":*")
            if keys:
                self._client.delete(*keys)
        except Exception as e:
            log.error(f"Redis invalidate pattern error: {e}")

    def clear(self):
        try:
            # Only flush the current database
            self._client.flushdb()
            self.stats["hits"] = 0
            self.stats["misses"] = 0
            self.stats["evictions"] = 0
            self.stats["current_size"] = 0
            self.stats["total_requests"] = 0
        except Exception as e:
            log.error(f"Redis clear error: {e}")

    def get_size(self) -> int:
        """Estimate the number of keys in the cache."""
        try:
            # Count keys matching our pattern (NOTE: This can be slow for large databases)
            pattern = "rag:cache:*"
            keys = self._client.keys(pattern)
            return len(keys) if keys else 0
        except Exception as e:
            log.error(f"Redis size error: {e}")
            return 0

    def get_stats(self) -> Dict[str, Any]:
        try:
            info = self._client.info("memory")
            used_memory = info.get("used_memory_human", "unknown")
            connected_clients = info.get("connected_clients", 0)
            return {
                **self.stats,
                "backend": "redis",
                "used_memory": used_memory,
                "connected_clients": connected_clients,
            }
        except Exception as e:
            log.error(f"Redis stats error: {e}")
            return self.stats


class CacheService:
    """Service for caching RAG search results."""

    def __init__(self, enabled: bool = True, backend: str = "memory", **backend_kwargs):
        self.enabled = enabled
        self.backend = backend
        self.backend_kwargs = backend_kwargs
        self._stats = {}

        # Initialize backend
        if enabled:
            if backend == "memory":
                self.cache = LRUBackend(
                    capacity=backend_kwargs.get("capacity", 10000),
                    default_ttl=backend_kwargs.get("ttl", 3600),
                )
            elif backend == "redis":
                self.cache = RedisBackend(
                    host=backend_kwargs.get("host", "localhost"),
                    port=backend_kwargs.get("port", 6379),
                    db=backend_kwargs.get("db", 0),
                    password=backend_kwargs.get("password"),
                    max_connections=backend_kwargs.get("max_connections", 50),
                    default_ttl=backend_kwargs.get("ttl", 3600),
                )
            else:
                raise ValueError(f"Unsupported cache backend: {backend}")

    def generate_key(
        self,
        collection_name: str,
        query: Optional[str] = None,
        vectors: Optional[List[List[float]]] = None,
        limit: int = 10,
        filter: Optional[Dict] = None,
        hybrid_bm25_weight: float = 0.5,
        model_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Generate a cache key from search parameters."""
        # Create a unique key based on parameters
        data = {
            "collection": collection_name,
            "query": query,
            "vectors_hash": hashlib.sha256(
                str(vectors).encode() if vectors and len(vectors) > 0 else b""
            ).hexdigest(),
            "limit": limit,
            "filter": filter,
            "hybrid_bm25_weight": hybrid_bm25_weight,
            "model_id": model_id,
            "user_id": user_id,
        }
        return hashlib.sha256(str(data).encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:  # redis: str
        if not self.enabled:
            return None
        return self.cache.get(key)

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        if not self.enabled:
            return
        self.cache.set(key, value, ttl)

    def invalidate(self, *keys: str):
        """Invalidate specific cache entries."""
        if not self.enabled:
            return
        for key in keys:
            self.cache.invalidate(key)

    def invalidate_collection(self, collection_name: str):
        """Invalidate all cache entries for a specific collection."""
        if not self.enabled:
            return
        self.cache.invalidate_pattern(f"rag:cache:{collection_name}")

    def get_stats(self) -> Dict[str, Any]:
        if not self.enabled or not hasattr(self.cache, "get_stats"):
            return {"enabled": self.enabled, "backend": self.backend, "hit_rate": 0.0}
        return self.cache.get_stats()


# Singleton instance
_cache_service: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    """Get the singleton cache service instance."""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service


def set_cache_service(service: CacheService):
    """Set the singleton cache service instance."""
    global _cache_service
    _cache_service = service


def init_cache_service():
    """Initialize cache service based on environment configuration."""
    enabled = ENABLE_RAG_SEARCH_CACHE
    backend = RAG_CACHE_BACKEND
    kwargs = {
        "ttl": int(RAG_CACHE_TTL),
        "capacity": int(RAG_CACHE_SIZE) if backend == "memory" else None,
        "host": RAG_REDIS_HOST,
        "port": int(RAG_REDIS_PORT),
        "db": int(RAG_REDIS_DB),
        "password": RAG_REDIS_PASSWORD,
        "max_connections": int(RAG_REDIS_MAX_CONNECTIONS),
    }

    # Filter out None values
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    log.info(f"RAG Cache Service: {'Enabled' if enabled else 'Disabled'}, backend={backend}")
    service = CacheService(enabled=enabled, backend=backend, **kwargs)
    set_cache_service(service)
    return service


# Initialize cache service based on config
def init_cache_service():
    enabled = ENABLE_RAG_SEARCH_CACHE
    backend = RAG_CACHE_BACKEND
    kwargs = {
        "ttl": int(RAG_CACHE_TTL),
        "capacity": int(RAG_CACHE_SIZE) if backend == "memory" else None,
        "host": RAG_REDIS_HOST,
        "port": int(RAG_REDIS_PORT),
        "db": int(RAG_REDIS_DB),
        "password": RAG_REDIS_PASSWORD,
        "max_connections": int(RAG_REDIS_MAX_CONNECTIONS),
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    log.info(f"RAG Cache Service: {'Enabled' if enabled else 'Disabled'}, backend={backend}")
    service = CacheService(enabled=enabled, backend=backend, **kwargs)
    set_cache_service(service)
    return service


# For backwards compatibility
CACHE = get_cache_service()
