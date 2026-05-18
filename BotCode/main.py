"""
MAM16 Robot - Főprogram

Indítás:
  python main.py                                # Teljes robot üzemmód
  python main.py --dry-run                      # Hardver nélküli szimuláció
  python main.py --test-video kapu.mp4          # Videófájl kamera helyett
  python main.py --role GHOST                   # Szerep felülírása
  python main.py --test-video kapu.mp4 --dry-run  # Kombinált teszt
"""

import argparse
import asyncio
import logging
import signal
import socket
from dataclasses import dataclass, field

import settings
from utils.logger import setup_logger
from components.camera         import CameraManager
from components.vision         import VisionProcessor
from components.ir_transmitter import IRTransmitter
from components.lora_comm      import LoRaComm
from components.oled_display   import OLEDDisplay
from components.motor_controller import MotorController
from components.stream_server  import StreamServer


@dataclass
class RobotState:
    role:             str   = field(default_factory=lambda: settings.ROBOT_ROLE)
    ip_address:       str   = ""
    battery_voltage:  float = 0.0
    last_gate_code:   str   = "---"
    ir_transmitting:  bool  = False
    lora_connected:   bool  = False


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
    command_queue:   asyncio.Queue = asyncio.Queue(maxsize=50)

    # ── Komponensek inicializálása ─────────────────────────────────────────
    camera = CameraManager()
    vision = VisionProcessor()
    ir     = IRTransmitter()
    lora   = LoRaComm()
    oled   = OLEDDisplay()
    motor  = MotorController()
    stream = StreamServer()

    await camera.start()

    # ── Asyncio taskok indítása ────────────────────────────────────────────
    tasks = [
        asyncio.create_task(vision.processing_loop(camera, gate_code_queue, state),
                            name="vision"),
        asyncio.create_task(ir.transmit_loop(gate_code_queue, state),
                            name="ir"),
        asyncio.create_task(lora.receive_loop(command_queue, state),
                            name="lora"),
        asyncio.create_task(motor.command_loop(command_queue, state),
                            name="motor"),
        asyncio.create_task(oled.update_loop(state),
                            name="oled"),
        asyncio.create_task(stream.serve(camera, state),
                            name="stream"),
    ]

    log.info(f"Web UI elérhető: http://{state.ip_address}:{settings.STREAM_PORT}")
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
        motor.cleanup()
        log.info("Robot leállítva.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"MAM16 Robot vezérlő",
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
    args = parser.parse_args()
    asyncio.run(main(args))
