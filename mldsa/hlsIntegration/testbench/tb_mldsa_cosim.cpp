// HLS C/RTL co-simulation testbench for the FIPS 204 compliance changes (ctx in
// k_verify, real rnd wiring in k_sign/dataflow). Reduced vector set (one case per
// structurally distinct code path) - full 45-vector algorithmic coverage already
// exists via tb_mldsa.cpp/csim; this validates the HLS-scheduled RTL against the
// same C model instead, which is a per-code-path, not per-vector, concern.
// See gen_vectors.py --reduced for case selection rationale.

#include <cstdio>
#include <cstring>
#include "../kernel.hpp"
#include "tb_axi_depths.h"
#include "tb_vectors_cosim.h"

static int run_verify_cases()
{
    int fails = 0;
    for (unsigned i = 0; i < VER_CASES_COUNT; i++) {
        const VerCase &tc = VER_CASES[i];

        uint8_t dummy_ret[AXI_DEPTH_RET_OUT] = {0};
        uint8_t dummy_sign_out[AXI_DEPTH_SIGN] = {0};
        uint8_t dummy_sign_m[AXI_DEPTH_SIGN_M] = {0};
        uint8_t dummy_sk[AXI_DEPTH_SK] = {0};
        uint8_t dummy_rnd[AXI_DEPTH_RND] = {0};

        int ver_out_buf[AXI_DEPTH_VER_OUT] = {0};
        ver_out_buf[0] = -99;
        int &ver_out = ver_out_buf[0];

        mldsa_accelerator(
            /*kem_cfg=*/1,
            dummy_ret,
            dummy_sign_out,
            /*sign_in=*/const_cast<uint8_t *>(tc.sig),
            dummy_sign_m,
            /*mu_orig_in=*/const_cast<uint8_t *>(tc.msg),
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

        uint8_t ret_out[AXI_DEPTH_RET_OUT] = {0};
        uint8_t sign_out[AXI_DEPTH_SIGN] = {0};
        uint8_t dummy_sign_in[AXI_DEPTH_SIGN] = {0};
        uint8_t dummy_mu_orig[AXI_DEPTH_MU_ORIG] = {0};
        uint8_t dummy_pk[AXI_DEPTH_PK] = {0};
        int dummy_ver_buf[AXI_DEPTH_VER_OUT] = {0};

        mldsa_accelerator(
            /*kem_cfg=*/0,
            ret_out,
            sign_out,
            dummy_sign_in,
            /*sign_m_in=*/const_cast<uint8_t *>(tc.msg),
            dummy_mu_orig,
            /*sk_in=*/const_cast<uint8_t *>(tc.sk),
            dummy_pk,
            dummy_ver_buf,
            /*mlen_in=*/tc.mlen,
            /*rnd_in=*/const_cast<uint8_t *>(tc.rnd),
            /*ctx_in=*/const_cast<uint8_t *>(tc.ctx),
            /*ctxlen_in=*/(uint8_t)tc.ctxlen);

        bool ok = (memcmp(sign_out, tc.expected_sig, CRYPTO_BYTES) == 0);
        printf("[SIGN]   %-28s ret=%u -> %s\n", tc.label, ret_out[0], ok ? "OK" : "MISMATCH");
        if (!ok)
            fails++;
    }
    return fails;
}

int main()
{
    printf("=== ML-DSA-44 FIPS204-compliance COSIM testbench (reduced NIST ACVP vectors) ===\n");
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
