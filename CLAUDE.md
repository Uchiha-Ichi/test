# CLAUDE.md — Agent Instructions for FabbiDevelopment/test Assessment

This file contains instructions for AI coding agents (Claude Code, Cursor, etc.)
working on the developer assessment task defined in README.md.

---

## Project Overview

Full-stack Todo app — FastAPI backend + React/TypeScript frontend.
Stack: Python, FastAPI, PostgreSQL, Redis, SQLAlchemy, Alembic, React, TanStack Query, Zod.

## Your Mission

Read README.md fully. Your job is to:
1. Find every intentional bug in this codebase (security, logic, DB, cache, frontend, infra).
2. Fix the most important ones with actual code changes.
3. Write or update tests for your fixes.
4. Implement the optional Tags + Filtering + Bulk Actions feature if time allows.

---

## How to Read the Codebase

Start with these files in order:

```
backend/app/core/security.py       ← JWT logic
backend/app/api/deps.py            ← auth middleware
backend/app/api/v1/auth.py         ← login/register/logout/refresh
backend/app/api/v1/todos.py        ← CRUD endpoints
backend/app/services/todo_service.py
backend/app/models/user.py
backend/app/models/todo.py
backend/alembic/versions/          ← all migrations
frontend/src/features/todos/api/todos.ts
frontend/src/features/auth/hooks/useAuth.ts
frontend/src/lib/queryClient.ts
frontend/src/lib/api.ts
docker-compose.yml
```

---

## Known Bug Categories (Hints — do not skip any area)

Investigate ALL of these. Each area has at least one real bug:

- **JWT**: Does `verify_token` actually enforce expiry? Does `get_current_user` check the token *type*?
- **Authorization**: Does every todo endpoint verify `todo.user_id == current_user.id`?
- **Cache**: Is the Redis cache key user-scoped? What happens when User A's data is cached under a global key?
- **Logout**: After logout, can the access token still be used? Is the JTI blacklisted?
- **Login**: Does the error response reveal whether the email exists?
- **Database**: Does `users.email` have a UNIQUE constraint? Are timestamps timezone-aware?
- **Update logic**: In `PUT /todos/{id}`, how is `completed=False` handled? Is `update_todo` called correctly?
- **N+1 query**: Is there a SELECT inside a loop in `list_todos`?
- **Refresh endpoint**: Does it verify the user still exists in DB?
- **Frontend keys**: Are React list items keyed by `todo.id` or by array index?
- **React Query cache**: Is it cleared on logout? Do query keys include all params?
- **Optimistic update rollback**: Is previous data restored on mutation error?
- **Docker**: Does `depends_on` wait for the service to be *healthy* or just *started*?

---

## Fix Requirements

For each bug you fix, write a test that:
- Proves the bug existed (would fail before the fix)
- Proves the fix works (passes after)

Minimum: **5 fixed bugs** including **≥2 backend** and **≥1 frontend**.
Priority: security > data isolation > correctness > performance > style.

---

## Optional Feature: Tags + Filtering + Bulk Actions

If implementing the optional extension (see README.md for full spec), follow this order:

### Backend
1. Create models: `Tag`, `TodoTag` (see schema in README.md).
2. Add migration: unique index on `tags(user_id, lower(name))`, indexes on foreign keys.
3. Create `tag_service.py` with CRUD + attach/detach operations.
4. Update `todo_service.py`: add `keyword`, `status`, `tag_id`, `date_from`, `date_to` filters; add `bulk_update_status`.
5. Create `api/v1/tags.py` router.
6. Update `api/v1/todos.py`: add filter query params, `PATCH /bulk-status` endpoint.
7. Register new router in `main.py`.
8. Update cache key to include all filter params.

### Frontend
9. Add filter bar component (keyword, status, tag, date range, clear button).
10. Add tag management UI (list, create, rename, delete).
11. Add bulk select + bulk action buttons to TodoList.
12. Update `useTodos` query key to include all filter params.
13. Call `queryClient.clear()` on logout.

---

## Running Tests

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

---

## Commit Convention

```
fix(security): enforce JWT expiry in verify_token
fix(authz): add ownership check on todo endpoints
fix(cache): scope Redis key by user_id
feat(tags): add Tag model, service, and API endpoints
feat(todos): add filtering and bulk-status endpoint
test(security): add tests for all auth bug fixes
```

---

## PR Description Template

When opening the PR, describe:

1. **Bug Report** — one section per bug with Location / Reason / Fix.
2. **Implementation Notes** — tradeoffs made, anything left out.
3. **Testing** — how to run tests, what each new test covers.
4. **AI Assistance Disclosure** — what tools were used and how.
