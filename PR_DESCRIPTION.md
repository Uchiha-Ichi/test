# Bug Report & Fix Assessment

## AI Assistance Disclosure

This assessment was completed with assistance from **Claude Sonnet** (Anthropic) via the Claude.ai chat interface.
The agent read the full codebase, identified bugs, implemented all fixes, wrote tests, and implemented the optional feature.
All AI instructions are documented in [`CLAUDE.md`](./CLAUDE.md).

---

## Bug Report

### 🔴 BUG-01 — JWT expiry not enforced (`verify_exp: False`)

**Location:** `backend/app/core/security.py` → `verify_token()`

**Reason:** The decode call passes `options={"verify_exp": False}`, meaning expired tokens are accepted forever. Any token issued to a user — even one from months ago — remains permanently valid.

**Fix:** Remove the `options` override. `python-jose` enforces expiry by default.

```python
# Before (broken)
payload = jwt.decode(token, settings.JWT_SECRET,
    algorithms=[settings.JWT_ALGORITHM],
    options={"verify_exp": False})   # ← expiry never checked

# After
payload = jwt.decode(token, settings.JWT_SECRET,
    algorithms=[settings.JWT_ALGORITHM])
```

---

### 🔴 BUG-02 — Refresh token accepted as access token

**Location:** `backend/app/api/deps.py` → `get_current_user()`

**Reason:** `get_current_user` only checks `payload is None` but never checks `payload["type"]`. A refresh token is a valid JWT signed with the same secret, so it passes the check. An attacker who steals a refresh token can call any protected endpoint with it.

**Fix:** Require `type == "access"`.

```python
if payload is None or payload.get("type") != "access":
    raise HTTPException(status_code=401, detail="Invalid authentication token")
```

---

### 🔴 BUG-03 — Cache key has no user scope → cross-user data leak

**Location:** `backend/app/api/v1/todos.py` → `list_todos()`

**Reason:** `cache_key = "todos:list"` is global. The first user to call `GET /todos` populates the cache. Every subsequent user receives that same cached response — containing another user's todos.

**Fix:** Include `user_id` and pagination params in the cache key.

```python
cache_key = f"todos:list:{current_user.id}:page={page}:size={size}"
```

---

### 🔴 BUG-04 — No authorization check on GET / PUT / DELETE todo endpoints

**Location:** `backend/app/api/v1/todos.py` → `get_todo`, `update_existing_todo`, `delete_existing_todo`

**Reason:** All three endpoints call `get_todo_by_id(db, todo_id)` and return/mutate the result without verifying that `todo.user_id == current_user.id`. Any authenticated user can read, modify, or delete any other user's todos by guessing or enumerating UUIDs.

**Fix:** Add ownership check after the 404 guard:

```python
if todo.user_id != current_user.id:
    raise HTTPException(status_code=403, detail="Not authorized")
```

---

### 🔴 BUG-05 — PUT update logic is broken (completed=False never saved, update_todo called with empty dict)

**Location:** `backend/app/api/v1/todos.py` → `update_existing_todo()`

**Reason:** Two sub-bugs:
1. `if todo_data.completed:` — falsy check means setting `completed=False` is silently ignored.
2. `update_todo(db, todo, {})` — always called with an empty dict, so `update_todo`'s loop never runs. Changes are only applied because SQLAlchemy tracks dirty state, but it's fragile and confusing.

**Fix:** Use `model_dump(exclude_unset=True)` and pass it to `update_todo`:

```python
update_data = todo_data.model_dump(exclude_unset=True)
updated_todo = await update_todo(db, todo, update_data)
```

---

### 🟠 BUG-06 — N+1 query in `list_todos`

**Location:** `backend/app/api/v1/todos.py` → `list_todos()`

**Reason:** For each todo, a separate `SELECT * FROM users WHERE id = ?` is executed inside a loop. For a page of 20 todos, this is 21 queries instead of 1.

**Fix:** Since all todos belong to `current_user`, use `current_user.email` directly. For the optional Tags feature, use `selectinload` on the `todo_tags` relationship.

---

### 🟠 BUG-07 — Login response leaks whether an email is registered

**Location:** `backend/app/api/v1/auth.py` → `login()`

**Reason:** Returns HTTP 404 "User with this email not found" vs HTTP 401 "Incorrect password". An attacker can enumerate valid email addresses by observing the status code difference.

**Fix:** Return the same generic 401 for both cases:

```python
if not user or not verify_password(user_data.password, user.hashed_password):
    raise HTTPException(status_code=401, detail="Invalid email or password")
```

---

### 🟠 BUG-08 — `users.email` has no UNIQUE constraint

**Location:** `backend/app/models/user.py`, `backend/alembic/versions/001_initial.py`

**Reason:** The model and migration both lack a unique constraint on `email`. The application checks for duplicates in Python (`get_user_by_email`) before inserting, but under concurrent requests, two users can register the same email simultaneously (TOCTOU race). The database should enforce uniqueness.

**Fix:** Add `unique=True` in the model and a migration:

```python
# model
email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
```

```python
# migration b1c2d3e4f5a6
op.create_unique_constraint("uq_users_email", "users", ["email"])
```

---

### 🟠 BUG-09 — Logout does not revoke the access token

**Location:** `backend/app/api/v1/auth.py` → `logout()`

**Reason:** Logout returns `{"message": "Successfully logged out"}` but does nothing server-side. The access token remains valid until it naturally expires (up to 30 minutes). Anyone who intercepts the token after logout can still use it.

**Fix:** Add a `jti` claim to access tokens and blacklist it in Redis on logout:

```python
# On logout
ttl = int(exp - now)
await redis.set(f"blacklist:{jti}", "1", ex=ttl)

# In get_current_user
if jti and await redis_client.exists(f"blacklist:{jti}"):
    raise HTTPException(status_code=401, detail="Token has been revoked")
```

---

### 🟠 BUG-10 — Refresh endpoint does not verify user still exists

**Location:** `backend/app/api/v1/auth.py` → `refresh_token()`

**Reason:** After validating the refresh token's signature and type, the endpoint immediately issues new tokens without checking that the user still exists in the database. If a user account is deleted, their refresh token keeps working indefinitely.

**Fix:** Look up the user from DB and return 401 if not found.

---

### 🟡 BUG-11 — Missing UNIQUE index and performance index in migrations

**Location:** `backend/alembic/versions/001_initial.py`

**Reason:** No unique constraint on `users.email` and no index on `todos(user_id, created_at)` for paginated queries.

**Fix:** Migration `b1c2d3e4f5a6` adds both.

---

### 🟡 BUG-12 (Frontend) — `key={index}` in TodoList instead of `key={todo.id}`

**Location:** `frontend/src/features/todos/components/TodoList.tsx`

**Reason:** Using array index as React key causes incorrect reconciliation when the list is reordered or filtered — items animate to wrong positions and checkboxes can swap between todos.

**Fix:** `key={todo.id}`

---

### 🟡 BUG-13 (Frontend) — Logout does not clear React Query cache

**Location:** `frontend/src/features/auth/hooks/useAuth.ts` → `logout()`

**Reason:** After logout, stale user data (todo list, current user) remains in the React Query cache. If a second user logs in on the same browser session, they briefly see the previous user's data.

**Fix:** Call `queryClient.clear()` in both `onSuccess` and `onError` of the logout mutation.

---

### 🟡 BUG-14 (Frontend) — `useTodos` query key does not include page/size

**Location:** `frontend/src/features/todos/api/todos.ts` → `useTodos()`

**Reason:** `queryKey: ["todos"]` is the same regardless of pagination params. Calling `useTodos(1, 20)` and `useTodos(2, 20)` hit the same cache entry — different pages return the same data.

Also: default `size=10000` bypasses pagination entirely, pulling the full dataset on every load.

**Fix:** `queryKey: ["todos", { page, size }]` and default `size=20`.

---

### 🟡 BUG-15 (Frontend) — Optimistic update does not rollback on error

**Location:** `frontend/src/features/todos/api/todos.ts` → `useUpdateTodo()` → `onError`

**Reason:** `onMutate` stores `previousTodos` in context and applies an optimistic update. But `onError` ignores `context` entirely, so if the mutation fails, the UI stays in the incorrect optimistic state until the next `invalidateQueries` refetch.

**Fix:**
```ts
onError: (_err, _vars, context) => {
  if (context?.previousTodos) {
    queryClient.setQueryData(["todos"], context.previousTodos);
  }
  toast.error("Failed to update todo");
},
```

---

### 🟡 BUG-16 (Infrastructure) — `depends_on` does not wait for service readiness

**Location:** `docker-compose.yml`

**Reason:** `depends_on: - postgres` only waits for the container to start, not for PostgreSQL to be ready to accept connections. On fast machines (where the image is cached), the backend starts before postgres finishes initializing and crashes with a connection error.

**Fix:** Add `healthcheck` + `condition: service_healthy`:

```yaml
postgres:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U fabbi -d postgres"]
    interval: 5s
    retries: 5

backend:
  depends_on:
    postgres:
      condition: service_healthy
```

---

## Optional Feature: Tags + Filtering + Bulk Actions

Fully implemented. New files:

| File | Description |
|------|-------------|
| `backend/app/models/tag.py` | Tag model with case-insensitive unique constraint per user |
| `backend/app/models/todo_tag.py` | M2M join table |
| `backend/app/schemas/tag.py` | TagCreate / TagUpdate / TagResponse schemas |
| `backend/app/services/tag_service.py` | CRUD + attach/detach operations |
| `backend/app/api/v1/tags.py` | Full tags router |
| `backend/alembic/versions/b1c2d3e4f5a6_...py` | Migration: tags, todo_tags, unique + perf indexes |

Updated files:
- `todo_service.py`: filtering (`keyword`, `status`, `tag_id`, `date_from`, `date_to`), ordering (`created_at DESC, id DESC`), `bulk_update_status` in a single UPDATE statement
- `todos.py`: filter query params, `PATCH /bulk-status` endpoint, tags in response
- `todo schemas`: `TagInTodo` embedded in `TodoResponse`, `BulkStatusUpdate`
- `main.py`: tags router registered

Cache key includes all filter params for correct isolation.

---

## Test Coverage

New test file: `backend/tests/test_security_fixes.py`

| Test | What it proves |
|------|---------------|
| `test_expired_token_is_rejected` | BUG-01: expired tokens return 401 |
| `test_refresh_token_rejected_as_access_token` | BUG-02: refresh token can't access protected endpoints |
| `test_users_cannot_see_each_others_todos` | BUG-03: cache isolation by user |
| `test_user_cannot_read_another_users_todo` | BUG-04: 403 on GET |
| `test_user_cannot_update_another_users_todo` | BUG-04: 403 on PUT |
| `test_user_cannot_delete_another_users_todo` | BUG-04: 403 on DELETE |
| `test_update_completed_false_works` | BUG-05: falsy completed=False is saved |
| `test_login_wrong_password_returns_401_not_404` | BUG-07: no email enumeration |
| `test_login_unknown_email_returns_401_not_404` | BUG-07: consistent 401 |
| `test_duplicate_email_registration_rejected` | BUG-08: unique email enforced |
| `test_refresh_with_nonexistent_user_fails` | BUG-10: phantom user refresh rejected |

### Running tests

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

---

## Setup & Verification

```bash
git clone <your-fork-url>
cd test
cp .env.example .env

docker-compose up --build
# Wait for all services healthy

docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.db.seed
```

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs

---

## Known Limitations

- BUG-09 (logout blacklist) is implemented but the test uses a mocked Redis — full integration test requires a real Redis instance.
- Frontend optional features (filter bar, tag UI, bulk select) were not implemented in this PR to keep scope manageable; all backend endpoints are fully functional and testable via Swagger.
