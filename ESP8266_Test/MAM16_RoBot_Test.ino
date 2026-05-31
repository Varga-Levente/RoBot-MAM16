// =============================================================================
//  RoBot MAM16 — ESP8266 Teszt firmware
//  Arduino IDE | Board: NodeMCU 1.0 (ESP-12E Module)
//
//  Funkciók:
//    - WiFi Access Point (hotspot)
//    - Webes vezérlőfelület (WASD + QE + X + L)
//    - Mecanum kerekek (DRV8833 driver)
//    - LED villogtatás
//
//  Szükséges könyvtár: ESP8266WiFi (beépített az ESP8266 board csomagban)
// =============================================================================

#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include "config.h"

// ── Webes HTML oldal ──────────────────────────────────────────────────────────

static const char INDEX_HTML[] PROGMEM = R"rawhtml(
<!DOCTYPE html>
<html lang="hu">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MAM16 RoBot Teszt</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #1a1a2e;
      color: #eee;
      font-family: monospace;
      display: flex;
      flex-direction: column;
      align-items: center;
      min-height: 100vh;
      padding: 20px;
      gap: 20px;
    }
    h1 { font-size: 1.4em; color: #00d4ff; letter-spacing: 2px; }
    #status {
      background: #16213e;
      border: 1px solid #0f3460;
      border-radius: 8px;
      padding: 10px 20px;
      font-size: 0.9em;
      color: #aaa;
      min-width: 280px;
      text-align: center;
    }
    #status span { color: #00d4ff; font-weight: bold; }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, 70px);
      grid-template-rows: repeat(3, 70px);
      gap: 8px;
    }
    .btn {
      background: #16213e;
      border: 2px solid #0f3460;
      border-radius: 8px;
      color: #eee;
      font-size: 1.1em;
      font-family: monospace;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 2px;
      user-select: none;
      transition: background 0.1s, border-color 0.1s;
    }
    .btn small { font-size: 0.55em; color: #888; }
    .btn:active, .btn.pressed { background: #0f3460; border-color: #00d4ff; color: #00d4ff; }
    .btn.stop  { border-color: #ff4444; color: #ff4444; }
    .btn.stop:active, .btn.stop.pressed { background: #3a0000; border-color: #ff6666; }
    .btn.led   { border-color: #ffcc00; color: #ffcc00; }
    .btn.led:active, .btn.led.pressed { background: #2a2000; border-color: #ffee44; }
    .btn.led.active { background: #2a2000; border-color: #ffee44; color: #ffee44; }
    .extra {
      display: flex;
      gap: 8px;
    }
    .extra .btn { width: 100px; height: 70px; }
    .hint {
      font-size: 0.75em;
      color: #555;
      text-align: center;
      line-height: 1.6;
    }
  </style>
</head>
<body>
  <h1>MAM16 RoBot Teszt</h1>

  <div id="status">Parancs: <span id="cmd">–</span></div>

  <!-- WASD + QE gombmátrix -->
  <div class="grid">
    <button class="btn" id="btn-q" data-key="q">Q<small>Fordulj &#8592;</small></button>
    <button class="btn" id="btn-w" data-key="w">W<small>Előre</small></button>
    <button class="btn" id="btn-e" data-key="e">E<small>Fordulj &#8594;</small></button>
    <button class="btn" id="btn-a" data-key="a">A<small>Csúszj &#8592;</small></button>
    <button class="btn" id="btn-s" data-key="s">S<small>Hátra</small></button>
    <button class="btn" id="btn-d" data-key="d">D<small>Csúszj &#8594;</small></button>
    <div></div>
    <div></div>
    <div></div>
  </div>

  <!-- X stop + L LED -->
  <div class="extra">
    <button class="btn stop" id="btn-x" data-key="x">X<small>E-STOP</small></button>
    <button class="btn led"  id="btn-l" data-key="l">L<small>LED</small></button>
  </div>

  <div class="hint">
    Billentyűzet: W A S D &nbsp;|&nbsp; Q E &nbsp;|&nbsp; X &nbsp;|&nbsp; L<br>
    Nyomva tartva folyamatos mozgás • X = azonnali leállás
  </div>

<script>
  const MOVE_KEYS = ['w','a','s','d','q','e'];
  let activeKey = null;
  let ledOn = false;
  let moveTimer = null;

  function send(cmd) {
    document.getElementById('cmd').textContent = cmd.toUpperCase();
    fetch('/cmd?k=' + cmd).catch(() => {});
  }

  function startMove(key) {
    if (activeKey === key) return;
    stopMove();
    activeKey = key;
    document.getElementById('btn-' + key)?.classList.add('pressed');
    send(key);
    moveTimer = setInterval(() => send(key), 150);
  }

  function stopMove() {
    if (!activeKey) return;
    document.getElementById('btn-' + activeKey)?.classList.remove('pressed');
    clearInterval(moveTimer);
    moveTimer = null;
    activeKey = null;
    send('x');
  }

  // Billentyűzet
  document.addEventListener('keydown', e => {
    if (e.repeat) return;
    const k = e.key.toLowerCase();
    if (MOVE_KEYS.includes(k)) { e.preventDefault(); startMove(k); }
    else if (k === 'x') { e.preventDefault(); stopMove(); send('x'); }
    else if (k === 'l') { e.preventDefault(); toggleLed(); }
  });
  document.addEventListener('keyup', e => {
    const k = e.key.toLowerCase();
    if (MOVE_KEYS.includes(k) && k === activeKey) stopMove();
  });

  // Érintő / egér gombok
  document.querySelectorAll('.btn[data-key]').forEach(btn => {
    const k = btn.dataset.key;
    if (k === 'l') {
      btn.addEventListener('click', toggleLed);
      return;
    }
    if (k === 'x') {
      btn.addEventListener('pointerdown', () => { stopMove(); send('x'); });
      return;
    }
    btn.addEventListener('pointerdown', () => startMove(k));
    btn.addEventListener('pointerup',   stopMove);
    btn.addEventListener('pointerleave', stopMove);
  });

  function toggleLed() {
    ledOn = !ledOn;
    document.getElementById('btn-l').classList.toggle('active', ledOn);
    send('l');
  }
</script>
</body>
</html>
)rawhtml";

// ── Globális állapot ──────────────────────────────────────────────────────────

ESP8266WebServer server(80);

// Motor pin tömbök [FL, FR, RL, RR]
const uint8_t IN1[4] = { MOTOR_FL_IN1, MOTOR_FR_IN1, MOTOR_RL_IN1, MOTOR_RR_IN1 };
const uint8_t IN2[4] = { MOTOR_FL_IN2, MOTOR_FR_IN2, MOTOR_RL_IN2, MOTOR_RR_IN2 };

bool ledBlinking   = false;
bool ledState      = false;
unsigned long ledLastToggle = 0;

// ── Motor vezérlés ────────────────────────────────────────────────────────────

// speed: -1023 .. +1023
void setMotor(uint8_t id, int speed) {
    speed = constrain(speed, -1023, 1023);
    if (speed > 0) {
        analogWrite(IN1[id], speed);
        analogWrite(IN2[id], 0);
    } else if (speed < 0) {
        analogWrite(IN1[id], 0);
        analogWrite(IN2[id], -speed);
    } else {
        analogWrite(IN1[id], 0);
        analogWrite(IN2[id], 0);
    }
}

// Mecanum kinematika — azonos a Jetson Nano kóddal
// linear: előre/hátra, angular: fordulás, lateral: oldalra csúszás
void setMecanum(float linear, float angular, float lateral) {
    float fl = linear + lateral + angular;
    float fr = linear - lateral - angular;
    float rl = linear - lateral + angular;
    float rr = linear + lateral - angular;

    // Normalizálás: max érték nem lépheti túl az 1.0-t
    float mx = max(max(abs(fl), abs(fr)), max(abs(rl), abs(rr)));
    if (mx > 1.0f) { fl /= mx; fr /= mx; rl /= mx; rr /= mx; }

    setMotor(0, (int)(fl * MOTOR_SPEED));
    setMotor(1, (int)(fr * MOTOR_SPEED));
    setMotor(2, (int)(rl * MOTOR_SPEED));
    setMotor(3, (int)(rr * MOTOR_SPEED));
}

void emergencyStop() {
    for (uint8_t i = 0; i < 4; i++) {
        analogWrite(IN1[i], 0);
        analogWrite(IN2[i], 0);
    }
}

// ── LED ───────────────────────────────────────────────────────────────────────

void setLed(bool on) {
    ledState = on;
#if LED_ACTIVE_LOW
    digitalWrite(LED_PIN, on ? LOW : HIGH);
#else
    digitalWrite(LED_PIN, on ? HIGH : LOW);
#endif
}

// ── HTTP kezelők ──────────────────────────────────────────────────────────────

void handleRoot() {
    server.send_P(200, "text/html", INDEX_HTML);
}

void handleCmd() {
    if (!server.hasArg("k")) { server.send(400, "text/plain", "missing k"); return; }

    String key = server.arg("k");
    key.toLowerCase();

    if      (key == "w") setMecanum( 1.0f,  0.0f,  0.0f);   // Előre
    else if (key == "s") setMecanum(-1.0f,  0.0f,  0.0f);   // Hátra
    else if (key == "a") setMecanum( 0.0f,  0.0f, -1.0f);   // Mecanum balra
    else if (key == "d") setMecanum( 0.0f,  0.0f,  1.0f);   // Mecanum jobbra
    else if (key == "q") setMecanum( 0.0f, -1.0f,  0.0f);   // Fordulás balra
    else if (key == "e") setMecanum( 0.0f,  1.0f,  0.0f);   // Fordulás jobbra
    else if (key == "x") emergencyStop();                     // Emergency STOP
    else if (key == "l") {                                    // LED villogás toggle
        ledBlinking = !ledBlinking;
        if (!ledBlinking) setLed(false);
    }

    server.send(200, "text/plain", "ok");
}

// ── Setup ─────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.println("\nMAM16 RoBot ESP8266 Teszt indul...");

    // Motor pinek
    analogWriteFreq(MOTOR_PWM_FREQ);
    analogWriteRange(1023);
    for (uint8_t i = 0; i < 4; i++) {
        pinMode(IN1[i], OUTPUT);
        pinMode(IN2[i], OUTPUT);
        analogWrite(IN1[i], 0);
        analogWrite(IN2[i], 0);
    }

    // LED
    pinMode(LED_PIN, OUTPUT);
    setLed(false);

    // WiFi AP
    WiFi.softAP(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("AP elindult — IP: ");
    Serial.println(WiFi.softAPIP());

    // Webszerver
    server.on("/",    handleRoot);
    server.on("/cmd", handleCmd);
    server.begin();
    Serial.println("Webszerver fut — nyisd meg: http://192.168.4.1");
}

// ── Loop ──────────────────────────────────────────────────────────────────────

void loop() {
    server.handleClient();

    // LED villogtatás (nem blokkoló)
    if (ledBlinking) {
        unsigned long now = millis();
        if (now - ledLastToggle >= LED_BLINK_MS) {
            ledLastToggle = now;
            setLed(!ledState);
        }
    }
}
