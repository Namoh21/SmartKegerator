"""
Camera manager — continuous frame capture.

Tries two backends in order:

  1. OpenCV / V4L2  — works for USB webcams and Pi Camera on Bookworm
                      with the libcamera V4L2 compat layer.
  2. picamera2      — required for Pi Camera Module on Pi OS Trixie (and
                      any setup where the unicam device opens but read() fails).
                      Pre-installed on Pi OS; ignored silently if unavailable.

The manager runs a capture loop in a daemon thread and:
  • keeps the latest raw BGR frame in memory for facial recognition
  • emits Qt signals with each new frame for the UI and recognizer
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

try:
    from picamera2 import Picamera2
    _PICAM2_AVAILABLE = True
except Exception:
    _PICAM2_AVAILABLE = False


class Camera(QObject):
    """
    Captures frames continuously and exposes them via Qt signals.

    Signals:
        frame_ready(QPixmap)  — each frame as a QPixmap for UI display
        raw_frame_ready(obj)  — each frame as a BGR np.ndarray for the recognizer

    Properties:
        is_running   — True once the capture loop is active
        latest_frame — most recent BGR frame (thread-safe copy), or None
    """

    frame_ready     = pyqtSignal(QPixmap)
    raw_frame_ready = pyqtSignal(object)   # np.ndarray BGR

    def __init__(self, config: dict, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        hw = config.get("hardware", {})
        self._index     = hw.get("camera_index",    0)
        self._width     = hw.get("camera_width",  640)
        self._height    = hw.get("camera_height", 480)
        self._use_color = hw.get("camera_use_color", True)
        self._mirror    = hw.get("camera_mirror",   True)

        # Preview JPEG written periodically for the web UI
        import pathlib
        data_dir = pathlib.Path(config.get("data", {}).get("user_photos_dir", "/tmp"))
        self._preview_path = str(data_dir.parent / "camera_preview.jpg")
        self._frame_count  = 0

        self._cap:    Optional[cv2.VideoCapture] = None
        self._picam:  Optional[object]           = None   # Picamera2 instance
        self._lock    = threading.Lock()
        self._latest: Optional[np.ndarray] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Open the camera and begin capturing. Returns False if unavailable."""
        if self._try_opencv():
            return True
        if self._try_picamera2():
            return True
        log.error(
            "Camera: no working backend found (tried OpenCV index %d%s)",
            self._index, " and picamera2" if _PICAM2_AVAILABLE else "",
        )
        return False

    def stop(self) -> None:
        self._running = False
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._picam is not None:
            try:
                self._picam.stop()
            except Exception:
                pass
            self._picam = None
        log.info("Camera: stopped")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running and (self._cap is not None or self._picam is not None)

    @property
    def latest_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return None if self._latest is None else self._latest.copy()

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

    # ------------------------------------------------------------------
    # Backend: OpenCV / V4L2
    # ------------------------------------------------------------------

    def _try_opencv(self) -> bool:
        cap = cv2.VideoCapture(self._index, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap = cv2.VideoCapture(self._index)
        if not cap.isOpened():
            return False

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)

        # Read 3 consecutive frames to confirm the stream is stable.
        # A unicam (Pi Camera raw) device can open and return one buffered
        # frame but then fail on subsequent reads — 3 reads catches that.
        last_frame = None
        for attempt in range(3):
            ret, frame = cap.read()
            if not ret or frame is None:
                log.warning(
                    "Camera: OpenCV device %d failed on read %d — trying picamera2",
                    self._index, attempt + 1,
                )
                cap.release()
                return False
            last_frame = frame

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log.info("Camera: OpenCV backend, device %d at %dx%d", self._index, actual_w, actual_h)

        self._cap     = cap
        self._running = True
        # Store the last test frame immediately so latest_frame is never None
        # from the moment start() returns
        with self._lock:
            self._latest = last_frame

        self._thread = threading.Thread(target=self._opencv_loop, name="camera", daemon=True)
        self._thread.start()
        return True

    def _opencv_loop(self) -> None:
        while self._running and self._cap is not None:
            ret, frame = self._cap.read()
            if not ret:
                log.warning("Camera: failed to read frame — retrying")
                time.sleep(0.1)
                continue
            self._emit(frame)

    # ------------------------------------------------------------------
    # Backend: picamera2  (Pi Camera Module on Trixie / Bookworm)
    # ------------------------------------------------------------------

    def _try_picamera2(self) -> bool:
        if not _PICAM2_AVAILABLE:
            return False
        try:
            picam = Picamera2()
            # Use RGB888 explicitly so we always know what we're getting,
            # then convert to BGR for OpenCV consistency.  BGR888 is
            # ambiguous across Pi Camera generations and can deliver RGB
            # data on some sensors, causing red/blue to appear swapped.
            cfg   = picam.create_preview_configuration(
                main={"size": (self._width, self._height), "format": "RGB888"}
            )
            picam.configure(cfg)
            picam.start()
            time.sleep(0.5)   # let the sensor stabilise before first capture

            # Grab one frame immediately so latest_frame is never None
            # from the moment start() returns
            first_rgb = picam.capture_array("main")
            first     = cv2.cvtColor(first_rgb, cv2.COLOR_RGB2BGR)
            with self._lock:
                self._latest = first

            log.info("Camera: picamera2 backend at %dx%d", self._width, self._height)
            self._picam   = picam
            self._running = True
            self._thread  = threading.Thread(target=self._picam_loop, name="camera", daemon=True)
            self._thread.start()
            return True
        except Exception as exc:
            log.warning("Camera: picamera2 failed to start: %s", exc)
            return False

    def _picam_loop(self) -> None:
        while self._running and self._picam is not None:
            try:
                frame_rgb = self._picam.capture_array("main")
                if frame_rgb.ndim == 3 and frame_rgb.shape[2] == 3:
                    frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                    self._emit(frame)
                else:
                    time.sleep(0.05)
            except Exception as exc:
                log.warning("Camera: picamera2 read error: %s", exc)
                time.sleep(0.1)

    # ------------------------------------------------------------------
    # Shared frame handling
    # ------------------------------------------------------------------

    def _emit(self, frame: np.ndarray) -> None:
        if not self._use_color:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        if self._mirror:
            frame = cv2.flip(frame, 1)   # horizontal flip — mirror effect
        with self._lock:
            self._latest = frame
        self.frame_ready.emit(_bgr_to_pixmap(frame))
        self.raw_frame_ready.emit(frame)

        # Write preview JPEG every 15 frames (~2 fps) for the web UI
        self._frame_count += 1
        if self._frame_count % 15 == 0:
            cv2.imwrite(self._preview_path, frame)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bgr_to_pixmap(frame: np.ndarray) -> QPixmap:
    rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    img     = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(img)
