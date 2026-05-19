# =============================================================================
#  MAM16 Robot - Beállítások
#  Minden hangolható paraméter itt található, szekciókra bontva.
# =============================================================================

# ── ROBOT ─────────────────────────────────────────────────────────────────────
# Általános robot azonosítás és üzemmód

ROBOT_NAME = "MAM16"
ROBOT_ROLE = "PACMAN"   # "PACMAN" | "GHOST"
DRY_RUN    = False       # True = hardver nélküli szimulációs mód (CLI --dry-run is beállítja)

# ── CAMERA ────────────────────────────────────────────────────────────────────
# IMX219 CSI kamera (Jetson Nano natív GStreamer pipeline)

CAMERA_WIDTH  = 1280     # Felbontás szélesség (px)
CAMERA_HEIGHT = 720      # Felbontás magasság  (px)
CAMERA_FPS    = 30       # Képkocka / másodperc
CAMERA_FLIP   = 0        # nvvidconv flip-method: 0=nincs, 1=h-flip, 2=v-flip, 4=180°

# Tesztelési mód: ha nem üres, a kamera helyett videófájlt használ
# Példa: CAMERA_TEST_VIDEO = "test_gate.mp4"
CAMERA_TEST_VIDEO = ""   # "" = valódi CSI kamera
CAMERA_TEST_LOOP  = True # True = videó végén visszaugrik az elejére

# ── VISION ────────────────────────────────────────────────────────────────────
# Kapu LED villogás felismerés (OpenCV)

# Kapu kör detektálás (HoughCircles) — automatikusan megtalálja a kaput, nincs fix ROI
# Ha a kör nem detektálható (pl. rossz fényviszony), visszaesik a fix ROI-ra.
VISION_USE_HOUGH        = True   # True = HoughCircles (ajánlott); False = fix ROI
VISION_HOUGH_PARAM1     = 100    # Canny edge detector felső küszöb
VISION_HOUGH_PARAM2     = 30     # Kör akkumulátor küszöb (kisebb = több találat)
VISION_HOUGH_MIN_RADIUS = 100    # Minimális kapu sugár pixelben
VISION_HOUGH_MAX_RADIUS = 200    # Maximális kapu sugár pixelben

# Fix ROI fallback — csak akkor használt, ha HoughCircles nem talál kört
# (x, y, szélesség, magasság) pixelben
# 1280×720: VISION_ROI_X, VISION_ROI_Y, VISION_ROI_W, VISION_ROI_H = 400, 200, 480, 320
# 458×458:
VISION_ROI_X = 29
VISION_ROI_Y = 29
VISION_ROI_W = 400
VISION_ROI_H = 400

# LED jellemzők
VISION_LED_THRESHOLD   = 180   # Binarizálás küszöbértéke (0–255); fölötte = LED bekapcsolt
VISION_MIN_SQUARE_AREA = 500   # Minimális négyzet kontúr terület (szűri a zajt)

# Bit-sorrend (versenyspecifikáció szerint):
#   TL=1 (LSB), TR=2, BL=4, BR=8 (MSB)
#   Pl. C=12=1100: BR(8)+BL(4)=12; A=10=1010: BR(8)+TR(2)=10; 6=0110: BL(4)+TR(2)=6

# Időzítés
VISION_DIGIT_INTERVAL_MS = 200   # Egy LED állapotváltás időablaka (ms) — verseny spec: 200ms
# Hány egymást követő egyforma frame kell a digit elfogadásához.
# Tesztvideóhoz (GIF-alapú): 1; éles kameránál (zajszűrés): 2–3
VISION_STABLE_FRAMES     = 1
VISION_COOLDOWN_MS       = 500   # Sikeres kódolvasás után ennyi ms-ig nem indul újabb felismerés

# ── IR ────────────────────────────────────────────────────────────────────────
# SFH4546 infra LED vezérlés (soros kommunikáció 38kHz vivőfrekvencián)

# Adási mód:
#   DIRECT_UART  — 1200 baud UART, külső hardver (555 IC vagy HW PWM) biztosítja a 38kHz-t
#   CARRIER_UART — 38400 baud UART, szoftver carrier: 0xAA=burst, 0x00=csend (nincs extra hw)
#   HW_PWM       — 1200 baud UART + Jetson Nano hardware PWM 38kHz vivő (IR_PWM_PIN-en)
IR_MODE            = "CARRIER_UART"

IR_UART_PORT       = "/dev/ttyTHS1"  # Jetson Nano hardware UART port
IR_BAUD_RATE       = 1200            # Soros kommunikáció baudrate (DIRECT_UART és HW_PWM módban)
IR_DATA_BITS       = 8               # Adatbitek száma
IR_PARITY          = "N"             # Paritás: "N"=nincs, "E"=páros, "O"=páratlan
IR_STOP_BITS       = 1               # Stop bitek száma
IR_TIMEOUT_SEC     = 1.0             # UART időtúllépés másodpercben
IR_MAX_TX_PER_SEC  = 2               # Maximális adások száma másodpercenként (verseny limit)

# CARRIER_UART mód paraméterei
# 4 byte @ 38400 baud ≈ 833µs ≈ 1 bit @ 1200 baud
IR_CARRIER_BAUD    = 38400           # UART baudrate CARRIER_UART módban
IR_CARRIER_BYTE    = 0xAA            # 10101010 bináris → ~38.4kHz burst minta
IR_SILENCE_BYTE    = 0x00            # Csend (nincs vivő)
IR_BYTES_PER_BIT   = 4               # Hány carrier/silence byte fedi le egy 1200 baud bitet

# HW_PWM mód paraméterei (csak HW_PWM módban használt)
IR_PWM_PIN         = 32              # Jetson Nano hardware PWM pin (BCM); -1 = külső 555 IC

# ── LORA ──────────────────────────────────────────────────────────────────────
# RFM95W LoRa modul konfiguráció (SPI) és titkosítás

LORA_SPI_BUS          = 0           # SPI busz azonosító
LORA_SPI_DEVICE       = 0           # SPI chip select azonosító (CE0)
LORA_RESET_PIN        = 17          # GPIO reset pin (BCM számozás)
LORA_FREQUENCY_MHZ    = 868.0       # Frekvencia (MHz) — EU ISM sáv
LORA_SPREADING_FACTOR = 7           # SF7–SF12; kisebb = gyorsabb, nagyobb = nagyobb hatótáv
LORA_BANDWIDTH_KHZ    = 125         # Sávszélesség kHz-ben (125 / 250 / 500)
LORA_CODING_RATE      = 5           # Kódolási arány: 5=4/5, 6=4/6, 7=4/7, 8=4/8
LORA_TX_POWER_DBM     = 17          # Adási teljesítmény (dBm), max 20
LORA_RECEIVE_TIMEOUT  = 0.1         # Fogadási várakozás másodpercenként (nem blokkoló poll)

# Titkosítás — FONTOS: éles használat előtt cseréld le mindkét kulcsot!
# Mindkét robot és a távirányító ugyanazt a kulcspárt kell használja.
LORA_DEVICE_ID = b"\xDE\xAD\xBE\xEF"            # 4 bájt egyedi robot azonosító
LORA_AES_KEY   = b"change_me_16byte"              # 16 bájtos AES-128 titkosítási kulcs
LORA_HMAC_KEY  = b"change_me_hmac_key_32bytes!!"  # 32 bájtos HMAC-SHA256 hitelesítési kulcs

# ── MOTORS ────────────────────────────────────────────────────────────────────
# DRV8833 motor driver GPIO kiosztás (BCM számozás) — 4 db N20 motor

# Bal első motor (Front Left)
MOTOR_FL_IN1 = 5
MOTOR_FL_IN2 = 6
# Jobb első motor (Front Right)
MOTOR_FR_IN1 = 13
MOTOR_FR_IN2 = 19
# Bal hátsó motor (Rear Left)
MOTOR_RL_IN1 = 26
MOTOR_RL_IN2 = 20
# Jobb hátsó motor (Rear Right)
MOTOR_RR_IN1 = 21
MOTOR_RR_IN2 = 16

MOTOR_PWM_FREQ_HZ  = 1000   # PWM frekvencia Hz-ben
MOTOR_MAX_SPEED    = 1.0    # Maximális sebesség (0.0–1.0 normalizált)
MOTOR_MIN_SPEED    = 0.0    # Minimális sebesség (holt sáv szűrő)
MOTOR_RAMP_RATE    = 0.05   # Sebesség változás / vezérlési ciklus (gyorsulás korlát)
MOTOR_COMMAND_HZ   = 50     # Motor vezérlési ciklus frekvencia (Hz)

# ── OLED ──────────────────────────────────────────────────────────────────────
# 0.91" 128x32 pixeles SSD1306 OLED kijelző (I2C)

OLED_I2C_BUS     = 1       # I2C busz azonosító (Jetson Nano: 1)
OLED_I2C_ADDRESS = 0x3C    # I2C cím (0x3C vagy 0x3D, hardver függő)
OLED_WIDTH       = 128     # Kijelző szélesség pixelben
OLED_HEIGHT      = 32      # Kijelző magasság pixelben
OLED_UPDATE_HZ   = 2       # Kijelző frissítési frekvencia (Hz)
OLED_CONTRAST    = 200     # Fényerő (0–255)

# ── STREAM ────────────────────────────────────────────────────────────────────
# aiortc WebRTC videóstream szerver

STREAM_HOST        = "0.0.0.0"                        # Hálózati interfész
STREAM_PORT        = 8080                              # HTTP/WebRTC port
STREAM_CODEC       = "VP8"                             # Videó kodek: "VP8" | "H264"
STREAM_VIDEO_BITRATE = 1_500_000                       # Videó bitrate (bps)

# STUN szerver WebRTC ICE egyeztetéshez
# Ha a robot és a böngésző ugyanazon a LAN-on van (pl. verseny), üresen hagyható.
# Ha internet elérhető és NAT mögött van a kliens, használj STUN szervert.
STREAM_STUN_SERVER = "stun:stun.l.google.com:19302"   # "" = csak lokális ICE kandidátok

STREAM_ICE_TIMEOUT = 5     # ICE összeköttetés időtúllépése másodpercben
TEST_UI_PORT       = 8081  # Teszt UI port (--test-ui flag esetén)

# ── LOGGING ───────────────────────────────────────────────────────────────────
# Naplózás fájlba és a web UI-ba (SSE)

LOG_LEVEL        = "INFO"          # DEBUG | INFO | WARNING | ERROR | CRITICAL
LOG_FILE         = "robot.log"     # Naplófájl neve (üres = nincs fájlba írás)
LOG_MAX_BYTES    = 5 * 1024 * 1024 # Maximális naplófájl méret (5 MB)
LOG_BACKUP_COUNT = 3               # Régi naplófájlok száma amit megőriz
LOG_SSE_MAXQUEUE = 500             # SSE log sor puffer méret (régebbi sorok eldobódnak)
