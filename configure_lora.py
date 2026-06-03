#!/usr/bin/env python3
"""
E22-900T22D-V2 LoRa modul konfigurációs script.

Mindkét eszközön (Pi + Jetson) futtatni kell egymás után.
Beállítja a maximális air data rate-et (62.5kbps).

Futtatás Pi-n:
    ~/RoBot-MAM16/BotController/venv/bin/python configure_lora.py --pi

Futtatás Jetsonnál:
    ~/RoBot-MAM16/BotCode/venv/bin/python configure_lora.py --jetson
"""

import argparse
import sys
import time

# ── Config ────────────────────────────────────────────────────────────────────

CHANNEL  = 18     # 850.125 + 18 = 868.125 MHz
# REG0: UART 9600 baud (011) + 8N1 (00) + air 62.5kbps (110) = 0x66
REG0_TARGET = 0x66
# REG1: sub-packet 200B (01) + RSSI noise off (0) + TX 22dBm (11) = 0x43
REG1_TARGET = 0x43

# ── Argumentumok ──────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="E22 LoRa konfiguráció")
grp = parser.add_mutually_exclusive_group(required=True)
grp.add_argument("--pi",     action="store_true", help="Raspberry Pi (ttyAMA0, RPi.GPIO)")
grp.add_argument("--jetson", action="store_true", help="Jetson Nano (ttyTHS1, Jetson.GPIO)")
args = parser.parse_args()

if args.pi:
    UART_PORT = "/dev/ttyAMA0"
    M0_PIN, M1_PIN, AUX_PIN = 20, 21, 16
    import RPi.GPIO as GPIO
else:
    UART_PORT = "/dev/ttyTHS1"
    M0_PIN, M1_PIN, AUX_PIN = 20, 21, 16
    import Jetson.GPIO as GPIO

import serial

# ── GPIO init ─────────────────────────────────────────────────────────────────

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(M0_PIN,  GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(M1_PIN,  GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(AUX_PIN, GPIO.IN)

def wait_aux(timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if GPIO.input(AUX_PIN) == GPIO.HIGH:
                return True
        except Exception:
            pass
        time.sleep(0.01)
    return False

def read_all(ser, timeout=2.0):
    """Olvas mindent ami jön a megadott ideig."""
    buf = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ser.in_waiting:
            buf.extend(ser.read(ser.in_waiting))
        time.sleep(0.01)
    return bytes(buf)

# ── Serial megnyitása (konfigurációs mód ELŐTT) ───────────────────────────────

print(f"Port: {UART_PORT}")
print("Soros port megnyitása...")
ser = serial.Serial(UART_PORT, 9600, timeout=2.0)
time.sleep(0.2)

# Bármilyen korábbi adat kiürítése
ser.reset_input_buffer()

# ── Konfigurációs mód (M0=HIGH, M1=HIGH) ─────────────────────────────────────

print("Konfigurációs módba lépés (M0=H M1=H)...")
GPIO.output(M0_PIN, GPIO.HIGH)
GPIO.output(M1_PIN, GPIO.HIGH)

# AUX nélkül hosszabb várakozás
aux_ok = wait_aux(3.0)
print(f"  AUX: {'HIGH (kész)' if aux_ok else 'timeout — folytatjuk'}")
time.sleep(0.5)  # extra várakozás az E22-nek

# Bármilyen auto-küldött adat az E22-től
auto = read_all(ser, 0.5)
if auto:
    print(f"  Auto-üzenet az E22-től: {auto.hex()}")

# ── Jelenlegi konfig olvasása ─────────────────────────────────────────────────

print("Jelenlegi konfig olvasása (C1 00 09)...")
ser.write(bytes([0xC1, 0x00, 0x09]))
ser.flush()
resp = read_all(ser, 2.0)
print(f"  Válasz ({len(resp)} byte): {resp.hex() if resp else 'semmi'}")

if not resp:
    print("\n  FIGYELEM: Nincs válasz az E22-től!")
    print("  Lehetséges okok:")
    print("  - M0/M1 pin nincs rendesen bekötve")
    print("  - A modul nem lép be konfigurációs módba")
    print("  - Ellenőrizd: M0→Pin38 (BCM20), M1→Pin40 (BCM21)")
    print()
    # Alternatív próba: C0 parancs
    print("Alternatív próba (C0 00 09)...")
    ser.write(bytes([0xC0, 0x00, 0x09]))
    ser.flush()
    resp2 = read_all(ser, 2.0)
    print(f"  Válasz: {resp2.hex() if resp2 else 'semmi'}")

# ── Új konfig írása ───────────────────────────────────────────────────────────

print(f"\nÚj konfig írása...")
print(f"  REG0=0x{REG0_TARGET:02X} (9600 baud, 8N1, 62.5kbps air rate)")
print(f"  REG1=0x{REG1_TARGET:02X} (200B sub-packet, 22dBm TX power)")
print(f"  CH  ={CHANNEL} ({850.125 + CHANNEL:.3f} MHz)")

cfg = bytes([
    0xC0,               # Write to EEPROM
    0x00, 0x09,         # Start address 0, length 9
    0x00, 0x00,         # ADDH, ADDL (broadcast)
    REG0_TARGET,        # UART + air rate
    REG1_TARGET,        # TX power + sub-packet
    CHANNEL,            # Channel
    0x00,               # REG3 default
    0x00, 0x00,         # CRYPT off
])
print(f"  Küldés: {cfg.hex()}")
ser.write(cfg)
ser.flush()
ack = read_all(ser, 2.0)
print(f"  Nyugta: {ack.hex() if ack else 'semmi'}")

# ── Ellenőrzés ────────────────────────────────────────────────────────────────

print("\nKonfig ellenőrzése...")
ser.write(bytes([0xC1, 0x00, 0x09]))
ser.flush()
verify = read_all(ser, 2.0)
print(f"  Válasz: {verify.hex() if verify else 'semmi'}")

if len(verify) >= 12:
    reg0_got = verify[5]
    ch_got   = verify[7]
    ok = reg0_got == REG0_TARGET and ch_got == CHANNEL
    print(f"  REG0: {'OK' if reg0_got == REG0_TARGET else 'HIBA'} (várt=0x{REG0_TARGET:02X}, kapott=0x{reg0_got:02X})")
    print(f"  CH:   {'OK' if ch_got == CHANNEL else 'HIBA'} (várt={CHANNEL}, kapott={ch_got})")
    print(f"\n  {'✓ Konfiguráció sikeres!' if ok else '✗ Konfiguráció sikertelen'}")
elif verify:
    print("  Rövid válasz — formátum nem egyezik, de valami érkezett.")
else:
    print("  Nincs válasz — az E22 nem reagál AT parancsokra.")
    print("  A robot valószínűleg az alapértelmezett 2.4kbps-en kommunikál.")
    print("  Ebben az esetben állítsd CTRL_SEND_HZ=2-re a BotController/settings.py-ban.")

# ── Vissza transparent módba ──────────────────────────────────────────────────

ser.close()
print("\nVissza transparent módba (M0=L M1=L)...")
GPIO.output(M0_PIN, GPIO.LOW)
GPIO.output(M1_PIN, GPIO.LOW)
time.sleep(0.2)
GPIO.cleanup([M0_PIN, M1_PIN, AUX_PIN])
print("Kész.")
