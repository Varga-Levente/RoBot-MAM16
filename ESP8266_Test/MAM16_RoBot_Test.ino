// =============================================================================
//  RoBot MAM16 — ESP8266 Teszt firmware
//  Arduino IDE | Board: NodeMCU 1.0 (ESP-12E Module)
//
//  Funkciók:
//    - WiFi Access Point (hotspot)
//    - Webes vezérlőfelület (WASD + QE + X + L)
//    - Mecanum kerekek (DRV8833 driver)
//    - Sebesség csúszka (0–100%)
//    - LED: BE / KI / Villogás
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
      gap: 18px;
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

    /* ── Sebesség csúszka ── */
    .speed-row {
      display: flex;
      align-items: center;
      gap: 10px;
      background: #16213e;
      border: 1px solid #0f3460;
      border-radius: 8px;
      padding: 10px 16px;
      min-width: 280px;
    }
    .speed-row label { font-size: 0.85em; color: #aaa; white-space: nowrap; }
    .speed-row input[type=range] {
      flex: 1;
      accent-color: #00d4ff;
      cursor: pointer;
    }
    #speed-val { color: #00d4ff; font-weight: bold; min-width: 36px; text-align: right; }

    /* ── Mozgás gombok ── */
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

    /* ── LED panel ── */
    .led-panel {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      background: #16213e;
      border: 1px solid #0f3460;
      border-radius: 8px;
      padding: 12px 20px;
      min-width: 280px;
    }
    .led-panel .label { font-size: 0.8em; color: #aaa; }
    .led-panel .indicator {
      width: 28px; height: 28px;
      border-radius: 50%;
      background: #2a2000;
      border: 2px solid #554400;
      transition: background 0.15s, box-shadow 0.15s;
    }
    .led-panel .indicator.on {
      background: #ffcc00;
      border-color: #ffee44;
      box-shadow: 0 0 10px #ffcc00aa;
    }
    .led-btns { display: flex; gap: 8px; }
    .led-btns .btn { width: 80px; height: 44px; font-size: 0.85em; }
    .btn.led-on   { border-color: #44ff88; color: #44ff88; }
    .btn.led-on.active   { background: #003322; }
    .btn.led-off  { border-color: #ff6644; color: #ff6644; }
    .btn.led-off.active  { background: #330d00; }
    .btn.led-blink { border-color: #ffcc00; color: #ffcc00; }
    .btn.led-blink.active { background: #2a2000; border-color: #ffee44; color: #ffee44; }

    .extra { display: flex; gap: 8px; }
    .extra .btn { width: 148px; height: 54px; font-size: 0.95em; }

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

  <!-- Sebesség csúszka -->
  <div class="speed-row">
    <label>Sebesség:</label>
    <input type="range" id="speed" min="0" max="100" value="80">
    <span id="speed-val">80%</span>
  </div>

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

  <!-- Emergency STOP -->
  <div class="extra">
    <button class="btn stop" id="btn-x">X<small>EMERGENCY STOP</small></button>
  </div>

  <!-- LED panel -->
  <div class="led-panel">
    <span class="label">LED állapot</span>
    <div class="indicator" id="led-indicator"></div>
    <div class="led-btns">
      <button class="btn led-on"    id="btn-led-on">BE</button>
      <button class="btn led-off"   id="btn-led-off">KI</button>
      <button class="btn led-blink" id="btn-led-blink">Villog<br><small>1s / 1s</small></button>
    </div>
  </div>

  <div class="hint">
    Billentyűzet: W A S D &nbsp;|&nbsp; Q E &nbsp;|&nbsp; X &nbsp;|&nbsp; L = villogás<br>
    Nyomva tartva folyamatos mozgás &nbsp;•&nbsp; X = azonnali leállás
  </div>

<script>
  const MOVE_KEYS = ['w','a','s','d','q','e'];
  let activeKey  = null;
  let moveTimer  = null;
  let ledMode    = 'off';   // 'off' | 'on' | 'blink'
  let speedPct   = 80;

  // ── Sebesség ──
  const speedSlider = document.getElementById('speed');
  const speedLabel  = document.getElementById('speed-val');
  speedSlider.addEventListener('input', () => {
    speedPct = parseInt(speedSlider.value);
    speedLabel.textContent = speedPct + '%';
    fetch('/speed?v=' + speedPct).catch(() => {});
  });

  // ── Mozgás ──
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

  document.addEventListener('keydown', e => {
    if (e.repeat) return;
    const k = e.key.toLowerCase();
    if (MOVE_KEYS.includes(k))  { e.preventDefault(); startMove(k); }
    else if (k === 'x')         { e.preventDefault(); stopMove(); }
    else if (k === 'l')         { e.preventDefault(); setLed('blink'); }
  });
  document.addEventListener('keyup', e => {
    const k = e.key.toLowerCase();
    if (MOVE_KEYS.includes(k) && k === activeKey) stopMove();
  });

  document.querySelectorAll('.btn[data-key]').forEach(btn => {
    const k = btn.dataset.key;
    btn.addEventListener('pointerdown', () => startMove(k));
    btn.addEventListener('pointerup',   stopMove);
    btn.addEventListener('pointerleave', stopMove);
  });
  document.getElementById('btn-x').addEventListener('pointerdown', () => { stopMove(); send('x'); });

  // ── LED ──
  function setLed(mode) {
    ledMode = mode;
    fetch('/led?m=' + mode).catch(() => {});
    document.getElementById('btn-led-on').classList.toggle('active',    mode === 'on');
    document.getElementById('btn-led-off').classList.toggle('active',   mode === 'off');
    document.getElementById('btn-led-blink').classList.toggle('active', mode === 'blink');
  }

  document.getElementById('btn-led-on').addEventListener('click',    () => setLed('on'));
  document.getElementById('btn-led-off').addEventListener('click',   () => setLed('off'));
  document.getElementById('btn-led-blink').addEventListener('click', () => setLed('blink'));

  // LED visszajelző polling (500ms-enként kérdezi az ESP-t)
  setInterval(() => {
    fetch('/ledstate').then(r => r.text()).then(s => {
      document.getElementById('led-indicator').classList.toggle('on', s === '1');
    }).catch(() => {});
  }, 500);
</script>
</body>
</html>
)rawhtml";

// ── Globális állapot ──────────────────────────────────────────────────────────

ESP8266WebServer server(80);

const uint8_t IN1[4] = { MOTOR_FL_IN1, MOTOR_FR_IN1, MOTOR_RL_IN1, MOTOR_RR_IN1 };
const uint8_t IN2[4] = { MOTOR_FL_IN2, MOTOR_FR_IN2, MOTOR_RL_IN2, MOTOR_RR_IN2 };

int  motorSpeed     = MOTOR_SPEED;   // 0–1023, felülírható a /speed végponton

// LED állapot: 0=ki, 1=be, 2=villog
uint8_t ledMode     = 0;
bool    ledState    = false;
unsigned long ledLastToggle = 0;

// ── Motor vezérlés ────────────────────────────────────────────────────────────

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

void setMecanum(float linear, float angular, float lateral) {
    float fl = linear + lateral + angular;
    float fr = linear - lateral - angular;
    float rl = linear - lateral + angular;
    float rr = linear + lateral - angular;

    float mx = max(max(abs(fl), abs(fr)), max(abs(rl), abs(rr)));
    if (mx > 1.0f) { fl /= mx; fr /= mx; rl /= mx; rr /= mx; }

    setMotor(0, (int)(fl * motorSpeed));
    setMotor(1, (int)(fr * motorSpeed));
    setMotor(2, (int)(rl * motorSpeed));
    setMotor(3, (int)(rr * motorSpeed));
}

void emergencyStop() {
    for (uint8_t i = 0; i < 4; i++) {
        analogWrite(IN1[i], 0);
        analogWrite(IN2[i], 0);
    }
}

// ── LED ───────────────────────────────────────────────────────────────────────

void applyLed(bool on) {
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

    if      (key == "w") setMecanum( 1.0f,  0.0f,  0.0f);
    else if (key == "s") setMecanum(-1.0f,  0.0f,  0.0f);
    else if (key == "a") setMecanum( 0.0f,  0.0f, -1.0f);
    else if (key == "d") setMecanum( 0.0f,  0.0f,  1.0f);
    else if (key == "q") setMecanum( 0.0f, -1.0f,  0.0f);
    else if (key == "e") setMecanum( 0.0f,  1.0f,  0.0f);
    else if (key == "x") emergencyStop();

    server.send(200, "text/plain", "ok");
}

void handleSpeed() {
    if (!server.hasArg("v")) { server.send(400, "text/plain", "missing v"); return; }
    int pct = constrain(server.arg("v").toInt(), 0, 100);
    motorSpeed = (pct * 1023) / 100;
    server.send(200, "text/plain", "ok");
}

void handleLed() {
    if (!server.hasArg("m")) { server.send(400, "text/plain", "missing m"); return; }
    String mode = server.arg("m");

    if (mode == "on")    { ledMode = 1; applyLed(true); }
    else if (mode == "off")   { ledMode = 0; applyLed(false); }
    else if (mode == "blink") { ledMode = 2; }

    server.send(200, "text/plain", "ok");
}

void handleLedState() {
    server.send(200, "text/plain", ledState ? "1" : "0");
}

// ── Setup ─────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.println("\nMAM16 RoBot ESP8266 Teszt indul...");

    analogWriteFreq(MOTOR_PWM_FREQ);
    analogWriteRange(1023);
    for (uint8_t i = 0; i < 4; i++) {
        pinMode(IN1[i], OUTPUT);
        pinMode(IN2[i], OUTPUT);
        analogWrite(IN1[i], 0);
        analogWrite(IN2[i], 0);
    }

    pinMode(LED_PIN, OUTPUT);
    applyLed(false);

    WiFi.softAP(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("AP elindult — IP: ");
    Serial.println(WiFi.softAPIP());

    server.on("/",         handleRoot);
    server.on("/cmd",      handleCmd);
    server.on("/speed",    handleSpeed);
    server.on("/led",      handleLed);
    server.on("/ledstate", handleLedState);
    server.begin();
    Serial.println("Webszerver fut — nyisd meg: http://192.168.4.1");
}

// ── Loop ──────────────────────────────────────────────────────────────────────

void loop() {
    server.handleClient();

    if (ledMode == 2) {
        unsigned long now = millis();
        if (now - ledLastToggle >= LED_BLINK_MS) {
            ledLastToggle = now;
            applyLed(!ledState);
        }
    }
}
