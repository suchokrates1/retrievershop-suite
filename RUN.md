# How to run the application

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

## 2. Run with Gunicorn

```bash
gunicorn --bind 0.0.0.0:8000 magazyn.wsgi:app
```

This will start the application on port 8000. You can change the port by modifying the `--bind` parameter.
