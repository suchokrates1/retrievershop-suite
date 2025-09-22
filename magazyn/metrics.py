"""Shared Prometheus metrics used across the application."""

from prometheus_client import Counter, Gauge, Histogram


PRINT_LABELS_TOTAL = Counter(
    "magazyn_print_labels_total",
    "Total number of labels successfully submitted to the printer.",
)
PRINT_LABEL_ERRORS_TOTAL = Counter(
    "magazyn_print_errors_total",
    "Total number of errors encountered by the print agent.",
    ["stage"],
)
PRINT_QUEUE_SIZE = Gauge(
    "magazyn_print_queue_size",
    "Current number of labels waiting in the queue.",
)
PRINT_QUEUE_OLDEST_AGE_SECONDS = Gauge(
    "magazyn_print_queue_oldest_age_seconds",
    "Age in seconds of the oldest queued label.",
)
PRINT_AGENT_ITERATION_SECONDS = Histogram(
    "magazyn_print_iteration_duration_seconds",
    "Duration of a single agent processing loop in seconds.",
)
PRINT_AGENT_RETRIES_TOTAL = Counter(
    "magazyn_print_retries_total",
    "Total number of retry attempts performed by the print agent.",
)
PRINT_AGENT_DOWNTIME_SECONDS = Counter(
    "magazyn_print_downtime_seconds",
    "Total duration in seconds spent waiting before retries.",
)

ALLEGRO_API_ERRORS_TOTAL = Counter(
    "magazyn_allegro_api_errors_total",
    "Total number of Allegro API errors grouped by endpoint and status code.",
    ["endpoint", "status"],
)
ALLEGRO_API_RETRIES_TOTAL = Counter(
    "magazyn_allegro_api_retries_total",
    "Total number of retry attempts performed for Allegro API requests.",
    ["endpoint"],
)
ALLEGRO_API_RATE_LIMIT_SLEEP_SECONDS = Counter(
    "magazyn_allegro_api_rate_limit_sleep_seconds",
    "Total duration spent sleeping due to Allegro API rate limits.",
    ["endpoint"],
)
ALLEGRO_SYNC_ERRORS_TOTAL = Counter(
    "magazyn_allegro_sync_errors_total",
    "Total number of unrecoverable Allegro synchronisation errors.",
    ["reason"],
)
ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL = Counter(
    "magazyn_allegro_token_refresh_attempts_total",
    "Total number of automatic Allegro token refresh attempts grouped by result.",
    ["result"],
)
ALLEGRO_TOKEN_REFRESH_RETRIES_TOTAL = Counter(
    "magazyn_allegro_token_refresh_retries_total",
    "Total number of retry attempts performed after refresh failures.",
)
ALLEGRO_TOKEN_REFRESH_LAST_SUCCESS = Gauge(
    "magazyn_allegro_token_refresh_last_success_timestamp",
    "Unix timestamp of the last successful automatic Allegro token refresh.",
)

PRINT_QUEUE_SIZE.set(0)
PRINT_QUEUE_OLDEST_AGE_SECONDS.set(0)
PRINT_LABEL_ERRORS_TOTAL.labels(stage="print")
PRINT_LABEL_ERRORS_TOTAL.labels(stage="queue")
PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop")
PRINT_AGENT_RETRIES_TOTAL.inc(0)
PRINT_AGENT_DOWNTIME_SECONDS.inc(0)
ALLEGRO_API_ERRORS_TOTAL.labels(endpoint="offers", status="0").inc(0)
ALLEGRO_API_ERRORS_TOTAL.labels(endpoint="listing", status="0").inc(0)
ALLEGRO_API_RETRIES_TOTAL.labels(endpoint="offers").inc(0)
ALLEGRO_API_RETRIES_TOTAL.labels(endpoint="listing").inc(0)
ALLEGRO_API_RATE_LIMIT_SLEEP_SECONDS.labels(endpoint="offers").inc(0)
ALLEGRO_API_RATE_LIMIT_SLEEP_SECONDS.labels(endpoint="listing").inc(0)
ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="http").inc(0)
ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="token_refresh").inc(0)
ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="unexpected").inc(0)
ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="settings_store").inc(0)
ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="success").inc(0)
ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="error").inc(0)
ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="skipped").inc(0)
ALLEGRO_TOKEN_REFRESH_RETRIES_TOTAL.inc(0)
ALLEGRO_TOKEN_REFRESH_LAST_SUCCESS.set(0)

