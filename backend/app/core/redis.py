import redis.asyncio as aioredis

from app.core.config import settings


class RedisClient:
    def __init__(self):
        self._redis = None

    async def initialize(self):
        self._redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )

    async def close(self):
        if self._redis:
            await self._redis.close()

    @property
    def client(self):
        return self._redis

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        await self._redis.set(key, value, ex=ex)

    async def delete(self, *keys: str):
        await self._redis.delete(*keys)

    async def exists(self, key: str) -> bool:
        return await self._redis.exists(key)

    async def scan(self, cursor: int, match: str | None = None, count: int | None = None):
        return await self._redis.scan(cursor, match=match, count=count)


redis_client = RedisClient()
