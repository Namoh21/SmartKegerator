"""
Facial recognition pipeline using the face_recognition library (dlib ResNet).

Replaces the original OpenCV FisherFace + custom libfacerec approach with a
modern, pre-trained deep-learning model that requires no manual training session
— you just add photos, encode them, and matching is a vector distance comparison.

Accuracy: ~99.4% on the LFW benchmark at threshold 0.6 (vs ~87% for FisherFace).

Architecture
------------
• FaceRecognizer is a QObject that owns a background worker thread.
• The camera (or any caller) submits BGR frames via submit_frame(). Frames are
  dropped if the recognizer is still busy — the queue holds only one item so
  the recognizer always sees the freshest frame rather than a stale backlog.
• Recognition runs at camera speed up to a configurable cap (default: every
  frame the queue receives). On Pi 4 this is naturally rate-limited to ~1 fps
  by the dlib inference time, which is fine for a kegerator.
• Training (encoding new photos) runs in a separate one-shot thread so it never
  blocks recognition.

Signals
-------
  user_identified(user_id: int, confidence: float)
      Emitted when a face is matched.  confidence is 1 - distance (0‥1).
  face_detected(found: bool)
      Emitted every processed frame; True if any face was found (matched or not).
  training_complete(user_id: int, count: int)
      Emitted after train_user() finishes. count = number of encodings stored.
  training_failed(user_id: int, reason: str)
      Emitted if training found no usable faces in the user's photos.
"""

from __future__ import annotations

import logging
import threading
from queue import Empty, Queue
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

try:
    import face_recognition as _fr
    _FR_AVAILABLE = True
except ImportError:
    _FR_AVAILABLE = False
    log.warning(
        "face_recognition not available — recognition will be disabled (dev/non-Pi mode)"
    )


class FaceRecognizer(QObject):
    user_identified  = pyqtSignal(int, float)   # (user_id, confidence)
    face_detected    = pyqtSignal(bool)          # any face found in frame?
    training_complete = pyqtSignal(int, int)     # (user_id, num_encodings)
    training_failed   = pyqtSignal(int, str)     # (user_id, reason)

    def __init__(self, config: dict, db, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        rec = config.get("recognition", {})
        self._enabled    = rec.get("enabled", True) and _FR_AVAILABLE
        self._threshold  = rec.get("confidence_threshold", 0.55)
        self._model      = rec.get("detection_model", "hog")   # "hog" or "cnn"

        self._db = db

        # Parallel lists — index i links a user_id to its encoding
        self._known_encodings: list[np.ndarray] = []
        self._known_user_ids:  list[int]        = []
        self._enc_lock = threading.Lock()

        self._queue:   Queue[np.ndarray] = Queue(maxsize=1)
        self._running  = False
        self._thread:  Optional[threading.Thread] = None

        # Prevents concurrent training threads and pauses recognition inference
        # during training so both don't compete for the same ~400 MB of RAM.
        self._training_lock   = threading.Lock()
        self._training_active = False

        if self._enabled:
            self._load_encodings()

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not self._enabled or self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._recognition_loop, name="face-rec", daemon=True
        )
        self._thread.start()

        # Reload encodings every 60 s to pick up photos added via the web UI
        from PyQt6.QtCore import QTimer
        self._reload_timer = QTimer(self)
        self._reload_timer.setInterval(60_000)
        self._reload_timer.timeout.connect(self._load_encodings)
        self._reload_timer.start()

        log.info(
            "FaceRecognizer started — %d known face encoding(s), model=%s, threshold=%.2f",
            len(self._known_encodings), self._model, self._threshold,
        )

    def stop(self) -> None:
        self._running = False

    def submit_frame(self, bgr_frame: np.ndarray) -> None:
        """
        Offer a frame for recognition. Non-blocking — drops the frame silently
        if the recognizer thread is still processing the previous one.
        """
        if not self._enabled:
            return
        try:
            self._queue.put_nowait(bgr_frame)
        except Exception:
            pass   # queue full — drop frame

    def reload_encodings(self) -> None:
        """Re-read all face encodings from the database (call after training)."""
        self._load_encodings()

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train_user(self, user_id: int) -> None:
        """
        Encode all photos stored for *user_id* and persist them to the database.
        Runs asynchronously; emits training_complete or training_failed when done.
        """
        if not _FR_AVAILABLE:
            self.training_failed.emit(user_id, "face_recognition library not available")
            return

        # Guard: only one training thread at a time.  A second call while
        # training is in progress is silently dropped — the UI button is
        # disabled during training so this is only a safety net.
        with self._training_lock:
            if self._training_active:
                log.warning("train_user: training already in progress — ignoring duplicate call")
                return
            self._training_active = True

        # Write pending status to DB so the web server's cross-process guard
        # can see that the touchscreen is training and refuse to start its own run.
        try:
            self._db.set_setting(f"train_status_{user_id}", "pending")
        except Exception:
            pass

        threading.Thread(
            target=self._do_train, args=(user_id,), name=f"train-{user_id}", daemon=True
        ).start()

    def train_all_users(self) -> None:
        """Convenience: re-encode every user in the database."""
        users = self._db.get_all_users()
        for user in users:
            if user.id != -1 and user.image_paths:
                self.train_user(user.id)

    def _do_train(self, user_id: int) -> None:
        import gc
        # Pause the recognition inference loop while training so both don't
        # compete for the same ~400 MB of RAM on a Pi 3.
        self._training_active = True
        try:
            self._do_train_inner(user_id)
        except Exception as exc:
            log.error("Training user %d crashed: %s", user_id, exc, exc_info=True)
            self.training_failed.emit(user_id, f"unexpected error: {exc}")
            try:
                self._db.set_setting(f"train_status_{user_id}", f"error:{exc}")
            except Exception:
                pass
        finally:
            with self._training_lock:
                self._training_active = False
            try:
                self._db.set_setting(f"train_status_{user_id}", "")
            except Exception:
                pass
            gc.collect()

    def _do_train_inner(self, user_id: int) -> None:
        import gc

        user = self._db.get_user(user_id)
        if user is None:
            self.training_failed.emit(user_id, "user not found")
            return

        results: list[tuple[str, np.ndarray]] = []

        for img_path in user.image_paths:
            p = Path(img_path)
            if not p.exists():
                log.warning("Training: image not found: %s", img_path)
                continue
            img = None
            try:
                img       = _fr.load_image_file(str(p))
                locations = _fr.face_locations(img, model=self._model)
                if not locations:
                    log.warning("Training: no face found in %s", img_path)
                    continue
                # Use the largest detected face if there are multiple
                largest_loc = max(locations, key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]))
                encodings   = _fr.face_encodings(img, [largest_loc])
                if encodings:
                    results.append((img_path, encodings[0]))
                    log.debug("Training: encoded %s", img_path)
            except Exception as exc:
                log.warning("Training: failed to encode %s: %s", img_path, exc)
            finally:
                # Explicitly free the large image array after each photo so
                # peak RAM is one-photo-worth, not all photos at once.
                del img
                gc.collect()

        if not results:
            reason = f"no usable faces found in {len(user.image_paths)} photo(s)"
            log.warning("Training user %d (%s): %s", user_id, user.name, reason)
            self.training_failed.emit(user_id, reason)
            return

        self._db.save_face_encodings(user_id, results)
        self._load_encodings()

        log.info(
            "Training user %d (%s): stored %d encoding(s)", user_id, user.name, len(results)
        )
        self.training_complete.emit(user_id, len(results))

    # ------------------------------------------------------------------
    # Recognition loop (background thread)
    # ------------------------------------------------------------------

    def _recognition_loop(self) -> None:
        while self._running:
            try:
                frame = self._queue.get(timeout=0.5)
            except Empty:
                continue
            # Skip inference while training — both use dlib and ~400 MB RAM
            if self._training_active:
                continue
            try:
                self._process_frame(frame)
            except Exception as exc:
                log.error("Recognition loop error: %s", exc)

    def _process_frame(self, bgr_frame: np.ndarray) -> None:
        # Work at half resolution — 4× faster detection, negligible accuracy loss
        small    = cv2.resize(bgr_frame, (0, 0), fx=0.5, fy=0.5)
        rgb      = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        locations = _fr.face_locations(rgb, model=self._model)
        self.face_detected.emit(bool(locations))

        if not locations:
            return

        with self._enc_lock:
            known_enc  = list(self._known_encodings)
            known_ids  = list(self._known_user_ids)

        if not known_enc:
            return

        face_encodings = _fr.face_encodings(rgb, locations)

        for encoding in face_encodings:
            distances = _fr.face_distance(known_enc, encoding)
            best_idx  = int(np.argmin(distances))
            best_dist = float(distances[best_idx])

            if best_dist <= self._threshold:
                user_id    = known_ids[best_idx]
                confidence = round(1.0 - best_dist, 3)
                log.debug(
                    "Identified user %d with confidence %.3f (distance %.3f)",
                    user_id, confidence, best_dist,
                )
                self.user_identified.emit(user_id, confidence)

    # ------------------------------------------------------------------
    # Encoding cache
    # ------------------------------------------------------------------

    def _load_encodings(self) -> None:
        try:
            rows = self._db.get_all_face_encodings()
        except Exception as exc:
            log.error("Failed to load face encodings: %s", exc)
            return

        user_ids:  list[int]        = []
        encodings: list[np.ndarray] = []
        for user_id, enc in rows:
            user_ids.append(user_id)
            encodings.append(enc)

        with self._enc_lock:
            self._known_user_ids  = user_ids
            self._known_encodings = encodings

        log.info("Loaded %d face encoding(s) from database", len(encodings))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def is_trained(self) -> bool:
        return bool(self._known_encodings)

    @property
    def known_user_count(self) -> int:
        return len(set(self._known_user_ids))


# ---------------------------------------------------------------------------
# Standalone helper — callable from the web server (no Qt event loop needed)
# ---------------------------------------------------------------------------

def train_user_sync(db, config: dict, user_id: int) -> tuple[int, str]:
    """
    Encode all photos for *user_id* and persist them to the database.
    Returns (num_encodings, error_message).  error_message is "" on success.

    Safe to call from any thread or async context — does not require Qt.
    The live FaceRecognizer picks up the new encodings within 60 seconds
    via its periodic reload timer.

    Memory note: each dlib HOG encoding pass uses ~300-400 MB peak on Pi 3.
    Photos are processed one at a time with explicit GC between each so the
    peak footprint is one-photo-worth rather than all photos at once.
    """
    import gc

    if not _FR_AVAILABLE:
        return 0, "face_recognition library not available on this system"

    user = db.get_user(user_id)
    if not user:
        return 0, "user not found"

    model   = config.get("recognition", {}).get("detection_model", "hog")
    results: list[tuple[str, np.ndarray]] = []

    for img_path in user.image_paths:
        p = Path(img_path)
        if not p.exists():
            log.warning("train_user_sync: image not found: %s", img_path)
            continue
        img = None
        try:
            img       = _fr.load_image_file(str(p))
            locations = _fr.face_locations(img, model=model)
            if not locations:
                log.warning("train_user_sync: no face in %s", img_path)
                continue
            largest = max(locations, key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]))
            encs    = _fr.face_encodings(img, [largest])
            if encs:
                results.append((img_path, encs[0]))
                log.debug("train_user_sync: encoded %s", Path(img_path).name)
        except Exception as exc:
            log.warning("train_user_sync: failed to encode %s: %s", img_path, exc)
        finally:
            # Explicitly free the large image array before loading the next one
            del img
            gc.collect()

    if not results:
        return 0, f"no usable faces found in {len(user.image_paths)} photo(s)"

    db.save_face_encodings(user_id, results)
    log.info("train_user_sync: stored %d encoding(s) for user %d", len(results), user_id)
    return len(results), ""
