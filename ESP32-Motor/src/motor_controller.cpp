#include "motor_controller.h"
#include "settings.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <math.h>

// Motor pin párok: {IN1, IN2}
static const int MOTOR_PINS[4][2] = {
    {FL_IN1, FL_IN2},  // 0: Elülső bal (FL)
    {FR_IN1, FR_IN2},  // 1: Elülső jobb (FR)
    {RL_IN1, RL_IN2},  // 2: Hátsó bal (RL)
    {RR_IN1, RR_IN2},  // 3: Hátsó jobb (RR)
};

// LEDC csatornák (2 csatorna/motor)
static const int LEDC_CHANNELS[4][2] = {
    {0, 1},
    {2, 3},
    {4, 5},
    {6, 7},
};

void MotorController::init()
{
    _lastCmdMs = millis();
    for (int i = 0; i < 4; i++) {
        _speeds[i] = 0.0f;
    }

    // GPIO és LEDC csatornák inicializálása
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 2; j++) {
            int pin = MOTOR_PINS[i][j];
            int ch  = LEDC_CHANNELS[i][j];
            ledcSetup(ch, MOTOR_PWM_FREQ, MOTOR_PWM_RES);
            ledcAttachPin(pin, ch);
            ledcWrite(ch, 0);
        }
    }

    Serial.println("[Motor] Inicializálva.");
}

void MotorController::setMotor(int id, float speed)
{
    if (id < 0 || id >= 4) return;

    // Határok között tartás
    if (speed >  1.0f) speed =  1.0f;
    if (speed < -1.0f) speed = -1.0f;

    _speeds[id] = speed;

    int duty = (int)(fabsf(speed) * 255.0f);
    int ch_in1 = LEDC_CHANNELS[id][0];
    int ch_in2 = LEDC_CHANNELS[id][1];

    // DRV8833 PWM vezérlés
    if (speed > 0.0f) {
        ledcWrite(ch_in1, duty);
        ledcWrite(ch_in2, 0);
    } else if (speed < 0.0f) {
        ledcWrite(ch_in1, 0);
        ledcWrite(ch_in2, duty);
    } else {
        ledcWrite(ch_in1, 0);
        ledcWrite(ch_in2, 0);
    }
}

void MotorController::emergencyStop()
{
    for (int i = 0; i < 4; i++) {
        setMotor(i, 0.0f);
    }
    Serial.println("[Motor] Vészleállás!");
}

void MotorController::setMecanum(float linear, float angular, float lateral)
{
    // Mecanum kerék sebességszámítás
    float fl = linear + lateral + angular;
    float fr = linear - lateral - angular;
    float rl = linear - lateral + angular;
    float rr = linear + lateral - angular;

    // Normalizálás: max(|fl|,|fr|,|rl|,|rr|,1.0) osztó
    float mx = 1.0f;
    if (fabsf(fl) > mx) mx = fabsf(fl);
    if (fabsf(fr) > mx) mx = fabsf(fr);
    if (fabsf(rl) > mx) mx = fabsf(rl);
    if (fabsf(rr) > mx) mx = fabsf(rr);

    setMotor(0, fl / mx);
    setMotor(1, fr / mx);
    setMotor(2, rl / mx);
    setMotor(3, rr / mx);
}

void MotorController::processCommand(const uint8_t *json, size_t len)
{
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, json, len);
    if (err) {
        Serial.printf("[Motor] JSON hiba: %s\n", err.c_str());
        return;
    }

    _lastCmdMs = millis();

    const char *cmd = doc["cmd"] | "";

    if (strcmp(cmd, "move") == 0) {
        float linear  = doc["linear"]  | 0.0f;
        float angular = doc["angular"] | 0.0f;
        float lateral = doc["lateral"] | 0.0f;
        float left_y  = doc["left_y"]  | 0.0f;

        // Bal stick Y negatív = előre, kombinálás
        float combined_linear = linear - left_y;
        setMecanum(combined_linear, angular, lateral);

    } else if (strcmp(cmd, "stop") == 0) {
        emergencyStop();

    } else if (strcmp(cmd, "jump") == 0) {
        const char *direction = doc["direction"] | "forward";
        float duration        = doc["duration"]  | 1.0f;
        uint32_t dur_ms       = (uint32_t)(duration * 1000.0f);
        if (dur_ms > 3000) dur_ms = 3000;  // biztonsági korlát

        // Teljes gáz az adott irányba
        if (strcmp(direction, "forward") == 0) {
            setMecanum(1.0f, 0.0f, 0.0f);
        } else if (strcmp(direction, "backward") == 0) {
            setMecanum(-1.0f, 0.0f, 0.0f);
        } else if (strcmp(direction, "left") == 0) {
            setMecanum(0.0f, 0.0f, -1.0f);
        } else if (strcmp(direction, "right") == 0) {
            setMecanum(0.0f, 0.0f, 1.0f);
        }

        delay(dur_ms);
        emergencyStop();

    } else if (strcmp(cmd, "motor") == 0) {
        int   id    = doc["id"]    | -1;
        float speed = doc["speed"] | 0.0f;
        setMotor(id, speed);

    } else {
        Serial.printf("[Motor] Ismeretlen parancs: %s\n", cmd);
    }
}

void MotorController::checkWatchdog()
{
    if ((millis() - _lastCmdMs) > MOTOR_TIMEOUT_MS) {
        emergencyStop();
        _lastCmdMs = millis();  // ne spammelj
    }
}
