"""
LoRa küldő modul — EBYTE E22-900T22D-V2 UART, AES-128 CTR + HMAC-SHA256.

A csomag formátum és a titkosítási séma pontosan megegyezik
a BotCode/components/lora_comm.py robot oldali implementációval.

Keret formátum (alkalmazás réteg):
  [0xAA][0x55][len_hi][len_lo][payload]

Handshake protokoll (robot kezdeményez):
  1. Robot küld 32 raw byte nonce-t
  2. Controller válaszol: HMAC-SHA256(nonce, LORA_HMAC_KEY)
  3. Robot visszaküld titkosított {"status":"ok"}-t

GPIO (RPi.GPIO, BCM számozás):
  LORA_M0_PIN  = kimenet, LOW normál módhoz
  LORA_M1_PIN  = kimenet, LOW normál módhoz
  LORA_AUX_PIN = bemenet, HIGH = modul szabad
"""

import json
import logging
import os
import time
from typing import Optional

import settings

log = logging.getLogger("lora")

_MAGIC = b'\xAA\x55'

try:
    from Crypto.Cipher import AES
    from Crypto.Hash   import HMAC, SHA256
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False
    log.warning("pycryptodome nem elérhető")

try:
    import serial as _serial_mod
    _SERIAL_OK = True
except ImportError:
    _SERIAL_OK = False
    log.warning("pyserial nem elérhető — LoRa nem elérhető")

try:
    import RPi.GPIO as GPIO
    _GPIO_OK = True
except ImportError:
    _GPIO_OK = False
    log.warning("RPi.GPIO nem elérhető — AUX/M0/M1 szimulálva")


# ── Keretezés ─────────────────────────────────────────────────────────────────

def _frame(data: bytes) -> bytes:
    n = len(data)
    return _MAGIC + bytes([n >> 8, n & 0xFF]) + data


def _unframe(buf: bytearray) -> Optional[bytes]:
    """Kiolvassa az első teljes csomagot a bufferből, helyben módosítja."""
    while len(buf) >= 4:
        idx = buf.find(_MAGIC)
        if idx < 0:
            del buf[:-1]
            return None
        if idx > 0:
            del buf[:idx]
        if len(buf) < 4:
            return None
        n = (buf[2] << 8) | buf[3]
        if len(buf) < 4 + n:
            return None
        payload = bytes(buf[4:4 + n])
        del buf[:4 + n]
        return payload
    return None


# ── LoraSender osztály ────────────────────────────────────────────────────────

class LoraSender:
    def __init__(self):
        self._ser: Optional[object] = None
        self._rx_buf = bytearray()
        self._auth   = False

    @property
    def hw_available(self) -> bool:
        return _SERIAL_OK

    # ── GPIO ──────────────────────────────────────────────────────────────────

    def _gpio_setup(self) -> None:
        if not _GPIO_OK:
            return
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(settings.LORA_M0_PIN,  GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(settings.LORA_M1_PIN,  GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(settings.LORA_AUX_PIN, GPIO.IN)

    def _wait_aux(self, timeout: float = 2.0) -> bool:
        if not _GPIO_OK:
            time.sleep(0.02)
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if GPIO.input(settings.LORA_AUX_PIN) == GPIO.HIGH:
                return True
            time.sleep(0.002)
        log.warning("LoRa AUX timeout — modul nem válaszol")
        return False

    # ── Hardware init ─────────────────────────────────────────────────────────

    def open(self) -> bool:
        if not _SERIAL_OK:
            log.warning("pyserial nem elérhető — LoRa nem elérhető")
            return False
        try:
            self._gpio_setup()
            self._wait_aux()
            self._ser = _serial_mod.Serial(
                port=settings.LORA_UART_PORT,
                baudrate=settings.LORA_UART_BAUD,
                bytesize=8, parity='N', stopbits=1,
                timeout=0.1,
            )
            self._ser.reset_input_buffer()
            freq = 850.125 + settings.LORA_CHANNEL
            log.info(f"LoRa E22 init: {settings.LORA_UART_PORT}  "
                     f"{settings.LORA_UART_BAUD} baud  "
                     f"ch{settings.LORA_CHANNEL} ({freq:.3f} MHz)")
            return True
        except Exception as e:
            log.error(f"LoRa init hiba: {e}")
            self._ser = None
            return False

    def reinit(self) -> bool:
        self.close()
        return self.open()

    # ── Titkosítás ────────────────────────────────────────────────────────────

    def _encrypt(self, plaintext: bytes) -> bytes:
        if not _CRYPTO_OK:
            return plaintext
        nonce = os.urandom(8)
        ct    = AES.new(settings.LORA_AES_KEY, AES.MODE_CTR, nonce=nonce).encrypt(plaintext)
        mac   = HMAC.new(settings.LORA_HMAC_KEY,
                         settings.LORA_DEVICE_ID + nonce + ct, SHA256).digest()
        return settings.LORA_DEVICE_ID + nonce + ct + mac

    def _decrypt(self, data: bytes) -> Optional[bytes]:
        if not _CRYPTO_OK:
            return data
        if len(data) < 4 + 8 + 1 + 32:
            return None
        if data[:4] != settings.LORA_DEVICE_ID:
            return None
        nonce    = data[4:12]
        ct       = data[12:-32]
        mac_recv = data[-32:]
        expected = HMAC.new(settings.LORA_HMAC_KEY,
                            settings.LORA_DEVICE_ID + nonce + ct, SHA256).digest()
        if expected != mac_recv:
            log.warning("HMAC ellenőrzés sikertelen")
            return None
        return AES.new(settings.LORA_AES_KEY, AES.MODE_CTR, nonce=nonce).decrypt(ct)

    # ── Alacsony szintű küldés / fogadás ──────────────────────────────────────

    def _send_raw(self, data: bytes) -> bool:
        if not _SERIAL_OK or self._ser is None:
            return False
        try:
            self._wait_aux()
            self._ser.write(_frame(data))
            self._ser.flush()
            self._wait_aux()
            return True
        except Exception as e:
            log.error(f"LoRa küldési hiba: {e}")
            return False

    def _recv_raw(self, timeout: float = 1.0) -> Optional[bytes]:
        if not _SERIAL_OK or self._ser is None:
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._ser.in_waiting:
                self._rx_buf.extend(self._ser.read(self._ser.in_waiting))
            payload = _unframe(self._rx_buf)
            if payload is not None:
                return payload
            time.sleep(0.01)
        return None

    # ── Handshake ─────────────────────────────────────────────────────────────

    def do_handshake(self, timeout_sec: float = 15.0) -> bool:
        self._auth = False
        deadline   = time.monotonic() + timeout_sec
        log.info("Handshake várakozás (robot challenge nonce)...")

        while time.monotonic() < deadline:
            nonce = self._recv_raw(timeout=1.0)
            if nonce is None or len(nonce) != 32:
                continue

            log.debug("Challenge nonce megérkezett, HMAC küldése...")
            response = (
                HMAC.new(settings.LORA_HMAC_KEY, nonce, SHA256).digest()
                if _CRYPTO_OK else nonce
            )
            self._send_raw(response)

            conf_raw  = self._recv_raw(timeout=3.0)
            if conf_raw is None:
                log.warning("Handshake megerősítés timeout")
                continue
            plaintext = self._decrypt(conf_raw)
            if plaintext is None:
                continue
            try:
                if json.loads(plaintext.decode("utf-8")).get("status") == "ok":
                    self._auth = True
                    log.info("Handshake OK — robot hitelesítve")
                    return True
            except Exception:
                pass
            log.warning("Érvénytelen handshake megerősítés")

        log.warning(f"Handshake timeout ({timeout_sec}s)")
        return False

    # ── Parancsküldés ─────────────────────────────────────────────────────────

    def send_command(self, linear: float, angular: float,
                     lateral: float = 0.0, left_y: float = 0.0) -> bool:
        payload = json.dumps({
            "cmd":     "move",
            "linear":  round(linear,  4),
            "angular": round(angular, 4),
            "lateral": round(lateral, 4),
            "left_y":  round(left_y,  4),
        }).encode()
        return self._send_raw(self._encrypt(payload))

    def send_jump(self, direction: str) -> bool:
        payload = json.dumps({"cmd": "jump", "direction": direction}).encode()
        return self._send_raw(self._encrypt(payload))

    def send_stop(self) -> bool:
        return self._send_raw(self._encrypt(b'{"cmd":"stop"}'))

    def close(self) -> None:
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
        self._auth = False
