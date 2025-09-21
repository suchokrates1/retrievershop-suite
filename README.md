# RetrieverShop Suite

This repository contains the code for the RetrieverShop warehouse application and the built-in printing agent.

## Configuration

1. Copy `.env.example` to `.env` in the repository root:
   ```bash
   cp .env.example .env
   ```
2. On POSIX systems restrict the file permissions so the contents stay private:
   ```bash
   chmod 600 .env
   ```
3. Edit `.env` and provide your API credentials. The printing agents require values such as `API_TOKEN`, `PAGE_ACCESS_TOKEN` and `RECIPIENT_ID`.
4. Configure CUPS access. When mounting the host's CUPS socket you should leave
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
| `ALLEGRO_CLIENT_ID` | Client identifier for Allegro OAuth |
| `ALLEGRO_CLIENT_SECRET` | Secret key for Allegro OAuth |
| `ALLEGRO_REDIRECT_URI` | Redirect URI registered for the Allegro application |
| `ALLEGRO_ACCESS_TOKEN` | OAuth access token used for Allegro API requests |
| `ALLEGRO_REFRESH_TOKEN` | Token used to refresh the Allegro access token |
| `ALLEGRO_SELLER_ID` | Your Allegro seller ID to exclude own offers |
| `ALLEGRO_EXCLUDED_SELLERS` | Comma-separated seller IDs to ignore |
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

## Allegro integration

### Obtaining tokens

1. Register an application in [Allegro's Developer Console](https://developer.allegro.pl/) and note the client ID and secret.
2. Set `ALLEGRO_REDIRECT_URI` in `.env` to match the redirect URL configured for your application.
3. Visit `https://allegro.pl/auth/oauth/authorize?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=YOUR_REDIRECT_URI` in a browser and authorise access.
4. Exchange the returned `code` for tokens using the helper:
   ```bash
   python - <<'PY'
from magazyn.allegro_api import get_access_token
print(get_access_token("YOUR_CLIENT_ID", "YOUR_CLIENT_SECRET", "AUTH_CODE", "YOUR_REDIRECT_URI"))
PY
   ```
   Save the `access_token` and `refresh_token` values as `ALLEGRO_ACCESS_TOKEN`
   and `ALLEGRO_REFRESH_TOKEN` in your environment or `.env` file.

### Running synchronization

1. Start the application.
2. Navigate to the **Oferty Allegro** page at `/allegro/offers`.
3. Use the **Odśwież** button to launch offer synchronization.

### Price monitor

The `allegro_price_monitor` helper checks public listings on Allegro and
notifies when competitors offer lower prices.  Configure the following
variables in your `.env`:

- `ALLEGRO_ACCESS_TOKEN` – OAuth token obtained in the steps above.
- `ALLEGRO_SELLER_ID` – your Allegro seller ID so the monitor can skip your
  own offers.
- `ALLEGRO_EXCLUDED_SELLERS` – comma-separated seller IDs to ignore.

Run the monitor manually with:

```bash
python -m magazyn.allegro_price_monitor
```

To execute it on a schedule, add a cron entry such as:

```cron
0 * * * * cd /path/to/retrievershop-suite && /usr/bin/env python -m magazyn.allegro_price_monitor >> /var/log/allegro_price_monitor.log 2>&1
```

Alternatively create a systemd service and timer:

```ini
# /etc/systemd/system/allegro_price_monitor.service
[Unit]
Description=Allegro price monitor

[Service]
Type=oneshot
WorkingDirectory=/path/to/retrievershop-suite
ExecStart=/usr/bin/env python -m magazyn.allegro_price_monitor

# /etc/systemd/system/allegro_price_monitor.timer
[Unit]
Description=Run Allegro price monitor hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

Enable the timer with `sudo systemctl enable --now allegro_price_monitor.timer`.

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

The project is developed and tested using **Python 3.12**.

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

The container image now starts the application with Gunicorn using the
`magazyn.wsgi:app` entrypoint bound to `0.0.0.0:8000`. Traefik and any reverse
proxy configuration should therefore forward traffic to port `8000` inside the
container. If you run the image manually, you can use the same command:

```bash
docker run --env-file=.env retrievershop/magazyn \
  gunicorn magazyn.wsgi:app --bind 0.0.0.0:8000
```

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

