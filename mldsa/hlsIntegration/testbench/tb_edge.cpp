// Edge-case testbench for mldsa_accelerator (C simulation, and RTL co-simulation with -DEDGE_COSIM).
// Same call shape as hlsIntegration/testbench/tb_mldsa.cpp; vectors from gen_edge.py (dilithium-py reference).
// Every buffer is allocated at its port depth (see tb_axi_depths.h): cosim's C post-check reads that many elements.
#include <cstdio>
#include <cstring>
#include "../kernel.hpp"
#include "tb_axi_depths.h"
#ifdef EDGE_COSIM
#include "tb_vectors_edge_cosim.h"
#else
#include "tb_vectors_edge.h"
#endif

static int run_sign()
{
    int fails = 0;
    for (unsigned i = 0; i < EDGE_SIGN_COUNT; i++) {
        const EdgeSign &tc = EDGE_SIGN[i];
        static uint8_t msg[AXI_DEPTH_SIGN_M], ctx[AXI_DEPTH_CTX], rnd[AXI_DEPTH_RND];
        static uint8_t ret_out[AXI_DEPTH_RET_OUT], sign_out[AXI_DEPTH_SIGN], sign_in[AXI_DEPTH_SIGN];
        static uint8_t mu_orig[AXI_DEPTH_MU_ORIG], sk[AXI_DEPTH_SK], pk[AXI_DEPTH_PK];
        static int ver_buf[AXI_DEPTH_VER_OUT];
        memset(msg, 0, sizeof msg); memset(ctx, 0, sizeof ctx); memset(sign_out, 0, sizeof sign_out);
        memcpy(msg, tc.msg, tc.mlen); memcpy(ctx, tc.ctx, tc.ctxlen); memcpy(rnd, tc.rnd, 32);
        memcpy(sk, EDGE_SK, 2560);

        mldsa_accelerator(0, ret_out, sign_out, sign_in, msg, mu_orig, sk, pk, ver_buf,
                          tc.mlen, rnd, ctx, (uint8_t)tc.ctxlen);

        bool ok = memcmp(sign_out, tc.expected_sig, CRYPTO_BYTES) == 0;
        printf("[SIGN] %-40s L=%4u L%%136=%3u ret=%u -> %s\n", tc.label, tc.Lhash, tc.Lhash % 136, ret_out[0], ok ? "OK" : "MISMATCH");
        fails += !ok;
    }
    return fails;
}

static int run_verify()
{
    int fails = 0;
    for (unsigned i = 0; i < EDGE_VER_COUNT; i++) {
        const EdgeVer &tc = EDGE_VER[i];
        static uint8_t msg[AXI_DEPTH_MU_ORIG], ctx[AXI_DEPTH_CTX], sig[AXI_DEPTH_SIGN], pk[AXI_DEPTH_PK];
        static uint8_t ret_out[AXI_DEPTH_RET_OUT], sign_out[AXI_DEPTH_SIGN], sign_m[AXI_DEPTH_SIGN_M];
        static uint8_t sk[AXI_DEPTH_SK], rnd[AXI_DEPTH_RND];
        static int ver_buf[AXI_DEPTH_VER_OUT];
        memset(msg, 0, sizeof msg); memset(ctx, 0, sizeof ctx);
        memcpy(msg, tc.msg, tc.mlen); memcpy(ctx, tc.ctx, tc.ctxlen); memcpy(sig, tc.sig, CRYPTO_BYTES);
        memcpy(pk, EDGE_PK, CRYPTO_PUBLICKEYBYTES);
        ver_buf[0] = -99;

        mldsa_accelerator(1, ret_out, sign_out, sig, sign_m, msg, sk, pk, ver_buf,
                          tc.mlen, rnd, ctx, (uint8_t)tc.ctxlen);

        bool accepted = (ver_buf[0] == 0);
        bool ok = (accepted == tc.expected_accept);
        printf("[VERIFY] %-46s expect=%s got=%s (ver_out=%d) -> %s\n", tc.label,
               tc.expected_accept ? "ACCEPT" : "REJECT", accepted ? "ACCEPT" : "REJECT", ver_buf[0], ok ? "OK" : "MISMATCH");
        fails += !ok;
    }
    return fails;
}

int main()
{
    printf("=== ML-DSA-44 accelerator edge-case test (reference: dilithium-py) ===\n");
    int sf = run_sign();
    int vf = run_verify();
    printf("=== Edge result: %u/%u sign OK, %u/%u verify OK ===\n",
           EDGE_SIGN_COUNT - sf, EDGE_SIGN_COUNT, EDGE_VER_COUNT - vf, EDGE_VER_COUNT);
    return (sf + vf) ? 1 : 0;
}
