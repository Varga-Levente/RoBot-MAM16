#include <Arduino.h>
#include "settings.h"
#include "motor_controller.h"
#include "lora_comm.h"

MotorController motors;
LoRaComm        lora;

void setup()
{
    Serial.begin(DEBUG_BAUD);
    delay(500);
    Serial.println("[Main] RoBot ESP32-Motor indítás...");

    motors.init();
    lora.init();

    Serial.println("[Main] Handshake várakozás...");
    while (!lora.doHandshake(10000)) {
        Serial.println("[Main] Handshake timeout, újra 5s múlva...");
        delay(5000);
    }
    Serial.println("[Main] Kapcsolat felépítve, parancsok fogadása.");
}

void loop()
{
    uint8_t cmd_buf[256];
    size_t  cmd_len = lora.receiveCommand(cmd_buf, sizeof(cmd_buf), 50);

    if (cmd_len > 0) {
        motors.processCommand(cmd_buf, cmd_len);
    }

    motors.checkWatchdog();
}
