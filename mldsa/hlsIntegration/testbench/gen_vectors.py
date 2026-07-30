#!/usr/bin/env python3
"""
Generate a C++ header of ML-DSA-44 known-answer test vectors for the HLS testbench,
sourced directly from the official NIST ACVP-Server KAT files
(usnistgov/ACVP-Server, gen-val/json-files/ML-DSA-{sigGen,sigVer}-FIPS204).

Run fetch_vectors.sh first to download the raw vectors into ./vectors/, then run this
script; it writes tb_vectors.h next to it. No third-party dependencies (stdlib only).

Selected groups:
  sigVer tgId=1  (external, pure, ML-DSA-44): pk, message, context, signature -> testPassed
      Exercises k_verify's fixed ctx/domain-separation path end-to-end.
  sigGen tgId=7  (internal, deterministic=true,  ML-DSA-44): mu, sk -> signature
      rnd is implicitly all-zero (Algorithm 2 step 5's deterministic substitution) -
      exercises k_sign/dataflow() with the "kept off" default rnd behavior.
  sigGen tgId=19 (internal, deterministic=false, ML-DSA-44): mu, rnd, sk -> signature
      Exercises the new real rnd wiring with genuine hedged values.

--reduced selects one case per structurally distinct code path instead of the full
45 - used for RTL cosimulation, where full-vector csim coverage already exists and
cosim's job is validating the HLS schedule (a structural property), not re-checking
per-value algorithmic correctness:
  sigVer tc12 - valid signature, non-trivial ctx (accept path, ctx fix engaged)
  sigVer tc2  - invalid signature, non-trivial ctx (reject path, ctx fix engaged)
  sigGen      - first deterministic (rnd=0) case + first hedged (real rnd) case

M_AXI_DEPTH["msg"] is the production message-size bound (see README.md's "Known
finding" section), not NIST's own test-vector maximum - any sigVer case whose real
message exceeds it is automatically excluded below (printed, not silently dropped)
rather than padded/truncated, since accepting it would misrepresent what this
configuration actually validates.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VECTORS = ROOT / "vectors"

PARAM_SET = "ML-DSA-44"
REDUCED_VER_TCIDS = (12, 2)  # accept (non-trivial ctx), reject (non-trivial ctx) - both <= 1024 bytes

# Must match the "#pragma HLS INTERFACE m_axi port=... depth=..." values in
# mldsa_accelerator's declaration (k_dsa.cpp). cosim's C-TB post-check reads up to
# `depth` bytes from whatever pointer is passed for that port, REGARDLESS of the
# design's own runtime-supplied length (mlen_in/ctxlen_in) - it's a static,
# compile-time assumption used by the auto-generated cosim harness for its own
# simulated-memory bookkeeping, not something that adapts per call. If a test
# case's real array is shorter than the port's declared depth, cosim reads past
# its end -> SIGSEGV during "C post checking". Padding every buffer up to its
# port's declared depth is required for cosim; harmless for csim (unused past the
# real mlen/ctxlen either way).
#
# "msg" specifically is the production message-size bound, not a value chosen to
# fit NIST's test vectors (see README.md's "Known finding" section) - so unlike
# every other entry here, it can legitimately be smaller than what some official
# vectors need, and those vectors are excluded rather than padded (see skip logic
# in generate()).
M_AXI_DEPTH = {
    "pk": 2600,    # pk_in
    "msg": 1024,   # mu_orig_in - production bound, see README.md "Known finding"
    "ctx": 255,    # ctx_in
    "sig": 2620,   # sign_in / sign_out
    "sk": 2628,    # sk_in
    "mu": 64,      # mu_processed_in / mu2_processed_in (exact match, no real padding needed)
    "rnd": 32,     # rnd_in (exact match, no real padding needed)
}


def pad(data, kind):
    depth = M_AXI_DEPTH[kind]
    if len(data) > depth:
        raise ValueError(f"{kind}: data length {len(data)} exceeds m_axi depth {depth} - "
                          f"bump M_AXI_DEPTH['{kind}'] AND the matching pragma in k_dsa.cpp")
    return data + bytes(depth - len(data))


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def hexbytes(s):
    return bytes.fromhex(s) if s else b""


def index_expected(expected_json, tg_id):
    for g in expected_json["testGroups"]:
        if g["tgId"] == tg_id:
            return {t["tcId"]: t for t in g["tests"]}
    raise KeyError(f"tgId {tg_id} not found in expected results")


def find_group(prompt_json, tg_id):
    for g in prompt_json["testGroups"]:
        if g["tgId"] == tg_id:
            assert g["parameterSet"] == PARAM_SET, (tg_id, g["parameterSet"])
            return g
    raise KeyError(f"tgId {tg_id} not found in prompt")


def c_array(name, data):
    body = ", ".join(f"0x{b:02X}" for b in data)
    return f"static const uint8_t {name}[{len(data)}] = {{{body}}};\n"


def generate(out_path, reduced):
    guard = out_path.stem.upper() + "_H"

    sigver_prompt = load(VECTORS / "ML-DSA-sigVer-FIPS204" / "prompt.json")
    sigver_expected = load(VECTORS / "ML-DSA-sigVer-FIPS204" / "expectedResults.json")
    siggen_prompt = load(VECTORS / "ML-DSA-sigGen-FIPS204" / "prompt.json")
    siggen_expected = load(VECTORS / "ML-DSA-sigGen-FIPS204" / "expectedResults.json")

    ver_group = find_group(sigver_prompt, 1)
    ver_exp = index_expected(sigver_expected, 1)

    gen_det_group = find_group(siggen_prompt, 7)
    gen_det_exp = index_expected(siggen_expected, 7)
    gen_hedge_group = find_group(siggen_prompt, 19)
    gen_hedge_exp = index_expected(siggen_expected, 19)

    if reduced:
        ver_tests = [tc for tc in ver_group["tests"] if tc["tcId"] in REDUCED_VER_TCIDS]
        gen_det_tests = gen_det_group["tests"][:1]
        gen_hedge_tests = gen_hedge_group["tests"][:1]
    else:
        ver_tests = ver_group["tests"]
        gen_det_tests = gen_det_group["tests"]
        gen_hedge_tests = gen_hedge_group["tests"]

    # sigGen cases are unaffected by M_AXI_DEPTH["msg"]: dataflow()/k_sign never has a
    # raw message flow through it (it takes a pre-computed mu), so only sigVer needs
    # this filter. Exclude rather than pad/truncate - see module docstring.
    msg_limit = M_AXI_DEPTH["msg"]
    fits = [tc for tc in ver_tests if len(tc["message"]) // 2 <= msg_limit]
    excluded = [tc for tc in ver_tests if len(tc["message"]) // 2 > msg_limit]
    if excluded:
        print(f"  Excluding {len(excluded)} sigVer case(s) exceeding msg depth ({msg_limit} bytes): "
              + ", ".join(f'tc{tc["tcId"]}({len(tc["message"]) // 2}B)' for tc in excluded))
    ver_tests = fits

    lines = []
    lines.append("// AUTO-GENERATED by gen_vectors.py - do not edit by hand.")
    lines.append("// Source: NIST ACVP-Server (usnistgov/ACVP-Server), gen-val/json-files/")
    lines.append("//   ML-DSA-sigVer-FIPS204 (tgId=1, external/pure, ML-DSA-44)")
    lines.append("//   ML-DSA-sigGen-FIPS204 (tgId=7 deterministic=true, tgId=19 deterministic=false, internal, ML-DSA-44)")
    if reduced:
        lines.append("// --reduced: one case per code path, for RTL cosimulation (see gen_vectors.py docstring)")
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("#include <stdint.h>")
    lines.append("")

    # ---- sigVer cases ----
    ver_entries = []
    for i, tc in enumerate(ver_tests):
        pk = hexbytes(tc["pk"])
        msg = hexbytes(tc["message"])
        ctx = hexbytes(tc["context"])
        sig = hexbytes(tc["signature"])
        expected = ver_exp[tc["tcId"]]["testPassed"]
        # mlen/ctxlen below stay the REAL lengths (what mlen_in/ctxlen_in tells the
        # design); only the underlying buffers are padded, for cosim's benefit - see
        # M_AXI_DEPTH / pad() above.
        lines.append(c_array(f"ver_pk_{i}", pad(pk, "pk")))
        lines.append(c_array(f"ver_msg_{i}", pad(msg, "msg")))
        lines.append(c_array(f"ver_ctx_{i}", pad(ctx, "ctx")))
        lines.append(c_array(f"ver_sig_{i}", pad(sig, "sig")))
        ver_entries.append(
            f'  {{ "sigVer tc{tc["tcId"]}", {tc["tcId"]}, ver_pk_{i}, ver_msg_{i}, {len(msg)}, '
            f'ver_ctx_{i}, {len(ctx)}, ver_sig_{i}, {"true" if expected else "false"} }},'
        )

    lines.append("struct VerCase {")
    lines.append("    const char *label; unsigned tcId;")
    lines.append("    const uint8_t *pk;")
    lines.append("    const uint8_t *msg; unsigned mlen;")
    lines.append("    const uint8_t *ctx; unsigned ctxlen;")
    lines.append("    const uint8_t *sig;")
    lines.append("    bool expected;")
    lines.append("};")
    lines.append("static const VerCase VER_CASES[] = {")
    lines.extend(ver_entries)
    lines.append("};")
    lines.append("#define VER_CASES_COUNT (sizeof(VER_CASES)/sizeof(VER_CASES[0]))")
    lines.append("")

    # ---- sigGen cases (deterministic + hedged) ----
    sign_entries = []
    idx = 0
    for tests, expected_map, is_hedged in (
        (gen_det_tests, gen_det_exp, False),
        (gen_hedge_tests, gen_hedge_exp, True),
    ):
        for tc in tests:
            sk = hexbytes(tc["sk"])
            mu = hexbytes(tc["mu"])
            rnd = hexbytes(tc["rnd"]) if is_hedged else bytes(32)  # off-by-default: all-zero rnd
            sig = hexbytes(expected_map[tc["tcId"]]["signature"])  # not an m_axi pointer arg, no pad needed

            lines.append(c_array(f"sign_sk_{idx}", pad(sk, "sk")))
            lines.append(c_array(f"sign_mu_{idx}", pad(mu, "mu")))
            lines.append(c_array(f"sign_rnd_{idx}", pad(rnd, "rnd")))
            lines.append(c_array(f"sign_sig_{idx}", sig))
            label = f'sigGen tc{tc["tcId"]} ({"hedged" if is_hedged else "deterministic/rnd=0"})'
            sign_entries.append(
                f'  {{ "{label}", {tc["tcId"]}, sign_sk_{idx}, sign_mu_{idx}, sign_rnd_{idx}, sign_sig_{idx} }},'
            )
            idx += 1

    lines.append("struct SignCase {")
    lines.append("    const char *label; unsigned tcId;")
    lines.append("    const uint8_t *sk;")
    lines.append("    const uint8_t *mu;")
    lines.append("    const uint8_t *rnd;")
    lines.append("    const uint8_t *expected_sig;")
    lines.append("};")
    lines.append("static const SignCase SIGN_CASES[] = {")
    lines.extend(sign_entries)
    lines.append("};")
    lines.append("#define SIGN_CASES_COUNT (sizeof(SIGN_CASES)/sizeof(SIGN_CASES[0]))")
    lines.append("")
    lines.append(f"#endif // {guard}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path} ({out_path.stat().st_size} bytes)")
    print(f"  sigVer cases:  {len(ver_entries)}")
    print(f"  sigGen cases:  {len(sign_entries)} ({len(gen_det_tests)} deterministic + {len(gen_hedge_tests)} hedged)")


if __name__ == "__main__":
    generate(ROOT / "tb_vectors.h", reduced=False)
    generate(ROOT / "tb_vectors_cosim.h", reduced=True)
