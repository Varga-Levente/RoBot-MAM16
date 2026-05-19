"use strict";

// ── Navigáció ──────────────────────────────────────────────────────────────
document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".panel").forEach(p =>
      p.classList.toggle("active", p.id === "panel-" + btn.dataset.panel)
    );
    document.querySelectorAll(".nav-btn").forEach(b =>
      b.classList.toggle("active", b === btn)
    );
    activePanel = btn.dataset.panel;
  });
});

let activePanel    = "vision";
let visionRunning  = false;
let currentVideo   = "";
let prevCodeCount  = 0;
let statusInterval = null;
let motorTimer     = null;

// ── Vision ─────────────────────────────────────────────────────────────────

async function loadVideos() {
  const list = document.getElementById("file-list");
  list.innerHTML = '<li class="file-placeholder">Betöltés...</li>';
  try {
    const res  = await fetch("/test/api/videos");
    const data = await res.json();
    if (!data.videos || data.videos.length === 0) {
      list.innerHTML = '<li class="file-placeholder">Nincs videó a ~/Videos/ mappában</li>';
      return;
    }
    list.innerHTML = "";
    data.videos.forEach(v => {
      const li      = document.createElement("li");
      const playing = v.name === currentVideo && visionRunning;
      li.className  = "file-item" + (playing ? " playing" : "");
      li.innerHTML  =
        `<span class="file-name" title="${esc(v.name)}">${esc(v.name)}</span>` +
        `<span class="file-size">${fmtSize(v.size)}</span>` +
        `<button class="file-play" onclick="startVision('${esc(v.name)}')">${playing ? "▶▶" : "▶"}</button>`;
      list.appendChild(li);
    });
  } catch (_) {
    list.innerHTML = '<li class="file-placeholder">Hiba a betöltés során</li>';
  }
}

async function startVision(filename) {
  try {
    const res = await fetch("/test/api/vision/start", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ video: filename }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.error || "Hiba a teszt indításakor");
      return;
    }
    currentVideo   = filename;
    visionRunning  = true;
    prevCodeCount  = 0;

    const img = document.getElementById("stream-img");
    img.src   = "/test/api/vision/stream?" + Date.now();
    img.classList.remove("hidden");
    document.getElementById("stream-placeholder").style.display = "none";
    document.getElementById("btn-stop").disabled = false;
    setBadge("Fut", true);
    loadVideos();

    if (statusInterval) clearInterval(statusInterval);
    statusInterval = setInterval(pollVisionStatus, 800);
  } catch (_) {}
}

async function stopVision() {
  await fetch("/test/api/vision/stop", { method: "POST" });
  visionRunning = false;
  currentVideo  = "";

  const img = document.getElementById("stream-img");
  img.src   = "";
  img.classList.add("hidden");
  document.getElementById("stream-placeholder").style.display = "";
  document.getElementById("btn-stop").disabled = true;
  setBadge("Leállítva", false);

  if (statusInterval) { clearInterval(statusInterval); statusInterval = null; }
  loadVideos();
}

async function pollVisionStatus() {
  try {
    const res  = await fetch("/test/api/vision/status");
    const data = await res.json();
    document.getElementById("frame-count").textContent = data.frame_count + " frame";

    const codes = data.detected_codes || [];
    if (codes.length > prevCodeCount) {
      appendCodes(codes.slice(prevCodeCount));
      prevCodeCount = codes.length;
    }
    if (!data.running && visionRunning) stopVision();
  } catch (_) {}
}

function appendCodes(codes) {
  const list = document.getElementById("code-list");
  const ph   = list.querySelector(".file-placeholder");
  if (ph) ph.remove();
  codes.forEach(code => {
    const li  = document.createElement("li");
    li.className = "code-item";
    const ts  = new Date().toLocaleTimeString("hu-HU");
    li.innerHTML = `<span class="code-hex">${esc(code)}</span><span class="code-ts">${ts}</span>`;
    list.prepend(li);
  });
}

function clearCodes() {
  document.getElementById("code-list").innerHTML = '<li class="file-placeholder">Még nincs kód</li>';
  prevCodeCount = 0;
}

function setBadge(text, running) {
  const b = document.getElementById("vision-badge");
  b.textContent = text;
  b.classList.toggle("running", running);
}

// ── IR ─────────────────────────────────────────────────────────────────────

async function sendIR() {
  const input = document.getElementById("ir-input");
  const code  = input.value.trim();
  if (code.length !== 3) {
    addIRLog(`<span class="lerr">Hibás kód — pontosan 3 hex jegy kell</span>`);
    return;
  }
  try {
    const res  = await fetch("/test/api/ir/send", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ code }),
    });
    const data = await res.json();
    if (data.ok) {
      addIRLog(`Elküldve: <span class="lc">${esc(code)}</span> <span class="lok">✓</span>`);
      input.value = "";
    } else {
      addIRLog(`<span class="lerr">Hiba: ${esc(data.error || "ismeretlen")}</span>`);
    }
  } catch (_) {
    addIRLog('<span class="lerr">Hálózati hiba</span>');
  }
}

function addIRLog(html) {
  const box = document.getElementById("ir-log");
  const ts  = new Date().toLocaleTimeString("hu-HU");
  const div = document.createElement("div");
  div.className = "log-entry";
  div.innerHTML = `<span style="color:#475569">${ts}</span> ${html}`;
  box.prepend(div);
  while (box.children.length > 60) box.removeChild(box.lastChild);
}

// ── Motor ───────────────────────────────────────────────────────────────────

function onSlider() {
  const linear  = parseInt(document.getElementById("sld-linear").value) / 100;
  const angular = parseInt(document.getElementById("sld-angular").value) / 100;
  document.getElementById("lbl-linear").textContent  = linear.toFixed(2);
  document.getElementById("lbl-angular").textContent = angular.toFixed(2);
  if (motorTimer) clearTimeout(motorTimer);
  motorTimer = setTimeout(() => sendMotor(linear, angular), 80);
}

async function sendMotor(linear, angular) {
  try {
    const res  = await fetch("/test/api/motor/set", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ linear, angular }),
    });
    const data = await res.json();
    if (data.motor_speeds) updateMotorBars(data.motor_speeds);
  } catch (_) {}
}

async function stopMotors() {
  document.getElementById("sld-linear").value   = 0;
  document.getElementById("sld-angular").value  = 0;
  document.getElementById("lbl-linear").textContent  = "0.00";
  document.getElementById("lbl-angular").textContent = "0.00";
  try {
    await fetch("/test/api/motor/stop", { method: "POST" });
    updateMotorBars([0, 0, 0, 0]);
  } catch (_) {}
}

function updateMotorBars(speeds) {
  speeds.forEach((spd, i) => {
    const bar = document.getElementById("mb-" + i);
    const val = document.getElementById("mv-" + i);
    if (bar) { bar.style.width = Math.abs(spd) * 100 + "%"; bar.classList.toggle("rev", spd < 0); }
    if (val)   val.textContent = spd.toFixed(2);
  });
}

// ── Általános állapot poll (LoRa + motorok) ────────────────────────────────

async function pollState() {
  try {
    const res  = await fetch("/state");
    const data = await res.json();
    const el   = document.getElementById("lora-conn");
    if (el) el.textContent = data.lora_connected ? "Kapcsolva" : "Nincs kapcsolat";
    if (activePanel === "motor" && data.motor_speeds) updateMotorBars(data.motor_speeds);
  } catch (_) {}
}

// ── Segédek ────────────────────────────────────────────────────────────────

function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function fmtSize(bytes) {
  if (bytes > 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
  if (bytes > 1024)         return (bytes / 1024).toFixed(0) + " KB";
  return bytes + " B";
}

// ── Init ────────────────────────────────────────────────────────────────────
loadVideos();
setInterval(pollState, 1000);
