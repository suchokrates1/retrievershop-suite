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

## Running Tests

Install the dependencies and run the test suite using `pytest`. Tests rely on
modules within this repository, so run them with `PYTHONPATH=.`:
```bash
pip install -r magazyn/requirements.txt
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
