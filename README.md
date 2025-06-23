# RetrieverShop Suite

This repository contains the code for the RetrieverShop warehouse and printing utilities.

## Configuration

1. Copy `.env.example` to `.env` in the repository root:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` and provide your API credentials. The printing agents require values such as `API_TOKEN`, `PAGE_ACCESS_TOKEN` and `RECIPIENT_ID`.
3. Set the CUPS printing server address. For the provided infrastructure use:
   ```env
   CUPS_SERVER=192.168.1.107
   CUPS_PORT=631
   ```
   This points the agents at the CUPS server running at `192.168.1.107:631`.

## Running Tests

Install the dependencies and run the test suite using `pytest`:
```bash
pip install -r magazyn/requirements.txt -r printer/requirements.txt
PYTHONPATH=. pytest -q
```

## Running with Docker Compose

Start the stack using the `docker-compose.yml` file in the repository root:

```bash
docker compose up
```
