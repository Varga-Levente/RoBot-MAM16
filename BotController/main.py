"""
RoBot BotController — Főprogram

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
from dataclasses import dataclass

import settings
from web_server       import ControllerWebServer, load_config
from controller_input import GamepadReader
from lora_sender      import LoraSender


@dataclass
class ControllerState:
    gamepad_connected:     bool  = False
    lora_hw_ok:            bool  = False
    lora_authenticated:    bool  = False
    linear:                float = 0.0
    angular:               float = 0.0
    lateral:               float = 0.0
    left_y:                float = 0.0
    lt:                    float = 0.0
    rt:                    float = 0.0
    stick_x:               float = 0.0
    jump_dir:              str   = ""
    btn_y:                 bool  = False
    btn_a:                 bool  = False
    btn_x:                 bool  = False
    btn_b:                 bool  = False
    lora_reinit_requested: bool  = False


def _setup_logger() -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("main")


async def _handshake_loop(sender: LoraSender, state: ControllerState) -> None:
    loop = asyncio.get_running_loop()
    while True:
        state.lora_authenticated = False
        ok = await loop.run_in_executor(
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
        try:
            await _control_tick(sender, gamepad, state, dry_run, interval, log)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"Vezérlési ciklus váratlan hiba: {e}", exc_info=True)
            await asyncio.sleep(1.0)


async def _control_tick(
    sender:   LoraSender,
    gamepad:  GamepadReader,
    state:    ControllerState,
    dry_run:  bool,
    interval: float,
    log:      logging.Logger,
) -> None:
    loop = asyncio.get_running_loop()

    # ── Gamepad megnyitás / újracsatlakozás ──────────────────────────────
    if not state.gamepad_connected:
        log.info("Gamepad keresése...")
        ok = await loop.run_in_executor(None, gamepad.open)
        if not ok:
            await asyncio.sleep(1.0)
            return
        state.gamepad_connected = True
        log.info("Kontroller csatlakozva")

    # ── Handshake (vagy újra-handshake ha LoRa újrainicializálás kell) ──
    if state.lora_hw_ok and state.lora_reinit_requested:
        log.info("LoRa újrainicializálás...")
        ok = await loop.run_in_executor(None, sender.reinit)
        state.lora_hw_ok = ok
        state.lora_reinit_requested = False

    if state.lora_hw_ok and not state.lora_authenticated:
        log.info("LoRa handshake indítása...")
        await _handshake_loop(sender, state)

    # ── Fő vezérlési ciklus ───────────────────────────────────────────────
    t0 = loop.time()
    try:
        linear, angular, lateral, left_y, jump_dir = await loop.run_in_executor(
            None, gamepad.read_state
        )
    except OSError:
        log.warning("Kontroller lecsatlakozva")
        gamepad.close()
        state.gamepad_connected = False
        return

    state.linear   = linear
    state.angular  = angular
    state.lateral  = lateral
    state.left_y   = left_y
    state.lt       = gamepad.raw_lt
    state.rt       = gamepad.raw_rt
    state.stick_x  = gamepad.raw_rx
    state.jump_dir = jump_dir or ""
    state.btn_y    = gamepad.btn_y
    state.btn_a    = gamepad.btn_a
    state.btn_x    = gamepad.btn_x
    state.btn_b    = gamepad.btn_b

    moving = (linear != 0.0 or angular != 0.0 or
              lateral != 0.0 or left_y  != 0.0)

    if dry_run:
        if moving or jump_dir:
            log.debug(f"[DRY-RUN] lin={linear:.3f} ang={angular:.3f} "
                      f"lat={lateral:.3f} ly={left_y:.3f} jump={jump_dir}")
    elif state.lora_hw_ok and state.lora_authenticated:
        if jump_dir:
            sender.send_jump(jump_dir, settings.CTRL_JUMP_DURATION)
            gamepad.queue_rumble(500, 0x8000, 0x5000)  # ugrás visszajelzés
        elif moving:
            sender.send_command(linear, angular, lateral, left_y)
        elif int(t0) % max(1, settings.CTRL_SEND_HZ) == 0:
            sender.send_stop()

    elapsed = loop.time() - t0
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
    log.info("  RoBot BotController")
    log.info(f"  Sebesség limit: {settings.CTRL_SPEED_LIMIT * 100:.0f}%")
    if args.dry_run:
        log.warning("  *** DRY-RUN MÓD — hardver kikapcsolva ***")
    log.info("=" * 50)

    state   = ControllerState()
    sender  = LoraSender()
    gamepad = GamepadReader()
    webui   = ControllerWebServer(state)

    if not args.dry_run:
        lora_ok = await asyncio.get_event_loop().run_in_executor(None, sender.open)
        state.lora_hw_ok = lora_ok
        if not lora_ok:
            log.warning("LoRa hardver nem elérhető — csak gamepad + web UI mód")

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

    def _on_task_done(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception():
            log.error(f"Task '{task.get_name()}' leállt: {task.exception()}", exc_info=task.exception())

    ctrl_task.add_done_callback(_on_task_done)
    web_task.add_done_callback(_on_task_done)

    try:
        await stop_event.wait()
    finally:
        ctrl_task.cancel()
        web_task.cancel()
        await asyncio.gather(ctrl_task, web_task, return_exceptions=True)
        if not args.dry_run and state.lora_hw_ok:
            sender.send_stop()
            sender.close()
        gamepad.close()
        log.info("BotController leállítva.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="RoBot BotController",
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
