'use strict';

// ── Joystick canvas rajzolás ──────────────────────────────────────────────────
const joyCanvas = document.getElementById('joy-canvas');
const joyCtx    = joyCanvas.getContext('2d');

function drawJoystick(linear, angular) {
  const W = joyCanvas.width, H = joyCanvas.height;
  const cx = W / 2, cy = H / 2, R = W / 2 - 4;
  joyCtx.clearRect(0, 0, W, H);

  // Crosshair
  joyCtx.strokeStyle = 'rgba(255,255,255,0.12)';
  joyCtx.lineWidth = 1;
  joyCtx.beginPath(); joyCtx.moveTo(cx, 4); joyCtx.lineTo(cx, H - 4); joyCtx.stroke();
  joyCtx.beginPath(); joyCtx.moveTo(4, cy); joyCtx.lineTo(W - 4, cy); joyCtx.stroke();

  // Dot
  const px = cx + angular * R * 0.85;
  const py = cy - linear  * R * 0.85;
  const isActive = Math.abs(linear) > 0.01 || Math.abs(angular) > 0.01;

  joyCtx.beginPath();
  joyCtx.arc(px, py, 6, 0, Math.PI * 2);
  joyCtx.fillStyle = isActive ? '#60a5fa' : 'rgba(255,255,255,0.3)';
  if (isActive) joyCtx.shadowColor = '#60a5fa', joyCtx.shadowBlur = 8;
  else          joyCtx.shadowBlur = 0;
  joyCtx.fill();
  joyCtx.shadowBlur = 0;
}

drawJoystick(0, 0);

// ── Status poll ───────────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const r  = await fetch('/api/status');
    const st = await r.json();

    const dotG = document.getElementById('dot-gamepad');
    const dotL = document.getElementById('dot-lora');
    dotG.className = 'dot ' + (st.gamepad_connected    ? 'ok' : 'err');
    const loraOk = st.lora_hw_ok !== false;
    dotL.className = 'dot ' + (st.lora_authenticated ? 'ok' : loraOk ? 'err' : '');
    document.getElementById('lbl-gamepad').textContent =
      'Gamepad: ' + (st.gamepad_connected  ? 'OK' : 'nincs');
    document.getElementById('lbl-lora').textContent =
      'LoRa: ' + (st.lora_authenticated ? 'Hitelesítve' : loraOk ? 'Várakozás...' : 'Nem csatlakoztatva');
    document.getElementById('speed-badge').textContent =
      'Sebesség: ' + Math.round(st.speed_limit * 100) + '%';

    document.getElementById('val-linear').textContent  = st.linear.toFixed(3);
    document.getElementById('val-angular').textContent = st.angular.toFixed(3);

    // Raw triggerek (függőleges kitöltés alulról)
    const ltPct = Math.round((st.lt || 0) * 100);
    const rtPct = Math.round((st.rt || 0) * 100);
    document.getElementById('lt-fill').style.height = ltPct + '%';
    document.getElementById('rt-fill').style.height = rtPct + '%';
    document.getElementById('lt-pct').textContent = ltPct + '%';
    document.getElementById('rt-pct').textContent = rtPct + '%';

    // Bal stick X csúszka
    const sx = st.stick_x || 0;
    document.getElementById('stick-knob').style.left = ((sx + 1) / 2 * 100) + '%';
    document.getElementById('val-stick-x').textContent = sx.toFixed(3);

    drawJoystick(st.linear, st.angular);
  } catch (_) {}
}
setInterval(pollStatus, 200);
pollStatus();

// ── Beállítások betöltése ─────────────────────────────────────────────────────
async function loadSettings() {
  try {
    const r   = await fetch('/api/settings');
    const cfg = await r.json();

    if (cfg.CTRL_SPEED_LIMIT !== undefined) {
      const pct = Math.round(cfg.CTRL_SPEED_LIMIT * 100);
      document.getElementById('inp-speed').value = pct;
      document.getElementById('hint-speed').textContent = pct + '%';
    }
    if (cfg.CTRL_DEADZONE !== undefined) {
      const pct = Math.round(cfg.CTRL_DEADZONE * 100);
      document.getElementById('inp-dz').value = pct;
      document.getElementById('hint-dz').textContent = pct + '%';
    }
    if (cfg.CTRL_SEND_HZ !== undefined)
      document.getElementById('inp-hz').value = cfg.CTRL_SEND_HZ;
    if (cfg.CTRL_GAMEPAD_DEVICE !== undefined)
      document.getElementById('inp-device').value = cfg.CTRL_GAMEPAD_DEVICE;
    if (cfg.LORA_FREQUENCY_MHZ !== undefined)
      document.getElementById('inp-freq').value = cfg.LORA_FREQUENCY_MHZ;
    if (cfg.LORA_SPREADING_FACTOR !== undefined)
      document.getElementById('inp-sf').value = cfg.LORA_SPREADING_FACTOR;
    if (cfg.LORA_TX_POWER_DBM !== undefined) {
      document.getElementById('inp-txpwr').value = cfg.LORA_TX_POWER_DBM;
      document.getElementById('hint-txpwr').textContent = cfg.LORA_TX_POWER_DBM + ' dBm';
    }
  } catch (_) {}
}
loadSettings();

// ── Mentés ────────────────────────────────────────────────────────────────────
async function saveSection(section) {
  const statusEl = document.getElementById('status-' + section);
  statusEl.className = 'save-status';
  statusEl.textContent = 'Mentés...';

  let payload = {};

  if (section === 'ctrl') {
    payload = {
      CTRL_SPEED_LIMIT:    parseFloat(document.getElementById('inp-speed').value) / 100,
      CTRL_DEADZONE:       parseFloat(document.getElementById('inp-dz').value)    / 100,
      CTRL_SEND_HZ:        parseInt(document.getElementById('inp-hz').value),
      CTRL_GAMEPAD_DEVICE: document.getElementById('inp-device').value.trim(),
    };
  } else if (section === 'lora') {
    payload = {
      LORA_FREQUENCY_MHZ:   parseFloat(document.getElementById('inp-freq').value),
      LORA_SPREADING_FACTOR: parseInt(document.getElementById('inp-sf').value),
      LORA_TX_POWER_DBM:    parseInt(document.getElementById('inp-txpwr').value),
    };
  }

  try {
    const r   = await fetch('/api/settings', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify(payload),
    });
    const res = await r.json();

    if (Object.keys(res.errors || {}).length === 0) {
      statusEl.className   = 'save-status ok';
      statusEl.textContent = '✓ Mentve';
    } else {
      const msgs = Object.entries(res.errors).map(([k,v]) => `${k}: ${v}`).join(', ');
      statusEl.className   = 'save-status err';
      statusEl.textContent = 'Hiba: ' + msgs;
    }
  } catch (e) {
    statusEl.className   = 'save-status err';
    statusEl.textContent = 'Hálózati hiba';
  }

  setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'save-status'; }, 3000);
}
