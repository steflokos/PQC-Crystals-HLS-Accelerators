"""Edge-case vectors for the ML-DSA-44 accelerator, from the dilithium-py reference.

    python3 gen_edge.py        # needs: pip install dilithium-py; writes tb_vectors_edge.h and tb_vectors_edge_cosim.h next to this file

Expected values come from the reference (_sign_internal / _verify_internal on M' = 0x00 || len(ctx) || ctx || M),
never from the accelerator. The script asserts that the reference accepts every valid signature and rejects every
tampered one, so an expectation can only be wrong if the reference is.

L = 64 + 2 + ctxlen + mlen is the number of bytes the accelerator feeds to SHAKE256 for mu (tr || M').
SHAKE256 rate = 136: L % 136 == 135 puts both pad bytes (0x1F and 0x80) in one byte (0x9F); L % 136 == 0 needs an
extra block; L < 136 is a single partial block. The 16 sign cases cover ctxlen {0, 1, 16, 133, 255} and mlen
{0, 1, 68..71, 86, 100, 206, 1024}. The reduced set (--out-cosim) keeps 4 sign and 6 verify cases for RTL cosim.
"""
import argparse
import os
import random

from dilithium_py.ml_dsa import ML_DSA_44 as M

RATE = 136
HERE = os.path.dirname(os.path.abspath(__file__))

# (label, ctxlen, mlen, rnd is all-zero)
SIGN = [
    ("ctx0_m0_L66_single_partial_block",      0,    0, True),
    ("ctx0_m1_L67",                            0,    1, False),
    ("ctx0_m68_L134",                          0,   68, False),
    ("ctx0_m69_L135_pad_collision_rnd0",       0,   69, True),
    ("ctx0_m69_L135_pad_collision_hedged",     0,   69, False),
    ("ctx0_m70_L136_exact_block",              0,   70, True),
    ("ctx0_m71_L137",                          0,   71, False),
    ("ctx0_m206_L272_exact_two_blocks",        0,  206, False),
    ("ctx255_m0_L321",                       255,    0, False),
    ("ctx255_m1_L322_rnd0",                  255,    1, True),
    ("ctx255_m86_L407_pad_collision",        255,   86, False),
    ("ctx0_m1024_L1090_max_msg",               0, 1024, False),
    ("ctx133_m1024_L1223_pad_collision",     133, 1024, False),
    ("ctx255_m1024_L1345_max_all",           255, 1024, False),
    ("ctx1_m1024_L1091_rnd0",                  1, 1024, True),
    ("ctx16_m100_L182_typical",               16,  100, False),
]
COSIM_SIGN = {"ctx0_m0_L66_single_partial_block", "ctx0_m69_L135_pad_collision_hedged",
              "ctx0_m70_L136_exact_block", "ctx255_m1024_L1345_max_all"}
COSIM_VER = {"accept_ctx0_m0_L66_single_partial_block", "accept_ctx0_m69_L135_pad_collision_hedged",
             "accept_ctx0_m70_L136_exact_block", "accept_ctx255_m1024_L1345_max_all",
             "rej_ctilde_ctx0_m0_L66_single_partial_block", "rej_ctx_length_ctx255_m86_L407_pad_collision"}


def mprime(ctx: bytes, msg: bytes) -> bytes:
    return bytes([0x00, len(ctx)]) + ctx + msg


def arr(name: str, data: bytes) -> str:
    body = ",".join(f"0x{b:02x}" for b in data) if data else "0x00"      # never a zero-length C array
    return f"static const uint8_t {name}[{max(len(data), 1)}] = {{{body}}};\n"


def flip(b: bytes, off: int, bit: int = 0) -> bytes:
    x = bytearray(b)
    x[off] ^= 1 << bit
    return bytes(x)


def build():
    rng = random.Random(0x204)
    pk, sk = M.key_derive(bytes(range(32)))
    assert M.pk_from_sk(sk) == pk
    signs, cases = [], []
    for label, ctxlen, mlen, rnd0 in SIGN:
        ctx, msg = rng.randbytes(ctxlen), rng.randbytes(mlen)
        rnd = bytes(32) if rnd0 else rng.randbytes(32)
        sig = M._sign_internal(sk, mprime(ctx, msg), rnd)
        assert M._verify_internal(pk, mprime(ctx, msg), sig), label
        assert len(sig) == 2420
        signs.append(dict(label=label, ctx=ctx, msg=msg, rnd=rnd, sig=sig, L=64 + 2 + ctxlen + mlen))
        cases.append((label, ctx, msg, sig))

    vers = []

    def add_ver(label, sig, msg, ctx, accept_expected):
        ref = M._verify_internal(pk, mprime(ctx, msg), sig)
        assert ref == accept_expected, f"reference disagrees with intent for {label}"
        vers.append(dict(label=label, sig=sig, msg=msg, ctx=ctx, accept=ref))

    for label, ctx, msg, sig in cases:
        add_ver(f"accept_{label}", sig, msg, ctx, True)
    for label, ctx, msg, sig in [cases[0], cases[3], cases[5], cases[10], cases[13], cases[15]]:
        add_ver(f"rej_ctilde_{label}", flip(sig, 3), msg, ctx, False)                  # commitment hash
        add_ver(f"rej_z_{label}", flip(sig, 32 + 200, 2), msg, ctx, False)              # response z
        add_ver(f"rej_hint_{label}", flip(sig, len(sig) - 5), msg, ctx, False)           # hint area
        if ctx:
            add_ver(f"rej_ctx_bit_{label}", sig, msg, flip(ctx, len(ctx) - 1), False)    # same length, other ctx
        other = ctx[:-1] if len(ctx) == 255 else ctx + b"\x00"                          # |ctx| differs, <= 255
        add_ver(f"rej_ctx_length_{label}", sig, msg, other, False)
        if msg:
            add_ver(f"rej_msg_bit_{label}", sig, flip(msg, 0), ctx, False)
        else:
            add_ver(f"rej_msg_longer_{label}", sig, b"\x00", ctx, False)
    return pk, sk, signs, vers


def emit(path, pk, sk, signs, vers):
    out = ["// GENERATED by gen_edge.py from dilithium-py; do not edit.\n#include <stdint.h>\n",
           "struct EdgeSign { const char *label; const uint8_t *msg; unsigned mlen; const uint8_t *ctx; unsigned ctxlen;"
           " const uint8_t *rnd; const uint8_t *expected_sig; unsigned Lhash; };\n",
           "struct EdgeVer  { const char *label; const uint8_t *sig; const uint8_t *msg; unsigned mlen; const uint8_t *ctx;"
           " unsigned ctxlen; bool expected_accept; };\n",
           arr("EDGE_SK", sk), arr("EDGE_PK", pk)]
    srows, vrows = [], []
    for i, s in enumerate(signs):
        out += [arr(f"s{i}_msg", s["msg"]), arr(f"s{i}_ctx", s["ctx"]), arr(f"s{i}_rnd", s["rnd"]), arr(f"s{i}_sig", s["sig"])]
        srows.append(f'  {{"{s["label"]}", s{i}_msg, {len(s["msg"])}, s{i}_ctx, {len(s["ctx"])}, s{i}_rnd, s{i}_sig, {s["L"]}}},')
    for j, v in enumerate(vers):
        out += [arr(f"v{j}_sig", v["sig"]), arr(f"v{j}_msg", v["msg"]), arr(f"v{j}_ctx", v["ctx"])]
        vrows.append(f'  {{"{v["label"]}", v{j}_sig, v{j}_msg, {len(v["msg"])}, v{j}_ctx, {len(v["ctx"])}, {"true" if v["accept"] else "false"}}},')
    out.append("static const EdgeSign EDGE_SIGN[] = {\n" + "\n".join(srows) + "\n};\n")
    out.append(f"static const unsigned EDGE_SIGN_COUNT = {len(srows)};\n")
    out.append("static const EdgeVer EDGE_VER[] = {\n" + "\n".join(vrows) + "\n};\n")
    out.append(f"static const unsigned EDGE_VER_COUNT = {len(vrows)};\n")
    with open(path, "w") as f:
        f.write("".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-full", default=os.path.join(HERE, "tb_vectors_edge.h"))
    ap.add_argument("--out-cosim", default=os.path.join(HERE, "tb_vectors_edge_cosim.h"))
    a = ap.parse_args()
    pk, sk, signs, vers = build()
    emit(a.out_full, pk, sk, signs, vers)
    print(f"{a.out_full}: {len(signs)} sign cases, {len(vers)} verify cases")
    print("  L mod 136 of the sign cases:", sorted({s['L'] % RATE for s in signs}), " L range:",
          min(s['L'] for s in signs), "-", max(s['L'] for s in signs))
    if a.out_cosim:
        cs = [s for s in signs if s["label"] in COSIM_SIGN]
        cv = [v for v in vers if v["label"] in COSIM_VER]
        assert len(cs) == len(COSIM_SIGN) and len(cv) == len(COSIM_VER)
        emit(a.out_cosim, pk, sk, cs, cv)
        print(f"{a.out_cosim}: {len(cs)} sign cases, {len(cv)} verify cases (reduced, for RTL cosim)")
