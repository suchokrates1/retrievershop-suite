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

### Environment variables

`.env.example` lists all recognised settings:

| Key | Purpose |
| --- | --- |
| `API_TOKEN` | BaseLinker API token used to fetch new orders |
| `PAGE_ACCESS_TOKEN` | Messenger page token for sending notifications |
| `RECIPIENT_ID` | Messenger recipient ID that receives alerts |
| `STATUS_ID` | Order status ID to filter orders for printing |
| `PRINTER_NAME` | Name of the CUPS printer to use |
| `CUPS_SERVER` | Hostname of a remote CUPS server |
| `CUPS_PORT` | Port of the remote CUPS server |
| `POLL_INTERVAL` | Seconds between polling for orders |
| `QUIET_HOURS_START` | Start time for muting printing (`hh:mm` 24h) |
| `QUIET_HOURS_END` | End time for muting printing (`hh:mm` 24h) |
| `TIMEZONE` | IANA timezone used for quiet hour checks |
| `PRINTED_EXPIRY_DAYS` | Days to keep printed order IDs in the database |
| `LOG_LEVEL` | Logging level for the printing agent |
| `LOG_FILE` | Path to the agent log file |
| `DB_PATH` | Path to the SQLite database file |
| `SECRET_KEY` | Secret key for Flask sessions |
| `FLASK_DEBUG` | Set to `1` to enable Flask debug mode |
| `FLASK_ENV` | Flask configuration environment |
| `COMMISSION_ALLEGRO` | Commission percentage charged by Allegro |
| `ENABLE_WEEKLY_REPORTS` | Set to `1` to send weekly sales reports |
| `ENABLE_MONTHLY_REPORTS` | Set to `1` to send monthly sales reports |

`DB_PATH` is read only during application startup, so changing it requires
restarting the server.

### Single printing agent

Only one printing agent should run at a time. The application uses a lock
file (`agent.lock` next to the log file) to ensure additional processes skip
starting the agent. When multiple workers load the application, only the first
one obtains the lock and launches the background thread.

## Modifying settings via the web interface

After starting the application you can modify the values stored in your `.env` file without touching the filesystem. Log in to the web interface and open the **Ustawienia** tab from the navigation bar.
The form lists all variables defined in `.env.example` so new options appear automatically. When you click **Zapisz** the application rewrites `.env` in the same order as `.env.example` and calls `print_agent.reload_config()` so the running printing agent immediately uses the updated environment. Log-related options like `LOG_LEVEL` and `LOG_FILE` therefore take effect as soon as you save the form.
Variables that are only read when the application starts, such as `DB_PATH`, do
not appear on this page.

## Running Tests

Use the `run-tests.sh` helper script in the repository root. It installs the
required dependencies and executes `pytest` with the repository root on
`PYTHONPATH`:

```bash
./run-tests.sh
```

Additional arguments are passed directly to `pytest`, for example:

```bash
./run-tests.sh magazyn/tests/test_agent_thread.py
```

The project is developed and tested using **Python 3.9**.

## Running with Docker Compose

Start the stack using the `docker-compose.yml` file in the repository root:

```bash
docker compose up
```

The compose configuration mounts the environment files so updates made through
the application persist on the host:

- `./.env:/app/.env`
- `./.env.example:/app/.env.example:ro`

The compose configuration mounts the host's `/var/run/cups/cups.sock` so the
printing agent can communicate with the host CUPS server.

The application uses a SQLite database stored in `magazyn/database.db`. This
file is created automatically on first startup if it does not already exist.
When running the stack in Docker, this file is mounted inside the container as
`/app/database.db` and the `DB_PATH` variable in your `.env` file should point
to that location. The value is read only during startup so any changes require
restarting the application.

## Database migration

The project now uses SQLAlchemy for all database interactions. Existing
SQLite databases remain compatible with the new ORM models. When upgrading,
install the updated requirements and initialise the database once using the
new command:

```bash
pip install -r magazyn/requirements.txt
python -m magazyn.app init_db
```

The `init_db` argument runs the database initialisation and exits without
starting the server. No data is removed during this step. The application can then be started as
before using the same database file.

Running a newer version of the application on an older database file will
automatically add missing columns (for example the `barcode` column in the
`product_sizes` table) during startup. Any tables introduced in new versions
are created on each launch because `init_db()` now runs every time the
application starts.

## Importing invoices

The **Import faktury** page accepts Excel or PDF invoices. PDF files produced
by the Tip-Top accounting software are recognised automatically. The parser
handles values written with spaces as thousand separators and extracts product
barcodes from lines containing "Kod kreskowy". When a barcode is found, it is
used to match existing items during import.

After uploading a file the application shows a preview of the parsed rows.
You can adjust quantities or other fields and deselect unwanted entries
before confirming the import.

## Responsive tables

Product lists are displayed inside Bootstrap's `.table-responsive` wrapper.
This element sets `overflow-x: auto` so the table can be scrolled
horizontally when it grows wider than the screen. Size columns use a fixed
width of 100&nbsp;px (see `static/styles.css`) to keep the quantity buttons
visible without cutting off content.

## Frontend assets

The barcode scanner uses Quagga 0.12.1 bundled as `static/quagga.min.js` so the
page works even without internet access.

## License

This project is licensed under the terms of the [MIT License](LICENSE).

