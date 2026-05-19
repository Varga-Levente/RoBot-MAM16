"use strict";

// ── Állapot ────────────────────────────────────────────────────────────────
const MAX_LOG_ROWS    = 500;
let   logOpen         = false;
let   debugOpen       = false;
let   annotationOn    = false;
let   logRowCount     = 0;
let   autoScroll      = true;
let   pc              = null;   // RTCPeerConnection
let   stateInterval   = null;

// ── DOM referenciák ────────────────────────────────────────────────────────
const video       = document.getElementById("video");
const noVideo     = document.getElementById("no-video");
const roleBadge   = document.getElementById("role-badge");
const gateCode    = document.getElementById("gate-code");
const irCode      = document.getElementById("ir-code");
const irDot       = document.getElementById("ir-dot");
const connDot     = document.getElementById("conn-dot");
const connText    = document.getElementById("conn-text");
const logBody     = document.getElementById("log-body");
const logCount    = document.getElementById("log-count");
const toggleBtn   = document.getElementById("toggle-btn");

// ── Log panel ──────────────────────────────────────────────────────────────
window.toggleLog = function () {
  logOpen = !logOpen;
  logBody.classList.toggle("open", logOpen);
  toggleBtn.textContent = logOpen ? "▼" : "▲";
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
      const entry = JSON.parse(evt.data);
      appendLog(entry);
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
    const s = await res.json();
    updateState(s);
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

  // LoRa kapcsolat
  connDot.classList.toggle("connected", !!s.lora_connected);
  connDot.classList.toggle("error", !s.lora_connected);
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
  const iceServers = [];
  // Ha a szerver küld STUN szerver konfigurációt, itt lehetne dinamikusan beállítani.
  // Alapesetben üres (LAN-on nincs szükség STUN-ra).

  pc = new RTCPeerConnection({
    iceServers,
    iceTransportPolicy:  "all",
    bundlePolicy:        "max-bundle",
    rtcpMuxPolicy:       "require",
  });

  pc.addTransceiver("video", { direction: "recvonly" });

  pc.ontrack = (evt) => {
    if (evt.track.kind === "video") {
      video.srcObject = evt.streams[0];
      noVideo.classList.add("hidden");
      setConnStatus("WebRTC csatlakozva", "connected");
    }
  };

  pc.onconnectionstatechange = () => {
    const st = pc.connectionState;
    if (st === "connected") {
      setConnStatus("WebRTC csatlakozva", "connected");
    } else if (st === "failed" || st === "disconnected" || st === "closed") {
      setConnStatus("Stream megszakadt", "error");
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
    setConnStatus("Szerver nem elérhető", "error");
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

function setConnStatus(text, cssClass) {
  connText.textContent = text;
  connDot.className    = "conn-dot " + (cssClass || "");
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
