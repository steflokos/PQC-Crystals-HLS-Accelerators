// HLS C-simulation testbench for the FIPS 204 compliance changes (ctx in k_verify,
// real rnd wiring in k_sign/dataflow). Validated against official NIST ACVP-Server
// ML-DSA-44 KAT vectors (see gen_vectors.py for provenance).
//
// Runs entirely as plain C++ - no board, no Vivado, no Vitis SW workspace.

#include <cstdio>
#include <cstring>
#include "../kernel.hpp"
#include "tb_vectors.h"

static int run_verify_cases()
{
    int fails = 0;
    for (unsigned i = 0; i < VER_CASES_COUNT; i++) {
        const VerCase &tc = VER_CASES[i];

        uint8_t dummy_ret[64] = {0};
        uint8_t dummy_sign_out[CRYPTO_BYTES] = {0};
        uint8_t dummy_mu_processed[CRHBYTES] = {0};
        uint8_t dummy_mu2_processed[CRHBYTES] = {0};
        uint8_t dummy_sk[CRYPTO_SECRETKEYBYTES] = {0};
        uint8_t dummy_rnd[RNDBYTES] = {0};

        int ver_out = -99;

        mldsa_accelerator(
            /*kem_cfg=*/1,
            dummy_ret,
            dummy_sign_out,
            /*sign_in=*/const_cast<uint8_t *>(tc.sig),
            dummy_mu_processed,
            /*mu_orig_in=*/const_cast<uint8_t *>(tc.msg),
            dummy_mu2_processed,
            dummy_sk,
            /*pk_in=*/const_cast<uint8_t *>(tc.pk),
            &ver_out,
            /*mlen_in=*/tc.mlen,
            dummy_rnd,
            /*ctx_in=*/const_cast<uint8_t *>(tc.ctx),
            /*ctxlen_in=*/(uint8_t)tc.ctxlen);

        bool passed = (ver_out == 0);
        bool ok = (passed == tc.expected);
        printf("[VERIFY] %-28s expected=%s got=%s (ver_out=%d) -> %s\n",
               tc.label, tc.expected ? "PASS" : "FAIL", passed ? "PASS" : "FAIL",
               ver_out, ok ? "OK" : "MISMATCH");
        if (!ok)
            fails++;
    }
    return fails;
}

static int run_sign_cases()
{
    int fails = 0;
    for (unsigned i = 0; i < SIGN_CASES_COUNT; i++) {
        const SignCase &tc = SIGN_CASES[i];

        uint8_t ret_out[64] = {0};
        uint8_t sign_out[CRYPTO_BYTES] = {0};
        uint8_t dummy_sign_in[CRYPTO_BYTES] = {0};
        uint8_t dummy_mu_orig[1] = {0};
        uint8_t dummy_pk[CRYPTO_PUBLICKEYBYTES] = {0};
        int dummy_ver = 0;
        uint8_t dummy_ctx[1] = {0};

        mldsa_accelerator(
            /*kem_cfg=*/0,
            ret_out,
            sign_out,
            dummy_sign_in,
            /*mu_processed_in=*/const_cast<uint8_t *>(tc.mu),
            dummy_mu_orig,
            /*mu2_processed_in=*/const_cast<uint8_t *>(tc.mu),
            /*sk_in=*/const_cast<uint8_t *>(tc.sk),
            dummy_pk,
            &dummy_ver,
            /*mlen_in=*/0,
            /*rnd_in=*/const_cast<uint8_t *>(tc.rnd),
            dummy_ctx,
            /*ctxlen_in=*/0);

        bool ok = (memcmp(sign_out, tc.expected_sig, CRYPTO_BYTES) == 0);
        printf("[SIGN]   %-28s ret=%u -> %s\n", tc.label, ret_out[0], ok ? "OK" : "MISMATCH");
        if (!ok)
            fails++;
    }
    return fails;
}

int main()
{
    printf("=== ML-DSA-44 FIPS204-compliance testbench (NIST ACVP KAT vectors) ===\n");
    printf("-- Verify (ctx domain separation), %u cases --\n", (unsigned)VER_CASES_COUNT);
    int ver_fails = run_verify_cases();

    printf("-- Sign (rnd wiring: deterministic + hedged), %u cases --\n", (unsigned)SIGN_CASES_COUNT);
    int sign_fails = run_sign_cases();

    int total_fails = ver_fails + sign_fails;
    printf("=== Result: %u/%u verify cases OK, %u/%u sign cases OK ===\n",
           (unsigned)VER_CASES_COUNT - ver_fails, (unsigned)VER_CASES_COUNT,
           (unsigned)SIGN_CASES_COUNT - sign_fails, (unsigned)SIGN_CASES_COUNT);

    return total_fails ? 1 : 0;
}
