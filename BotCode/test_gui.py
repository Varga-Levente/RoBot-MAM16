"""
MAM16 Robot — Grafikus tesztelő felület

Indítás:   python test_gui.py
Függőség:  pip install customtkinter opencv-python Pillow
"""

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageTk

# ── customtkinter (modern dark UI) ────────────────────────────────────────────
try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
except ImportError:
    sys.exit(
        "Hiányzó csomag: customtkinter\n"
        "Telepítés: pip install customtkinter"
    )

# ── BotCode modulok ───────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settings

settings.DRY_RUN = True   # Teszt GUI mindig dry-run módban fut

from components.vision          import VisionProcessor
from components.ir_transmitter  import IRTransmitter
from components.motor_controller import MotorController

# ── Stílus konstansok ─────────────────────────────────────────────────────────
_FONT_TITLE  = ("Segoe UI", 20, "bold")
_FONT_LABEL  = ("Segoe UI", 12)
_FONT_SMALL  = ("Segoe UI", 10)
_FONT_MONO   = ("Courier New", 13)
_FONT_CODE   = ("Courier New", 36, "bold")
_FONT_BADGE  = ("Segoe UI", 11, "bold")

_CLR_ACCENT   = "#38bdf8"
_CLR_GREEN    = "#4ade80"
_CLR_ORANGE   = "#fb923c"
_CLR_RED      = "#f87171"
_CLR_PURPLE   = "#a855f7"
_CLR_MUTED    = "#94a3b8"
_CLR_SURFACE  = "#1e1e2e"
_CLR_SURFACE2 = "#2a2a3e"


# ══════════════════════════════════════════════════════════════════════════════
#  Alap panel
# ══════════════════════════════════════════════════════════════════════════════

class _Panel(ctk.CTkFrame):
    """Alap panel osztály — minden komponens panel ebből örököl."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=_CLR_SURFACE, corner_radius=12, **kwargs)

    def cleanup(self) -> None:
        """Takarítás panel váltáskor (override ha szükséges)."""
        pass


def _section(parent, title: str) -> ctk.CTkFrame:
    """Fejléccel ellátott szekció keret."""
    outer = ctk.CTkFrame(parent, fg_color=_CLR_SURFACE2, corner_radius=10)
    ctk.CTkLabel(outer, text=title, font=_FONT_BADGE,
                 text_color=_CLR_MUTED).pack(anchor="w", padx=12, pady=(8, 2))
    ctk.CTkFrame(outer, height=1, fg_color="#333355", corner_radius=0).pack(fill="x", padx=8)
    inner = ctk.CTkFrame(outer, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=10, pady=(4, 10))
    return inner


def _status_dot(parent, color: str = _CLR_MUTED) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text="●", font=_FONT_LABEL, text_color=color)


# ══════════════════════════════════════════════════════════════════════════════
#  Kamera panel
# ══════════════════════════════════════════════════════════════════════════════

class CameraPanel(_Panel):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._after_id = None
        self._frame_count = 0
        self._fps_ts = time.monotonic()
        self._fps_val = 0.0
        self._build_ui()
        self._start_camera()

    def _build_ui(self):
        # Fejléc
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(hdr, text="Kamera preview", font=_FONT_TITLE).pack(side="left")
        self._fps_lbl = ctk.CTkLabel(hdr, text="FPS: –", font=_FONT_SMALL, text_color=_CLR_MUTED)
        self._fps_lbl.pack(side="right", padx=8)
        self._status_lbl = _status_dot(hdr, _CLR_MUTED)
        self._status_lbl.pack(side="right")

        # Kép terület
        self._img_lbl = ctk.CTkLabel(self, text="Kamera inicializálása...",
                                     font=_FONT_LABEL, text_color=_CLR_MUTED,
                                     fg_color="#0a0a0f", corner_radius=10)
        self._img_lbl.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        # Vezérlők
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(ctrl, text="Flip:", font=_FONT_SMALL).pack(side="left")
        self._flip_var = tk.IntVar(value=settings.CAMERA_FLIP)
        for val, label in [(0, "Nincs"), (1, "Vízszintes"), (2, "Függőleges"), (4, "180°")]:
            ctk.CTkRadioButton(ctrl, text=label, variable=self._flip_var, value=val,
                               font=_FONT_SMALL,
                               command=lambda: None).pack(side="left", padx=6)

        ctk.CTkButton(ctrl, text="Alapbeállítás visszaállítása", width=180, height=30,
                      font=_FONT_SMALL,
                      command=self._reset).pack(side="right")

        # Info sor
        self._info_lbl = ctk.CTkLabel(self, text="", font=_FONT_SMALL, text_color=_CLR_MUTED)
        self._info_lbl.pack(pady=(0, 8))

    def _start_camera(self):
        test_video = settings.CAMERA_TEST_VIDEO
        if test_video and os.path.exists(test_video):
            self._cap = cv2.VideoCapture(test_video)
            src = f"Videófájl: {os.path.basename(test_video)}"
        else:
            # Próbál webcam-ot (0. index) — Jetson Nano-n ez a CSI kamera
            self._cap = cv2.VideoCapture(0)
            src = "Kamera index: 0"

        if self._cap.isOpened():
            self._running = True
            self._status_lbl.configure(text_color=_CLR_GREEN)
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._info_lbl.configure(text=f"{src}  |  {w}×{h}")
            self._update()
        else:
            self._status_lbl.configure(text_color=_CLR_RED)
            self._img_lbl.configure(text="Kamera nem elérhető\n(Próbálj tesztvideót beállítani a settings.py-ban)")

    def _update(self):
        if not self._running or not self._cap or not self._cap.isOpened():
            return
        ret, frame = self._cap.read()
        if ret:
            flip = self._flip_var.get()
            if flip == 1:
                frame = cv2.flip(frame, 1)
            elif flip == 2:
                frame = cv2.flip(frame, 0)
            elif flip == 4:
                frame = cv2.flip(frame, -1)

            # ROI jelzés
            cv2.rectangle(frame,
                (settings.VISION_ROI_X, settings.VISION_ROI_Y),
                (settings.VISION_ROI_X + settings.VISION_ROI_W,
                 settings.VISION_ROI_Y + settings.VISION_ROI_H),
                (0, 200, 255), 2)

            w = self._img_lbl.winfo_width() or 640
            h = self._img_lbl.winfo_height() or 400
            self._show_frame(frame, w, h)

            self._frame_count += 1
            now = time.monotonic()
            if now - self._fps_ts >= 1.0:
                self._fps_val = self._frame_count / (now - self._fps_ts)
                self._fps_lbl.configure(text=f"FPS: {self._fps_val:.1f}")
                self._frame_count = 0
                self._fps_ts = now
        else:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        self._after_id = self.after(33, self._update)

    def _show_frame(self, frame: np.ndarray, max_w: int, max_h: int):
        h, w = frame.shape[:2]
        scale = min(max_w / w, max_h / h, 1.0)
        nw, nh = int(w * scale), int(h * scale)
        if nw < 10 or nh < 10:
            return
        frame_rgb = cv2.cvtColor(cv2.resize(frame, (nw, nh)), cv2.COLOR_BGR2RGB)
        img = ImageTk.PhotoImage(Image.fromarray(frame_rgb))
        self._img_lbl.configure(image=img, text="")
        self._img_lbl.image = img

    def _reset(self):
        self._flip_var.set(0)

    def cleanup(self):
        self._running = False
        if self._after_id:
            self.after_cancel(self._after_id)
        if self._cap:
            self._cap.release()


# ══════════════════════════════════════════════════════════════════════════════
#  Vision panel
# ══════════════════════════════════════════════════════════════════════════════

class VisionPanel(_Panel):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._cap: Optional[cv2.VideoCapture] = None
        self._processor = VisionProcessor()
        self._playing = False
        self._loop_var = tk.BooleanVar(value=True)
        self._video_path = tk.StringVar(value="")
        self._detected_codes: list[str] = []
        self._after_id = None
        self._state_var    = tk.StringVar(value="WAIT_FOR_F")
        self._digit_var    = tk.StringVar(value="–")
        self._code_var     = tk.StringVar(value="---")
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text="Vision – Kapu kód felismerés",
                     font=_FONT_TITLE).pack(anchor="w", padx=16, pady=(14, 8))

        # Fájl tallózás sáv
        fb = ctk.CTkFrame(self, fg_color=_CLR_SURFACE2, corner_radius=8)
        fb.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(fb, text="Videó tallózása...", width=150, height=32,
                      command=self._browse).pack(side="left", padx=8, pady=8)
        ctk.CTkEntry(fb, textvariable=self._video_path, state="readonly",
                     font=_FONT_SMALL, height=32).pack(side="left", fill="x", expand=True, padx=(0, 8), pady=8)

        # Lejátszás vezérlők
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=16, pady=(0, 8))
        self._play_btn = ctk.CTkButton(ctrl, text="▶  Lejátszás", width=130, height=34,
                                       fg_color=_CLR_GREEN, hover_color="#22c55e",
                                       text_color="#000", font=("Segoe UI", 12, "bold"),
                                       command=self._play)
        self._play_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(ctrl, text="■  Stop", width=90, height=34,
                      fg_color="#334155", hover_color="#475569",
                      command=self._stop).pack(side="left", padx=(0, 8))
        ctk.CTkCheckBox(ctrl, text="Ismétlés", variable=self._loop_var,
                        font=_FONT_SMALL).pack(side="left", padx=8)

        # Fő tartalom: bal=videó, jobb=eredmények
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        # Bal: videó + ROI zoom
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(0, weight=3)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        self._video_lbl = ctk.CTkLabel(left, text="Válassz videófájlt a teszteléshez",
                                       font=_FONT_LABEL, text_color=_CLR_MUTED,
                                       fg_color="#0a0a0f", corner_radius=10)
        self._video_lbl.grid(row=0, column=0, sticky="nsew", pady=(0, 6))

        roi_frame = _section(left, "ROI nagyítás")
        roi_frame.master.grid(row=1, column=0, sticky="nsew")
        self._roi_lbl = ctk.CTkLabel(roi_frame, text="–",
                                     font=_FONT_SMALL, text_color=_CLR_MUTED,
                                     fg_color="#0a0a0f", corner_radius=8)
        self._roi_lbl.pack(fill="both", expand=True)

        # Jobb: állapot + kód
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(4, weight=1)
        right.columnconfigure(0, weight=1)

        # Állapot gép
        state_sec = _section(right, "Állapotgép")
        state_sec.master.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._state_badge = ctk.CTkLabel(state_sec, textvariable=self._state_var,
                                         font=_FONT_BADGE, text_color=_CLR_ACCENT,
                                         fg_color="#0f2744", corner_radius=8)
        self._state_badge.pack(fill="x", ipady=6)

        # Aktuális digit
        digit_sec = _section(right, "Aktuális digit")
        digit_sec.master.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        dig_row = ctk.CTkFrame(digit_sec, fg_color="transparent")
        dig_row.pack()
        self._digit_lbl = ctk.CTkLabel(dig_row, textvariable=self._digit_var,
                                        font=("Courier New", 42, "bold"),
                                        text_color=_CLR_ACCENT)
        self._digit_lbl.pack(side="left", padx=(0, 12))

        # 4 bit LED indikátor
        self._bit_dots: list[ctk.CTkLabel] = []
        bits_frame = ctk.CTkFrame(dig_row, fg_color="transparent")
        bits_frame.pack(side="left")
        ctk.CTkLabel(bits_frame, text="MSB → LSB", font=_FONT_SMALL,
                     text_color=_CLR_MUTED).pack()
        dots_row = ctk.CTkFrame(bits_frame, fg_color="transparent")
        dots_row.pack()
        for _ in range(4):
            d = ctk.CTkLabel(dots_row, text="●", font=("Segoe UI", 22),
                             text_color=_CLR_MUTED)
            d.pack(side="left", padx=3)
            self._bit_dots.append(d)

        # Felismert kód
        code_sec = _section(right, "Felismert kód")
        code_sec.master.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self._code_lbl = ctk.CTkLabel(code_sec, textvariable=self._code_var,
                                       font=_FONT_CODE,
                                       text_color=_CLR_GREEN)
        self._code_lbl.pack(ipady=8)

        # Előzmények
        hist_sec = _section(right, "Előzmények")
        hist_sec.master.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self._history_lbl = ctk.CTkLabel(hist_sec, text="–",
                                          font=_FONT_MONO, text_color=_CLR_MUTED,
                                          justify="left")
        self._history_lbl.pack(anchor="w")

        # Statisztika
        stat_sec = _section(right, "Statisztika")
        stat_sec.master.grid(row=4, column=0, sticky="nsew")
        self._stat_lbl = ctk.CTkLabel(stat_sec, text="Frame: 0  |  Kódok: 0",
                                       font=_FONT_SMALL, text_color=_CLR_MUTED)
        self._stat_lbl.pack()
        ctk.CTkButton(stat_sec, text="Előzmények törlése", height=28,
                      font=_FONT_SMALL, fg_color="#334155",
                      command=self._clear_history).pack(pady=(6, 0))

        self._frame_count = 0

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Válassz tesztvideót",
            filetypes=[
                ("Videó fájlok", "*.mp4 *.avi *.mov *.mkv *.webm *.m4v"),
                ("Minden fájl", "*.*"),
            ]
        )
        if path:
            self._video_path.set(path)
            self._stop()

    def _play(self):
        path = self._video_path.get()
        if not path:
            messagebox.showwarning("Nincs videó", "Kérlek tallózz be egy videófájlt!")
            return
        if not os.path.exists(path):
            messagebox.showerror("Fájl nem található", f"Nem létezik: {path}")
            return

        self._stop()
        self._cap = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            messagebox.showerror("Hiba", f"Nem sikerült megnyitni: {path}")
            return

        self._processor = VisionProcessor()   # reset
        self._playing = True
        self._play_btn.configure(fg_color="#0f766e", text="▶  Fut...")
        self._update()

    def _stop(self):
        self._playing = False
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self._cap:
            self._cap.release()
            self._cap = None
        self._play_btn.configure(fg_color=_CLR_GREEN, text="▶  Lejátszás")
        self._state_var.set("WAIT_FOR_F")
        self._digit_var.set("–")
        self._update_bit_dots(0)

    def _update(self):
        if not self._playing or not self._cap:
            return

        ret, frame = self._cap.read()
        if not ret:
            if self._loop_var.get():
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self._after_id = self.after(33, self._update)
            else:
                self._stop()
            return

        self._frame_count += 1

        # ── Vision feldolgozás ───────────────────────────────────────────
        code = self._processor._process_frame(frame)
        digit = self._processor._last_digit
        state_name = self._processor._state.name

        # ── Annotáció a frame-re ─────────────────────────────────────────
        annotated = frame.copy()

        # ROI keret
        rx = settings.VISION_ROI_X
        ry = settings.VISION_ROI_Y
        rw = settings.VISION_ROI_W
        rh = settings.VISION_ROI_H
        cv2.rectangle(annotated, (rx, ry), (rx + rw, ry + rh), (0, 200, 255), 2)

        # Állapot szöveg a frame-en
        state_color = {"WAIT_FOR_F": (150, 150, 150),
                       "COLLECTING": (0, 220, 130),
                       "COOLDOWN":   (200, 100, 0)}.get(state_name, (255, 255, 255))
        cv2.putText(annotated, state_name, (rx, ry - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, state_color, 2)

        # Digit overlay
        if digit is not None:
            dtext = f"{digit:X}"
            cv2.putText(annotated, dtext,
                        (rx + rw + 10, ry + 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.8, (56, 189, 248), 3)

        # ── Kép megjelenítése ────────────────────────────────────────────
        vw = self._video_lbl.winfo_width() or 640
        vh = self._video_lbl.winfo_height() or 400
        self._show_in_label(self._video_lbl, annotated, vw, vh)

        # ── ROI zoom ─────────────────────────────────────────────────────
        h, w = frame.shape[:2]
        if rx + rw <= w and ry + rh <= h:
            roi = annotated[ry:ry + rh, rx:rx + rw].copy()
            # Szekció vonalak
            sw = rw // 4
            for i in range(1, 4):
                cv2.line(roi, (i * sw, 0), (i * sw, rh), (100, 100, 100), 1)
            roi_h = self._roi_lbl.winfo_height() or 100
            roi_w = self._roi_lbl.winfo_width() or 300
            self._show_in_label(self._roi_lbl, roi, roi_w, roi_h)

        # ── UI állapot frissítés ─────────────────────────────────────────
        self._state_var.set(state_name)
        if digit is not None:
            self._digit_var.set(f"{digit:X}")
            self._update_bit_dots(digit)
        if code:
            self._code_var.set(code)
            self._detected_codes.insert(0, code)
            self._detected_codes = self._detected_codes[:20]
            self._history_lbl.configure(
                text="  ".join(self._detected_codes[:8])
            )

        self._stat_lbl.configure(
            text=f"Frame: {self._frame_count}  |  Kódok: {len(self._detected_codes)}"
        )

        self._after_id = self.after(33, self._update)

    def _show_in_label(self, label: ctk.CTkLabel, frame: np.ndarray, max_w: int, max_h: int):
        if max_w < 10 or max_h < 10:
            return
        h, w = frame.shape[:2]
        scale = min(max_w / w, max_h / h, 1.0)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        rgb = cv2.cvtColor(cv2.resize(frame, (nw, nh)), cv2.COLOR_BGR2RGB)
        photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        label.configure(image=photo, text="")
        label.image = photo

    def _update_bit_dots(self, value: int):
        for i, dot in enumerate(self._bit_dots):
            bit = (value >> (3 - i)) & 1
            dot.configure(text_color=_CLR_GREEN if bit else "#334155")

    def _clear_history(self):
        self._detected_codes.clear()
        self._history_lbl.configure(text="–")
        self._code_var.set("---")
        self._stat_lbl.configure(text="Frame: 0  |  Kódok: 0")
        self._frame_count = 0

    def cleanup(self):
        self._stop()


# ══════════════════════════════════════════════════════════════════════════════
#  IR Adó panel
# ══════════════════════════════════════════════════════════════════════════════

class IRPanel(_Panel):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._ir = IRTransmitter()
        self._sent: list[str] = []
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text="IR Adó teszt", font=_FONT_TITLE).pack(
            anchor="w", padx=16, pady=(14, 10))

        ctk.CTkLabel(self, text="Dry-run mód: valódi UART hardver nélkül fut",
                     font=_FONT_SMALL, text_color=_CLR_ORANGE).pack(anchor="w", padx=16)

        # Kód küldés
        send_sec = _section(self, "Kód manuális küldése")
        send_sec.master.pack(fill="x", padx=16, pady=(12, 8))

        row = ctk.CTkFrame(send_sec, fg_color="transparent")
        row.pack(fill="x")

        ctk.CTkLabel(row, text="Hex kód (3 karakter):", font=_FONT_LABEL).pack(side="left")
        self._code_entry = ctk.CTkEntry(row, width=100, font=_FONT_MONO,
                                         placeholder_text="CA6")
        self._code_entry.pack(side="left", padx=8)
        self._code_entry.insert(0, "CA6")

        ctk.CTkButton(row, text="Küldés", width=100, height=34,
                      fg_color=_CLR_ACCENT, hover_color="#0ea5e9",
                      text_color="#000", font=("Segoe UI", 12, "bold"),
                      command=self._send).pack(side="left", padx=8)

        self._send_status = ctk.CTkLabel(send_sec, text="", font=_FONT_LABEL)
        self._send_status.pack(anchor="w", pady=(8, 0))

        # Rate limiter státusz
        rate_sec = _section(self, "Rate limiter")
        rate_sec.master.pack(fill="x", padx=16, pady=(0, 8))
        self._rate_lbl = ctk.CTkLabel(rate_sec,
                                       text=f"Maximum: {settings.IR_MAX_TX_PER_SEC} adás / másodperc",
                                       font=_FONT_LABEL, text_color=_CLR_MUTED)
        self._rate_lbl.pack(anchor="w")

        # Előzmények
        hist_sec = _section(self, "Küldési előzmények")
        hist_sec.master.pack(fill="x", padx=16, pady=(0, 8))
        self._hist_box = ctk.CTkTextbox(hist_sec, height=200, font=_FONT_MONO,
                                         state="disabled", fg_color="#0a0a0f")
        self._hist_box.pack(fill="x")

        # Beállítások info
        info_sec = _section(self, "Jelenlegi beállítások")
        info_sec.master.pack(fill="x", padx=16, pady=(0, 12))
        mode = settings.IR_MODE
        if mode == "CARRIER_UART":
            baud_info = f"{settings.IR_CARRIER_BAUD} baud (carrier, {settings.IR_BYTES_PER_BIT}B/bit)"
        else:
            baud_info = f"{settings.IR_BAUD_RATE} baud"
        info = (
            f"Mód:         {mode}\n"
            f"UART port:   {settings.IR_UART_PORT}\n"
            f"Baud rate:   {baud_info}\n"
            f"Stop bits:   {settings.IR_STOP_BITS}\n"
            f"Max TX/sec:  {settings.IR_MAX_TX_PER_SEC}"
        )
        ctk.CTkLabel(info_sec, text=info, font=_FONT_MONO,
                     text_color=_CLR_MUTED, justify="left").pack(anchor="w")

    def _send(self):
        code = self._code_entry.get().strip().upper()
        if len(code) != 3 or not all(c in "0123456789ABCDEF" for c in code):
            self._send_status.configure(text="Érvénytelen kód! (3 hex karakter szükséges)",
                                         text_color=_CLR_RED)
            return

        ok = self._ir.transmit(code)
        if ok:
            self._send_status.configure(text=f"✓ Elküldve: {code}", text_color=_CLR_GREEN)
            ts = time.strftime("%H:%M:%S")
            self._sent.insert(0, f"[{ts}]  {code}")
            self._hist_box.configure(state="normal")
            self._hist_box.delete("1.0", "end")
            self._hist_box.insert("1.0", "\n".join(self._sent[:50]))
            self._hist_box.configure(state="disabled")
        else:
            self._send_status.configure(
                text="Rate limit! Várj 0.5 másodpercet.", text_color=_CLR_ORANGE)

    def cleanup(self):
        self._ir.close()


# ══════════════════════════════════════════════════════════════════════════════
#  LoRa panel
# ══════════════════════════════════════════════════════════════════════════════

class LoRaPanel(_Panel):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._packets: list[str] = []
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text="LoRa kommunikáció", font=_FONT_TITLE).pack(
            anchor="w", padx=16, pady=(14, 10))

        ctk.CTkLabel(self, text="Dry-run mód: valódi RFM95W hardver nélkül fut",
                     font=_FONT_SMALL, text_color=_CLR_ORANGE).pack(anchor="w", padx=16)

        # Státusz
        stat_sec = _section(self, "Modul státusz")
        stat_sec.master.pack(fill="x", padx=16, pady=(12, 8))

        fields = [
            ("Frekvencia",       f"{settings.LORA_FREQUENCY_MHZ} MHz"),
            ("Spreading Factor", f"SF{settings.LORA_SPREADING_FACTOR}"),
            ("Sávszélesség",     f"{settings.LORA_BANDWIDTH_KHZ} kHz"),
            ("TX teljesítmény",  f"{settings.LORA_TX_POWER_DBM} dBm"),
            ("Device ID",        settings.LORA_DEVICE_ID.hex().upper()),
            ("AES kulcs",        "● " * 16 + " (rejtett)"),
        ]
        for label, value in fields:
            row = ctk.CTkFrame(stat_sec, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=f"{label}:", font=_FONT_SMALL,
                         text_color=_CLR_MUTED, width=140, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value, font=_FONT_MONO).pack(side="left")

        # Titkosítás teszt
        crypto_sec = _section(self, "Titkosítás teszt (encrypt → decrypt round-trip)")
        crypto_sec.master.pack(fill="x", padx=16, pady=(0, 8))

        row = ctk.CTkFrame(crypto_sec, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text="Teszt üzenet:", font=_FONT_SMALL).pack(side="left")
        self._msg_entry = ctk.CTkEntry(row, width=200, font=_FONT_SMALL,
                                        placeholder_text='{"cmd":"move","linear":0.5}')
        self._msg_entry.pack(side="left", padx=8)
        self._msg_entry.insert(0, '{"cmd":"move","linear":0.5}')
        ctk.CTkButton(row, text="Teszt", width=80,
                      command=self._crypto_test).pack(side="left")

        self._crypto_result = ctk.CTkLabel(crypto_sec, text="", font=_FONT_MONO,
                                            justify="left")
        self._crypto_result.pack(anchor="w", pady=(6, 0))

        # Szimulált csomag log
        log_sec = _section(self, "Csomag log (szimulált)")
        log_sec.master.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(log_sec, text="Szimulált csomag fogadása", height=32,
                      command=self._sim_receive).pack(anchor="w", pady=(0, 6))
        self._log_box = ctk.CTkTextbox(log_sec, height=160, font=_FONT_MONO,
                                        state="disabled", fg_color="#0a0a0f")
        self._log_box.pack(fill="x")

    def _crypto_test(self):
        from components.lora_comm import _encrypt, _decrypt
        msg = self._msg_entry.get().encode()
        encrypted = _encrypt(msg, settings.LORA_AES_KEY,
                             settings.LORA_HMAC_KEY, settings.LORA_DEVICE_ID)
        decrypted = _decrypt(encrypted, settings.LORA_AES_KEY,
                             settings.LORA_HMAC_KEY, settings.LORA_DEVICE_ID)
        ok = decrypted == msg
        result = (
            f"Eredeti:    {msg.decode()}\n"
            f"Titkosított: {encrypted[:20].hex()}... ({len(encrypted)} bájt)\n"
            f"Visszafejtve: {decrypted.decode() if decrypted else 'HIBA'}\n"
            f"Eredmény: {'✓ SIKERES' if ok else '✗ SIKERTELEN'}"
        )
        self._crypto_result.configure(
            text=result,
            text_color=_CLR_GREEN if ok else _CLR_RED
        )

    def _sim_receive(self):
        import json
        from components.lora_comm import _encrypt
        cmds = [
            {"cmd": "move",  "linear": 0.5,  "angular": 0.0},
            {"cmd": "move",  "linear": 0.0,  "angular": 0.3},
            {"cmd": "stop"},
            {"cmd": "move",  "linear": -0.3, "angular": -0.1},
        ]
        import random
        cmd = random.choice(cmds)
        payload = json.dumps(cmd).encode()
        encrypted = _encrypt(payload, settings.LORA_AES_KEY,
                             settings.LORA_HMAC_KEY, settings.LORA_DEVICE_ID)
        ts = time.strftime("%H:%M:%S")
        entry = f"[{ts}]  RX {len(encrypted)}B  →  {json.dumps(cmd)}\n"
        self._log_box.configure(state="normal")
        self._log_box.insert("1.0", entry)
        self._log_box.configure(state="disabled")


# ══════════════════════════════════════════════════════════════════════════════
#  OLED panel
# ══════════════════════════════════════════════════════════════════════════════

class OLEDPanel(_Panel):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._build_ui()
        self._render_mock()

    def _build_ui(self):
        ctk.CTkLabel(self, text="OLED kijelző", font=_FONT_TITLE).pack(
            anchor="w", padx=16, pady=(14, 10))

        ctk.CTkLabel(self, text="Dry-run mód: szimulált megjelenítés",
                     font=_FONT_SMALL, text_color=_CLR_ORANGE).pack(anchor="w", padx=16)

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=12)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)

        # Bal: preview + konfig
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        prev_sec = _section(left, f"OLED preview  ({settings.OLED_WIDTH}×{settings.OLED_HEIGHT} px, 4× nagyítva)")
        prev_sec.master.pack(fill="x")

        # Canvas a mock OLED-hez
        scale = 4
        cw = settings.OLED_WIDTH * scale
        ch = settings.OLED_HEIGHT * scale
        self._canvas = tk.Canvas(prev_sec, width=cw, height=ch,
                                  bg="#000000", highlightthickness=2,
                                  highlightbackground="#334155")
        self._canvas.pack(pady=8)

        # Tartalom beállítás
        edit_sec = _section(left, "Megjelenítendő tartalom")
        edit_sec.master.pack(fill="x", pady=(12, 0))

        fields = [
            ("Sor 1 (Cím):",  "MAM16 [P] *"),
            ("Sor 2 (IP):",   "192.168.1.100"),
            ("Sor 3 (Akku):", "Akku: 11.4V"),
            ("Sor 4 (Kód):",  "Kod: CA6"),
        ]
        self._row_vars: list[tk.StringVar] = []
        for label, default in fields:
            row = ctk.CTkFrame(edit_sec, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, font=_FONT_SMALL,
                         width=120, anchor="w").pack(side="left")
            var = tk.StringVar(value=default)
            self._row_vars.append(var)
            ctk.CTkEntry(row, textvariable=var, font=_FONT_MONO,
                         height=28).pack(side="left", fill="x", expand=True)

        ctk.CTkButton(edit_sec, text="Kijelző frissítése", height=34,
                      fg_color=_CLR_ACCENT, hover_color="#0ea5e9",
                      text_color="#000", font=("Segoe UI", 12, "bold"),
                      command=self._render_mock).pack(pady=(10, 0))

        # Jobb: hardver info
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")

        hw_sec = _section(right, "Hardver beállítások")
        hw_sec.master.pack(fill="x")
        hw_info = (
            f"I2C busz:    {settings.OLED_I2C_BUS}\n"
            f"I2C cím:     0x{settings.OLED_I2C_ADDRESS:02X}\n"
            f"Felbontás:   {settings.OLED_WIDTH}×{settings.OLED_HEIGHT}\n"
            f"Kontraszt:   {settings.OLED_CONTRAST}\n"
            f"Frissítés:   {settings.OLED_UPDATE_HZ} Hz\n"
        )
        ctk.CTkLabel(hw_sec, text=hw_info, font=_FONT_MONO,
                     text_color=_CLR_MUTED, justify="left").pack(anchor="w")

        note_sec = _section(right, "Megjegyzés")
        note_sec.master.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(note_sec,
                     text="A valódi OLED-en a szöveg\n8×8 px-es fonttal jelenik meg.\n"
                          "A preview ezt mutatja szimulálva.",
                     font=_FONT_SMALL, text_color=_CLR_MUTED, justify="left").pack(anchor="w")

    def _render_mock(self):
        scale = 4
        self._canvas.delete("all")
        rows = [var.get() for var in self._row_vars]
        # 8×8 px font → 4× = 32×32 px egy karakter
        # Egyszerűsített: tkinter-rel rajzolunk szöveget
        for i, text in enumerate(rows[:4]):
            y = i * (settings.OLED_HEIGHT // 4) * scale + 2
            self._canvas.create_text(
                3 * scale, y,
                text=text[:21],  # max 21 karakter fér ki
                fill="white",
                anchor="nw",
                font=("Courier New", 7 * scale // 8),
            )

        # Keret
        w = settings.OLED_WIDTH * scale
        h = settings.OLED_HEIGHT * scale
        for i in range(1, 4):
            y = i * (h // 4)
            self._canvas.create_line(0, y, w, y, fill="#111133", width=1)


# ══════════════════════════════════════════════════════════════════════════════
#  Motor panel
# ══════════════════════════════════════════════════════════════════════════════

class MotorPanel(_Panel):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._ctrl = MotorController()
        self._ctrl._init_hardware()
        self._lin_var = tk.DoubleVar(value=0.0)
        self._ang_var = tk.DoubleVar(value=0.0)
        self._motor_vars = [tk.DoubleVar(value=0.0) for _ in range(4)]
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text="Motor vezérlő", font=_FONT_TITLE).pack(
            anchor="w", padx=16, pady=(14, 10))

        ctk.CTkLabel(self, text="Dry-run mód: GPIO nélkül — parancsok logolva",
                     font=_FONT_SMALL, text_color=_CLR_ORANGE).pack(anchor="w", padx=16)

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=12)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)

        # Bal: differenciálhajtás
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        diff_sec = _section(left, "Differenciálhajtás")
        diff_sec.master.pack(fill="x")

        # Irány gombok (WASD)
        pad = ctk.CTkFrame(diff_sec, fg_color=_CLR_SURFACE)
        pad.pack(pady=8)

        btn_kw = dict(width=56, height=44, font=("Segoe UI", 16, "bold"),
                      fg_color=_CLR_SURFACE2, hover_color="#334155")
        ctk.CTkButton(pad, text="▲", **btn_kw,
                      command=lambda: self._set_vel(0.6, 0.0)).grid(row=0, column=1, padx=4, pady=4)
        ctk.CTkButton(pad, text="◀", **btn_kw,
                      command=lambda: self._set_vel(0.0, -0.5)).grid(row=1, column=0, padx=4, pady=4)
        ctk.CTkButton(pad, text="■", width=56, height=44,
                      font=("Segoe UI", 16), fg_color=_CLR_RED, hover_color="#dc2626",
                      text_color="#000",
                      command=self._stop_all).grid(row=1, column=1, padx=4, pady=4)
        ctk.CTkButton(pad, text="▶", **btn_kw,
                      command=lambda: self._set_vel(0.0, 0.5)).grid(row=1, column=2, padx=4, pady=4)
        ctk.CTkButton(pad, text="▼", **btn_kw,
                      command=lambda: self._set_vel(-0.6, 0.0)).grid(row=2, column=1, padx=4, pady=4)

        # Csúszkák
        sliders = ctk.CTkFrame(diff_sec, fg_color="transparent")
        sliders.pack(fill="x", pady=8)

        ctk.CTkLabel(sliders, text="Linear:", font=_FONT_SMALL).grid(row=0, column=0, sticky="w")
        ctk.CTkSlider(sliders, from_=-1, to=1, variable=self._lin_var,
                      command=lambda _: self._update_diff()).grid(row=0, column=1, padx=8, sticky="ew")
        self._lin_lbl = ctk.CTkLabel(sliders, text="0.00", font=_FONT_MONO, width=50)
        self._lin_lbl.grid(row=0, column=2)

        ctk.CTkLabel(sliders, text="Angular:", font=_FONT_SMALL).grid(row=1, column=0, sticky="w")
        ctk.CTkSlider(sliders, from_=-1, to=1, variable=self._ang_var,
                      command=lambda _: self._update_diff()).grid(row=1, column=1, padx=8, sticky="ew")
        self._ang_lbl = ctk.CTkLabel(sliders, text="0.00", font=_FONT_MONO, width=50)
        self._ang_lbl.grid(row=1, column=2)
        sliders.columnconfigure(1, weight=1)

        # Jobb: egyedi motorok
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")

        ind_sec = _section(right, "Egyedi motor vezérlés")
        ind_sec.master.pack(fill="x")

        motor_names = ["FL (Bal első)", "FR (Jobb első)", "RL (Bal hátsó)", "RR (Jobb hátsó)"]
        self._speed_lbls: list[ctk.CTkLabel] = []
        for i, name in enumerate(motor_names):
            row = ctk.CTkFrame(ind_sec, fg_color="transparent")
            row.pack(fill="x", pady=3)
            row.columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=name, font=_FONT_SMALL, width=130, anchor="w").grid(
                row=0, column=0, sticky="w")
            ctk.CTkSlider(row, from_=-1, to=1, variable=self._motor_vars[i],
                          command=lambda v, idx=i: self._set_single_motor(idx, v)).grid(
                row=0, column=1, padx=8, sticky="ew")
            lbl = ctk.CTkLabel(row, text="0.00", font=_FONT_MONO, width=48)
            lbl.grid(row=0, column=2)
            self._speed_lbls.append(lbl)

        ctk.CTkButton(ind_sec, text="Minden motor STOP", height=36,
                      fg_color=_CLR_RED, hover_color="#dc2626",
                      text_color="#000", font=("Segoe UI", 12, "bold"),
                      command=self._stop_all).pack(fill="x", pady=(12, 0))

        # Log
        log_sec = _section(right, "Parancs log")
        log_sec.master.pack(fill="x", pady=(12, 0))
        self._log_box = ctk.CTkTextbox(log_sec, height=140, font=_FONT_MONO,
                                        state="disabled", fg_color="#0a0a0f")
        self._log_box.pack(fill="x")

    def _set_vel(self, linear: float, angular: float):
        self._lin_var.set(linear)
        self._ang_var.set(angular)
        self._update_diff()

    def _update_diff(self):
        lin = round(self._lin_var.get(), 2)
        ang = round(self._ang_var.get(), 2)
        self._lin_lbl.configure(text=f"{lin:+.2f}")
        self._ang_lbl.configure(text=f"{ang:+.2f}")
        self._ctrl.set_velocity(lin, ang)
        self._log(f"set_velocity(linear={lin}, angular={ang})")

    def _set_single_motor(self, motor_id: int, speed: float):
        speed = round(speed, 2)
        self._speed_lbls[motor_id].configure(text=f"{speed:+.2f}")
        self._ctrl.set_motor(motor_id, speed)
        names = ["FL", "FR", "RL", "RR"]
        self._log(f"set_motor({names[motor_id]}, speed={speed})")

    def _stop_all(self):
        self._lin_var.set(0.0)
        self._ang_var.set(0.0)
        for v in self._motor_vars:
            v.set(0.0)
        for lbl in self._speed_lbls:
            lbl.configure(text=" 0.00")
        self._lin_lbl.configure(text=" 0.00")
        self._ang_lbl.configure(text=" 0.00")
        self._ctrl.emergency_stop()
        self._log("emergency_stop()")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self._log_box.configure(state="normal")
        self._log_box.insert("1.0", f"[{ts}] {msg}\n")
        self._log_box.configure(state="disabled")

    def cleanup(self):
        self._ctrl.emergency_stop()
        self._ctrl.cleanup()


# ══════════════════════════════════════════════════════════════════════════════
#  Stream panel
# ══════════════════════════════════════════════════════════════════════════════

class StreamPanel(_Panel):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._server_thread: Optional[threading.Thread] = None
        self._server_running = False
        self._loop = None
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text="WebRTC Stream szerver", font=_FONT_TITLE).pack(
            anchor="w", padx=16, pady=(14, 10))

        # Vezérlők
        ctrl_sec = _section(self, "Szerver vezérlés")
        ctrl_sec.master.pack(fill="x", padx=16, pady=(12, 8))

        row = ctk.CTkFrame(ctrl_sec, fg_color="transparent")
        row.pack(fill="x")

        self._start_btn = ctk.CTkButton(row, text="▶  Szerver indítása", width=180, height=38,
                                         fg_color=_CLR_GREEN, hover_color="#22c55e",
                                         text_color="#000", font=("Segoe UI", 12, "bold"),
                                         command=self._start_server)
        self._start_btn.pack(side="left")
        self._stop_btn = ctk.CTkButton(row, text="■  Leállítás", width=130, height=38,
                                        fg_color="#334155", state="disabled",
                                        command=self._stop_server)
        self._stop_btn.pack(side="left", padx=8)

        self._server_status = ctk.CTkLabel(ctrl_sec, text="Leállítva",
                                            font=_FONT_LABEL, text_color=_CLR_MUTED)
        self._server_status.pack(anchor="w", pady=(8, 0))

        # URL
        url_sec = _section(self, "Elérési cím")
        url_sec.master.pack(fill="x", padx=16, pady=(0, 8))
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            ip = "127.0.0.1"

        url = f"http://{ip}:{settings.STREAM_PORT}"
        ctk.CTkLabel(url_sec, text=url, font=("Courier New", 16, "bold"),
                     text_color=_CLR_ACCENT).pack(anchor="w")

        ctk.CTkButton(url_sec, text="Megnyitás böngészőben", height=32,
                      font=_FONT_SMALL,
                      command=lambda: __import__("webbrowser").open(url)).pack(
            anchor="w", pady=(8, 0))

        # Beállítások
        cfg_sec = _section(self, "Stream beállítások")
        cfg_sec.master.pack(fill="x", padx=16, pady=(0, 12))
        cfg = (
            f"Host:         {settings.STREAM_HOST}\n"
            f"Port:         {settings.STREAM_PORT}\n"
            f"Kodek:        {settings.STREAM_CODEC}\n"
            f"STUN szerver: {settings.STREAM_STUN_SERVER or '(nincs, LAN mód)'}\n"
            f"Bitrate:      {settings.STREAM_VIDEO_BITRATE // 1000} kbps"
        )
        ctk.CTkLabel(cfg_sec, text=cfg, font=_FONT_MONO,
                     text_color=_CLR_MUTED, justify="left").pack(anchor="w")

        ctk.CTkLabel(self,
                     text="A stream szerver elindításához futtasd a main.py-t.",
                     font=_FONT_SMALL, text_color=_CLR_MUTED).pack(pady=8)

    def _start_server(self):
        self._server_status.configure(
            text="A stream szerver a main.py-ból indítható (python main.py --dry-run)",
            text_color=_CLR_ORANGE)

    def _stop_server(self):
        pass

    def cleanup(self):
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  Főablak
# ══════════════════════════════════════════════════════════════════════════════

_COMPONENTS = [
    ("Kamera",     "📷  Kamera",    CameraPanel),
    ("Vision",     "👁  Vision",    VisionPanel),
    ("IR Adó",     "📡  IR Adó",    IRPanel),
    ("LoRa",       "📻  LoRa",      LoRaPanel),
    ("OLED",       "🖥  OLED",      OLEDPanel),
    ("Motorok",    "⚙  Motorok",   MotorPanel),
    ("Stream",     "🌐  Stream",    StreamPanel),
]


class TestGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"{settings.ROBOT_NAME}  —  TEST MODE")
        self.geometry("1280x780")
        self.minsize(900, 600)
        self._current_panel: Optional[_Panel] = None
        self._active_btn: Optional[ctk.CTkButton] = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Alapértelmezetten a Vision panelt mutatjuk
        self._show_panel(VisionPanel, self._sidebar_btns[1])

    def _build_ui(self):
        # ── Fejléc ────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, height=56, corner_radius=0,
                               fg_color=_CLR_SURFACE2)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        ctk.CTkLabel(header, text=settings.ROBOT_NAME,
                     font=("Segoe UI", 18, "bold"),
                     text_color=_CLR_ACCENT).pack(side="left", padx=20)

        badge = ctk.CTkLabel(header, text=" TEST MODE ",
                              font=_FONT_BADGE, text_color="#000",
                              fg_color=_CLR_ORANGE, corner_radius=6)
        badge.pack(side="left", padx=4)

        role_color = _CLR_GREEN if settings.ROBOT_ROLE == "PACMAN" else _CLR_PURPLE
        role_lbl = ctk.CTkLabel(header,
                                 text=f"  {settings.ROBOT_ROLE}  ",
                                 font=_FONT_BADGE, text_color="#000",
                                 fg_color=role_color, corner_radius=6)
        role_lbl.pack(side="left", padx=4)

        ctk.CTkLabel(header, text=f"DRY-RUN  |  {settings.ROBOT_NAME}",
                     font=_FONT_SMALL, text_color=_CLR_MUTED).pack(side="right", padx=20)

        # ── Tartalom ───────────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=10)

        # Oldalsáv
        sidebar = ctk.CTkFrame(body, width=190, fg_color=_CLR_SURFACE2, corner_radius=12)
        sidebar.pack(fill="y", side="left", padx=(0, 8))
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="KOMPONENSEK",
                     font=("Segoe UI", 10, "bold"),
                     text_color=_CLR_MUTED).pack(pady=(14, 6), padx=12, anchor="w")

        self._sidebar_btns: list[ctk.CTkButton] = []
        for _, label, panel_cls in _COMPONENTS:
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w",
                font=_FONT_LABEL, height=40,
                fg_color="transparent",
                text_color=_CLR_MUTED,
                hover_color=_CLR_SURFACE,
                corner_radius=8,
                command=lambda cls=panel_cls, b=None: self._show_panel(cls, b),
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._sidebar_btns.append(btn)

        # Kötés — a late-binding lambda miatt utólag rendeljük hozzá a gombokat
        for i, (_, _, panel_cls) in enumerate(_COMPONENTS):
            b = self._sidebar_btns[i]
            b.configure(command=lambda cls=panel_cls, btn=b: self._show_panel(cls, btn))

        # Tartalom terület
        self._content = ctk.CTkFrame(body, fg_color="transparent")
        self._content.pack(fill="both", expand=True)

    def _show_panel(self, panel_cls, btn: Optional[ctk.CTkButton] = None):
        # Aktív gomb stílus
        if self._active_btn:
            self._active_btn.configure(fg_color="transparent", text_color=_CLR_MUTED)
        if btn:
            btn.configure(fg_color=_CLR_SURFACE, text_color="white")
            self._active_btn = btn

        # Régi panel takarítása
        if self._current_panel:
            self._current_panel.cleanup()
            self._current_panel.destroy()

        # Új panel
        panel = panel_cls(self._content)
        panel.pack(fill="both", expand=True)
        self._current_panel = panel

    def _on_close(self):
        if self._current_panel:
            self._current_panel.cleanup()
        self.destroy()


# ── Belépési pont ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = TestGUI()
    app.mainloop()
