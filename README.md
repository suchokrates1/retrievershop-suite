# RetrieverShop Suite

This repository contains the code for the RetrieverShop warehouse application and the built-in printing agent.

## Configuration

1. Copy `.env.example` to `.env` in the repository root:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` and provide your API credentials. The printing agents require values such as `API_TOKEN`, `PAGE_ACCESS_TOKEN` and `RECIPIENT_ID`.
3. Configure CUPS access. When mounting the host's CUPS socket you should leave
   the variables empty:
   ```env
   CUPS_SERVER=
   CUPS_PORT=
   ```
   If you prefer to connect to a remote CUPS server instead, set `CUPS_SERVER`
   and `CUPS_PORT` accordingly.

## Modifying settings via the web interface

After starting the application you can modify the values stored in your `.env` file without touching the filesystem. Log in to the web interface and open the **Ustawienia** tab from the navigation bar.
The form lists all variables defined in `.env.example` so new options appear automatically. When you click **Zapisz** the application rewrites `.env` in the same order as `.env.example` and calls `print_agent.reload_config()` so the running printing agent immediately uses the updated environment.

## Running Tests

Before running the tests you must install the required dependencies:

```bash
pip install -r magazyn/requirements.txt
```

Tests rely on modules within this repository, so execute `pytest` with the
repository root on `PYTHONPATH`:

```bash
PYTHONPATH=. pytest -q
```

## Running with Docker Compose

Start the stack using the `docker-compose.yml` file in the repository root:

```bash
docker compose up
```

The compose configuration mounts the host's `/var/run/cups/cups.sock` so the
printing agent can communicate with the host CUPS server.

The application uses a SQLite database stored in `magazyn/database.db`. This
file is created automatically on first startup if it does not already exist.
When running the stack in Docker, this file is mounted inside the container as
`/app/database.db` and the `DB_PATH` variable in your `.env` file should point
to that location.

## Database migration

The project now uses SQLAlchemy for all database interactions. Existing
SQLite databases remain compatible with the new ORM models. When upgrading,
install the updated requirements and run `init_db` once to create any missing
tables:

```bash
pip install -r magazyn/requirements.txt
python -m magazyn.app init_db
```

No data is removed during this step. The application can then be started as
before using the same database file.

Running a newer version of the application on an older database file will
automatically add missing columns (for example the `barcode` column in the
`product_sizes` table) during startup.

## License

This project is licensed under the terms of the [MIT License](LICENSE).

