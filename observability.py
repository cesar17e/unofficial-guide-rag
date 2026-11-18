"""Small JSONL logging helper for RAG request records.

This module does not instrument the application by itself. Callers create one
request record after a question finishes (or fails) and append it to the shared
log file. Importing the module does not create the file.
"""

from __future__ import annotations

import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "logs" / "rag_runs.jsonl"
SESSION_ID = str(uuid4())
VALID_STATUSES = frozenset({"success", "refused", "error"})

SCHEMA_FIELDS = (
    "timestamp",
    "session_id",
    "request_id",
    "question",
    "answer",
    "status",
    "retrieval_ms",
    "generation_ms",
    "duration_ms",
    "prompt_tokens",
    "output_tokens",
    "cache_hit",
    "error",
)


class _JsonFormatter(logging.Formatter):
    """Serialize the structured payload as exactly one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record.json_record, ensure_ascii=False, allow_nan=False)


class _RaisingFileHandler(logging.FileHandler):
    """Propagate JSONL write failures to the caller instead of suppressing them."""

    def handleError(self, record: logging.LogRecord) -> None:
        _, error, traceback = sys.exc_info()
        if error is None:
            raise RuntimeError("JSONL logging failed without an active exception")
        raise error.with_traceback(traceback)


def new_request_id() -> str:
    """Return a fresh request identifier."""
    return str(uuid4())


def safe_error(exc: BaseException, message: str = "Request failed.") -> dict[str, str]:
    """Return a log-safe error without copying the raw exception message.

    Exception strings can contain URLs, credentials, request bodies, or other
    sensitive details. The caller may provide a short public message, while the
    exception contributes only its class name.
    """
    if not isinstance(exc, BaseException):
        raise TypeError("exc must be an exception instance")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty safe string")
    return {"type": type(exc).__name__, "message": message.strip()}


class JsonlRequestLogger:
    """Append request records with a stable per-process session ID."""

    def __init__(
        self,
        log_path: str | Path = DEFAULT_LOG_PATH,
        session_id: str | None = None,
    ) -> None:
        self.log_path = Path(log_path)
        self.session_id = session_id or SESSION_ID
        UUID(self.session_id)

        self._logger = logging.getLogger(f"rag_jsonl.{uuid4()}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._handler: logging.FileHandler | None = None

    def _ensure_handler(self) -> None:
        if self._handler is not None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = _RaisingFileHandler(
            self.log_path,
            mode="a",
            encoding="utf-8",
            delay=True,
        )
        handler.setFormatter(_JsonFormatter())
        self._logger.addHandler(handler)
        self._handler = handler

    def log_request(
        self,
        *,
        question: str,
        answer: str | None,
        status: str,
        request_id: str | None = None,
        retrieval_ms: float | int | None = None,
        generation_ms: float | int | None = None,
        duration_ms: float | int | None = None,
        prompt_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_hit: bool | None = None,
        error: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Validate and append one request record, then return that record."""
        if not isinstance(question, str):
            raise TypeError("question must be a string")
        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
        if status == "error" and error is None:
            raise ValueError("error records require a safe error value")
        if status != "error" and error is not None:
            raise ValueError("only error records may include an error value")
        if status != "error" and not isinstance(answer, str):
            raise TypeError("successful and refused records require an answer string")
        if cache_hit is not None and not isinstance(cache_hit, bool):
            raise TypeError("cache_hit must be true, false, or null")

        for name, value in (
            ("retrieval_ms", retrieval_ms),
            ("generation_ms", generation_ms),
            ("duration_ms", duration_ms),
        ):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value < 0
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be a non-negative number or null")

        for name, value in (
            ("prompt_tokens", prompt_tokens),
            ("output_tokens", output_tokens),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or null")

        if error is not None:
            if set(error) != {"type", "message"}:
                raise ValueError("error must contain only type and message")
            if not all(isinstance(value, str) and value.strip() for value in error.values()):
                raise ValueError("error type and message must be non-empty strings")

        actual_request_id = request_id or new_request_id()
        UUID(actual_request_id)
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "session_id": self.session_id,
            "request_id": actual_request_id,
            "question": question,
            "answer": answer,
            "status": status,
            "retrieval_ms": retrieval_ms,
            "generation_ms": generation_ms,
            "duration_ms": duration_ms,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "cache_hit": cache_hit,
            "error": error,
        }

        self._ensure_handler()
        self._logger.info("request", extra={"json_record": record})
        return record

    def close(self) -> None:
        """Flush and close this helper's file handler."""
        if self._handler is None:
            return
        self._handler.flush()
        self._handler.close()
        self._logger.removeHandler(self._handler)
        self._handler = None


_default_logger = JsonlRequestLogger(session_id=SESSION_ID)


def log_request(**fields: Any) -> dict[str, Any]:
    """Append one request using the application's shared session ID."""
    return _default_logger.log_request(**fields)
