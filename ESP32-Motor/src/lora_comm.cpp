#include "lora_comm.h"
#include "crypto.h"
#include "settings.h"
#include <Arduino.h>
#include <string.h>
#include <esp_random.h>

// Keret formátum: [0xAA][0x55][0x5A][0xA5][len_hi][len_lo][payload]
static const uint8_t FRAME_MAGIC[4] = {0xAA, 0x55, 0x5A, 0xA5};

static HardwareSerial LoraSerial(LORA_UART_PORT);

void LoRaComm::init()
{
    LoraSerial.begin(LORA_UART_BAUD, SERIAL_8N1, LORA_UART_RX, LORA_UART_TX);
}

void LoRaComm::sendFrame(const uint8_t *data, size_t len)
{
    uint8_t header[6];
    memcpy(header, FRAME_MAGIC, 4);
    header[4] = (len >> 8) & 0xFF;
    header[5] = len & 0xFF;
    LoraSerial.write(header, 6);
    LoraSerial.write(data, len);
    LoraSerial.flush();
}

bool LoRaComm::recvFrame(uint8_t *out, size_t out_max, size_t *out_len, uint32_t timeout_ms)
{
    uint32_t deadline = millis() + timeout_ms;
    uint8_t  magic_buf[4] = {0};
    int      magic_pos = 0;

    // Keret mágikus fejléc keresése
    while (millis() < deadline) {
        if (!LoraSerial.available()) {
            delay(1);
            continue;
        }
        uint8_t b = (uint8_t)LoraSerial.read();
        if (b == FRAME_MAGIC[magic_pos]) {
            magic_pos++;
            if (magic_pos == 4) break;  // magic megtalálva
        } else {
            magic_pos = (b == FRAME_MAGIC[0]) ? 1 : 0;
        }
    }
    if (magic_pos < 4) return false;  // timeout

    // Hossz olvasása (2 byte)
    uint8_t len_buf[2];
    for (int i = 0; i < 2; i++) {
        uint32_t t = millis() + 500;
        while (!LoraSerial.available() && millis() < t) delay(1);
        if (!LoraSerial.available()) return false;
        len_buf[i] = (uint8_t)LoraSerial.read();
    }
    size_t payload_len = ((size_t)len_buf[0] << 8) | len_buf[1];
    if (payload_len == 0 || payload_len > out_max) return false;

    // Payload olvasása
    size_t received = 0;
    uint32_t t = millis() + 2000;
    while (received < payload_len && millis() < t) {
        if (LoraSerial.available()) {
            out[received++] = (uint8_t)LoraSerial.read();
        } else {
            delay(1);
        }
    }
    if (received < payload_len) return false;

    *out_len = payload_len;
    return true;
}

bool LoRaComm::doHandshake(uint32_t timeout_ms)
{
    uint32_t deadline = millis() + timeout_ms;

    while (millis() < deadline) {
        // 1. Robot küld: frame(challenge[32]) — 32 véletlen byte
        uint8_t challenge[32];
        esp_fill_random(challenge, sizeof(challenge));
        sendFrame(challenge, sizeof(challenge));

        // 2. Kontroller válasza: frame(HMAC-SHA256(challenge, hmac_key)[32])
        uint8_t response[64];
        size_t  resp_len = 0;
        uint32_t resp_deadline = millis() + 5000;
        bool got_response = false;

        while (millis() < resp_deadline) {
            if (recvFrame(response, sizeof(response), &resp_len, 1000)) {
                got_response = true;
                break;
            }
        }

        if (!got_response || resp_len != 32) {
            delay(5000);
            continue;
        }

        // 3. Robot ellenőrzi, majd küld: frame(encrypt({"status":"ok"}))
        if (!verify_hmac_response(challenge, response)) {
            Serial.println("[LoRa] Handshake HMAC ellenőrzés sikertelen, újra...");
            delay(5000);
            continue;
        }

        // Sikeres handshake — titkosított visszaigazolás küldése
        const char ok_msg[] = "{\"status\":\"ok\"}";
        uint8_t enc_buf[128];
        size_t enc_len = lora_encrypt((const uint8_t *)ok_msg, strlen(ok_msg),
                                       enc_buf, sizeof(enc_buf));
        if (enc_len > 0) {
            sendFrame(enc_buf, enc_len);
        }

        Serial.println("[LoRa] Handshake sikeres.");
        return true;
    }

    return false;  // timeout
}

size_t LoRaComm::receiveCommand(uint8_t *out, size_t out_max, uint32_t timeout_ms)
{
    uint8_t frame_buf[512];
    size_t  frame_len = 0;

    if (!recvFrame(frame_buf, sizeof(frame_buf), &frame_len, timeout_ms)) {
        return 0;
    }

    // Visszafejtés
    size_t plain_len = lora_decrypt(frame_buf, frame_len, out, out_max);
    return plain_len;
}
