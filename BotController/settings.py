# =============================================================================
#  RoBot BotController - Beállítások
#  FONTOS: A LORA_* értékek azonosak kell legyenek a BotCode/settings.py-val!
#  A CTRL_* értékek felülírhatók config.json-nal (POST /api/settings).
# =============================================================================

# ── LORA ──────────────────────────────────────────────────────────────────────
# EBYTE E22-900T22D-V2 LoRa modul — azonos értékek mint a robot BotCode/settings.py-ban!
# Frekvencia: 850.125 + LORA_CHANNEL MHz  (pl. csatorna 18 → 868.125 MHz)

LORA_UART_PORT = "/dev/ttyAMA0"  # Raspberry Pi UART port
LORA_UART_BAUD = 9600            # Alapértelmezett UART baudrate

# GPIO pin kiosztás (BCM számozás) — M0/M1: mód vezérlés, AUX: kész jelző
LORA_M0_PIN  = 20               # M0=LOW + M1=LOW → normál/transparent mód
LORA_M1_PIN  = 21               # M0=LOW + M1=HIGH → AT konfigurációs mód
LORA_AUX_PIN = 16               # HIGH = modul szabad; LOW = foglalt (küld/fogad)

# Modul RF paraméterek
LORA_CHANNEL  = 18              # Csatorna 0–80; frekvencia = 850.125 + ch (MHz)
LORA_TX_POWER = 22              # Adási teljesítmény (dBm), max 22

# Titkosítás — FONTOS: éles használat előtt cseréld le, és egyezzen a robot oldalával!
LORA_DEVICE_ID = b"\xDE\xAD\xBE\xEF"
LORA_AES_KEY   = b"change_me_16byte"
LORA_HMAC_KEY  = b"change_me_hmac_key_32bytes!!"

# ── CONTROLLER ────────────────────────────────────────────────────────────────
# Xbox One gamepad és küldési paraméterek

CTRL_SPEED_LIMIT    = 1.0    # 0.0–1.0: az összes tengely kimenete ezzel szorzódik
CTRL_DEADZONE       = 0.05   # normalizált holtzona (0.0–1.0 közötti érték alatt = 0)
CTRL_SEND_HZ        = 20     # parancsküldés frekvenciája (Hz)
CTRL_GAMEPAD_DEVICE = ""     # "" = automatikus keresés; vagy pl. "/dev/input/event3"
CTRL_RECONNECT_SEC  = 3.0    # LoRa handshake újrakísérlet időköze (s)
CTRL_JUMP_DURATION  = 0.20   # ugrás impulzus hossza (s) — hány másodpercig tart a burst
CTRL_JUMP_POWER     = 1.0    # ugrás ereje (0.0–1.0)

# ── WEB SERVER ────────────────────────────────────────────────────────────────
# Beállítás UI szerver

WEB_HOST = "0.0.0.0"
WEB_PORT = 8081              # böngészőben: http://<pi-ip>:8081

# ── LOGGING ───────────────────────────────────────────────────────────────────

LOG_LEVEL = "INFO"           # DEBUG | INFO | WARNING | ERROR
