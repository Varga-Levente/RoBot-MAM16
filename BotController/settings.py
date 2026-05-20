# =============================================================================
#  RoBot BotController - Beállítások
#  FONTOS: A LORA_* értékek azonosak kell legyenek a BotCode/settings.py-val!
#  A CTRL_* értékek felülírhatók config.json-nal (POST /api/settings).
# =============================================================================

# ── LORA ──────────────────────────────────────────────────────────────────────
# RFM95W konfiguráció — azonos értékek mint a robot BotCode/settings.py-ban!

LORA_SPI_BUS          = 0
LORA_SPI_DEVICE       = 0
LORA_RESET_PIN        = 17          # BCM GPIO (Raspberry Pi)
LORA_FREQUENCY_MHZ    = 868.0       # EU ISM sáv
LORA_SPREADING_FACTOR = 7
LORA_BANDWIDTH_KHZ    = 125
LORA_CODING_RATE      = 5           # 4/5
LORA_TX_POWER_DBM     = 17
LORA_RECEIVE_TIMEOUT  = 0.5         # fogadási várakozás másodpercben

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

# ── WEB SERVER ────────────────────────────────────────────────────────────────
# Beállítás UI szerver

WEB_HOST = "0.0.0.0"
WEB_PORT = 8081              # böngészőben: http://<pi-ip>:8081

# ── LOGGING ───────────────────────────────────────────────────────────────────

LOG_LEVEL = "INFO"           # DEBUG | INFO | WARNING | ERROR
