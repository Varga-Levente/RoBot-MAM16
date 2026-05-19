# MAM16 BotController — Távirányító szoftver

Xbox One USB kontroller → Raspberry Pi 3B+ → RFM95W LoRa → robot.  
Platform: **Raspberry Pi 3B+** | Nyelv: **Python 3.10+**

---

## Architektúra

```
main.py
  │
  ├── ControllerState     ← megosztott állapot (gamepad, LoRa, linear/angular)
  │
  ├── GamepadReader  ──── evdev Xbox One USB → (linear, angular)
  ├── LoraSender     ──── RFM95W SPI, AES-128 + HMAC, handshake + küldés
  └── ControllerWebServer ← aiohttp beállítás UI + config.json perzisztencia
```

### Adatfolyam

```
Xbox One (USB)
    │  evdev ABS_X / ABS_Z / ABS_RZ
    ▼
GamepadReader.read_state()
    │  (linear, angular) −1.0 .. 1.0
    ▼  deadzone + speed_limit szűrés
LoraSender.send_command()
    │  JSON → AES-128 CTR → HMAC-SHA256
    ▼
RFM95W LoRa 868 MHz
    │
    ▼
Robot (BotCode) → motor_controller
```

### Komponensek

| Fájl | Felelősség |
|------|-----------|
| `main.py` | asyncio főhurok, handshake → vezérlés → reconnect |
| `settings.py` | Minden konfigurálható paraméter |
| `controller_input.py` | evdev Xbox gamepad olvasó, deadzone, speed limit |
| `lora_sender.py` | RFM95W SPI, titkosítás, challenge-response handshake |
| `web_server.py` | aiohttp beállítás UI, config.json perzisztencia |
| `web/` | Sötét glassmorphism UI, live joystick canvas |

---

## Hardver előfeltételek

### Alkatrészek

| Alkatrész | Megjegyzés |
|-----------|-----------|
| Raspberry Pi 3B+ | Bármilyen RPi 3/4 működik |
| RFM95W LoRa modul | Azonos mint a roboron (868 MHz) |
| Xbox One kontroller | Pulse Red vagy bármely USB-s Xbox One típus |
| USB kábel | Mikro-USB, kontroller csatlakozáshoz |

### GPIO kiosztás — RFM95W SPI bekötés (BCM számozás)

| RFM95W pin | RPi GPIO | RPi fizikai pin |
|-----------|----------|----------------|
| VIN / 3.3V | 3.3V | Pin 1 |
| GND | GND | Pin 6 |
| SCK | GPIO 11 (SCLK) | Pin 23 |
| MOSI | GPIO 10 (MOSI) | Pin 19 |
| MISO | GPIO 9 (MISO) | Pin 21 |
| CS / NSS | GPIO 8 (CE0) | Pin 24 |
| RST | GPIO 17 | Pin 11 |

> **Fontos:** Az SPI-t engedélyezni kell a Pi-n (`raspi-config` → Interface Options → SPI).

---

## Telepítés

```bash
# 1. Repository klónozása
git clone <repo-url>
cd RoBot-MAM16/BotController

# 2. Virtuális környezet (ajánlott)
python3 -m venv .venv
source .venv/bin/activate

# 3. Függőségek telepítése
pip install -r requirements.txt

# 4. SPI engedélyezése
sudo raspi-config
# Interface Options → SPI → Enable

# 5. GPIO jogosultság
sudo usermod -aG gpio,spi,input $USER
# Majd kijelentkezés / újraindítás

# 6. Xbox kontroller tesztelése
ls /dev/input/event*
# Dugd be az Xbox kontrollerhez tartozó USB kábelt, majd:
python3 -c "import evdev; [print(d, evdev.InputDevice(d).name) for d in evdev.list_devices()]"
# Keress "Xbox" vagy "Microsoft" nevű eszközt
```

### Raspberry Pi-specifikus megjegyzések

- **evdev:** Csak Linux-on működik. A `input` csoport tagságára szükség van (`/dev/input/event*` olvasáshoz).
- **adafruit-blinka:** A `BLINKA_MCP2221` környezeti változó beállítása **nem** szükséges RPi-n — natív GPIO használ.
- **SPI sebesség:** Az RFM95W alapértelmezetten 5 MHz-en kommunikál, RPi SPI elbírja.

---

## Beállítás (`settings.py`)

A `settings.py` két szekciót tartalmaz.

### LoRa szekció — azonos kell legyen a robot `BotCode/settings.py`-val!

```python
LORA_FREQUENCY_MHZ    = 868.0
LORA_SPREADING_FACTOR = 7
LORA_TX_POWER_DBM     = 17
LORA_DEVICE_ID        = b"\xDE\xAD\xBE\xEF"   # ← egyezzen a robottal
LORA_AES_KEY          = b"change_me_16byte"     # ← cseréld le!
LORA_HMAC_KEY         = b"change_me_hmac_key_32bytes!!"  # ← cseréld le!
```

> **Verseny előtt:** A `LORA_AES_KEY` és `LORA_HMAC_KEY` értékeket cseréld le egyedi kulcsokra, és győződj meg róla, hogy a robot oldalon (`BotCode/settings.py`) ugyanazok az értékek szerepelnek.

### Controller szekció

```python
CTRL_SPEED_LIMIT    = 1.0    # 0.0–1.0: sebesség korlát (100% = teljes sebesség)
CTRL_DEADZONE       = 0.05   # holtzona normalizált értékben
CTRL_SEND_HZ        = 20     # parancsküldés frekvenciája
CTRL_GAMEPAD_DEVICE = ""     # "" = automatikus keresés
```

### Perzisztens beállítások (`config.json`)

A web UI-on mentett értékek a `config.json` fájlba íródnak, és induláskor automatikusan betöltődnek — felülírják a `settings.py` alapértékeket. A fájl `.gitignore`-ban szerepel (nem kerül a repóba).

---

## Futtatás

### Normál mód
```bash
python main.py
```

### Hardver nélküli szimulációs mód (fejlesztéshez, Pi nélkül)
```bash
python main.py --dry-run
```

### Sebesség limit beállítása induláskor
```bash
python main.py --speed-limit 0.7   # max 70%
```

### Gamepad eszköz megadása kézzel
```bash
python main.py --device /dev/input/event3
```

### Kombinált
```bash
python main.py --speed-limit 0.5 --device /dev/input/event3
```

---

## Beállítás web UI

Indítás után a böngészőben elérhető:

```
http://<raspberry-pi-ip>:8081
```

### Funkciók

- **Valós idejű állapot:** joystick pozíció canvas-on, LT/RT trigger bar-ok, LoRa és gamepad kapcsolat státusz
- **Vezérlés beállítások:** sebesség limit slider (0–100%), holtzona slider, küldési sebesség (10/20/50 Hz), gamepad eszköz
- **LoRa beállítások:** frekvencia, Spreading Factor, TX teljesítmény — mentés után automatikusan újrainicializálja a LoRa modult
- **Perzisztencia:** minden mentés azonnal érvényes futás közben, és `config.json`-ba íródik (megmarad újraindítás után)

---

## Vezérlés

### Tengely kiosztás

| Gomb / Tengely | Funkció | Irány |
|----------------|---------|-------|
| **RT** (jobb trigger) | Előremenet | Minél jobban húzva → annál gyorsabb |
| **LT** (bal trigger) | Hátramenet | Minél jobban húzva → annál gyorsabb |
| **Bal joystick X** | Kanyar | Bal → balra, Jobb → jobbra |

> RT és LT egyszerre is húzható — a nettó lineáris sebesség az RT−LT különbsége.

### Sebesség limit

A `CTRL_SPEED_LIMIT` (0.0–1.0) az összes tengelyt lineárisan skálázza. Ha például `0.5`-re állítod, az RT teljes behúzásával a robot fele sebességgel megy. Módosítható:
- A web UI-on (azonnal érvényes, elmenti)
- CLI-vel: `--speed-limit 0.7`
- `settings.py`-ban (alapértelmezett)

---

## LoRa titkosítás és handshake

### Csomag formátum

```
[device_id: 4B][nonce: 8B][ciphertext: variable][HMAC-SHA256: 32B]
```

- **AES-128 CTR** mód (pycryptodome)
- **HMAC-SHA256** hitelesítés (device_id + nonce + ciphertext felett)

### Handshake protokoll (robot kezdeményez)

```
Robot                    Controller
  │── 32 byte nonce ────►│
  │◄── HMAC(nonce,key) ──│
  │── {"status":"ok"} ──►│  (titkosított)
  │                       │
  │◄── {"cmd":"move"} ───│  (titkosított parancsok)
```

Ha a kapcsolat megszakad (pl. robot újraindul), a controller automatikusan újra elvégzi a handshake-t.

---

## Hibaelhárítás

### Gamepad nem található
```bash
# Ellenőrizd, hogy az USB eszköz látható-e
lsusb | grep -i xbox
ls /dev/input/event*

# Engedély ellenőrzése
groups $USER   # kell szerepeljen: input
sudo usermod -aG input $USER && newgrp input

# Kézi eszköz megadása
python main.py --device /dev/input/event2
```

### SPI / LoRa nem elérhető
```bash
# SPI ellenőrzése
ls /dev/spidev*   # /dev/spidev0.0 kell látszódjon

# Ha nem látszik, engedélyezd:
sudo raspi-config   # Interface Options → SPI → Enable
sudo reboot

# SPI csoport jogosultság
groups $USER   # kell szerepeljen: spi
sudo usermod -aG spi $USER && newgrp spi
```

### LoRa handshake timeout
- Ellenőrizd, hogy a robot fut-e (`python main.py` a BotCode mappában)
- Ellenőrizd, hogy a `LORA_FREQUENCY_MHZ`, `LORA_SPREADING_FACTOR`, és titkosítási kulcsok **pontosan** egyeznek-e mindkét oldalon
- Ellenőrizd a fizikai bekötést (különösen a CS és RST pineket)
- Próbáld közelebb vinni a két eszközt (ha nagy a távolság, csökkentsd a SF értéket: SF7 = leggyorsabb, legrövidebb hatótáv)

### Web UI nem érhető el
```bash
# Ellenőrizd, hogy a szerver fut
python main.py   # a log-ban kell legyen: "Beállítás UI: http://0.0.0.0:8081"

# Port ellenőrzése
ss -tlnp | grep 8081

# Tűzfal (ha engedélyezve van)
sudo ufw allow 8081
```

### `evdev` importálási hiba
```bash
pip install evdev
# Ha nem megy:
sudo apt-get install python3-evdev
```
