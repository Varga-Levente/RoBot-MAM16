"""
LoRa kommunikációs modul — EBYTE E22-900T22D-V2 UART alapú.

Keret formátum (alkalmazás réteg, packet határokon átnyúló adatokhoz):
  [0xAA][0x55][len_hi][len_lo][payload]

Titkosítás (változatlan):
  AES-128 CTR mód + HMAC-SHA256 hitelesítés
  Csomag: [device_id:4B][nonce:8B][ciphertext][HMAC:32B]

Handshake (változatlan):
  Robot → 32 bájt nonce → Controller
  Controller → HMAC-SHA256(nonce, hmac_key) → Robot
  Robot → encrypted {"status":"ok"} → Controller

GPIO (Jetson.GPIO, BCM számozás):
  LORA_M0_PIN  = kimenet, LOW normál módhoz
  LORA_M1_PIN  = kimenet, LOW normál módhoz
  LORA_AUX_PIN = bemenet, HIGH = modul szabad
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional

import settings

log = logging.getLogger("lora")

_MAGIC = b'\xAA\x55\x5A\xA5'  # 4 bájt — megakadályozza a hamis detektálást AES-CTR outputban

try:
    from Crypto.Hash import HMAC as _HMAC_TEST, SHA256 as _SHA256_TEST
    _test_mac = _HMAC_TEST.new(settings.LORA_HMAC_KEY, b"lora_key_check", _SHA256_TEST).hexdigest()
    log.info(f"LoRa kulcs ellenőrzés: hmac_test={_test_mac[:16]}")
except Exception as _e:
    log.warning(f"LoRa kulcs ellenőrzés hiba: {_e}")

try:
    import serial as _serial_mod
    _SERIAL_OK = True
except ImportError:
    _SERIAL_OK = False
    log.warning("pyserial nem elérhető")

try:
    import Jetson.GPIO as GPIO
    _GPIO_OK = True
except ImportError:
    _GPIO_OK = False
    log.warning("Jetson.GPIO nem elérhető — AUX/M0/M1 szimulálva")


# ── Keretezés ─────────────────────────────────────────────────────────────────

def _frame(data: bytes) -> bytes:
    n = len(data)
    return _MAGIC + bytes([n >> 8, n & 0xFF]) + data


def _unframe(buf: bytearray) -> Optional[bytes]:
    """Kiolvassa az első teljes csomagot a bufferből, helyben módosítja."""
    while len(buf) >= 6:  # 4B magic + 2B len
        idx = buf.find(_MAGIC)
        if idx < 0:
            del buf[:-3]  # megtartja az utolsó 3 bájtot (magic-1), ha épp érkezik
            return None
        if idx > 0:
            del buf[:idx]
        if len(buf) < 6:
            return None
        n = (buf[4] << 8) | buf[5]
        if len(buf) < 6 + n:
            return None
        payload = bytes(buf[6:6 + n])
        del buf[:6 + n]
        return payload
    return None


# ── Titkosítás ────────────────────────────────────────────────────────────────

def _encrypt(plaintext: bytes) -> bytes:
    from Crypto.Cipher import AES
    from Crypto.Hash import HMAC, SHA256
    nonce = os.urandom(8)
    ct    = AES.new(settings.LORA_AES_KEY, AES.MODE_CTR, nonce=nonce).encrypt(plaintext)
    mac   = HMAC.new(settings.LORA_HMAC_KEY,
                     settings.LORA_DEVICE_ID + nonce + ct, SHA256).digest()
    return settings.LORA_DEVICE_ID + nonce + ct + mac


def _decrypt(data: bytes) -> Optional[bytes]:
    from Crypto.Cipher import AES
    from Crypto.Hash import HMAC, SHA256
    min_size = 4 + 8 + 1 + 32
    if len(data) < min_size:
        log.debug(f"Túl rövid csomag: {len(data)} byte (min {min_size})")
        return None
    if data[:4] != settings.LORA_DEVICE_ID:
        log.debug(f"Ismeretlen device_id: {data[:4].hex()} — eldobva")
        return None
    nonce    = data[4:12]
    ct       = data[12:-32]
    mac_recv = data[-32:]
    expected = HMAC.new(settings.LORA_HMAC_KEY,
                        settings.LORA_DEVICE_ID + nonce + ct, SHA256).digest()
    if expected != mac_recv:
        _decrypt._fail_count = getattr(_decrypt, '_fail_count', 0) + 1
        if _decrypt._fail_count <= 3:
            log.warning(f"HMAC hiba #{_decrypt._fail_count}: {len(data)}B, ct={len(ct)}B\n"
                        f"  nonce      : {nonce.hex()}\n"
                        f"  várt  HMAC : {expected.hex()}\n"
                        f"  kapott HMAC: {mac_recv.hex()}\n"
                        f"  teljes hex : {data.hex()}")
        else:
            log.warning(f"HMAC hiba: {len(data)} byte, ct={len(ct)}B, "
                        f"első 8B: {data[:8].hex()}, utolsó 8B: {data[-8:].hex()}")
        return None
    return AES.new(settings.LORA_AES_KEY, AES.MODE_CTR, nonce=nonce).decrypt(ct)


# ── LoRaComm osztály ──────────────────────────────────────────────────────────

class LoRaComm:
    def __init__(self):
        self._ser: Optional[object] = None
        self._rx_buf        = bytearray()
        self._authenticated = False
        self._challenge: Optional[bytes] = None

    # ── GPIO ──────────────────────────────────────────────────────────────────

    def _gpio_setup(self) -> None:
        if not _GPIO_OK:
            return
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(settings.LORA_M0_PIN,  GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(settings.LORA_M1_PIN,  GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(settings.LORA_AUX_PIN, GPIO.IN)

    def _wait_aux(self, timeout: float = 0.1) -> bool:
        if not _GPIO_OK:
            time.sleep(0.02)
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if GPIO.input(settings.LORA_AUX_PIN) == GPIO.HIGH:
                return True
            time.sleep(0.002)
        return True  # Timeout esetén is folytatjuk — AUX opcionális

    # ── Hardware init ─────────────────────────────────────────────────────────

    def _init_hardware(self) -> bool:
        if settings.DRY_RUN:
            log.info("[DRY-RUN] LoRa E22 szimulálva")
            return True
        if not _SERIAL_OK:
            log.error("pyserial nem elérhető — LoRa nem indítható")
            return False
        try:
            self._gpio_setup()
            self._wait_aux()
            self._ser = _serial_mod.Serial(
                port=settings.LORA_UART_PORT,
                baudrate=settings.LORA_UART_BAUD,
                bytesize=8, parity='N', stopbits=1,
                timeout=0.1,
                rtscts=False, dsrdtr=False,
            )
            self._ser.reset_input_buffer()
            freq = 850.125 + settings.LORA_CHANNEL
            log.info(f"LoRa E22 init: {settings.LORA_UART_PORT}  "
                     f"{settings.LORA_UART_BAUD} baud  "
                     f"ch{settings.LORA_CHANNEL} ({freq:.3f} MHz)")
            return True
        except Exception as e:
            log.error(f"LoRa init hiba: {e}")
            return False

    # ── Küldés / fogadás ──────────────────────────────────────────────────────

    def _send_raw(self, data: bytes) -> None:
        if settings.DRY_RUN or self._ser is None:
            log.debug(f"[DRY-RUN] LoRa TX: {data.hex()}")
            return
        self._wait_aux()
        self._ser.write(_frame(data))
        self._ser.flush()
        self._wait_aux()

    def _recv_raw(self, timeout: float = 1.0) -> Optional[bytes]:
        if settings.DRY_RUN or self._ser is None:
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Read all available bytes
            waiting = self._ser.in_waiting
            if waiting:
                self._rx_buf.extend(self._ser.read(waiting))

            # If we have at least a header, determine expected frame size
            # and wait until the full frame has arrived before unframing
            idx = self._rx_buf.find(_MAGIC)
            if idx >= 0 and len(self._rx_buf) >= idx + 6:
                n = (self._rx_buf[idx + 4] << 8) | self._rx_buf[idx + 5]
                needed = idx + 6 + n
                # Drain until complete frame present
                while len(self._rx_buf) < needed and time.monotonic() < deadline:
                    w = self._ser.in_waiting
                    if w:
                        self._rx_buf.extend(self._ser.read(w))
                    else:
                        time.sleep(0.001)

            payload = _unframe(self._rx_buf)
            if payload is not None:
                log.debug(f"RX frame OK: {len(payload)}B payload")
                return payload
            time.sleep(0.005)
        return None

    # ── Handshake ─────────────────────────────────────────────────────────────

    def _verify_challenge_response(self, response: bytes) -> bool:
        from Crypto.Hash import HMAC, SHA256
        if self._challenge is None:
            return False
        try:
            HMAC.new(settings.LORA_HMAC_KEY, self._challenge, SHA256).verify(response)
            return True
        except ValueError:
            return False

    # ── Fő fogadó hurok ───────────────────────────────────────────────────────

    async def receive_loop(self, command_queue: asyncio.Queue, state) -> None:
        if not self._init_hardware():
            log.warning("LoRa hardver nem elérhető — szimulált mód")
            while True:
                await asyncio.sleep(10)

        self._challenge = os.urandom(32)
        loop = asyncio.get_event_loop()
        _last_nonce_tx = 0.0

        while True:
            now = loop.time()
            if not self._authenticated and now - _last_nonce_tx >= 5.0:
                await loop.run_in_executor(None, self._send_raw, self._challenge)
                log.info("LoRa handshake nonce elküldve, várakozás hitelesítésre...")
                _last_nonce_tx = now

            raw = await loop.run_in_executor(
                None, lambda: self._recv_raw(timeout=0.5)
            )

            if raw is None:
                await asyncio.sleep(0.01)
                continue

            if not self._authenticated:
                if self._verify_challenge_response(raw):
                    self._authenticated = True
                    state.lora_connected = True
                    log.info("LoRa távirányító hitelesítve!")
                    confirm = _encrypt(b'{"status":"ok"}')
                    await loop.run_in_executor(None, self._send_raw, confirm)
                else:
                    log.warning("LoRa: érvénytelen handshake válasz")
                continue

            plaintext = _decrypt(raw)
            if plaintext is None:
                continue

            try:
                cmd = json.loads(plaintext.decode("utf-8"))
                log.debug(f"LoRa RX JSON: {json.dumps(cmd, ensure_ascii=False)}")
                await command_queue.put(cmd)
            except Exception as e:
                log.warning(f"LoRa parse hiba: {e} | raw={plaintext[:64]}")

    async def send(self, data: dict) -> None:
        payload   = json.dumps(data).encode("utf-8")
        encrypted = _encrypt(payload)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_raw, encrypted)

    def cleanup(self) -> None:
        if self._ser:
            self._ser.close()
            self._ser = None
        if _GPIO_OK:
            try:
                GPIO.cleanup([
                    settings.LORA_M0_PIN,
                    settings.LORA_M1_PIN,
                    settings.LORA_AUX_PIN,
                ])
            except Exception:
                pass


# ── Önálló teszt ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LoRa E22 kommunikáció teszt")
    parser.add_argument("--listen", action="store_true",
                        help="Fogad és kiírja a csomagokat")
    args = parser.parse_args()

    async def _run():
        lora = LoRaComm()
        q: asyncio.Queue = asyncio.Queue()

        class MockState:
            lora_connected = False

        if args.listen:
            print("LoRa figyelő mód (Ctrl+C a kilépéshez)...")
            await lora.receive_loop(q, MockState())
        else:
            parser.print_help()

    asyncio.run(_run())
