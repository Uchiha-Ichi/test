import asyncio
import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Use SQLite for tests before app modules initialize their default engine.
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.api.deps import get_redis
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_maker = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class FakeRedis:
    def __init__(self):
        self.store = {}
    async def get(self, key: str) -> str | None:
        return self.store.get(key)
    async def set(self, key: str, value: str, ex: int | None = None):
        self.store[key] = value
    async def delete(self, *keys: str):
        for k in keys:
            self.store.pop(k, None)
    async def scan(self, cursor: int, match: str | None = None, count: int | None = None):
        import fnmatch
        keys = list(self.store.keys())
        if match:
            matched = [k for k in keys if fnmatch.fnmatch(k, match)]
        else:
            matched = keys
        return 0, matched
    async def exists(self, key: str) -> bool:
        return key in self.store

fake_redis = FakeRedis()


@pytest.fixture(autouse=True)
def clear_redis():
    fake_redis.store.clear()
    yield


def override_get_redis():
    return fake_redis


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_redis] = override_get_redis


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_maker() as session:
        yield session


@pytest.fixture
def auth_headers() -> dict:
    """Create auth headers with a valid token for testing."""
    token = create_access_token(data={"sub": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}
