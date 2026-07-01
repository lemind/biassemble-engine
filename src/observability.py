import logging
import time

import structlog

# ── Event name constants (used in structlog calls across the retrieval pipeline) ──
EVT_RETRIEVAL_STARTED = "retrieval_started"
EVT_QUERY_EMBEDDED    = "query_embedded"
EVT_VECTOR_SEARCH     = "vector_search"
EVT_RERANKED          = "reranked"
EVT_COMPLETED         = "completed"

# ── Field name constants (keep key names consistent across all log events) ────
KEY_REQUEST_ID = "request_id"
KEY_LATENCY_MS = "latency_ms"


class TimingContext:
    """Measures wall-clock elapsed time in milliseconds.

    Usage:
        with TimingContext() as t:
            do_work()
        log.info("done", latency_ms=t.elapsed_ms)
    """

    def __enter__(self) -> "TimingContext":
        self._start = time.monotonic()
        self.elapsed_ms: int = 0
        return self

    def __exit__(self, *_: object) -> None:
        self.elapsed_ms = int((time.monotonic() - self._start) * 1000)


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog for the application.

    DEBUG → ConsoleRenderer (human-readable, coloured).
    INFO and above → JSONRenderer (machine-readable for HuggingFace Spaces logs).
    Called once at app startup in lifespan().
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    renderer = (
        structlog.dev.ConsoleRenderer()
        if log_level.upper() == "DEBUG"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    logging.basicConfig(format="%(message)s", level=level)
