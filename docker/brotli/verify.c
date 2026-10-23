#include <brotli/decode.h>
#include <brotli/encode.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* Dynamic calls verify the installed libraries, not just headers or labels. */
int main(int argc, char **argv) {
    unsigned major, minor, patch;
    const uint8_t input[] = "TGI Brotli runtime roundtrip";
    uint8_t compressed[256], output[256];
    size_t compressed_size = sizeof(compressed), output_size = sizeof(output);
    if (argc != 2 || sscanf(argv[1], "%u.%u.%u", &major, &minor, &patch) != 3) return 1;
    uint32_t expected = (major << 24) | (minor << 12) | patch;
    if (BrotliDecoderVersion() != expected || BrotliEncoderVersion() != expected) return 2;
    if (!BrotliEncoderCompress(5, BROTLI_DEFAULT_WINDOW, BROTLI_MODE_GENERIC,
            sizeof(input), input, &compressed_size, compressed)) return 3;
    if (BrotliDecoderDecompress(compressed_size, compressed, &output_size, output)
            != BROTLI_DECODER_RESULT_SUCCESS) return 4;
    if (output_size != sizeof(input) || memcmp(input, output, sizeof(input))) return 5;
    printf("Brotli %s dynamic decoder/encoder roundtrip passed\n", argv[1]);
    return 0;
}
