"""
MAM16 BotController — Főprogram

Indítás:
  python main.py                        # Normál mód
  python main.py --dry-run              # Hardver nélküli szimuláció
  python main.py --speed-limit 0.7      # Sebesség limit (0.0–1.0)
  python main.py --device /dev/input/event3  # Kontroller eszköz
"""

import argparse
import asyncio
import logging
import signal
from dataclasses import dataclass, field

import settings
from web_server       import ControllerWebServer, load_config
from controller_input import GamepadReader
from lora_sender      import LoraSender


@dataclass
class ControllerState:
    gamepad_connected:     bool  = False
    lora_authenticated:    bool  = False
    linear:                float = 0.0
    angular:               float = 0.0
    lt:                    float = 0.0
    rt:                    float = 0.0
    stick_x:               float = 0.0
    lora_reinit_requested: bool  = False


def _setup_logger() -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("main")


async def _handshake_loop(sender: LoraSender, state: ControllerState) -> None:
    while True:
        state.lora_authenticated = False
        ok = await asyncio.get_event_loop().run_in_executor(
            None, lambda: sender.do_handshake(timeout_sec=10.0)
        )
        if ok:
            state.lora_authenticated = True
            return
        await asyncio.sleep(settings.CTRL_RECONNECT_SEC)


async def control_loop(
    sender:  LoraSender,
    gamepad: GamepadReader,
    state:   ControllerState,
    dry_run: bool,
) -> None:
    log = logging.getLogger("main")
    interval = 1.0 / settings.CTRL_SEND_HZ

    while True:
        # ── Handshake (vagy újra-handshake ha LoRa újrainicializálás kell) ──
        if state.lora_reinit_requested:
            log.info("LoRa újrainicializálás...")
            await asyncio.get_event_loop().run_in_executor(None, sender.reinit)
            state.lora_reinit_requested = False

        if not state.lora_authenticated:
            log.info("LoRa handshake indítása...")
            await _handshake_loop(sender, state)

        # ── Gamepad megnyitás / újracsatlakozás ──────────────────────────────
        if not state.gamepad_connected:
            log.info("Gamepad keresése...")
            ok = await asyncio.get_event_loop().run_in_executor(None, gamepad.open)
            if not ok:
                await asyncio.sleep(1.0)
                continue
            state.gamepad_connected = True
            log.info("Kontroller csatlakozva")

        # ── Fő vezérlési ciklus ───────────────────────────────────────────────
        t0 = asyncio.get_event_loop().time()
        try:
            linear, angular = await asyncio.get_event_loop().run_in_executor(
                None, gamepad.read_state
            )
        except OSError:
            log.warning("Kontroller lecsatlakozva")
            await asyncio.get_event_loop().run_in_executor(None, sender.send_stop)
            gamepad.close()
            state.gamepad_connected = False
            continue

        state.linear  = linear
        state.angular = angular
        state.lt      = gamepad.raw_lt
        state.rt      = gamepad.raw_rt
        state.stick_x = gamepad.raw_steer

        if dry_run:
            if linear or angular:
                log.debug(f"[DRY-RUN] linear={linear:.3f} angular={angular:.3f}")
        else:
            if linear != 0.0 or angular != 0.0:
                sender.send_command(linear, angular)
            # keepalive stop ~1 Hz
            elif int(t0 * 1.0) % max(1, int(settings.CTRL_SEND_HZ)) == 0:
                sender.send_stop()

        elapsed = asyncio.get_event_loop().time() - t0
        await asyncio.sleep(max(0.0, interval - elapsed))


async def main(args: argparse.Namespace) -> None:
    load_config()

    if args.dry_run:
        pass  # settings változtatás nem kell, komponensek self-detect

    if args.speed_limit is not None:
        settings.CTRL_SPEED_LIMIT = max(0.0, min(1.0, args.speed_limit))

    if args.device:
        settings.CTRL_GAMEPAD_DEVICE = args.device

    log = _setup_logger()
    log.info("=" * 50)
    log.info("  MAM16 BotController")
    log.info(f"  Sebesség limit: {settings.CTRL_SPEED_LIMIT * 100:.0f}%")
    if args.dry_run:
        log.warning("  *** DRY-RUN MÓD — hardver kikapcsolva ***")
    log.info("=" * 50)

    state   = ControllerState()
    sender  = LoraSender()
    gamepad = GamepadReader()
    webui   = ControllerWebServer(state)

    if not args.dry_run:
        await asyncio.get_event_loop().run_in_executor(None, sender.open)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    ctrl_task = asyncio.create_task(
        control_loop(sender, gamepad, state, dry_run=args.dry_run),
        name="control",
    )
    web_task = asyncio.create_task(webui.serve(), name="web")

    log.info(f"Beállítás UI: http://0.0.0.0:{settings.WEB_PORT}")
    log.info("Fut. Ctrl+C a leállításhoz.")

    try:
        done, _ = await asyncio.wait(
            [asyncio.create_task(stop_event.wait()), ctrl_task, web_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        ctrl_task.cancel()
        web_task.cancel()
        await asyncio.gather(ctrl_task, web_task, return_exceptions=True)
        if not args.dry_run:
            sender.send_stop()
            sender.close()
        gamepad.close()
        log.info("BotController leállítva.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MAM16 BotController",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run",     action="store_true",
                        help="Hardver nélküli szimulációs mód")
    parser.add_argument("--speed-limit", type=float, metavar="0.0-1.0",
                        help="Sebesség limit felülírása (0.0–1.0)")
    parser.add_argument("--device",      metavar="PATH",
                        help="Gamepad eszköz (pl. /dev/input/event3)")
    asyncio.run(main(parser.parse_args()))
