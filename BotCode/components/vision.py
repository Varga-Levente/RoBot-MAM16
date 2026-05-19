"""
Kapu kód felismerő modul (OpenCV alapú).

A kapu 4 LED-et villogtat 2×2-es elrendezésben (TL, TR, BL, BR).
Egy LED állapota = 1 bit; együtt 1 hex digitot kódolnak:

    TL = bit 3 (MSB)    TR = bit 2
    BL = bit 1          BR = bit 0 (LSB)

A kódsorozat:
  - Az első digit mindig F (1111 — mind a 4 LED világít), ez a szinkron jel.
  - Ezután 3 db érvényes digit következik 200ms-onként:
      - Nem lehet 0x0
      - Nem ismétlődhet közvetlenül
  - A 3 digit együtt alkotja a visszasugárzandó hex kódot (pl. „CA6").

Felismerési algoritmus:
  1. ROI (érdeklődési terület) kivágása a frameből.
  2. Grayscale + GaussianBlur + Binary threshold.
  3. A 4 LED állapotának meghatározása:
     - Grid módszer (VISION_USE_CONTOURS=False, alapértelmezett):
       ROI 4 negyedre osztva, átlagos fényerő > VISION_GRID_THRESHOLD → bit=1.
       Robusztusabb, tesztvideóhoz és éles kamerához egyaránt ajánlott.
     - Kontúr alapú mód (VISION_USE_CONTOURS=True):
       4 legnagyobb folt keresése, 2×2 rács szerint rendezve (TL/TR/BL/BR).
       Zajosabb, de pontosabban jelzi az egyes LED-ek helyzetét.
  4. A 4 bit → hex digit konvertálása.
  5. Állapotgép: WAIT_FOR_F → COLLECTING → COOLDOWN.
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
            return self._digit_from_grid(binary)

    def _digit_from_grid(self, binary: np.ndarray) -> int:
        """4-negyed grid módszer: TL=bit3, TR=bit2, BL=bit1, BR=bit0.

        Az ROI-t 4 egyenlő negyedre osztja és minden negyed átlagos fényerejét méri.
        Robusztusabb a kontúr módszernél: nem igényel pontosan 4 detektált foltot.
        """
        h, w = binary.shape
        half_h, half_w = h // 2, w // 2
        quadrants = [
            binary[:half_h, :half_w],   # TL = bit 3 (MSB)
            binary[:half_h, half_w:],   # TR = bit 2
            binary[half_h:, :half_w],   # BL = bit 1
            binary[half_h:, half_w:],   # BR = bit 0 (LSB)
        ]
        bits = [1 if np.mean(q) > settings.VISION_GRID_THRESHOLD else 0 for q in quadrants]
        return (bits[0] << 3) | (bits[1] << 2) | (bits[2] << 1) | bits[3]

    def _digit_from_contours(self, binary: np.ndarray) -> int:
        """Kontúr alapú LED felismerés — 2×2 rács szerint rendezve (TL/TR/BL/BR).

        Ha kevés kontúrt talál, visszaesik a grid módszerre.
        """
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in contours if cv2.contourArea(c) >= settings.VISION_MIN_LED_AREA]

        if len(valid) < 2:
            return self._digit_from_grid(binary)

        # Legfeljebb 4 legnagyobb kontúr középpontja
        valid.sort(key=cv2.contourArea, reverse=True)
        centers = []
        for c in valid[:4]:
            x, y, cw, ch = cv2.boundingRect(c)
            centers.append((x + cw // 2, y + ch // 2))

        # Sor határ: y medián → felső vs alsó sor szétválasztás
        sorted_ys = sorted(cy for _, cy in centers)
        mid_y = sorted_ys[len(sorted_ys) // 2]
        top = sorted([(cx, cy) for cx, cy in centers if cy < mid_y],  key=lambda p: p[0])
        bot = sorted([(cx, cy) for cx, cy in centers if cy >= mid_y], key=lambda p: p[0])

        # Bit-térkép a ROI negyedei alapján
        h, w = binary.shape
        bits = [0, 0, 0, 0]
        for cx, cy in top + bot:
            col = 1 if cx >= w // 2 else 0
            row = 1 if cy >= h // 2 else 0
            idx = row * 2 + col  # TL=0, TR=1, BL=2, BR=3
            bits[idx] = 1
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
