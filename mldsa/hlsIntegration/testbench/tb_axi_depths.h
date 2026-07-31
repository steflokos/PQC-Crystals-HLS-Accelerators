// Must match every "#pragma HLS INTERFACE m_axi port=... depth=..." on
// mldsa_accelerator (k_dsa.cpp). Units are elements of the port's own pointer
// type (bytes for uint8_t*, ints for int*), NOT bytes uniformly.
//
// cosim's C-TB post-check reads up to `depth` elements from whatever pointer is
// passed for that port, for every call, regardless of which kem_cfg branch
// actually used it and regardless of the design's own runtime-supplied length
// (mlen_in/ctxlen_in) - it's a static, compile-time assumption. Every buffer
// passed to mldsa_accelerator (including "unused for this branch" dummies, and
// scalar outputs like ver_out) must be allocated to at least its port's depth,
// or cosim reads past the end -> SIGSEGV during "C post checking". Confirmed
// empirically: mu_orig_in depth=8300 vs. a 4741-byte real message array, and a
// scalar `int ver_out` vs. ver_out's depth=64 (i.e. 64 ints = 256 bytes).
#ifndef TB_AXI_DEPTHS_H
#define TB_AXI_DEPTHS_H

#define AXI_DEPTH_RET_OUT   64    // uint8_t* ret_out
#define AXI_DEPTH_SIGN      2620  // uint8_t* sign_out, sign_in
// mu_orig_in (verify) and sign_m_in (sign) both carry a raw message and share this
// same production bound (see README.md "Known finding") - k_sign derives tr/M'/mu
// on-chip now, same as k_verify, so both ports are sized identically.
#define AXI_DEPTH_MU_ORIG   1024  // uint8_t* mu_orig_in
#define AXI_DEPTH_SIGN_M    1024  // uint8_t* sign_m_in
#define AXI_DEPTH_SK        2628  // uint8_t* sk_in
#define AXI_DEPTH_PK        2600  // uint8_t* pk_in
#define AXI_DEPTH_VER_OUT   64    // int*     ver_out (64 ints, not 64 bytes)
#define AXI_DEPTH_RND       32    // uint8_t* rnd_in
#define AXI_DEPTH_CTX       255   // uint8_t* ctx_in

#endif // TB_AXI_DEPTHS_H
