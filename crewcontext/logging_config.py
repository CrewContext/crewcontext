"""Structured logging for CrewContext.

Provides JSON-formatted logs for production observability.

Usage:
    from crewcontext.logging import setup_logging, get_logger
    
    # Setup at application start
    setup_logging(level="INFO", json_format=True)
    
    # Use in your code
    log = get_logger(__name__)
    log.info("Event emitted", extra={"event_id": "abc123", "agent_id": "agent-1"})
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging.

    Outputs log records as JSON with consistent field names
    for easy parsing by log aggregation systems.
    """

    def __init__(
        self,
        service_name: str = "crewcontext",
        include_caller: bool = True,
    ):
        super().__init__()
        self.service_name = service_name
        self.include_caller = include_caller

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
        }

        # Add optional fields
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            log_data["stack_info"] = self.formatStack(record.stack_info)

        # Add caller information
        if self.include_caller:
            log_data["caller"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }

        # Add custom fields from extra={}
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "threadName",
                "message",
                "asctime",
            ):
                try:
                    # Ensure value is JSON-serializable
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)

        return json.dumps(log_data)


class TextFormatter(logging.Formatter):
    """Human-readable text formatter for development.

    Similar to default logging but with consistent formatting.
    """

    def __init__(self, service_name: str = "crewcontext"):
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        # Add service name to record
        record.service = self.service_name
        return super().format(record)


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    service_name: str = "crewcontext",
    log_to_file: Optional[str] = None,
    include_caller: bool = True,
) -> None:
    """Configure logging for CrewContext.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_format: If True, output JSON; otherwise human-readable text.
        service_name: Service name to include in log records.
        log_to_file: Optional file path to write logs to.
        include_caller: Include file/line info in logs (adds overhead).

    Usage:
        setup_logging(level="INFO", json_format=True, service_name="my-service")
    """
    # Get or create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))

    # Set formatter based on format type
    if json_format:
        formatter = JSONFormatter(service_name, include_caller)
    else:
        formatter = TextFormatter(service_name)

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Add file handler if specified
    if log_to_file:
        file_handler = logging.FileHandler(log_to_file)
        file_handler.setLevel(getattr(logging, level.upper()))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Log setup complete
    log = logging.getLogger(__name__)
    log.info(
        "Logging configured",
        extra={
            "level": level,
            "json_format": json_format,
            "service_name": service_name,
            "log_to_file": log_to_file,
        },
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Configured logger instance.
    """
    return logging.getLogger(name)


# Convenience function for logging context
class LogContext:
    """Context manager for adding structured context to logs.

    Usage:
        with LogContext(event_id="abc123", agent_id="agent-1"):
            log.info("Processing event")
    """

    def __init__(self, **context: Any):
        self.context = context
        self.logger = logging.getLogger(__name__)

    def __enter__(self):
        # Store context for use in logs
        self.logger.info("Entering context", extra=self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.logger.error(
                "Context exited with error",
                extra={
                    **self.context,
                    "error_type": exc_type.__name__,
                    "error_message": str(exc_val),
                },
            )
        else:
            self.logger.info("Context exited successfully", extra=self.context)
        return False  # Don't suppress exceptions
