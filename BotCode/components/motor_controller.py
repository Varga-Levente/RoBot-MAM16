"""
Motor vezérlő modul — Mecanum kerekek.

DRV8833 dual H-bridge driver, 4 db N20 Mecanum motorhoz.

Mecanum keréksebességek (standard 45° roller elrendezés):
  FL = linear + lateral + angular
  FR = linear - lateral - angular
  RL = linear - lateral + angular
  RR = linear + lateral - angular

Parancs formátum (LoRa-n érkező JSON):
  {"cmd": "move",  "linear": .., "angular": .., "lateral": .., "left_y": ..}
  {"cmd": "jump",  "direction": "forward"|"backward"|"left"|"right"}
  {"cmd": "stop"}
  {"cmd": "motor", "id": <0-3>, "speed": <-1.0..1.0>}
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

import settings

log = logging.getLogger("motor")


@dataclass
class _Motor:
    in1_pin: int
    in2_pin: int
    pwm1: Optional[object] = None
    pwm2: Optional[object] = None
    current_speed: float = 0.0


class MotorController:
    def __init__(self):
        self._motors: List[_Motor] = [
            _Motor(settings.MOTOR_FL_IN1, settings.MOTOR_FL_IN2),  # 0 = FL
            _Motor(settings.MOTOR_FR_IN1, settings.MOTOR_FR_IN2),  # 1 = FR
            _Motor(settings.MOTOR_RL_IN1, settings.MOTOR_RL_IN2),  # 2 = RL
            _Motor(settings.MOTOR_RR_IN1, settings.MOTOR_RR_IN2),  # 3 = RR
        ]
        self._initialized = False

    def _init_hardware(self) -> bool:
        if settings.DRY_RUN:
            log.info("[DRY-RUN] Motor vezérlő szimulálva (Mecanum)")
            self._initialized = True
            return True
        try:
            import Jetson.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            for m in self._motors:
                GPIO.setup(m.in1_pin, GPIO.OUT)
                GPIO.setup(m.in2_pin, GPIO.OUT)
                m.pwm1 = GPIO.PWM(m.in1_pin, settings.MOTOR_PWM_FREQ_HZ)
                m.pwm2 = GPIO.PWM(m.in2_pin, settings.MOTOR_PWM_FREQ_HZ)
                m.pwm1.start(0)
                m.pwm2.start(0)
            self._initialized = True
            log.info("Motor vezérlő inicializálva (4 Mecanum kerék)")
            return True
        except Exception as e:
            log.error(f"Motor inicializálási hiba: {e}")
            return False

    # ── Egyedi motor ─────────────────────────────────────────────────────────

    def set_motor(self, motor_id: int, speed: float) -> None:
        if motor_id < 0 or motor_id >= len(self._motors):
            return
        speed = max(-settings.MOTOR_MAX_SPEED, min(settings.MOTOR_MAX_SPEED, speed))
        m = self._motors[motor_id]
        m.current_speed = speed
        duty = abs(speed) * 100.0

        if settings.DRY_RUN:
            log.debug(f"[DRY-RUN] Motor[{motor_id}] speed={speed:.3f}")
            return
        if not self._initialized:
            return

        if speed > 0:
            m.pwm1.ChangeDutyCycle(duty)
            m.pwm2.ChangeDutyCycle(0)
        elif speed < 0:
            m.pwm1.ChangeDutyCycle(0)
            m.pwm2.ChangeDutyCycle(duty)
        else:
            m.pwm1.ChangeDutyCycle(0)
            m.pwm2.ChangeDutyCycle(0)

    # ── Mecanum vezérlés ──────────────────────────────────────────────────────

    def set_mecanum(self, linear: float, angular: float, lateral: float) -> None:
        """Mecanum keréksebességek beállítása.

        linear:  -1..1  (pozitív = előre)
        angular: -1..1  (pozitív = jobbra kanyar)
        lateral: -1..1  (pozitív = jobbra söpörve)
        """
        linear  = max(-1.0, min(1.0, linear))
        angular = max(-1.0, min(1.0, angular))
        lateral = max(-1.0, min(1.0, lateral))

        fl = linear + lateral + angular
        fr = linear - lateral - angular
        rl = linear - lateral + angular
        rr = linear + lateral - angular

        mx = max(abs(fl), abs(fr), abs(rl), abs(rr), 1.0)
        fl /= mx;  fr /= mx;  rl /= mx;  rr /= mx

        self.set_motor(0, fl)
        self.set_motor(1, fr)
        self.set_motor(2, rl)
        self.set_motor(3, rr)

    # ── Visszafelé kompatibilis alias ─────────────────────────────────────────

    def set_velocity(self, linear: float, angular: float) -> None:
        self.set_mecanum(linear, angular, 0.0)

    # ── Vészleállás ───────────────────────────────────────────────────────────

    def emergency_stop(self) -> None:
        log.warning("VÉSZLEÁLLÁS — minden motor megállítva")
        for i in range(len(self._motors)):
            self.set_motor(i, 0.0)

    def cleanup(self) -> None:
        if self._initialized and not settings.DRY_RUN:
            self.emergency_stop()
            try:
                import Jetson.GPIO as GPIO
                for m in self._motors:
                    if m.pwm1:
                        m.pwm1.stop()
                    if m.pwm2:
                        m.pwm2.stop()
                GPIO.cleanup()
            except Exception:
                pass

    # ── Parancs hurok ─────────────────────────────────────────────────────────

    async def command_loop(self, command_queue: asyncio.Queue, state) -> None:
        if not self._init_hardware():
            log.warning("Motor vezérlő hardver nem elérhető — szimulált mód")
            while True:
                try:
                    cmd = await asyncio.wait_for(command_queue.get(), timeout=1.0)
                    log.debug(f"[NO-HW] Motor parancs: {cmd}")
                except asyncio.TimeoutError:
                    pass
            return

        log.info("Motor parancs hurok elindult (Mecanum)")
        while True:
            try:
                cmd = await asyncio.wait_for(command_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                # Ha 0.5s-ig nem érkezett parancs → LoRa megszakadt → megállás
                self.emergency_stop()
                continue

            action = cmd.get("cmd", "")

            if action == "move":
                linear  = float(cmd.get("linear",  0.0))
                angular = float(cmd.get("angular", 0.0))
                lateral = float(cmd.get("lateral", 0.0))
                left_y  = float(cmd.get("left_y",  0.0))
                # left_y (bal stick Y) hozzáadódik a lineárishoz: negatív = előre
                combined_linear = max(-1.0, min(1.0, linear - left_y))
                self.set_mecanum(combined_linear, angular, lateral)

            elif action == "jump":
                direction = cmd.get("direction", "forward")
                duration  = float(cmd.get("duration", settings.MOTOR_JUMP_DURATION))
                duration  = max(0.05, min(5.0, duration))
                _jmap = {
                    "forward":  ( 1.0, 0.0,  0.0),
                    "backward": (-1.0, 0.0,  0.0),
                    "left":     ( 0.0, 0.0, -1.0),
                    "right":    ( 0.0, 0.0,  1.0),
                }
                lin, ang, lat = _jmap.get(direction, (0.0, 0.0, 0.0))
                power = settings.MOTOR_JUMP_POWER
                log.info(f"Ugrás: {direction} (power={power}, duration={duration}s)")
                self.set_mecanum(lin * power, ang, lat * power)
                await asyncio.sleep(duration)
                self.emergency_stop()

            elif action == "stop":
                self.emergency_stop()

            elif action == "motor":
                mid   = int(cmd.get("id",    0))
                speed = float(cmd.get("speed", 0.0))
                self.set_motor(mid, speed)

            else:
                log.warning(f"Ismeretlen motor parancs: {action}")

            state.motor_speeds = [m.current_speed for m in self._motors]


# ── Önálló teszt ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    print("Mecanum motor billentyűzetes teszt")
    print("W=előre  S=hátra  A=bal kanyar  D=jobb kanyar")
    print("Q=Mecanum bal  E=Mecanum jobb  X=stop  ESC=kilépés")

    ctrl = MotorController()
    if not ctrl._init_hardware():
        print("Motor nem inicializálható!")
        sys.exit(1)

    speed = 0.5
    try:
        while True:
            key = input("> ").strip().lower()
            if   key == "w":  ctrl.set_mecanum( speed, 0.0,  0.0)
            elif key == "s":  ctrl.set_mecanum(-speed, 0.0,  0.0)
            elif key == "a":  ctrl.set_mecanum(0.0,  -speed, 0.0)
            elif key == "d":  ctrl.set_mecanum(0.0,   speed, 0.0)
            elif key == "q":  ctrl.set_mecanum(0.0,   0.0,  -speed)
            elif key == "e":  ctrl.set_mecanum(0.0,   0.0,   speed)
            elif key == "x":  ctrl.emergency_stop()
            elif key in ("esc", "quit"): break
            else: print("W/S/A/D/Q/E/X/ESC")
    finally:
        ctrl.cleanup()
        print("Motor lezárva")
