import asyncio
import json
import logging
import logging.handlers
import time
from typing import List

import settings

# Minden csatlakozott SSE kliens saját queue-t kap; ide kerülnek a log bejegyzések.
_sse_clients: List[asyncio.Queue] = []


class _SSELogHandler(logging.Handler):
    """Log handler ami JSON-ként minden bejegyzést broadcast-ol az SSE klienseknek."""

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "level": record.levelname,
            "msg": self.format(record),
            "ts": time.strftime("%H:%M:%S", time.localtime(record.created))
            + f".{int(record.msecs):03d}",
        }
        data = json.dumps(entry, ensure_ascii=False)
        for q in _sse_clients[:]:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                # Lassú kliens: legrégebbi sort eldobjuk, újat betesszük
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                except Exception:
                    pass


def register_sse_client() -> asyncio.Queue:
    """Új SSE kliens regisztrálása. Visszaad egy queue-t amire az üzenetek kerülnek."""
    q: asyncio.Queue = asyncio.Queue(maxsize=settings.LOG_SSE_MAXQUEUE)
    _sse_clients.append(q)
    return q


def unregister_sse_client(q: asyncio.Queue) -> None:
    """SSE kliens eltávolítása (kapcsolat bontásakor)."""
    try:
        _sse_clients.remove(q)
    except ValueError:
        pass


def setup_logger() -> logging.Logger:
    """Inicializálja a root loggert: konzol + opcionális fájl + SSE broadcast."""
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Konzol handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Fájl handler (opcionális)
    if settings.LOG_FILE:
        fh = logging.handlers.RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=settings.LOG_MAX_BYTES,
            backupCount=settings.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    # SSE broadcast handler
    sse_handler = _SSELogHandler()
    sse_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logger.addHandler(sse_handler)

    # Zajos külső könyvtárak DEBUG spamjének elnyomása
    for _noisy in ("aiortc", "aiohttp", "aioice", "av"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    return logging.getLogger("robot")
