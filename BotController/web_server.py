"""
BotController beállítás web UI — aiohttp szerver.

Végpontok:
  GET  /              → web/index.html
  GET  /web/<file>    → statikus fájlok
  GET  /api/settings  → aktuális beállítások JSON-ban
  POST /api/settings  → beállítások frissítése + config.json mentés
  GET  /api/status    → kontroller valós idejű állapot
"""

import json
import logging
import os
from pathlib import Path

from aiohttp import web

import settings

log        = logging.getLogger("web")
_WEB_DIR   = Path(__file__).parent / "web"
_CFG_FILE  = Path(__file__).parent / "config.json"

# Szerkeszthető mezők és validációs korlátaik
_EDITABLE = {
    "CTRL_SPEED_LIMIT":    (float, 0.0,  1.0),
    "CTRL_DEADZONE":       (float, 0.0,  0.5),
    "CTRL_SEND_HZ":        (int,   1,    50),
    "CTRL_GAMEPAD_DEVICE": (str,   None, None),
    "LORA_FREQUENCY_MHZ":  (float, 863.0, 870.0),
    "LORA_SPREADING_FACTOR":(int,  7,    12),
    "LORA_TX_POWER_DBM":   (int,   2,    20),
}


def load_config() -> None:
    """config.json betöltése — felülírja a settings modul értékeit."""
    if not _CFG_FILE.exists():
        return
    try:
        data = json.loads(_CFG_FILE.read_text())
        for key, val in data.items():
            if key in _EDITABLE and hasattr(settings, key):
                setattr(settings, key, val)
        log.info(f"config.json betöltve: {_CFG_FILE}")
    except Exception as e:
        log.warning(f"config.json betöltési hiba: {e}")


def _save_config() -> None:
    data = {k: getattr(settings, k) for k in _EDITABLE if hasattr(settings, k)}
    _CFG_FILE.write_text(json.dumps(data, indent=2))


def _current_settings() -> dict:
    return {k: getattr(settings, k) for k in _EDITABLE if hasattr(settings, k)}


class ControllerWebServer:
    def __init__(self, state):
        self._state = state  # ControllerState dataclass a main.py-ból
        self._app   = web.Application()
        self._app.router.add_get("/",               self._index)
        self._app.router.add_get("/web/{file}",     self._static)
        self._app.router.add_get("/api/settings",   self._get_settings)
        self._app.router.add_post("/api/settings",  self._post_settings)
        self._app.router.add_get("/api/status",     self._get_status)

    async def _index(self, request: web.Request) -> web.Response:
        path = _WEB_DIR / "index.html"
        return web.FileResponse(path)

    async def _static(self, request: web.Request) -> web.Response:
        fname = request.match_info["file"]
        path  = _WEB_DIR / fname
        if not path.exists() or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def _get_settings(self, request: web.Request) -> web.Response:
        return web.json_response(_current_settings())

    async def _post_settings(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Érvénytelen JSON"}, status=400)

        errors = {}
        applied = {}
        needs_lora_reinit = False

        for key, raw_val in body.items():
            if key not in _EDITABLE:
                errors[key] = "Ismeretlen mező"
                continue
            typ, lo, hi = _EDITABLE[key]
            try:
                val = typ(raw_val)
            except (ValueError, TypeError):
                errors[key] = f"Típushiba: {typ.__name__} szükséges"
                continue
            if lo is not None and val < lo:
                errors[key] = f"Minimum: {lo}"
                continue
            if hi is not None and val > hi:
                errors[key] = f"Maximum: {hi}"
                continue
            old = getattr(settings, key, None)
            setattr(settings, key, val)
            applied[key] = val
            if key.startswith("LORA_") and val != old:
                needs_lora_reinit = True

        if applied:
            _save_config()
            log.info(f"Beállítások frissítve: {applied}")

        if needs_lora_reinit and self._state:
            self._state.lora_reinit_requested = True

        return web.json_response({
            "applied": applied,
            "errors":  errors,
            "settings": _current_settings(),
        })

    async def _get_status(self, request: web.Request) -> web.Response:
        st = self._state
        return web.json_response({
            "gamepad_connected":  st.gamepad_connected  if st else False,
            "lora_hw_ok":         st.lora_hw_ok         if st else False,
            "lora_authenticated": st.lora_authenticated if st else False,
            "linear":   round(st.linear,  3) if st else 0.0,
            "angular":  round(st.angular, 3) if st else 0.0,
            "lt":       round(st.lt,      3) if st else 0.0,
            "rt":       round(st.rt,      3) if st else 0.0,
            "stick_x":  round(st.stick_x, 3) if st else 0.0,
            "speed_limit": settings.CTRL_SPEED_LIMIT,
        })

    async def serve(self) -> None:
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, settings.WEB_HOST, settings.WEB_PORT)
        await site.start()
        log.info(f"Beállítás UI: http://{settings.WEB_HOST}:{settings.WEB_PORT}")
