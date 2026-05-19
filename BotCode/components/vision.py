"""
Kapu kód felismerő modul (OpenCV alapú).

A kapu 4 LED-et villogtat, amelyek egy 4-bites bináris számot reprezentálnak (0x0–0xF).
A kódsorozat:
  - Az első digit mindig F (1111 — mind a 4 LED világít), ez a szinkron jel.
  - Ezután 3 db érvényes digit következik 200ms-onként:
      - Nem lehet 0
      - Nem ismétlődhet közvetlenül
  - A 3 digit együtt alkotja a visszasugárzandó hex kódot (pl. „CA6").

Felismerési algoritmus:
  1. ROI (érdeklődési terület) kivágása a frameből.
  2. Grayscale + GaussianBlur + Binary threshold.
  3. A megvilágított LED-ek meghatározása:
     - Kontúr alapú mód (VISION_USE_CONTOURS=True): 4 legnagyobb folt keresése,
       pozíció alapján bal→jobb sorrendbe rendezve (MSB→LSB).
     - Szekció alapú mód (VISION_USE_CONTOURS=False): az ROI 4 egyenlő vízszintes
       részre osztva, átlagos fényerő dönt.
  4. A 4 bit → hex digit konvertálása.
  5. Állapotgép: WAIT_FOR_F → COLLECTING → CODE_READY.
"""

import asyncio
import logging
import time
from enum import Enum, auto
from typing import Optional

import cv2
import numpy as np

import settings

log = logging.getLogger("vision")


class _State(Enum):
    WAIT_FOR_F = auto()
    COLLECTING = auto()
    COOLDOWN   = auto()


class VisionProcessor:
    def __init__(self):
        self._state      = _State.WAIT_FOR_F
        self._digits: list[int] = []
        self._last_digit: Optional[int] = None
        self._last_change_ts: float = 0.0
        self._cooldown_until: float = 0.0
        self._stable_count: int = 0
        self._candidate: Optional[int] = None

    async def processing_loop(
        self,
        camera,
        gate_code_queue: asyncio.Queue,
        state,
    ) -> None:
        """Főhurok: folyamatosan olvas frameket és feltölti a gate_code_queue-t."""
        log.info("Vision feldolgozó elindult")
        while True:
            frame = camera.get_frame()
            if frame is not None:
                code = self._process_frame(frame)
                if code:
                    state.last_gate_code = code
                    log.info(f"Kapu kód felismerve: {code}")
                    try:
                        gate_code_queue.put_nowait(code)
                    except asyncio.QueueFull:
                        log.warning("Gate code queue teli, kód eldobva")
            await asyncio.sleep(1.0 / (settings.CAMERA_FPS * 1.5))  # kicsit gyorsabb mint FPS

    def _process_frame(self, frame: np.ndarray) -> Optional[str]:
        """Egy frame feldolgozása. Visszaad egy 3 karakteres hex kódot vagy None-t."""
        now = time.monotonic()

        # Cooldown fázisban ne csinálunk semmit
        if self._state == _State.COOLDOWN:
            if now >= self._cooldown_until:
                self._state = _State.WAIT_FOR_F
                self._digits.clear()
                self._last_digit = None
                log.debug("Cooldown lejárt, várakozás újra F-re")
            return None

        digit = self._extract_digit(frame)
        if digit is None:
            return None

        # Stabil-frame szűrő: VISION_STABLE_FRAMES egymást követő egyforma frame kell
        if digit == self._candidate:
            self._stable_count += 1
        else:
            self._candidate = digit
            self._stable_count = 1

        if self._stable_count < settings.VISION_STABLE_FRAMES:
            return None

        # Csak akkor fogadjuk el, ha a digit valóban változott
        if digit == self._last_digit:
            return None

        self._last_digit = digit
        self._last_change_ts = now
        log.debug(f"Digit detektálva: {digit:X}  állapot={self._state.name}")

        if self._state == _State.WAIT_FOR_F:
            if digit == 0xF:
                self._state = _State.COLLECTING
                self._digits.clear()
                log.debug("F szinkron jel, gyűjtés kezdése")

        elif self._state == _State.COLLECTING:
            if digit == 0xF:
                # Új F → újrakezdjük a gyűjtést
                self._digits.clear()
                log.debug("Új F: gyűjtés újraindítva")
            elif digit == 0x0:
                # Nulla tiltott
                log.debug("Nulla digit, figyelmen kívül hagyva")
            elif self._digits and self._digits[-1] == digit:
                # Közvetlen ismétlés tiltott
                log.debug(f"Ismétlődő digit ({digit:X}), figyelmen kívül hagyva")
            else:
                self._digits.append(digit)
                log.debug(f"Digit hozzáadva: {digit:X}  összesen={len(self._digits)}")
                if len(self._digits) == 3:
                    code = "".join(f"{d:X}" for d in self._digits)
                    self._state = _State.COOLDOWN
                    self._cooldown_until = now + settings.VISION_COOLDOWN_MS / 1000.0
                    return code

        return None

    def _extract_digit(self, frame: np.ndarray) -> Optional[int]:
        """Kivágja az ROI-t, binarizál, és visszaadja a 4-bites értéket (0–15) vagy None-t."""
        rx = settings.VISION_ROI_X
        ry = settings.VISION_ROI_Y
        rw = settings.VISION_ROI_W
        rh = settings.VISION_ROI_H

        # Bounds ellenőrzés — automatikus szűkítés ha a ROI kilóg a frame-ből
        h, w = frame.shape[:2]
        if rx >= w or ry >= h:
            log.warning(f"ROI origó ({rx},{ry}) kívül esik a {w}×{h} frame-en")
            return None
        if rx + rw > w or ry + rh > h:
            new_rw = min(rw, w - rx)
            new_rh = min(rh, h - ry)
            log.debug(f"ROI {rw}×{rh} → {new_rw}×{new_rh} (frame: {w}×{h})")
            rw, rh = new_rw, new_rh

        roi = frame[ry : ry + rh, rx : rx + rw]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (settings.VISION_BLUR_KERNEL, settings.VISION_BLUR_KERNEL), 0)
        _, binary = cv2.threshold(blurred, settings.VISION_LED_THRESHOLD, 255, cv2.THRESH_BINARY)

        if settings.VISION_USE_CONTOURS:
            return self._digit_from_contours(binary)
        else:
            return self._digit_from_sections(binary)

    def _digit_from_contours(self, binary: np.ndarray) -> Optional[int]:
        """Kontúr alapú LED felismerés: a 4 legnagyobb folt pozíció szerint rendezve."""
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # Szűrjük minimális terület szerint
        valid = [c for c in contours if cv2.contourArea(c) >= settings.VISION_MIN_LED_AREA]

        if len(valid) < 1:
            return None

        # Legfeljebb 4 legnagyobb kontúr, bal→jobb rendezve
        valid.sort(key=cv2.contourArea, reverse=True)
        top4 = valid[:4]
        top4.sort(key=lambda c: cv2.boundingRect(c)[0])  # x pozíció szerint

        # Meghatározzuk a 4 bit pozíciót a ROI szélességéből
        roi_w = binary.shape[1]
        section_w = roi_w / 4

        bits = [0, 0, 0, 0]
        for c in top4:
            cx = cv2.boundingRect(c)[0] + cv2.boundingRect(c)[2] // 2
            idx = min(int(cx / section_w), 3)
            bits[idx] = 1

        return (bits[0] << 3) | (bits[1] << 2) | (bits[2] << 1) | bits[3]

    def _digit_from_sections(self, binary: np.ndarray) -> int:
        """Szekció alapú LED felismerés: az ROI 4 egyenlő részre osztva."""
        h, w = binary.shape
        section_w = w // 4
        bits = []
        for i in range(4):
            section = binary[:, i * section_w : (i + 1) * section_w]
            mean = np.mean(section)
            bits.append(1 if mean > settings.VISION_LED_THRESHOLD / 2 else 0)
        return (bits[0] << 3) | (bits[1] << 2) | (bits[2] << 1) | bits[3]


# ── Önálló teszt ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Vision modul teszt videóval")
    parser.add_argument("--video", required=True, help="Tesztvideó fájl elérési útja")
    parser.add_argument("--show", action="store_true", help="Ablakban mutatja a feldolgozott képet")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"Nem sikerült megnyitni: {args.video}")
        sys.exit(1)

    processor = VisionProcessor()
    print("Feldolgozás... (q = kilépés)")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Videó vége")
            break

        code = processor._process_frame(frame)
        if code:
            print(f">>> Felismert kód: {code}")

        if args.show:
            # ROI vizualizáció
            cv2.rectangle(
                frame,
                (settings.VISION_ROI_X, settings.VISION_ROI_Y),
                (settings.VISION_ROI_X + settings.VISION_ROI_W, settings.VISION_ROI_Y + settings.VISION_ROI_H),
                (0, 255, 0), 2,
            )
            cv2.imshow("Vision Test", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()
