"""
Infra LED vezérlő modul.

A kapu kódot (3 hex karakter, pl. „CA6") soros UART kommunikációval küldi el.
A 38kHz vivőfrekvenciát külső hardver (555 IC vagy GPIO PWM) biztosítja;
ez a modul csak a soros adatjelért felelős.

Verseny korlát: maximum 2 adás / másodperc (token bucket alapú rate limiter).

Adatformátum (verseny spec):
  - 1200 baud
  - 8 adatbit
  - Paritás nélkül
  - 1 stop bit
"""

import asyncio
import logging
import time
from typing import Optional

import settings

log = logging.getLogger("ir")


class IRTransmitter:
    def __init__(self):
        self._serial = None
        self._last_tx_times: list[float] = []  # token bucket: utolsó adások időpontjai

    def _open_serial(self) -> None:
        if settings.DRY_RUN:
            return
        try:
            import serial
            self._serial = serial.Serial(
                port     = settings.IR_UART_PORT,
                baudrate = settings.IR_BAUD_RATE,
                bytesize = settings.IR_DATA_BITS,
                parity   = settings.IR_PARITY,
                stopbits = settings.IR_STOP_BITS,
                timeout  = settings.IR_TIMEOUT_SEC,
            )
            log.info(f"IR UART megnyitva: {settings.IR_UART_PORT} @ {settings.IR_BAUD_RATE} baud")
        except Exception as e:
            log.error(f"IR UART megnyitási hiba: {e}")
            self._serial = None

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

        if settings.DRY_RUN or self._serial is None:
            log.info(f"[DRY-RUN] IR küldés: {code}")
            return True

        try:
            # 3 hex karaktert 3 bájtként küldjük el (pl. "CA6" → 0xCA, 0x0A, 0x06? )
            # Verseny spec: a hex string karaktereit ASCII-ként küldjük + '\n' lezáró
            data = (code + "\n").encode("ascii")
            self._serial.write(data)
            self._serial.flush()
            log.info(f"IR küldve: {code}")
            return True
        except Exception as e:
            log.error(f"IR küldési hiba: {e}")
            return False

    async def transmit_loop(self, gate_code_queue: asyncio.Queue, state) -> None:
        """Főhurok: vár a gate_code_queue-ra és elküldi a kódot IR-en."""
        self._open_serial()
        log.info("IR adó hurok elindult")
        while True:
            code: str = await gate_code_queue.get()
            state.ir_transmitting = True
            success = await asyncio.get_event_loop().run_in_executor(None, self.transmit, code)
            if success:
                # Rövid ideig tartjuk aktívan az IR státuszt (UI visszajelzéshez)
                await asyncio.sleep(0.5)
            state.ir_transmitting = False

    def close(self) -> None:
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
