#pragma once
#include <Arduino.h>
#include <stdint.h>
#include <stddef.h>

class MotorController {
public:
    void init();
    void processCommand(const uint8_t *json, size_t len);  // ArduinoJson parse + execute
    void checkWatchdog();    // emergency_stop if timeout
    void emergencyStop();
    void setMotor(int id, float speed);   // -1.0..1.0
    void setMecanum(float linear, float angular, float lateral);
private:
    uint32_t _lastCmdMs;
    float    _speeds[4];
};
