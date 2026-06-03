#!/usr/bin/env python3
"""
E22-900T22D-V2 LoRa modul konfigurációs script.

Mindkét eszközön (Pi + Jetson) futtatni kell egymás után.
Beállítja a maximális air data rate-et (62.5kbps).

FONTOS: A konfigurációs mód Mode 2: M0=LOW, M1=HIGH
        (M0=HIGH, M1=HIGH = Mode 3 = Deep Sleep — NEM konfigurációs mód!)

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

# REG0 (03H): UART baud + parity + air data rate
#   bits 7,6,5 = 011 → 9600 baud
#   bits 4,3   = 00  → 8N1
#   bits 2,1,0 = 111 → 62.5kbps
REG0_TARGET = 0x67

# REG1 (04H): sub-packet + RSSI noise + TX power
#   bits 7,6 = 00 → 240B sub-packet (largest)
#   bit 5    = 0  → RSSI ambient noise off
#   bits 4,3,2 = 000 → reserved
#   bits 1,0 = 00 → 22dBm (max)
REG1_TARGET = 0x00

# ── Argumentumok ──────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="E22 LoRa konfiguráció")
grp = parser.add_mutually_exclusive_group(required=True)
grp.add_argument("--pi",     action="store_true", help="Raspberry Pi (ttyAMA0, RPi.GPIO)")
grp.add_argument("--jetson", action="store_true", help="Jetson Nano (ttyTHS1, Jetson.GPIO)")
args = parser.parse_args()

if args.pi:
    UART_PORT = "/dev/ttyAMA0"
    GPIO_MODE = "BCM"
    M0_PIN, M1_PIN, AUX_PIN = 20, 21, 16   # BCM számok
    import RPi.GPIO as GPIO
else:
    UART_PORT = "/dev/ttyTHS1"
    GPIO_MODE = "BOARD"
    M0_PIN, M1_PIN, AUX_PIN = 38, 40, 36   # Fizikai pin számok (BOARD mód)
    import Jetson.GPIO as GPIO

import serial

# ── GPIO init ─────────────────────────────────────────────────────────────────

if GPIO_MODE == "BCM":
    GPIO.setmode(GPIO.BCM)
else:
    GPIO.setmode(GPIO.BOARD)
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
ser.reset_input_buffer()

# ── Konfigurációs mód (M0=LOW, M1=HIGH = Mode 2) ─────────────────────────────
# FONTOS: Mode 2 = M0=0, M1=1  (NEM M0=1, M1=1 ami Deep Sleep!)

print("Konfigurációs módba lépés (M0=L, M1=H = Mode 2)...")
GPIO.output(M0_PIN, GPIO.LOW)
GPIO.output(M1_PIN, GPIO.HIGH)

aux_ok = wait_aux(3.0)
print(f"  AUX: {'HIGH (kész)' if aux_ok else 'timeout — folytatjuk'}")
time.sleep(0.5)

auto = read_all(ser, 0.5)
if auto:
    print(f"  Auto-üzenet az E22-től: {auto.hex()}")

# ── Jelenlegi konfig olvasása ─────────────────────────────────────────────────
# Regiszterek 00H..08H: ADDH, ADDL, NETID, REG0, REG1, CH, REG3, CRYPT_H, CRYPT_L

print("Jelenlegi konfig olvasása (C1 00 09)...")
ser.write(bytes([0xC1, 0x00, 0x09]))
ser.flush()
resp = read_all(ser, 2.0)
print(f"  Válasz ({len(resp)} byte): {resp.hex() if resp else 'semmi'}")

if len(resp) >= 12:
    # Válasz: C1 + start + len + 9 adat byte
    addh   = resp[3]
    addl   = resp[4]
    netid  = resp[5]
    reg0   = resp[6]
    reg1   = resp[7]
    ch     = resp[8]
    reg3   = resp[9]
    baud_idx  = (reg0 >> 5) & 0x07
    air_idx   = reg0 & 0x07
    air_rates = ["0.3k","1.2k","2.4k","4.8k","9.6k","19.2k","38.4k","62.5k"]
    baud_rates = [1200,2400,4800,9600,19200,38400,57600,115200]
    print(f"  ADDR:  0x{addh:02X}{addl:02X}  NETID: 0x{netid:02X}")
    print(f"  REG0:  0x{reg0:02X}  → UART {baud_rates[baud_idx]}bps, air {air_rates[air_idx]}")
    print(f"  REG1:  0x{reg1:02X}  CH: {ch} ({850.125+ch:.3f} MHz)")
elif resp:
    print("  Rövid vagy érvénytelen válasz.")
else:
    print("\n  FIGYELEM: Nincs válasz!")
    print("  Ellenőrizd: M0→BCM20 (Pin38), M1→BCM21 (Pin40), AUX→BCM16 (Pin36)")
    print("  A modul 9600 baud 8N1-en válaszol konfigurációs módban.")
    print()
    print("  Folytatjuk az írással...")

# ── Új konfig írása ───────────────────────────────────────────────────────────
# Regiszterek: ADDH ADDL NETID REG0 REG1 CH REG3 CRYPT_H CRYPT_L (9 byte)

print(f"\nÚj konfig írása (C0 00 09 ...):")
print(f"  ADDH=0x00 ADDL=0x00 NETID=0x00")
print(f"  REG0=0x{REG0_TARGET:02X} → 9600 baud, 8N1, 62.5kbps air rate")
print(f"  REG1=0x{REG1_TARGET:02X} → 240B sub-packet, 22dBm TX power")
print(f"  CH  =0x{CHANNEL:02X} ({850.125 + CHANNEL:.3f} MHz)")
print(f"  REG3=0x00 CRYPT_H=0x00 CRYPT_L=0x00")

cfg = bytes([
    0xC0,          # Write to EEPROM (C0 = permanent)
    0x00, 0x09,    # Start address 0x00, length 9
    0x00, 0x00,    # ADDH, ADDL (broadcast address)
    0x00,          # NETID (network ID)
    REG0_TARGET,   # REG0: UART baud + parity + air rate
    REG1_TARGET,   # REG1: sub-packet + RSSI + TX power
    CHANNEL,       # REG2/CH: channel number
    0x00,          # REG3: no repeater, no LBT, WOR receiver default
    0x00, 0x00,    # CRYPT_H, CRYPT_L: encryption key off
])
print(f"  Küldés ({len(cfg)} byte): {cfg.hex()}")
ser.write(cfg)
ser.flush()
ack = read_all(ser, 2.0)
print(f"  Nyugta ({len(ack)} byte): {ack.hex() if ack else 'semmi'}")

# ── Ellenőrzés ────────────────────────────────────────────────────────────────

print("\nKonfig ellenőrzése (C1 00 09)...")
ser.write(bytes([0xC1, 0x00, 0x09]))
ser.flush()
verify = read_all(ser, 2.0)
print(f"  Válasz ({len(verify)} byte): {verify.hex() if verify else 'semmi'}")

if len(verify) >= 12:
    reg0_got = verify[6]
    reg1_got = verify[7]
    ch_got   = verify[8]
    ok_reg0 = reg0_got == REG0_TARGET
    ok_reg1 = reg1_got == REG1_TARGET
    ok_ch   = ch_got == CHANNEL
    print(f"  REG0: {'OK' if ok_reg0 else 'HIBA'} (várt=0x{REG0_TARGET:02X}, kapott=0x{reg0_got:02X})")
    print(f"  REG1: {'OK' if ok_reg1 else 'HIBA'} (várt=0x{REG1_TARGET:02X}, kapott=0x{reg1_got:02X})")
    print(f"  CH:   {'OK' if ok_ch else 'HIBA'} (várt={CHANNEL}, kapott={ch_got})")
    if ok_reg0 and ok_reg1 and ok_ch:
        print(f"\n  ✓ Konfiguráció sikeres! Air rate: 62.5kbps, TX: 22dBm, CH: {CHANNEL}")
        print(f"  Most beállíthatod a BotController/settings.py-ban: CTRL_SEND_HZ = 20")
    else:
        print(f"\n  ✗ Konfiguráció sikertelen — módosítások nem léptek életbe")
elif verify:
    print("  Rövid válasz — formátum nem egyezik.")
else:
    print("  Nincs válasz ellenőrzéskor.")
    print("  Ha az írás nyugta sem érkezett, az E22 valószínűleg nem lép be konfigurációs módba.")
    print("  Ellenőrizd az M0/M1 bekötést és a 9600 baud UART-ot.")

# ── Vissza normal módba (M0=L, M1=L = Mode 0) ────────────────────────────────

ser.close()
print("\nVissza normál módba (M0=L, M1=L = Mode 0)...")
GPIO.output(M0_PIN, GPIO.LOW)
GPIO.output(M1_PIN, GPIO.LOW)
time.sleep(0.5)
GPIO.cleanup([M0_PIN, M1_PIN, AUX_PIN])
print("Kész.")
