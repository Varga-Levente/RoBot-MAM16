"""
Kamera kezelő modul.

Két forrást támogat:
  - Jetson Nano CSI kamera (IMX219) — GStreamer nvarguscamerasrc pipeline
  - Videófájl (teszteléshez) — cv2.VideoCapture(path)

A legfrissebb frame egy „slot"-ban tárolódik (nem queue), így a fogyasztó
mindig a legaktuálisabb képet kapja, késedelem nélkül.
"""

import asyncio
import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

import settings

log = logging.getLogger("camera")


def _build_gstreamer_pipeline() -> str:
    return (
        f"nvarguscamerasrc sensor-id=0 ! "
        f"video/x-raw(memory:NVMM), "
        f"width={settings.CAMERA_WIDTH}, height={settings.CAMERA_HEIGHT}, "
        f"format=NV12, framerate={settings.CAMERA_FPS}/1 ! "
        f"nvvidconv ! "
        f"video/x-raw, "
        f"width={settings.CAMERA_WIDTH}, height={settings.CAMERA_HEIGHT}, format=BGRx ! "
        f"videoconvert ! "
        f"video/x-raw, format=BGR ! "
        f"appsink drop=1 max-buffers=1 sync=false"
    )


class CameraManager:
    """Kamera kezelő: folyamatosan olvas és egy slotban tárolja a legfrissebb frameet."""

    def __init__(self, test_video: str = ""):
        self._test_video = test_video or settings.CAMERA_TEST_VIDEO
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    async def start(self) -> None:
        if settings.DRY_RUN and not self._test_video:
            log.info("Dry-run mód: kamera szimulálva (fekete frame)")
            self._running = True
            self._thread = threading.Thread(target=self._dummy_loop, daemon=True)
            self._thread.start()
            return

        source: str | int
        if self._test_video:
            source = self._test_video
            log.info(f"Tesztvideó forrás: {source}")
        else:
            source = _build_gstreamer_pipeline()
            log.info("CSI kamera megnyitása GStreamer pipeline-nal")

        self._cap = cv2.VideoCapture(source, cv2.CAP_GSTREAMER if not self._test_video else cv2.CAP_ANY)

        if not self._cap.isOpened():
            # Fallback: próba cv2.CAP_ANY-vel (pl. USB kamera vagy videófájl)
            log.warning("GStreamer pipeline sikertelen, fallback cv2.CAP_ANY")
            self._cap = cv2.VideoCapture(source)

        if not self._cap.isOpened():
            log.warning(f"Nem sikerült megnyitni a kamera forrást, dummy mód: {source}")
            self._cap = None
            self._running = True
            self._thread = threading.Thread(target=self._dummy_loop, daemon=True)
            self._thread.start()
            return

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        log.info("Kamera elindítva")

    async def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
        log.info("Kamera leállítva")

    def get_frame(self) -> Optional[np.ndarray]:
        """Visszaadja a legfrissebb frameet (nem blokkol, None ha még nincs kép)."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    # ── belső metódusok ──────────────────────────────────────────────────────

    @staticmethod
    def _flip_frame(frame: np.ndarray) -> np.ndarray:
        """CAMERA_FLIP értéke alapján forgatja/tükrözi a képet (nvvidconv flip-method sorrend)."""
        f = settings.CAMERA_FLIP
        if f == 0:
            return frame
        if f == 1:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if f == 2:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if f == 3:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if f == 4:
            return cv2.flip(frame, 1)   # vízszintes tükrözés
        if f == 6:
            return cv2.flip(cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE), 1)
        log.warning(f"Ismeretlen CAMERA_FLIP érték: {f} — nincs forgatás")
        return frame

    def _capture_loop(self) -> None:
        consecutive_errors = 0
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                if self._test_video and settings.CAMERA_TEST_LOOP:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    consecutive_errors = 0
                    continue
                consecutive_errors += 1
                if consecutive_errors == 1:
                    log.error("Kamera frame olvasási hiba — kamera nincs bekötve?")
                elif consecutive_errors % 300 == 0:
                    log.warning(f"Kamera nem olvasható ({consecutive_errors} egymás utáni hiba)")
                time.sleep(0.1)
                continue
            consecutive_errors = 0
            frame = self._flip_frame(frame)
            with self._lock:
                self._frame = frame

    def _dummy_loop(self) -> None:
        blank = np.zeros((settings.CAMERA_HEIGHT, settings.CAMERA_WIDTH, 3), dtype=np.uint8)
        while self._running:
            with self._lock:
                self._frame = blank
            time.sleep(1.0 / settings.CAMERA_FPS)


# ── Önálló teszt ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Kamera teszt")
    parser.add_argument("--video", type=str, default="", help="Tesztvideó fájl elérési útja")
    args = parser.parse_args()

    async def _run():
        cam = CameraManager(test_video=args.video)
        await cam.start()
        print("Kamera fut. Nyomd meg a 'q' billentyűt a kilépéshez.")
        while True:
            frame = cam.get_frame()
            if frame is not None:
                cv2.imshow("Camera Test", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            await asyncio.sleep(1 / 30)
        await cam.stop()
        cv2.destroyAllWindows()

    asyncio.run(_run())
