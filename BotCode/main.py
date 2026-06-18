"""
RoBot - Főprogram

Indítás:
  python main.py                                # Teljes robot üzemmód
  python main.py --dry-run                      # Hardver nélküli szimuláció
  python main.py --test-video kapu.mp4          # Videófájl kamera helyett
  python main.py --role GHOST                   # Szerep felülírása
  python main.py --test-video kapu.mp4 --dry-run  # Kombinált teszt
  python main.py --test-ui                         # Teszt UI a 8081-es porton
"""

import argparse
import asyncio
import logging
import signal
import socket
from dataclasses import dataclass, field
from typing import List, Optional

import settings
from utils.logger import setup_logger
from components.camera         import CameraManager
from components.vision         import VisionProcessor
from components.ir_transmitter import IRTransmitter
from components.oled_display   import OLEDDisplay
from components.stream_server  import StreamServer


@dataclass
class RobotState:
    role:             str   = field(default_factory=lambda: settings.ROBOT_ROLE)
    ip_address:       str   = ""
    battery_voltage:  float = 0.0
    last_gate_code:   str   = "---"
    ir_transmitting:  bool  = False
    lora_connected:   bool  = False  # ESP32-n kezelt; itt csak megjelenítési célra
    # Debug mezők (böngészős debug UI)
    debug_annotation: bool         = False
    vision_state:     str          = "WAIT_FOR_F"
    last_digit:       Optional[int] = None
    motor_speeds:     List[float]  = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])  # ESP32-n kezelt; itt csak megjelenítési célra
    ir_last_code:     str          = "---"
    ir_tx_count:      int          = 0


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


async def main(args: argparse.Namespace) -> None:
    # ── Beállítások alkalmazása a CLI argumentumokból ──────────────────────
    if args.dry_run:
        settings.DRY_RUN = True
    if args.test_video:
        settings.CAMERA_TEST_VIDEO = args.test_video
    if args.role:
        settings.ROBOT_ROLE = args.role

    # ── Logger inicializálás ───────────────────────────────────────────────
    log = setup_logger()

    # ── Megosztott állapot ─────────────────────────────────────────────────
    state             = RobotState(role=settings.ROBOT_ROLE)
    state.ip_address  = _get_local_ip()

    log.info(f"{'=' * 50}")
    log.info(f"  {settings.ROBOT_NAME}  |  Szerep: {state.role}")
    log.info(f"  IP: {state.ip_address}:{settings.STREAM_PORT}")
    if settings.DRY_RUN:
        log.warning("  *** DRY-RUN MÓD — hardver kikapcsolva ***")
    if settings.CAMERA_TEST_VIDEO:
        log.info(f"  Tesztvideó: {settings.CAMERA_TEST_VIDEO}")
    log.info(f"{'=' * 50}")

    # ── Kommunikációs queue-k ──────────────────────────────────────────────
    gate_code_queue: asyncio.Queue = asyncio.Queue(maxsize=10)

    # ── Komponensek inicializálása ─────────────────────────────────────────
    camera = CameraManager()
    vision = VisionProcessor()
    ir     = IRTransmitter()
    oled   = OLEDDisplay()
    stream = StreamServer()

    await camera.start()

    # ── Asyncio taskok indítása ────────────────────────────────────────────
    tasks = [
        asyncio.create_task(vision.processing_loop(camera, gate_code_queue, state),
                            name="vision"),
        asyncio.create_task(ir.transmit_loop(gate_code_queue, state),
                            name="ir"),
        asyncio.create_task(oled.update_loop(state),
                            name="oled"),
        asyncio.create_task(
            stream.serve(camera, state, vision, ir,
                         enable_test_ui=args.test_ui),
            name="stream",
        ),
    ]

    log.info(f"Web UI elérhető: http://{state.ip_address}:{settings.STREAM_PORT}")
    if args.test_ui:
        log.info(f"Teszt UI elérhető: http://{state.ip_address}:{settings.TEST_UI_PORT}")
    log.info("Robot futásban. Ctrl+C a leállításhoz.")

    # ── Leállítás kezelése ─────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(*_):
        log.info("Leállítás jelzés fogadva...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    try:
        # Fut amíg le nem állítják, vagy valamelyik task meg nem hal
        done, pending = await asyncio.wait(
            [asyncio.create_task(stop_event.wait())] + tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await camera.stop()
        log.info("Robot leállítva.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"RoBot vezérlő",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--test-video", metavar="PATH",
        help="Videófájl kamera helyett (pl. kapu.mp4)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Hardver nélküli szimulációs mód"
    )
    parser.add_argument(
        "--role", choices=["PACMAN", "GHOST"],
        help="Szerep felülírása induláskor"
    )
    parser.add_argument(
        "--test-ui", action="store_true",
        help=f"Teszt UI indítása a {settings.TEST_UI_PORT}-es porton (vision/IR/motor teszteléshez)"
    )
    args = parser.parse_args()
    asyncio.run(main(args))
