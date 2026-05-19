"""
LoRa küldő modul — RFM95W SPI, AES-128 CTR + HMAC-SHA256.

A csomag formátum és a titkosítási séma pontosan megegyezik
a BotCode/components/lora_comm.py robot oldali implementációval.

Handshake protokoll (robot kezdeményez):
  1. Robot küld 32 raw byte nonce-t
  2. Controller válaszol: HMAC-SHA256(nonce, LORA_HMAC_KEY)
  3. Robot visszaküld titkosított {"status":"ok"}-t
"""

import json
import logging
import os
import time

import settings

log = logging.getLogger("lora")

try:
    from Crypto.Cipher  import AES
    from Crypto.Hash    import HMAC, SHA256
    from Crypto.Util    import Counter
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False
    log.warning("pycryptodome nem elérhető")

try:
    import board
    import busio
    import digitalio
    import adafruit_rfm9x
    _RFM_OK = True
except Exception:
    _RFM_OK = False
    log.warning("adafruit_rfm9x nem elérhető — száraz futás mód")


class LoraSender:
    def __init__(self):
        self._rfm     = None
        self._auth    = False

    # ── Hardware init ────────────────────────────────────────────────────────

    def open(self) -> bool:
        if not _RFM_OK:
            log.info("[DRY-RUN] LoraSender szimulált módban")
            return True
        try:
            spi   = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
            cs    = digitalio.DigitalInOut(board.CE0)
            reset = digitalio.DigitalInOut(
                getattr(board, f"D{settings.LORA_RESET_PIN}")
            )
            self._rfm = adafruit_rfm9x.RFM9x(
                spi, cs, reset,
                frequency=settings.LORA_FREQUENCY_MHZ,
            )
            self._rfm.signal_bandwidth       = settings.LORA_BANDWIDTH_KHZ * 1000
            self._rfm.spreading_factor       = settings.LORA_SPREADING_FACTOR
            self._rfm.coding_rate            = settings.LORA_CODING_RATE
            self._rfm.tx_power               = settings.LORA_TX_POWER_DBM
            self._rfm.receive_timeout        = settings.LORA_RECEIVE_TIMEOUT
            log.info(f"LoRa init: {settings.LORA_FREQUENCY_MHZ} MHz, SF{settings.LORA_SPREADING_FACTOR}")
            return True
        except Exception as e:
            log.error(f"LoRa init hiba: {e}")
            self._rfm = None
            return False

    def reinit(self) -> bool:
        self.close()
        return self.open()

    # ── Titkosítás ───────────────────────────────────────────────────────────

    def _encrypt(self, plaintext: bytes) -> bytes:
        if not _CRYPTO_OK:
            return plaintext
        nonce      = os.urandom(8)
        ctr        = Counter.new(64, prefix=nonce, little_endian=True)
        cipher     = AES.new(settings.LORA_AES_KEY, AES.MODE_CTR, counter=ctr)
        ciphertext = cipher.encrypt(plaintext)
        mac_input  = settings.LORA_DEVICE_ID + nonce + ciphertext
        mac        = HMAC.new(settings.LORA_HMAC_KEY, mac_input, SHA256).digest()
        return settings.LORA_DEVICE_ID + nonce + ciphertext + mac

    def _decrypt(self, packet: bytes) -> bytes | None:
        if not _CRYPTO_OK:
            return packet
        min_len = 4 + 8 + 1 + 32
        if len(packet) < min_len:
            return None
        device_id  = packet[:4]
        if device_id != settings.LORA_DEVICE_ID:
            return None
        nonce      = packet[4:12]
        ciphertext = packet[12:-32]
        recv_mac   = packet[-32:]
        mac_input  = device_id + nonce + ciphertext
        expected   = HMAC.new(settings.LORA_HMAC_KEY, mac_input, SHA256).digest()
        if expected != recv_mac:
            log.warning("HMAC ellenőrzés sikertelen")
            return None
        ctr       = Counter.new(64, prefix=nonce, little_endian=True)
        cipher    = AES.new(settings.LORA_AES_KEY, AES.MODE_CTR, counter=ctr)
        return cipher.decrypt(ciphertext)

    # ── Handshake ────────────────────────────────────────────────────────────

    def do_handshake(self, timeout_sec: float = 15.0) -> bool:
        """Robot oldalról érkező challenge nonce-ra válaszol HMAC-cal."""
        self._auth = False
        deadline = time.monotonic() + timeout_sec
        log.info("Handshake várakozás (robot challenge nonce)...")

        while time.monotonic() < deadline:
            nonce = self._recv_raw(timeout=1.0)
            if nonce is None or len(nonce) != 32:
                continue

            log.debug("Challenge nonce megérkezett, HMAC küldése...")
            if not _CRYPTO_OK:
                response = nonce  # dry-run
            else:
                response = HMAC.new(settings.LORA_HMAC_KEY, nonce, SHA256).digest()
            self._send_raw(response)

            # Várunk encrypted {"status":"ok"} visszaigazolásra
            conf_raw = self._recv_raw(timeout=3.0)
            if conf_raw is None:
                log.warning("Handshake megerősítés timeout")
                continue
            plaintext = self._decrypt(conf_raw)
            if plaintext is None:
                log.warning("Handshake megerősítés visszafejtési hiba")
                continue
            try:
                msg = json.loads(plaintext.decode("utf-8"))
                if msg.get("status") == "ok":
                    self._auth = True
                    log.info("Handshake OK — robot hitelesítve")
                    return True
            except Exception:
                pass
            log.warning("Érvénytelen handshake megerősítés")

        log.warning(f"Handshake timeout ({timeout_sec}s)")
        return False

    # ── Parancsküldés ────────────────────────────────────────────────────────

    def send_command(self, linear: float, angular: float) -> bool:
        payload = json.dumps({"cmd": "move", "linear": round(linear, 4),
                                             "angular": round(angular, 4)}).encode()
        return self._send_encrypted(payload)

    def send_stop(self) -> bool:
        return self._send_encrypted(b'{"cmd":"stop"}')

    def _send_encrypted(self, plaintext: bytes) -> bool:
        packet = self._encrypt(plaintext)
        return self._send_raw(packet)

    # ── Alacsony szintű küldés/fogadás ───────────────────────────────────────

    def _send_raw(self, data: bytes) -> bool:
        if not _RFM_OK or self._rfm is None:
            log.debug(f"[DRY-RUN] LoRa küldés: {len(data)} byte")
            return True
        try:
            self._rfm.send(data)
            return True
        except Exception as e:
            log.error(f"LoRa küldési hiba: {e}")
            return False

    def _recv_raw(self, timeout: float = 1.0) -> bytes | None:
        if not _RFM_OK or self._rfm is None:
            return None
        try:
            return self._rfm.receive(timeout=timeout)
        except Exception as e:
            log.error(f"LoRa fogadási hiba: {e}")
            return None

    def close(self) -> None:
        self._rfm  = None
        self._auth = False
