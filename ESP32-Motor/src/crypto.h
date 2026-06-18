#pragma once
#include <stdint.h>
#include <stddef.h>

// Titkosítás: out max mérete: 4+8+pt_len+32; visszaad total méretet, 0 hiba
size_t lora_encrypt(const uint8_t *pt, size_t pt_len, uint8_t *out, size_t out_max);

// Visszafejt: visszaad plaintext méretét, 0 hiba esetén
size_t lora_decrypt(const uint8_t *data, size_t data_len, uint8_t *out, size_t out_max);

// Handshake ellenőrzés: challenge[32] vs response[32]
bool verify_hmac_response(const uint8_t *challenge, const uint8_t *response);
