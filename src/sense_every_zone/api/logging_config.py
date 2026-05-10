"""
Logging configuration for the sense_every_zone server.

Call ``configure()`` once at application startup.  All subsequent
``getLogger(__name__)`` calls across the package inherit the handlers
automatically.

Log directory resolution (in priority order)::

    1. ``log_dir`` argument to ``configure()``
    2. ``SEZ_LOG_DIR`` environment variable
    3. ``/var/log/sense_every_zone/``  (Pi production path)
    4. ``~/.sense_every_zone/logs/``   (dev / fallback)
    5. Current working directory       (last resort)

Log level resolution::

    1. ``level`` argument to ``configure()``
    2. ``SEZ_LOG_LEVEL`` environment variable  (e.g. ``DEBUG``)
    3. ``INFO`` (default)

Two handlers are attached to the *root* logger:

* **console** — stderr, always present (uvicorn reads stdout/stderr)
* **file**    — rotating ``sense_every_zone.log`` (10 MB × 5 files);
                silently skipped if the directory cannot be created

Additionally, ``GET /zones/*/status 200`` access-log lines are demoted
from INFO to DEBUG so the aggregator's 5-second poll does not bury other
log output.  Pass ``SEZ_LOG_LEVEL=DEBUG`` to restore them.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional, Union

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_configured = False
_resolved_dir: Optional[Path] = None


def configure(
    log_dir: Optional[Union[Path, str]] = None,
    level: Optional[Union[int, str]] = None,
) -> Path:
    """Configure application logging and return the resolved log directory.

    Idempotent — subsequent calls return the previously resolved directory
    without reconfiguring handlers.
    """
    global _configured, _resolved_dir
    if _configured:
        assert _resolved_dir is not None
        return _resolved_dir

    resolved_level = _resolve_level(level)
    resolved_dir = _resolve_log_dir(log_dir)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(resolved_level)

    has_console = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in root.handlers
    )
    if not has_console:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    try:
        resolved_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            resolved_dir / "sense_every_zone.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Cannot create log file in %s (%s) — logging to stderr only.",
            resolved_dir,
            exc,
        )

    logging.getLogger("uvicorn.access").addFilter(_StatusPollFilter())

    _configured = True
    _resolved_dir = resolved_dir
    logging.getLogger(__name__).info(
        "Logging configured: level=%s dir=%s",
        logging.getLevelName(resolved_level),
        resolved_dir,
    )
    return resolved_dir


def reset() -> None:
    """Reset the configuration guard — for use in tests only."""
    global _configured, _resolved_dir
    _configured = False
    _resolved_dir = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_level(level: Optional[Union[int, str]]) -> int:
    if level is not None:
        if isinstance(level, str):
            result = logging.getLevelName(level.upper())
            return result if isinstance(result, int) else logging.INFO
        return level
    env_val = os.environ.get("SEZ_LOG_LEVEL", "INFO").upper()
    result = logging.getLevelName(env_val)
    return result if isinstance(result, int) else logging.INFO


def _resolve_log_dir(override: Optional[Union[Path, str]]) -> Path:
    if override is not None:
        return Path(override)
    if env_dir := os.environ.get("SEZ_LOG_DIR"):
        return Path(env_dir)
    for candidate in (
        Path("/var/log/sense_every_zone"),
        Path.home() / ".sense_every_zone" / "logs",
    ):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path(".")


class _StatusPollFilter(logging.Filter):
    """Demote zone status poll access-log lines from INFO to DEBUG."""

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        msg = record.getMessage()
        if '"GET /zones/' in msg and "/status" in msg and '" 200 ' in msg:
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True
