# Magyarok a Marson - Robotika Verseny

## Verseny rövid leírása

A **Magyarok a Marson** egy valós idejű robotikai verseny, ahol a csapatoknak egy saját építésű robotot kell készíteniük. A robot feladata attól függően változik, hogy éppen **PAC-MAN** vagy **GHOST** szerepben van.

A cél:
- PAC-MAN-ként a lehető leggyorsabban átjutni a kapukon
- GHOST-ként elkapni a PAC-MAN robotot

---

# Robot követelmények

A robotnak az alábbi feltételeknek kell megfelelnie:

- Maximális méret: **18cm x 18cm x 18cm**
- Maximális tömeg: **1kg**
- Meghajtás:
  - Tetszőleges számú és paraméterű **N20 motor**
- Kommunikáció:
  - Kizárólag **868MHz ISM sáv**
  - Az alkatrészcsomagban található **RFM95W** modul használatával
- Videó kapcsolat:
  - Engedélyezett WiFi sávok:
    - 2.4 GHz
    - 5.8 GHz
- Infra kommunikáció:
  - Maximum **1 db SFH4546 infra LED**
- A robot irányítása:
  - A pálya sarkából történik
  - A csapattagok nem sétálhatnak körbe a pálya körül jobb rálátás érdekében
- Kötelező elem:
  - 4mm-es hurkapálca rögzítési pont
  - PAC-MAN / GHOST zászló számára

---

# Játékmenet

A játék két szerepre bontható:

## PAC-MAN

Feladat:
- A lehető leggyorsabban átjutni a 8 kapun
- Pontokat gyűjteni
- Elkerülni a GHOST robotokat

Amikor a PAC-MAN átjut az utolsó kapun:
- Az időmérő megáll
- A fennmaradó idő pontokká alakul

## GHOST

Feladat:
- Fizikai érintkezéssel elkapni a PAC-MAN robotot
- Az elfogást a pálya fölötti kamera ellenőrzi

---

# Verseny menete

A pályán egyszerre:
- 4 csapat versenyez

Minden csapat:
- 1x PAC-MAN
- 3x GHOST szerepet kap egy fordulóban

A PAC-MAN elfogása:
- Fizikai ütközéssel történik
- Az idő ilyenkor megáll
- Az elkapó GHOST kivételével minden robot visszatér a startpozícióba
- Az elkapó GHOST kiesik a további üldözésből

Ha mindhárom GHOST sikeres:
- A PAC-MAN egyedül marad a pályán

---

# Példa játékszituáció

- A PAC-MAN robot 5 kapun már átjutott
- A `"destroyer"` nevű GHOST csapat elkapja
- Az óra megáll
- A destroyer pontot kap
- Mindenki visszaáll a starthelyre
- Már csak 2 GHOST marad a pályán
- A PAC-MAN végül teljesíti a maradék 3 kaput
- 86 másodperc marad az órán

Ez a 86 másodperc hozzáadódik a megszerzett pontokhoz.

---

# A kapuk működése

A kapu:
- Egy 4 bites vizuális kódot jelenít meg
- Közepén infravevő található
![target_image](https://www.magyarokamarson.hu/weblap2026/assets/img/gate1.png)
![target_gif](https://www.magyarokamarson.hu/weblap2026/assets/img/gate_code.gif)

Feladat:
- A megjelenített 3 jegyű hexadecimális számot vissza kell sugározni infrával

## Kód működése

- A kezdőérték: `F`
- Ezután:
  - 200ms-onként új számjegy jelenik meg
- A szám:
  - Nem lehet nulla
  - Nem ismétlődhet közvetlenül

Minden változás új számjegyet jelent.

A helyes kód visszasugárzása esetén:
- A kapu azonnal nyílik
- 10 másodpercig nyitva marad

---

# Példa kapukód


```text
Kód: CA6
```



A `CA6` visszasugárzásával:
- A kapu azonnal kinyílik

---

# Infra kommunikáció

Az adatátvitel:
- 1 db infra LED-del történik

Jel paraméterei:
- 38KHz modulált infrajel
- Soros kommunikáció:
  - 1200 baud
  - 8 bit
  - Paritás nélkül
![signal_image1](https://www.magyarokamarson.hu/weblap2026/assets/img/signal1.png)
![signal_image2](https://www.magyarokamarson.hu/weblap2026/assets/img/signal2.png)

A cél:
- Fél méterről is stabil érzékelés
- Kb. ±20° célzási tolerancia

---

# Hardver megoldás

Egy lehetséges megoldás:
- 555 IC generál 38KHz négyszögjelet
- Tranzisztor hajtja meg az infra LED-et
- A mikrokontroller soros jele kapcsolja a vivőfrekvenciát

Alternatíva:
- A 38KHz szoftverből is előállítható

A kapu infravevője:
- 950nm hullámhosszon a legérzékenyebb
- Az SFH4546 LED ehhez illeszkedik

---

# Infra sugárzási szabály

A kód:
- Maximum másodpercenként kétszer sugározható

Cél:
- Az infra „szmog" csökkentése a pályán

---

# Kód felismerése

A kapukód:
- Emberi szemmel is értelmezhető
- Gépi látással is feldolgozható

## Használt teszt hardver

- ESP32-S3 Sense
- Külső 2.4GHz antenna
- OV5640 kamera

A kamera:
- Videó streamet továbbított

A feldolgozás:
- OpenCV + Python

---

# Kódfejtési módszerek

A csapat több módszert is talált:

1. Manuális dekódolás
2. OpenCV alapú automatikus felismerés
3. Titkos módszer :)
4. További meglepetések a verseny napján

---

# Pálya

## Méretek

- Pálya mérete:
  - 8m x 8m
- Palánk magasság:
  - 13cm
- Kapu szélesség:
  - 50cm
- Legszűkebb átjáró:
  - 75cm
![terrain_image](https://www.magyarokamarson.hu/weblap2026/assets/img/palya_top_800.png)

A talaj:
- A díszaula járólap burkolata

Ajánlott:
- Jó tapadású gumikerekek

---

# Pontozás

## PAC-MAN pontok

- Minden első sikeres kapu:
  - 40 pont
- 8 kapu:
  - 320 pont maximum

A fennmaradó idő:
- 1 másodperc = 1 pont

### Példa

Ha valaki:
- 3 perc alatt teljesíti

Pontszám:

```text
320 + 120 = 440 pont
```



---

## GHOST pontok

A GHOST:
- Csak PAC-MAN elfogásért kap pontot

Számítás:

```text
Hátralévő másodpercek / 5
```



### Példa

Elfogás:
- 150 másodpercnél

Pont:

```text
150 / 5 = 30 pont
```



---

# Maximálisan szerezhető pont

## PAC-MAN


```text
320 pont kapukért
+ 300 pont időért
= 620 pont
```



## GHOST


```text
3 x 60 = 180 pont
```



## Elméleti maximum


```text
620 + 180 = 800 pont
```


---

# Technikai megszakítás

Ha technikai probléma miatt:
- Be kell menni a pályára

Akkor:
- A robot visszakerül a starthelyre
- 1 perc várakozás következik

---

# Verseny struktúra

20 csapat esetén:
- Egy forduló kb. 2 - 2.5 óra

Ezért:
- 2 forduló biztosan belefér egy napba

Minden csapat:
- 2x PAC-MAN
- 6x GHOST

A legjobb:
- 8 csapat középdöntőbe jut
- Majd következik a négyes döntő

---

# Díjazás

A díjak:
- Pontarányosan kerülnek kiosztásra

Tehát:
- Mindenki a megszerzett pontjai alapján részesül a díjalapból

---

# Tesztelés

A pályát:
- Péntek délután építik fel

Ezután:
- Egész éjszaka lehet tesztelni

---

# Köszönet

Köszönöm a „vén rókák" segítségét,
akik segítettek átnézni és véglegesíteni a kiírást.
