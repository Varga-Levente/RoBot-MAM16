"""
Xbox One USB gamepad olvasó — Mecanum vezérlés (evdev alapú, Linux).

Tengely kiosztás:
  ABS_X  (0) — bal stick X   → lateral (-1=bal, +1=jobb Mecanum söpörve)
  ABS_Y  (1) — bal stick Y   → left_y  (-1=előre, +1=hátra átlós komponens)
  ABS_Z  (2) — LT trigger    → hátrament (linear-)
  ABS_RX (3) — jobb stick X  → angular (kanyarodás)
  ABS_RZ (5) — RT trigger    → előremenet (linear+)

Gombok:
  BTN_SOUTH (304) — A → hátra ugrás
  BTN_EAST  (305) — B → jobbra ugrás (Mecanum oldalra)
  BTN_WEST  (307) — X → balra ugrás  (Mecanum oldalra)
  BTN_NORTH (308) — Y → előre ugrás

read_state() → (linear, angular, lateral, left_y, jump_dir)
"""

import logging
import settings

log = logging.getLogger("ctrl")

try:
    import evdev
    from evdev import ecodes
    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False
    log.warning("evdev nem elérhető — szimulált gamepad mód")

# ── Gomb kódok ────────────────────────────────────────────────────────────────
_BTN_A = 304
_BTN_B = 305
_BTN_X = 307
_BTN_Y = 308

_JUMP_MAP = {
    _BTN_Y: "forward",
    _BTN_A: "backward",
    _BTN_X: "left",
    _BTN_B: "right",
}


class GamepadReader:
    _AXIS_LX = 0   # bal stick X  → lateral
    _AXIS_LY = 1   # bal stick Y  → left_y
    _AXIS_LT = 2   # LT trigger   → reverse
    _AXIS_RX = 3   # jobb stick X → angular
    _AXIS_RT = 5   # RT trigger   → forward

    def __init__(self):
        self._dev   = None
        self._state = {
            self._AXIS_LX: 0, self._AXIS_LY: 0,
            self._AXIS_LT: 0, self._AXIS_RX: 0, self._AXIS_RT: 0,
        }
        self._btn_state: dict = {k: False for k in _JUMP_MAP}
        self._pending_jump    = None
        self._ranges: dict    = {}

        self.raw_lt:  float = 0.0
        self.raw_rt:  float = 0.0
        self.raw_lx:  float = 0.0
        self.raw_ly:  float = 0.0
        self.raw_rx:  float = 0.0
        self.btn_y:   bool  = False
        self.btn_a:   bool  = False
        self.btn_x:   bool  = False
        self.btn_b:   bool  = False

    # ── Eszköz keresés ────────────────────────────────────────────────────────

    def find_xbox_device(self):
        if not _EVDEV_OK:
            return None
        for path in evdev.list_devices():
            try:
                dev  = evdev.InputDevice(path)
                name = dev.name.lower()
                dev.close()
                if "xbox" in name or "microsoft" in name or "x-box" in name:
                    return path
            except Exception:
                pass
        return None

    def open(self, path=None) -> bool:
        if not _EVDEV_OK:
            log.info("[SIM] GamepadReader szimulált módban fut")
            return True
        target = path or settings.CTRL_GAMEPAD_DEVICE or self.find_xbox_device()
        if not target:
            log.warning("Xbox kontroller nem található — ellenőrizd az USB kapcsolatot")
            return False
        try:
            self._dev = evdev.InputDevice(target)
            self._dev.grab()
            self._detect_ranges()
            log.info(f"Gamepad megnyitva: {self._dev.name} ({target})")
            return True
        except Exception as e:
            log.error(f"Gamepad megnyitási hiba ({target}): {e}")
            self._dev = None
            return False

    def _detect_ranges(self) -> None:
        if not self._dev:
            return
        for code, info in self._dev.capabilities().get(ecodes.EV_ABS, []):
            if code in self._state:
                self._ranges[code] = (info.min, info.max)
                log.debug(f"Tengely {code}: min={info.min} max={info.max}")

    # ── Normalizálás ──────────────────────────────────────────────────────────

    def _norm_axis(self, code: int, val: int, signed: bool) -> float:
        lo, hi = self._ranges.get(code, (-32768, 32767) if signed else (0, 255))
        if signed:
            n = val / max(abs(lo), abs(hi))
        else:
            n = val / hi if hi > 0 else 0.0
        return max(-1.0, min(1.0, n))

    @staticmethod
    def _deadzone(val: float, dz: float) -> float:
        if abs(val) < dz:
            return 0.0
        sign = 1.0 if val > 0 else -1.0
        return sign * (abs(val) - dz) / (1.0 - dz)

    # ── Polling ───────────────────────────────────────────────────────────────

    def poll(self) -> None:
        if not _EVDEV_OK or not self._dev:
            return
        try:
            for event in self._dev.read():
                if event.type == ecodes.EV_ABS and event.code in self._state:
                    self._state[event.code] = event.value
                elif event.type == ecodes.EV_KEY and event.code in _JUMP_MAP:
                    prev = self._btn_state[event.code]
                    now  = bool(event.value)
                    self._btn_state[event.code] = now
                    if now and not prev:          # felfutó él = ugrás trigger
                        self._pending_jump = _JUMP_MAP[event.code]
        except BlockingIOError:
            pass

    # ── Állapot olvasás ───────────────────────────────────────────────────────

    def read_state(self):
        """Visszaad (linear, angular, lateral, left_y, jump_dir).

        linear:   RT-LT  (-1..1), pozitív=előre
        angular:  jobb stick X (-1..1), pozitív=jobbra kanyar
        lateral:  bal stick X (-1..1), pozitív=Mecanum jobbra söpörve
        left_y:   bal stick Y (-1..1), negatív=előre (átlós komponens)
        jump_dir: None | "forward" | "backward" | "left" | "right"
        Raises OSError ha a kontroller lecsatlakozott.
        """
        self.poll()

        dz    = settings.CTRL_DEADZONE
        limit = settings.CTRL_SPEED_LIMIT

        rt = self._norm_axis(self._AXIS_RT, self._state[self._AXIS_RT], signed=False)
        lt = self._norm_axis(self._AXIS_LT, self._state[self._AXIS_LT], signed=False)
        lx = self._norm_axis(self._AXIS_LX, self._state[self._AXIS_LX], signed=True)
        ly = self._norm_axis(self._AXIS_LY, self._state[self._AXIS_LY], signed=True)
        rx = self._norm_axis(self._AXIS_RX, self._state[self._AXIS_RX], signed=True)

        self.raw_rt = rt
        self.raw_lt = lt
        self.raw_lx = lx
        self.raw_ly = ly
        self.raw_rx = rx
        self.btn_y  = self._btn_state.get(_BTN_Y, False)
        self.btn_a  = self._btn_state.get(_BTN_A, False)
        self.btn_x  = self._btn_state.get(_BTN_X, False)
        self.btn_b  = self._btn_state.get(_BTN_B, False)

        linear  = self._deadzone(rt - lt, dz) * limit
        angular = self._deadzone(rx,       dz) * limit
        lateral = self._deadzone(lx,       dz) * limit
        left_y  = self._deadzone(ly,       dz) * limit  # negatív=előre

        jump_dir           = self._pending_jump
        self._pending_jump = None

        return linear, angular, lateral, left_y, jump_dir

    # ── Kompatibilitás ────────────────────────────────────────────────────────

    @property
    def raw_steer(self) -> float:
        return self.raw_rx

    def close(self) -> None:
        if self._dev:
            try:
                self._dev.ungrab()
                self._dev.close()
            except Exception:
                pass
            self._dev = None
