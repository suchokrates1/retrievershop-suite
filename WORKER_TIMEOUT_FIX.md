# Worker Timeout & 422 Error Fix

## Problems Identified

### 1. WORKER TIMEOUT (CRITICAL)
**Symptom:** `[CRITICAL] WORKER TIMEOUT (pid:X)` repeating every ~60 seconds

**Root Cause:** 
- Alembic database migrations were running inside `create_app()` in `factory.py`
- Every Gunicorn worker tried to run migrations during startup
- SQLite database locks prevented concurrent migrations
- Workers timed out after 60 seconds waiting for database lock

**Impact:** Application couldn't start properly, constant worker restarts

### 2. HTTP 422 Error
**Symptom:** 
```
requests.exceptions.HTTPError: 422 Client Error: Unprocessable Entity 
for url: https://api.allegro.pl/messaging/threads/fsMhkBGCQIv3QNpRef27tl5wWI2THo4x6Zk6on3gTvW/messages
```

**Root Cause:**
- Thread ID `fsMhkBGCQIv3QNpRef27tl5wWI2THo4x6Zk6on3gTvW` is an **issue ID**, not a messaging thread ID
- Frontend defaulted to `source="messaging"` when parameter was missing
- Backend tried to fetch from wrong API endpoint (`/messaging/threads/` instead of `/sale/issues/`)

**Impact:** Users couldn't load discussion/claim threads, only messaging threads worked

## Solutions Implemented

### 1. Fix Worker Timeout - Move Migrations to Entrypoint

#### Created `magazyn/entrypoint.sh`:
```bash
#!/bin/sh
# Runs migrations ONCE before starting Gunicorn

set -e

echo "Running database migrations..."
cd /app
alembic upgrade head

echo "Starting Gunicorn..."
exec gunicorn magazyn.wsgi:app --bind 0.0.0.0:8000 --config magazyn/gunicorn.conf.py
```

#### Updated `magazyn/Dockerfile`:
```dockerfile
# Copy entrypoint script
COPY magazyn/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Use entrypoint instead of CMD
ENTRYPOINT ["/app/entrypoint.sh"]
```

#### Updated `magazyn/factory.py`:
- **Removed:** Alembic imports (`from alembic.config import Config`, `from alembic import command`)
- **Removed:** Migration execution from `create_app()`:
  ```python
  # REMOVED:
  alembic_ini_path = os.path.join(app.root_path, '..', 'alembic.ini')
  alembic_cfg = Config(alembic_ini_path)
  alembic_cfg.set_main_option('sqlalchemy.url', f"sqlite:///{settings.DB_PATH}")
  command.upgrade(alembic_cfg, "head")
  ```
- **Added:** Comment explaining the change

**Result:** 
- ✅ Migrations run once before any workers start
- ✅ No more database locks
- ✅ No more worker timeouts
- ✅ Fast application startup

### 2. Fix 422 Error - Auto-detect Thread Type

#### Updated `magazyn/app.py` - `/discussions/<thread_id>` endpoint:

**Added fallback logic:**
1. Try fetching with specified `source` parameter (messaging or issue)
2. If HTTP 422 error occurs:
   - If tried as "messaging" → retry as "issue"
   - If tried as "issue" → retry as "messaging"
3. Return the correct source type in response

**Implementation:**
```python
def try_fetch_messages(source_type):
    """Helper to fetch messages from the appropriate API."""
    if source_type == "issue":
        data = allegro_api.fetch_discussion_chat(token, thread_id)
        raw_messages = data.get("chat", [])
    else:
        data = allegro_api.fetch_thread_messages(token, thread_id)
        raw_messages = data.get("messages", [])
    # ... convert and return

try:
    messages, actual_source = try_fetch_messages(thread_source)
except HTTPError as exc:
    if status_code == 422 and thread_source == "messaging":
        # Retry as issue
        messages, actual_source = try_fetch_messages("issue")
    elif status_code == 422 and thread_source == "issue":
        # Retry as messaging
        messages, actual_source = try_fetch_messages("messaging")
```

**Result:**
- ✅ Automatic detection of thread type
- ✅ Works even when frontend doesn't pass correct source
- ✅ Graceful fallback between APIs
- ✅ Returns correct source type for future requests

### 3. Improved Gunicorn Configuration

#### Updated `magazyn/gunicorn.conf.py`:
```python
bind = "0.0.0.0:8000"
workers = 2  # Limit concurrent workers
worker_class = 'geventwebsocket.gunicorn.workers.GeventWebSocketWorker'  # For SocketIO
timeout = 120  # Increased from default 30s
keepalive = 5
graceful_timeout = 30
```

**Benefits:**
- ✅ Proper SocketIO support with GeventWebSocketWorker
- ✅ Longer timeout for slow API calls
- ✅ Controlled number of workers (prevents resource exhaustion)

## Testing & Verification

### Build and Run:
```bash
# Rebuild Docker image
docker-compose build

# Start container
docker-compose up -d

# Watch logs
docker-compose logs -f
```

### Expected Log Output (Good):
```
Running database migrations...
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
Starting Gunicorn...
[INFO] Starting gunicorn 21.2.0
[INFO] Listening at: http://0.0.0.0:8000 (1)
[INFO] Using worker: geventwebsocket.gunicorn.workers.GeventWebSocketWorker
[INFO] Booting worker with pid: 7
[INFO] Booting worker with pid: 8
```

### What to Check:
- ✅ Migrations run ONCE at startup (before "Starting Gunicorn")
- ✅ No "WORKER TIMEOUT" errors
- ✅ Workers boot successfully (pid: 7, 8, etc.)
- ✅ Application responds to requests
- ✅ Discussions page loads both messaging and issue threads
- ✅ Clicking threads loads messages without 422 errors

### API Testing:
```bash
# Test messaging thread (should work)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/discussions/MESSAGING_THREAD_ID?source=messaging"

# Test issue thread (should work)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/discussions/ISSUE_ID?source=issue"

# Test auto-detection (should work with retry)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/discussions/ISSUE_ID?source=messaging"
# Should log: "Thread ... returned 422 as messaging, trying as issue..."
```

## Files Modified

1. **magazyn/entrypoint.sh** (NEW) - Migration entrypoint script
2. **magazyn/Dockerfile** - Use entrypoint, copy script, set execute permission
3. **magazyn/factory.py** - Removed Alembic migration from create_app()
4. **magazyn/app.py** - Added auto-detection logic with 422 fallback
5. **magazyn/gunicorn.conf.py** - Improved configuration (workers, timeout, SocketIO support)

## Architecture Improvements

### Before:
```
Docker Start → Gunicorn → Worker 1 → create_app() → Run migrations (blocks)
                        → Worker 2 → create_app() → Run migrations (waits for lock, TIMEOUT)
                        → Worker 3 → create_app() → Run migrations (waits for lock, TIMEOUT)
```

### After:
```
Docker Start → entrypoint.sh → Run migrations ONCE
                             → Gunicorn → Worker 1 → create_app() (fast)
                                       → Worker 2 → create_app() (fast)
```

## Best Practices Applied

1. ✅ **Database migrations run before application starts** (not during)
2. ✅ **Single migration run** (not per-worker)
3. ✅ **Graceful error handling** with retry logic
4. ✅ **Auto-detection** of thread types
5. ✅ **Proper worker configuration** for SocketIO
6. ✅ **Clear logging** for debugging

## Related Issues Fixed

- Worker timeout crashes
- Database lock contention
- 422 errors when loading discussions
- Slow application startup
- SocketIO connection issues

## Future Considerations

1. **Migration rollback strategy** - Add ability to rollback failed migrations
2. **Health checks** - Add `/health` endpoint to verify app readiness
3. **Monitoring** - Track migration execution time
4. **Database backups** - Backup before running migrations
5. **Zero-downtime deployments** - Use migration strategies compatible with rolling updates
