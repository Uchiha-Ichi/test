"""Todo tests."""

import pytest
from httpx import AsyncClient


async def get_auth_token(client: AsyncClient, email: str = "todo@example.com") -> str:
    """Helper to register and get auth token."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_create_todo(client: AsyncClient):
    """Test creating a new todo."""
    token = await get_auth_token(client, "create@example.com")

    response = await client.post(
        "/api/v1/todos",
        json={"title": "Test Todo", "description": "A test todo item"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Todo"
    assert data["description"] == "A test todo item"
    assert data["completed"] is False


@pytest.mark.asyncio
async def test_get_todos(client: AsyncClient):
    """Test getting todo list."""
    token = await get_auth_token(client, "list@example.com")

    # Create a todo first
    await client.post(
        "/api/v1/todos",
        json={"title": "List Todo"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Get todos
    response = await client.get(
        "/api/v1/todos",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert len(data["items"]) >= 1


@pytest.mark.asyncio
async def test_update_todo(client: AsyncClient):
    """Test updating a todo."""
    token = await get_auth_token(client, "update@example.com")

    # Create a todo
    create_response = await client.post(
        "/api/v1/todos",
        json={"title": "Update Me"},
        headers={"Authorization": f"Bearer {token}"},
    )
    todo_id = create_response.json()["id"]

    # Update it
    response = await client.put(
        f"/api/v1/todos/{todo_id}",
        json={"title": "Updated Title", "completed": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    assert data["completed"] is True


@pytest.mark.asyncio
async def test_delete_todo(client: AsyncClient):
    """Test deleting a todo."""
    token = await get_auth_token(client, "delete@example.com")

    # Create a todo
    create_response = await client.post(
        "/api/v1/todos",
        json={"title": "Delete Me"},
        headers={"Authorization": f"Bearer {token}"},
    )
    todo_id = create_response.json()["id"]

    # Delete it
    response = await client.delete(
        f"/api/v1/todos/{todo_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_get_single_todo(client: AsyncClient):
    """Test getting a single todo by ID."""
    token = await get_auth_token(client, "single@example.com")

    # Create a todo
    create_response = await client.post(
        "/api/v1/todos",
        json={"title": "Single Todo", "description": "Get me"},
        headers={"Authorization": f"Bearer {token}"},
    )
    todo_id = create_response.json()["id"]

    # Get it
    response = await client.get(
        f"/api/v1/todos/{todo_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Single Todo"


@pytest.mark.asyncio
async def test_cross_user_todo_access_prevented(client: AsyncClient):
    """Bug 5: Test that User B cannot read, update, or delete User A's todo."""
    # User A creates a todo
    token_a = await get_auth_token(client, "usera@example.com")
    create_response = await client.post(
        "/api/v1/todos",
        json={"title": "User A Todo"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    todo_id = create_response.json()["id"]

    # User B logs in
    token_b = await get_auth_token(client, "userb@example.com")

    # User B tries to read User A's todo
    read_resp = await client.get(
        f"/api/v1/todos/{todo_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert read_resp.status_code == 403
    assert read_resp.json()["detail"] == "Access denied"

    # User B tries to update User A's todo
    update_resp = await client.put(
        f"/api/v1/todos/{todo_id}",
        json={"title": "Hacked Title"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert update_resp.status_code == 403
    assert update_resp.json()["detail"] == "Access denied"

    # User B tries to delete User A's todo
    delete_resp = await client.delete(
        f"/api/v1/todos/{todo_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert delete_resp.status_code == 403
    assert delete_resp.json()["detail"] == "Access denied"


@pytest.mark.asyncio
async def test_update_completed_to_false(client: AsyncClient):
    """Bug 7: Test that updating completed status to False works correctly."""
    token = await get_auth_token(client, "toggle@example.com")

    # Create a todo (defaults to completed=False)
    create_response = await client.post(
        "/api/v1/todos",
        json={"title": "Toggle Todo"},
        headers={"Authorization": f"Bearer {token}"},
    )
    todo_id = create_response.json()["id"]

    # Mark completed=True
    resp_true = await client.put(
        f"/api/v1/todos/{todo_id}",
        json={"completed": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_true.status_code == 200
    assert resp_true.json()["completed"] is True

    # Mark completed=False
    resp_false = await client.put(
        f"/api/v1/todos/{todo_id}",
        json={"completed": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_false.status_code == 200
    assert resp_false.json()["completed"] is False


@pytest.mark.asyncio
async def test_redis_cache_key_user_scoped(client: AsyncClient):
    """Bug 3: Test that Redis cache keys are user-scoped."""
    from tests.conftest import fake_redis

    # User A lists todos
    token_a = await get_auth_token(client, "cache_a@example.com")
    resp_a = await client.get(
        "/api/v1/todos",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_a.status_code == 200

    # Locate User A's cache key in the fake Redis store
    keys_a = [k for k in fake_redis.store.keys() if "todos:list:" in k]
    assert len(keys_a) == 1

    # User B lists todos
    token_b = await get_auth_token(client, "cache_b@example.com")
    resp_b = await client.get(
        "/api/v1/todos",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_b.status_code == 200

    # Ensure another key was created for User B
    keys_b = [k for k in fake_redis.store.keys() if "todos:list:" in k]
    assert len(keys_b) == 2
