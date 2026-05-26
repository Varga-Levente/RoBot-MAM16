# MAM16 BotCode — Robot szoftver

A Magyarok a Marson versenyhez készült robot szoftvere.  
Platform: **Nvidia Jetson Nano Dev Kit** | Nyelv: **Python 3.8+** (deadsnakes PPA)

---

## Architektúra

```
main.py
  │
  ├── RobotState          ← megosztott állapot (role, IP, gate_code, …)
  │
  ├── gate_code_queue ──► vision → ir_transmitter
  └── command_queue   ──► lora_comm → motor_controller
```

Minden komponens egy önálló asyncio task, queue-kon kommunikálnak egymással.

### Komponensek

| Fájl | Felelősség |
|------|-----------|
| `components/camera.py` | IMX219 CSI kamera / tesztvideó olvasás |
| `components/vision.py` | OpenCV kapu LED kód felismerés |
| `components/ir_transmitter.py` | 38kHz modulált IR jel küldés UART-on |
| `components/lora_comm.py` | E22-900T22D-V2 LoRa (UART), AES-128 titkosítással |
| `components/oled_display.py` | 0.91" SSD1306 OLED kijelző |
| `components/motor_controller.py` | DRV8833 + 4× N20 Mecanum motor (FL/FR/RL/RR) |
| `components/stream_server.py` | aiortc WebRTC stream + aiohttp web UI |
| `utils/logger.py` | Logging: konzol + fájl + SSE broadcast |
| `settings.py` | **Minden** konfigurálható paraméter |

---

## Hardver előfeltételek

### GPIO kiosztás (BCM számozás)

| Funkció | GPIO pin |
|---------|---------|
| Motor FL IN1 | 5 |
| Motor FL IN2 | 6 |
| Motor FR IN1 | 13 |
| Motor FR IN2 | 19 |
| Motor RL IN1 | 26 |
| Motor RL IN2 | 20 |
| Motor RR IN1 | 21 |
| Motor RR IN2 | 16 |
| LoRa M0 | 20 |
| LoRa M1 | 21 |
| LoRa AUX | 16 |

### I2C / SPI / UART

| Eszköz | Protokoll | Bus | Cím / CS |
|--------|-----------|-----|---------|
| SSD1306 OLED | I2C | Bus 1 | 0x3C |
| E22-900T22D-V2 LoRa | UART | /dev/ttyTHS2 | — |

### Soros port

| Funkció | Port |
|---------|------|
| IR LED (UART) | `/dev/ttyTHS1` |

---

## Telepítés

```bash
# 1. Repository klónozása
git clone <repo-url>
cd RoBot-MAM16/BotCode

# 2. Virtuális környezet (opcionális, de ajánlott)
python3 -m venv .venv
source .venv/bin/activate

# 3. Függőségek telepítése
pip install -r requirements.txt

# 4. GPIO jogosultság (Jetson Nano)
sudo usermod -aG gpio $USER
# Majd újraindítás vagy: newgrp gpio

# 5. UART engedélyezése (Jetson Nano)
sudo systemctl stop nvgetty
sudo systemctl disable nvgetty
# Majd újraindítás
```

### Jetson-specifikus megjegyzések

- **Python 3.8**: A Jetson Nano JetPack alapértelmezett Python verziója 3.6. Python 3.8 telepítéséhez a deadsnakes PPA szükséges:
  ```bash
  sudo add-apt-repository ppa:deadsnakes/ppa
  sudo apt-get update
  sudo apt-get install python3.8 python3.8-venv python3.8-dev
  ```
- **OpenCV**: Ajánlott a [Jetson előre fordított build](https://github.com/mdegans/nano_build_opencv) — gyorsabb, CUDA-képes.
- **Jetson.GPIO**: A JetPack-kel együtt telepítve van. Ha manuálisan kell: `pip install Jetson.GPIO`.
- **GStreamer**: Alapértelmezetten telepítve JetPack-kel (`nvarguscamerasrc` plugin).

---

## Beállítás (`settings.py`)

A `settings.py` fájl szekciókra bontva tartalmaz minden paramétert.  
**Éles használat előtt mindenképpen módosítandó:**

```python
# Robot azonosítás
ROBOT_NAME = "MAM16"
ROBOT_ROLE = "PACMAN"   # vagy "GHOST"

LORA_UART_PORT = "/dev/ttyTHS2"  # Jetson Nano UART port
LORA_M0_PIN    = 20              # BCM GPIO
LORA_M1_PIN    = 21              # BCM GPIO
LORA_AUX_PIN   = 16             # BCM GPIO
LORA_CHANNEL   = 18             # csatorna (868.125 MHz)
LORA_TX_POWER  = 22             # dBm
LORA_DEVICE_ID = b"\xDE\xAD\xBE\xEF"
LORA_AES_KEY   = b"change_me_16byte"
LORA_HMAC_KEY  = b"change_me_hmac_key_32bytes!!"

# Verseny: internet nélkül állítsd üresre
STREAM_STUN_SERVER = ""

# Mecanum motor vezérlés (4 kerék: FL/FR/RL/RR)
# FL = linear+lateral+angular, FR = linear-lateral-angular
# RL = linear-lateral+angular, RR = linear+lateral-angular
MOTOR_JUMP_DURATION = 1.0   # Ugrás impulzus hossza (s) — a LoRa JSON payload "duration" mezője felülírja
MOTOR_JUMP_POWER    = 1.0   # Ugrás ereje (0.0–1.0)
```

---

## Futtatás

### Teljes robot üzemmód
```bash
python main.py
```

### Hardver nélküli szimulációs mód (fejlesztéshez)
```bash
python main.py --dry-run
```

### Kamera helyett videófájl (vision tesztelés)
```bash
python main.py --test-video kapufelvétel.mp4
```

### Kombinált (videó + nincs hardver)
```bash
python main.py --test-video kapufelvétel.mp4 --dry-run
```

### Szerep felülírása
```bash
python main.py --role GHOST
```

---

## Videóalapú tesztelés (vision modul)

Ez az egyik legfontosabb tesztelési lehetőség: a kapu felismerő rendszer
tesztelésére nincs szükség fizikai hardverre, csak egy felvételre a kapuról.

### Tesztvideó készítése

1. Telefon kamerával vedd fel a kapu LED villogását.
2. Mentsd el pl. `test_gate.mp4` névvel a `BotCode/` mappába.
3. Javasolt felvételi beállítások: minimum 30 FPS, jó megvilágítás.

### Csak a vision modul tesztelése (konzolra írja az eredményt)

```bash
python -m components.vision --video test_gate.mp4
```

Képes megjelenítéssel (OpenCV ablak):

```bash
python -m components.vision --video test_gate.mp4 --show
```

A parancs kiírja a konzolra a felismert kódokat:
```
>>> Felismert kód: CA6
>>> Felismert kód: 3B9
```

### Teljes rendszer tesztelése videóval (web UI-val)

```bash
python main.py --test-video test_gate.mp4 --dry-run
```

Majd böngészőben: `http://localhost:8080`

- A videóból felismert kód megjelenik a jobb felső sarokban.
- A log panel mutatja a felismerési folyamatot.
- Az IR adás szimulálva van (log-ban látszik).

### ROI beállítása videó alapján

Ha a felismerés nem működik, állítsd be az ROI-t a `settings.py`-ban:

```python
VISION_ROI_X = 400   # bal oldal x koordináta
VISION_ROI_Y = 200   # felső y koordináta
VISION_ROI_W = 480   # szélesség
VISION_ROI_H = 320   # magasság
```

A `--show` kapcsolóval zöld kerettel látható az ROI a videón.

---

## Komponensek önálló tesztelése

### Kamera
```bash
python -m components.camera
python -m components.camera --video test.mp4
```

### Motor (billentyűzetes vezérlés, hardver szükséges)
```bash
python -m components.motor_controller
# W=előre, S=hátra, A=bal kanyar, D=jobb kanyar, Q=Mecanum bal oldalazás, E=Mecanum jobb oldalazás, X=stop
```

A motor vezérlő 4 db Mecanum kereket hajt (FL/FR/RL/RR). A Mecanum képlet:
- **FL** = linear + lateral + angular
- **FR** = linear − lateral − angular
- **RL** = linear − lateral + angular
- **RR** = linear + lateral − angular

### OLED kijelző (hardver szükséges)
```bash
python -m components.oled_display
```

### IR adó (hardver szükséges)
```bash
python -m components.ir_transmitter --code CA6
python -m components.ir_transmitter --code CA6 --count 3
```

### LoRa figyelő mód (hardver szükséges)
```bash
python -m components.lora_comm --listen
```

### Csak a web szerver (stream nélkül)
```bash
python -m components.stream_server
# Böngésző: http://localhost:8080
```

---

## Log értelmezés

A web UI log panelén és a konzolon a következő szinteket látod:

| Szint | Szín | Jelentés |
|-------|------|---------|
| `DEBUG` | Fehér | Részletes fejlesztői info (csak DEBUG módban) |
| `INFO` | Kék | Normál működési esemény |
| `WARNING` | Narancssárga | Figyelmeztető, de a rendszer fut |
| `ERROR` | Piros | Hiba, de a robot tovább fut |
| `CRITICAL` | Piros háttér | Súlyos hiba, azonnali beavatkozás kell |

A log szintet a `settings.py`-ban állíthatod:
```python
LOG_LEVEL = "DEBUG"   # részletes naplózáshoz
LOG_LEVEL = "INFO"    # normál üzemmód
```

---

## Hibaelhárítás

### „Permission denied" GPIO-n
```bash
sudo usermod -aG gpio $USER
newgrp gpio
```

### OLED nem jelenik meg
```bash
# I2C eszközök listázása
i2cdetect -y 1
# Ha nem látszik a 0x3C cím, ellenőrizd a bekötést
# Próbálj 0x3D címet: settings.py → OLED_I2C_ADDRESS = 0x3D
```

### Kamera nem indul (GStreamer hiba)
```bash
# Kamera tesztelése
gst-launch-1.0 nvarguscamerasrc ! nvvidconv ! xvimagesink
# Ha hibát dob, a kamera vagy a szalagkábel problémás
# Tesztvideóval: python main.py --test-video dummy.mp4 --dry-run
```

### LoRa nem kommunikál
```bash
# UART ellenőrzése
ls -la /dev/ttyTHS2
python3.8 -c "import serial; s=serial.Serial('/dev/ttyTHS2', 9600); print('OK')"
# GPIO jogosultság
sudo usermod -a -G gpio $USER
```

### WebRTC stream nem jelenik meg a böngészőben
- Ellenőrizd, hogy a robot és a böngésző ugyanazon a hálózaton van.
- Ha NAT mögött vagy: `settings.py → STREAM_STUN_SERVER = "stun:stun.l.google.com:19302"`
- Tűzfal: a `STREAM_PORT` (alapértelmezett: 8080) legyen nyitva.

### IR nem küldi a kódot
```bash
# UART port ellenőrzése
ls /dev/ttyTHS*   # /dev/ttyTHS1 kell látszódjon
# nvgetty kikapcsolása (ha fut)
sudo systemctl stop nvgetty && sudo systemctl disable nvgetty
```
