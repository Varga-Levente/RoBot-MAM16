# RoBot MAM16 — Felhasználói útmutató

Ez az útmutató segít a robot és a távirányító beüzemelésében, a kontroller kezelésében és az alapvető problémák megoldásában. Nem tartalmaz kódot vagy műszaki részleteket — csak azt, amit a használathoz tudni kell.

---

## Mi ez a rendszer?

A RoBot MAM16 egy távirányítós versenyrobot a Magyarok a Marson versenyre. A robot (Jetson Nano alapú) és a távirányító (Raspberry Pi alapú) LoRa rádión keresztül kommunikál egymással. A robot 4 Mecanum kerékkel rendelkezik, amelyekkel nemcsak előre-hátra és kanyarodni tud, hanem oldalra is csúszhat.

---

## Robot indítása

1. Kapcsold be a robotot (tápegység csatlakoztatása).
2. Várj ~30 másodpercet, amíg a rendszer elindul.
3. SSH-val vagy helyi terminállal futtasd:

```
cd RoBot-MAM16/BotCode
python3.8 main.py
```

A robot ezután vár a távirányítóra.

---

## Távirányító indítása

1. Csatlakoztasd az Xbox kontrollerhez tartozó USB kábelt a Raspberry Pi-be.
2. Futtasd:

```
cd RoBot-MAM16/BotController
python3 main.py
```

3. Néhány másodpercen belül a handshake megtörténik, és a kontroller aktív lesz.

---

## Vezérlési séma

| Gomb / Kar | Mit csinál? |
|---|---|
| **RT** (jobb ravasz) | Előremenet — minél jobban húzod, annál gyorsabb |
| **LT** (bal ravasz) | Hátramenet — minél jobban húzod, annál gyorsabban hátrál |
| **Bal joystick — vízszintes** | Kanyarodás — balra dől → balra fordul, jobbra dől → jobbra fordul |
| **Bal joystick — függőleges** | Nincs hatása |
| **Jobb joystick — vízszintes** | Oldalazás (Mecanum) — balra dől → balra csúszik, jobbra dől → jobbra csúszik |

> RT és LT egyszerre is nyomható — a robot a kettő különbségével mozog.

---

## Ugrás funkció (Y / A / X / B gombok)

Az ugrás egy rövid, teljes teljesítményű impulzus, amely segíthet a robot gyors pozícióváltásában.

| Gomb | Hatás |
|---|---|
| **Y** | Rövid előre ugrás |
| **A** | Rövid hátra ugrás |
| **X** | Rövid Mecanum bal oldalazás |
| **B** | Rövid Mecanum jobb oldalazás |

Az ugrás alapértelmezett időtartama **1 másodperc**, de a távirányító web felületén 0.1–5.0 másodperc között szabadon állítható.

---

## Web UI — Távirányító beállítások

Böngészőből nyisd meg:

```
http://<raspberry-pi-ip>:8081
```

Amit itt látni és beállítani lehet:

- **Állapotjelzők** — gamepad csatlakozva van-e, LoRa kapcsolat aktív-e, aktuális sebesség
- **Kontroller vizualizáció** — LT/RT trigger sávok, joystick pozíció, Mecanum keréksebesség top-down nézetben
- **Sebesség limit** — 0–100% között csúszkával állítható; azonnali hatással bír
- **Holtzona** — milyen kis elmozdulásokat hagyjon figyelmen kívül
- **Küldési sebesség** — hányszor küldjön parancsot másodpercenként (10/20/50 Hz)
- **Ugrás időtartam** — az Y/A/X/B gombok impulzushossza (0.1–5.0 s)
- **LoRa beállítások** — port, csatorna, teljesítmény (ha módosítasz, mentésre azonnal újrainicializálódik)

Minden mentett beállítás azonnal érvényes, és újraindítás után is megmarad.

---

## Web UI — Robot monitor

Böngészőből nyisd meg:

```
http://<jetson-ip>:8080
```

Amit itt látni lehet:

- **Élő videóstream** — a robot kamerájának képe teljes képernyőn
- **Debug panel** — vision állapot, felismert kapukód, motor sebességek, IR küldés visszajelzés
- **Log panel** — élő eseménynapló, összecsukható, színkódolt szintekkel (kék=info, narancs=figyelmeztetés, piros=hiba)
- **Kapukód megjelenítés** — a legutóbb felismert kapu kód látható a felületen

---

## Sebesség limit

A sebesség limit megakadályozza, hogy a robot teljes sebességgel menjen. Hasznos szűk helyeken vagy beállítás közben.

- A web UI-on (távirányító, port 8081) a „Sebesség limit" csúszkával állítható.
- 100% = teljes sebesség, 50% = fele sebesség.
- Mentés után azonnal érvényes, újraindítás után is megmarad.

---

## Hibaelhárítás

### A kontroller nem reagál (robot nem mozdul)

1. Ellenőrizd, hogy az Xbox kontroller USB-n csatlakozva van-e.
2. Ellenőrizd a távirányító web UI-ján (port 8081), hogy a „Gamepad" jelzőlámpa zöld-e.
3. Ha nem zöld: húzd ki és dugd vissza az USB kábelt, majd indítsd újra a `python3 main.py` parancsot.

### A robot nem megy, bár a kontroller csatlakozva van

1. Ellenőrizd a LoRa kapcsolat jelzőjét a web UI-on — legyen zöld.
2. Győződj meg róla, hogy a robot oldalán is fut a `main.py`.
3. Vidd közelebb a két eszközt — a LoRa hatótávolsága csökkent akadályok esetén.
4. Ellenőrizd, hogy a sebesség limit nem 0%-ra van-e állítva.

### A videóstream nem jelenik meg

1. Ellenőrizd, hogy a robot és a böngésző ugyanazon a hálózaton van-e.
2. Próbálj meg ráfrissíteni az oldalra (F5).
3. Ha más hálózatról csatlakozol, szükség lehet STUN szerverre — kérdezd a csapat technikusát.

### Az ugrás gomb nem csinál semmit

1. Ellenőrizd, hogy a LoRa kapcsolat aktív-e.
2. Ellenőrizd, hogy az ugrás időtartam nem 0-ra van-e állítva a web UI-on.
