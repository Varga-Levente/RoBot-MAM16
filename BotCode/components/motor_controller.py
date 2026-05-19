"""
Motor vezérlő modul.

DRV8833 dual H-bridge driver, 4 db N20 motorhoz.
Differenciálhajtás modell: linear + angular bemenetek alapján számolja
a 4 keréksebességet (2 bal + 2 jobb pár).

Parancs formátum (LoRa-n érkező JSON):
  {"cmd": "move",  "linear": <-1.0..1.0>, "angular": <-1.0..1.0>}
  {"cmd": "stop"}
  {"cmd": "motor", "id": <0-3>, "speed": <-1.0..1.0>}
"""

import asyncio
import logging
import time
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
            _Motor(settings.MOTOR_FL_IN1, settings.MOTOR_FL_IN2),
            _Motor(settings.MOTOR_FR_IN1, settings.MOTOR_FR_IN2),
            _Motor(settings.MOTOR_RL_IN1, settings.MOTOR_RL_IN2),
            _Motor(settings.MOTOR_RR_IN1, settings.MOTOR_RR_IN2),
        ]
        self._initialized = False

    def _init_hardware(self) -> bool:
        if settings.DRY_RUN:
            log.info("[DRY-RUN] Motor vezérlő szimulálva")
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
            log.info("Motor vezérlő inicializálva (4 motor)")
            return True
        except Exception as e:
            log.error(f"Motor inicializálási hiba: {e}")
            return False

    def set_motor(self, motor_id: int, speed: float) -> None:
        """
        Egyedi motor beállítása.
        speed: -1.0 (teljes visszafelé) .. 0.0 (stop) .. 1.0 (teljes előre)
        """
        if motor_id < 0 or motor_id >= len(self._motors):
            return

        speed = max(-settings.MOTOR_MAX_SPEED, min(settings.MOTOR_MAX_SPEED, speed))
        m = self._motors[motor_id]
        m.current_speed = speed

        duty = abs(speed) * 100.0

        if settings.DRY_RUN:
            log.debug(f"[DRY-RUN] Motor[{motor_id}] speed={speed:.2f}")
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

    def set_velocity(self, linear: float, angular: float) -> None:
        """
        Differenciálhajtás: linear (-1..1) és angular (-1..1) bemenetek alapján
        kiszámítja és beállítja a bal/jobb oldali sebességeket.
        """
        linear  = max(-1.0, min(1.0, linear))
        angular = max(-1.0, min(1.0, angular))

        left  = linear + angular
        right = linear - angular

        # Normalizálás ha bármelyik meghaladja a maximumot
        max_val = max(abs(left), abs(right), 1.0)
        left  /= max_val
        right /= max_val

        left  = max(-settings.MOTOR_MAX_SPEED, min(settings.MOTOR_MAX_SPEED, left))
        right = max(-settings.MOTOR_MAX_SPEED, min(settings.MOTOR_MAX_SPEED, right))

        # Bal oldal: motor 0 (FL) és motor 2 (RL)
        self.set_motor(0, left)
        self.set_motor(2, left)
        # Jobb oldal: motor 1 (FR) és motor 3 (RR)
        self.set_motor(1, right)
        self.set_motor(3, right)

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

    async def command_loop(self, command_queue: asyncio.Queue, state) -> None:
        """Főhurok: LoRa parancsokat fogad és végrehajtja."""
        if not self._init_hardware():
            log.warning("Motor vezérlő hardver nem elérhető — parancsok figyelve, GPIO nélkül")
            while True:
                try:
                    cmd = await asyncio.wait_for(command_queue.get(), timeout=1.0)
                    log.debug(f"[NO-HW] Motor parancs figyelve: {cmd}")
                except asyncio.TimeoutError:
                    pass

        log.info("Motor parancs hurok elindult")
        while True:
            try:
                cmd = await asyncio.wait_for(command_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            action = cmd.get("cmd", "")
            if action == "move":
                linear  = float(cmd.get("linear",  0.0))
                angular = float(cmd.get("angular", 0.0))
                self.set_velocity(linear, angular)
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

    print("Motor billentyűzetes teszt (hardver szükséges)")
    print("W=előre  S=hátra  A=bal  D=jobb  X=stop  Q=kilépés")

    ctrl = MotorController()
    if not ctrl._init_hardware():
        print("Motor nem inicializálható!")
        sys.exit(1)

    speed = 0.5
    try:
        while True:
            key = input("> ").strip().lower()
            if   key == "w": ctrl.set_velocity( speed,  0.0)
            elif key == "s": ctrl.set_velocity(-speed,  0.0)
            elif key == "a": ctrl.set_velocity(0.0, -speed)
            elif key == "d": ctrl.set_velocity(0.0,  speed)
            elif key == "x": ctrl.emergency_stop()
            elif key == "q": break
            else: print("Ismeretlen billentyű")
    finally:
        ctrl.cleanup()
        print("Motor lezárva")
