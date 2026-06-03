#!/usr/bin/env python3
"""
E22-900T22D-V2 LoRa modul konfigurációs script.

Mindkét eszközön (Pi + Jetson) futtatni kell egymás után.
Beállítja a maximális air data rate-et (62.5kbps) és tartja a
csatornát, hogy a 20Hz-es parancsküldés ne okozzon puffer-torlódást.

Futtatás Pi-n:
    python3 configure_lora.py --pi

Futtatás Jetsonnál:
    python3.8 configure_lora.py --jetson
"""

import argparse
import sys
import time

# ── Config ────────────────────────────────────────────────────────────────────

# Közös beállítások (mindkét modulon azonos)
CHANNEL   = 18     # 850.125 + 18 = 868.125 MHz
TX_POWER  = 22     # dBm (max)

# E22 REG0: UART baud + parity + air data rate
# Bits 7-5: UART baud  (011=9600)
# Bits 4-3: parity     (00=8N1)
# Bits 2-0: air rate   (110=62.5kbps)
REG0 = 0b01100110  # 0x66 — 9600 baud, 8N1, 62.5kbps air rate

# E22 REG1: sub-packet (10=200 bytes), RSSI noise off, TX power (11=22dBm)
REG1 = 0b01000011  # 0x43

# E22 REG3: RSSI byte off, forward error correction on, LBT off
REG3 = 0b00000000  # 0x00

# ── Platform argumentumok ─────────────────────────────────────────────────────

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

def wait_aux(timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if GPIO.input(AUX_PIN) == GPIO.HIGH:
                return True
        except Exception:
            pass
        time.sleep(0.01)
    return False  # Timeout — folytatjuk AUX nélkül

def set_mode(m0, m1):
    GPIO.output(M0_PIN, GPIO.HIGH if m0 else GPIO.LOW)
    GPIO.output(M1_PIN, GPIO.HIGH if m1 else GPIO.LOW)
    time.sleep(0.1)
    wait_aux(1.0)

# ── Konfigurációs mód (M0=HIGH, M1=HIGH) ─────────────────────────────────────

print(f"Port: {UART_PORT}")
print("Konfigurációs módba lépés (M0=H M1=H)...")
set_mode(1, 1)
time.sleep(0.2)

ser = serial.Serial(UART_PORT, 9600, timeout=1.0)
ser.reset_input_buffer()

# ── Jelenlegi konfig olvasása ─────────────────────────────────────────────────

print("Jelenlegi konfig olvasása...")
ser.write(bytes([0xC1, 0x00, 0x09]))
ser.flush()
time.sleep(0.2)
resp = ser.read(12)
if len(resp) >= 9:
    print(f"  Jelenlegi: {resp.hex()}")
    old_reg0   = resp[2]
    old_reg1   = resp[3]
    old_ch     = resp[4]
    print(f"  REG0=0x{old_reg0:02X}  REG1=0x{old_reg1:02X}  CH={old_ch}")
else:
    print(f"  Nem sikerült olvasni (kapott: {resp.hex() if resp else 'semmi'})")

# ── Új konfig írása ───────────────────────────────────────────────────────────

# Csomag: C0 00 09 ADDH ADDL REG0 REG1 CH REG3 00 00 00
cfg = bytes([
    0xC0,          # Write command
    0x00, 0x09,    # Starting address 0, length 9
    0x00, 0x00,    # ADDH, ADDL (broadcast address)
    REG0,          # UART 9600, 8N1, 62.5kbps air rate
    REG1,          # Sub-packet 200B, RSSI off, 22dBm
    CHANNEL,       # Channel 18 = 868.125 MHz
    REG3,          # Default options
    0x00, 0x00,    # CRYPT_H, CRYPT_L (hardware enc off)
])

print(f"Új konfig írása: {cfg.hex()}")
ser.write(cfg)
ser.flush()
time.sleep(0.3)
ack = ser.read(12)
print(f"  Válasz: {ack.hex() if ack else 'semmi'}")

# ── Ellenőrzés ────────────────────────────────────────────────────────────────

print("Konfig ellenőrzése...")
ser.write(bytes([0xC1, 0x00, 0x09]))
ser.flush()
time.sleep(0.2)
verify = ser.read(12)
if len(verify) >= 7:
    actual_reg0 = verify[2]
    actual_ch   = verify[4]
    ok_reg0 = actual_reg0 == REG0
    ok_ch   = actual_ch   == CHANNEL
    print(f"  REG0: {'OK' if ok_reg0 else 'HIBA'} (várt=0x{REG0:02X}, kapott=0x{actual_reg0:02X})")
    print(f"  CH:   {'OK' if ok_ch   else 'HIBA'} (várt={CHANNEL}, kapott={actual_ch})")
    if ok_reg0 and ok_ch:
        print("\n  ✓ Konfiguráció sikeres!")
    else:
        print("\n  ✗ Konfiguráció sikertelen — ellenőrizd a kapcsolatot.")
else:
    print(f"  Ellenőrzés nem sikerült: {verify.hex() if verify else 'semmi'}")

# ── Vissza transparent módba (M0=LOW, M1=LOW) ─────────────────────────────────

ser.close()
print("\nVissza transparent módba (M0=L M1=L)...")
set_mode(0, 0)
GPIO.cleanup([M0_PIN, M1_PIN, AUX_PIN])
print("Kész.")
