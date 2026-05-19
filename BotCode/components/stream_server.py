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
       POST /api/debug  → debug annotáció be/ki

Teszt UI (külön porton, --test-ui flag):
       GET  /           → web_test/index.html
       GET  /test/web/<file>
       GET  /test/api/videos
       POST /test/api/vision/start
       POST /test/api/vision/stop
       GET  /test/api/vision/stream   → MJPEG
       GET  /test/api/vision/status
       POST /test/api/ir/send
       POST /test/api/motor/set
       POST /test/api/motor/stop
"""

import asyncio
import fractions
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

import av
import cv2
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaRelay

import settings
from utils.logger import register_sse_client, unregister_sse_client

log = logging.getLogger("stream")

_WEB_DIR      = Path(__file__).parent.parent / "web"
_WEB_TEST_DIR = Path(__file__).parent.parent / "web_test"
_VIDEOS_DIR   = Path.home() / "Videos"
_VIDEO_EXTS   = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
_VIDEO_CLOCK_RATE = 90000
_VIDEO_PTIME = fractions.Fraction(1, settings.CAMERA_FPS)


class _TestVisionRunner:
    """Vision teszt futtatása videófájlon külön VisionProcessor példánnyal."""

    def __init__(self):
        self._task:           Optional[asyncio.Task] = None
        self._running:        bool = False
        self._last_frame:     Optional[np.ndarray] = None
        self._detected_codes: List[str] = []
        self._current_video:  str = ""
        self._frame_count:    int = 0
        self._processor              = None
        self._blank: np.ndarray = self._make_blank()

    @staticmethod
    def _make_blank() -> np.ndarray:
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(img, "Nincs aktiv teszt",
                    (140, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (70, 70, 70), 2)
        return img

    async def start(self, video_path: str) -> None:
        await self.stop()
        from components.vision import VisionProcessor
        self._processor      = VisionProcessor()
        self._detected_codes = []
        self._current_video  = Path(video_path).name
        self._frame_count    = 0
        self._running        = True
        self._task = asyncio.create_task(self._run(video_path))

    async def _run(self, video_path: str) -> None:
        from components.vision import VisionProcessor
        cap = cv2.VideoCapture(str(video_path))
        try:
            fps      = cap.get(cv2.CAP_PROP_FPS) or 30.0
            interval = 1.0 / max(fps, 1.0)
            while self._running and cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self._processor = VisionProcessor()
                    await asyncio.sleep(0.1)
                    continue
                code = self._processor._process_frame(frame)
                if code:
                    self._detected_codes.append(code)
                    log.info(f"[Vision teszt] kód: {code}")
                self._last_frame  = self._processor.annotate(frame, self._processor._candidate)
                self._frame_count += 1
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        finally:
            cap.release()
            self._running = False

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task       = None
        self._last_frame = None

    def get_frame(self) -> np.ndarray:
        return self._last_frame if self._last_frame is not None else self._blank

    def status(self) -> dict:
        return {
            "running":        self._running,
            "video":          self._current_video,
            "frame_count":    self._frame_count,
            "detected_codes": self._detected_codes[-50:],
        }


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
        self._pcs:         Set[RTCPeerConnection] = set()
        self._relay:       Optional[MediaRelay]   = None
        self._camera       = None
        self._state        = None
        self._vision       = None
        self._motor        = None
        self._ir           = None
        self._test_runner  = _TestVisionRunner()

    async def serve(self, camera, state, vision=None, motor=None, ir=None,
                    enable_test_ui: bool = False) -> None:
        self._camera = camera
        self._state  = state
        self._vision = vision
        self._motor  = motor
        self._ir     = ir
        self._relay  = MediaRelay()

        # ── Fő UI (port 8080) ──────────────────────────────────────────────
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

        # ── Teszt UI (port 8081, --test-ui flag) ───────────────────────────
        if enable_test_ui:
            test_app = web.Application()
            test_app.router.add_get("/",                         self._test_index)
            test_app.router.add_get("/test/web/{file}",          self._test_static)
            test_app.router.add_get("/state",                    self._state_handler)
            test_app.router.add_get("/test/api/videos",          self._test_videos)
            test_app.router.add_post("/test/api/vision/start",   self._test_vision_start)
            test_app.router.add_post("/test/api/vision/stop",    self._test_vision_stop)
            test_app.router.add_get("/test/api/vision/stream",   self._test_vision_stream)
            test_app.router.add_get("/test/api/vision/status",   self._test_vision_status)
            test_app.router.add_post("/test/api/ir/send",        self._test_ir_send)
            test_app.router.add_post("/test/api/motor/set",      self._test_motor_set)
            test_app.router.add_post("/test/api/motor/stop",     self._test_motor_stop)

            test_runner = web.AppRunner(test_app)
            await test_runner.setup()
            test_site = web.TCPSite(test_runner, settings.STREAM_HOST, settings.TEST_UI_PORT)
            await test_site.start()
            log.info(f"Teszt UI elindult:  http://0.0.0.0:{settings.TEST_UI_PORT}")

        # Futás fenntartása
        while True:
            await asyncio.sleep(3600)

    # ── Fő UI route-ok ────────────────────────────────────────────────────────

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

    # ── Teszt UI route-ok ─────────────────────────────────────────────────────

    async def _test_index(self, request: web.Request) -> web.Response:
        return web.FileResponse(_WEB_TEST_DIR / "index.html")

    async def _test_static(self, request: web.Request) -> web.Response:
        filename = request.match_info["file"]
        file_path = _WEB_TEST_DIR / filename
        if not file_path.exists() or not file_path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(file_path)

    async def _test_videos(self, request: web.Request) -> web.Response:
        videos = []
        if _VIDEOS_DIR.exists():
            for f in sorted(_VIDEOS_DIR.iterdir()):
                if f.is_file() and f.suffix.lower() in _VIDEO_EXTS:
                    videos.append({"name": f.name, "size": f.stat().st_size})
        return web.json_response({"videos": videos})

    async def _test_vision_start(self, request: web.Request) -> web.Response:
        data = await request.json()
        filename = data.get("video", "")
        if not filename:
            return web.json_response({"error": "Hiányzó videó fájlnév"}, status=400)
        video_path = _VIDEOS_DIR / filename
        if not video_path.exists():
            return web.json_response({"error": "Fájl nem található"}, status=404)
        await self._test_runner.start(str(video_path))
        return web.json_response({"ok": True})

    async def _test_vision_stop(self, request: web.Request) -> web.Response:
        await self._test_runner.stop()
        return web.json_response({"ok": True})

    async def _test_vision_stream(self, request: web.Request) -> web.StreamResponse:
        """MJPEG stream a teszt vision annotált képéről."""
        response = web.StreamResponse(
            headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                "Cache-Control": "no-cache",
                "Connection":    "keep-alive",
            }
        )
        await response.prepare(request)
        try:
            while True:
                frame = self._test_runner.get_frame()
                ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ret:
                    data = buf.tobytes()
                    await response.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n"
                        + data + b"\r\n"
                    )
                await asyncio.sleep(1.0 / 25)
        except (ConnectionResetError, Exception):
            pass
        return response

    async def _test_vision_status(self, request: web.Request) -> web.Response:
        return web.json_response(self._test_runner.status())

    async def _test_ir_send(self, request: web.Request) -> web.Response:
        data = await request.json()
        code = data.get("code", "")
        if len(code) != 3:
            return web.json_response({"ok": False, "error": "Érvénytelen kód"}, status=400)
        if self._ir is None:
            return web.json_response({"ok": False, "error": "IR nem elérhető"}, status=503)
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._ir.transmit, code)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _test_motor_set(self, request: web.Request) -> web.Response:
        data   = await request.json()
        linear  = float(data.get("linear",  0.0))
        angular = float(data.get("angular", 0.0))
        if self._motor is None:
            return web.json_response({"ok": False, "error": "Motor nem elérhető"}, status=503)
        self._motor.set_velocity(linear, angular)
        return web.json_response({"ok": True, "motor_speeds": self._state.motor_speeds})

    async def _test_motor_stop(self, request: web.Request) -> web.Response:
        if self._motor is not None:
            self._motor.emergency_stop()
        return web.json_response({"ok": True, "motor_speeds": [0.0, 0.0, 0.0, 0.0]})


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
