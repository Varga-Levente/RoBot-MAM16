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
        # Cache: _process_frame() feltölti, annotate() reuse-olja (nincs dupla HoughCircles)
        # _last_cx/cy: eredeti felbontás koordinátái (annotációhoz)
        # _last_binary/_last_mask: kisméretű (proc) frame tere (_read_squares-hoz)
        self._last_cx:     int = 0
        self._last_cy:     int = 0
        self._last_binary: Optional[np.ndarray] = None
        self._last_mask:   Optional[np.ndarray] = None
        self._proc_scale:  float = 1.0  # eredeti_szélesség / proc_szélesség
        self._hough_skip:  int = 0   # HoughCircles kihagyás-számláló (interval caching)

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
        self._last_cx        = 0
        self._last_cy        = 0
        self._last_binary    = None
        self._last_mask      = None
        self._proc_scale     = 1.0
        self._hough_skip     = 0

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
            await asyncio.sleep(1.0 / settings.VISION_PROCESS_FPS)

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

    @staticmethod
    def _downscale(frame: np.ndarray) -> Tuple[np.ndarray, float]:
        """Frame lekicsinyítése VISION_PROCESS_WIDTH-re. Visszaad (small, scale)
        ahol scale = eredeti_szélesség / small_szélesség (≥1.0)."""
        pw = settings.VISION_PROCESS_WIDTH
        h, w = frame.shape[:2]
        if pw > 0 and pw < w:
            ph = int(h * pw / w)
            return cv2.resize(frame, (pw, ph), interpolation=cv2.INTER_LINEAR), w / pw
        return frame, 1.0

    def _store_cache(self, cx_s: int, cy_s: int,
                     binary: np.ndarray, mask: np.ndarray, scale: float) -> None:
        """Cache feltöltése: small-frame bináris/maszk + vissza-skálázott középpont.
        _last_circle MINDIG a kis (proc) frame terében marad — annotate() skáláz vissza."""
        self._proc_scale  = scale
        self._last_binary = binary
        self._last_mask   = mask
        self._last_cx = int(cx_s * scale)  # eredeti frame koordináta (annotációhoz)
        self._last_cy = int(cy_s * scale)  # eredeti frame koordináta (annotációhoz)

    def _extract_digit_cuda(self, frame: np.ndarray) -> Optional[int]:
        """Hibrid GPU/CPU feldolgozás — Maxwell-kompatibilis műveletek GPU-n."""
        try:
            small, scale = self._downscale(frame)

            # BGR → Szürke GPU-n (megbízható Maxwell-on)
            gpu_frame = cv2.cuda_GpuMat()
            gpu_frame.upload(small)
            gpu_gray = cv2.cuda.cvtColor(gpu_frame, cv2.COLOR_BGR2GRAY)
            gray = gpu_gray.download()

            # Medián blur + körkeresés + maszkolás CPU-n
            # (Maxwell SM 5.3-on ezek GPU-n instabilak bizonyos képméreteknél)
            blurred = cv2.medianBlur(gray, 5)
            cx_s, cy_s, mask = self._find_circle_mask_cpu(small, blurred)
            masked_gray = cv2.bitwise_and(gray, gray, mask=mask)

            # Threshold GPU-n (megbízható, egyszerű elem-szintű művelet)
            gpu_mg = cv2.cuda_GpuMat()
            gpu_mg.upload(masked_gray)
            _, gpu_binary = cv2.cuda.threshold(
                gpu_mg, settings.VISION_LED_THRESHOLD, 255, cv2.THRESH_BINARY
            )
            binary = gpu_binary.download()
            self._store_cache(cx_s, cy_s, binary, mask, scale)
            return self._read_squares(binary, cx_s, cy_s)

        except Exception as e:
            log.warning(f"CUDA frame hiba (CPU fallback): {e}")
            return self._extract_digit_cpu(frame)

    def _extract_digit_cpu(self, frame: np.ndarray) -> Optional[int]:
        """CPU alapú feldolgozás."""
        small, scale = self._downscale(frame)
        gray    = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        blurred = cv2.medianBlur(gray, 5)
        cx_s, cy_s, mask = self._find_circle_mask_cpu(small, blurred)
        masked      = cv2.bitwise_and(small, small, mask=mask)
        masked_gray = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)
        _, binary   = cv2.threshold(masked_gray, settings.VISION_LED_THRESHOLD,
                                    255, cv2.THRESH_BINARY)
        self._store_cache(cx_s, cy_s, binary, mask, scale)
        return self._read_squares(binary, cx_s, cy_s)

    # ── Körkeresés ────────────────────────────────────────────────────────────

    def _find_circle_mask_cpu(
        self, frame: np.ndarray, blurred: np.ndarray
    ) -> Tuple[int, int, np.ndarray]:
        h, w = frame.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)

        if settings.VISION_USE_HOUGH:
            # Kör cache: VISION_HOUGH_INTERVAL frame-enként fut csak a HoughCircles
            self._hough_skip += 1
            if self._last_circle is not None and self._hough_skip < settings.VISION_HOUGH_INTERVAL:
                cx, cy, r = self._last_circle
                cv2.circle(mask, (cx, cy), r, 255, -1)
                return cx, cy, mask

            self._hough_skip = 0
            # Radius paraméterek arányosan skálázva a kis frame méretéhez
            _rscale = frame.shape[1] / max(settings.CAMERA_WIDTH, 1)
            _min_r  = max(1, int(settings.VISION_HOUGH_MIN_RADIUS * _rscale))
            _max_r  = int(settings.VISION_HOUGH_MAX_RADIUS * _rscale) if settings.VISION_HOUGH_MAX_RADIUS > 0 else 0
            circles = cv2.HoughCircles(
                blurred, cv2.HOUGH_GRADIENT, 1,
                blurred.shape[0] / 8,
                param1=settings.VISION_HOUGH_PARAM1,
                param2=settings.VISION_HOUGH_PARAM2,
                minRadius=_min_r,
                maxRadius=_max_r,
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

    # ── LED olvasás: rács (grid) alapú módszer ────────────────────────────────
    #
    # A kör/ROI középpontja (cx, cy) osztóként 4 negyedre bontja a bináris képet.
    # Az átlagot CSAK a körön belüli pixelekre számítjuk (mask alapján) — a körön
    # kívüli nullák nem hígítják a mérést.
    #
    # Bit-kiosztás (versenyspecifikáció): TL=1, TR=2, BL=4, BR=8

    @staticmethod
    def _quad_mean(b: np.ndarray, m: Optional[np.ndarray]) -> float:
        """Átlag csak a maszkolt (körön belüli) pixelekre."""
        if m is None or not b.size:
            return float(np.mean(b)) if b.size else 0.0
        n = int(np.count_nonzero(m))
        return float(np.sum(b)) / n if n > 0 else 0.0

    def _read_squares(
        self, binary: np.ndarray, cx: int, cy: int
    ) -> Optional[int]:
        # Ha nincs detektált kör (csak ROI fallback), ne olvassunk zaj-digitot
        if settings.VISION_REQUIRE_CIRCLE and self._last_circle is None:
            return None
        thr  = settings.VISION_GRID_THRESHOLD
        mask = self._last_mask
        code = 0
        quads = [
            (binary[:cy, :cx], mask[:cy, :cx] if mask is not None else None, 1),  # TL
            (binary[:cy, cx:], mask[:cy, cx:] if mask is not None else None, 2),  # TR
            (binary[cy:, :cx], mask[cy:, :cx] if mask is not None else None, 4),  # BL
            (binary[cy:, cx:], mask[cy:, cx:] if mask is not None else None, 8),  # BR
        ]
        for b, m, bit in quads:
            if self._quad_mean(b, m) > thr:
                code |= bit
        return code if code else None

    def get_debug_frame(self) -> Optional[np.ndarray]:
        return self._last_annotated

    # ── Annotált frame ────────────────────────────────────────────────────────

    def annotate(self, frame: np.ndarray, digit: Optional[int]) -> np.ndarray:
        out    = frame.copy()
        binary = self._last_binary
        if binary is None:
            return out  # _process_frame() még nem futott

        # Koordináták: cx/cy az eredeti frame-ben (rajzoláshoz),
        # cx_s/cy_s a kis proc-frame-ben (binary/mask indexeléshez)
        cx, cy = self._last_cx, self._last_cy
        s      = self._proc_scale
        cx_s   = int(cx / s) if s > 1.0 else cx
        cy_s   = int(cy / s) if s > 1.0 else cy

        mask = self._last_mask
        thr  = settings.VISION_GRID_THRESHOLD
        H, W = out.shape[:2]

        # Négy negyed definíciója az eredeti frame-ben (rajzolás) és a binary-ban (mérés)
        quads = [
            # (b_slice, m_slice, draw_rect(x1,y1,x2,y2), label_pos, label)
            (binary[:cy_s, :cx_s], mask[:cy_s, :cx_s] if mask is not None else None,
             (0,  0,  cx, cy),  (max(cx//2-20, 2),        max(cy//2, 14)),       "TL:1"),
            (binary[:cy_s, cx_s:], mask[:cy_s, cx_s:] if mask is not None else None,
             (cx, 0,  W,  cy),  (cx + (W-cx)//2 - 20,     max(cy//2, 14)),       "TR:2"),
            (binary[cy_s:, :cx_s], mask[cy_s:, :cx_s] if mask is not None else None,
             (0,  cy, cx, H),   (max(cx//2-20, 2),        cy + (H-cy)//2),       "BL:4"),
            (binary[cy_s:, cx_s:], mask[cy_s:, cx_s:] if mask is not None else None,
             (cx, cy, W,  H),   (cx + (W-cx)//2 - 20,     cy + (H-cy)//2),       "BR:8"),
        ]

        # Negyed kiemelés: félátlátszó zöld (aktív) / sötétszürke (inaktív)
        overlay = out.copy()
        for b, m, (x1, y1, x2, y2), _, _ in quads:
            active = self._quad_mean(b, m) > thr
            color  = (0, 180, 0) if active else (40, 40, 40)
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
        cv2.addWeighted(overlay, 0.25, out, 0.75, 0, out)

        # Kör / ROI keret (_last_circle a proc frame terében van → vissza kell skálázni)
        if self._last_circle:
            lcx = int(self._last_circle[0] * s)
            lcy = int(self._last_circle[1] * s)
            lr  = int(self._last_circle[2] * s)
            cv2.circle(out, (lcx, lcy), lr, (0, 200, 255), 2)
            cv2.circle(out, (lcx, lcy), 3,  (0, 200, 255), -1)
        else:
            rx = settings.VISION_ROI_X
            ry = settings.VISION_ROI_Y
            rw = min(settings.VISION_ROI_W, W - rx)
            rh = min(settings.VISION_ROI_H, H - ry)
            cv2.rectangle(out, (rx, ry), (rx + rw, ry + rh), (0, 200, 255), 2)

        # Rács osztóvonalak
        cv2.line(out, (cx, 0), (cx, H), (0, 200, 255), 1)
        cv2.line(out, (0, cy), (W, cy), (0, 200, 255), 1)

        # Negyed átlag szöveg
        for b, m, _, (lx, ly), lbl in quads:
            mean_val = self._quad_mean(b, m)
            active   = mean_val > thr
            color    = (0, 255, 0) if active else (160, 160, 160)
            cv2.putText(out, f"{lbl} {mean_val:.0f}",
                        (lx, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

        # Állapot + digit + CPU/GPU jelzés
        cv2.putText(out, self._state.name, (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
        if digit is not None:
            cv2.putText(out, f"{digit:X}", (8, 52),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (56, 189, 248), 2)
        cuda_lbl = "GPU" if self._cuda_ok else "CPU"
        cv2.putText(out, cuda_lbl, (W - 44, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 0) if self._cuda_ok else (0, 165, 255), 1)
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

