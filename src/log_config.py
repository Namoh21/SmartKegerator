"""
Shared logging configuration for both the Qt touchscreen app and the
FastAPI web server.  Both processes call configure() at startup with
their process name ("gui" or "web") and write to separate rotating log
files under {install_dir}/logs/.

Log location is derived from config["data"]["database_path"]:
  /opt/smartkegerator/data/smartkegerator.db
      → /opt/smartkegerator/logs/smartkegerator-gui.log
      → /opt/smartkegerator/logs/smartkegerator-web.log

Each log file rotates at 5 MB and keeps 5 backups (max 25 MB each).

Log levels (stored as the string key in the DB under "log_level"):
  none     → CRITICAL  (only fatal errors)
  basic    → WARNING   (warnings + errors)
  high     → INFO      (normal operational messages — default)
  verbose  → DEBUG     (full debug trace, very noisy)
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

# Mapping from UI label to Python logging level
LEVELS: dict[str, int] = {
    "none":    logging.CRITICAL,
    "basic":   logging.WARNING,
    "high":    logging.INFO,
    "verbose": logging.DEBUG,
}

LEVEL_LABELS: dict[str, str] = {
    "none":    "None (fatal errors only)",
    "basic":   "Basic (warnings + errors)",
    "high":    "High (normal operation)",
    "verbose": "Verbose (full debug trace)",
}

_DEFAULT_LEVEL = "high"

# Third-party loggers kept quieter regardless of the chosen level
_NOISY = ("uvicorn.access", "httpx", "httpcore", "PIL", "picamera2")


def configure(config: dict, process: str = "app") -> Path:
    """
    Set up the root logger with a rotating file handler and a console
    handler.  Returns the Path of the log file being written.
    Safe to call multiple times — duplicate handlers are not added.
    """
    db_path  = Path(config.get("data", {}).get("database_path", "/tmp/sk.db"))
    log_dir  = db_path.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"smartkegerator-{process}.log"

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    # Avoid adding duplicate handlers on repeated calls (e.g. during tests)
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return log_file

    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    root.setLevel(logging.INFO)

    for noisy in _NOISY:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_file


def apply_level(level_key: str) -> None:
    """
    Apply a log level key (none/basic/high/verbose) to the root logger
    immediately.  Safe to call from any thread at any time.
    """
    level = LEVELS.get(level_key, logging.INFO)
    logging.getLogger().setLevel(level)
    # Keep third-party loggers at WARNING unless we're in verbose mode
    floor = logging.DEBUG if level_key == "verbose" else logging.WARNING
    for noisy in _NOISY:
        logging.getLogger(noisy).setLevel(max(level, floor))
    logging.getLogger(__name__).info(
        "Log level set to %s (%s)", level_key.upper(),
        logging.getLevelName(level)
    )


def log_dir_for(config: dict) -> Path:
    """Return the logs directory path without configuring logging."""
    db_path = Path(config.get("data", {}).get("database_path", "/tmp/sk.db"))
    return db_path.parent.parent / "logs"


def tail_log(log_file: Path, lines: int = 300) -> str:
    """Return the last *lines* lines of a log file as a single string."""
    if not log_file.exists():
        return "(log file not found — the service may not have written any entries yet)"
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:]) or "(log file is empty)"
    except OSError as exc:
        return f"(could not read log file: {exc})"
