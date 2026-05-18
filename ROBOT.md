# Robot specifikáció

## Számítási egység

- **Nvidia Jetson Nano Dev Kit**
  - A robot fő vezérlőegysége
  - Fedélzeti gépi látás és kommunikáció futtatása

---

## Kamera

- **IMX219 160 fokos széglátószögű kamera**
  - Kapu villogásának felismerése OpenCV segítségével
  - Élő videóstream WebRTC-n keresztül

---

## Tápellátás

- **21700 cellás 3S1P akkumulátor csomag**
  - 11.1V névleges feszültség
  - A teljes robot tápellátásáért felelős

---

## Megjelenítő

- **0.91 inches 128x32 pixeles OLED kijelző**
  - Robot IP-cím megjelenítése
  - Egyéb állapotinformációk kijelzése (akkufeszültség, státusz stb.)

---

## Motorvezérlő

- **DRV8833 motor driver**
  - 4 db N20 motort hajt meg
  - Kétirányú vezérlés, PWM alapú sebességszabályozás

---

## Meghajtás

- **4 db N20 motor**
  - A verseny szabályaival összhangban tetszőleges paraméterű N20 motorok

---

## Kommunikáció

- **RFM95W LoRa modul** (868 MHz ISM sáv)
  - Titkosított kapcsolat a saját távirányítóval
  - A robot kizárólag az azonosított saját távirányítóra reagál
  - Idegen jelre nem reagál

---

## Váz

- **JetBot alap átalakított változata**
  - Saját tervezésű, 3D nyomtatott alváz
  - Anyag: **PET-G** vagy **ABS**

---

## Szoftver

### Gépi látás

- **OpenCV** (Python)
  - Kamera képéből valós időben felismeri a kapu 4 bites LED villogását
  - Dekódolja a 3 jegyű hexadecimális kapukódot
  - Átadja az infra modulnak a visszasugárzandó kódot

### Infra kommunikáció

- 38KHz modulált infrajel
- 1200 baud, 8 bit, paritás nélkül
- Maximum másodpercenként 2x sugárzás

### Élő videóstream

- **WebRTC** alapú böngészős élő kép
  - Böngészőből megtekinthető kamerakép
  - Overlayként megjelenik:
    - Az aktuálisan felismert kapukód
    - Az éppen sugárzott infrakód
