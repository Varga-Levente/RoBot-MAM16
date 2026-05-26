# MAM16 BotController — Távirányító szoftver

Xbox One USB kontroller → Raspberry Pi 3B+ → E22-900T22D-V2 LoRa → robot.  
Platform: **Raspberry Pi 3B+** | Nyelv: **Python 3.x**

---

## Architektúra

```
main.py
  │
  ├── ControllerState     ← megosztott állapot (gamepad, LoRa, linear/angular/lateral)
  │
  ├── GamepadReader  ──── evdev Xbox One USB → (linear, angular, lateral, left_y=0, jump_dir)
  ├── LoraSender     ──── E22-900T22D-V2 UART, AES-128 + HMAC, handshake + küldés
  └── ControllerWebServer ← aiohttp beállítás UI + config.json perzisztencia
```

### Adatfolyam

```
Xbox One (USB)
    │  evdev ABS_X / ABS_Z / ABS_RZ / ABS_RX
    ▼
GamepadReader.read_state()
    │  (linear, angular, lateral, left_y=0, jump_dir) −1.0 .. 1.0
    ▼  deadzone + speed_limit szűrés
LoraSender.send_command()
    │  JSON → AES-128 CTR → HMAC-SHA256
    ▼
E22-900T22D-V2 LoRa 868.125 MHz
    │
    ▼
Robot (BotCode) → motor_controller (Mecanum)
```

### Komponensek

| Fájl | Felelősség |
|------|-----------|
| `main.py` | asyncio főhurok, handshake → vezérlés → reconnect |
| `settings.py` | Minden konfigurálható paraméter |
| `controller_input.py` | evdev Xbox gamepad olvasó, deadzone, speed limit |
| `lora_sender.py` | E22-900T22D-V2 UART, titkosítás, challenge-response handshake |
| `web_server.py` | aiohttp beállítás UI, config.json perzisztencia |
| `web/` | Sötét glassmorphism UI, live joystick canvas, Mecanum vizualizáció |

---

## Hardver előfeltételek

### Alkatrészek

| Alkatrész | Megjegyzés |
|-----------|-----------|
| Raspberry Pi 3B+ | Bármilyen RPi 3/4 működik |
| E22-900T22D-V2 LoRa modul | Azonos mint a roboron (868.125 MHz, ch18) |
| Xbox One kontroller | Pulse Red vagy bármely USB-s Xbox One típus |
| USB kábel | Mikro-USB, kontroller csatlakozáshoz |

### GPIO kiosztás — E22-900T22D-V2 UART bekötés (BCM számozás)

| E22 pin | RPi GPIO | RPi fizikai pin | Funkció           |
|---------|----------|-----------------|-------------------|
| TX      | RX (GPIO 15) | 10          | UART fogadás      |
| RX      | TX (GPIO 14) | 8           | UART küldés       |
| M0      | GPIO 20  | 38              | Mód vezérlés      |
| M1      | GPIO 21  | 40              | Mód vezérlés      |
| AUX     | GPIO 16  | 36              | Kész jelző        |
| VCC     | 3.3V     | 1               | Tápfeszültség     |
| GND     | GND      | 6               | Föld              |

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

# 4. UART engedélyezése
sudo raspi-config
# Interface Options → Serial Port → No (login shell), Yes (serial hardware)

# 5. GPIO jogosultság
sudo usermod -aG gpio,dialout,input $USER
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
- **pyserial:** Az E22-900T22D-V2 UART kommunikációhoz szükséges (`pip install pyserial`).

---

## Beállítás (`settings.py`)

A `settings.py` két szekciót tartalmaz.

### LoRa szekció — azonos kell legyen a robot `BotCode/settings.py`-val!

```python
# LoRa pin kiosztás (settings.py-ban állítható, webes UI-ból is)
LORA_UART_PORT = "/dev/ttyAMA0"  # ← RPi UART port
LORA_M0_PIN    = 20              # ← BCM GPIO
LORA_M1_PIN    = 21              # ← BCM GPIO
LORA_AUX_PIN   = 16             # ← BCM GPIO
LORA_CHANNEL   = 18             # csatorna 18 = 868.125 MHz
LORA_TX_POWER  = 22             # dBm, max 22
LORA_DEVICE_ID = b"\xDE\xAD\xBE\xEF"   # ← egyezzen a robottal
LORA_AES_KEY   = b"change_me_16byte"     # ← cseréld le!
LORA_HMAC_KEY  = b"change_me_hmac_key_32bytes!!"  # ← cseréld le!
```

> **Verseny előtt:** A `LORA_AES_KEY` és `LORA_HMAC_KEY` értékeket cseréld le egyedi kulcsokra, és győződj meg róla, hogy a robot oldalon (`BotCode/settings.py`) ugyanazok az értékek szerepelnek. A `LORA_CHANNEL` értéknek szintén egyeznie kell mindkét oldalon.

### Controller szekció

```python
CTRL_SPEED_LIMIT    = 1.0    # 0.0–1.0: sebesség korlát (100% = teljes sebesség)
CTRL_DEADZONE       = 0.05   # holtzona normalizált értékben
CTRL_SEND_HZ        = 20     # parancsküldés frekvenciája
CTRL_GAMEPAD_DEVICE = ""     # "" = automatikus keresés
CTRL_JUMP_DURATION  = 1.0    # ugrás impulzus hossza másodpercben (0.1–5.0s)
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

## Vezérlés

### Tengely kiosztás

| Gomb / Tengely | Funkció | Irány |
|----------------|---------|-------|
| **RT** (jobb trigger) | Előremenet (linear+) | Minél jobban húzva → annál gyorsabb |
| **LT** (bal trigger) | Hátramenet (linear−) | Minél jobban húzva → annál lassabb/hátrább |
| **Bal joystick X** | Kanyarodás (angular) | Bal → balra fordul, Jobb → jobbra fordul |
| **Bal joystick Y** | Figyelmen kívül hagyva | — |
| **Jobb joystick X** | Mecanum oldalazás (lateral) | Bal → balra csúszik, Jobb → jobbra csúszik |

> RT és LT egyszerre is húzható — a nettó lineáris sebesség az RT−LT különbsége.

### Ugrás (burst) gombok

| Gomb | Funkció |
|------|---------|
| **Y** | 1 mp-es előre ugrás (burst) |
| **A** | 1 mp-es hátra ugrás |
| **X** | 1 mp-es Mecanum bal oldalazás burst |
| **B** | 1 mp-es Mecanum jobb oldalazás burst |

Az ugrás időtartama alapértelmezetten **1.0 s**, a web UI-ból 0.1–5.0 s között állítható. A `duration` mező a JSON payloadban kerül elküldésre, a robot ezt veszi figyelembe.

### Sebesség limit

A `CTRL_SPEED_LIMIT` (0.0–1.0) az összes tengelyt lineárisan skálázza. Ha például `0.5`-re állítod, az RT teljes behúzásával a robot fele sebességgel megy. Módosítható:
- A web UI-on (azonnal érvényes, elmenti)
- CLI-vel: `--speed-limit 0.7`
- `settings.py`-ban (alapértelmezett)

---

## Beállítás web UI

Indítás után a böngészőben elérhető:

```
http://<raspberry-pi-ip>:8081
```

### Funkciók

- **Valós idejű állapot:** LT/RT trigger bar-ok, joystick canvas (angular/lateral), LoRa és gamepad kapcsolat státusz, sebesség kijelző
- **Kontroller vizualizáció:** Y/A/X/B gombállapot jelzők, Lat/LY csúszkák
- **Mecanum robot vizualizáció canvas:** top-down nézet, 4 kerék (FL/FR/RL/RR) valós idejű sebességgel és iránnyal, mozgásnyilak, gombállapotok
- **Vezérlés beállítások:** sebesség limit slider (0–100%), holtzona slider, küldési sebesség (10/20/50 Hz), ugrás időtartam slider (0.1–5.0 s), gamepad eszköz
- **LoRa beállítások:** UART port, M0/M1/AUX pin (BCM), csatorna (0–80), TX teljesítmény — mentés után automatikusan újrainicializálja a LoRa modult
- **Perzisztencia:** minden mentés azonnal érvényes futás közben, és `config.json`-ba íródik (megmarad újraindítás után)

---

## LoRa titkosítás és handshake

### Csomag formátum

```
[device_id: 4B][nonce: 8B][ciphertext: variable][HMAC-SHA256: 32B]
```

Keret szintű burkolás:
```
[0xAA][0x55][len_hi][len_lo][payload]
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

### UART / LoRa nem elérhető

```bash
# UART ellenőrzése
ls -la /dev/ttyAMA0
python3 -c "import serial; s=serial.Serial('/dev/ttyAMA0',9600); print('OK')"

# UART engedélyezése (ha nem fut)
sudo raspi-config   # Interface Options → Serial Port → No / Yes

# Felhasználói jogosultság
sudo usermod -a -G dialout $USER
```

### LoRa handshake timeout
- Ellenőrizd, hogy a robot fut-e (`python main.py` a BotCode mappában)
- Ellenőrizd, hogy a `LORA_CHANNEL` és a titkosítási kulcsok **pontosan** egyeznek-e mindkét oldalon
- Ellenőrizd a fizikai bekötést (különösen az M0, M1 és AUX pineket)
- Próbáld közelebb vinni a két eszközt

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
