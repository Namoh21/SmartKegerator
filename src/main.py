"""
SmartKegerator — entry point.

Usage:
    python main.py [config.yaml]

Defaults to config.yaml in the same directory if no argument given.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml
from PyQt6.QtWidgets import QApplication


def _configure_logging(config: dict) -> None:
    from log_config import configure
    log_file = configure(config, "gui")
    logging.getLogger("main").info("Logging to %s", log_file)


def _load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    # Basic console logging until we load config and know the log path
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
    log = logging.getLogger("main")

    config_path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "config.yaml")

    if not Path(config_path).exists():
        log.error("Config file not found: %s", config_path)
        sys.exit(1)

    config = _load_config(config_path)
    _configure_logging(config)
    log = logging.getLogger("main")
    log.info("Loaded config: %s", config_path)

    app = QApplication(sys.argv)
    app.setApplicationName("SmartKegerator")

    from ui.app import App
    keg_app = App(config)

    # Clean shutdown when the Qt event loop exits
    app.aboutToQuit.connect(keg_app.shutdown)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
