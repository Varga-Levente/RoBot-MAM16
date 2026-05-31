// =============================================================================
//  RoBot MAM16 - ESP8266 Teszt konfiguráció
//  Arduino IDE
//
//  Pineket és WiFi beállításokat itt lehet módosítani.
//
//  NodeMCU lábkiosztás (D-jelölés → GPIO):
//    D0=16  D1=5   D2=4   D3=0   D4=2
//    D5=14  D6=12  D7=13  D8=15
// =============================================================================

#pragma once

// ── WIFI HOTSPOT ─────────────────────────────────────────────────────────────

#define WIFI_SSID     "MAM16-RoBot"
#define WIFI_PASSWORD "12345678"

// ── LED ──────────────────────────────────────────────────────────────────────
// Az ESP8266 beépített LED-je GPIO2 (D4), és aktív LOW.

#define LED_PIN         2       // GPIO szám (D4 = GPIO2 = beépített LED)
#define LED_ACTIVE_LOW  true    // true = aktív LOW (beépített LED)
#define LED_BLINK_MS    1000    // Villogás: ennyi ms be, majd ennyi ms ki

// ── MOTOROK ──────────────────────────────────────────────────────────────────
// DRV8833 motor driver GPIO kiosztás.
// Minden motorhoz 2 PWM pin kell (IN1, IN2).

// Bal első (Front Left)
#define MOTOR_FL_IN1    5       // D1
#define MOTOR_FL_IN2    4       // D2

// Jobb első (Front Right)
#define MOTOR_FR_IN1    0       // D3
#define MOTOR_FR_IN2    14      // D5

// Bal hátsó (Rear Left)
#define MOTOR_RL_IN1    12      // D6
#define MOTOR_RL_IN2    13      // D7

// Jobb hátsó (Rear Right)
#define MOTOR_RR_IN1    15      // D8
#define MOTOR_RR_IN2    16      // D0

#define MOTOR_PWM_FREQ  1000    // PWM frekvencia (Hz) — ESP8266: analogWriteFreq()
#define MOTOR_SPEED     800     // Alapsebesség (0–1023 PWM duty)
