# 🤖 AI Agent Instructions for RetrieverShop Suite

**Target Audience:** AI coding assistants (GitHub Copilot, Claude, GPT, etc.)  
**Purpose:** Detailed development and deployment workflow documentation

---

## 📋 General Workflow

### When Making Code Changes

1. **Understand the context first** - read relevant code, check logs
2. **Make targeted changes** - modify only what's necessary
3. **Test locally if possible** - run tests or validate syntax
4. **Commit with clear message** - use conventional commit format
5. **Push to GitHub** - `git push origin main`
6. **Deploy to production** - SSH to server and pull changes

### Commit Message Format

```bash
<type>: <description>

# Types:
feat:     New feature
fix:      Bug fix
refactor: Code restructuring without behavior change
docs:     Documentation changes
test:     Test additions or modifications
chore:    Maintenance tasks
```

**Examples:**
```bash
git commit -m "fix: Handle InvalidOperation in _to_decimal() for invoice import"
git commit -m "feat: Add WebSocket support for real-time discussions"
git commit -m "refactor: Simplify message fetching logic in discussions"
```

---

## 🚀 Deployment Process

### Automatic Deployment (GitHub Actions) ⭐ RECOMMENDED

**After pushing to `main`, GitHub Actions automatically deploys!**

1. **Push changes:**
   ```bash
   git push origin main
   ```

2. **Monitor deployment:**
   - Go to GitHub → **Actions** tab
   - Watch workflow progress in real-time
   - Green checkmark = success ✅
   - Red X = failure (check logs) ❌

3. **Manual trigger (if needed):**
   - GitHub → **Actions** → **Deploy to Production**
   - Click **Run workflow** → Choose `main` → **Run workflow**

### Manual Deployment (SSH Fallback)

**Use if GitHub Actions is down or misconfigured:**

```bash
# SSH to production server
ssh magazyn@magazyn.retrievershop.pl

# Navigate to app directory
cd /app

# Pull latest changes
git pull origin main

# Restart Docker containers
docker-compose restart web

# Check logs for errors
docker-compose logs -f web --tail=50
```

### Quick Deployment (One-liner)

```bash
ssh magazyn@magazyn.retrievershop.pl "cd /app && git pull origin main && docker-compose restart web"
```

### Verification After Deployment

1. **Check application health:** https://magazyn.retrievershop.pl/healthz
2. **Monitor logs:** `docker-compose logs -f web --tail=100`
3. **Test affected features** in production UI
4. **Check for errors:** `docker-compose logs web | grep ERROR`

---

## 🗂️ Project Structure

```
retrievershop-suite/
├── magazyn/                    # Main application package
│   ├── __init__.py
│   ├── app.py                  # Flask routes and views
│   ├── models.py               # SQLAlchemy ORM models
│   ├── db.py                   # Database utilities
│   ├── allegro_api.py          # Allegro API client
│   ├── allegro.py              # Allegro OAuth and routes
│   ├── forms.py                # WTForms definitions
│   ├── factory.py              # Flask app factory
│   ├── wsgi.py                 # WSGI entry point
│   ├── print_agent.py          # Background printing agent
│   ├── domain/                 # Business logic layer
│   │   ├── products.py         # Product operations
│   │   ├── invoice_import.py   # Invoice parsing
│   │   ├── inventory.py        # Stock management
│   │   └── reports.py          # Sales reporting
│   ├── static/                 # CSS, JS, images
│   ├── templates/              # Jinja2 HTML templates
│   ├── tests/                  # pytest test suite
│   └── migrations/             # Database migration scripts
├── docker-compose.yml          # Docker orchestration
├── Dockerfile                  # Container image definition
├── requirements.txt            # Python dependencies
├── .env                        # Environment variables (not in git)
├── .env.example                # Example environment config
└── README.md                   # User documentation
```

---

## 🔧 Common Tasks

### Adding a New Feature

1. **Plan the change:**
   - Which files need modification?
   - Are new models/tables needed?
   - What are the edge cases?

2. **Implement:**
   ```bash
   # Create feature branch (optional)
   git checkout -b feature/new-feature
   
   # Make changes
   # ... edit files ...
   
   # Test locally if possible
   python -m pytest magazyn/tests/
   ```

3. **Commit and deploy:**
   ```bash
   git add <changed-files>
   git commit -m "feat: Add new feature description"
   git push origin main
   
   # Deploy to production
   ssh magazyn@magazyn.retrievershop.pl "cd /app && git pull && docker-compose restart web"
   ```

### Fixing a Bug

1. **Diagnose:**
   - Check production logs: `docker-compose logs web --tail=100`
   - Reproduce locally if possible
   - Identify root cause

2. **Fix:**
   ```python
   # Example: Add error handling
   try:
       result = risky_operation()
   except SpecificError as e:
       logger.error(f"Operation failed: {e}")
       return fallback_value
   ```

3. **Deploy immediately:**
   ```bash
   git add <fixed-files>
   git commit -m "fix: Handle SpecificError in risky_operation"
   git push origin main
   ssh magazyn@magazyn.retrievershop.pl "cd /app && git pull && docker-compose restart web"
   ```

### Database Changes

**⚠️ IMPORTANT:** Always backup database before migrations!

1. **Create migration script:**
   ```python
   # magazyn/migrations/add_new_column.py
   def upgrade(db_path: str):
       """Add new column to products table."""
       with sqlite3.connect(db_path) as conn:
           conn.execute("ALTER TABLE products ADD COLUMN new_field TEXT")
           conn.commit()
   ```

2. **Test locally:**
   ```bash
   cp database.db database.db.backup
   python -m magazyn.migrations.add_new_column
   ```

3. **Deploy with caution:**
   ```bash
   # On production server
   cd /app
   cp magazyn/database.db magazyn/database.db.backup
   git pull origin main
   docker-compose restart web
   ```

---

## 🐛 Known Issues & Solutions

### Issue: HTTP 422 from Allegro Messaging API

**Symptom:** All discussion threads fail to load with 422 error

**Cause:** Messaging API accepts max `limit=20`, code was sending `limit=100`

**Solution:**
```python
# magazyn/allegro_api.py
def fetch_thread_messages(access_token: str, thread_id: str, limit: int = 20):
    params = {"limit": min(limit, 20)}  # ✅ Enforce API limit
```

**Fixed in:** Commit `6e3b972`

### Issue: decimal.ConversionSyntax on Invoice Import

**Symptom:** Import fails with `[<class 'decimal.ConversionSyntax'>]` error

**Cause:** Invalid values in invoice (text instead of numbers) not handled

**Solution:**
```python
# magazyn/domain/products.py
def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as e:
        logging.warning(f"Cannot convert '{value}' to Decimal: {e}")
        return Decimal("0.00")  # ✅ Fallback instead of crash
```

**Fixed in:** Commit `59727ce`

### Issue: Database Locked Errors

**Symptom:** `sqlite3.OperationalError: database is locked`

**Cause:** Multiple processes trying to write simultaneously

**Solution:**
- Use WAL mode: `PRAGMA journal_mode=WAL;`
- Implement retry logic with exponential backoff
- Reduce concurrent write operations

### Issue: WebSocket Connection Drops

**Symptom:** Real-time messages stop working after some time

**Cause:** Long-polling timeout or network issues

**Solution:**
- Implement reconnection logic in frontend
- Add heartbeat/ping mechanism
- Check reverse proxy timeout settings

---

## 📚 API Integration Details

### Allegro API - Two Separate Systems

**1. Messaging API** (`application/vnd.allegro.public.v1+json`)
- **Endpoints:**
  - `GET /messaging/threads` - List all message threads
  - `GET /messaging/threads/{id}/messages` - Get messages (max limit=20)
  - `POST /messaging/threads/{id}/messages` - Send message
  - `POST /messaging/message-attachments` - Upload attachment

**2. Issues API** (`application/vnd.allegro.beta.v1+json`)
- **Endpoints:**
  - `GET /sale/issues` - List disputes/claims
  - `GET /sale/issues/{id}/chat` - Get discussion messages (max limit=100)
  - `POST /sale/issues/{id}/message` - Send message with type:"REGULAR"
  - `POST /sale/issues/attachments` - Upload attachment (max 2MB)

**⚠️ CRITICAL:** Never mix these two APIs! They use different:
- Response formats: `{"messages": [...]}` vs `{"chat": [...]}`
- Authentication headers
- Rate limits
- Attachment handling

---

## 🧪 Testing Guidelines

### Running Tests

```bash
# All tests
./run-tests.sh

# Specific test file
./run-tests.sh magazyn/tests/test_discussions.py

# Specific test function
./run-tests.sh magazyn/tests/test_discussions.py::test_message_parsing

# With coverage
./run-tests.sh --cov=magazyn --cov-report=html
```

### Writing Tests

```python
# magazyn/tests/test_feature.py
import pytest
from magazyn.factory import create_app

@pytest.fixture
def app():
    """Create test application."""
    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    return app

def test_feature(app):
    """Test that feature works correctly."""
    with app.test_client() as client:
        response = client.get("/endpoint")
        assert response.status_code == 200
        assert b"Expected content" in response.data
```

### Test Production Features

**Real-world tests against production:**
```python
# magazyn/tests/test_discussions_real.py
def test_discussions_layout_real():
    """Test discussions page layout on production."""
    driver = webdriver.Chrome()
    driver.get("https://magazyn.retrievershop.pl/discussions")
    
    # Inject CSS if base.html missing styles block
    driver.execute_script("""
        var style = document.createElement('style');
        style.textContent = arguments[0];
        document.head.appendChild(style);
    """, custom_css)
    
    driver.save_screenshot("discussions_real_screenshot.png")
```

---

## 📝 Code Style Guidelines

### Python

- **PEP 8** compliance
- **Type hints** for function signatures
- **Docstrings** for public functions
- **f-strings** for string formatting

```python
def fetch_messages(thread_id: str, limit: int = 20) -> List[Dict]:
    """
    Fetch messages for a specific thread.
    
    Args:
        thread_id: Unique thread identifier
        limit: Maximum messages to fetch (default: 20)
    
    Returns:
        List of message dictionaries
    
    Raises:
        HTTPError: If API request fails
    """
    # Implementation...
```

### HTML/Templates

- **Jinja2** template inheritance
- **Bootstrap 5** components
- **Responsive design** (mobile-first)

```html
{% extends "base.html" %}

{% block styles %}
<style>
    /* Component-specific styles */
</style>
{% endblock %}

{% block content %}
<div class="container">
    <!-- Content -->
</div>
{% endblock %}
```

### JavaScript

- **ES6+** syntax
- **Vanilla JS** preferred (avoid jQuery)
- **WebSocket** for real-time features

```javascript
const ws = new WebSocket('wss://magazyn.retrievershop.pl/ws/discussions');

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleMessage(data);
};
```

---

## 🔒 Security Best Practices

1. **Never commit secrets:**
   - `.env` is in `.gitignore`
   - Use environment variables
   - Tokens in database encrypted

2. **Input validation:**
   ```python
   from wtforms import validators
   
   class MyForm(FlaskForm):
       email = StringField('Email', validators=[
           validators.Email(),
           validators.DataRequired()
       ])
   ```

3. **SQL injection prevention:**
   - Use SQLAlchemy ORM (no raw SQL)
   - Parameterized queries only

4. **XSS protection:**
   - Jinja2 auto-escapes by default
   - Use `{{ variable }}` not `{{ variable|safe }}`

5. **CSRF protection:**
   - Flask-WTF handles this automatically
   - All forms include `{{ form.csrf_token }}`

---

## 🚨 Emergency Procedures

### Application Won't Start

```bash
# Check Docker status
docker ps -a

# View logs
docker-compose logs web --tail=100

# Restart everything
docker-compose down
docker-compose up -d

# Check database
sqlite3 magazyn/database.db ".schema"
```

### Database Corruption

```bash
# Stop application
docker-compose stop web

# Backup corrupted database
cp magazyn/database.db magazyn/database.db.corrupted

# Restore from backup
cp /backups/database.db.YYYY-MM-DD magazyn/database.db

# Restart
docker-compose start web
```

### Rollback Deployment

```bash
# On production server
cd /app

# Find last working commit
git log --oneline -10

# Rollback
git reset --hard <commit-hash>

# Restart
docker-compose restart web
```

---

## 📊 Monitoring & Logs

### Log Locations

- **Application logs:** `docker-compose logs web`
- **Gunicorn logs:** Inside container `/var/log/gunicorn/`
- **Nginx/Traefik logs:** Depends on setup

### Log Levels

```python
import logging

logger = logging.getLogger(__name__)

logger.debug("Detailed diagnostic information")
logger.info("General informational messages")
logger.warning("Warning messages for potentially harmful situations")
logger.error("Error messages for serious problems")
logger.critical("Critical messages for very serious errors")
```

### Useful Log Queries

```bash
# Find errors in last hour
docker-compose logs web --since 1h | grep ERROR

# Follow live logs
docker-compose logs -f web --tail=50

# Filter by endpoint
docker-compose logs web | grep "/discussions"

# Count 422 errors
docker-compose logs web | grep -c "HTTP 422"
```

---

## 🎯 Quick Reference Commands

```bash
# ===== GIT & DEPLOYMENT =====

# Push and auto-deploy (GitHub Actions)
git push origin main
# Then watch: https://github.com/suchokrates1/retrievershop-suite/actions

# Manual deployment (fallback)
ssh magazyn@magazyn.retrievershop.pl "cd /app && git pull && docker-compose restart web"

# ===== MONITORING =====

# View logs
docker-compose logs -f web --tail=100

# Run tests
./run-tests.sh

# Database backup
cp magazyn/database.db magazyn/database.db.backup

# Check app health
curl https://magazyn.retrievershop.pl/healthz

# Restart containers
docker-compose restart web

# Check container status
docker ps

# Enter container shell
docker-compose exec web bash

# Run Python in container
docker-compose exec web python -c "print('Hello')"
```

---

## 📞 Getting Help

**When stuck:**
1. Check this document first
2. Review recent commits: `git log --oneline -20`
3. Search codebase: `grep -r "search_term" magazyn/`
4. Check production logs
5. Review Allegro API docs: https://developer.allegro.pl/
6. Ask the user for clarification

**When providing updates:**
- Be clear about what was changed and why
- Show commit hash for reference
- Explain deployment steps needed
- Mention any risks or rollback procedures

---

## ✅ Pre-Deployment Checklist

Before pushing to production:

- [ ] Code changes tested locally
- [ ] No syntax errors or import issues
- [ ] Commit message is clear and descriptive
- [ ] Breaking changes documented
- [ ] Database migrations tested
- [ ] Secrets not in code
- [ ] User notified of deployment
- [ ] Rollback plan ready

---

**Last Updated:** 2025-11-07  
**Version:** 1.0  
**Maintainer:** AI Agent
