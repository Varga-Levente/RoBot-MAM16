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
from typing import List, Optional, Tuple

import cv2
import numpy as np

import settings

log = logging.getLogger("vision")

# CUDA elérhetőség ellenőrzése induláskor
_CUDA_OK = cv2.cuda.getCudaEnabledDeviceCount() > 0
if _CUDA_OK:
    log.info("CUDA elérhető — GPU-gyorsított vision feldolgozás aktív")
else:
    log.info("CUDA nem elérhető — CPU feldolgozás")


class _State(Enum):
    WAIT_FOR_F = auto()
    COLLECTING = auto()
    COOLDOWN   = auto()


class VisionProcessor:
    def __init__(self):
        self._state          = _State.WAIT_FOR_F
        self._digits: List[int] = []
        self._last_digit: Optional[int] = None
        self._cooldown_until: float = 0.0
        self._stable_count:  int = 0
        self._candidate:     Optional[int] = None
        self._last_circle:   Optional[Tuple[int, int, int]] = None
        self._last_annotated: Optional[np.ndarray] = None

        # CUDA ellenőrzés — Maxwell (SM 5.3) csak cvtColor + threshold-t támogat
        # megbízhatóan; median filter és bitwise_and+mask GPU-n nem fut ezen a HW-en
        self._cuda_ok = _CUDA_OK
        if self._cuda_ok:
            try:
                # Teszteljük hogy a cvtColor valóban működik-e
                _test = cv2.cuda_GpuMat()
                _test.upload(cv2.cuda_GpuMat(1, 1, cv2.CV_8UC3).download() * 0 +
                             cv2.cuda_GpuMat(1, 1, cv2.CV_8UC3).download())
                log.info("CUDA vision aktív (cvtColor + threshold GPU-n)")
            except Exception as e:
                log.warning(f"CUDA inicializálás sikertelen, CPU módra visszaesés: {e}")
                self._cuda_ok = False

    def reset(self) -> None:
        self._state          = _State.WAIT_FOR_F
        self._digits.clear()
        self._last_digit     = None
        self._cooldown_until = 0.0
        self._stable_count   = 0
        self._candidate      = None
        self._last_circle    = None
        self._last_annotated = None

    async def processing_loop(
        self,
        camera,
        gate_code_queue: asyncio.Queue,
        state,
    ) -> None:
        loop = asyncio.get_running_loop()
        log.info("Vision feldolgozó elindult")
        while True:
            frame = camera.get_frame()
            if frame is not None:
                # CPU-intenzív HoughCircles nem blokkolja az event loopot
                code = await loop.run_in_executor(None, self._process_frame, frame)
                state.vision_state = self._state.name
                state.last_digit   = self._candidate
                if state.debug_annotation:
                    self._last_annotated = await loop.run_in_executor(
                        None, self.annotate, frame, self._candidate
                    )
                else:
                    self._last_annotated = None
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

    # ── Digit kinyerése ───────────────────────────────────────────────────────

    def _extract_digit(self, frame: np.ndarray) -> Optional[int]:
        if self._cuda_ok:
            return self._extract_digit_cuda(frame)
        return self._extract_digit_cpu(frame)

    def _extract_digit_cuda(self, frame: np.ndarray) -> Optional[int]:
        """Hibrid GPU/CPU feldolgozás — Maxwell-kompatibilis műveletek GPU-n."""
        try:
            # BGR → Szürke GPU-n (megbízható Maxwell-on)
            gpu_frame = cv2.cuda_GpuMat()
            gpu_frame.upload(frame)
            gpu_gray = cv2.cuda.cvtColor(gpu_frame, cv2.COLOR_BGR2GRAY)
            gray = gpu_gray.download()

            # Medián blur + körkeresés + maszkolás CPU-n
            # (Maxwell SM 5.3-on ezek GPU-n instabilak bizonyos képméreteknél)
            blurred = cv2.medianBlur(gray, 5)
            cx, cy, mask = self._find_circle_mask_cpu(frame, blurred)
            masked_gray = cv2.bitwise_and(gray, gray, mask=mask)

            # Threshold GPU-n (megbízható, egyszerű elem-szintű művelet)
            gpu_mg = cv2.cuda_GpuMat()
            gpu_mg.upload(masked_gray)
            _, gpu_binary = cv2.cuda.threshold(
                gpu_mg, settings.VISION_LED_THRESHOLD, 255, cv2.THRESH_BINARY
            )
            binary = gpu_binary.download()

            return self._read_squares(binary, cx, cy)

        except Exception as e:
            log.warning(f"CUDA frame hiba (CPU fallback): {e}")
            return self._extract_digit_cpu(frame)

    def _extract_digit_cpu(self, frame: np.ndarray) -> Optional[int]:
        """CPU alapú feldolgozás (fallback)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.medianBlur(gray, 5)
        cx, cy, mask = self._find_circle_mask_cpu(frame, blurred)
        masked = cv2.bitwise_and(frame, frame, mask=mask)
        masked_gray = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(masked_gray, settings.VISION_LED_THRESHOLD,
                                  255, cv2.THRESH_BINARY)
        return self._read_squares(binary, cx, cy)

    # ── Körkeresés ────────────────────────────────────────────────────────────

    def _find_circle_mask_cpu(
        self, frame: np.ndarray, blurred: np.ndarray
    ) -> Tuple[int, int, np.ndarray]:
        h, w = frame.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        cx, cy = w // 2, h // 2

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

        return self._roi_fallback(frame, mask)

    def _roi_fallback(
        self, frame: np.ndarray, mask: np.ndarray
    ) -> Tuple[int, int, np.ndarray]:
        h, w = frame.shape[:2]
        rx = settings.VISION_ROI_X
        ry = settings.VISION_ROI_Y
        rw = min(settings.VISION_ROI_W, w - rx)
        rh = min(settings.VISION_ROI_H, h - ry)
        mask[ry:ry + rh, rx:rx + rw] = 255
        self._last_circle = None
        return rx + rw // 2, ry + rh // 2, mask

    # ── Négyzet olvasás (CPU) ─────────────────────────────────────────────────

    def _read_squares(
        self, binary: np.ndarray, cx: int, cy: int
    ) -> Optional[int]:
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
            if not (0.95 <= bw / float(bh) <= 1.05):
                continue
            sqx = x + bw // 2
            sqy = y + bh // 2
            if sqy < cy:
                code += 1 if sqx < cx else 2
            else:
                code += 4 if sqx < cx else 8
        return code if code > 0 else None

    def get_debug_frame(self) -> Optional[np.ndarray]:
        return self._last_annotated

    # ── Annotált frame ────────────────────────────────────────────────────────

    def annotate(self, frame: np.ndarray, digit: Optional[int]) -> np.ndarray:
        out  = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.medianBlur(gray, 5)

        cx, cy, mask = self._find_circle_mask_cpu(frame, blurred)

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

        state_lbl = self._state.name
        cv2.putText(out, state_lbl, (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
        if digit is not None:
            cv2.putText(out, f"{digit:X}", (8, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (56, 189, 248), 2)

        # CUDA állapot jelzése
        cuda_lbl = "GPU" if self._cuda_ok else "CPU"
        cv2.putText(out, cuda_lbl, (out.shape[1] - 40, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 0) if self._cuda_ok else (0, 165, 255), 1)
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
    print(f"CUDA: {'igen' if processor._cuda_ok else 'nem'}")
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

