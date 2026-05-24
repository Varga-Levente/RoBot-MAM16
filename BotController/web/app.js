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

    // Lateral (bal stick X)
    const lat = st.lateral || 0;
    document.getElementById('stick-lat-knob').style.left = ((lat + 1) / 2 * 100) + '%';
    document.getElementById('val-stick-lat').textContent = lat.toFixed(3);
    document.getElementById('val-lateral').textContent   = lat.toFixed(3);

    // Left Y (bal stick Y)
    const ly = st.left_y || 0;
    document.getElementById('stick-ly-knob').style.left = ((ly + 1) / 2 * 100) + '%';
    document.getElementById('val-stick-ly').textContent = ly.toFixed(3);
    document.getElementById('val-lefty').textContent    = ly.toFixed(3);

    // Gombállapotok
    setBtnState('bs-y', st.btn_y);
    setBtnState('bs-a', st.btn_a);
    setBtnState('bs-x', st.btn_x);
    setBtnState('bs-b', st.btn_b);

    // Jump jelző
    const jumpEl = document.getElementById('jump-indicator');
    if (st.jump_dir) {
      jumpEl.textContent = 'JUMP: ' + st.jump_dir.toUpperCase();
      jumpEl.className   = 'jump-indicator active';
      jumpFlash = 6;
    } else if (jumpFlash <= 0) {
      jumpEl.textContent = '–';
      jumpEl.className   = 'jump-indicator';
    }

    drawJoystick(st.linear, st.angular);
    drawMecanumRobot(
      st.linear || 0, st.angular || 0, lat, ly,
      !!st.btn_y, !!st.btn_a, !!st.btn_x, !!st.btn_b,
      st.jump_dir || ''
    );
  } catch (_) {}
}
setInterval(pollStatus, 200);
pollStatus();

// ── Gombállapot helper ────────────────────────────────────────────────────────
function setBtnState(id, active) {
  const el = document.getElementById(id);
  if (active) el.classList.add('active');
  else        el.classList.remove('active');
}

// ── Robot Mecanum vizualizáció ────────────────────────────────────────────────
const robotCanvas = document.getElementById('robot-canvas');
const robotCtx    = robotCanvas.getContext('2d');
let   jumpFlash   = 0;

function rrect(ctx, x, y, w, h, r, fill, stroke, lw) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
  if (fill)   { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = lw || 1; ctx.stroke(); }
}

function darrow(ctx, x1, y1, x2, y2, color, lw) {
  const dx = x2 - x1, dy = y2 - y1;
  if (Math.sqrt(dx * dx + dy * dy) < 4) return;
  const a = Math.atan2(dy, dx), hs = 7;
  ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = lw || 2;
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - hs * Math.cos(a - 0.45), y2 - hs * Math.sin(a - 0.45));
  ctx.lineTo(x2 - hs * Math.cos(a + 0.45), y2 - hs * Math.sin(a + 0.45));
  ctx.closePath(); ctx.fill();
}

function drawWheel(x, y, w, h, speed, rollerDir) {
  const abs = Math.abs(speed);
  let fill;
  if (abs < 0.05)   fill = 'rgba(30,41,59,0.9)';
  else if (speed > 0) fill = `rgba(37,99,235,${0.4 + abs * 0.6})`;
  else                fill = `rgba(220,60,10,${0.4 + abs * 0.6})`;
  robotCtx.fillStyle = fill;
  robotCtx.strokeStyle = 'rgba(148,163,184,0.4)';
  robotCtx.lineWidth = 1;
  robotCtx.fillRect(x, y, w, h);
  robotCtx.strokeRect(x, y, w, h);
  // Mecanum diagonal roller lines
  robotCtx.save();
  robotCtx.beginPath(); robotCtx.rect(x, y, w, h); robotCtx.clip();
  robotCtx.strokeStyle = 'rgba(255,255,255,0.22)'; robotCtx.lineWidth = 1;
  for (let i = -(h + w); i < w + h + 5; i += 5) {
    robotCtx.beginPath();
    robotCtx.moveTo(x + i,               y);
    robotCtx.lineTo(x + i + h * rollerDir, y + h);
    robotCtx.stroke();
  }
  robotCtx.restore();
}

function drawCanvasBtn(x, y, r, label, active, color) {
  robotCtx.beginPath();
  robotCtx.arc(x, y, r, 0, Math.PI * 2);
  robotCtx.fillStyle   = active ? color : 'rgba(30,41,59,0.85)';
  robotCtx.fill();
  robotCtx.strokeStyle = active ? color : 'rgba(100,116,139,0.35)';
  robotCtx.lineWidth   = 1.5;
  robotCtx.stroke();
  if (active) { robotCtx.shadowColor = color; robotCtx.shadowBlur = 10; }
  robotCtx.fillStyle    = active ? '#fff' : 'rgba(148,163,184,0.55)';
  robotCtx.font         = 'bold 10px monospace';
  robotCtx.textAlign    = 'center';
  robotCtx.textBaseline = 'middle';
  robotCtx.fillText(label, x, y);
  robotCtx.shadowBlur = 0;
}

function drawMecanumRobot(linear, angular, lateral, leftY, btnY, btnA, btnX, btnB, jumpDir) {
  const W = robotCanvas.width, H = robotCanvas.height;
  const cx = W / 2, cy = H / 2;
  robotCtx.clearRect(0, 0, W, H);

  // Mecanum wheel speeds (same formula as motor_controller.py)
  const cl = linear - leftY;
  let fl = cl + lateral + angular;
  let fr = cl - lateral - angular;
  let rl = cl - lateral + angular;
  let rr = cl + lateral - angular;
  const mx = Math.max(Math.abs(fl), Math.abs(fr), Math.abs(rl), Math.abs(rr), 1.0);
  fl /= mx; fr /= mx; rl /= mx; rr /= mx;

  // Layout
  const bw = 100, bh = 76;
  const bx = cx - bw / 2, by = cy - bh / 2;
  const ww = 30, wh = 13, wgap = 5;

  // Body fill: flash yellow on jump
  const bodyFill = jumpFlash > 0
    ? `rgba(245,158,11,${0.12 + 0.1 * Math.sin(jumpFlash)})`
    : 'rgba(15,23,42,0.92)';
  rrect(robotCtx, bx, by, bw, bh, 10, bodyFill, 'rgba(96,165,250,0.35)', 1.5);

  // Front marker triangle
  robotCtx.fillStyle = 'rgba(96,165,250,0.5)';
  robotCtx.beginPath();
  robotCtx.moveTo(cx - 7, by + 9); robotCtx.lineTo(cx + 7, by + 9); robotCtx.lineTo(cx, by + 2);
  robotCtx.closePath(); robotCtx.fill();

  // Wheels: FL(+roller), FR(-), RL(-), RR(+)
  const wyT = by + 8, wyB = by + bh - wh - 8;
  drawWheel(bx - ww - wgap, wyT, ww, wh, fl,  1);
  drawWheel(bx + bw + wgap, wyT, ww, wh, fr, -1);
  drawWheel(bx - ww - wgap, wyB, ww, wh, rl, -1);
  drawWheel(bx + bw + wgap, wyB, ww, wh, rr,  1);

  // Movement arrows (drawn from body center)
  const AR = 30;
  if (Math.abs(cl)      > 0.04) darrow(robotCtx, cx, cy, cx,             cy - cl * AR,      '#60a5fa', 2.5);
  if (Math.abs(lateral) > 0.04) darrow(robotCtx, cx, cy, cx + lateral * AR, cy,             '#4ade80', 2.5);
  if (Math.abs(angular) > 0.04) {
    const aR = 22, sa = -Math.PI / 2, ea = sa + angular * Math.PI * 0.75;
    robotCtx.strokeStyle = '#fb923c'; robotCtx.lineWidth = 2.5;
    robotCtx.beginPath();
    robotCtx.arc(cx, cy, aR, Math.min(sa, ea), Math.max(sa, ea));
    robotCtx.stroke();
    const tipA = ea + (angular > 0 ? Math.PI / 2 : -Math.PI / 2);
    const tx = cx + aR * Math.cos(ea), ty = cy + aR * Math.sin(ea), hs = 6;
    robotCtx.fillStyle = '#fb923c';
    robotCtx.beginPath();
    robotCtx.moveTo(tx, ty);
    robotCtx.lineTo(tx - hs * Math.cos(tipA - 0.45), ty - hs * Math.sin(tipA - 0.45));
    robotCtx.lineTo(tx - hs * Math.cos(tipA + 0.45), ty - hs * Math.sin(tipA + 0.45));
    robotCtx.closePath(); robotCtx.fill();
  }

  // Buttons around the robot
  const br = 11;
  drawCanvasBtn(cx,                          by - 18,        br, 'Y', btnY, '#eab308');
  drawCanvasBtn(cx,                          by + bh + 18,   br, 'A', btnA, '#22c55e');
  drawCanvasBtn(bx - ww - wgap - br - 4,    cy,             br, 'X', btnX, '#3b82f6');
  drawCanvasBtn(bx + bw + wgap + ww + br + 4, cy,           br, 'B', btnB, '#ef4444');

  if (jumpFlash > 0) jumpFlash--;
}

drawMecanumRobot(0, 0, 0, 0, false, false, false, false, '');

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
    if (cfg.LORA_UART_PORT !== undefined)
      document.getElementById('inp-uart').value = cfg.LORA_UART_PORT;
    if (cfg.LORA_M0_PIN !== undefined)
      document.getElementById('inp-m0').value = cfg.LORA_M0_PIN;
    if (cfg.LORA_M1_PIN !== undefined)
      document.getElementById('inp-m1').value = cfg.LORA_M1_PIN;
    if (cfg.LORA_AUX_PIN !== undefined)
      document.getElementById('inp-aux').value = cfg.LORA_AUX_PIN;
    if (cfg.LORA_CHANNEL !== undefined) {
      document.getElementById('inp-ch').value = cfg.LORA_CHANNEL;
      document.getElementById('hint-ch').textContent =
        (850.125 + cfg.LORA_CHANNEL).toFixed(3) + ' MHz';
    }
    if (cfg.LORA_TX_POWER !== undefined) {
      document.getElementById('inp-txpwr').value = cfg.LORA_TX_POWER;
      document.getElementById('hint-txpwr').textContent = cfg.LORA_TX_POWER + ' dBm';
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
      LORA_UART_PORT: document.getElementById('inp-uart').value.trim(),
      LORA_M0_PIN:    parseInt(document.getElementById('inp-m0').value),
      LORA_M1_PIN:    parseInt(document.getElementById('inp-m1').value),
      LORA_AUX_PIN:   parseInt(document.getElementById('inp-aux').value),
      LORA_CHANNEL:   parseInt(document.getElementById('inp-ch').value),
      LORA_TX_POWER:  parseInt(document.getElementById('inp-txpwr').value),
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
