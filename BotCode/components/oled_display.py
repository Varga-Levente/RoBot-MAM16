"""
OLED kijelző kezelő modul.

0.91 inches, 128x32 pixeles SSD1306 OLED, I2C csatlakozással.
Megjelenített információk (4 sor):
  Sor 1: Robot neve + szerep (PAC-MAN / GHOST)
  Sor 2: IP cím
  Sor 3: Akkufeszültség
  Sor 4: Utoljára felismert kapu kód
"""

import asyncio
import logging

import settings

log = logging.getLogger("oled")


class OLEDDisplay:
    def __init__(self):
        self._device = None

    def _init_hardware(self) -> bool:
        if settings.DRY_RUN:
            log.info("[DRY-RUN] OLED szimulálva")
            return True
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306

            serial = i2c(port=settings.OLED_I2C_BUS, address=settings.OLED_I2C_ADDRESS)
            self._device = ssd1306(
                serial,
                width=settings.OLED_WIDTH,
                height=settings.OLED_HEIGHT,
            )
            self._device.contrast(settings.OLED_CONTRAST)
            log.info(f"OLED inicializálva: I2C bus={settings.OLED_I2C_BUS} addr=0x{settings.OLED_I2C_ADDRESS:02X}")
            return True
        except Exception as e:
            log.error(f"OLED inicializálási hiba: {e}")
            return False

    def _render(self, state) -> None:
        if settings.DRY_RUN or self._device is None:
            return

        from luma.core.render import canvas
        from PIL import ImageFont

        # Beépített kis font
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        role_icon = "P" if state.role == "PACMAN" else "G"
        gate_code = state.last_gate_code if state.last_gate_code else "---"
        battery   = f"{state.battery_voltage:.1f}V" if state.battery_voltage > 0 else "---"
        lora_icon = "*" if state.lora_connected else "x"

        with canvas(self._device) as draw:
            # Sor 1: név + szerep + LoRa
            draw.text((0,  0), f"{settings.ROBOT_NAME} [{role_icon}] {lora_icon}", fill="white", font=font)
            # Sor 2: IP cím
            draw.text((0, 11), state.ip_address or "nincs IP", fill="white", font=font)
            # Sor 3: kapu kód
            draw.text((0, 22), f"Kod: {gate_code}", fill="white", font=font)

    async def update_loop(self, state) -> None:
        if not self._init_hardware():
            log.warning("OLED nem elérhető, kijelző hurok kimarad")
            while True:
                await asyncio.sleep(10)

        log.info("OLED frissítő hurok elindult")
        interval = 1.0 / settings.OLED_UPDATE_HZ
        while True:
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._render, state)
            except Exception as e:
                log.error(f"OLED render hiba: {e}")
            await asyncio.sleep(interval)

    def clear(self) -> None:
        if self._device:
            self._device.clear()


# ── Önálló teszt ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    class _MockState:
        role            = "PACMAN"
        ip_address      = "192.168.1.100"
        battery_voltage = 11.4
        last_gate_code  = "CA6"
        lora_connected  = True

    async def _run():
        display = OLEDDisplay()
        state   = _MockState()
        if not display._init_hardware():
            print("OLED nem érhető el (esetleg --dry-run szükséges?)")
            return
        display._render(state)
        print("OLED frissítve. Ctrl+C a kilépéshez.")
        await asyncio.sleep(5)
        display.clear()

    asyncio.run(_run())
