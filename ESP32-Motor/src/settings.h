#pragma once

// ── LoRa UART beállítások ──────────────────────────────────────────────────
// ESP32-S3 DevKitC: GPIO1=TX, GPIO3=RX (fejléc TX/RX lábak)
// Debug kimenet: USB-CDC (Serial, GPIO19/20 — natív USB)
#define LORA_UART_PORT  1       // HardwareSerial(1) — UART1, szabad a TX/RX lábakra
#define LORA_UART_TX    1       // GPIO1 = TX fejléc láb
#define LORA_UART_RX    3       // GPIO3 = RX fejléc láb
#define LORA_UART_BAUD  115200  // Baud rate

// ── Motor GPIO kiosztás (2× DRV8833, ESP32-S3 DevKitC N16R8) ─────────────
// Elülső bal (Front Left)
#define LEFT_FRONT_FWD   4
#define LEFT_FRONT_REV   5
// Hátsó bal (Back Left)
#define LEFT_REAR_FWD    6
#define LEFT_REAR_REV    7
// Elülső jobb (Front Right)
#define RIGHT_FRONT_FWD  15
#define RIGHT_FRONT_REV  16
// Hátsó jobb (Back Right)
#define RIGHT_REAR_FWD   17
#define RIGHT_REAR_REV   18

// ── Motor PWM beállítások ──────────────────────────────────────────────────
#define MOTOR_PWM_FREQ  1000    // PWM frekvencia Hz-ben
#define MOTOR_PWM_RES   8       // Felbontás bitek (0-255 duty cycle)

// ── Motor vezérlés időzítők ────────────────────────────────────────────────
#define MOTOR_TIMEOUT_MS        500     // Watchdog: ennyi ms parancs nélkül → vészleállás
#define MOTOR_JUMP_DURATION_MS  1000    // Ugrás parancs alapértelmezett időtartama (ms)

// ── LoRa titkosítás és azonosítás ─────────────────────────────────────────
// Eszközazonosító (4 byte)
#define LORA_DEVICE_ID  { 0xDE, 0xAD, 0xBE, 0xEF }

// AES-128 kulcs (pontosan 16 byte)
#define LORA_AES_KEY    "change_me_16byte"

// HMAC kulcs (28 byte)
#define LORA_HMAC_KEY   "change_me_hmac_key_32bytes!!"

// ── Debug soros port ───────────────────────────────────────────────────────
#define DEBUG_BAUD  115200
