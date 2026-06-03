"""
Infra LED vezérlő modul.

Három adási mód (settings.IR_MODE):
  DIRECT_UART  — 1200 baud UART, külső hardver biztosítja a 38kHz vivőt (555 IC / HW PWM)
  CARRIER_UART — 38400 baud UART, szoftver carrier trick: minden 1200 baud bit 4 byte-ra
                 terjesztve ki; 0xAA (10101010) = ~38.4kHz burst, 0x00 = csend
  HW_PWM       — 1200 baud UART + Jetson Nano sysfs PWM 38kHz vivő IR_PWM_PIN-en

Verseny korlát: maximum 2 adás / másodperc (token bucket alapú rate limiter).

Verseny adatformátum (spec):
  - 1200 baud (logikai szint), 8N1
  - Payload: ASCII hex karakterek + '\\n' lezáró
"""

import asyncio
import logging
import time
from typing import List, Optional

import settings

log = logging.getLogger("ir")


class IRTransmitter:
    def __init__(self):
        self._serial = None
        self._last_tx_times: List[float] = []  # token bucket: utolsó adások időpontjai

    def _open_serial(self) -> None:
        if settings.DRY_RUN:
            return
        try:
            import serial
            baud = (settings.IR_CARRIER_BAUD
                    if settings.IR_MODE == "CARRIER_UART"
                    else settings.IR_BAUD_RATE)
            self._serial = serial.Serial(
                port     = settings.IR_UART_PORT,
                baudrate = baud,
                bytesize = settings.IR_DATA_BITS,
                parity   = settings.IR_PARITY,
                stopbits = settings.IR_STOP_BITS,
                timeout  = settings.IR_TIMEOUT_SEC,
            )
            log.info(f"IR UART megnyitva: {settings.IR_UART_PORT} @ {baud} baud [{settings.IR_MODE}]")
            if settings.IR_MODE == "HW_PWM" and settings.IR_PWM_PIN > 0:
                self._start_hw_pwm()
        except Exception as e:
            log.error(f"IR UART megnyitási hiba: {e}")
            self._serial = None

    def _start_hw_pwm(self) -> None:
        """38kHz PWM indítása Jetson Nano sysfs PWM-en (HW_PWM mód)."""
        try:
            import Jetson.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(settings.IR_PWM_PIN, GPIO.OUT)
            self._pwm = GPIO.PWM(settings.IR_PWM_PIN, 38000)
            self._pwm.start(50)  # 50% duty cycle
            log.info(f"IR HW PWM elindítva: GPIO{settings.IR_PWM_PIN} @ 38kHz")
        except Exception as e:
            log.warning(f"IR HW PWM nem érhető el: {e}")

    def _encode_carrier(self, code: str) -> bytes:
        """CARRIER_UART: minden 1200 baud UART bitet IR_BYTES_PER_BIT byte-ra terjeszt ki.

        Egy 1200 baud 8N1 UART frame 10 bit: [START=0] + 8 adatbit (LSB first) + [STOP=1]
        Minden bitből IR_BYTES_PER_BIT darab byte lesz:
          mark (1) → IR_CARRIER_BYTE  (~38.4kHz burst)
          space (0) → IR_SILENCE_BYTE (csend)
        """
        n = settings.IR_BYTES_PER_BIT
        carrier = bytes([settings.IR_CARRIER_BYTE] * n)
        silence = bytes([settings.IR_SILENCE_BYTE] * n)
        result  = bytearray()
        for byte_val in (code + "\n").encode("ascii"):
            bits = [0]  # start bit (space)
            for i in range(8):
                bits.append((byte_val >> i) & 1)
            bits.append(1)  # stop bit (mark)
            for bit in bits:
                result += carrier if bit else silence
        return bytes(result)

    def _can_transmit(self) -> bool:
        """Token bucket: ellenőrzi, hogy az IR_MAX_TX_PER_SEC korlát teljesül-e."""
        now = time.monotonic()
        # Csak az utolsó 1 másodpercen belüli adásokat tartjuk
        self._last_tx_times = [t for t in self._last_tx_times if now - t < 1.0]
        return len(self._last_tx_times) < settings.IR_MAX_TX_PER_SEC

    def transmit(self, code: str) -> bool:
        """
        Szinkron adás (belső használatra).
        Visszatér True-val ha sikeresen elküldve, False ha rate limit vagy hiba.
        """
        if not self._can_transmit():
            log.debug(f"IR rate limit, kód eldobva: {code}")
            return False

        self._last_tx_times.append(time.monotonic())

        if settings.DRY_RUN:
            log.info(f"[DRY-RUN] IR küldés: {code} [{settings.IR_MODE}]")
            return True
        if self._serial is None:
            log.warning(f"IR UART nem elérhető, küldés kihagyva: {code}")
            return False

        try:
            if settings.IR_MODE == "CARRIER_UART":
                data = self._encode_carrier(code)
                log.debug(f"IR CARRIER_UART: {len(data)} byte @ {settings.IR_CARRIER_BAUD} baud")
            else:
                data = (code + "\n").encode("ascii")
            self._serial.write(data)
            self._serial.flush()
            log.info(f"IR küldve: {code} [{settings.IR_MODE}]")
            return True
        except Exception as e:
            log.error(f"IR küldési hiba: {e}")
            return False

    async def transmit_loop(self, gate_code_queue: asyncio.Queue, state) -> None:
        """Főhurok: vár a gate_code_queue-ra és elküldi a kódot IR-en."""
        if not getattr(settings, "IR_ENABLED", True):
            log.info("IR adó letiltva (IR_ENABLED=False) — hurok kihagyva")
            while True:
                await gate_code_queue.get()  # queue-t ürítjük, hogy ne telítődjön
            return
        self._open_serial()
        log.info("IR adó hurok elindult")
        while True:
            code: str = await gate_code_queue.get()
            state.ir_transmitting = True
            success = await asyncio.get_event_loop().run_in_executor(None, self.transmit, code)
            if success:
                state.ir_last_code = code
                state.ir_tx_count += 1
                # Rövid ideig tartjuk aktívan az IR státuszt (UI visszajelzéshez)
                await asyncio.sleep(0.5)
            state.ir_transmitting = False

    def close(self) -> None:
        if hasattr(self, "_pwm"):
            try:
                self._pwm.stop()
            except Exception:
                pass
        if self._serial and self._serial.is_open:
            self._serial.close()


# ── Önálló teszt ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="IR adó teszt")
    parser.add_argument("--code", required=True, help="Küldendő hex kód (pl. CA6)")
    parser.add_argument("--count", type=int, default=1, help="Hányszor küldje el")
    args = parser.parse_args()

    tx = IRTransmitter()
    tx._open_serial()
    for i in range(args.count):
        ok = tx.transmit(args.code)
        print(f"[{i+1}/{args.count}] IR küldés {'OK' if ok else 'KIHAGYVA (rate limit)'}: {args.code}")
        time.sleep(0.6)  # 2/sec limit miatt
    tx.close()
