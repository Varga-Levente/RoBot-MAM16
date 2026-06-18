#pragma once
#include <Arduino.h>
#include <stdint.h>
#include <stddef.h>

class LoRaComm {
public:
    void init();
    bool doHandshake(uint32_t timeout_ms = 10000);  // false = timeout, retry needed
    // Receives a complete frame, returns decrypted JSON; 0 = no data / error
    size_t receiveCommand(uint8_t *out, size_t out_max, uint32_t timeout_ms = 50);
private:
    void sendFrame(const uint8_t *data, size_t len);
    bool recvFrame(uint8_t *out, size_t out_max, size_t *out_len, uint32_t timeout_ms);
};
