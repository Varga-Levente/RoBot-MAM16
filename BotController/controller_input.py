"""
Xbox One USB gamepad olvasó (evdev alapú, Linux).

Tengely kiosztás:
  ABS_X  (0) — bal joystick X: -32768..32767 → angular (-1=bal, +1=jobb)
  ABS_Z  (2) — LT trigger: 0..max → hátramenet (linear negatív)
  ABS_RZ (5) — RT trigger: 0..max → előremenet (linear pozitív)

A read_state() (linear, angular) tuple-t ad vissza -1..1 között,
deadzone és speed_limit alkalmazásával.
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


class GamepadReader:
    _AXIS_X  = 0   # ABS_X  — bal stick X (angular)
    _AXIS_LT = 2   # ABS_Z  — LT trigger (reverse)
    _AXIS_RT = 5   # ABS_RZ — RT trigger (forward)

    def __init__(self):
        self._dev   = None
        self._state = {self._AXIS_X: 0, self._AXIS_LT: 0, self._AXIS_RT: 0}
        self._ranges: dict[int, tuple[int, int]] = {}

    # ── Eszköz keresés / megnyitás ──────────────────────────────────────────

    def find_xbox_device(self) -> str | None:
        if not _EVDEV_OK:
            return None
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                name = dev.name.lower()
                dev.close()
                if "xbox" in name or "microsoft" in name or "x-box" in name:
                    return path
            except Exception:
                pass
        return None

    def open(self, path: str | None = None) -> bool:
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
        caps = self._dev.capabilities()
        abs_caps = caps.get(ecodes.EV_ABS, [])
        for code, info in abs_caps:
            if code in (self._AXIS_X, self._AXIS_LT, self._AXIS_RT):
                self._ranges[code] = (info.min, info.max)
                log.debug(f"Tengely {code}: min={info.min} max={info.max}")

    # ── Olvasás ─────────────────────────────────────────────────────────────

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

    def poll(self) -> None:
        """Nem blokkoló esemény polling — frissíti a belső állapotot."""
        if not _EVDEV_OK or not self._dev:
            return
        try:
            for event in self._dev.read():
                if event.type == ecodes.EV_ABS and event.code in self._state:
                    self._state[event.code] = event.value
        except BlockingIOError:
            pass  # nincs új esemény

    def read_state(self) -> tuple[float, float]:
        """Visszaadja (linear, angular) -1..1 között.

        linear:  RT - LT   (pozitív = előre, negatív = hátra)
        angular: bal stick X (negatív = bal, pozitív = jobb)
        Raises OSError ha a kontroller lecsatlakozott.
        """
        self.poll()

        dz    = settings.CTRL_DEADZONE
        limit = settings.CTRL_SPEED_LIMIT

        rt      = self._norm_axis(self._AXIS_RT, self._state[self._AXIS_RT], signed=False)
        lt      = self._norm_axis(self._AXIS_LT, self._state[self._AXIS_LT], signed=False)
        steer   = self._norm_axis(self._AXIS_X,  self._state[self._AXIS_X],  signed=True)

        linear  = self._deadzone(rt - lt, dz) * limit
        angular = self._deadzone(steer,   dz) * limit

        return linear, angular

    def close(self) -> None:
        if self._dev:
            try:
                self._dev.ungrab()
                self._dev.close()
            except Exception:
                pass
            self._dev = None
