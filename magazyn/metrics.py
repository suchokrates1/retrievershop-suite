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

PRINT_QUEUE_SIZE.set(0)
PRINT_QUEUE_OLDEST_AGE_SECONDS.set(0)
PRINT_LABEL_ERRORS_TOTAL.labels(stage="print")
PRINT_LABEL_ERRORS_TOTAL.labels(stage="queue")
PRINT_LABEL_ERRORS_TOTAL.labels(stage="loop")

