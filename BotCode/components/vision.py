"""
Kapu kód felismerő modul (OpenCV alapú).

A kapu 4 LED-et villogtat 2×2-es elrendezésben.
Bit-sorrend (versenyspecifikáció):
    TL = 1  (bit 0, LSB)    TR = 2  (bit 1)
    BL = 4  (bit 2)         BR = 8  (bit 3, MSB)

Kódsorozat:
  - Első digit: F (15 = 1111 = mind a 4 LED ON) → szinkron jel, reset
  - Majd 3 hex digit 200ms-onként (nem 0, nem ismétlés)
  - A 3 digit = visszasugárzandó kód (pl. "CA6")

Algoritmus:
  1. HoughCircles → kapu körének megkeresése → maszk a körön belülre
     (Ha nem talál kört, visszaesik fix ROI-ra.)
  2. Grayscale + medianBlur + threshold a körön belül
  3. Kontúrkeresés → csak négyzetes alakok (aspect ratio ~1:1, min terület)
  4. Minden négyzet középpontja a kör középpontjához képest → bit érték:
       y < center_y, x < center_x → TL → += 1
       y < center_y, x ≥ center_x → TR → += 2
       y ≥ center_y, x < center_x → BL → += 4
       y ≥ center_y, x ≥ center_x → BR → += 8
  5. Állapotgép: reset F-re, gyűjt 3 digitot → kód kész
"""

import asyncio
import logging
import time
from enum import Enum, auto
from typing import Optional, Tuple

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
        self._state          = _State.WAIT_FOR_F
        self._digits: list[int] = []
        self._last_digit: Optional[int] = None
        self._cooldown_until: float = 0.0
        self._stable_count:  int = 0
        self._candidate:     Optional[int] = None
        # Utolsó detektált kör pozíció (annotációhoz)
        self._last_circle:   Optional[tuple[int, int, int]] = None

    async def processing_loop(
        self,
        camera,
        gate_code_queue: asyncio.Queue,
        state,
    ) -> None:
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
            await asyncio.sleep(1.0 / (settings.CAMERA_FPS * 1.5))

    # ── Fő feldolgozás ────────────────────────────────────────────────────────

    def _process_frame(self, frame: np.ndarray) -> Optional[str]:
        """Egy frame feldolgozása. None vagy 3 karakteres hex kód."""
        now = time.monotonic()

        if self._state == _State.COOLDOWN:
            if now >= self._cooldown_until:
                self._state = _State.WAIT_FOR_F
                self._digits.clear()
                self._last_digit = None
            return None

        digit = self._extract_digit(frame)
        if digit is None:
            return None

        # 2-frame debounce (referencia kódból)
        if digit == self._candidate:
            self._stable_count += 1
        else:
            self._candidate = digit
            self._stable_count = 1

        if self._stable_count < settings.VISION_STABLE_FRAMES:
            return None

        if digit == self._last_digit:
            return None

        self._last_digit = digit
        log.debug(f"Digit: {digit:X}  állapot={self._state.name}")

        if digit == 0xF:
            self._state = _State.COLLECTING
            self._digits.clear()
            self._last_digit = None
            log.debug("F szinkron → gyűjtés kezdése")
            return None

        if self._state == _State.COLLECTING:
            if digit == 0x0:
                return None
            self._digits.append(digit)
            log.debug(f"Digit hozzáadva: {digit:X}  összesen={len(self._digits)}")
            if len(self._digits) == 3:
                code = "".join(f"{d:X}" for d in self._digits)
                self._state = _State.COOLDOWN
                self._cooldown_until = now + settings.VISION_COOLDOWN_MS / 1000.0
                return code

        return None

    # ── Digit kinyerése egy frame-ből ────────────────────────────────────────

    def _extract_digit(self, frame: np.ndarray) -> Optional[int]:
        """Megkeresi a kapu kört, maszkolja, és visszaadja a 4-bit kódot."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.medianBlur(gray, 5)

        cx, cy, mask = self._find_circle_mask(frame, blurred)

        # Körön belüli kép kinyerése
        masked = cv2.bitwise_and(frame, frame, mask=mask)
        masked_gray = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(masked_gray, settings.VISION_LED_THRESHOLD,
                                  255, cv2.THRESH_BINARY)

        return self._read_squares(binary, cx, cy)

    def _find_circle_mask(
        self, frame: np.ndarray, blurred: np.ndarray
    ) -> Tuple[int, int, np.ndarray]:
        """HoughCircles alapú körkeresés. Visszaad (cx, cy, mask) tuple-t."""
        h, w = frame.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        cx, cy = w // 2, h // 2  # alapértelmezett: képközép

        if settings.VISION_USE_HOUGH:
            circles = cv2.HoughCircles(
                blurred, cv2.HOUGH_GRADIENT, 1,
                blurred.shape[0] / 8,
                param1=settings.VISION_HOUGH_PARAM1,
                param2=settings.VISION_HOUGH_PARAM2,
                minRadius=settings.VISION_HOUGH_MIN_RADIUS,
                maxRadius=settings.VISION_HOUGH_MAX_RADIUS,
            )
            if circles is not None:
                circles = np.uint16(np.around(circles))
                cx, cy, r = circles[0, 0]
                self._last_circle = (int(cx), int(cy), int(r))
                cv2.circle(mask, (int(cx), int(cy)), int(r), 255, -1)
                return int(cx), int(cy), mask

        # Fallback: fix ROI téglalap mint maszk
        rx = settings.VISION_ROI_X
        ry = settings.VISION_ROI_Y
        rw = min(settings.VISION_ROI_W, w - rx)
        rh = min(settings.VISION_ROI_H, h - ry)
        mask[ry:ry + rh, rx:rx + rw] = 255
        cx = rx + rw // 2
        cy = ry + rh // 2
        self._last_circle = None
        return cx, cy, mask

    def _read_squares(
        self, binary: np.ndarray, cx: int, cy: int
    ) -> Optional[int]:
        """Négyzetes kontúrokat keres, bit értéket számít a kör középponthoz képest."""
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        code = 0
        for c in contours:
            area = cv2.contourArea(c)
            if area < settings.VISION_MIN_SQUARE_AREA:
                continue

            epsilon = 0.02 * cv2.arcLength(c, True)
            approx  = cv2.approxPolyDP(c, epsilon, True)
            if len(approx) != 4:
                continue

            x, y, bw, bh = cv2.boundingRect(approx)
            ar = bw / float(bh)
            if not (0.95 <= ar <= 1.05):
                continue

            # Négyzet középpontja a kör középpontjához képest
            sqx = x + bw // 2
            sqy = y + bh // 2

            if sqy < cy:
                code += 1 if sqx < cx else 2   # TL=1, TR=2
            else:
                code += 4 if sqx < cx else 8   # BL=4, BR=8

        return code if code > 0 else None

    # ── Annotált frame (test_gui.py-hoz) ─────────────────────────────────────

    def annotate(self, frame: np.ndarray, digit: Optional[int]) -> np.ndarray:
        """Visszaad egy annotált másolatot (kör, négyzetek, bit értékek)."""
        out  = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.medianBlur(gray, 5)

        cx, cy, mask = self._find_circle_mask(frame, blurred)

        # Kör rajzolása
        if self._last_circle:
            lcx, lcy, lr = self._last_circle
            cv2.circle(out, (lcx, lcy), lr, (0, 200, 255), 2)
            cv2.circle(out, (lcx, lcy), 3,  (0, 200, 255), -1)
        else:
            rx = settings.VISION_ROI_X
            ry = settings.VISION_ROI_Y
            rw = min(settings.VISION_ROI_W, frame.shape[1] - rx)
            rh = min(settings.VISION_ROI_H, frame.shape[0] - ry)
            cv2.rectangle(out, (rx, ry), (rx + rw, ry + rh), (0, 200, 255), 2)

        # Négyzet kontúrok + bit értékek
        masked      = cv2.bitwise_and(frame, frame, mask=mask)
        masked_gray = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)
        _, binary   = cv2.threshold(masked_gray, settings.VISION_LED_THRESHOLD,
                                    255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            if cv2.contourArea(c) < settings.VISION_MIN_SQUARE_AREA:
                continue
            epsilon = 0.02 * cv2.arcLength(c, True)
            approx  = cv2.approxPolyDP(c, epsilon, True)
            if len(approx) != 4:
                continue
            x, y, bw, bh = cv2.boundingRect(approx)
            if not (0.95 <= bw / float(bh) <= 1.05):
                continue
            sqx, sqy = x + bw // 2, y + bh // 2
            if sqy < cy:
                bit_lbl = "TL:1" if sqx < cx else "TR:2"
            else:
                bit_lbl = "BL:4" if sqx < cx else "BR:8"
            cv2.drawContours(out, [approx], -1, (0, 255, 0), 2)
            cv2.putText(out, bit_lbl, (x, y - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (56, 189, 248), 1)

        # Állapot szöveg
        state_lbl = self._state.name
        cv2.putText(out, state_lbl, (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
        if digit is not None:
            cv2.putText(out, f"{digit:X}", (8, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (56, 189, 248), 2)
        return out


# ── Önálló teszt ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="Vision modul teszt videóval")
    parser.add_argument("--video", required=True)
    parser.add_argument("--show", action="store_true")
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
            annotated = processor.annotate(frame, processor._candidate)
            cv2.imshow("Vision Test", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    cap.release()
    cv2.destroyAllWindows()
