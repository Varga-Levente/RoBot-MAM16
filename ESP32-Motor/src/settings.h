#pragma once

// ── LoRa UART beállítások ──────────────────────────────────────────────────
#define LORA_UART_PORT  2       // HardwareSerial port száma
#define LORA_UART_TX    17      // TX GPIO
#define LORA_UART_RX    16      // RX GPIO
#define LORA_UART_BAUD  115200  // Baud rate

// ── Motor GPIO kiosztás (ESP32-safe: nem strapping, nem input-only) ────────
// Elülső bal (FL)
#define FL_IN1  25
#define FL_IN2  26
// Elülső jobb (FR)
#define FR_IN1  27
#define FR_IN2  14
// Hátsó bal (RL)
#define RL_IN1  18
#define RL_IN2  19
// Hátsó jobb (RR)
#define RR_IN1  22
#define RR_IN2  23

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
