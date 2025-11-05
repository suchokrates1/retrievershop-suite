# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app

RUN python -m venv "$VIRTUAL_ENV"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlite3-dev \
    cups-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY magazyn/ /app/magazyn/
COPY alembic.ini /app/alembic.ini
COPY migrations/ /app/migrations/


FROM python:3.12-slim AS runtime

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    cups-client \
    curl \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder $VIRTUAL_ENV $VIRTUAL_ENV
COPY --from=builder /app /app

RUN groupadd --system magazyn && \
    useradd --system --gid magazyn --home /app magazyn && \
    chown -R magazyn:magazyn /app "$VIRTUAL_ENV"

USER magazyn

EXPOSE 8000

CMD ["gunicorn", "magazyn.wsgi:app", "--bind", "0.0.0.0:8000"]
