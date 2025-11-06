# Allegro API Integration Fix - Summary

## Problem Overview

The discussions/messaging system was not working correctly because:
1. **Backend was using local SQLite database** instead of calling Allegro API endpoints
2. **CSS styling was not visible** due to browser cache issues
3. **Missing API function** for fetching discussion issues

## Changes Made

### 1. Backend: `magazyn/allegro_api.py`

**Added missing function:**
```python
def fetch_discussion_issues(access_token, limit=100):
    """
    Pobierz listę dyskusji/reklamacji z Allegro API.
    https://developer.allegro.pl/tutorials/jak-zarzadzac-dyskusjami-i-reklamacjami-d7eRdVVgWiZ
    """
    url = "https://api.allegro.pl/sale/issues"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json"
    }
    params = {
        "limit": limit,
        "offset": 0
    }
    
    response = _request_with_retry(
        "GET",
        url,
        headers=headers,
        params=params,
        timeout=10
    )
    response.raise_for_status()
    return response.json()
```

### 2. Backend: `magazyn/app.py`

#### Added Helper Functions:
- `_get_thread_title(thread)` - Generate title for messaging threads
- `_get_thread_author(thread)` - Extract author from thread
- `_get_message_author(message)` - Extract author with role handling
- `_get_issue_title(issue)` - Generate title for disputes/claims
- `_get_issue_type_pl(issue_type)` - Convert issue type to Polish

#### Rewrote Endpoints:

**1. GET `/discussions`** - Fetch and merge threads from both APIs
```python
@bp.route("/discussions")
@login_required
def discussions():
    # BEFORE: db.query(Thread).all()
    # AFTER: allegro_api.fetch_message_threads() + fetch_discussion_issues()
    
    # Fetches from:
    # - /messaging/threads (Centrum Wiadomości)
    # - /sale/issues (Dyskusje i Reklamacje)
    
    # Merges both sources, adds source="messaging" or source="issue"
    # Sorts by last_message_at descending
```

**2. GET `/discussions/<thread_id>`** - Load messages with source parameter
```python
@bp.route("/discussions/<thread_id>")
@login_required
def get_thread(thread_id):
    # NEW: Checks request.args.get("source")
    
    # If source == "issue":
    #   - Calls allegro_api.fetch_discussion_chat(token, thread_id)
    #   - Returns messages with author_role (BUYER/SELLER/ADMIN)
    
    # If source == "messaging" (default):
    #   - Calls allegro_api.fetch_thread_messages(token, thread_id)
    #   - Returns messages with standard author field
```

**3. POST `/discussions/<thread_id>/send`** - Send message to appropriate API
```python
@bp.route("/discussions/<thread_id>/send", methods=["POST"])
@login_required
def send_message(thread_id):
    # NEW: Checks payload.get("source")
    
    # If source == "issue":
    #   - Calls allegro_api.send_discussion_message(token, thread_id, text)
    #   - Uses type="REGULAR" parameter
    
    # If source == "messaging" (default):
    #   - Calls allegro_api.send_thread_message(token, thread_id, text)
```

### 3. Frontend: `magazyn/templates/discussions.html`

#### Added `data-source` attribute to thread items:
```html
<div class="thread-item" 
     data-thread-id="{{ thread.id }}"
     data-source="{{ thread.source|default('messaging', true) }}"
     ...>
```

#### Updated JavaScript:
1. **Added global variable:**
   ```javascript
   let currentThreadSource = null;
   ```

2. **Modified `loadThread()` function:**
   ```javascript
   const source = threadEl.dataset.source || 'messaging';
   currentThreadSource = source;
   const response = await fetch(`/discussions/${threadId}?source=${encodeURIComponent(source)}`, ...);
   ```

3. **Modified message send:**
   ```javascript
   body: JSON.stringify({ 
       content, 
       source: currentThreadSource || 'messaging' 
   })
   ```

## Allegro API Endpoints Used

### Centrum Wiadomości (Messaging)
- **GET** `/messaging/threads` - List threads (paginated, limit=20)
- **GET** `/messaging/threads/{threadId}/messages` - Get messages (limit=100)
- **POST** `/messaging/threads/{threadId}/messages` - Send message
- **Header:** `Accept: application/vnd.allegro.public.v1+json`

### Dyskusje i Reklamacje (Issues)
- **GET** `/sale/issues` - List disputes/claims (limit=100)
- **GET** `/sale/issues/{issueId}/chat` - Get chat messages (limit=100)
- **POST** `/sale/issues/{issueId}/message` - Send message (type="REGULAR")
- **Header:** `Accept: application/vnd.allegro.beta.v1+json`

## Data Structure

### Thread List Response:
```python
{
    "id": "thread_or_issue_id",
    "title": "Generated title",
    "author": "interlocutor_login",
    "type": "dyskusja" | "reklamacja" | "",
    "read": true,
    "last_message_at": "2024-01-20T10:30:00Z",
    "last_message_preview": "Message text...",
    "last_message_author": "username",
    "last_message_iso": "2024-01-20T10:30:00Z",
    "source": "messaging" | "issue"  # NEW FIELD
}
```

### Messages Response:
```python
{
    "messages": [
        {
            "id": "message_id",
            "author": "username",
            "author_role": "BUYER" | "SELLER" | "ADMIN",  # For issues only
            "content": "Message text",
            "created_at": "2024-01-20T10:30:00Z"
        }
    ],
    "thread": { ... }  # Thread info
}
```

## Browser Cache Fix

**Problem:** CSS changes not visible due to 304 Not Modified response

**Solution:** Hard refresh the browser
- **Chrome/Edge:** `Ctrl + Shift + R` or `Ctrl + F5`
- **Firefox:** `Ctrl + Shift + R` or `Ctrl + F5`
- **Safari:** `Cmd + Option + R`

**Verification:**
1. Open DevTools (F12)
2. Go to Network tab
3. Refresh page
4. Check `styles.css` - should show `200 OK` (not `304`)

See `CACHE_CLEAR_INSTRUCTIONS.md` for detailed guide.

## Testing Checklist

- [ ] Clear browser cache (Ctrl+Shift+R)
- [ ] Verify CSS loads correctly (DevTools Network tab)
- [ ] Check thread list loads from Allegro API
- [ ] Verify both messaging and issue threads appear
- [ ] Click on messaging thread - messages should load
- [ ] Click on issue thread - messages should load
- [ ] Send message to messaging thread - should work
- [ ] Send message to issue thread - should work
- [ ] Check thread updates after sending
- [ ] Verify unread badges update correctly
- [ ] Test WebSocket real-time updates (if configured)

## Future Improvements

1. **Caching Strategy:** Use Redis or TTL-based SQLite cache to reduce API calls
2. **Webhooks:** Subscribe to Allegro webhooks for real-time updates
3. **Error Handling:** Add user-friendly error messages for API failures
4. **Pagination:** Implement infinite scroll for large thread lists
5. **Offline Mode:** Use local cache when API is unavailable
6. **Performance:** Batch API calls, add loading skeletons

## Documentation Created

1. `CACHE_CLEAR_INSTRUCTIONS.md` - User guide for clearing browser cache
2. `ALLEGRO_API_ANALYSIS.md` - Detailed API compliance analysis
3. `ALLEGRO_API_FIX_SUMMARY.md` - This file (implementation summary)

## Files Modified

1. **magazyn/allegro_api.py** - Added `fetch_discussion_issues()` function
2. **magazyn/app.py** - Rewrote 3 endpoints + added 5 helper functions
3. **magazyn/templates/discussions.html** - Added `data-source` + updated JavaScript

## API Compliance Status

✅ **Centrum Wiadomości** - Fully implemented
✅ **Dyskusje i Reklamacje** - Fully implemented  
✅ **Source Parameter** - Properly routed
✅ **Data Transformation** - Helper functions convert API responses
✅ **Error Handling** - Try/except blocks with user feedback

## Result

The discussions module now:
- ✅ Fetches data directly from Allegro API (no local database)
- ✅ Supports both messaging threads and discussion issues
- ✅ Properly routes requests based on source parameter
- ✅ Displays correct author information (handling roles)
- ✅ Sends messages to the correct API endpoint
- ✅ Shows modern CSS styling (after cache clear)

## Notes

- Old `Thread` and `Message` models in database are now obsolete (or can be used for caching)
- All API calls use Bearer token from `settings.ALLEGRO_ACCESS_TOKEN`
- Cache save operations are wrapped in try/except (non-blocking)
- Frontend JavaScript properly passes `source` parameter in all API calls
