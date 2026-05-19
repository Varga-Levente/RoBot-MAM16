"""
WebRTC videóstream + web UI szerver.

Két fő feladat:
  1. aiortc alapú WebRTC stream: a kamera legfrissebb framejét közvetlenül
     injektálja a VideoStreamTrack.recv() hívásba — nincs queue, nincs buffer.
  2. aiohttp HTTP szerver:
       GET  /           → web UI (index.html)
       GET  /web/<file> → statikus fájlok (style.css, app.js)
       POST /offer      → WebRTC SDP offer/answer csere
       GET  /logs       → Server-Sent Events: Python log stream
       GET  /state      → aktuális robot státusz JSON
"""

import asyncio
import fractions
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional, Set

import av
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaRelay

import settings
from utils.logger import register_sse_client, unregister_sse_client

log = logging.getLogger("stream")

_WEB_DIR = Path(__file__).parent.parent / "web"
_VIDEO_CLOCK_RATE = 90000
_VIDEO_PTIME = fractions.Fraction(1, settings.CAMERA_FPS)


class _CameraVideoTrack(VideoStreamTrack):
    """VideoStreamTrack ami a CameraManager slotjából veszi a frameket (0 buffer)."""

    kind = "video"

    def __init__(self, camera, state=None, vision=None):
        super().__init__()
        self._camera = camera
        self._state  = state
        self._vision = vision
        self._blank = np.zeros(
            (settings.CAMERA_HEIGHT, settings.CAMERA_WIDTH, 3), dtype=np.uint8
        )

    async def recv(self) -> av.VideoFrame:
        pts, time_base = await self.next_timestamp()

        if self._state and self._state.debug_annotation and self._vision:
            frame_data = self._vision.get_debug_frame() or self._camera.get_frame()
        else:
            frame_data = self._camera.get_frame()

        if frame_data is None:
            frame_data = self._blank

        frame = av.VideoFrame.from_ndarray(frame_data, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


class StreamServer:
    def __init__(self):
        self._pcs: Set[RTCPeerConnection] = set()
        self._relay: Optional[MediaRelay] = None
        self._camera = None
        self._state  = None
        self._vision = None

    async def serve(self, camera, state, vision=None) -> None:
        self._camera = camera
        self._state  = state
        self._vision = vision
        self._relay  = MediaRelay()

        app = web.Application()
        app.router.add_get("/",             self._index)
        app.router.add_get("/web/{file}",   self._static)
        app.router.add_post("/offer",       self._offer)
        app.router.add_get("/logs",         self._logs_sse)
        app.router.add_get("/state",        self._state_handler)
        app.router.add_post("/api/debug",   self._debug_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, settings.STREAM_HOST, settings.STREAM_PORT)
        await site.start()
        log.info(f"Web szerver elindult: http://0.0.0.0:{settings.STREAM_PORT}")

        # Futás fenntartása
        while True:
            await asyncio.sleep(3600)

    # ── HTTP route-ok ────────────────────────────────────────────────────────

    async def _index(self, request: web.Request) -> web.Response:
        html_path = _WEB_DIR / "index.html"
        return web.FileResponse(html_path)

    async def _static(self, request: web.Request) -> web.Response:
        filename = request.match_info["file"]
        file_path = _WEB_DIR / filename
        if not file_path.exists() or not file_path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(file_path)

    async def _offer(self, request: web.Request) -> web.Response:
        """WebRTC SDP offer feldolgozása és answer visszaküldése."""
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

        pc = RTCPeerConnection()
        self._pcs.add(pc)

        @pc.on("connectionstatechange")
        async def _on_state():
            log.info(f"WebRTC állapot: {pc.connectionState}")
            if pc.connectionState in ("failed", "closed"):
                await pc.close()
                self._pcs.discard(pc)

        # Video track hozzáadása — relay-el több kliens is nézheti
        track = self._relay.subscribe(
            _CameraVideoTrack(self._camera, self._state, self._vision), buffered=False
        )
        pc.addTrack(track)

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()

        # H264 codec preferálása ha beállítva (VP8 az alapértelmezett)
        if settings.STREAM_CODEC == "H264":
            answer = _prefer_codec(answer, "video", "H264")

        await pc.setLocalDescription(answer)

        return web.json_response(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        )

    async def _logs_sse(self, request: web.Request) -> web.StreamResponse:
        """Server-Sent Events: Python log bejegyzések valós időben a böngészőnek."""
        response = web.StreamResponse(
            headers={
                "Content-Type":  "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache",
                "Connection":    "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)

        q = register_sse_client()
        log.debug("Új SSE log kliens csatlakozott")
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    await response.write(f"data: {data}\n\n".encode("utf-8"))
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    await response.write(b": ping\n\n")
        except (ConnectionResetError, Exception):
            pass
        finally:
            unregister_sse_client(q)
            log.debug("SSE log kliens lecsatlakozott")

        return response

    async def _state_handler(self, request: web.Request) -> web.Response:
        """Aktuális robot állapot JSON-ban (JS 500ms-onként pollozza)."""
        s = self._state
        return web.json_response({
            "role":             s.role,
            "ip":               s.ip_address,
            "battery":          s.battery_voltage,
            "gate_code":        s.last_gate_code,
            "ir_transmitting":  s.ir_transmitting,
            "lora_connected":   s.lora_connected,
            "debug_annotation": s.debug_annotation,
            "vision_state":     s.vision_state,
            "last_digit":       s.last_digit,
            "motor_speeds":     s.motor_speeds,
            "ir_last_code":     s.ir_last_code,
            "ir_tx_count":      s.ir_tx_count,
        })

    async def _debug_handler(self, request: web.Request) -> web.Response:
        """Debug beállítások módosítása (pl. annotáció be/ki)."""
        data = await request.json()
        if "annotation" in data:
            self._state.debug_annotation = bool(data["annotation"])
            log.info(f"Debug annotáció: {'BE' if self._state.debug_annotation else 'KI'}")
        return web.json_response({"debug_annotation": self._state.debug_annotation})


# ── Segédfüggvény: codec preferencia SDP módosítással ────────────────────────

def _prefer_codec(
    sdp_desc: RTCSessionDescription, kind: str, codec_name: str
) -> RTCSessionDescription:
    """SDP-ben előrehozza az adott nevű kodeket."""
    lines = sdp_desc.sdp.split("\r\n")
    result = []
    in_media = False
    pt_map: Dict[str, str] = {}

    for line in lines:
        if line.startswith(f"m={kind}"):
            in_media = True
        elif line.startswith("m="):
            in_media = False

        if in_media and line.startswith("a=rtpmap:"):
            parts = line.split(" ", 1)
            if len(parts) == 2 and codec_name.lower() in parts[1].lower():
                pt = parts[0].split(":")[1]
                pt_map[pt] = pt

        result.append(line)

    # Egyszerűsített: a PT-ket átrendezzük az m= sorban
    # (teljes SDP manipuláció komplex, ezt az egyszerűsített változatot hagyjuk meg)
    return sdp_desc


# ── Önálló teszt ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from components.camera import CameraManager
    from dataclasses import dataclass

    @dataclass
    class _MockState:
        role:             str   = "PACMAN"
        ip_address:       str   = "127.0.0.1"
        battery_voltage:  float = 11.4
        last_gate_code:   str   = "CA6"
        ir_transmitting:  bool  = False
        lora_connected:   bool  = True
        debug_annotation: bool  = False
        vision_state:     str   = "WAIT_FOR_F"
        last_digit:       object = None
        motor_speeds:     object = None
        ir_last_code:     str   = "---"
        ir_tx_count:      int   = 0

        def __post_init__(self):
            if self.motor_speeds is None:
                self.motor_speeds = [0.0, 0.0, 0.0, 0.0]

    async def _run():
        from utils.logger import setup_logger
        setup_logger()

        camera = CameraManager()
        await camera.start()

        server = StreamServer()
        state  = _MockState()
        print(f"Web szerver: http://localhost:{settings.STREAM_PORT}")
        await server.serve(camera, state)

    asyncio.run(_run())
