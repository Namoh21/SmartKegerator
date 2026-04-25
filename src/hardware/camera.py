"""
Camera manager — continuous frame capture via OpenCV + V4L2.

On Raspberry Pi OS Bookworm, the Pi camera module is exposed through a V4L2
compatibility layer provided by libcamera, so standard OpenCV VideoCapture
works with no extra code. USB cameras also work the same way.

The manager runs a tight capture loop in a daemon thread and:
  • keeps the latest raw frame in memory for facial recognition
  • emits a Qt signal with each new frame for the UI to display
  • converts BGR frames to RGB before emitting (PyQt6 expects RGB)

Replaces the original MMAL-based raspicamcv wrapper (~30 C files) with
~80 lines of Python.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

log = logging.getLogger(__name__)


class Camera(QObject):
    """
    Captures frames continuously and exposes them via a Qt signal.

    Signals:
        frame_ready(QPixmap) — emitted for every captured frame; connect this
                               to a QLabel to display the live camera feed.

    Properties:
        latest_frame (np.ndarray | None) — most recent BGR frame, thread-safe;
                                           used by the face recogniser.
    """

    frame_ready      = pyqtSignal(QPixmap)    # for UI display
    raw_frame_ready  = pyqtSignal(object)     # np.ndarray BGR — for face recognizer

    def __init__(self, config: dict, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        hw = config.get("hardware", {})
        self._index       = hw.get("camera_index",  0)
        self._width       = hw.get("camera_width",  640)
        self._height      = hw.get("camera_height", 480)
        self._use_color   = hw.get("camera_use_color", True)

        self._cap:    Optional[cv2.VideoCapture] = None
        self._lock    = threading.Lock()
        self._latest: Optional[np.ndarray] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Open the camera and begin capturing. Returns False if unavailable."""
        self._cap = cv2.VideoCapture(self._index, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            # Fall back to auto backend (works on non-Pi systems)
            self._cap = cv2.VideoCapture(self._index)

        if not self._cap.isOpened():
            log.error("Camera: could not open device %d", self._index)
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)   # minimise latency

        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log.info("Camera: opened device %d at %dx%d", self._index, actual_w, actual_h)

        self._running = True
        self._thread  = threading.Thread(
            target=self._capture_loop, name="camera", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        log.info("Camera: stopped")

    # ------------------------------------------------------------------
    # Latest frame (thread-safe property for facial recognition)
    # ------------------------------------------------------------------

    @property
    def latest_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._latest if self._latest is None else self._latest.copy()

    # ------------------------------------------------------------------
    # Capture loop (background thread)
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        while self._running and self._cap is not None:
            ret, frame = self._cap.read()
            if not ret:
                log.warning("Camera: failed to read frame — retrying")
                time.sleep(0.1)
                continue

            if not self._use_color:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

            with self._lock:
                self._latest = frame

            self.frame_ready.emit(_bgr_to_pixmap(frame))
            self.raw_frame_ready.emit(frame)

    # ------------------------------------------------------------------
    # Snapshot helper
    # ------------------------------------------------------------------

    def capture_photo(self, path: str) -> bool:
        """Save the current frame to disk. Returns True on success."""
        frame = self.latest_frame
        if frame is None:
            log.warning("Camera: no frame available for snapshot")
            return False
        ok = cv2.imwrite(path, frame)
        if ok:
            log.info("Camera: saved snapshot to %s", path)
        else:
            log.error("Camera: failed to write snapshot to %s", path)
        return ok


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bgr_to_pixmap(frame: np.ndarray) -> QPixmap:
    """Convert an OpenCV BGR frame to a QPixmap for display in PyQt6."""
    rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    img   = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(img)
