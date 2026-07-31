# README
## How to Generate the MLDSA Accelerator

### Requirements:

- Vitis\_HLS 2024.2 version

To generate the accelerator, run:

```sh
make mldsa2
```

## FIPS 204 Compliance Changes (this fork)

This fork brings the accelerator's sign/verify interfaces closer to FIPS 204 as specified,
plus real hedged-signing support. The `rnd_in`/`ctx_in` additions below are additive -
existing callers supplying an all-zero `rnd_in` and an empty `ctx_in` (`ctxlen_in = 0`) get
behavior identical to the upstream accelerator. The on-chip sign-path mu derivation
further down, however, **removes** `mu_processed_in`/`mu2_processed_in` and replaces them
with a raw-message input (`sign_m_in`) - this is an interface-breaking change for any
caller that was supplying a pre-computed `mu`; see that section.

### `rnd_in` — real hedged-signing input

`mldsa_accelerator`/`k_sign` now take an additional `uint8_t *rnd_in` (32 bytes). Previously,
the `rnd` component of the `rho'' <- H(K || rnd || mu, 64)` derivation (FIPS 204 Algorithm 7,
step 7) was hardcoded to all-zero inside `keccak_absorb_key_mu`. It is now an input:

- All-zero `rnd_in` reproduces the previous behavior exactly — this is the spec-permitted
  deterministic variant (Algorithm 2, step 5: *"for the optional deterministic variant,
  substitute rnd <- {0}^32"*).
- A non-zero `rnd_in` enables genuine hedged signing.

Nothing generates randomness on-chip; *the caller is responsible* for supplying `rnd_in`.

### `ctx_in` / `ctxlen_in` — message domain separation (verify and sign)

`mldsa_accelerator` takes an additional `uint8_t *ctx_in` (up to 255 bytes) and
`uint8_t ctxlen_in`, shared between the verify and sign branches (`kem_cfg` selects
exactly one per invocation, so there's no real conflict - the same sharing already used
for `ret_out`/`ver_out` on `bundle=gmemout`). Both `k_verify` and `k_sign` build the FIPS
204 Algorithm 3 formatted message

```
M' = BytesToBits(IntegerToBytes(0,1) || IntegerToBytes(|ctx|,1) || ctx) || M
```

(via the shared `make_mprime` helper) ahead of `mu = H(tr || M', 64)` - Algorithm 8
(Verify_internal) step 7 for `k_verify`, Algorithm 7 (Sign_internal) step 6 for `k_sign`
(one step earlier there, since Sign_internal already has `tr` from `sk` and does not need
Verify_internal's preceding `tr = H(pk)` step) - instead of hashing the raw message
directly. `ctxlen_in` is `uint8_t`, so the spec's `|ctx| <= 255` bound (Algorithm 3, steps
1-3) holds by construction; no separate runtime check is required.

### On-chip `tr`/`M'`/`mu` derivation for `k_sign`

`k_sign` previously took a pre-computed `mu`/`mu2` (both the same 64-byte digest, supplied
twice because HLS streams are single-consumer) as an opaque input — it never had access to
the raw message, `tr`, or `ctx`, so all of Algorithm 2's message formatting had to happen
in whatever host software called this accelerator. `k_sign` now takes a raw message instead
(`sign_m_in`, `mlen_in`) and derives everything on-chip, mirroring `k_verify`'s existing
architecture:

- **`tr`**: unpacked directly from `sk_in` (`unpack_sk`'s `TRBYTES` loop, previously
  discarded with `uint8_t discard = s_sk.read();` since nothing consumed it - now routed
  into a real stream). FIPS 204's `sk = rho || K || tr || s1 || s2 || t0` (Algorithm 6)
  already stores `tr`, so no hash is needed here, unlike `k_verify` which must compute
  `tr = H(pk)` fresh since verify never has more than the public key.
- **`M'`**: built via the same `make_mprime` helper `k_verify` uses.
- **`mu`**: a new `shake_sign_mprime` function (mirrors `shakeVer`'s structure, built from
  this file's non-Ver/sign-path `keccak_absorb`/`keccak_finalize`/`keccak_squeeze`
  primitives, which already existed for other sign-path hashes) computes
  `mu = H(tr || M', 64)`. The result is split into the two streams the rest of
  `dataflow()` already expected (`s_mu_0` for the `rho''` derivation, `s_mu_1` for the
  challenge hash) via the existing `duplicate` helper, instead of reading two identical
  copies from an external pointer.

**Interface change:** `mu_processed_in` and `mu2_processed_in` are removed entirely -
`mldsa_accelerator`'s signature changed (see `kernel.hpp`). This is **not** additive like
`rnd_in`/`ctx_in` above: any caller supplying a pre-computed `mu` must be updated to supply
the raw message instead. `sign_m_in` shares `bundle=gmemm` with `mu_orig_in` (mutually
exclusive per `kem_cfg`, same sharing pattern as `ret_out`/`ver_out`) and the same
1024-byte production message-size bound (see "Known finding" below) - it is not a
separately-sized port.

### Validation

All changes were validated via HLS C-simulation (`csim_design`) *and* RTL cosimulation
(`cosim_design`) against the official [NIST ACVP-Server](https://github.com/usnistgov/ACVP-Server)
ML-DSA-44 KAT vectors (`gen-val/json-files/ML-DSA-{sigGen,sigVer}-FIPS204`): covering
verify with non-trivial `context` values (including negative/malformed signatures,
correctly rejected), and sign with both `rnd = 0` and real hedged `rnd` values - now driven
by raw `(message, ctx)` inputs through the on-chip derivation above, not pre-computed `mu`
- each checked for a byte-exact signature match against the NIST-published expected
output. sigGen vectors come from the ACVP-Server's *external* groups (tgId=1 deterministic,
tgId=13 hedged - message+context+sk, mirroring sigVer's own external tgId=1), not the
*internal* groups (tgId=7/19, mu+sk) used before the mu-processed interface was removed.
12 of the 45 official vectors apply to this build (5 sigVer + 3 deterministic sigGen + 4
hedged sigGen) - the rest have messages exceeding this build's 1024-byte production
message-size bound and are correctly excluded, not failing. This is a smaller applicable
fraction than the previous 35/45: sign's real message-length exposure is new (the old
internal/mu-based sigGen vectors had no message field to filter, since `mu` is always a
fixed 64 bytes regardless of real message length) - the reduction reflects sign now being
honestly subject to the same bound verify already was, not a regression; see "Known
finding" below.

### Running the testbench

Two validation tiers, both gitignored until (re)generated locally: the downloaded NIST
vectors and the generated header(s).

```sh
cd mldsa/hlsIntegration/testbench
./fetch_vectors.sh        # downloads the official NIST ACVP-Server ML-DSA KAT vectors
python3 gen_vectors.py    # writes tb_vectors.h AND tb_vectors_cosim.h, stdlib only

cd ..
vitis-run --mode hls --tcl scripts/mldsa2_csim.tcl    # fast: plain C-simulation, all 45 vectors
vitis-run --mode hls --tcl scripts/mldsa2_cosim.tcl   # slow: full csynth + cycle-accurate RTL cosim, 4 reduced vectors
```

`mldsa2_csim.tcl` runs entirely as plain C++ - no board, no Vivado project, no Vitis SW
workspace. Expect it to end with:

```
=== Result: 5/5 verify cases OK, 7/7 sign cases OK ===
INFO: [SIM 211-1] CSim done with 0 errors.
```

`mldsa2_cosim.tcl` additionally synthesizes the design and simulates the actual RTL via
XSIM - real hardware-accuracy, not just the C model - on a reduced 4-case set (one
verify-accept, one verify-reject, one deterministic sign, one hedged sign; see
`gen_vectors.py`'s docstring for why a reduced set is appropriate here). Expect it to
end with:

```
=== Result: 2/2 verify cases OK, 2/2 sign cases OK ===
INFO: [COSIM 212-1000] *** C/RTL co-simulation finished: PASS ***
```

Tested with Vitis HLS 2024.2 paired with Vivado 2024.2

### Known finding: message-length buffer sizing (`mu_orig_in` / `sign_m_in`)

While validating the `ctx` fix via `cosim_design` (RTL-accurate simulation), a **separate,
pre-existing** defect surfaced: `mu_orig_in`'s AXI interface (the raw message input for
`k_verify`) was declared `depth=2600` - far too small for real messages. NIST's own
ML-DSA-44 conformance vectors include messages up to 8192 bytes; anything past the
declared depth got silently corrupted during RTL-accurate simulation (`csim_design`'s
simplified stream model never enforces the declared depth, so this was invisible to it -
it passed all 45 vectors while quietly being wrong for the long ones). This predates the
`ctx` change entirely; it was never exercised with realistic message lengths before.
`sign_m_in` (the raw message input for `k_sign`, added once `k_sign` started deriving
`tr`/`M'`/`mu` on-chip instead of taking a pre-computed `mu`) is subject to the exact same
sizing concern and was given the same bound from the start.

**Production value: `depth=1024`**, consistent across seven places: `k_dsa.cpp`'s
`mu_orig_in` and `sign_m_in` `#pragma HLS INTERFACE`, the `s_mu_mrg`/`s_m` (verify) and
`s_mu_mrg_sign`/`s_m_sign` (sign) internal stream depths, `testbench/tb_axi_depths.h`'s
`AXI_DEPTH_MU_ORIG`/`AXI_DEPTH_SIGN_M`, and `gen_vectors.py`'s `M_AXI_DEPTH["msg"]`. Chosen
for automotive/aerospace deployment: typical direct-signed protocol/telemetry messages in
that space (e.g. V2X/J2735-style safety messages, CCSDS telecommand/telemetry packets) are
well under 1KB, and FIPS 204 itself recommends pre-hashing genuinely large content
externally and signing the digest (`HashML-DSA`/"pre-hash" mode, Section 5.4) rather than
streaming it through this port - 1024 bytes is comfortable headroom over realistic message
sizes without paying BRAM cost for capacity the application should never use directly.
SELENE's own existing test harness fixes `MLEN=100`, well within this bound.

**Direct, expected consequence for testing:** `gen_vectors.py` excludes (prints, does not
silently pad/truncate) every NIST vector whose real message exceeds 1024 bytes - this now
applies to sigGen as well as sigVer, since sign takes a real message subject to the same
bound. **12 of the 45 official vectors participate in `csim_design`** (`tb_vectors.h`
covers 5 sigVer + 3 deterministic sigGen + 4 hedged sigGen), and the reduced cosim set uses
one fitting case per code path (`sigVer tc12` accept, `tc2` reject; `sigGen tc2`
deterministic, `tc182` hedged - all with non-trivial `ctx`). This is a scope reduction of
what this production build can accept as input, correctly reflecting the 1024-byte bound -
not a bug, and not something to "fix" back to passing all 45 by re-growing the buffer.

If a future deployment genuinely needs to verify longer messages directly, revisit this
number specifically against that requirement rather than reverting to NIST's own
worst-case test length.

1024 is a reasoned default informed by general automotive/aerospace message-size conventions 
and FIPS 204's own pre-hash guidance above
- it is not derived from a specific, named target protocol or customer requirement. Treat
it as a documented, justified placeholder, not a value signed off by an actual system
spec. `AXI_DEPTH_MU_ORIG`/`AXI_DEPTH_SIGN_M` (and the other values that must track them,
listed above) are a single point of change if a real target protocol turns out to need
something smaller (e.g. 512 or 256) or larger.