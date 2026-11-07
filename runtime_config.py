"""Strict environment parsing for the optional container runtime."""

from dataclasses import dataclass
import math
import os


DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 10.0
MIN_UPSTREAM_TIMEOUT = 0.1
MAX_UPSTREAM_TIMEOUT = 120.0
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass(frozen=True)
class RuntimeConfig:
    port: int
    connect_timeout: float
    read_timeout: float
    log_level: str
    max_concurrent_extractions: int

    @property
    def request_timeout(self):
        return self.connect_timeout, self.read_timeout


def _parse_port(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise RuntimeError("PORT must be an integer from 1 to 65535")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("PORT must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("PORT must be an integer from 1 to 65535")
    return port


def _parse_timeout(name, value, default):
    if value is None:
        return default
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"{name} must be a number from {MIN_UPSTREAM_TIMEOUT:g} to {MAX_UPSTREAM_TIMEOUT:g}"
        ) from exc
    if not math.isfinite(timeout) or not MIN_UPSTREAM_TIMEOUT <= timeout <= MAX_UPSTREAM_TIMEOUT:
        raise RuntimeError(f"{name} must be a number from {MIN_UPSTREAM_TIMEOUT:g} to {MAX_UPSTREAM_TIMEOUT:g}")
    return timeout


def _parse_concurrency(value):
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("EXTRACT_MAX_CONCURRENT must be 0 (unlimited) or 1") from exc
    if limit not in {0, 1}:
        raise RuntimeError("EXTRACT_MAX_CONCURRENT must be 0 (unlimited) or 1")
    return limit


def load_runtime_config(environ=None):
    """Read supported settings. Invalid explicit values fail instead of falling back."""
    values = os.environ if environ is None else environ
    level = values.get("EXTRACT_LOG_LEVEL", "INFO").upper()
    if level not in LOG_LEVELS:
        raise RuntimeError("EXTRACT_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    return RuntimeConfig(
        port=_parse_port(values.get("PORT", "5000")),
        connect_timeout=_parse_timeout(
            "EXTRACT_CONNECT_TIMEOUT", values.get("EXTRACT_CONNECT_TIMEOUT"), DEFAULT_CONNECT_TIMEOUT
        ),
        read_timeout=_parse_timeout(
            "EXTRACT_READ_TIMEOUT", values.get("EXTRACT_READ_TIMEOUT"), DEFAULT_READ_TIMEOUT
        ),
        log_level=level,
        max_concurrent_extractions=_parse_concurrency(values.get("EXTRACT_MAX_CONCURRENT", "0")),
    )
