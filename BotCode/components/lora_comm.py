"""
LoRa kommunikációs modul (RFM95W, 868 MHz).

Titkosítási séma:
  - AES-128 CTR mód (pycryptodome)
  - HMAC-SHA256 üzenet hitelesítés
  - Csomag formátum: [device_id: 4B][nonce: 8B][ciphertext][HMAC: 32B]
  - Ismeretlen device_id vagy hibás HMAC → csomag eldobás

Handshake:
  - Robot induláskor 32 bájtos véletlenszerű nonce-t broadcast-ol.
  - A távirányítónak HMAC-SHA256(nonce, LORA_HMAC_KEY) értékkel kell válaszolnia.
  - Helyes válasz után a robothoz tartozó távirányítóként hitelesítődik.

Parancs formátum (decryptált payload):
  JSON: {"cmd": "move", "linear": 0.5, "angular": -0.2}
  vagy: {"cmd": "stop"}
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional

import settings

log = logging.getLogger("lora")


def _encrypt(plaintext: bytes, aes_key: bytes, hmac_key: bytes, device_id: bytes) -> bytes:
    from Crypto.Cipher import AES
    from Crypto.Hash import HMAC, SHA256

    nonce = os.urandom(8)
    cipher = AES.new(aes_key, AES.MODE_CTR, nonce=nonce)
    ciphertext = cipher.encrypt(plaintext)

    mac_input = device_id + nonce + ciphertext
    h = HMAC.new(hmac_key, mac_input, SHA256)
    return device_id + nonce + ciphertext + h.digest()


def _decrypt(data: bytes, aes_key: bytes, hmac_key: bytes, expected_device_id: bytes) -> Optional[bytes]:
    from Crypto.Cipher import AES
    from Crypto.Hash import HMAC, SHA256

    min_len = 4 + 8 + 1 + 32  # device_id + nonce + min 1B ciphertext + hmac
    if len(data) < min_len:
        return None

    device_id = data[:4]
    if device_id != expected_device_id:
        log.debug(f"Ismeretlen device_id: {device_id.hex()} — csomag eldobva")
        return None

    nonce = data[4:12]
    hmac_recv = data[-32:]
    ciphertext = data[12:-32]

    mac_input = device_id + nonce + ciphertext
    h = HMAC.new(hmac_key, mac_input, SHA256)
    try:
        h.verify(hmac_recv)
    except ValueError:
        log.warning("HMAC ellenőrzés sikertelen — csomag eldobva")
        return None

    cipher = AES.new(aes_key, AES.MODE_CTR, nonce=nonce)
    return cipher.decrypt(ciphertext)


class LoRaComm:
    def __init__(self):
        self._rfm9x = None
        self._authenticated = False
        self._challenge: Optional[bytes] = None

    def _init_hardware(self) -> bool:
        if settings.DRY_RUN:
            log.info("[DRY-RUN] LoRa szimulálva")
            return True
        try:
            import board
            import busio
            import digitalio
            import adafruit_rfm9x

            spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
            cs = digitalio.DigitalInOut(board.CE0)
            reset = digitalio.DigitalInOut(getattr(board, f"D{settings.LORA_RESET_PIN}"))

            self._rfm9x = adafruit_rfm9x.RFM9x(spi, cs, reset, settings.LORA_FREQUENCY_MHZ)
            self._rfm9x.tx_power         = settings.LORA_TX_POWER_DBM
            self._rfm9x.spreading_factor = settings.LORA_SPREADING_FACTOR
            self._rfm9x.signal_bandwidth = settings.LORA_BANDWIDTH_KHZ * 1000
            self._rfm9x.coding_rate      = settings.LORA_CODING_RATE

            log.info(f"LoRa inicializálva: {settings.LORA_FREQUENCY_MHZ} MHz, SF{settings.LORA_SPREADING_FACTOR}")
            return True
        except Exception as e:
            log.error(f"LoRa inicializálási hiba: {e}")
            return False

    async def _send_challenge(self) -> None:
        """Handshake: nonce küldése a távirányítónak hitelesítéshez."""
        self._challenge = os.urandom(32)
        log.info("LoRa handshake nonce elküldve, várakozás hitelesítésre...")
        await self._send_raw(self._challenge)

    async def _send_raw(self, data: bytes) -> None:
        if settings.DRY_RUN or self._rfm9x is None:
            log.debug(f"[DRY-RUN] LoRa küldés: {data.hex()}")
            return
        await asyncio.get_event_loop().run_in_executor(None, self._rfm9x.send, data)

    def _receive_raw(self) -> Optional[bytes]:
        if settings.DRY_RUN or self._rfm9x is None:
            return None
        packet = self._rfm9x.receive(timeout=settings.LORA_RECEIVE_TIMEOUT)
        return bytes(packet) if packet is not None else None

    def _verify_challenge_response(self, response: bytes) -> bool:
        from Crypto.Hash import HMAC, SHA256
        if self._challenge is None:
            return False
        h = HMAC.new(settings.LORA_HMAC_KEY, self._challenge, SHA256)
        try:
            h.verify(response)
            return True
        except ValueError:
            return False

    async def receive_loop(self, command_queue: asyncio.Queue, state) -> None:
        """Főhurok: fogad, hitelesít, dekryptál, parancsot queue-ba tesz."""
        if not self._init_hardware():
            log.error("LoRa nem inicializálható, kommunikációs hurok leáll")
            return

        await self._send_challenge()
        log.info("LoRa fogadó hurok elindult")

        while True:
            raw = await asyncio.get_event_loop().run_in_executor(None, self._receive_raw)

            if raw is None:
                await asyncio.sleep(0.01)
                continue

            if not self._authenticated:
                if self._verify_challenge_response(raw):
                    self._authenticated = True
                    state.lora_connected = True
                    log.info("LoRa távirányító hitelesítve!")
                    # Sikeres handshake visszaigazolás
                    confirm = _encrypt(b'{"status":"ok"}', settings.LORA_AES_KEY,
                                       settings.LORA_HMAC_KEY, settings.LORA_DEVICE_ID)
                    await self._send_raw(confirm)
                else:
                    log.warning("LoRa: érvénytelen handshake válasz")
                continue

            plaintext = _decrypt(raw, settings.LORA_AES_KEY, settings.LORA_HMAC_KEY, settings.LORA_DEVICE_ID)
            if plaintext is None:
                continue

            try:
                cmd = json.loads(plaintext.decode("utf-8"))
                await command_queue.put(cmd)
                log.debug(f"LoRa parancs fogadva: {cmd}")
            except Exception as e:
                log.warning(f"LoRa parancs parse hiba: {e}")

    async def send(self, data: dict) -> None:
        payload = json.dumps(data).encode("utf-8")
        encrypted = _encrypt(payload, settings.LORA_AES_KEY, settings.LORA_HMAC_KEY, settings.LORA_DEVICE_ID)
        await self._send_raw(encrypted)


# ── Önálló teszt ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LoRa kommunikáció teszt")
    parser.add_argument("--listen", action="store_true", help="Fogad és kiírja a csomagokat")
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
