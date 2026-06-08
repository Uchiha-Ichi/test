import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_redis
from app.core.redis import RedisClient
from app.db.session import get_db
from app.models.todo import Todo
from app.models.user import User
from app.schemas.todo import TodoCreate, TodoListResponse, TodoResponse, TodoUpdate
from app.services.todo_service import (
    create_todo,
    delete_todo,
    get_todo_by_id,
    get_todos,
    update_todo,
)

router = APIRouter()

CACHE_TTL = 300  # 5 minutes


@router.get("", response_model=TodoListResponse)
async def list_todos(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """Get paginated list of todos."""
    skip = (page - 1) * size

    # Bug 3 fix: scope cache key by user_id, page, and size to prevent data leaks
    cache_key = f"todos:list:{current_user.id}:{page}:{size}"

    # Try to get from cache
    cached = await redis.get(cache_key)
    if cached:
        cached_data = json.loads(cached)
        return TodoListResponse(**cached_data)

    # Bug 9 fix: fetch todos with user email in a single query using JOIN
    todos, total = await get_todos(db, user_id=current_user.id, skip=skip, limit=size)

    items = []
    for todo in todos:
        items.append(
            TodoResponse(
                id=todo.id,
                title=todo.title,
                description=todo.description,
                completed=todo.completed,
                user_id=todo.user_id,
                created_at=todo.created_at,
                updated_at=todo.updated_at,
                user_email=current_user.email,
            )
        )

    response = TodoListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )

    # Cache the response
    await redis.set(cache_key, response.model_dump_json(), ex=CACHE_TTL)

    return response


@router.post("", response_model=TodoResponse, status_code=status.HTTP_201_CREATED)
async def create_new_todo(
    todo_data: TodoCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """Create a new todo item."""
    todo = await create_todo(db, todo_data, current_user.id)
    # Invalidate user's todo cache
    await _invalidate_todo_cache(redis, current_user.id)
    return todo


@router.get("/{todo_id}", response_model=TodoResponse)
async def get_todo(
    todo_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific todo by ID."""
    todo = await get_todo_by_id(db, todo_id)
    if not todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found",
        )

    # Bug 5 fix: enforce ownership — users can only access their own todos
    if todo.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return todo


@router.put("/{todo_id}", response_model=TodoResponse)
async def update_existing_todo(
    todo_id: uuid.UUID,
    todo_data: TodoUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """Update a todo item."""
    todo = await get_todo_by_id(db, todo_id)
    if not todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found",
        )

    # Bug 5 fix: enforce ownership
    if todo.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Bug 7 fix: use `is not None` so completed=False is applied correctly
    # Bug 8 fix: build the actual update_data dict and pass it to update_todo
    update_data = {}
    if todo_data.completed is not None:
        update_data["completed"] = todo_data.completed
    if todo_data.title is not None:
        update_data["title"] = todo_data.title
    if "description" in todo_data.model_fields_set:
        update_data["description"] = todo_data.description

    updated_todo = await update_todo(db, todo, update_data)

    # Invalidate user's todo cache
    await _invalidate_todo_cache(redis, current_user.id)

    return updated_todo


@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_existing_todo(
    todo_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """Delete a todo item."""
    todo = await get_todo_by_id(db, todo_id)
    if not todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found",
        )

    # Bug 5 fix: enforce ownership
    if todo.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    await delete_todo(db, todo)

    # Invalidate user's todo cache
    await _invalidate_todo_cache(redis, current_user.id)

    return None


async def _invalidate_todo_cache(redis: RedisClient, user_id: uuid.UUID) -> None:
    """Invalidate all cached todo pages for a given user."""
    # Scan and delete all keys matching this user's todo cache pattern
    pattern = f"todos:list:{user_id}:*"
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        for key in keys:
            await redis.delete(key)
        if cursor == 0:
            break
