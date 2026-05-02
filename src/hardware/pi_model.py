"""
Raspberry Pi model detection helpers.

Reads /proc/device-tree/model once at import time — cheap, no dependencies.
Used by hardware drivers to pick correct defaults for the running Pi.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_model_str: str = ""


def _read_model() -> str:
    global _model_str
    if _model_str:
        return _model_str
    try:
        raw = Path("/proc/device-tree/model").read_bytes()
        _model_str = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    except Exception:
        _model_str = "Unknown"
    return _model_str


def pi_generation() -> int:
    """Return the Pi generation (3, 4, or 5). Returns 0 on non-Pi hardware."""
    model = _read_model().lower()
    for gen in (5, 4, 3):
        if f"raspberry pi {gen}" in model:
            return gen
    return 0


def is_low_memory() -> bool:
    """True on Pi 3 / 1 GB models where RAM is a constraint."""
    try:
        mem_kb = int(Path("/proc/meminfo").read_text().split()[1])
        return mem_kb < 1_572_864   # < 1.5 GB
    except Exception:
        return False


def default_gpio_chip() -> str:
    """
    Return the correct gpiochip device for the running Pi.
    Pi 5 uses /dev/gpiochip4 (RP1); all others use /dev/gpiochip0.
    """
    chip = "/dev/gpiochip4" if pi_generation() == 5 else "/dev/gpiochip0"
    log.debug("pi_model: detected Pi %d, default GPIO chip %s", pi_generation(), chip)
    return chip
