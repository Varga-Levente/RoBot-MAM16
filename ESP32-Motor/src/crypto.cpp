#include "crypto.h"
#include "settings.h"
#include <string.h>
#include <mbedtls/aes.h>
#include <mbedtls/md.h>
#include <esp_random.h>

// Csomag formátum: [device_id:4B][nonce:8B][ciphertext:N][HMAC-SHA256:32B]
// AES-128 CTR mód: nonce_counter = nonce[8] || zeros[8]

static const uint8_t s_device_id[4] = LORA_DEVICE_ID;
static const char    s_aes_key[]    = LORA_AES_KEY;
static const char    s_hmac_key[]   = LORA_HMAC_KEY;

// Segédfüggvény: HMAC-SHA256 számítás
static bool _hmac_sha256(const uint8_t *key, size_t key_len,
                          const uint8_t *data, size_t data_len,
                          uint8_t *out32)
{
    mbedtls_md_context_t ctx;
    mbedtls_md_init(&ctx);
    const mbedtls_md_info_t *info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (!info) return false;
    if (mbedtls_md_setup(&ctx, info, 1) != 0) { mbedtls_md_free(&ctx); return false; }
    if (mbedtls_md_hmac_starts(&ctx, key, key_len) != 0) { mbedtls_md_free(&ctx); return false; }
    if (mbedtls_md_hmac_update(&ctx, data, data_len) != 0) { mbedtls_md_free(&ctx); return false; }
    if (mbedtls_md_hmac_finish(&ctx, out32) != 0) { mbedtls_md_free(&ctx); return false; }
    mbedtls_md_free(&ctx);
    return true;
}

size_t lora_encrypt(const uint8_t *pt, size_t pt_len, uint8_t *out, size_t out_max)
{
    // Szükséges méret: 4 (device_id) + 8 (nonce) + pt_len + 32 (HMAC)
    size_t total = 4 + 8 + pt_len + 32;
    if (out_max < total) return 0;

    // device_id
    memcpy(out, s_device_id, 4);

    // véletlen nonce (8 byte)
    uint8_t nonce[8];
    esp_fill_random(nonce, sizeof(nonce));
    memcpy(out + 4, nonce, 8);

    // AES-128 CTR titkosítás
    // nonce_counter = nonce[8] || zeros[8]
    uint8_t nonce_counter[16] = {0};
    memcpy(nonce_counter, nonce, 8);
    uint8_t stream_block[16] = {0};
    size_t nc_off = 0;

    mbedtls_aes_context aes;
    mbedtls_aes_init(&aes);
    if (mbedtls_aes_setkey_enc(&aes, (const uint8_t *)s_aes_key, 128) != 0) {
        mbedtls_aes_free(&aes);
        return 0;
    }
    if (mbedtls_aes_crypt_ctr(&aes, pt_len, &nc_off, nonce_counter, stream_block,
                               pt, out + 12) != 0) {
        mbedtls_aes_free(&aes);
        return 0;
    }
    mbedtls_aes_free(&aes);

    // HMAC-SHA256 a device_id + nonce + ciphertext felett
    uint8_t hmac[32];
    if (!_hmac_sha256((const uint8_t *)s_hmac_key, sizeof(s_hmac_key) - 1,
                      out, 4 + 8 + pt_len, hmac)) {
        return 0;
    }
    memcpy(out + 4 + 8 + pt_len, hmac, 32);

    return total;
}

size_t lora_decrypt(const uint8_t *data, size_t data_len, uint8_t *out, size_t out_max)
{
    // Minimum méret: 4 + 8 + 32 = 44 byte
    if (data_len < 44) return 0;

    size_t ct_len = data_len - 44;
    if (out_max < ct_len) return 0;

    // device_id ellenőrzés
    if (memcmp(data, s_device_id, 4) != 0) return 0;

    // HMAC ellenőrzés
    uint8_t expected_hmac[32];
    if (!_hmac_sha256((const uint8_t *)s_hmac_key, sizeof(s_hmac_key) - 1,
                      data, 4 + 8 + ct_len, expected_hmac)) {
        return 0;
    }
    // Konstans idejű összehasonlítás
    uint8_t diff = 0;
    for (int i = 0; i < 32; i++) {
        diff |= expected_hmac[i] ^ data[4 + 8 + ct_len + i];
    }
    if (diff != 0) return 0;

    // AES-128 CTR visszafejtés
    uint8_t nonce_counter[16] = {0};
    memcpy(nonce_counter, data + 4, 8);  // nonce az adatból
    uint8_t stream_block[16] = {0};
    size_t nc_off = 0;

    mbedtls_aes_context aes;
    mbedtls_aes_init(&aes);
    if (mbedtls_aes_setkey_enc(&aes, (const uint8_t *)s_aes_key, 128) != 0) {
        mbedtls_aes_free(&aes);
        return 0;
    }
    if (mbedtls_aes_crypt_ctr(&aes, ct_len, &nc_off, nonce_counter, stream_block,
                               data + 12, out) != 0) {
        mbedtls_aes_free(&aes);
        return 0;
    }
    mbedtls_aes_free(&aes);

    return ct_len;
}

bool verify_hmac_response(const uint8_t *challenge, const uint8_t *response)
{
    uint8_t expected[32];
    if (!_hmac_sha256((const uint8_t *)s_hmac_key, sizeof(s_hmac_key) - 1,
                      challenge, 32, expected)) {
        return false;
    }
    uint8_t diff = 0;
    for (int i = 0; i < 32; i++) {
        diff |= expected[i] ^ response[i];
    }
    return diff == 0;
}
