"use strict";

// ── Állapot ────────────────────────────────────────────────────────────────
const MAX_LOG_ROWS = 500;
let logOpen        = false;
let debugOpen      = false;
let annotationOn   = false;
let logRowCount    = 0;
let autoScroll     = true;
let pc             = null;
let stateInterval  = null;

// Log szint szűrők (true = megjelenítve)
const logFilters = { DEBUG: true, INFO: true, WARNING: true, ERROR: true, CRITICAL: true };

// ── DOM referenciák ────────────────────────────────────────────────────────
const video        = document.getElementById("video");
const noVideo      = document.getElementById("no-video");
const roleBadge    = document.getElementById("role-badge");
const gateCode     = document.getElementById("gate-code");
const irCode       = document.getElementById("ir-code");
const irDot        = document.getElementById("ir-dot");
const connDot      = document.getElementById("conn-dot");
const connText     = document.getElementById("conn-text");
const webrtcDot    = document.getElementById("webrtc-dot");
const webrtcText   = document.getElementById("webrtc-text");
const logBody      = document.getElementById("log-body");
const logCount     = document.getElementById("log-count");
const logDrawer    = document.getElementById("log-drawer");
const logTrigger   = document.getElementById("log-trigger");

// ── Log drawer toggle ──────────────────────────────────────────────────────
window.toggleLog = function () {
  logOpen = !logOpen;
  logDrawer.classList.toggle("open", logOpen);
  logTrigger.classList.toggle("hidden", logOpen);
  if (logOpen && autoScroll) scrollLogToBottom();
};

// ── Debug panel ────────────────────────────────────────────────────────────
window.toggleDebug = function () {
  debugOpen = !debugOpen;
  document.getElementById("debug-body").classList.toggle("open", debugOpen);
  document.getElementById("debug-toggle-btn").textContent = debugOpen ? "▼" : "▲";
};

window.toggleAnnotation = async function () {
  annotationOn = !annotationOn;
  const btn = document.getElementById("annot-btn");
  btn.textContent = annotationOn ? "BE" : "KI";
  btn.classList.toggle("active", annotationOn);
  try {
    await fetch("/api/debug", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ annotation: annotationOn }),
    });
  } catch (_) {}
};

// ── Log szint szűrők ───────────────────────────────────────────────────────
window.toggleFilter = function (level) {
  logFilters[level] = !logFilters[level];
  const btn = document.querySelector(`.lvl-btn[data-level="${level}"]`);
  if (btn) btn.classList.toggle("active", logFilters[level]);
  // CSS class alapú elrejtés — a DOM bejegyzések megmaradnak (szűrő visszakapcsoláskor újra látszanak)
  logBody.classList.toggle(`hide-${level}`, !logFilters[level]);
};

// ── Log kezelés ────────────────────────────────────────────────────────────
function scrollLogToBottom() {
  logBody.scrollTop = logBody.scrollHeight;
}

function appendLog(entry) {
  // Limit: régebbi sorok eltávolítása
  while (logBody.children.length >= MAX_LOG_ROWS) {
    logBody.removeChild(logBody.firstChild);
    logRowCount = Math.max(0, logRowCount - 1);
  }

  const row = document.createElement("div");
  row.className = `log-entry ${entry.level}`;
  row.innerHTML =
    `<span class="log-ts">${escHtml(entry.ts)}</span>` +
    `<span class="log-level">${escHtml(entry.level)}</span>` +
    `<span class="log-msg">${escHtml(entry.msg)}</span>`;

  logBody.appendChild(row);
  logRowCount++;
  logCount.textContent = `${logRowCount} sor`;

  if (logOpen && autoScroll) scrollLogToBottom();
}

// Automatikus scroll: ha a felhasználó felfelé görgetett, ne ugorjon le
logBody.addEventListener("scroll", () => {
  const atBottom = logBody.scrollHeight - logBody.scrollTop - logBody.clientHeight < 30;
  autoScroll = atBottom;
});

// ── Server-Sent Events: log stream ────────────────────────────────────────
function startLogStream() {
  const es = new EventSource("/logs");

  es.onmessage = (evt) => {
    try {
      appendLog(JSON.parse(evt.data));
    } catch (_) {}
  };

  es.onerror = () => {
    setTimeout(startLogStream, 3000);
    es.close();
  };
}

// ── Robot állapot polling ─────────────────────────────────────────────────
async function fetchState() {
  try {
    const res = await fetch("/state");
    if (!res.ok) return;
    updateState(await res.json());
  } catch (_) {}
}

function updateState(s) {
  // Szerep badge
  roleBadge.textContent = s.role === "PACMAN" ? "PAC-MAN" : "GHOST";
  roleBadge.className   = "role-badge " + (s.role === "PACMAN" ? "pacman" : "ghost");

  // Kapu kód
  const newCode = s.gate_code || "---";
  if (gateCode.textContent !== newCode) {
    gateCode.textContent = newCode;
    gateCode.classList.remove("flash");
    void gateCode.offsetWidth; // reflow a re-animáláshoz
    gateCode.classList.add("flash");
    gateCode.addEventListener("animationend", () => gateCode.classList.remove("flash"), { once: true });
  }

  // IR státusz
  irCode.textContent = s.ir_transmitting ? (s.gate_code || "---") : "---";
  irDot.classList.toggle("active", !!s.ir_transmitting);

  // LoRa kapcsolat (kizárólag a lora_connected állapotból — nem érintik a WebRTC események)
  connDot.classList.toggle("connected", !!s.lora_connected);
  connDot.classList.toggle("error",    !s.lora_connected);
  connText.textContent = s.lora_connected ? "LoRa kapcsolva" : "LoRa nincs";

  // Debug panel
  const dbgVision = document.getElementById("dbg-vision-state");
  const dbgDigit  = document.getElementById("dbg-digit");
  const dbgIrCode = document.getElementById("dbg-ir-code");
  const dbgIrCnt  = document.getElementById("dbg-ir-count");
  const annotBtn  = document.getElementById("annot-btn");

  if (dbgVision) dbgVision.textContent = s.vision_state || "---";
  if (dbgDigit)  dbgDigit.textContent  = s.last_digit != null ? s.last_digit.toString(16).toUpperCase() : "---";
  if (dbgIrCode) dbgIrCode.textContent = s.ir_last_code || "---";
  if (dbgIrCnt)  dbgIrCnt.textContent  = s.ir_tx_count  != null ? s.ir_tx_count : 0;

  // Annotáció gomb szinkronizálás (ha szerver állítja)
  if (s.debug_annotation !== undefined && s.debug_annotation !== annotationOn) {
    annotationOn = s.debug_annotation;
    if (annotBtn) {
      annotBtn.textContent = annotationOn ? "BE" : "KI";
      annotBtn.classList.toggle("active", annotationOn);
    }
  }

  // Motor sebességek
  if (Array.isArray(s.motor_speeds)) {
    s.motor_speeds.forEach(function (spd, i) {
      const bar = document.getElementById("dbg-spd-" + i);
      const val = document.getElementById("dbg-val-" + i);
      if (bar) {
        bar.style.width = (Math.abs(spd) * 100) + "%";
        bar.classList.toggle("reverse", spd < 0);
      }
      if (val) val.textContent = spd.toFixed(2);
    });
  }
}

// ── WebRTC kapcsolat ──────────────────────────────────────────────────────
async function startWebRTC() {
  pc = new RTCPeerConnection({
    iceServers: [],
    iceTransportPolicy:  "all",
    bundlePolicy:        "max-bundle",
    rtcpMuxPolicy:       "require",
  });

  pc.addTransceiver("video", { direction: "recvonly" });

  pc.ontrack = (evt) => {
    if (evt.track.kind === "video") {
      video.srcObject = evt.streams[0];
      noVideo.classList.add("hidden");
      setWebRTCStatus("Stream OK", "connected");
    }
  };

  pc.onconnectionstatechange = () => {
    const st = pc.connectionState;
    if (st === "connected") {
      setWebRTCStatus("Stream OK", "connected");
    } else if (st === "failed" || st === "disconnected" || st === "closed") {
      setWebRTCStatus("Stream off", "error");
      noVideo.classList.remove("hidden");
      setTimeout(startWebRTC, 3000);
    }
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  // ICE gyűjtés megvárása (max 5 mp)
  await waitForIceGathering(pc, 5000);

  try {
    const res = await fetch("/offer", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        sdp:  pc.localDescription.sdp,
        type: pc.localDescription.type,
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const answer = await res.json();
    await pc.setRemoteDescription(new RTCSessionDescription(answer));
  } catch (err) {
    console.error("WebRTC offer hiba:", err);
    setWebRTCStatus("Szerver off", "error");
    setTimeout(startWebRTC, 4000);
  }
}

function waitForIceGathering(pc, timeoutMs) {
  return new Promise((resolve) => {
    if (pc.iceGatheringState === "complete") { resolve(); return; }
    const timer = setTimeout(resolve, timeoutMs);
    pc.onicegatheringstatechange = () => {
      if (pc.iceGatheringState === "complete") {
        clearTimeout(timer);
        resolve();
      }
    };
  });
}

// WebRTC státusz frissítése — csak a webrtc-dot és webrtc-text elemeket érinti
function setWebRTCStatus(text, cssClass) {
  if (webrtcText) webrtcText.textContent = text;
  if (webrtcDot)  webrtcDot.className    = "conn-dot " + (cssClass || "");
}

// ── Segédfüggvény ─────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Indítás ────────────────────────────────────────────────────────────────
startLogStream();
startWebRTC();
fetchState();
stateInterval = setInterval(fetchState, 500);
